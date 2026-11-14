"""How many active companies get at least one "Aller" tender, with the app's own matching and rules.

    python coverage.py            # Île-de-France, then all of France -> artifacts/coverage.json

Active company (same definition as find_demo.py): 10–200 public contracts won, at least one since 2025-01-01,
and at least 2 wins in the same 4-digit CPV class and département (in Île-de-France for the IDF figure).
"""
import json
import sys
import time

sys.path.insert(0, "src")
import pandas as pd  # noqa: E402

from common import ART, TODAY  # noqa: E402
from explain import _avg_rate, recommend  # noqa: E402
from profiles import fit_table, load_all_scored, profile_of, relevant  # noqa: E402

IDF = {"75", "77", "78", "91", "92", "93", "94", "95"}

aw = pd.read_parquet("data/clean/awards.parquet")
sc = load_all_scored()
avg = _avg_rate()
stats = aw.groupby("company_siren").agg(n_wins=("id", "size"), last_win=("date", "max"))
stats = stats[stats["n_wins"].between(10, 200) & (stats["last_win"] >= "2025-01-01")]
w = aw[aw["company_siren"].isin(stats.index) & (aw["cpv_cls"] != "NA") & (aw["dept"] != "NA")]
pairs = w.groupby(["company_siren", "cpv_cls", "dept"]).size().rename("k").reset_index()
pairs = pairs[pairs["k"] >= 2]
by_company = {s: g for s, g in aw[aw["company_siren"].isin(set(pairs["company_siren"]))].groupby("company_siren")}


def hs(v):
    return None if pd.isna(v) else float(v)


def count(siren: str) -> tuple[int, int, int]:
    a = by_company[siren]
    prof = profile_of(a, siren)
    t = relevant(fit_table(prof, sc, a))
    if t.empty:
        return 0, 0, 0
    n_aller = n_open = 0
    for r in t.itertuples():
        inc = str(r.incumbent_siren or "").replace(".0", "")[:9] == siren
        reco = recommend(r.proba, avg, int(r.n_match_dept), hs(r.hist_single_share), inc,
                         0 if inc else int(r.incumbent_streak or 0))[0]
        if reco == "Aller":
            n_aller += 1
            n_open += int(r.source == "BOAMP" and pd.notna(r.due_date) and r.due_date >= TODAY)
    return len(t), n_aller, n_open


out = {"date": str(TODAY.date()), "definition": __doc__.strip().splitlines()[-2:], "regions": {}}
for region, sirens in (("Île-de-France", pairs[pairs["dept"].isin(IDF)]["company_siren"].unique()),
                       ("France", pairs["company_siren"].unique())):
    t0, rows = time.time(), []
    for i, s in enumerate(sirens):
        rows.append((s, *count(s)))
        if i % 1000 == 0:
            print(f"  {region}: {i:,}/{len(sirens):,} ({time.time() - t0:.0f}s)", flush=True)
    d = pd.DataFrame(rows, columns=["siren", "n_tenders", "n_aller", "n_aller_open"])
    res = {"companies": int(len(d)),
           "with_aller": int((d["n_aller"] >= 1).sum()),
           "with_aller_open": int((d["n_aller_open"] >= 1).sum()),
           "with_any_tender": int((d["n_tenders"] >= 1).sum()),
           "median_tenders": float(d["n_tenders"].median())}
    res["share_with_aller"] = res["with_aller"] / max(res["companies"], 1)
    res["share_with_aller_open"] = res["with_aller_open"] / max(res["companies"], 1)
    out["regions"][region] = res
    print(region, json.dumps(res, ensure_ascii=False), flush=True)
    (ART / "coverage.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
