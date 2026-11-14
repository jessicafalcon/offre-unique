"""Experiment A: does the contract title improve the single-bid model? Measured on Jessica's exact setup.

    python experiments/text_auc.py [--reps 100]

Same rows, time split (train < SPLIT_YEAR, test >= SPLIT_YEAR), target encoding (train.encode) and
LightGBM settings (train.fit_model) as src/train.py. Only extra features change:

    base         Jessica's features (reproduces metrics.json)
    tfidf        + text_rate: out-of-fold logistic regression on hashed TF-IDF word 1-2 grams of the title (local, free)
    emb_rate     + emb_rate:  out-of-fold logistic regression on the title embedding (Featherless)
    emb_dims     + the first 32 embedding dimensions as raw features
    tfidf+emb    + text_rate + emb_rate

Each is run for the main model and the BOAMP variant (no amount, duration or clauses).
The "+X" features are built without leakage: out-of-fold on the train years, and for the test
years from a model fitted on the train years only.
Gain significance: paired bootstrap of the AUC difference vs base, resampling *buyers* (contracts
of the same buyer are correlated), `--reps` times.
Writes experiments/results/text_auc.json and text_auc.md. Nothing in artifacts/ is touched.
"""
from __future__ import annotations

import argparse
import gc
import json
import time

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import HashingVectorizer, TfidfTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import KFold

from _shared import CACHE, RESULTS, guard, mem_gb
from common import CAT_FEATURES, CLEAN, EXCLUDED_PROCEDURES, FEATURES, MIN_YEAR, SPLIT_YEAR, TODAY
from embed_titles import title_key
from train import VARIANTS, encode, fit_model, scores, to_model_frame

COLS = ["objet", "year", "valid_label", "procedure_c", "single_bid", "buyer_siren", "cpv_div", "cpv_grp",
        "categorie", "amount_band", "duration_bin", "dept", "clause_sociale", "clause_env"]


def load_labelled() -> pd.DataFrame:
    """Same filter as train.main(), reading only the needed columns."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    # Row filters pushed into the parquet read, so the 1.8M-row table is never fully in memory
    t = pq.read_table(CLEAN / "contracts.parquet", columns=COLS,
                      filters=[("valid_label", "==", True), ("year", ">=", MIN_YEAR), ("year", "<=", TODAY.year)])
    lab = t.to_pandas()
    del t
    lab = lab[~lab["procedure_c"].isin(EXCLUDED_PROCEDURES)].copy()
    pa.default_memory_pool().release_unused()
    lab["single_bid"] = lab["single_bid"].astype(int)
    lab["buyer_siren"] = lab["buyer_siren"].fillna("NA")
    for col in CAT_FEATURES:
        lab[col] = lab[col].astype(str)
    return lab.reset_index(drop=True)


def oof_logreg(X_train, y_train, X_test, C: float, k: int = 5, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Out-of-fold predictions on train, and predictions on test from a fit on all of train."""
    oof = np.zeros(X_train.shape[0])
    for tr, va in KFold(k, shuffle=True, random_state=seed).split(oof):
        m = LogisticRegression(C=C, max_iter=300, solver="liblinear")
        m.fit(X_train[tr], y_train[tr])
        oof[va] = m.predict_proba(X_train[va])[:, 1]
    m = LogisticRegression(C=C, max_iter=300, solver="liblinear").fit(X_train, y_train)
    return oof, m.predict_proba(X_test)[:, 1]


