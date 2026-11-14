"""Buyer type and location for every scored tender, from the public company register (free, no key).

    python src/buyers.py            # ~2,700 buyers, ~15 min, resumable -> artifacts/buyers.json

Source: recherche-entreprises.api.gouv.fr (SIRENE, Licence Ouverte). One call per buyer:
- buyer_type: from the legal form code (catégorie juridique INSEE), e.g. 7364 hospital, 7331 collège / lycée;
- lat / lon / address: the buyer's busiest establishment in past contracts (artifacts/buyer_sirets.json),
  else its head office. This is where the BUYER is, not necessarily the worksite;
- multi_site: State, regions, départements and buyers with 3+ open establishments buy for many sites,
  so their pin is only indicative.
"""
from __future__ import annotations

import json
import re
import time

import pandas as pd
import requests

from common import ART, CLEAN

OUT = ART / "buyers.json"
API = "https://recherche-entreprises.api.gouv.fr/search"

# INSEE legal form (catégorie juridique) -> buyer type shown to the SME
EXACT = {
    "7210": "Commune", "7312": "Commune",
    "7220": "Département", "7230": "Région", "7225": "Collectivité territoriale", "7229": "Collectivité territoriale",
    "7364": "Hôpital, santé", "7365": "Hôpital, santé", "7366": "Santé, médico-social",
    "7331": "Collège, lycée", "7362": "Collège, lycée",
    "7383": "Université, recherche", "7384": "Université, recherche",
    "7371": "Logement social", "7372": "Pompiers (SDIS)", "7361": "Action sociale (CCAS)",
    "7373": "Culture",
}
PREFIX = [  # checked after EXACT
    ("71", "État, ministère"), ("734", "Intercommunalité"), ("735", "Syndicat, intercommunalité"),
    ("738", "Établissement public national"), ("737", "Établissement public local"), ("73", "Établissement public"),
    ("41", "Établissement public industriel et commercial"), ("55", "Entreprise publique, SEM"),
    ("56", "Entreprise publique, SEM"), ("57", "Entreprise publique, SEM"),
]
NAME_HINTS = [  # when the legal form is generic, the name often says more
    (r"(?i)\b(chu|chr|ch |centre hospitalier|h[ôo]pital|ehpad|ap-hp|groupement hospitalier|ght)\b", "Hôpital, santé"),
    (r"(?i)\b(lyc[ée]e|coll[èe]ge)\b", "Collège, lycée"),
    (r"(?i)\buniversit|cnrs|inrae|inserm|[ée]cole (nationale|normale|centrale|des mines)", "Université, recherche"),
    (r"(?i)\b(resah|ugap|centrale d.achat)", "Centrale d'achat"),
]
MULTI_TYPES = {"État, ministère", "Région", "Département", "Centrale d'achat"}


def buyer_type(nj: str, name: str) -> str:
    nj = str(nj or "")
    for pat, label in NAME_HINTS:
        if label == "Centrale d'achat" and re.search(pat, name or ""):
            return label
    if nj in EXACT:
        return EXACT[nj]
    generic = nj.startswith(("737", "738", "73", "41")) or not nj
    if generic:
        for pat, label in NAME_HINTS:
            if re.search(pat, name or ""):
                return label
    for pre, label in PREFIX:
        if nj.startswith(pre):
            return label
    return "Autre organisme"


def lookup(siren: str, siret: str | None) -> dict | None:
    for attempt in range(5):
        try:
            r = requests.get(API, params={"q": siret or siren, "per_page": 1}, timeout=10)
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code != 200:
            return None
        res = [x for x in r.json().get("results", []) if x.get("siren") == siren]
        if not res:
            return None
        x = res[0]
        est = next((m for m in (x.get("matching_etablissements") or []) if m.get("siret") == siret), None)
        src = "établissement acheteur" if est else "siège"
        est = est or x.get("siege") or {}
        name = x.get("nom_complet") or ""
        t = buyer_type(x.get("nature_juridique"), name)
        n_open = x.get("nombre_etablissements_ouverts") or x.get("nombre_etablissements") or 1
        return {"name": name, "nj": x.get("nature_juridique"), "type": t,
                "lat": float(est["latitude"]) if est.get("latitude") else None,
                "lon": float(est["longitude"]) if est.get("longitude") else None,
                "address": est.get("adresse"), "location_source": src, "n_establishments": n_open,
                "multi_site": t in MULTI_TYPES or n_open >= 3}
    return None


def main():
    s = pd.concat([pd.read_parquet(CLEAN / f) for f in ("scored.parquet", "scored_boamp.parquet")])
    sirens = sorted(set(s["buyer_siren"].dropna().astype(str)) - {"NA", "nan", ""})
    sirets = json.loads((ART / "buyer_sirets.json").read_text()) if (ART / "buyer_sirets.json").exists() else {}
    out = json.loads(OUT.read_text()) if OUT.exists() else {}  # resumable
    todo = [x for x in sirens if x not in out]
    print(f"{len(sirens):,} buyers, {len(todo):,} to look up", flush=True)
    t0 = time.time()
    for i, siren in enumerate(todo, 1):
        out[siren] = lookup(siren, (sirets.get(siren) or [None])[0]) or {"type": "Inconnu", "lat": None, "lon": None}
        time.sleep(0.15)  # the API allows ~7 requests/s
        if i % 100 == 0 or i == len(todo):
            OUT.write_text(json.dumps(out, ensure_ascii=False))
            print(f"  {i:,}/{len(todo):,} ({time.time() - t0:.0f}s)", flush=True)
    types = pd.Series([v.get("type") for v in out.values()]).value_counts()
    print(types.to_string())
    print(f"with coordinates: {sum(v.get('lat') is not None for v in out.values()):,} / {len(out):,} | "
          f"multi-site: {sum(bool(v.get('multi_site')) for v in out.values()):,}")


if __name__ == "__main__":
    main()
