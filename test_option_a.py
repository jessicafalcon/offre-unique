"""Option A check: are the riskiest upcoming purchases convincing buyer-side examples?

    python test_option_a.py
"""
import pandas as pd

s = pd.read_parquet("data/clean/scored.parquet")
s = s[s["proba"].notna()].sort_values("proba", ascending=False)
avg = s["proba"].mean()
print(f"{len(s):,} upcoming purchases, average predicted risk {avg:.0%}")
for t in (0.4, 0.5, 0.6):
    print(f"  risk ≥ {t:.0%}: {(s['proba'] >= t).sum():,}")

print("\nBuyers with the most high-risk (≥ 50 %) purchases:")
hi = s[s["proba"] >= 0.5]
print(hi.groupby(hi["buyer_name"].fillna(hi["buyer_siren"]))["proba"].size().sort_values(ascending=False).head(8).to_string())

out = pd.DataFrame({
    "risk": (100 * s["proba"]).round().astype(int).astype(str) + " %",
    "buyer": s["buyer_name"].fillna(s["buyer_siren"]).astype(str).str.slice(0, 35),
    "past comparable": s["hist_n"].fillna(0).astype(int),
    "of which 1 bid": (100 * s["hist_single_share"]).round().map(lambda v: "" if pd.isna(v) else f"{int(v)} %"),
    "title": s["libelle"].astype(str).str.slice(0, 70),
})
print("\nTop 20 (check: varied buyers? titles a judge understands? backed by real history?)")
print(out.head(20).to_string(index=False))
