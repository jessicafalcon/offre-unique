"""Low-RAM data access for webdesign/, built on Jessica's src/ (read-only: nothing in src/, data/ or artifacts/ is written).

Rules: never load the full awards/contracts files (filter with pyarrow), read every JSON as UTF-8
(Windows defaults to cp1252), keep each process under ~1 GB.

    current_siren()            SIREN chosen in the sidebar
    scored()                   all scored tenders (BOAMP + APProch), buyer names unescaped
    company_awards(siren)      the company's past wins (filtered read of awards.parquet)
    profile(siren)             Jessica's profile_of()
    company_contracts(siren)   past wins + sector / buyer kind / amount band tags, for charts
    tenders(siren)             matching tenders with the go / no-go of explain.recommend() and tags
    identity(siren)            company card (size, NAF, creation, address, finances): cache in webdesign/data/companies/,
                               else live from recherche-entreprises.api.gouv.fr (free, no key)
    buyers()                   buyer SIREN -> INSEE nature juridique (webdesign/data/buyers.parquet, if built)
    metrics() / backtest() / benchmark() / notes()   artifacts, read as UTF-8
"""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

WD = Path(__file__).resolve().parents[1]          # webdesign/
ROOT = WD.parent                                  # repo root
DATA = WD / "data"                                # data added by webdesign (companies/, buyers.parquet, ...)
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from common import ART, CLEAN, TODAY, cpv_label  # noqa: E402
from explain import recommend  # noqa: E402
from profiles import fit_table, load_all_scored, profile_of, relevant  # noqa: E402

from . import taxonomy as tx  # noqa: E402

DEMO_SIREN = "834709248"  # Point Contrôles (see CLAUDE.md §7)


