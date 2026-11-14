"""Experiment B: does title similarity find a company's tenders better than CPV codes alone?

    python experiments/matching_recall.py [--companies 300] [--dims 128]

Backtest on DECP. For a random sample of companies with >= 5 wins in 2023-2025 and >= 3 wins in
2026, the profile is built from the 2023-2025 wins only, and the "tenders" are all 2026 contracts.
A method is good if the contracts the company really won in 2026 come out near the top of its list.

    rules        Jessica's matching (profiles.fit_table + relevant), ordered by her fit score
    rules+emb    the same selection, re-ordered by title similarity to the company's past wins
    emb          title similarity over all 2026 contracts in the départements where it has won
    emb+cpv2     title similarity, restricted to the CPV divisions where it has won

Similarity = max cosine between a tender title and the company's past win titles (embeddings from
embed_titles.py, first `dims` dimensions). Metrics, averaged over companies: recall@20/50/100 (share
of its 2026 wins found in the first K) and, for "rules", the size and recall of the whole selection.
Caveat: here the pool is every 2026 contract (much larger than the app's ~10k open tenders), and a
contract the company did not win is not necessarily irrelevant; recall is the fair comparison.
Writes experiments/results/matching_recall.json and .md.
"""
from __future__ import annotations

import argparse
import gc
import json
import time

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from _shared import CACHE, RESULTS, guard
from common import CLEAN, MIN_YEAR
from embed_titles import title_key
from profiles import fit_table, profile_of, relevant

COLS = ["company_siren", "acheteur_id", "id", "objet", "cpv_div", "cpv_grp", "cpv_cls", "dept", "amount_band",
        "categorie", "titulaire_nom", "date", "year", "buyer_siren"]
