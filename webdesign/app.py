"""Offre unique, redesigned demonstrator (separate from the main app.py; nothing there is touched).

    cd webdesign && ../.venv/Scripts/python -m streamlit run app.py      (Windows)
    cd webdesign && ../.venv/bin/python -m streamlit run app.py          (macOS)

Run it from webdesign/ so that webdesign/.streamlit/config.toml (theme) is picked up.
Pages live in views/, shared pieces in lib/ (taxonomy, data, charts, ui).
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import data, ui  # noqa: E402

st.set_page_config(page_title="Offre unique", page_icon="🎯", layout="wide")
ui.inject_css()

if "siren" not in st.session_state:
    st.session_state["siren"] = data.current_siren()

with st.sidebar:
    st.markdown("## 🎯 Offre unique")
    st.caption("Les appels d'offres qui manquent de candidats, là où votre candidature compte le plus.")
    st.text_input("SIREN de votre entreprise", key="siren", max_chars=14,
                  help="Réservé aux sociétés. N'entrez pas le SIREN d'un entrepreneur individuel : "
                       "son profil serait celui d'une personne.")

pages = [
    st.Page("views/entreprise.py", title="Votre entreprise", icon=":material/apartment:", default=True),
    st.Page("views/appels.py", title="Appels d'offres", icon=":material/target:"),
    st.Page("views/preuves.py", title="Preuves", icon=":material/verified:"),
    st.Page("views/pipeline.py", title="Comment ça marche", icon=":material/account_tree:"),
]
nav = st.navigation(pages)

with st.sidebar:
    # followed tenders, kept in the session only (set on the Appels d'offres page)
    siren9 = data.current_siren()
    mine = {k: v for k, v in st.session_state.get("ap_follows", {}).items() if k.startswith(f"{siren9}:")}
    if mine:
        st.divider()
        st.markdown(f"**⭐ Appels d'offres suivis ({len(mine)})**")
        for v in mine.values():
            reco = data.tx.RECO.get(v.get("reco"))
            st.caption(f"{reco.emoji if reco else ''} {str(v.get('title', ''))[:70]} · {v.get('deadline', '')} · "
                       f"{v.get('chance', '')}")
        st.caption("Prochaine étape : rappels avant l'échéance et alerte si l'avis est modifié.")
    st.divider()
    st.caption("Données : DECP (data.gouv.fr), BOAMP (DILA), APProch et Marchés publics notifiés via l'API Hémicycle, "
               "Sirene (Insee). Licence Ouverte 2.0.")

nav.run()
