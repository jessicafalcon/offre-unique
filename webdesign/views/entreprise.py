"""Page 1: "Votre entreprise", a visual and positive portrait of the company (webdesign/PLAN.md).

Data: Sirene via recherche-entreprises (lib.data.identity, cached), past wins from DECP (lib.data.company_contracts),
matching tenders (lib.data.tenders). Read-only.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import charts, data, ui
from lib import entreprise_widgets as w
from lib import taxonomy as tx
from lib.fmt import fr_eur, fr_int, plural

siren = data.current_siren()
if len(siren) != 9:
    st.markdown("### 👋 Bienvenue")
    st.info("Entrez le SIREN de votre entreprise (9 chiffres) dans la barre de gauche pour découvrir son portrait.")
    st.stop()

if not w.siren_valid(siren):
    st.markdown("### 🔢 Numéro à vérifier")
    st.info(f"« {siren} » n'est pas un numéro SIREN valide (9 chiffres avec une clé de contrôle). "
            "Vous le trouverez sur un extrait Kbis ou sur annuaire-entreprises.data.gouv.fr.")
    st.stop()

ident = data.identity(siren)  # cached file, else live fetch; None without network
if ident and ident.get("entrepreneur_individuel"):
    st.markdown("### 🔒 Profil non affiché")
    st.info("Ce SIREN correspond à un entrepreneur individuel : son profil serait celui d'une personne. "
            "Offre unique ne présente que des sociétés.")
    st.stop()

prof = data.profile(siren)
name = w.pretty_name(prof, ident, siren)
if not prof:
    st.markdown(f"### 🔎 {ui.esc(name)}")
    st.info("Nous n'avons trouvé aucun marché public remporté par ce SIREN dans les données ouvertes (DECP). "
            "Le portrait et les recommandations s'appuient sur les marchés déjà gagnés : vérifiez le numéro, "
            "ou revenez après un premier marché public.")
    st.stop()

c = data.company_contracts(siren)
n_wins = int(prof["n_wins"])
small = n_wins < w.SMALL_TRACK
sg = (ident or {}).get("siege") or {}
dept = sg.get("departement") or (list(prof["dept"])[0] if prof.get("dept") else "")
place = ", ".join(x for x in [(sg.get("commune") or "").title(), w.dept_label(dept) if dept else ""] if x)
since = f"depuis {str(ident['date_creation'])[:4]}" if ident and ident.get("date_creation") else ""
naf = (ident or {}).get("naf")
activity = w.naf_text(naf)
top_cpv = c["cpv_div"].astype(str).value_counts()
main_sector = tx.sector_of_naf(naf) if naf else tx.sector_of(top_cpv.index[0] if len(top_cpv) else "")
size = tx.size_of((ident or {}).get("tranche_effectif"), (ident or {}).get("categorie_entreprise"))
level = tx.SIZE_LEVEL[size.key]
kinds = {t.key: t for t in tx.BUYER_KINDS}
sectors = {t.key: t for t in tx.SECTORS}

# ------------------------------------------------------------------------------------------- hero
chips = [w.white_chip(size.emoji, size.label), w.white_chip(main_sector.emoji, main_sector.label)]
chips += [w.white_chip(e, lab) for k, (e, lab) in w.LABELS.items() if ((ident or {}).get("labels") or {}).get(k)]
chips.append(w.white_chip("🏆", plural(n_wins, "marché public remporté", "marchés publics remportés")))
st.markdown(w.hero_html(name, activity, f"📍 {place}" if place else "", f"📅 {since}" if since else "", chips),
            unsafe_allow_html=True)
ui.source("Sirene (Insee) via l'API Recherche d'entreprises, data.gouv.fr · Licence Ouverte 2.0" if ident
          else "Identité non disponible hors connexion : portrait établi à partir des marchés publics (DECP)")
st.write("")

# ------------------------------------------------------------------------------------------- identity cards
k1, k2, k3 = st.columns([1, 1.25, 1], gap="medium")
with k1:
    st.markdown(w.size_card_html(size, level, tx.headcount_label((ident or {}).get("tranche_effectif")),
                                 (ident or {}).get("annee_effectif"), (ident or {}).get("categorie_entreprise"),
                                 (ident or {}).get("nb_etablissements_ouverts")), unsafe_allow_html=True)
with k2:
    shares = c["sector"].value_counts(normalize=True).head(4)
    st.markdown(w.sector_card_html(main_sector, activity, [(sectors[k], float(v)) for k, v in shares.items()]),
                unsafe_allow_html=True)
with k3:
    st.markdown(w.finance_card_html((ident or {}).get("finances") or {}, place), unsafe_allow_html=True)
st.write("")

# ------------------------------------------------------------------------------------------- KPIs
amount = pd.to_numeric(c["montant"], errors="coerce")
amount = amount[(amount > 0) & (amount < 1e9)]  # drop junk amounts
known = c["offres"].notna() & (pd.to_numeric(c["offres"], errors="coerce") > 0)
n_known = int(known.sum())
n_alone = int((pd.to_numeric(c.loc[known, "offres"]) == 1).sum())
depts = c["dept"].astype(str)
depts = depts[~depts.isin(["NA", "", "nan", "None"])]
last = pd.to_datetime(c["date"], errors="coerce").max()
n_buyers = int(c["buyer_siren"].nunique())

st.markdown("#### 🏆 Son parcours dans la commande publique")
cols = st.columns(3, gap="small") + st.columns(3, gap="small")
with cols[0]:
    ui.kpi("Marchés", fr_int(n_wins), "🏆", "remportés, dans les données publiques", tx.TEAL)
with cols[1]:
    if len(amount):
        sub = (f"par marché · total {fr_eur(amount.sum())} sur {plural(len(amount), 'marché')} "
               "(montants maximum des accords-cadres inclus)") if len(amount) > 1 else "sur 1 marché au montant connu"
        ui.kpi("Montant médian", fr_eur(amount.median()), "💶", sub, "#6366F1")
    else:
        ui.kpi("Montant médian", "—", "💶", "montants non renseignés", "#6366F1")
with cols[2]:
    ui.kpi("Clients publics", fr_int(n_buyers), "🤝",
           "acheteur public" if n_buyers <= 1 else "acheteurs publics différents", "#F59E0B")
with cols[3]:
    ui.kpi("Départements", fr_int(depts.nunique()), "📍",
           ", ".join(depts.value_counts().head(3).index) or "non précisés", "#0EA5E9")
with cols[4]:
    ui.kpi("Seul candidat", f"{round(100 * n_alone / n_known)} %" if n_known else "—", "🎯",
           f"sur {plural(n_known, 'marché')} dont le nombre d'offres est connu" if n_known else "nombre d'offres inconnu",
           "#22C55E")
with cols[5]:
    ui.kpi("Dernier marché", last.strftime("%m/%Y") if pd.notna(last) else "—", "🗓️", "date de notification", "#EC4899")
ui.source(w.SOURCE_DECP)
st.write("")

kind_counts = c["buyer_kind"].value_counts().to_dict()
typology_note = w.SOURCE_DECP + (" · type d'acheteur : nature juridique Insee (API Recherche d'entreprises), "
                                 "à défaut son nom" if len(data.buyers()) else " · type d'acheteur déduit de son nom")

# ------------------------------------------------------------------------------------------- small track record
if small:
    st.markdown(w.small_track_html(n_wins), unsafe_allow_html=True)
    st.write("")
    st.markdown("#### 📑 Ses marchés")
    st.markdown(w.contracts_list_html(c), unsafe_allow_html=True)
    ui.source(w.SOURCE_DECP)
    st.write("")
    with st.container(border=True):
        st.markdown("**Les types d'acheteurs publics** · en couleur, ceux avec qui l'entreprise a déjà travaillé")
        st.markdown(w.typology_html(kind_counts), unsafe_allow_html=True)
        ui.source(typology_note)
    st.write("")

# ------------------------------------------------------------------------------------------- clients
else:
    st.markdown("#### 🏛️ Ses clients publics")
    g = (c.assign(nom=c["acheteur_nom"].fillna(c["buyer_siren"]).astype(str))
         .groupby("buyer_siren").agg(n=("id", "size"), nom=("nom", lambda s: s.mode().iloc[0]),
                                     kind=("buyer_kind", "first"))
         .sort_values("n", ascending=False).head(8))
    bar_items = [(f"{kinds[r.kind].emoji} {r.nom if len(r.nom) <= 38 else r.nom[:37] + '…'}", int(r.n),
                  kinds[r.kind].color) for r in g.itertuples()]
    n_kinds = sum(1 for v in kind_counts.values() if v)
    h = max(240, w.bar_height(len(bar_items)), 24 * n_kinds + 60)
    a, b = st.columns([1.15, 1], gap="large")
    with a:
        with st.container(border=True):
            st.markdown("**Par type de client**")
            w.kind_donut(kind_counts, len(c), h, key=f"ent_kinds_{siren}")
    with b:
        with st.container(border=True):
            st.markdown("**Ses principaux clients**")
            w.ordered_hbar(bar_items, h, key=f"ent_top_{siren}")
    with st.container(border=True):
        st.markdown("**Les types d'acheteurs publics** · en couleur, ceux avec qui l'entreprise a déjà travaillé")
        st.markdown(w.typology_html(kind_counts), unsafe_allow_html=True)
        ui.source(typology_note)
    st.write("")

    # --------------------------------------------------------------------------------------- contracts
    st.markdown("#### 📑 Ses marchés")
    amt = w.amount_items(c)
    sec = c["sector"].value_counts().head(7)
    sec_items = [(f"{sectors[k].emoji} {sectors[k].label}", int(v), sectors[k].color) for k, v in sec.items()]
    card_h = w.bar_height(max(len(amt), len(sec_items))) + 72
    a, b = st.columns(2, gap="large")
    with a:
        with st.container(border=True, height=card_h):
            st.markdown("**Par taille de marché**")
            if amt:
                w.ordered_hbar(amt, w.bar_height(len(amt)), key=f"ent_amount_{siren}")
            else:
                st.caption("Montants non renseignés.")
    with b:
        with st.container(border=True, height=card_h):
            st.markdown("**Par type de prestation**")
            w.ordered_hbar(sec_items, w.bar_height(len(sec_items)), key=f"ent_sector_{siren}")
    years, vals = w.year_counts(c)
    dc = depts.value_counts().head(8)
    h = max(240, w.bar_height(len(dc)))
    a, b = st.columns(2, gap="large")
    with a:
        with st.container(border=True, height=h + 72):
            st.markdown("**Marchés remportés par année**")
            if years:
                w.wins_per_year(years, vals, h, key=f"ent_years_{siren}")
            else:
                st.caption("Dates non renseignées.")
    with b:
        with st.container(border=True, height=h + 72):
            st.markdown("**Où elle travaille**")
            if len(dc):
                w.ordered_hbar([(f"📍 {w.dept_label(d)}", int(v), "#0EA5E9") for d, v in dc.items()], h,
                               key=f"ent_dept_{siren}")
            else:
                st.caption("Lieux d'exécution non renseignés.")
    ui.source(w.SOURCE_DECP)
    st.write("")

# ------------------------------------------------------------------------------------------- teaser
t = data.tenders(siren)
if len(t):
    n_open = int((t["source"] == "BOAMP").sum())
    st.markdown(w.teaser_html(len(t), n_open, int((t["reco"] == "Aller").sum()), int((t["reco"] == "À étudier").sum())),
                unsafe_allow_html=True)
    st.page_link("views/appels.py", label="Voir les appels d'offres qui lui correspondent", icon="🎯")
    ui.source("BOAMP (DILA), APProch via l'API Hémicycle · score Offre unique · Licence Ouverte 2.0")
