"""Company establishments from Hémicycle's Sirene dataset (jeu `sirene_etablissements`), 1 credit per call.

    python webdesign/scripts/hemicycle_sirene.py 834709248

One POST, no retry loop (credits). Saves webdesign/data/hemicycle_sirene_<siren>.json with fetched_at,
so the company page can say "via l'API Hémicycle". The key comes from .env (HEMICYCLE_API_KEY) and is never printed.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import requests

WD = Path(__file__).resolve().parents[1]
ROOT = WD.parent
sys.path.insert(0, str(ROOT / "src"))
from hemicycle_history import API, _headers  # noqa: E402  (also loads .env through common)

OUT_DIR = WD / "data"


def fetch(siren: str) -> dict:
    body = {"jeu": "sirene_etablissements", "tri": "siret", "ordre": "asc", "limite": 100,
            "filtres": [{"colonne": "siren", "op": "eq", "valeur": siren}]}
    r = requests.post(API, json=body, headers=_headers(), timeout=30)
    r.raise_for_status()
    payload = r.json()
    rows = payload.get("lignes", payload) if isinstance(payload, dict) else payload
    meta = {k: v for k, v in payload.items() if k != "lignes"} if isinstance(payload, dict) else {}
    return {"siren": siren, "jeu": "sirene_etablissements", "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "credits_remaining": r.headers.get("X-Credits-Remaining"), "meta": meta, "lignes": rows,
            "source": "API Hémicycle, jeu « sirene_etablissements » (Insee, Licence Ouverte 2.0)"}


def main():
    siren = "".join(ch for ch in (sys.argv[1] if len(sys.argv) > 1 else "834709248") if ch.isdigit())[:9]
    d = fetch(siren)
    p = OUT_DIR / f"hemicycle_sirene_{siren}.json"
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(d['lignes'])} établissement(s) saved to {p} · credits remaining: {d['credits_remaining']}")


if __name__ == "__main__":
    main()
