"""Find demo companies whose matching upcoming tenders actually have a high single-bid risk.

    python find_demo.py                      # all of France
    python find_demo.py --idf                # Île-de-France only
    python find_demo.py --min-risk 0.4       # what counts as "little competition" (default 0.35)

Matching = same 4-digit CPV class AND a département where the company has won at least twice.
"""
import argparse
import sys

sys.path.insert(0, "src")
import pandas as pd  # noqa: E402

IDF = ["75", "77", "78", "91", "92", "93", "94", "95"]

ap = argparse.ArgumentParser()
ap.add_argument("--idf", action="store_true")
ap.add_argument("--min-risk", type=float, default=0.35)
ap.add_argument("--since", default="2025-01-01", help="company must have won since this date")
a = ap.parse_args()

aw = pd.read_parquet("data/clean/awards.parquet")
from profiles import load_all_scored  # noqa: E402
sc = load_all_scored()
if "cpv_cls" not in aw or "cpv_cls" not in sc:
    sys.exit("cpv_cls missing: rerun python src/prepare.py, python src/profiles.py and python src/score.py first")

stats = aw.groupby("company_siren").agg(n_wins=("id", "size"), last_win=("date", "max"))
stats = stats[stats["n_wins"].between(10, 200) & (stats["last_win"] >= a.since)]
w = aw[aw["company_siren"].isin(stats.index) & (aw["cpv_cls"] != "NA") & (aw["dept"] != "NA")]
pairs = w.groupby(["company_siren", "cpv_cls", "dept"]).size().rename("wins_here").reset_index()
pairs = pairs[pairs["wins_here"] >= 2]
if a.idf:
    pairs = pairs[pairs["dept"].isin(IDF)]

up = sc[(sc["cpv_cls"] != "NA") & (sc["dept"] != "NA")][["cpv_cls", "dept", "proba", "libelle", "source"]]
m = pairs.merge(up, on=["cpv_cls", "dept"])
res = m.groupby("company_siren").agg(
    tenders=("proba", "size"),
    high_risk=("proba", lambda s: int((s >= a.min_risk).sum())),
    max_risk=("proba", "max"),
    open_now=("source", lambda s: int((s == "BOAMP").sum())),
    main_class=("cpv_cls", lambda s: s.mode().iloc[0]),
    main_dept=("dept", lambda s: s.mode().iloc[0]),
).join(stats)
if "titulaire_nom" in aw:
    res = res.join(aw.dropna(subset=["titulaire_nom"]).groupby("company_siren")["titulaire_nom"].first().rename("name"))
res = res[res["high_risk"] >= 2].sort_values(["high_risk", "max_risk"], ascending=False)
res["max_risk"] = (100 * res["max_risk"]).round().astype(int).astype(str) + " %"

eligible = pairs["company_siren"].nunique()
print(f"{len(res):,} of {eligible:,} active companies ({len(res) / max(eligible, 1):.0%}) have ≥ 2 matching "
      f"upcoming tenders at risk ≥ {a.min_risk:.0%}  ← say this number when you present the demo company\n")
print(res.head(25).reset_index().to_string(index=False))
print("\nNext: check one on annuaire-entreprises.data.gouv.fr (PME?), then: python check_fit.py <siren>")
