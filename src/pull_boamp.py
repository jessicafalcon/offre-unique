"""Pull open BOAMP calls for tender (response deadline from today on) into data/raw/boamp.parquet.

    python src/pull_boamp.py          # free, no key; ~75 requests of 100 notices

Source: BOAMP open data (DILA), Licence Ouverte 2.0, via the Opendatasoft API.
CPV codes and the buyer SIRET are not separate fields: they are extracted from the 'donnees' JSON blob
(85 % and 84 % of notices in our check). Amount and duration are mostly absent, so the BOAMP model
variant does not use them.
"""
from __future__ import annotations

import re
import sys
import time

import pandas as pd
import requests

from common import RAW, TODAY

URL = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records"
LIMIT = 100
OFFSET_CAP = 10_000  # Opendatasoft: offset + limit must stay <= 10,000

FIELDS = ["idweb", "objet", "nomacheteur", "code_departement", "datelimitereponse", "dateparution",
          "nature_libelle", "type_marche", "procedure_libelle", "url_avis", "famille_libelle", "donnees"]

CPV_NEAR = re.compile(r"(?i)cpv\D{0,80}?(\d{8})")
CPV_ANY = re.compile(r"(?<!\d)(\d{8})(?:-\d)?(?!\d)")
SIRET_NEAR = re.compile(r"(?i)siret\D{0,40}?(\d{14})")
SIRET_ANY = re.compile(r"(?<!\d)(\d{14})(?!\d)")
VALID_DIV = {"03", "09", "14", "15", "16", "18", "19", "22", "24", "30", "31", "32", "33", "34", "35", "37",
             "38", "39", "41", "42", "43", "44", "45", "48", "50", "51", "55", "60", "63", "64", "65", "66",
             "70", "71", "72", "73", "75", "76", "77", "79", "80", "85", "90", "92", "98"}


def extract_cpv(blob: str) -> str | None:
    for rx in (CPV_NEAR, CPV_ANY):
        for code in rx.findall(blob):
            if code[:2] in VALID_DIV:
                return code
    return None


def extract_siret(blob: str) -> str | None:
    m = SIRET_NEAR.search(blob) or SIRET_ANY.search(blob)
    return m.group(1) if m else None


def first_dept(v) -> tuple[str | None, str]:
    if isinstance(v, (list, tuple)):
        vals = [str(x) for x in v if x]
    elif v is None or (isinstance(v, float) and pd.isna(v)):
        vals = []
    else:
        vals = [s for s in re.split(r"[|,; ]+", str(v).strip("[]'\" ")) if s]
    vals = [s.strip("'\" ") for s in vals]
    return (vals[0] if vals else None), "|".join(vals)


def get(params: dict) -> dict:
    for attempt in range(5):
        r = requests.get(URL, params=params, timeout=90)
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"{r.status_code}: {r.text[:400]}")
        return r.json()
    raise RuntimeError("too many 429 responses")


def main():
    today = TODAY.strftime("%Y-%m-%d")
    base = {"where": f"datelimitereponse >= date'{today}'", "select": ",".join(FIELDS),
            "order_by": "dateparution desc", "limit": LIMIT}
    rows, off, total = [], 0, None
    try:
        while off + LIMIT <= OFFSET_CAP:
            page = get({**base, "offset": off})
            total = page.get("total_count", total)
            res = page.get("results", [])
            for x in res:
                blob = str(x.pop("donnees", "") or "")
                x["cpv"] = extract_cpv(blob)
                x["buyer_siret"] = extract_siret(blob)
                rows.append(x)
            print(f"  offset={off:>5} got={len(res):>3} total={len(rows):>5} / {total}")
            if len(res) < LIMIT:
                break
            off += LIMIT
    except (RuntimeError, requests.RequestException) as e:
        print(f"STOPPED EARLY ({e}). Saving the {len(rows)} notices already downloaded.")
    if not rows:
        sys.exit("Nothing downloaded: paste the error above to Claude.")

    df = pd.DataFrame(rows)
    df[["dept_first", "departements"]] = [first_dept(v) for v in df["code_departement"]]
    df = df.drop(columns=["code_departement"]).drop_duplicates(subset=["idweb"])
    print(f"\n{len(df):,} open notices · nature: {df['nature_libelle'].value_counts().head(5).to_dict()}")
    print(f"CPV found: {df['cpv'].notna().mean():.0%} · buyer SIRET found: {df['buyer_siret'].notna().mean():.0%}")
    out = RAW / "boamp.parquet"
    df.to_parquet(out, index=False)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
