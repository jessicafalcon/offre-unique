"""Shared paths, column normalisation and feature alignment.

Every feature is built the same way for past contracts (DECP) and upcoming
purchases (APProch), so the model sees identical inputs in training and scoring.
If a real column name differs from what is expected, add it to ALIASES below.
"""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean"
ART = ROOT / "artifacts"
REPORTS = ROOT / "reports"
for _p in (RAW, CLEAN, ART, REPORTS):
    _p.mkdir(parents=True, exist_ok=True)

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

SPLIT_YEAR = int(os.environ.get("SPLIT_YEAR", "2025"))  # test = this year and later
MIN_YEAR = int(os.environ.get("MIN_YEAR", "2023"))      # older years: junk dates and a different mix of sources
TODAY = pd.Timestamp(os.environ.get("TODAY", pd.Timestamp.today().normalize()))

# ---------------------------------------------------------------------------
# Column normalisation
# ---------------------------------------------------------------------------

# canonical name -> other spellings seen in DECP exports (after lower-casing)
ALIASES = {
    "acheteur_id": ["acheteur_id", "acheteurid", "acheteur.id", "siretacheteur", "acheteur_siret"],
    "acheteur_nom": ["acheteur_nom", "acheteurnom", "acheteur.nom"],
    "id": ["id", "id_marche", "idmarche"],
    "uid": ["uid"],
    "objet": ["objet"],
    "codecpv": ["codecpv", "code_cpv", "cpv"],
    "procedure": ["procedure"],
    "nature": ["nature"],
    "montant": ["montant"],
    "dureemois": ["dureemois", "duree_mois", "duree"],
    "datenotification": ["datenotification", "date_notification"],
    "offresrecues": ["offresrecues", "offres_recues", "nombreoffresrecues"],
    "lieuexecution_code": ["lieuexecution_code", "lieuexecution.code", "lieu_execution_code"],
    "lieuexecution_typecode": ["lieuexecution_typecode", "lieuexecution.typecode", "lieu_execution_typecode"],
    "titulaire_id_1": ["titulaire_id_1", "titulaire_id", "titulaireid", "titulaire.id", "titulaires_id"],
    "titulaire_nom": ["titulaire_nom", "titulaire_denominationsociale", "titulaire_denomination", "titulaire.denominationsociale"],
    "titulaire_id_2": ["titulaire_id_2"],
    "titulaire_id_3": ["titulaire_id_3"],
    "considerationssociales": ["considerationssociales", "considerations_sociales"],
    "considerationsenvironnementales": ["considerationsenvironnementales", "considerations_environnementales"],
    "idmodification": ["idmodification", "modification_id", "id_modification"],
}


def _norm_name(c: str) -> str:
    return str(c).strip().lower().replace(" ", "_")


def normalize_decp_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case column names and map known aliases to canonical names."""
    df = df.rename(columns={c: _norm_name(c) for c in df.columns})
    rename = {}
    for canon, alts in ALIASES.items():
        if canon in df.columns:
            continue
        for a in alts:
            if a in df.columns and a not in rename:
                rename[a] = canon
                break
    return df.rename(columns=rename)


REQUIRED_DECP = ["acheteur_id", "id", "codecpv", "procedure", "montant", "datenotification", "offresrecues"]


def missing_required(df: pd.DataFrame) -> list[str]:
    return [c for c in REQUIRED_DECP if c not in df.columns]


# ---------------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------------

def strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


def low(s) -> str:
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    return strip_accents(str(s)).lower().strip()


def siren_of(x) -> str | None:
    """First 9 digits of a SIRET/SIREN, or None."""
    d = re.sub(r"\D", "", str(x)) if x is not None and str(x) != "nan" else ""
    return d[:9] if len(d) >= 9 else None


# ---------------------------------------------------------------------------
# Aligned features
# ---------------------------------------------------------------------------

def first_cpv(x) -> str:
    """First CPV code's digits (APProch can list several, separated by | , ; or spaces)."""
    s = str(x) if x is not None else ""
    m = re.search(r"\d{2,8}", s)
    return m.group(0) if m else ""


def cpv_div(x) -> str:
    c = first_cpv(x)
    return c[:2] if len(c) >= 2 else "NA"


def cpv_group(x) -> str:
    c = first_cpv(x)
    return c[:3] if len(c) >= 3 else cpv_div(x)


