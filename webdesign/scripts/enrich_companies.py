"""Company cards (size, NAF, creation date, address, finances, labels) for any list of SIRENs.

    python webdesign/scripts/enrich_companies.py 834709248 798298899
    python webdesign/scripts/enrich_companies.py --refresh 834709248     # overwrite an existing card

Uses lib.data.fetch_identity() (API Recherche d'entreprises, free, no key), same schema as the app's live fetch.
Writes webdesign/data/companies/<siren>.json (UTF-8). No personal data kept (no dirigeants).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

WD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WD))
from lib import data  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sirens", nargs="+")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    out = data.DATA / "companies"
    out.mkdir(parents=True, exist_ok=True)
    for s in a.sirens:
        s = "".join(ch for ch in s if ch.isdigit())[:9]
        p = out / f"{s}.json"
        if p.exists() and not a.refresh:
            print(f"{s}: cached")
            continue
        try:
            d = data.fetch_identity(s)
        except Exception as e:  # noqa: BLE001
            print(f"{s}: failed ({e.__class__.__name__})")
            continue
        if not d:
            print(f"{s}: not found")
            continue
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{s}: {d['nom']} · {d['categorie_entreprise']} · tranche {d['tranche_effectif']} · NAF {d['naf']}")
        time.sleep(0.2)


if __name__ == "__main__":
    main()
