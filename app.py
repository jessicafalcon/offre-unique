"""QtFetcher (Offre unique project): upcoming public tenders where a company would face little competition.

    python -m streamlit run app.py
Reads only precomputed files: data/clean/scored.parquet, awards_app.parquet (or awards.parquet), artifacts/metrics.json, notes.json
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))
from common import ART, CLEAN, cpv_label  # noqa: E402
from siren import clean_siren, siren_valid  # noqa: E402
from profiles import fit_table, load_all_scored, profile_of, relevant, similar_wins  # noqa: E402
from explain import recommend_row  # noqa: E402

# Share of DECP contracts that report the number of bids (reports/data_check.md). Update if the data changes.
SHARE_LABELLED = os.environ.get("SHARE_LABELLED", "42 %")
# Hosted public copy (see deploy/): HEMICYCLE_LIVE=0 hides the live Hémicycle button (1 credit per click),
# LIVE_NOTES_PER_DAY caps the notes written on demand, all visitors together (0 = no cap).
HEMICYCLE_LIVE = os.environ.get("HEMICYCLE_LIVE", "1") != "0"
NOTES_PER_DAY = int(os.environ.get("LIVE_NOTES_PER_DAY", "0") or 0)

MASCOT_DIR = Path(__file__).parent / "images"
st.set_page_config(page_title="QtFetcher", page_icon=str(MASCOT_DIR / "mascot_64.png"), layout="wide",
                   initial_sidebar_state="collapsed")
MASCOT = "data:image/jpeg;base64," + __import__("base64").b64encode(
    (MASCOT_DIR / "mascot_240.jpg").read_bytes()).decode()


@st.cache_resource  # one shared copy for all visitors (cache_data copied the 840 MB contracts table at every
def load():         # interaction); nothing may modify these tables in place: fit_table() works on a copy
    scored = load_all_scored()
    # Hosted copy: with the slim file (src/build_app_data.py) each company's rows are read on demand, see awards_of()
    awards = None if AWARDS_APP.exists() else pd.read_parquet(CLEAN / "awards.parquet")
    metrics = json.loads((ART / "metrics.json").read_text()) if (ART / "metrics.json").exists() else None
    mb = ART / "metrics_boamp.json"
    metrics_boamp = json.loads(mb.read_text()) if mb.exists() else None
    return scored, awards, metrics, metrics_boamp


AWARDS_APP = CLEAN / "awards_app.parquet"        # same rows as awards.parquet, sorted by company
COMPANY_COUNTS = CLEAN / "company_counts.parquet"  # contracts won per company


@st.cache_data(max_entries=32, show_spinner=False)
def _awards_slim(siren: str) -> pd.DataFrame:
    return pd.read_parquet(AWARDS_APP, filters=[("company_siren", "==", siren)])


def awards_of(siren: str) -> pd.DataFrame:
    """Past contracts to look a company up in: its own rows from the slim file, or the full table if there is none."""
    return awards if awards is not None else _awards_slim(str(siren))


def load_notes() -> dict:
    p = ART / "notes.json"
    return json.loads(p.read_text()) if p.exists() else {}


@st.cache_resource
def _note_budget() -> dict:
    return {"day": None, "n": 0}  # one counter for the whole server


def note_budget_left() -> bool:
    """True if a note may still be written today; counts the call."""
    if not NOTES_PER_DAY:
        return True
    b, today = _note_budget(), pd.Timestamp.today().date()
    if b["day"] != today:
        b.update(day=today, n=0)
    if b["n"] >= NOTES_PER_DAY:
        return False
    b["n"] += 1
    return True


FOLLOWS = ART / "follows.json"

# Fake identifiers found in the contract data (e.g. 123456789 appears on 43 rows)
PLACEHOLDER_SIRENS = {"123456789", "000000000", "111111111", "999999999", "987654321"}


@st.cache_data(ttl=86400, show_spinner=False)
def _register_record(siren9: str) -> dict:
    """Sole-trader flag and size category (PME / ETI / GE) from the public company register.
    Raises if the register is unreachable, so a network blip is never cached (only real answers are)."""
    import requests
    r = requests.get("https://recherche-entreprises.api.gouv.fr/search", params={"q": siren9, "per_page": 1}, timeout=4)
    r.raise_for_status()
    for x in r.json().get("results", []):
        if x.get("siren") == siren9:
            sole = bool((x.get("complements") or {}).get("est_entrepreneur_individuel")) \
                or str(x.get("nature_juridique")) == "1000"
            return {"sole": sole, "categorie": x.get("categorie_entreprise")}
    return {"sole": False, "categorie": None}


def company_size(siren9: str) -> str | None:
    """'PME', 'ETI' or 'GE' per the register; None if unknown or unreachable (then nothing is shown)."""
    try:
        return _register_record(siren9).get("categorie")
    except Exception:
        return None


def is_sole_trader(siren9: str) -> bool | None:
    """Sole trader (entrepreneur individuel) per the public company register. None if the register is unreachable."""
    try:
        return _register_record(siren9)["sole"]
    except Exception:
        return None


# Words that show a name belongs to a company, not a person (used when the register is unreachable)
COMPANY_WORDS = re.compile(
    r"(?i)\b(sas|sasu|sarl|eurl|sa|sca|snc|sci|scop|scic|gie|sem|spl|soci[ée]t[ée]|ste|ets|[ée]tablissements?|groupe|"
    r"entreprise|association|asso|cie|compagnie|france|services?|industries?|international|holding|consulting|"
    r"conseil|ing[ée]nierie|travaux|btp|bureau|cabinet|atelier|agence|syst[èe]mes?|technologies?|solutions?|"
    r"environnement|construction|b[âa]timent|transports?|nettoyage|propret[ée]|restauration|r[ée]seaux?)\b|[&\d()]")


def looks_like_person(name: str | None, n_wins: int) -> bool:
    """Offline fallback: a short name with no company word and few contracts is treated as a possible sole trader."""
    n = str(name or "").strip()
    return bool(n) and not COMPANY_WORDS.search(n) and len(n.split()) <= 3 and n_wins < 10


# Followed tenders are kept per visitor (browser session): with a public link, judges must not share one list
def load_follows() -> dict:
    return st.session_state.setdefault("follows", {})


def save_follows(f: dict) -> None:
    st.session_state["follows"] = f


def days_left(iso) -> str:
    if not iso:
        return ""
    d = (pd.Timestamp(iso).normalize() - pd.Timestamp.now().normalize()).days
    return "clos" if d < 0 else ("dernier jour" if d == 0 else f"J-{d}")


def reco_of(note: str) -> str:
    for w in ("À étudier", "Passer", "Aller"):
        if w in (note or ""):
            return w
    return ""


def render_follows(siren9: str) -> None:
    mine = {k: v for k, v in load_follows().items() if k.startswith(f"{siren9}:")}
    with st.sidebar:
        st.subheader("Appels d'offres suivis")
        if not mine:
            st.caption("Aucun pour l'instant. Cliquez sur « Suivre cet appel d'offres ».")
            return
        for k, v in sorted(mine.items(), key=lambda kv: kv[1].get("due") or "9999"):
            title = v.get("title", "")
            st.markdown(f"**{title if len(title) <= 90 else title[:89] + '…'}**")
            due = fmt_date(v["due"]) if v.get("due") else v.get("when", "")
            parts = [v.get("buyer", ""), due, days_left(v.get("due")),
                     f"{v['risk']} %" if v.get("risk") is not None else "", v.get("reco", "")]
            st.caption(" · ".join(x for x in parts if x))
            a, b = st.columns(2)
            if v.get("url"):
                a.link_button("Voir l'avis", v["url"])
            if b.button("Retirer", key=f"rm_{k}"):
                d = load_follows()
                d.pop(k, None)
                save_follows(d)
                st.rerun()
            st.divider()
        st.caption("Prochaine étape : rappels avant l'échéance et alerte si l'avis est modifié.")


def editions_table(eds: list[dict]) -> None:
    e = pd.DataFrame(eds)
    past = pd.DataFrame({
        "Date": pd.to_datetime(e["date"], errors="coerce").dt.strftime("%d/%m/%Y").fillna(""),
        "Offres": e["offres"].map(lambda v: "" if v is None or pd.isna(v) or v <= 0 else str(int(v))),
        "Objet": e["objet"].fillna("").astype(str),
        "Titulaire": (e["titulaire_nom"] if "titulaire_nom" in e else pd.Series("", index=e.index))
        .fillna("—").replace({"None": "—", "": "—"}).astype(str),
    })
    st.dataframe(past, hide_index=True, width="stretch", column_config={
        "Date": st.column_config.TextColumn(width=98),
        "Offres": st.column_config.TextColumn(width=64, help="Nombre d'offres reçues"),
        "Objet": st.column_config.TextColumn(width=170),
        "Titulaire": st.column_config.TextColumn(width=120),
    })


def render_buyer_history(r: pd.Series) -> None:
    """Latest comparable contracts of the buyer, live from Hémicycle (cached), with the local DECP as fallback."""
    from hemicycle_history import CACHE, NAMES, SIRET_MAP, history_for, load_json
    code = str(r.get("code"))
    h = load_json(CACHE).get(code)
    st.markdown("**Derniers marchés comparables de cet acheteur**")
    if h and h.get("editions"):
        when_ = pd.Timestamp(h["fetched_at"]).strftime("%d/%m/%Y à %H:%M")
        st.caption(f":material/sync: **En direct d'Hémicycle**, consulté le {when_}  \n"
                   "Source : jeu « Marchés publics notifiés », Licence Ouverte 2.0")
        editions_table(h["editions"])
    else:
        eds = json.loads(r.get("hist_editions") or "[]")
        if eds:
            st.caption("Source : DECP consolidées (data.gouv.fr), Licence Ouverte 2.0")
            editions_table(eds)
        else:
            st.caption("Aucun marché comparable de cet acheteur dans les données.")
    if HEMICYCLE_LIVE and st.button("Actualiser via Hémicycle" if h else "Interroger Hémicycle", key=f"hemi_{code}",
                 help="Interroge l'API Hémicycle en direct (1 crédit par établissement de l'acheteur)."):
        try:
            new = history_for(r, load_json(SIRET_MAP), load_json(NAMES))
            if new is None:
                st.caption("Acheteur sans établissement connu : rien à interroger.")
            else:
                cache = load_json(CACHE)
                cache[code] = new
                CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
                st.rerun()
        except Exception as e:  # keep the demo alive without network
            st.caption(f"Hémicycle injoignable ({e.__class__.__name__}) : affichage des données en cache.")


def fmt_date(d) -> str:
    return "" if pd.isna(d) else pd.Timestamp(d).strftime("%d/%m/%Y")


def fr_num(x: float) -> str:
    """5.0 -> '5', 1.25 -> '1,3' (French decimal comma)."""
    x = round(float(x), 1)
    return str(int(x)) if x == int(x) else f"{x:.1f}".replace(".", ",")


def fr_int(n: int) -> str:
    return f"{int(n):,}".replace(",", " ")


def when(r: pd.Series) -> str:
    if pd.notna(r.get("due_date")):
        return f"{fmt_date(r['due_date'])} · {days_left(r['due_date'])}"  # e.g. 30/11/2026 · J-16
    if pd.notna(r.get("pub_date")):
        return "publication " + pd.Timestamp(r["pub_date"]).strftime("%m/%Y")
    return ""


def duration_text(x) -> str:
    s = str(x or "").strip()
    if not s or s in {"None", "nan"}:
        return ""
    return f"{s} mois" if re.fullmatch(r"\d+(?:[.,]\d+)?", s) else s


def fact_sentences(r: pd.Series, siren: str = "") -> list[str]:
    out = []
    n, nd = int(r["n_match"]), int(r["n_match_dept"])
    contrats = "contrat passé" if n == 1 else "contrats passés"
    s = f"Correspond à {n} de vos {contrats}"
    out.append(s + (f", dont {nd} dans ce département." if nd and nd != n else
                    (" dans ce département." if nd else ".")))
    eds = json.loads(r.get("hist_editions") or "[]")
    offers = [e["offres"] for e in eds[:3] if e.get("offres") is not None]
    hist_n = int(r.get("hist_n", 0))
    if offers and all(o == 1 for o in offers):
        out.append(f"Les {len(offers)} derniers marchés comparables de cet acheteur n'ont reçu qu'une offre."
                   if len(offers) > 1 else "Le dernier marché comparable de cet acheteur n'a reçu qu'une offre.")
    elif hist_n > 0 and pd.notna(r.get("hist_single_share")):
        share = round(100 * float(r["hist_single_share"]))
        n_lab = int(r.get("hist_n_lab") or hist_n)
        marches = ("marché comparable dont le nombre d'offres est connu" if n_lab == 1
                   else "marchés comparables dont le nombre d'offres est connu")
        mean = ""
        if pd.notna(r.get("hist_mean_offers")):
            m = float(r["hist_mean_offers"])
            mean = f" ({fr_num(m)} {'offre' if m < 2 else 'offres'} en moyenne)"
        out.append(f"Sur ses {n_lab} {marches}, cet acheteur n'a reçu qu'une offre dans {share} % des cas{mean}.")
    elif hist_n > 0:
        marches = "un marché comparable" if hist_n == 1 else f"{hist_n} marchés comparables"
        out.append(f"Cet acheteur a passé {marches}, sans nombre d'offres renseigné.")
    else:
        out.append("Aucun marché comparable de cet acheteur dans les données.")
    streak = int(r.get("incumbent_streak", 0))
    inc = str(r.get("incumbent_siren") or "").replace(".0", "")[:9]
    if siren and inc == str(siren)[:9]:
        out.append("Vous êtes le titulaire sortant : ce marché est un renouvellement à défendre.")
    elif streak >= 2:
        out.append(f"Le même titulaire a gagné les {streak} dernières fois.")
    elif hist_n > 0:
        out.append("Pas de titulaire installé sur ce type de marché.")
    return out


scored, awards, metrics, metrics_boamp = load()

# "Essayez avec" examples: SMEs in different sectors, all checked (legal entities, open tenders, notes pre-written)
EXAMPLES = [("Point Contrôles", "834709248"), ("Bati Recyclage", "481447951"), ("Adimeo", "480980358")]
NON_DIFFUSIBLE = re.compile(r"(?i)non[- ]diffusible|donn[ée]es personnelles")


def _show_reco(t: pd.DataFrame, siren: str, reco: str) -> None:
    """Banner shortcut: filter the list on one recommendation, switching to the list type that has some."""
    kinds = [k for k in ("BOAMP", "APProch") if ((t["source"] == k) & (t["reco"] == reco)).any()]
    if not kinds:
        return
    st.session_state[f"kind_{siren}"] = kinds[0]
    for k in kinds:  # only where the option exists, else Streamlit rejects the value
        st.session_state[f"flt_{siren}_{k}"] = reco


def _pick_example(s9: str) -> None:
    st.session_state["q"] = s9


def _norm(x) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", str(x or "")).encode("ascii", "ignore").decode().lower()


@st.cache_data(show_spinner=False)
def company_index(_awards: pd.DataFrame | None) -> pd.DataFrame:
    """Companies that won public contracts: SIREN, usual name, number of contracts. Built once, shared by visitors."""
    names = json.loads((ART / "company_names.json").read_text()) if (ART / "company_names.json").exists() else {}
    if _awards is None:
        n = pd.read_parquet(COMPANY_COUNTS).set_index("siren")["n"]
    else:
        n = _awards["company_siren"].value_counts()
    d = pd.DataFrame({"siren": n.index.astype(str), "n": n.to_numpy()})
    d["name"] = d["siren"].map(names)
    d = d.dropna(subset=["name"])
    d = d[d["siren"].map(siren_valid) & ~d["name"].str.contains(NON_DIFFUSIBLE)]  # opted out of publication
    # names that look like a person's (possible sole traders) are not listed in search results
    d = d[[not looks_like_person(nm, k) for nm, k in zip(d["name"], d["n"])]]
    d["key"] = d["name"].map(_norm)
    return d.sort_values("n", ascending=False).reset_index(drop=True)


def search_companies(idx: pd.DataFrame, q: str, k: int = 12) -> pd.DataFrame:
    words = [w for w in re.split(r"\W+", _norm(q)) if len(w) >= 2]
    if not words:
        return idx.iloc[0:0]
    m = pd.Series(True, index=idx.index)
    for w in words:
        m &= idx["key"].str.contains(w, regex=False)
    return idx[m].head(k)
has_boamp = "source" in scored and (scored["source"] == "BOAMP").any()
avg = metrics["test_single_bid_rate"] if metrics else None

# Recommendation badges: always the word, plus an icon and a colour (never colour alone)
RECO_STYLE = {"Aller": ("green", ":material/check_circle:"), "À étudier": ("orange", ":material/help:"),
              "Passer": ("gray", ":material/do_not_disturb_on:")}
RECOS = ("Aller", "À étudier", "Passer")
# One icon per CPV division (first 2 digits), to recognise a trade at a glance
TRADE_ICONS = {
    "03": "agriculture", "09": "bolt", "14": "landscape", "15": "restaurant", "16": "agriculture", "18": "checkroom",
    "19": "checkroom", "22": "print", "24": "science", "30": "computer", "31": "electrical_services",
    "32": "cell_tower", "33": "medical_services", "34": "directions_car", "35": "shield", "37": "sports_soccer",
    "38": "biotech", "39": "chair", "41": "water_drop", "42": "precision_manufacturing", "43": "construction",
    "44": "foundation", "45": "construction", "48": "terminal", "50": "build", "51": "handyman", "55": "restaurant",
    "60": "local_shipping", "63": "warehouse", "64": "mail", "65": "water_drop", "66": "account_balance",
    "70": "apartment", "71": "architecture", "72": "computer", "73": "science", "75": "account_balance",
    "76": "oil_barrel", "77": "park", "79": "business_center", "80": "school", "85": "health_and_safety",
    "90": "recycling", "92": "theater_comedy", "98": "work",
}
SIZE_LABEL = {"PME": "PME", "ETI": "ETI", "GE": "Grande entreprise"}


def trade_of(prof: dict) -> tuple[str, str]:
    """Main trade(s): CPV divisions with at least 15 % of the company's wins (at least one)."""
    divs = [k for k in prof["cpv_div"] if k != "NA"]
    main = [k for k in divs if prof["cpv_div"][k] >= 0.15][:2] or divs[:1]
    if not main:
        return ":material/work:", ""
    return f":material/{TRADE_ICONS.get(main[0], 'work')}:", ", ".join(cpv_label(k) for k in main)