CPV_DIVISIONS = {  # short French labels for CPV divisions (first 2 digits)
    "03": "Produits agricoles", "09": "Énergie et carburants", "14": "Produits miniers", "15": "Alimentation",
    "16": "Machines agricoles", "18": "Habillement", "19": "Cuir et textiles", "22": "Imprimés",
    "24": "Produits chimiques", "30": "Matériel de bureau et informatique", "31": "Matériel électrique",
    "32": "Équipements radio et télécom", "33": "Matériel médical", "34": "Véhicules et transport",
    "35": "Sécurité et défense", "37": "Sport et loisirs (matériel)", "38": "Laboratoire et optique",
    "39": "Mobilier et équipement", "41": "Eau", "42": "Machines industrielles", "43": "Engins de chantier",
    "44": "Matériaux de construction", "45": "Travaux de construction", "48": "Logiciels",
    "50": "Réparation et maintenance", "51": "Installation", "55": "Restauration et hôtellerie",
    "60": "Transport", "63": "Logistique", "64": "Poste et télécom", "65": "Réseaux (eau, énergie)",
    "66": "Finance et assurance", "70": "Immobilier", "71": "Architecture et ingénierie",
    "72": "Services informatiques", "73": "Recherche et développement", "75": "Services publics",
    "76": "Services pétroliers", "77": "Espaces verts et agriculture", "79": "Services aux entreprises",
    "80": "Formation", "85": "Santé et action sociale", "90": "Déchets, propreté et environnement",
    "92": "Culture, sport et loisirs", "98": "Autres services",
}


def cpv_label(div: str) -> str:
    return CPV_DIVISIONS.get(str(div), f"CPV {div}")


def cpv_class(x) -> str:
    """First 4 CPV digits (e.g. 4523 road works vs 4533 HVAC): used to match a company's trade."""
    c = first_cpv(x)
    return c[:4] if len(c) >= 4 else "NA"


def categorie_from_cpv(div: str) -> str:
    """Works / supplies / services, derived from the CPV division in both datasets."""
    if not div or not div.isdigit():
        return "NA"
    d = int(div)
    if d == 45:
        return "Travaux"
    if d <= 44 or d == 48:
        return "Fournitures"
    return "Services"


def procedure_canon(x) -> str:
    s = low(x)
    if not s:
        return "NA"
    if "sans publicite" in s or "sans mise en concurrence" in s or "sans publicite ni mise en concurrence" in s:
        return "sans_pub"
    if "adapt" in s or "mapa" in s:
        return "adaptee"
    if "dialogue" in s:
        return "dialogue"
    if "concours" in s:
        return "concours"
    if "negoci" in s:
        return "negociee"
    if "restreint" in s:
        return "restreint"
    if "ouvert" in s:
        return "ouvert"
    return "autre"


# Procedures where a single bid is expected by design: excluded from training.
EXCLUDED_PROCEDURES = {"sans_pub"}


_NUM = r"(\d+(?:[.,]\d+)?)\s*([kKmM]?)"


def _to_eur(num: str, unit: str) -> float:
    v = float(num.replace(",", "."))
    u = unit.lower()
    return v * (1e3 if u == "k" else 1e6 if u == "m" else 1)


def parse_amount_band(x) -> tuple[float, float] | None:
    """'100k - 500k€' -> (1e5, 5e5); '+ 100M€' -> (1e8, inf)."""
    s = str(x) if x is not None else ""
    nums = re.findall(_NUM, s)
    if not nums:
        return None
    vals = [_to_eur(n, u) for n, u in nums]
    if len(vals) == 1:
        return (vals[0], float("inf")) if "+" in s or "plus" in low(s) else (0.0, vals[0])
    return (min(vals), max(vals))


DEFAULT_EDGES = [0, 40e3, 100e3, 500e3, 1e6, 5e6, 25e6, 100e6]


def band_edges_from_approch(bands: pd.Series) -> list[float]:
    """Use APProch's own band boundaries so DECP amounts land in the same bins."""
    lows = set()
    for b in bands.dropna().unique():
        p = parse_amount_band(b)
        if p:
            lows.add(p[0])
            if p[1] != float("inf"):
                lows.add(p[1])
    edges = sorted(lows | {0.0})
    return edges if len(edges) >= 3 else DEFAULT_EDGES


