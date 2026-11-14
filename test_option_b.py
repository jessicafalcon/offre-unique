"""Option B check: can BOAMP open tenders replace or extend APProch? Free, no key.

    python test_option_b.py
Reads 100 notices with a response deadline from today on, then reports what the model would need:
CPV codes, département, buyer SIRET, deadline, amount.
"""
import json
import re
from collections import Counter

import pandas as pd
import requests

URL = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records"
today = pd.Timestamp.today().strftime("%Y-%m-%d")

r = requests.get(URL, params={"where": f"datelimitereponse >= date'{today}'", "limit": 100,
                              "order_by": "dateparution desc"}, timeout=60)
print(f"HTTP {r.status_code}")
if r.status_code != 200:
    print(r.text[:600])
    raise SystemExit("Paste this output to Claude.")
payload = r.json()
rows = payload.get("results", [])
print(f"open notices (deadline ≥ {today}): {payload.get('total_count')}  (APProch upcoming purchases: ~4,100)")
if not rows:
    raise SystemExit("No rows returned: paste this output to Claude.")

df = pd.DataFrame(rows)
print(f"\nfields ({len(df.columns)}): {sorted(df.columns)}\n")


def filled(col):
    return f"{df[col].notna().mean():.0%}" if col in df else "missing"


for col in ["objet", "nomacheteur", "code_departement", "datelimitereponse", "nature_libelle",
            "type_marche", "procedure_libelle", "descripteur_code", "titulaire"]:
    print(f"  {col:<22} filled: {filled(col)}")

# CPV codes usually sit inside the 'donnees' JSON blob (eForms notices); look for 8-digit CPV-like codes and a SIRET
blob = df["donnees"].astype(str) if "donnees" in df else pd.Series([""] * len(df))
cpv = blob.map(lambda s: re.findall(r"\b(\d{8})(?:-\d)?\b", s))
siret = blob.map(lambda s: re.findall(r"\b(\d{14})\b", s))
amount = blob.str.contains(r"(?i)montant|valeur estim|estimatedvalue|EstimatedOverallContractAmount")
print(f"\n  notices with a CPV-like code in 'donnees': {(cpv.str.len() > 0).mean():.0%}")
print(f"  notices with a SIRET-like number:         {(siret.str.len() > 0).mean():.0%}")
print(f"  notices mentioning an amount:             {amount.mean():.0%}")
divs = Counter(c[:2] for codes in cpv for c in codes[:1])
print(f"  most common CPV divisions: {divs.most_common(8)}")

print("\nSample:")
cols = [c for c in ["dateparution", "datelimitereponse", "code_departement", "nomacheteur", "objet"] if c in df]
print(df[cols].head(8).astype(str).apply(lambda s: s.str.slice(0, 50)).to_string(index=False))
print("\nPaste this whole output to Claude.")
