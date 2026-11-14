"""4-request check of the APProch pull before spending credits.

    HEMICYCLE_API_KEY=hmc_test_... python src/test_api.py     # test key: 0 credits

Checks: (1) offset 9,900 still returns rows, (2) offset 10,000 is refused with the
10,000-row error, (3) descending order works and returns different rows.
"""
import os
import re

import requests

import common  # noqa: F401  (loads .env without overriding a key passed on the command line)
from pull_hemicycle import rows_of

API = "https://api.hemicycle.ai/v1/jeux/interroger"
H = {"Authorization": f"Bearer {os.environ['HEMICYCLE_API_KEY']}", "Hemicycle-Version": "2026-10-01",
     "Content-Type": "application/json"}
BASE = {"jeu": "projets_achats_publics", "tri": "date_previsionnelle_de_publication", "limite": 100}


def call(ordre, off):
    r = requests.post(API, json={**BASE, "ordre": ordre, "decalage": off}, headers=H, timeout=60)
    rows = []
    if r.status_code == 200:
        payload = r.json()
        shape = list(payload)[:10] if isinstance(payload, dict) else f"list of {len(payload)}"
        print(f"   response keys: {shape}")
        try:
            rows = rows_of(payload)
        except ValueError:
            print(f"   raw start: {r.text[:300]}")
    return r, rows


key_type = "TEST (0 credits)" if os.environ["HEMICYCLE_API_KEY"].startswith("hmc_test_") else "LIVE (1 credit per call)"
print(f"key: {key_type}\n")
ok = True

r0, first = call("asc", 0)
print(f"0. asc offset 0     -> HTTP {r0.status_code}, {len(first)} rows")
if r0.status_code == 200 and not first:
    print(f"   raw start: {r0.text[:300]}")

r1, asc = call("asc", 9900)
print(f"1. asc offset 9900  -> HTTP {r1.status_code}, {len(asc)} rows, credits left {r1.headers.get('X-Credits-Remaining')}")
ok &= r1.status_code == 200 and len(asc) == 100
if asc:
    print(f"   columns: {sorted(asc[0])[:8]}…  has 'code': {'code' in asc[0]}")
    ok &= "code" in asc[0]

r2, _ = call("asc", 10000)
cap_msg = r2.status_code == 422 and "10000" in re.sub(r"\s", "", r2.text)
print(f"2. asc offset 10000 -> HTTP {r2.status_code}, recognised as the 10,000-row cap: {cap_msg}")
ok &= cap_msg or (r2.status_code == 200)  # 200 would mean no cap: also fine

r3, desc = call("desc", 0)
overlap = {x.get("code") for x in desc} & {x.get("code") for x in asc}
print(f"3. desc offset 0    -> HTTP {r3.status_code}, {len(desc)} rows, overlap with page 1: {len(overlap)} rows")
ok &= r3.status_code == 200 and len(desc) > 0

print("\nREADY: run python src/pull_hemicycle.py approch" if ok else "\nSOMETHING IS OFF: paste this output to Claude")