def cluster_bootstrap(y, p_base, p_new, groups, reps: int, seed: int = 0) -> dict:
    """Paired bootstrap of AUC(new) - AUC(base), resampling buyers with replacement."""
    rng = np.random.default_rng(seed)
    codes, g = np.unique(groups, return_inverse=True)
    diffs = []
    for _ in range(reps):
        w = rng.multinomial(len(codes), np.full(len(codes), 1 / len(codes)))[g]
        keep = w > 0
        diffs.append(roc_auc_score(y[keep], p_new[keep], sample_weight=w[keep])
                     - roc_auc_score(y[keep], p_base[keep], sample_weight=w[keep]))
    d = np.array(diffs)
    return {"diff_mean": float(d.mean()), "ci95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
            "share_positive": float((d > 0).mean())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=100)
    a = ap.parse_args()
    t0 = time.time()

    lab = load_labelled()
    train_idx = np.flatnonzero(lab["year"].to_numpy() < SPLIT_YEAR)
    test_idx = np.flatnonzero(lab["year"].to_numpy() >= SPLIT_YEAR)
    categories = {col: sorted(lab[col].unique().tolist()) for col in CAT_FEATURES}
    y_tr = lab["single_bid"].to_numpy()[train_idx]
    print(f"labelled {len(lab):,} · train {len(train_idx):,} · test {len(test_idx):,} · mem {guard('load'):.2f} GB", flush=True)

    keys = title_key(lab["objet"])
    extra = pd.DataFrame(index=lab.index)

    # ---- TF-IDF of the title -> out-of-fold logistic regression
    # Hashed word 1-2 grams (fixed memory, no vocabulary to hold), IDF weights from the train years only
    hv = HashingVectorizer(ngram_range=(1, 2), n_features=2 ** 20, alternate_sign=False, norm=None,
                           strip_accents="unicode", dtype=np.float32)
    tf = TfidfTransformer(sublinear_tf=True)
    Xtr = tf.fit_transform(hv.transform(keys.iloc[train_idx]))
    Xte = tf.transform(hv.transform(keys.iloc[test_idx]))
    oof, te = oof_logreg(Xtr, y_tr, Xte, C=1.0)
    extra.loc[train_idx, "text_rate"], extra.loc[test_idx, "text_rate"] = oof, te
    del Xtr, Xte, hv, tf
    gc.collect()
    print(f"tfidf feature done · {time.time() - t0:.0f}s · mem {guard('tfidf'):.2f} GB", flush=True)

    # ---- Title embeddings (if embed_titles.py has run)
    have_emb = (CACHE / "emb_titles.npy").exists()
    if have_emb:
        emb = np.load(CACHE / "emb_titles.npy", mmap_mode="r")
        idx = pd.read_parquet(CACHE / "emb_titles.parquet").set_index("key")["row"]
        rows = keys.map(idx)
        missing = int(rows.isna().sum())
        rows = rows.fillna(-1).astype(int).to_numpy()
        E = np.zeros((len(lab), 64), dtype=np.float32)
        ok = rows >= 0
        E[ok] = emb[rows[ok], :64].astype(np.float32)   # Matryoshka: first 64 dims carry most of the signal
        E[ok] /= np.linalg.norm(E[ok], axis=1, keepdims=True) + 1e-12
        print(f"embeddings: {missing:,} titles without a vector", flush=True)
        oof, te = oof_logreg(E[train_idx], y_tr, E[test_idx], C=1.0)
        extra.loc[train_idx, "emb_rate"], extra.loc[test_idx, "emb_rate"] = oof, te
        for j in range(32):
            extra[f"emb_{j:02d}"] = E[:, j]
        del E, emb
        gc.collect()
        print(f"embedding features done · {time.time() - t0:.0f}s · mem {guard('emb'):.2f} GB", flush=True)

    # ---- Jessica's encoding, then each variant
    lab = pd.concat([lab.drop(columns=["objet"]), extra], axis=1)
    del extra, keys
    train_e, (test_e,), _ = encode(lab.iloc[train_idx], [lab.iloc[test_idx]])
    del lab
    gc.collect()
    y = test_e["single_bid"].to_numpy()
    groups = test_e["buyer_siren"].astype(str).to_numpy()

    emb_dims = [f"emb_{j:02d}" for j in range(32)]
    extras = {"base": [], "tfidf": ["text_rate"]}
    if have_emb:
        extras.update({"emb_rate": ["emb_rate"], "emb_dims": emb_dims, "tfidf+emb": ["text_rate", "emb_rate"]})

    results = {}
    for variant in ("main", "boamp"):
        feats0, _ = VARIANTS[variant]
        preds = {}
        for name, add in extras.items():
            feats = feats0 + add
            m = fit_model(to_model_frame(train_e, categories, feats), train_e["single_bid"])
            preds[name] = m.predict_proba(to_model_frame(test_e, categories, feats))[:, 1]
            r = scores(y, preds[name])
            if name != "base":
                r["vs_base"] = cluster_bootstrap(y, preds["base"], preds[name], groups, a.reps)
            imp = pd.Series(m.booster_.feature_importance("gain"), index=feats)
            r["importance_of_added"] = round(float(imp[add].sum() / imp.sum()), 4) if add else 0.0
            results[f"{variant}/{name}"] = r
            ci = r.get("vs_base", {}).get("ci95")
            print(f"{variant:5} {name:9} AUC {r['auc']:.4f}  top10 {r['precision_top10']:.3f}"
                  + (f"  ΔAUC {r['vs_base']['diff_mean']:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}]" if ci else "")
                  + f"  · {time.time() - t0:.0f}s · mem {guard(name):.2f} GB", flush=True)
            del m
            gc.collect()

    out = {"split_year": SPLIT_YEAR, "n_train": int(len(train_idx)), "n_test": int(len(test_idx)),
           "test_single_bid_rate": float(y.mean()), "bootstrap_reps": a.reps, "bootstrap_unit": "buyer",
           "results": results, "peak_note": f"mem at end {mem_gb():.2f} GB"}
    (RESULTS / "text_auc.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))

    lines = ["| Modèle | Variante | AUC | Δ AUC vs base [IC 95 %] | Offres uniques dans le top 10 % | Brier | Poids du nouveau critère |",
             "|---|---|---|---|---|---|---|"]
    for k, r in results.items():
        v, n = k.split("/")
        d = r.get("vs_base")
        ds = f"{d['diff_mean']:+.4f} [{d['ci95'][0]:+.4f} ; {d['ci95'][1]:+.4f}]" if d else "–"
        lines.append(f"| {v} | {n} | {r['auc']:.4f} | {ds} | {100 * r['precision_top10']:.1f} % | {r['brier']:.4f} "
                     f"| {100 * r['importance_of_added']:.0f} % |")
    (RESULTS / "text_auc.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
