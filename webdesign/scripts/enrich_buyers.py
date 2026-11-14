"""Buyer SIREN -> INSEE nature juridique, from the free API Recherche d'entreprises (no key).

    python webdesign/scripts/enrich_buyers.py            # all buyers of open tenders + demo companies' past buyers
    python webdesign/scripts/enrich_buyers.py --extra 834709248,798298899

Resumable: every answer is appended to webdesign/data/buyers_cache.jsonl, and SIRENs already there are skipped.
Writes webdesign/data/buyers.parquet (buyer_siren, nom, categorie_juridique, commune, departement, source).
Throttled to <= 6 requests/s (the API allows ~7), backs off on HTTP 429.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

WD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WD))
from lib import data  # noqa: E402

CACHE = data.DATA / "buyers_cache.jsonl"
OUT = data.DATA / "buyers.parquet"
API = "https://recherche-entreprises.api.gouv.fr/search"
HEADERS = {"User-Agent": "offre-unique-hackathon"}
MIN_GAP = 1 / 6  # seconds between requests


def target_sirens(demo: list[str]) -> list[str]:
    s = set(data.scored()["buyer_siren"].dropna().astype(str).str[:9])
    for siren in demo:
        s |= set(data.company_awards(siren)["buyer_siren"].dropna().astype(str).str[:9])
    return sorted(x for x in s if len(x) == 9 and x.isdigit())


def load_cache() -> dict:
    out = {}
    if CACHE.exists():
        for line in CACHE.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                out[r["buyer_siren"]] = r
            except (ValueError, KeyError):
                continue
    return out


def fetch(siren: str) -> dict:
    for attempt in range(3):
        try:
            r = requests.get(API, params={"q": siren, "per_page": 5}, headers=HEADERS, timeout=10)
            if r.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            hit = next((x for x in r.json().get("results", []) if x.get("siren") == siren), None)
            if not hit:
                return {"buyer_siren": siren, "found": False}
            sg = hit.get("siege") or {}
            return {"buyer_siren": siren, "found": True, "nom": hit.get("nom_complet") or hit.get("nom_raison_sociale"),
                    "categorie_juridique": str(hit.get("nature_juridique") or ""),
                    "commune": sg.get("libelle_commune"), "departement": sg.get("departement")}
        except requests.RequestException:
            time.sleep(1 + attempt)
    return {"buyer_siren": siren, "found": None}  # failed: retried on next run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra", default="834709248,798298899", help="companies whose past buyers are added")
    a = ap.parse_args()
    data.DATA.mkdir(parents=True, exist_ok=True)
    todo_all = target_sirens([s for s in a.extra.split(",") if s])
    cache = load_cache()
    todo = [s for s in todo_all if s not in cache or cache[s].get("found") is None]
    print(f"{len(todo_all):,} buyers · {len(todo):,} to fetch", flush=True)
    lock, state = threading.Lock(), {"next": 0.0}

    def throttled(s: str) -> dict:
        with lock:  # global rate limit across threads: one request start every MIN_GAP seconds
            now = time.time()
            start = max(now, state["next"])
            state["next"] = start + MIN_GAP
        if start > now:
            time.sleep(start - now)
        return fetch(s)

    with CACHE.open("a", encoding="utf-8") as f, ThreadPoolExecutor(max_workers=4) as ex:
        for i, r in enumerate(ex.map(throttled, todo), 1):
            cache[r["buyer_siren"]] = r
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            if i % 200 == 0:
                f.flush()
                print(f"  {i:,}/{len(todo):,}", flush=True)
    rows = [r for s, r in cache.items() if s in set(todo_all) and r.get("found")]
    df = pd.DataFrame(rows)[["buyer_siren", "nom", "categorie_juridique", "commune", "departement"]]
    df["source"] = "API Recherche d'entreprises (Sirene, Insee), Licence Ouverte 2.0"
    df.to_parquet(OUT, index=False)
    miss = sum(1 for s in todo_all if not (cache.get(s) or {}).get("found"))
    print(f"saved {len(df):,} buyers to {OUT} · not found or failed: {miss:,}")


if __name__ == "__main__":
    main()
