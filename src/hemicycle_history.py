"""Buyer history, live from Hémicycle ("Marchés publics notifiés", jeu `marches_publics`).

    python src/hemicycle_history.py --build-map                 # buyer SIREN -> SIRETs (local, free)
    python src/hemicycle_history.py --siren 834709248 --top 62  # prefetch a company's tenders (1 credit per buyer SIRET)

One POST per buyer SIRET (filter acheteur_id = SIRET, 100 most recent contracts, 1 credit).
Results are cached in artifacts/hemicycle_history.json, keyed by tender code, so the demo never waits on the network.
The app reads the cache and can fetch one tender live (button).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

import pandas as pd
import requests

from common import ART, CLEAN

API = "https://api.hemicycle.ai/v1/jeux/interroger"
CACHE = ART / "hemicycle_history.json"
SIRET_MAP = ART / "buyer_sirets.json"
NAMES = ART / "company_names.json"
MAX_SIRETS = 3  # a buyer with many sites: query its 3 busiest SIRETs


def _headers() -> dict:
    import os
    key = os.environ.get("HEMICYCLE_API_KEY")
    if not key:
        raise RuntimeError("HEMICYCLE_API_KEY missing")
    return {"Authorization": f"Bearer {key}", "Hemicycle-Version": "2026-10-01", "Content-Type": "application/json"}


def load_json(p) -> dict:
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def build_maps() -> None:
    """Buyer SIREN -> its busiest SIRETs, and company SIREN -> name (Hémicycle rows carry SIRETs, not names)."""
    c = pd.read_parquet(CLEAN / "contracts.parquet", columns=["acheteur_id", "buyer_siren"]).dropna()
    top = (c.groupby(["buyer_siren", "acheteur_id"]).size().rename("n").reset_index()
           .sort_values("n", ascending=False).groupby("buyer_siren").head(MAX_SIRETS))
    m = top.groupby("buyer_siren")["acheteur_id"].agg(list).to_dict()
    SIRET_MAP.write_text(json.dumps(m))
    a = pd.read_parquet(CLEAN / "awards.parquet", columns=["company_siren", "titulaire_nom"]).dropna()
    names = a.groupby("company_siren")["titulaire_nom"].agg(lambda s: s.mode().iloc[0]).to_dict()
    NAMES.write_text(json.dumps(names, ensure_ascii=False))
    print(f"{len(m):,} buyers mapped to SIRETs; {len(names):,} company names")


def fetch_siret(siret: str) -> tuple[list[dict], str | None]:
    body = {"jeu": "marches_publics", "tri": "datenotification", "ordre": "desc", "limite": 100,
            "filtres": [{"colonne": "acheteur_id", "op": "eq", "valeur": siret}]}
    r = requests.post(API, json=body, headers=_headers(), timeout=30)
    r.raise_for_status()
    payload = r.json()
    rows = payload.get("lignes", payload) if isinstance(payload, dict) else payload
    return rows, r.headers.get("X-Credits-Remaining")


def _offers(v) -> int | None:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 200 else None


def summarize(rows: list[dict], cpv_grp: str, cpv_div: str, names: dict) -> dict:
    """Same definition as score.py: same buyer, same CPV group (3 digits), falling back to the division (2 digits)."""
    seen, uniq = set(), []
    for x in rows:  # one row per contract (modifications repeat the id)
        k = (x.get("acheteur_id"), x.get("id"))
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    level, sel = "groupe CPV", [x for x in uniq if str(x.get("codecpv", "")).startswith(str(cpv_grp))]
    if not sel:
        level, sel = "division CPV", [x for x in uniq if str(x.get("codecpv", "")).startswith(str(cpv_div))]
    sel.sort(key=lambda x: str(x.get("datenotification") or ""), reverse=True)
    offers = [o for o in (_offers(x.get("offresrecues")) for x in sel) if o is not None]
    eds = []
    for x in sel[:5]:
        sid = str(x.get("titulaire_id_1") or "")[:9]
        eds.append({"date": x.get("datenotification"), "objet": str(x.get("objet") or "")[:140],
                    "offres": _offers(x.get("offresrecues")), "titulaire_nom": names.get(sid) or (f"SIREN {sid}" if sid else None)})
    return {"n": len(sel), "n_lab": len(offers), "level": level,
            "single_share": (sum(o == 1 for o in offers) / len(offers)) if offers else None,
            "last_date": sel[0].get("datenotification") if sel else None, "editions": eds}


def history_for(row: pd.Series, siret_map: dict, names: dict, raw_cache: dict | None = None) -> dict | None:
    """Fetch (or reuse) the buyer's contracts and summarise them for one tender. None if the buyer has no known SIRET."""
    sirets = siret_map.get(str(row.get("buyer_siren")), [])
    if not sirets:
        return None
    rows, left = [], None
    for s in sirets:
        if raw_cache is not None and s in raw_cache:
            rows += raw_cache[s]
            continue
        got, left = fetch_siret(s)
        if raw_cache is not None:
            raw_cache[s] = got
        rows += got
    out = summarize(rows, str(row.get("cpv_grp")), str(row.get("cpv_div")), names)
    out.update({"fetched_at": datetime.now().isoformat(timespec="minutes"), "sirets": sirets, "credits_left": left})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-map", action="store_true")
    ap.add_argument("--siren")
    ap.add_argument("--top", type=int, default=62)
    ap.add_argument("--max-credits", type=int, default=150, help="credit guard")
    a = ap.parse_args()
    if a.build_map or not SIRET_MAP.exists():
        build_maps()
    if not a.siren:
        return
    from profiles import fit_table, load_all_scored, profile_of, relevant
    awards = pd.read_parquet(CLEAN / "awards.parquet")
    prof = profile_of(awards, a.siren)
    t = relevant(fit_table(prof, load_all_scored(), awards)).sort_values("proba", ascending=False).head(a.top)
    siret_map, names, cache, raw = load_json(SIRET_MAP), load_json(NAMES), load_json(CACHE), {}
    for _, r in t.iterrows():
        need = [s for s in siret_map.get(str(r["buyer_siren"]), []) if s not in raw]
        if len(raw) + len(need) > a.max_credits:
            print("credit guard reached: stopping")
            break
        h = history_for(r, siret_map, names, raw)
        if h is None:
            print(f"[no SIRET] {str(r['libelle'])[:60]}")
            continue
        cache[str(r["code"])] = h
        share = "—" if h["single_share"] is None else f"{round(100 * h['single_share'])} %"
        print(f"[{h['n']:>3} contracts, {h['n_lab']:>3} with bids, single {share:>5}] {str(r['libelle'])[:60]}")
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    print(f"queried {len(raw)} SIRETs (= credits); cache: {CACHE}")


if __name__ == "__main__":
    main()
