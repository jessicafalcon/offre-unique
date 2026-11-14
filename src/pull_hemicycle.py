"""Pull a Hémicycle dataset page by page into data/raw/<name>.parquet.

    python src/pull_hemicycle.py approch            # ~106 pages = ~106 credits
    python src/pull_hemicycle.py decp --since 2025-01-01 --max-pages 300

Notes from the docs (hemicycle.ai/docs):
- POST /v1/jeux/interroger, 1 credit per page, `limite` <= 100 for these datasets.
- Pagination is by `decalage` (offset), capped at 10,000. To get past the cap the
  script reads the same query in ascending then descending order and de-duplicates.
- Test keys (hmc_test_) are limited to 100 requests/day: use a live key for APProch.
- For the full DECP, download the consolidated parquet from data.gouv.fr instead
  (free); see README.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time

import pandas as pd
import requests

from common import RAW

API = "https://api.hemicycle.ai/v1/jeux/interroger"
OFFSET_CAP = 10_000
LIMIT = 100

DATASETS = {
    "approch": {"jeu": "projets_achats_publics", "tri": "date_previsionnelle_de_publication", "key": ["code"]},
    "decp": {"jeu": "marches_publics", "tri": "datenotification", "key": ["acheteur_id", "id", "titulaire_id_1"]},
}


def headers() -> dict:
    key = os.environ.get("HEMICYCLE_API_KEY")
    if not key:
        sys.exit("Set HEMICYCLE_API_KEY in .env")
    return {
        "Authorization": f"Bearer {key}",
        "Hemicycle-Version": "2026-10-01",
        "Content-Type": "application/json",
    }


def rows_of(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    for k in ("data", "lignes", "rows", "resultats"):
        if k in payload and isinstance(payload[k], list):
            return payload[k]
    raise ValueError(f"Unexpected response shape: {list(payload)[:10]}")


def post(body: dict, budget: dict) -> list[dict]:
    if budget["pages"] >= budget["max_pages"]:
        raise RuntimeError("max-pages reached (credit guard)")
    for attempt in range(5):
        r = requests.post(API, json=body, headers=headers(), timeout=60)
        if r.status_code == 429:
            wait = int(float(r.headers.get("Retry-After", "5")))
            if wait > 60:  # daily quota, not a short burst limit
                raise RuntimeError(f"rate limit: retry in {wait}s (daily quota?)")
            time.sleep(wait)
            continue
        if r.status_code == 422 and "10000" in re.sub(r"\s", "", r.text):  # French text may use a no-break space
            raise CapReached(r.text[:200])
        if r.status_code >= 400:
            raise RuntimeError(f"{r.status_code}: {r.text[:500]}")
        budget["pages"] += 1
        rem = r.headers.get("X-Credits-Remaining")
        if rem is not None:
            budget["remaining"] = rem
        return rows_of(r.json())
    raise RuntimeError("Too many 429 responses")


class CapReached(Exception):
    """The API refuses to read past 10,000 rows of one query (HTTP 422)."""


def row_key(row: dict, keys: list[str]):
    if all(k in row for k in keys):
        return tuple(row.get(k) for k in keys)
    return tuple(sorted((k, str(v)) for k, v in row.items()))  # key column missing: use the whole row


def pull_order(jeu, tri, ordre, filtres, budget, out: list, keys: list[str], stop_on_seen: bool = False) -> bool:
    """Append one sort order to `out` until exhausted or the 10,000-row cap. Returns hit_cap.

    With stop_on_seen, stops as soon as a page contains a row already downloaded
    (used for the descending pass, which only needs the rows the ascending pass missed).
    """
    seen = {row_key(r, keys) for r in out} if stop_on_seen else set()
    off = 0
    while off < OFFSET_CAP:
        body = {"jeu": jeu, "tri": tri, "ordre": ordre, "limite": LIMIT, "decalage": off}
        if filtres:
            body["filtres"] = filtres
        try:
            page = post(body, budget)
        except CapReached:
            return True
        overlap = stop_on_seen and any(row_key(r, keys) in seen for r in page)
        out += page
        print(f"  {ordre} offset={off:>6} got={len(page):>3} total={len(out):>6} credits_left={budget.get('remaining')}")
        if overlap:
            print("  reached rows already downloaded: done")
            return False
        if len(page) < LIMIT:
            return False
        off += LIMIT
    return True


def pull(name: str, filtres=None, max_pages=400) -> pd.DataFrame:
    cfg = DATASETS[name]
    budget = {"pages": 0, "max_pages": max_pages}
    rows: list[dict] = []
    keys = cfg["key"]
    try:
        if pull_order(cfg["jeu"], cfg["tri"], "asc", filtres, budget, rows, keys):
            print("10,000-row cap reached: reading the end of the list in descending order")
            if pull_order(cfg["jeu"], cfg["tri"], "desc", filtres, budget, rows, keys, stop_on_seen=True):
                print("WARNING: more than ~20,000 rows for this query; narrow it with --since/--until")
    except RuntimeError as e:
        # daily quota (test keys: 100 requests/day), credit guard or API error: keep what we have
        print(f"STOPPED EARLY ({e}). Saving the {len(rows)} rows already downloaded.")
    if not rows:
        sys.exit("Nothing downloaded: check the key and the error above.")
    df = pd.DataFrame(rows)
    keys = [k for k in cfg["key"] if k in df.columns]
    before = len(df)
    df = df.drop_duplicates(subset=keys or None)
    print(f"{name}: {len(df)} rows ({before - len(df)} duplicates removed), {budget['pages']} pages used")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", choices=DATASETS)
    ap.add_argument("--since", help="decp only: datenotification >= YYYY-MM-DD")
    ap.add_argument("--until", help="decp only: datenotification < YYYY-MM-DD")
    ap.add_argument("--max-pages", type=int, default=400, help="credit guard (1 page = 1 credit)")
    a = ap.parse_args()
    filtres = []
    if a.since:
        filtres.append({"colonne": "datenotification", "op": "gte", "valeur": a.since})
    if a.until:
        filtres.append({"colonne": "datenotification", "op": "lt", "valeur": a.until})
    df = pull(a.name, filtres or None, a.max_pages)
    out = RAW / f"{a.name}.parquet"
    df.to_parquet(out, index=False)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