def read_json(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else default
    except (OSError, ValueError):
        return default


def current_siren() -> str:
    import os
    s = str(st.session_state.get("siren") or os.environ.get("DEMO_SIREN") or DEMO_SIREN)
    return "".join(ch for ch in s if ch.isdigit())[:9]


# ------------------------------------------------------------------------------------------ artifacts
@st.cache_data
def metrics(variant: str = "") -> dict | None:
    return read_json(ART / f"metrics{variant}.json")


def avg_rate() -> float | None:
    m = metrics()
    return m.get("test_single_bid_rate") if m else None


@st.cache_data
def backtest() -> dict | None:
    return read_json(ART / "rules_backtest.json")


@st.cache_data
def benchmark() -> dict | None:
    return read_json(ART / "llm_benchmark.json")


def notes() -> dict:
    return read_json(ART / "notes.json", {}) or {}


def hemicycle_history() -> dict:
    return read_json(ART / "hemicycle_history.json", {}) or {}


# ------------------------------------------------------------------------------------------ buyers
@st.cache_data
def buyers() -> pd.DataFrame:
    """buyer_siren, categorie_juridique (+ whatever the enrichment added). Empty if not built yet."""
    p = DATA / "buyers.parquet"
    if not p.exists():
        return pd.DataFrame(columns=["buyer_siren", "categorie_juridique"])
    return pd.read_parquet(p)


@st.cache_data
def _cj_map() -> dict:
    b = buyers()
    return dict(zip(b["buyer_siren"].astype(str), b["categorie_juridique"].astype(str))) if len(b) else {}


def buyer_kind_key(siren, name) -> str:
    return tx.buyer_kind_of(_cj_map().get(str(siren or "")[:9]), name).key


# ------------------------------------------------------------------------------------------ tenders
@st.cache_data
def scored() -> pd.DataFrame:
    s = load_all_scored()
    for col in ("buyer_name", "libelle"):
        s[col] = s[col].map(lambda x: html.unescape(x) if isinstance(x, str) else x)
    return s


def read_filtered(path: Path, col: str, values, columns: list[str] | None = None, batch: int = 100_000) -> pd.DataFrame:
    """Rows of a big parquet whose `col` is in `values`, read in batches so RAM stays flat (~100 MB)."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    pa.set_memory_pool(pa.system_memory_pool())  # the default pool keeps freed memory; the system one gives it back
    vals = pa.array(sorted({str(v) for v in values}))
    f = pq.ParquetFile(path)
    parts = []
    for i in range(f.num_row_groups):  # read the key column only, then the full row group if it matches
        key = f.read_row_group(i, columns=[col]).column(col)
        m = pc.is_in(key, value_set=vals)
        if pc.any(m).as_py():
            parts.append(f.read_row_group(i, columns=columns).filter(m))
        del key, m
    if not parts:
        return f.schema_arrow.empty_table().to_pandas() if columns is None else pd.DataFrame(columns=columns)
    return pa.concat_tables(parts).to_pandas()


@st.cache_data(max_entries=8)
def company_awards(siren: str) -> pd.DataFrame:
    return read_filtered(CLEAN / "awards.parquet", "company_siren", [siren])


def profile(siren: str) -> dict | None:
    if not siren_valid(siren):  # placeholders such as 999999999 appear hundreds of times in DECP
        return None
    aw = company_awards(siren)
    return profile_of(aw, siren) if len(aw) else None


@st.cache_data(max_entries=8)
def company_contracts(siren: str) -> pd.DataFrame:
    """One row per past win, with tags for charts: sector, buyer_kind, amount_band, single_bid."""
    a = company_awards(siren).copy()
    if a.empty:
        return a
    a["acheteur_nom"] = a["acheteur_nom"].map(lambda x: html.unescape(x) if isinstance(x, str) else x)
    a["sector"] = a["cpv_div"].map(lambda d: tx.sector_of(d).key)
    a["buyer_kind"] = [buyer_kind_key(s, n) for s, n in zip(a["buyer_siren"], a["acheteur_nom"])]
    a["amount_band_std"] = a["montant"].map(tx.amount_band_of)
    a["single_bid"] = a["offres"].map(lambda v: None if pd.isna(v) else bool(v == 1))
    return a.sort_values("date", ascending=False)


@st.cache_data(max_entries=8)
def tenders(siren: str) -> pd.DataFrame:
    """Matching tenders (Jessica's relevant()), sorted by chance of a single bid, with go / no-go and tags."""
    prof = profile(siren)
    if not prof:
        return pd.DataFrame()
    t = relevant(fit_table(prof, scored(), company_awards(siren)))
    t = t.sort_values("proba", ascending=False).reset_index(drop=True)
    if t.empty:
        return t
    avg = avg_rate()
    recos, reasons, inc_flags = [], [], []
    for r in t.itertuples():
        hs = None if pd.isna(r.hist_single_share) else float(r.hist_single_share)
        inc = str(r.incumbent_siren or "").replace(".0", "")[:9] == siren
        reco, why = recommend(float(r.proba), avg, int(r.n_match_dept), hs, inc,
                              0 if inc else int(r.incumbent_streak or 0))
        recos.append(reco), reasons.append(why), inc_flags.append(inc)
    t["reco"], t["reason"], t["is_incumbent"] = recos, reasons, inc_flags
    t["ratio"] = t["proba"] / avg if avg else 1.0
    t["sector"] = t["cpv_div"].map(lambda d: tx.sector_of(d).key)
    t["buyer_kind"] = [buyer_kind_key(s, n) for s, n in zip(t["buyer_siren"], t["buyer_name"])]
    band = t["montant_estime_du_marche"] if "montant_estime_du_marche" in t else pd.Series("", index=t.index)
    t["amount_rank"] = band.map(lambda b: tx.amount_style(b)[0])
    t["days_left"] = (t["due_date"].dt.normalize() - TODAY).dt.days
    t["kind"] = t["source"].map({"BOAMP": "Ouvert", "APProch": "Projet"}).fillna("Projet")
    return t


# ------------------------------------------------------------------------------------------ company identity
def _company_path(siren: str) -> Path:
    return DATA / "companies" / f"{siren}.json"


def fetch_identity(siren: str, timeout: float = 8.0) -> dict | None:
    """Company card from recherche-entreprises.api.gouv.fr (open data: Sirene, RNE, labels). No personal data kept."""
    import requests
    r = requests.get("https://recherche-entreprises.api.gouv.fr/search", params={"q": siren, "per_page": 1},
                     timeout=timeout, headers={"User-Agent": "offre-unique-hackathon"})
    r.raise_for_status()
    res = [x for x in r.json().get("results", []) if x.get("siren") == siren]
    if not res:
        return None
    x = res[0]
    sg = x.get("siege") or {}
    comp = x.get("complements") or {}
    fin = {str(y): {"ca": v.get("ca"), "resultat_net": v.get("resultat_net")}
           for y, v in (x.get("finances") or {}).items()}
    return {
        "siren": siren,
        "nom": x.get("nom_complet") or x.get("nom_raison_sociale"),
        "sigle": x.get("sigle"),
        "categorie_entreprise": x.get("categorie_entreprise"),          # PME / ETI / GE
        "tranche_effectif": x.get("tranche_effectif_salarie"),          # INSEE code, see taxonomy.TRANCHES
        "annee_effectif": x.get("annee_tranche_effectif_salarie"),
        "naf": x.get("activite_principale"),
        "section_naf": x.get("section_activite_principale"),
        "nature_juridique": x.get("nature_juridique"),
        "date_creation": x.get("date_creation"),
        "nb_etablissements_ouverts": x.get("nombre_etablissements_ouverts"),
        "siege": {"adresse": sg.get("adresse"), "commune": sg.get("libelle_commune"), "code_postal": sg.get("code_postal"),
                  "departement": sg.get("departement"), "lat": sg.get("latitude"), "lon": sg.get("longitude")},
        "finances": fin,
        "labels": {"rge": bool(comp.get("est_rge")), "ess": bool(comp.get("est_ess")),
                   "societe_mission": bool(comp.get("est_societe_mission")),
                   "organisme_formation": bool(comp.get("est_organisme_formation")),
                   "qualiopi": bool(comp.get("est_qualiopi"))},
        "entrepreneur_individuel": bool(comp.get("est_entrepreneur_individuel")),
        "source": "API Recherche d'entreprises (data.gouv.fr) · Sirene (Insee), Licence Ouverte 2.0",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }


def siren_valid(siren: str) -> bool:
    """9 digits, Luhn key OK, not a placeholder like 999999999 (563 DECP rows use it). La Poste (356000000) is the known exception."""
    s = str(siren or "")
    if len(s) != 9 or not s.isdigit() or len(set(s)) == 1:
        return False
    if s == "356000000":
        return True
    total = 0
    for i, ch in enumerate(reversed(s)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def identity(siren: str, live: bool = True) -> dict | None:
    """Cached card if present (webdesign/data/companies/<siren>.json), else a live fetch saved to that cache."""
    if not siren_valid(siren):
        return None
    p = _company_path(siren)
    d = read_json(p)
    if d or not live:
        return d
    try:
        d = fetch_identity(siren)
    except Exception:  # keep the page alive without network
        return None
    if d:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return d


__all__ = ["ART", "CLEAN", "TODAY", "cpv_label", "tx"]