KS = (20, 50, 100)
EVAL_YEAR = 2026


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--companies", type=int, default=300)
    ap.add_argument("--dims", type=int, default=128)
    a = ap.parse_args()
    t0 = time.time()

    aw = pq.read_table(CLEAN / "awards.parquet", columns=COLS, filters=[("year", ">=", MIN_YEAR)]).to_pandas()
    aw["key"] = aw["acheteur_id"].astype(str) + "|" + aw["id"].astype(str)
    past, now = aw[aw["year"] < EVAL_YEAR], aw[aw["year"] == EVAL_YEAR]
    del aw
    print(f"awards {MIN_YEAR}-{EVAL_YEAR - 1}: {len(past):,} · {EVAL_YEAR}: {len(now):,} · mem {guard('load'):.2f} GB", flush=True)

    # Pool of "tenders" = distinct 2026 contracts
    pool = now.drop_duplicates("key").drop(columns=["company_siren", "titulaire_nom"]).reset_index(drop=True)
    n_past, n_now = past["company_siren"].value_counts(), now["company_siren"].value_counts()
    eligible = sorted(set(n_past[n_past >= 5].index) & set(n_now[n_now >= 3].index))
    rng = np.random.default_rng(0)
    sample = list(rng.choice(eligible, size=min(a.companies, len(eligible)), replace=False))
    print(f"pool {len(pool):,} contracts · {len(eligible):,} eligible companies · sample {len(sample)}", flush=True)

    # Embeddings for pool titles and past win titles
    emb = np.load(CACHE / "emb_titles.npy", mmap_mode="r")
    idx = pd.read_parquet(CACHE / "emb_titles.parquet").set_index("key")["row"]

    def vecs(titles: pd.Series) -> np.ndarray:
        rows = title_key(titles).map(idx).fillna(-1).astype(int).to_numpy()
        v = np.zeros((len(rows), a.dims), dtype=np.float32)
        ok = rows >= 0
        v[ok] = emb[rows[ok], :a.dims].astype(np.float32)
        v[ok] /= np.linalg.norm(v[ok], axis=1, keepdims=True) + 1e-12
        return v

    P = vecs(pool["objet"])
    print(f"pool vectors {P.shape} · mem {guard('pool emb'):.2f} GB", flush=True)
    pool_pos = pd.Series(np.arange(len(pool)), index=pool["key"])
    past_s = past[past["company_siren"].isin(sample)]
    now_s = now[now["company_siren"].isin(sample)]
    del past, now
    gc.collect()

    def recall_at(ranked_keys: list[str], won: set[str]) -> dict:
        return {f"r@{k}": len(won & set(ranked_keys[:k])) / len(won) for k in KS}

    rows = []
    for i, s in enumerate(sample):
        w_past = past_s[past_s["company_siren"] == s]
        won = set(now_s.loc[now_s["company_siren"] == s, "key"])
        prof = profile_of(w_past, s)

        # rules: Jessica's matching on the 2026 pool
        sel = relevant(fit_table(prof, pool, w_past))
        sel_keys = sel.sort_values(["fit", "n_match"], ascending=False)["key"].tolist()
        r = {"siren": s, "n_won": len(won), "rules_size": len(sel_keys),
             "rules_recall_all": len(won & set(sel_keys)) / len(won)}
        r.update({f"rules_{k}": v for k, v in recall_at(sel_keys, won).items()})

        # similarity of each pool contract to the company's past wins (max cosine)
        W = vecs(w_past["objet"].drop_duplicates())
        sim = np.full(len(pool), -1.0, dtype=np.float32)
        for j in range(0, len(pool), 50_000):
            sim[j:j + 50_000] = (P[j:j + 50_000] @ W.T).max(axis=1)

        # rules+emb: same selection, re-ordered by similarity
        sel_pos = pool_pos[sel_keys].to_numpy()
        reord = [sel_keys[j] for j in np.argsort(-sim[sel_pos], kind="stable")]
        r.update({f"rules+emb_{k}": v for k, v in recall_at(reord, won).items()})

        # emb: départements where it has won
        depts = set(w_past["dept"].astype(str)) - {"NA", "nan", ""}
        cand = np.flatnonzero(pool["dept"].astype(str).isin(depts).to_numpy()) if depts else np.arange(len(pool))
        order = cand[np.argsort(-sim[cand])]
        r.update({f"emb_{k}": v for k, v in recall_at(pool["key"].to_numpy()[order[:max(KS)]].tolist(), won).items()})

        # emb+cpv2: CPV divisions where it has won (any département)
        divs = set(w_past["cpv_div"].astype(str)) - {"NA"}
        cand = np.flatnonzero(pool["cpv_div"].astype(str).isin(divs).to_numpy())
        order = cand[np.argsort(-sim[cand])]
        r.update({f"emb+cpv2_{k}": v for k, v in recall_at(pool["key"].to_numpy()[order[:max(KS)]].tolist(), won).items()})
        rows.append(r)
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(sample)} companies · {time.time() - t0:.0f}s · mem {guard('loop'):.2f} GB", flush=True)

    df = pd.DataFrame(rows)
    methods = ["rules", "rules+emb", "emb", "emb+cpv2"]
    summary = {m: {f"r@{k}": float(df[f"{m}_r@{k}"].mean()) for k in KS} for m in methods}
    summary["rules"].update({"selection_size_median": float(df["rules_size"].median()),
                             "recall_whole_selection": float(df["rules_recall_all"].mean())})
    # paired comparison vs rules at K=50: share of companies better / worse
    for m in methods[1:]:
        d = df[f"{m}_r@50"] - df["rules_r@50"]
        summary[m]["vs_rules_r@50"] = {"better": float((d > 0).mean()), "worse": float((d < 0).mean()),
                                       "mean_diff": float(d.mean())}
    out = {"eval_year": EVAL_YEAR, "pool_size": int(len(pool)), "companies": len(df), "dims": a.dims,
           "median_wins_in_eval_year": float(df["n_won"].median()), "summary": summary}
    (RESULTS / "matching_recall.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    df.to_csv(RESULTS / "matching_recall_companies.csv", index=False)

    lines = ["| Méthode | Rappel @20 | Rappel @50 | Rappel @100 | Mieux / moins bien que les règles (@50) |",
             "|---|---|---|---|---|"]
    for m in methods:
        s = summary[m]
        vs = s.get("vs_rules_r@50")
        lines.append(f"| {m} | {100 * s['r@20']:.1f} % | {100 * s['r@50']:.1f} % | {100 * s['r@100']:.1f} % | "
                     + (f"{100 * vs['better']:.0f} % / {100 * vs['worse']:.0f} %" if vs else "–") + " |")
    lines.append(f"\nRègles : sélection médiane de {summary['rules']['selection_size_median']:.0f} contrats, "
                 f"qui contient {100 * summary['rules']['recall_whole_selection']:.1f} % des marchés gagnés en {EVAL_YEAR}.")
    (RESULTS / "matching_recall.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