def band_label(lo: float, hi: float) -> str:
    def f(v):
        if v == float("inf"):
            return ""
        if v >= 1e6:
            return f"{v/1e6:g}M€"
        if v >= 1e3:
            return f"{v/1e3:g}k€"
        return f"{v:g}€"
    return f"+ {f(lo)}" if hi == float("inf") else f"{f(lo)} – {f(hi)}"


def amount_to_band(amount: pd.Series, edges: list[float]) -> pd.Series:
    e = list(edges) + [float("inf")]
    labels = [band_label(e[i], e[i + 1]) for i in range(len(e) - 1)]
    a = pd.to_numeric(amount, errors="coerce")
    out = pd.cut(a, bins=e, labels=labels, right=False, include_lowest=True)
    return out.astype("object").where(out.notna(), "NA")


def approch_band_to_band(bands: pd.Series, edges: list[float]) -> pd.Series:
    """Map an APProch band string onto the same labels as amount_to_band."""
    def one(b):
        p = parse_amount_band(b)
        if not p:
            return "NA"
        lo = p[0]
        mid = lo if p[1] == float("inf") else (lo + p[1]) / 2
        return amount_to_band(pd.Series([max(lo, mid * 0.999)]), edges).iloc[0]
    return bands.map(one)


def duration_months(x) -> float:
    """'36' / '36 mois' / '3 ans' / '90 jours' -> months."""
    s = low(x)
    m = re.search(r"(\d+(?:[.,]\d+)?)", s)
    if not m:
        return np.nan
    v = float(m.group(1).replace(",", "."))
    if "an" in s and "mois" not in s:
        v *= 12
    elif "jour" in s:
        v /= 30
    elif "semaine" in s:
        v /= 4.3
    return v


def duration_bin(months) -> str:
    m = pd.to_numeric(months, errors="coerce")
    bins = [-np.inf, 6, 12, 24, 36, 48, np.inf]
    labels = ["≤6", "7-12", "13-24", "25-36", "37-48", ">48"]
    out = pd.cut(m, bins=bins, labels=labels)
    return out.astype("object").where(out.notna(), "NA")


def dept_from_code(code, typecode="") -> str:
    """Département from a postcode / INSEE commune code / département code."""
    c = re.sub(r"\s", "", str(code or "")).upper()
    t = low(typecode)
    if not c or c == "NAN":
        return "NA"
    if "region" in t or "pays" in t:
        return "NA"
    if c.startswith(("2A", "2B")):
        return "20"
    if c.startswith(("97", "98")) and len(c) >= 3:
        return c[:3]
    if "dep" in t and len(c) <= 3:
        return c.zfill(2)
    digits = re.sub(r"\D", "", c)
    if len(digits) >= 5 or len(digits) == 2:
        return digits[:2]
    if len(digits) == 1:
        return digits.zfill(2)
    return "NA"


def first_dept(x) -> str:
    """APProch 'département(s)' field: '75|92' -> '75'."""
    s = str(x or "")
    parts = [p for p in re.split(r"[|,;/]", s) if p.strip()]
    if not parts:
        return "NA"
    m = re.search(r"(2A|2B|\d{2,3})", parts[0].upper())
    return dept_from_code(m.group(1), "departement") if m else "NA"


def yes_no(x) -> int:
    """Social/environmental clause fields -> 1 if a clause is present."""
    s = low(x)
    if not s or s in {"nan", "none", "null"}:
        return 0
    if s.startswith(("pas ", "non", "aucun", "false", "0")) or "pas de consideration" in s:
        return 0
    return 1


# Feature columns used by the model (built identically for DECP and APProch)
# procedure_c is not a feature: it is empty for ~88 % of APProch rows but ~12 % of DECP rows,
# so it would skew every upcoming score. It is still used to exclude single-bid-by-design contracts.
CAT_FEATURES = ["cpv_div", "categorie", "amount_band", "duration_bin", "dept"]
# buyer_n (how many contracts a buyer publishes) is left out: it made huge buyers look risky even when their
# own record in the category showed plenty of competition, which reads as a contradiction in the app.
NUM_FEATURES = ["clause_sociale", "clause_env", "buyer_rate", "buyer_cpv_rate", "cpv_rate"]
FEATURES = CAT_FEATURES + NUM_FEATURES
