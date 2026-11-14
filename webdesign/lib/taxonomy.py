"""Pictos, labels and colours used everywhere in webdesign/. Pure functions, no I/O.

    size_of(tranche_code, categorie)   company size (INSEE tranche d'effectifs) -> Size
    sector_of(cpv_div)                 CPV division (2 digits) -> Sector
    buyer_kind_of(cat_juridique, name) buyer nature juridique (INSEE, 4 digits), else its name -> Kind
    amount_style(band)                 amount band label -> (rank, colour)
    chance_style(proba, avg)           chance of a single bid -> (label, colour)
    RECO                               Aller / À étudier / Passer -> picto, colour
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------------------------- palette
TEAL = "#2E9E8F"       # brand (primaryColor)
INK = "#0F172A"
MUTED = "#64748B"
LINE = "#E2E8F0"
PALETTE = ["#2E9E8F", "#6366F1", "#F59E0B", "#EC4899", "#0EA5E9", "#84CC16", "#A855F7", "#F97316",
           "#14B8A6", "#EF4444", "#64748B", "#22C55E"]


@dataclass(frozen=True)
class Tag:
    key: str
    label: str
    emoji: str
    color: str
    hint: str = ""


# ---------------------------------------------------------------------------------------------- company size
# INSEE "tranche d'effectifs salariés" codes
TRANCHES = {
    "NN": ("non renseigné", None, None), "00": ("0 salarié", 0, 0), "01": ("1 ou 2 salariés", 1, 2),
    "02": ("3 à 5 salariés", 3, 5), "03": ("6 à 9 salariés", 6, 9), "11": ("10 à 19 salariés", 10, 19),
    "12": ("20 à 49 salariés", 20, 49), "21": ("50 à 99 salariés", 50, 99), "22": ("100 à 199 salariés", 100, 199),
    "31": ("200 à 249 salariés", 200, 249), "32": ("250 à 499 salariés", 250, 499),
    "41": ("500 à 999 salariés", 500, 999), "42": ("1 000 à 1 999 salariés", 1000, 1999),
    "51": ("2 000 à 4 999 salariés", 2000, 4999), "52": ("5 000 à 9 999 salariés", 5000, 9999),
    "53": ("10 000 salariés et plus", 10000, None),
}

SIZES = [  # (key, label, emoji, people icons 1-5, colour, max employees)
    Tag("micro", "Micro-entreprise", "🌱", "#84CC16", "moins de 10 salariés"),
    Tag("petite", "Petite entreprise", "🌿", "#22C55E", "10 à 49 salariés"),
    Tag("moyenne", "Moyenne entreprise", "🌳", "#2E9E8F", "50 à 249 salariés"),
    Tag("eti", "Entreprise de taille intermédiaire", "🏢", "#6366F1", "250 à 4 999 salariés"),
    Tag("grande", "Grande entreprise", "🏙️", "#A855F7", "5 000 salariés et plus"),
    Tag("inconnue", "Taille non renseignée", "❔", "#94A3B8", ""),
]
_SIZE = {t.key: t for t in SIZES}
SIZE_LEVEL = {"micro": 1, "petite": 2, "moyenne": 3, "eti": 4, "grande": 5, "inconnue": 0}


def size_of(tranche: str | None, categorie: str | None = None) -> Tag:
    """Size from the INSEE headcount band; falls back to the INSEE category (PME / ETI / GE)."""
    lo = TRANCHES.get(str(tranche or "NN"), TRANCHES["NN"])[1]
    if lo is None:
        c = (categorie or "").upper()
        return _SIZE["eti"] if c == "ETI" else _SIZE["grande"] if c == "GE" else _SIZE["inconnue"]
    if lo < 10:
        return _SIZE["micro"]
    if lo < 50:
        return _SIZE["petite"]
    if lo < 250:
        return _SIZE["moyenne"]
    return _SIZE["grande"] if lo >= 5000 else _SIZE["eti"]


def headcount_label(tranche: str | None) -> str:
    return TRANCHES.get(str(tranche or "NN"), TRANCHES["NN"])[0]


# ---------------------------------------------------------------------------------------------- sectors (CPV)
SECTORS = [
    Tag("btp", "Bâtiment et travaux", "🏗️", "#F59E0B"),
    Tag("ingenierie", "Ingénierie et architecture", "📐", "#2E9E8F"),
    Tag("numerique", "Numérique et télécoms", "💻", "#6366F1"),
    Tag("maintenance", "Maintenance et installation", "🔧", "#0EA5E9"),
    Tag("proprete", "Propreté, déchets et environnement", "♻️", "#22C55E"),
    Tag("espaces_verts", "Espaces verts et agriculture", "🌳", "#84CC16"),
    Tag("sante", "Santé et médical", "🩺", "#EC4899"),
    Tag("alimentation", "Alimentation et restauration", "🍽️", "#F97316"),
    Tag("transport", "Transport et véhicules", "🚚", "#14B8A6"),
    Tag("energie", "Énergie et réseaux", "⚡", "#EAB308"),
    Tag("assurance", "Assurance et finance", "🛡️", "#8B5CF6"),
    Tag("services", "Services aux organisations", "🤝", "#64748B"),
    Tag("formation", "Formation et recherche", "🎓", "#A855F7"),
    Tag("culture", "Culture, sport et loisirs", "🎭", "#EF4444"),
    Tag("fournitures", "Fournitures et équipements", "📦", "#78716C"),
    Tag("autre", "Autres", "📋", "#94A3B8"),
]
_SECTOR = {t.key: t for t in SECTORS}
_CPV_TO_SECTOR = {
    "45": "btp", "44": "btp", "43": "btp",
    "71": "ingenierie",
    "72": "numerique", "48": "numerique", "30": "numerique", "32": "numerique", "64": "numerique",
    "50": "maintenance", "51": "maintenance",
    "90": "proprete",
    "77": "espaces_verts", "03": "espaces_verts", "16": "espaces_verts",
    "33": "sante", "85": "sante",
    "15": "alimentation", "55": "alimentation",
    "34": "transport", "60": "transport", "63": "transport",
    "09": "energie", "65": "energie", "31": "energie", "76": "energie",
    "66": "assurance",
    "79": "services", "75": "services", "98": "services", "70": "services",
    "80": "formation", "73": "formation", "38": "formation",
    "92": "culture", "37": "culture", "22": "culture",
    "39": "fournitures", "18": "fournitures", "19": "fournitures", "24": "fournitures", "35": "fournitures",
    "42": "fournitures", "14": "fournitures",
}


def sector_of(cpv_div) -> Tag:
    return _SECTOR[_CPV_TO_SECTOR.get(str(cpv_div or "")[:2], "autre")]


# NAF (company activity) -> same sectors, by NAF division (2 digits)
_NAF_TO_SECTOR = {
    **{d: "btp" for d in ("41", "42", "43")}, "71": "ingenierie",
    **{d: "numerique" for d in ("58", "61", "62", "63")}, "33": "maintenance", "95": "maintenance",
    **{d: "proprete" for d in ("37", "38", "39", "81")}, "01": "espaces_verts", "02": "espaces_verts",
    **{d: "sante" for d in ("86", "87", "88", "21")}, "10": "alimentation", "56": "alimentation",
    **{d: "transport" for d in ("49", "50", "51", "52", "53", "29", "45")}, "35": "energie", "36": "energie",
    **{d: "assurance" for d in ("64", "65", "66")}, "85": "formation", "72": "formation",
    **{d: "culture" for d in ("90", "91", "93", "59", "60")},
    **{d: "services" for d in ("69", "70", "73", "74", "77", "78", "80", "82", "68")},
}


def sector_of_naf(naf) -> Tag:
    d = re.sub(r"\D", "", str(naf or ""))[:2]
    if not d:
        return _SECTOR["autre"]
    return _SECTOR[_NAF_TO_SECTOR.get(d, "fournitures" if "10" <= d <= "33" else "autre")]


# ---------------------------------------------------------------------------------------------- buyer kinds
BUYER_KINDS = [
    Tag("etat", "État et ministères", "🏛️", "#6366F1", "ministères, préfectures, services déconcentrés"),
    Tag("region", "Régions et collectivités", "🗺️", "#8B5CF6", "régions, Corse, collectivités d'outre-mer"),
    Tag("departement", "Départements", "🏞️", "#0EA5E9", "conseils départementaux"),
    Tag("interco", "Intercommunalités et syndicats", "🔗", "#14B8A6", "métropoles, agglomérations, syndicats"),
    Tag("commune", "Communes", "🏠", "#22C55E", "villes, mairies, CCAS"),
    Tag("ecole", "Collèges et lycées", "🏫", "#F59E0B", "un établissement, un bâtiment"),
    Tag("universite", "Universités et recherche", "🎓", "#A855F7", "universités, écoles, organismes de recherche"),
    Tag("hopital", "Hôpitaux et médico-social", "🏥", "#EC4899", "hôpitaux, EHPAD, groupements hospitaliers"),
    Tag("logement", "Logement social", "🏘️", "#F97316", "offices HLM, bailleurs"),
    Tag("operateur", "Entreprises et opérateurs publics", "⚙️", "#64748B", "EPIC, SEM, SPL, SDIS"),
    Tag("autre", "Autres acheteurs publics", "📋", "#94A3B8", ""),
]
_KIND = {t.key: t for t in BUYER_KINDS}


_HOUSING = r"habitat|\bhlm\b|\boph\b|logement|r[eé]sidences?\b"


def _kind_from_cj(cj: str, name: str = "") -> str | None:
    c = re.sub(r"\D", "", str(cj or ""))
    if len(c) != 4:
        return None
    s = str(name or "").lower()
    if c in ("5546", "5547") or (c[0] in "45" and re.search(_HOUSING, s)):
        return "logement"                       # OPH (4140), SA / coop HLM
    if c.startswith("71") or c in ("7389", "7385") or c.startswith("81"):
        return "etat"                           # State, national public bodies, social security (CPAM, CAF...)
    if c == "7229":                             # "other territorial authority": Ville de Paris, Corsica, overseas
        return "commune" if re.search(r"\bville\b|\bcommune\b|\bmairie\b|\bparis\b", s) else "region"
    if c == "7379":
        return "interco"                        # e.g. Île-de-France Mobilités, Sytral
    if c in ("7225", "7230", "7351", "7352"):
        return "region"
    if c == "7220":
        return "departement"
    if c in ("7210", "7312", "7313", "7361", "7362"):
        return "commune"
    if c == "7331":
        return "ecole"
    if c in ("7383", "7384"):
        return "universite"
    if c in ("7364", "7365", "7366", "7367", "7470"):
        return "hopital"
    if c == "7371":
        return "logement"
    if c in ("7372",) or c.startswith(("41", "55", "56", "57")):
        return "operateur"
    if c.startswith("734") or c.startswith("735"):
        return "interco"
    if c.startswith("73") or c.startswith("74"):
        return "autre"
    return None


_NAME_RULES = [  # fallback when the nature juridique is unknown (order matters)
    ("ecole", r"\bcoll[eè]ge\b|\blyc[eé]e\b|\beple\b|\bgreta\b"),
    ("universite", r"universit|\bcrous\b|\bcnrs\b|\binserm\b|\binrae\b|\becole (nationale|normale|centrale)|\bbrgm\b|\bcea\b"),
    ("hopital", r"h[oô]pita|\bchu\b|\bchr\b|centre hospitalier|\bghu?\b|\bght\b|\bhus\b|groupement hospitalier|\bresah\b|\behpad\b|sanitaire|\bars\b"),
    ("logement", _HOUSING),
    ("etat", r"minist|pr[eé]fect|\bdreal\b|\bddt|\bdirection (r[eé]gionale|d[eé]partementale)|arm[eé]e|gendarmerie|\bpolice\b|\bugap\b|rectorat"),
    ("region", r"\br[eé]gion\b|collectivit[eé] (de corse|europ[eé]enne|territoriale)"),
    ("departement", r"d[eé]partement|conseil d[eé]partemental"),
    ("interco", r"communaut[eé]|m[eé]tropole|agglom|\bept\b|syndicat|\bsivom\b|\bsivu\b|\bsictom\b|\bsmictom\b|territoire|"
                r"etablissement public territorial|^(ca|cc|cu)\b"),
    ("commune", r"\bville\b|\bcommune\b|\bmairie\b|\bccas\b|centre communal d.action sociale"),
    ("operateur", r"\bsem\b|\bspl\b|\bsncf\b|\bratp\b|\bepic\b|\bsdis\b|\bport\b|a[eé]roport|\bedf\b|la poste"),
]


def buyer_kind_of(cat_juridique: str | None = None, name: str | None = None) -> Tag:
    k = _kind_from_cj(cat_juridique, name)
    if k is None:
        s = str(name or "").lower()
        k = next((key for key, pat in _NAME_RULES if re.search(pat, s)), "autre")
    return _KIND[k]


# ---------------------------------------------------------------------------------------------- amounts
AMOUNT_ORDER = ["0€ – 40k€", "40k€ – 100k€", "100k€ – 500k€", "500k€ – 1M€", "1M€ – 5M€", "5M€ – 10M€",
                "10M€ – 50M€", "50M€ – 100M€", "+ 100M€"]
AMOUNT_COLORS = ["#E0F2FE", "#BAE6FD", "#7DD3FC", "#38BDF8", "#0EA5E9", "#0284C7", "#0369A1", "#075985", "#0C4A6E"]
AMOUNT_SHORT = ["< 40 k€", "40–100 k€", "100–500 k€", "0,5–1 M€", "1–5 M€", "5–10 M€", "10–50 M€", "50–100 M€", "> 100 M€"]


def _norm_band(b) -> str:
    s = str(b or "").replace(" ", "").replace("-", "–").lower()
    for i, lab in enumerate(AMOUNT_ORDER):
        if lab.replace(" ", "").lower() == s:
            return lab
    # APProch spelling: "100k - 500k€"
    m = re.match(r"^\+?(\d+)([km]?)€?–?(\d+)?([km]?)€?$", s)
    if m:
        lo = float(m.group(1)) * {"k": 1e3, "m": 1e6, "": 1}[m.group(2)]
        for lab, edge in zip(AMOUNT_ORDER, [0, 40e3, 100e3, 500e3, 1e6, 5e6, 10e6, 50e6, 100e6]):
            if lo == edge:
                return lab
    return ""


def amount_style(band) -> tuple[int, str, str]:
    """(rank 0-8 or -1, colour, short label) for an amount band; -1 when unknown (BOAMP has no amount)."""
    lab = _norm_band(band)
    if not lab:
        return -1, "#F1F5F9", "montant inconnu"
    i = AMOUNT_ORDER.index(lab)
    return i, AMOUNT_COLORS[i], AMOUNT_SHORT[i]


def amount_band_of(montant) -> str:
    try:
        v = float(montant)
    except (TypeError, ValueError):
        return ""
    edges = [0, 40e3, 100e3, 500e3, 1e6, 5e6, 10e6, 50e6, 100e6, float("inf")]
    for lab, lo, hi in zip(AMOUNT_ORDER, edges, edges[1:]):
        if lo <= v < hi:
            return lab
    return ""


# ---------------------------------------------------------------------------------------------- chance of a single bid
RECO = {
    "Aller": Tag("Aller", "Aller", "🟢", "#16A34A", "peu de concurrents attendus"),
    "À étudier": Tag("À étudier", "À étudier", "🟡", "#D97706", "à regarder de près"),
    "Passer": Tag("Passer", "Passer", "⚪", "#94A3B8", "concurrence habituelle ou forte"),
}


def chance_style(proba: float, avg: float | None) -> tuple[str, str]:
    """Label and colour for the chance of a single bid, relative to the average (an opportunity for the SME)."""
    r = proba / avg if avg else 1.0
    if r >= 2.0:
        return "très peu de concurrents", "#15803D"
    if r >= 1.5:
        return "peu de concurrents", "#22C55E"
    if r >= 1.0:
        return "concurrence modérée", "#F59E0B"
    if r >= 0.75:
        return "concurrence habituelle", "#94A3B8"
    return "forte concurrence", "#64748B"


def chance_gradient(proba: float, lo: float = 0.05, hi: float = 0.6) -> str:
    """Continuous colour (grey -> teal -> green) for a probability, for heatmaps and bars."""
    t = max(0.0, min(1.0, (proba - lo) / (hi - lo)))
    stops = [(0.0, (203, 213, 225)), (0.5, (46, 158, 143)), (1.0, (21, 128, 61))]
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            u = (t - t0) / (t1 - t0)
            return "#%02X%02X%02X" % tuple(round(a + (b - a) * u) for a, b in zip(c0, c1))
    return "#15803D"
