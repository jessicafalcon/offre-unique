"""Do the tenders shown for a company fit its trade?   python check_fit.py 753310598"""
import sys
sys.path.insert(0, "src")
import pandas as pd
from profiles import fit_table, profile_of, relevant

SIREN = sys.argv[1] if len(sys.argv) > 1 else "753310598"
aw = pd.read_parquet("data/clean/awards.parquet")
from profiles import load_all_scored
sc = load_all_scored()
c = pd.read_parquet("data/clean/contracts.parquet", columns=["acheteur_id", "id", "codecpv"])

mine = aw[aw.company_siren == SIREN].merge(c, on=["acheteur_id", "id"], how="left")
mine["cpv4"] = mine.codecpv.astype(str).str.extract(r"(\d{4})")[0]
print("== What the company has won: top CPV classes (4 digits) ==")
print(mine.cpv4.value_counts().head(8).to_string())
print("\n== Its 8 most recent wins ==")
print(mine.sort_values("date", ascending=False).objet.astype(str).str.slice(0, 100).head(8).to_string(index=False))

t = relevant(fit_table(profile_of(aw, SIREN), sc, aw)).sort_values("proba", ascending=False)
t["cpv4"] = t["cpv_cls"].astype(str)
print(f"matching level: {t['match_level'].iloc[0] if len(t) else 'none'}")
road = (r"voirie|chauss|trottoir|\broutes?\b|\brues?\b|espaces? publics?|enrob|assainissement|\bVRD\b"
        r"|terrassement|pavage|\bplaces?\b|parvis|carrefour|piste cyclable|réseaux?")
t["roads_kw"] = t.libelle.astype(str).str.contains(road, case=False, regex=True)
t["same_cpv4"] = t.cpv4.isin(set(mine.cpv4.dropna()))
print(f"\n== {len(t)} tenders the app shows for this company ==")
print(f"title mentions roads/public space: {int(t.roads_kw.sum())}   |   "
      f"same 4-digit CPV class as one of its past wins: {int(t.same_cpv4.sum())}\n")
out = pd.DataFrame({"risk %": (100 * t.proba).round().astype(int), "type": t["source"].map({"BOAMP": "open", "APProch": "project"}), "cpv4": t.cpv4,
                    "roads": t.roads_kw.map({True: "yes", False: ""}),
                    "same class": t.same_cpv4.map({True: "yes", False: ""}),
                    "title": t.libelle.astype(str).str.slice(0, 85)})
print(out.to_string(index=False))