def date_only(r: pd.Series) -> str:
    """List column 'Date limite': the deadline when known (projects show 'Publication prévue' separately)."""
    if pd.notna(r.get("due_date")):
        return f"{pd.Timestamp(r['due_date']):%d/%m/%Y}"
    return ""


def countdown(r: pd.Series) -> str:
    """List column 'Délai': J-16 when the deadline is within 4 months, else empty."""
    if pd.notna(r.get("due_date")):
        d = (pd.Timestamp(r["due_date"]).normalize() - pd.Timestamp.now().normalize()).days
        return days_left(r["due_date"]) if d <= 120 else ""
    return ""


def buyer_city(r: pd.Series) -> str:
    """City of the buyer's registered address (SIRENE). Left out for multi-site buyers (State, regions…)."""
    if r.get("buyer_multi_site"):
        return ""
    m = re.search(r"\b\d{5}\s+(.+)$", str(r.get("buyer_address") or ""))
    return re.sub(r"(?i)\s+cedex.*$", "", m.group(1)).strip().title() if m else ""


def render_detail(r: pd.Series, prof: dict) -> None:
    st.markdown(f"#### {html.unescape(str(r.get('libelle') or 'Achat sans titre'))}")
    reco = str(r.get("reco") or "")
    badges = []
    if reco in RECO_STYLE:
        color, icon = RECO_STYLE[reco]
        badges.append(f":{color}-badge[{icon} {reco}]")
    badges.append(":blue-badge[Ouvert maintenant · BOAMP]" if r.get("source") == "BOAMP"
                  else ":violet-badge[Projet d'achat · APProch]")
    st.container(key="badges").markdown(" ".join(badges))

    buyer = html.unescape(r["buyer_name"]) if isinstance(r.get("buyer_name"), str) else f"SIREN {r.get('buyer_siren')}"
    city = buyer_city(r)
    btype = r.get("buyer_type")
    facts_rows = [("Acheteur", buyer + (f" ({city})" if city else "")),
                  ("Type d'acheteur", btype if isinstance(btype, str) and btype != "Inconnu" else ""),
                  ("Taille", r.get("taille_marche") if isinstance(r.get("taille_marche"), str) else ""),
                  ("Durée", duration_text(r.get("duree_previsionnelle_du_marche")))]
    if r.get("source") != "BOAMP" and pd.notna(r.get("pub_date")):  # project: planned publication (no start date in APProch)
        facts_rows.append(("Publication prévue", fmt_date(r["pub_date"])))
    if pd.notna(r.get("due_date")):
        d = (pd.Timestamp(r["due_date"]).normalize() - pd.Timestamp.now().normalize()).days
        left = "dernier jour" if d == 0 else (f"dans {d} jour{'s' if d > 1 else ''}" if d > 0 else "clos")
        facts_rows.append(("Date limite", f"{fmt_date(r['due_date'])} ({left})"))
    st.html('<table class="ou-summary ou-compact">' + "".join(
        f"<tr><th>{k}</th><td>{html.escape(str(v))}</td></tr>"
        for k, v in facts_rows if v and str(v) not in {"None", "nan"}) + "</table>")
    if isinstance(r.get("procedure_note"), str):
        st.caption(f":material/info: {r['procedure_note']}.")

    risk = round(100 * float(r["proba"]))
    risk_line = f"**{risk} %** de chances qu'une seule offre soit déposée"
    if avg:
        risk_line += f" ({fr_num(float(r['proba']) / avg)} × la moyenne)"
    with st.container(key="risk"):
        st.markdown(risk_line)

    notes = load_notes()
    key = f"{prof['siren']}:{r.get('code')}"
    note = notes.get(key)
    has_note = bool(note and note.get("verified") and note.get("note", "").strip())
    if has_note:
        with st.container(key="note"):  # GOV.UK inset text
            st.write(note["note"])
    elif st.button("Rédiger la note go / no-go", icon=":material/edit_note:"):
        if not note_budget_left():
            st.caption("Le quota de notes rédigées à la demande est atteint pour aujourd'hui. "
                       "Les faits ci-dessous et la recommandation restent valables.")
        else:
            try:
                from explain import facts_for, generate, save_cache
                with st.spinner("Rédaction de la note par Gemma 4 (Featherless), chaque chiffre vérifié… environ 10 secondes"):
                    res = generate(facts_for(r, prof))
                notes[key] = res
                save_cache(notes)
                st.write(res["note"] if res["verified"] else
                         "Le modèle a proposé une note qui citait un chiffre absent des données : elle a été écartée. "
                         "Les faits ci-dessous et la recommandation restent valables.")
            except Exception as e:  # keep the demo alive if the API fails
                st.caption(f"Note indisponible ({e.__class__.__name__}).")

    c1 = c2 = st.container(horizontal=True, gap="small")  # buttons at their natural width
    if key in load_follows():
        c1.button("Suivi", icon=":material/check:", disabled=True, key=f"fd_{key}")
    elif c1.button("Suivre cet appel d'offres", icon=":material/bookmark_add:", key=f"f_{key}"):
        link = r.get("lien_vers_la_consultation")
        f = load_follows()
        f[key] = {
            "title": str(r.get("libelle") or "Achat sans titre"),
            "buyer": buyer,
            "due": pd.Timestamp(r["due_date"]).isoformat() if pd.notna(r.get("due_date")) else None,
            "when": when(r),
            "risk": risk,
            "reco": reco or reco_of(note.get("note", "") if note else ""),
            "url": link if isinstance(link, str) and link.startswith("http") else "",
            "source": str(r.get("source") or ""),
            "followed_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        }
        save_follows(f)
        st.toast("Ajouté à vos appels d'offres suivis : ouvrez le menu à gauche (») pour les retrouver.",
                 icon=":material/bookmark_added:")
        st.rerun()
    if isinstance(r.get("lien_vers_la_consultation"), str) and r["lien_vers_la_consultation"].startswith("http"):
        c2.link_button("Voir l'avis BOAMP" if r.get("source") == "BOAMP" else "Voir la consultation",
                       r["lien_vers_la_consultation"], icon=":material/open_in_new:")

    # Since 12fd910 the notes cite the score, the average, the company's similar contracts and the buyer's
    # single-bid share: the full fact list goes behind a click when a note is shown, open when there is none.
    facts = fact_sentences(r, prof["siren"])
    holder = [s for s in facts if s.startswith(("Vous êtes le titulaire", "Le même titulaire"))]
    if has_note and holder:  # not always in the note: keep it visible
        st.markdown(holder[0])
    with st.expander("Les faits derrière la note", expanded=not has_note):
        st.markdown("\n".join(f"- {s}" for s in facts))
    mine, n_mine = similar_wins(awards_of(prof["siren"]), prof["siren"], r)
    if n_mine:
        with st.expander(f"Vos contrats similaires ({n_mine})"):
            st.dataframe(pd.DataFrame({
                "Date": pd.to_datetime(mine["date"], errors="coerce").dt.strftime("%d/%m/%Y").fillna(""),
                "Acheteur": mine["acheteur_nom"].fillna("").astype(str),
                "Objet": mine["objet"].fillna("").astype(str),
                "Dép.": mine["dept"].astype(str).replace({"NA": ""}),
                "Montant": mine["montant"].map(lambda v: "" if pd.isna(v) or v <= 0 else f"{fr_int(round(v))} €"),
                "Offres": mine["offres"].map(lambda v: "" if pd.isna(v) or v <= 0 else str(int(v))),
            }), hide_index=True, width="stretch", column_config={
                "Date": st.column_config.TextColumn(width="small"),
                "Objet": st.column_config.TextColumn(width="large"),
                "Dép.": st.column_config.TextColumn(width="small"),
            })
            st.caption("Vos marchés gagnés dans la même catégorie d'achat, ce département d'abord.  \n"
                       "Source : DECP consolidées (data.gouv.fr), Licence Ouverte 2.0")
    render_buyer_history(r)


# Small custom CSS: Streamlit has no setting for input border thickness, focus colour, page width or panel tints.
# GOV.UK patterns (start page, hint text, focus ring, inset text), not its brand. Missing selectors fail silently.
st.html("""<style>
/* "Pie bavarde" palette: black #0B0C0C, navy #1F3A7A, white; light navy tint #EEF1F7 for panels */
.ou-header {background:#0b0c0c; color:#fff; padding:1.4rem 1.6rem; margin:-.5rem 0 .5rem 0; border-bottom:8px solid #1f3a7a; display:flex; align-items:center; gap:1rem;}
.ou-header img {width:132px; height:132px; border-radius:50%; object-fit:cover; border:3px solid #fff; flex:none;}
.ou-welcome {display:flex; align-items:center; gap:1.25rem; margin-bottom:.4rem;}
.ou-welcome img {width:110px; height:110px; border-radius:50%; object-fit:cover; border:3px solid #fff; flex:none;}
.ou-welcome h2 {font-size:2.1rem; font-weight:700; line-height:1.15; margin:0 0 .3rem 0; padding:0; color:#0b0c0c;}
@media (max-width:640px) {.ou-welcome img {width:72px; height:72px;}}
.ou-compact {font-size:1rem; margin:.2rem 0 .6rem 0;}
.ou-compact th, .ou-compact td {padding:.32rem .5rem .32rem 0;}
.ou-compact th {width:34%;}
[data-testid="stExpander"] summary p {font-size:1.15rem !important; font-weight:600;}
[data-testid="stExpander"] summary [data-testid="stIconMaterial"] {font-size:1.4rem !important;}
[data-testid="stButtonGroup"] button p {font-size:1.05rem !important;}
.stApp [data-testid="stBaseButton-secondary"] p, .stApp [data-testid="stBaseLinkButton-secondary"] p
  {font-size:1.05rem !important;}
.ou-splash {min-height:82vh; display:flex; flex-direction:column; align-items:center; justify-content:center;
  text-align:center; padding:1rem;}
.ou-splash img {width:min(320px,62vw); height:auto; border-radius:50%; border:6px solid #1f3a7a;}
.ou-splash h1 {font-size:clamp(3.2rem,9vw,6rem); font-weight:800; color:#0b0c0c; margin:.7rem 0 .2rem 0; padding:0;
  line-height:1;}
.ou-splash .motto {font-size:clamp(1.9rem,4.2vw,3rem); font-weight:700; color:#1f3a7a; max-width:950px; margin:.4rem 0;
  line-height:1.25;}
.ou-splash .what {font-size:clamp(1.15rem,2vw,1.4rem); color:#0b0c0c; max-width:780px; margin:.6rem 0 0 0; line-height:1.5;}
.ou-splash .go {margin-top:2rem; font-size:1.25rem; font-weight:700; color:#fff; background:#1f3a7a; padding:.7rem 1.4rem;
  box-shadow:0 3px 0 #0b0c0c;}
.st-key-enter {position:fixed; inset:0; z-index:1000;}
.st-key-enter button {width:100vw; height:100vh; opacity:0; cursor:pointer; border:0;}
.st-key-enter button:focus-visible {opacity:1; background:transparent; color:transparent; outline:6px solid #ffdd00 !important;
  outline-offset:-6px;}
.ou-header b {font-size:3.4rem; letter-spacing:.01em; line-height:1.05;}
.ou-header span {display:block; opacity:.95; font-size:1.55rem; margin-top:.4rem;}
.st-key-start {background:#eef1f7; padding:1.25rem 1.5rem 1rem 1.5rem; border-radius:0;}
.st-key-start h2 {font-size:2.1rem; font-weight:700; padding-top:0; line-height:1.15;}
.ou-lead {font-size:1.2rem; margin:.25rem 0 .9rem 0; color:#0b0c0c;}
.ou-label {font-size:1.3rem; font-weight:700; margin:0; color:#0b0c0c;}
.st-key-q [data-testid="stTextInputRootElement"] {border:2px solid #0b0c0c !important; border-radius:0 !important;
  background:#fff !important; min-height:3.4rem;}
.st-key-q [data-testid="stTextInputRootElement"]:focus-within {outline:3px solid #ffdd00; outline-offset:0;
  box-shadow:inset 0 0 0 2px #0b0c0c;}
.st-key-q [data-testid="stTextInputField"] {font-size:1.35rem !important; color:#0b0c0c; background:#fff !important;}
.st-key-go button {min-height:3.4rem; border-radius:0; font-weight:700; box-shadow:0 3px 0 #0b0c0c;}
.st-key-go button p, .st-key-go button span {font-size:1.15rem !important; font-weight:700; color:#fff !important;}
[class*="st-key-ex_"] button p {color:#1f3a7a; text-decoration:underline; text-underline-offset:3px; font-size:1.05rem;}
[class*="st-key-ex_"] button:hover p {color:#0b0c0c; text-decoration-thickness:3px;}
.st-key-detail h4 {font-size:1.35rem; line-height:1.3;}
.ou-summary {border-collapse:collapse; width:100%; font-size:1.08rem; color:#0b0c0c;}
.ou-summary th, .ou-summary td {border-bottom:1px solid #b1b4b6; padding:.55rem .5rem .55rem 0; text-align:left;
  vertical-align:middle;}
.ou-summary th {width:36%; font-weight:700;}
.ou-icon {font-family:"Material Symbols Rounded"; font-size:1.3rem; vertical-align:-.25rem; margin-right:.35rem;
  color:#1f3a7a; font-weight:normal;}
.st-key-banner {background:#eef1f7; border-left:8px solid #1f3a7a; padding:1.1rem 1.25rem;}
.st-key-banner strong {font-size:1.45rem; line-height:1.3; color:#0b0c0c;}
.st-key-banner p {font-size:1.15rem !important; color:#0b0c0c;}
[data-testid="stMainBlockContainer"] {max-width:1560px;}
.stApp, .stApp [data-testid="stMarkdownContainer"] {color:#0b0c0c;}
.stApp [data-testid="stMarkdown"] p, .stApp [data-testid="stMarkdown"] li {font-size:1.08rem; line-height:1.55;}
.stApp [data-testid="stCaptionContainer"], .stApp [data-testid="stCaptionContainer"] p {font-size:1.04rem;
  color:#2b2f33 !important; opacity:1 !important;}
.stApp [data-testid="stWidgetLabel"] p {color:#0b0c0c !important; font-size:1.1rem !important; font-weight:600;}
[data-testid="stSidebar"] p, [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {font-size:1.05rem !important;}
[data-testid="stSidebar"] h3 {font-size:1.4rem;}
[data-testid="stTooltipContent"] p, [data-baseweb="tooltip"] p {font-size:1rem !important;}
.st-key-badges p {font-size:1.12rem !important;}
.st-key-badges span {font-size:1.05rem !important; padding:.15rem .45rem;}
.ou-index {display:flex; flex-wrap:wrap; gap:.4rem 1.4rem; border-left:6px solid #1f3a7a; background:#eef1f7;
  padding:.8rem 1.1rem; margin:.5rem 0 .5rem 0; font-size:1.05rem;}
.ou-index span {font-weight:800; width:100%; color:#0b0c0c;}
.ou-index a {color:#1f3a7a; text-decoration:underline; text-underline-offset:3px; font-weight:600;}
.ou-kicker {scroll-margin-top:4rem;}
[class*="st-key-m_"], [class*="st-key-r_"] {padding:.9rem 1.1rem; height:100%;}
[class*="st-key-m_"] [data-testid="stMetricLabel"] p, [class*="st-key-r_"] [data-testid="stMetricLabel"] p
  {font-size:1.25rem !important; font-weight:800; color:#0b0c0c !important;}
[class*="st-key-m_"] [data-testid="stMetricValue"], [class*="st-key-r_"] [data-testid="stMetricValue"] {font-size:2.6rem; font-weight:800;}
.st-key-m_ours {background:#1f3a7a; border:3px solid #0b0c0c;}
.st-key-m_ours [data-testid="stMetricLabel"] p, .st-key-m_ours [data-testid="stMetricValue"],
  .st-key-m_ours [data-testid="stMetricValue"] div {color:#fff !important;}
.st-key-m_base1, .st-key-m_base2 {background:#f3f2f1; border:1px solid #b1b4b6;}
.st-key-r_go {background:#e7f4ec; border-left:10px solid #00703c;}
.st-key-r_go [data-testid="stMetricLabel"] p, .st-key-r_go [data-testid="stMetricValue"] div {color:#005a30 !important;}
.st-key-r_look {background:#fff4e0; border-left:10px solid #f0a000;}
.st-key-r_look [data-testid="stMetricLabel"] p, .st-key-r_look [data-testid="stMetricValue"] div {color:#7a4600 !important;}
.st-key-r_skip {background:#f3f2f1; border-left:10px solid #6f777b;}
.st-key-r_skip [data-testid="stMetricLabel"] p, .st-key-r_skip [data-testid="stMetricValue"] div {color:#383f43 !important;}
.stApp [data-testid="stMarkdownContainer"] a {color:#1f3a7a; text-underline-offset:3px;}
.stApp button:focus-visible, .stApp a:focus-visible {outline:3px solid #ffdd00 !important; outline-offset:0;}
[data-testid="stTab"] {padding:.6rem 1.1rem !important; height:auto !important;}
[data-testid="stTab"] p {font-size:1.35rem !important; font-weight:700;}
[data-testid="stTab"][aria-selected="true"] p {color:#1f3a7a !important;}
.st-key-note {border-left:8px solid #b1b4b6; padding:.3rem 0 .3rem 1.1rem; margin:.25rem 0;}
.st-key-note p {font-size:1.15rem !important; line-height:1.55 !important;}
.st-key-risk p {font-size:1.25rem !important;}
.st-key-company {border-radius:0;}
/* "Comment ça marche": a story in chapters */
.ou-hero {background:#0b0c0c; color:#fff; padding:1.6rem 1.75rem; border-left:8px solid #1f3a7a; margin:.5rem 0 1rem 0;}
.ou-hero .big {font-size:3.4rem; font-weight:800; line-height:1; display:block;}
.ou-hero .txt {font-size:1.35rem; font-weight:600; display:block; margin-top:.5rem;}
.ou-hero .sub {font-size:1.2rem; opacity:.95; display:block; margin-top:.7rem; line-height:1.5;}
.ou-kicker {color:#1f3a7a; font-weight:800; letter-spacing:.05em; font-size:1.45rem; text-transform:uppercase; margin:2.2rem 0 .2rem 0; padding-bottom:.35rem; border-bottom:3px solid #1f3a7a;}
.st-key-steps [data-testid="stColumn"] {background:#eef1f7; padding:1rem 1.1rem; border-top:6px solid #1f3a7a;}
.st-key-steps strong {font-size:1.25rem;}
.st-key-steps p {font-size:1.12rem !important;}
</style>""")
# Welcome page: name, motto, what it does, the mascot. A click anywhere (an invisible full-screen button, also
# reachable with Tab + Enter) enters the app; the choice is kept for the visit (session state).
MOTTO = "Tant pie pour vos concurrents\u202f!"  # pun: "tant pis" + the magpie ("pie") mascot
if not st.session_state.get("entered"):
    big = "data:image/jpeg;base64," + __import__("base64").b64encode((MASCOT_DIR / "mascot_480.jpg").read_bytes()).decode()
    st.html(f'<div class="ou-splash"><img src="{big}" alt="Mascotte QtFetcher, une pie bavarde">'
            f'<h1>QtFetcher</h1><p class="motto">{MOTTO}</p>'
            '<p class="what">Entrez le SIREN de votre entreprise : QtFetcher trouve les appels d\'offres de votre métier '
            'qui risquent de ne recevoir qu\'une seule offre, et vous dit lesquels valent votre candidature.</p>'
            '<p class="go">Cliquez n\'importe où pour commencer →</p></div>')
    st.button("Commencer", key="enter", on_click=lambda: st.session_state.update(entered=True))
    st.stop()

st.html(f'<div class="ou-header"><img src="{MASCOT}" alt="Mascotte QtFetcher, une pie bavarde">'
        f'<div><b>QtFetcher</b><span>{MOTTO}</span></div></div>')

tab_main, tab_proof = st.tabs(["Appels d'offres", "Comment ça marche"])

with tab_proof:
    # A story in six short chapters: the problem, the tool, the proof, the notes, who it is for, the limits.
    if not metrics:
        st.write("Lancez `python src/train.py` pour générer les résultats.")
    else:
        res = metrics["results"]
        avg_pct = round(100 * avg)
        n_test = fr_int(metrics["n_test"])
        test_years = f"{metrics['test_years'][0]}–{metrics['test_years'][1]}"

        # 1. The problem
        chapters = ["Le constat", "Ce que fait QtFetcher", "Peut-on s'y fier ?", "Qui écrit les notes ?",
                    "Pour qui ?", "Ce que l'outil ne dit pas"]
        st.html('<nav class="ou-index"><span>Sommaire</span>' + "".join(
            f'<a href="#ch{i}">{i} · {html.escape(c)}</a>' for i, c in enumerate(chapters, 1)) + "</nav>")
        st.html('<p class="ou-kicker" id="ch1">1 · Le constat</p>'
                f'<div class="ou-hero"><span class="big">1 marché sur 5</span>'
                '<span class="txt">ne reçoit qu\'une seule offre.</span>'
                f'<span class="sub">{avg_pct} % des {n_test} marchés publics de {test_years} dont on connaît le nombre '
                'd\'offres. Moins de candidats, c\'est moins de choix pour l\'acheteur public, et des contrats que les '
                'PME ne voient pas passer.</span></div>')

        # 2. What the tool does
        st.html('<p class="ou-kicker" id="ch2">2 · Ce que fait QtFetcher</p>')
        st.markdown("### Montrer à une PME les marchés où sa candidature compte le plus")
        with st.container(key="steps"):
            s1, s2, s3 = st.columns(3, gap="medium")
            s1.markdown("**:material/badge: Votre SIREN**\n\nVos marchés gagnés disent votre métier et vos départements.")
            s2.markdown("**:material/travel_explore: Vos appels d'offres**\n\nCeux de votre métier : ouverts maintenant "
                        "(BOAMP) et à venir (APProch).")
            s3.markdown("**:material/fact_check: Une recommandation**\n\nLa chance d'offre unique, puis Aller, À étudier "
                        "ou Passer, avec une note vérifiée.")

        # 3. The proof
        st.html('<p class="ou-kicker" id="ch3">3 · Peut-on s\'y fier ?</p>')
        st.markdown(f"### Testé sur {n_test} marchés que le modèle n'avait jamais vus")
        st.caption(f"Appris sur {metrics['train_years'][0]}–{metrics['train_years'][1]}, testé sur {test_years}. "
                   "Parmi les 10 % de marchés que chaque méthode juge les plus susceptibles de n'avoir qu'une offre, "
                   "part de ceux qui n'en ont reçu qu'une :")
        c1, c2, c3 = st.columns(3)
        c1.container(key="m_ours").metric("Notre score", f"{round(100 * res['model']['precision_top10'])} %")
        c2.container(key="m_base1").metric("Historique de l'acheteur seul",
                                           f"{round(100 * res['baseline_buyer_history']['precision_top10'])} %")
        c3.container(key="m_base2").metric("Moyenne, sans score", f"{avg_pct} %")
        bt_p = ART / "rules_backtest.json"
        bt = json.loads(bt_p.read_text()) if bt_p.exists() else {}
        g = bt.get("main", {}).get("groups", {})
        if g:
            st.caption(f"Et les recommandations elles-mêmes, sur les marchés {bt['years']} : part de ceux qui n'ont reçu "
                       "qu'une offre.")
            k1, k2, k3 = st.columns(3)
            for col, k, key in zip((k1, k2, k3), ("Aller", "À étudier", "Passer"), ("r_go", "r_look", "r_skip")):
                col.container(key=key).metric(f"« {k} »", f"{round(100 * g[k]['single_rate'])} %", help=f"{fr_int(g[k]['n'])} marchés")
        with st.expander("Détail technique"):
            names = {"model": "Notre score", "baseline_buyer_history": "Historique de l'acheteur",
                     "baseline_cpv_category": "Taux de la catégorie"}
            tbl = pd.DataFrame({names[k]: v for k, v in res.items()}).T
            st.dataframe(pd.DataFrame({
                "AUC": tbl["auc"].round(3),
                "Précision top 10 %": (100 * tbl["precision_top10"]).round(1).astype(str) + " %",
                "Brier": tbl["brier"].round(3),
            }), width="stretch")
            st.caption("AUC : capacité à classer les marchés du plus au moins susceptible d'offre unique (0,5 = hasard). "
                       "Brier : erreur des probabilités (plus bas = mieux).")
            if g:
                st.caption(f"Recommandations : seuils et calibration fixés sur {bt['fit_years']}, avant de regarder "
                           f"{bt['years']} ; sans la condition « déjà gagné ce métier dans ce département », qui dépend de "
                           "l'entreprise. Les pourcentages affichés sont calibrés : un score de 30 % correspond à environ "
                           "30 % d'offres uniques observées.")
            if metrics_boamp:
                mb = metrics_boamp["results"]
                st.caption(f"Appels d'offres ouverts (BOAMP) : sans montant ni durée, ils sont notés par une version du "
                           f"score sans ces informations : {round(100 * mb['model']['precision_top10'])} % sur le même test.")

        # 4. The notes
        st.html('<p class="ou-kicker" id="ch4">4 · Qui écrit les notes ?</p>')
        st.markdown("### Un modèle ouvert, et chaque chiffre vérifié")
        st.markdown("Gemma 4 31B (via Featherless) met les faits en deux phrases. Si un chiffre de la note n'est pas dans "
                    "les données, la note est écartée. La recommandation, elle, vient de trois règles explicites.")
        bm_p = ART / "llm_benchmark.json"
        if bm_p.exists():
            bm = json.loads(bm_p.read_text())
            with st.expander(f"Les {len(bm['models'])} modèles comparés"):
                st.caption(f"Mêmes faits, même consigne, une seule tentative par note, sur {bm['n']} appels d'offres de "
                           f"{bm['company']}. Conforme : tous les chiffres viennent des données, la recommandation est "
                           "gardée, 2 phrases et 45 mots au plus, en français. " + " ".join(bm.get("caveats", [])))
                rows = []
                for lab, m in bm["models"].items():
                    usd = m.get("usd_per_1000_notes")
                    rows.append({"Modèle": lab, "Notes conformes": f"{m['pass']['tout']} / {m['n']}",
                                 "Temps médian": f"{fr_num(m['median_seconds'])} s" if m.get("median_seconds") else "—",
                                 "Coût pour 1 000 notes": f"{usd:.2f} $".replace(".", ",") if usd is not None else "n.d."})
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        # 5. Who it is for
        cov_p = ART / "coverage.json"
        cov = json.loads(cov_p.read_text()).get("regions", {}) if cov_p.exists() else {}
        idf, fr = cov.get("Île-de-France"), cov.get("France")
        if idf and fr:
            st.html('<p class="ou-kicker" id="ch5">5 · Pour qui ?</p>')
            st.markdown(f"### Pour qui ? Environ {round(10 * idf['share_with_aller'])} entreprises actives sur 10 "
                        "en Île-de-France")
            st.markdown(f"Aujourd'hui, {fr_int(idf['with_aller'])} des {fr_int(idf['companies'])} entreprises actives "
                        f"d'Île-de-France ont au moins un appel d'offres « Aller », et {fr_int(fr['with_aller'])} sur "
                        f"{fr_int(fr['companies'])} en France ({round(100 * fr['share_with_aller'])} %). Chaque PME qui "
                        "répond transforme un marché à offre unique en marché disputé.")
            st.caption("Entreprise active : 10 à 200 marchés gagnés, dont un depuis 2025, et au moins 2 dans le même "
                       "métier et département. Un seul « Aller » suffit à être compté.")

        # 6. Limits and sources
        st.html('<p class="ou-kicker" id="ch6">6 · Ce que l\'outil ne dit pas</p>')
        st.markdown("### Limites")
        st.markdown(
            "- Le score dit combien d'offres un marché reçoit d'habitude, **pas si vous le gagnerez**.\n"
            f"- Seuls {SHARE_LABELLED} des marchés publiés indiquent le nombre d'offres reçues : le score apprend sur "
            "ceux-là.\n"
            "- Une offre unique ne signale pas en soi une irrégularité de l'acheteur : elle peut venir d'un marché étroit "
            "ou très spécialisé. Un titulaire qui gagne plusieurs fois n'indique en soi aucune irrégularité.\n"
            "- Le score décrit des régularités passées, pas des causes.\n"
            + ("- Les appels d'offres ouverts (BOAMP) ne donnent pas de montant : leur score s'en passe.\n" if has_boamp else
               "- Les achats à venir (APProch) viennent surtout de l'État ; beaucoup de collectivités n'y publient pas.\n") +
            "- Les avis BOAMP de moins de 90 k€ n'ont presque jamais de code CPV : ils manquent dans la liste, alors que "
            "les petits marchés sont ceux qui reçoivent le plus souvent une seule offre.\n"
            "- Seuls les marchés gagnés sont publiés : on ne connaît ni les offres perdues ni le taux de succès d'une "
            "entreprise.")
        st.markdown("### Sources")
        st.markdown("Appels d'offres ouverts : BOAMP (DILA) · projets d'achats (APProch) et derniers marchés de chaque "
                    "acheteur (« Marchés publics notifiés ») : API Hémicycle · historique complet pour le score : DECP "
                    "consolidées (data.gouv.fr) · entreprises et acheteurs : répertoire SIRENE (INSEE, via "
                    "recherche-entreprises.api.gouv.fr). **Licence Ouverte 2.0 (Etalab).**")


with tab_main:
    if "q" not in st.session_state:
        st.session_state["q"] = os.environ.get("DEMO_SIREN", "")
    # GOV.UK-style question page: question as label, hint under it, one big input, one main button
    with st.container(key="start"):
        if not str(st.session_state.get("q") or "").strip():  # landing screen only: results need the room
            st.html(f'<div class="ou-welcome"><img src="{MASCOT}" alt=""><div>'
                    '<h2>Quels marchés publics valent votre candidature ?</h2>'
                    '<p class="ou-lead">1 marché public sur 5 ne reçoit qu\'une seule offre. Trouvez ceux de votre '
                    'métier qui manquent de candidats : c\'est là que votre offre compte le plus.</p></div></div>')
        st.html('<p class="ou-label">Quel est le SIREN ou le nom de votre entreprise ?</p>')
        st.caption("Le SIREN a 9 chiffres : il figure sur votre extrait Kbis ou sur annuaire-entreprises.data.gouv.fr. "
                   "Un SIRET marche aussi. Réservé aux sociétés.")
        c_q, c_go = st.columns([4, 1.5], vertical_alignment="bottom")
        q = c_q.text_input("Quel est le SIREN ou le nom de votre entreprise ?", key="q", max_chars=80,
                           label_visibility="collapsed", placeholder="ex. 834 709 248 ou Point Contrôles")
        c_go.button("Voir mes appels d'offres", key="go", type="primary", icon=":material/arrow_forward:",
                    use_container_width=True)  # the input already commits on Enter or blur; the button makes it obvious
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.caption("ou essayez avec :", width="content")
            for label, s9 in EXAMPLES:
                st.button(label, key=f"ex_{s9}", on_click=_pick_example, args=(s9,), type="tertiary")
    raw = q
    if re.search(r"[A-Za-zÀ-ÿ]", q or "") and len(clean_siren(q)) < 9:  # a name, not a number
        if len(q.strip()) < 3:
            st.write("Tapez au moins 3 lettres du nom de l'entreprise.")
            st.stop()
        found = search_companies(company_index(awards), q)
        if found.empty:
            st.write("Aucune société de ce nom parmi celles qui ont gagné des marchés publics depuis 2019. "
                     "Essayez une partie du nom, ou le SIREN.")
            st.stop()
        labels = {r.siren: f"{r.name} · {fr_int(r.n)} marché{'s' if r.n > 1 else ''} · SIREN {r.siren}"
                  for r in found.itertuples()}
        raw = st.selectbox(f"{len(found)} société{'s' if len(found) > 1 else ''} trouvée{'s' if len(found) > 1 else ''}",
                           list(labels), format_func=labels.get)
    siren = clean_siren(raw)  # accepts spaces, dots and a full SIRET
    if not (raw or "").strip():  # landing screen: the start panel above already says what to do
        st.stop()
    if len(siren) < 9:
        st.write("Un SIREN compte 9 chiffres (ce sont aussi les 9 premiers chiffres du SIRET).")
        st.stop()
    if siren in PLACEHOLDER_SIRENS:
        st.write("Ce numéro est un identifiant fictif présent dans certaines données, pas une entreprise.")
        st.stop()
    if not siren_valid(siren):
        st.write("Ce numéro n'est pas un SIREN valide : sa clé de contrôle ne correspond pas. Vérifiez-le "
                 "(par exemple sur annuaire-entreprises.data.gouv.fr).")
        st.stop()
    sole = is_sole_trader(siren)
    if sole:
        st.write("Ce SIREN est celui d'un entrepreneur individuel. Par respect de la vie privée, QtFetcher "
                 "ne construit pas de profil à partir du nom d'une personne : l'outil est réservé aux sociétés.")
        st.stop()
    prof = profile_of(awards_of(siren), siren)
    if not prof:
        st.write("Aucun marché gagné trouvé pour ce SIREN dans les données publiques.")
        st.stop()
    if NON_DIFFUSIBLE.search(str(prof.get("name") or "")):
        st.write("Cette entité a demandé que ses données ne soient pas diffusées (statut « non diffusible » du "
                 "répertoire SIRENE) : QtFetcher n'affiche pas son profil.")
        st.stop()
    if sole is None and siren not in dict((s9, n) for n, s9 in EXAMPLES) and looks_like_person(prof["name"], prof["n_wins"]):
        st.write("Le répertoire des entreprises est injoignable pour l'instant : impossible de vérifier qu'il ne s'agit "
                 "pas d'un entrepreneur individuel. Par prudence, ce profil n'est pas affiché. Réessayez dans un instant.")
        st.stop()

    t = fit_table(prof, scored, awards_of(prof["siren"]))
    t = relevant(t).sort_values("proba", ascending=False).reset_index(drop=True)
    if not t.empty:
        try:  # same rules as the notes (src/explain.py)
            t["reco"] = [recommend_row(row, prof) for _, row in t.iterrows()]
        except Exception:
            t["reco"] = ""
    n_open = int((t["source"] == "BOAMP").sum()) if "source" in t else 0
    counts = t["reco"].value_counts() if "reco" in t else pd.Series(dtype=int)

    # --- "Votre entreprise": what we inferred from the contracts it has won
    with st.container(border=True, key="company"):
        a, b = st.columns([1, 1], gap="large")
        with a:
            st.caption("Votre entreprise, d'après ses marchés publics gagnés")
            st.subheader(prof["name"] or f"Entreprise {prof['siren']}")
            icon, trade = trade_of(prof)
            size = SIZE_LABEL.get(company_size(siren)) if sole is not None else None
            depts = [k for k in list(prof["dept"])[:3] if k != "NA"]
            n_w = prof["n_wins"]
            wins = f"{fr_int(n_w)}" + (f" (le dernier en {pd.Timestamp(prof['last_win']):%m/%Y})"
                                         if pd.notna(prof.get("last_win")) else "")
            icon_name = icon.removeprefix(":material/").removesuffix(":")
            rows = [("Métier", f'<span class="ou-icon">{icon_name}</span>{html.escape(trade)}' if trade else ""),
                    ("Taille", html.escape(size or "")),
                    ("Marchés gagnés" if n_w > 1 else "Marché gagné", html.escape(wins)),
                    ("Départements" if len(depts) > 1 else "Département", html.escape(", ".join(depts)))]
            # GOV.UK summary list: key / value rows (values are escaped; the icon is Streamlit's Material font)
            st.html('<table class="ou-summary">' + "".join(f"<tr><th>{k_}</th><td>{v_}</td></tr>"
                                                         for k_, v_ in rows if v_) + "</table>")
        if not t.empty:
            with b, st.container(key="banner"):  # the answer in one sentence (GOV.UK notification banner)
                n_al, n_et = int(counts.get("Aller", 0)), int(counts.get("À étudier", 0))
                if n_al:
                    top = t[t["reco"] == "Aller"].iloc[0]
                    who = html.unescape(top["buyer_name"]) if isinstance(top.get("buyer_name"), str) else "un acheteur public"
                    if pd.notna(top.get("due_date")):
                        d = (pd.Timestamp(top["due_date"]).normalize() - pd.Timestamp.now().normalize()).days
                        dl = "ferme aujourd'hui" if d <= 0 else ("ferme demain" if d == 1 else f"ferme dans {d} jours")
                    elif pd.notna(top.get("pub_date")):
                        dl = f"doit être publié en {pd.Timestamp(top['pub_date']):%m/%Y}"
                    else:
                        dl = ""
                    plural = n_al > 1
                    st.markdown(f"**{n_al} appel{'s' if plural else ''} d'offres à privilégier (« Aller »)**")
                    lead = (f"Le premier, chez {who}" if plural else f"Il est chez {who}") + (f", {dl}." if dl else ".")
                    st.markdown(lead + (f" {n_et} autre{'s' if n_et > 1 else ''} à étudier." if n_et else ""))
                elif n_et:
                    st.markdown(f"**Rien à privilégier aujourd'hui, mais {n_et} appel{'s' if n_et > 1 else ''} "
                                f"d'offres à étudier**")
                    st.markdown("Les autres appels d'offres de votre métier attirent la concurrence habituelle.")
                else:
                    st.markdown("**Rien à privilégier aujourd'hui**")
                    st.markdown("Les appels d'offres de votre métier attirent la concurrence habituelle, ou plus.")
                head = f"{len(t)} {'appel' if len(t) == 1 else 'appels'} d'offres dans votre métier"
                if n_open:
                    head += f", dont {n_open} {'ouvert' if n_open == 1 else 'ouverts'} maintenant"
                level = str(t["match_level"].iloc[0]) if "match_level" in t else ""
                if level and level != "même métier, même département":
                    head += f". Critère élargi : {level} (peu d'avis dans vos départements)"
                st.caption(head)
                shortcuts = [(k, int(counts.get(k, 0))) for k in ("Aller", "À étudier") if counts.get(k, 0)]
                if shortcuts:
                    with st.container(horizontal=True, gap="small"):
                        for k, n in shortcuts:
                            st.button(f"Voir {'les ' + str(n) if n > 1 else 'le'} « {k} »", key=f"show_{k}",
                                      icon=RECO_STYLE[k][1], on_click=_show_reco, args=(t, siren, k))
    if t.empty:
        st.write("Aucun achat à venir ne correspond à votre historique.")
        st.stop()

    left, right = st.columns([5, 3], gap="large")
    with left:
        kinds = [k for k in ("BOAMP", "APProch") if (t["source"] == k).any()]
        n_by = t["source"].value_counts()
        kind_lab = {"BOAMP": f"Ouverts maintenant ({n_by.get('BOAMP', 0)})",
                    "APProch": f"Projets à venir ({n_by.get('APProch', 0)})"}
        kind = kinds[0]
        k1, k2 = st.columns([3, 2], vertical_alignment="bottom")
        if len(kinds) > 1:
            if st.session_state.get(f"kind_{siren}") not in kinds:  # default via session state (banner shortcuts set it)
                st.session_state[f"kind_{siren}"] = kinds[0]
            kind = k1.segmented_control("Type d'avis", kinds, format_func=kind_lab.get,
                                        key=f"kind_{siren}", label_visibility="collapsed") or kinds[0]
        order = k2.segmented_control("Trier par", ["chances", "échéance"], default="chances", key=f"sort_{siren}",
                                     format_func={"chances": "Meilleures chances", "échéance": "Échéance"}.get,
                                     label_visibility="collapsed") or "chances"
        st.caption("Avis publiés au BOAMP : vous pouvez répondre maintenant." if kind == "BOAMP" else
                   "Achats annoncés par l'État (APProch), pas encore publiés : de quoi vous préparer.")
        sub = t[t["source"] == kind]
        rc = sub["reco"].value_counts()
        opts = ["Tous"] + [k for k in RECOS if rc.get(k, 0)]
        if st.session_state.get(f"flt_{siren}_{kind}") not in opts:
            st.session_state[f"flt_{siren}_{kind}"] = "Tous"
        flt = st.segmented_control("Recommandation", opts, key=f"flt_{siren}_{kind}",
                                   format_func=lambda k: f"{k} ({len(sub) if k == 'Tous' else int(rc[k])})") or "Tous"
        if flt != "Tous":
            sub = sub[sub["reco"] == flt]
        if order == "échéance":
            sub = sub.assign(_d=sub["due_date"].fillna(sub["pub_date"])).sort_values(
                ["_d", "proba"], ascending=[True, False], na_position="last")
        else:
            sub = sub.sort_values("proba", ascending=False)
        sub = sub.reset_index(drop=True)
        view = pd.DataFrame({
            "Avis": sub["reco"].astype(str),
            "Achat": sub["libelle"].astype(str),
            "Acheteur": [html.unescape(str(b)) + (f" · {d}" if d not in {"NA", "nan", "None", ""} else "")
                         for b, d in zip(sub["buyer_name"].fillna(sub["buyer_siren"]), sub["dept"].astype(str))],
            **({"Publication prévue": [f"{pd.Timestamp(d):%d/%m/%Y}" if pd.notna(d) else "" for d in sub["pub_date"]]}
               if kind == "APProch" else {}),
            "Date limite": [date_only(row) for _, row in sub.iterrows()],
            **({"Échéance": [countdown(row) for _, row in sub.iterrows()]}  # shown as "Délai" (J-16)
               if kind != "APProch" else {}),
            "Offre unique": (100 * sub["proba"]).round().astype(int),
            "vs moyenne": [f"{fr_num(p / avg)} fois" if avg else "" for p in sub["proba"]],
        })
        ev = st.dataframe(
            view, hide_index=True, width="stretch", height=min(39 + 35 * len(view), 520),
            on_select="rerun", selection_mode="single-row", key=f"list_{siren}_{kind}_{flt}_{order}",
            column_config={
                "Avis": st.column_config.TextColumn(width=82, help="Notre recommandation : Aller, À étudier ou Passer"),
                "Achat": st.column_config.TextColumn(width=176, help="Objet de l'appel d'offres"),
                "Acheteur": st.column_config.TextColumn("Acheteur · dép.", width=135,
                                                        help="Acheteur public et département d'exécution"),
                "Publication prévue": st.column_config.TextColumn(width=105, help="Date à laquelle l'acheteur prévoit "
                                                                  "de publier l'appel d'offres (APProch)"),
                "Date limite": st.column_config.TextColumn(width=95, help="Date limite de remise des offres, "
                                                           "quand l'acheteur l'a annoncée"),
                "Échéance": st.column_config.TextColumn("Délai", width=62,
                                                        help="Jours restants : J-16 = il reste 16 jours pour répondre"),
                "Offre unique": st.column_config.ProgressColumn(
                    width=100, min_value=0, max_value=100, format="%d %%",
                    help="Chance qu'une seule entreprise réponde, d'après les marchés passés"),
                "vs moyenne": st.column_config.TextColumn("vs moyenne", width=102,
                                                          help="Par rapport à un marché moyen : 2,7 fois = 2,7 fois plus de "
                                                               "chances d'offre unique"),
            },
        )
        st.caption("Cliquez sur une ligne pour voir la note et l'avis.")
        with st.expander("Comment lire ce tableau", icon=":material/help:"):
            st.markdown(
                "- **Avis** : notre recommandation. **Aller** = à privilégier ; **À étudier** = à regarder de près ; "
                "**Passer** = la concurrence sera habituelle ou forte.\n"
                f"- **Offre unique** : la chance qu'une seule entreprise réponde, d'après les marchés passés "
                f"(en moyenne : {round(100 * avg) if avg else 20} %).\n"
                f"- **vs moyenne** : « 2,7 fois » = 2,7 fois plus de chances d'offre unique qu'un marché moyen.\n"
                "- **Date limite** : dernier jour pour déposer une offre. **Délai** : jours restants (J-16 = dans 16 jours).\n"
                "- **Publication prévue** (projets à venir) : date à laquelle l'acheteur prévoit de publier l'appel "
                "d'offres. APProch ne donne pas de date de début du marché.")
        rows = ev.selection.rows if ev and ev.selection else []
        idx = rows[0] if rows and rows[0] < len(sub) else 0

    with right:
        if sub.empty:
            st.caption("Aucun appel d'offres pour ce filtre.")
        else:
            with st.container(key="detail"):
                render_detail(sub.iloc[idx], prof)

    st.divider()
    st.caption("**Sources**, toutes sous Licence Ouverte 2.0 (Etalab) :  \n"
               "Appels d'offres ouverts : BOAMP (DILA)  \n"
               "Projets d'achats (APProch) et derniers marchés des acheteurs : API Hémicycle  \n"
               "Marchés passés : DECP consolidées (data.gouv.fr)  \n"
               "Entreprises et acheteurs : répertoire SIRENE (INSEE)  \n"
               "Notes : Gemma 4 31B (Featherless), chaque chiffre vérifié.  \n"
               "Limites et méthode : onglet « Comment ça marche ».")


if siren and prof:
    render_follows(prof["siren"])
