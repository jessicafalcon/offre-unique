"""Page 2: the tenders that fit the company, ranked by the chance of a single bid (an opportunity for the SME).

Reads only precomputed data through lib.data (no LLM or Hémicycle call). Follows are kept in st.session_state.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import appels_widgets as w
from lib import charts, data, ui
from lib import taxonomy as tx
from lib.fmt import plural

PAGE = 10  # cards shown per step

st.markdown(w.CSS, unsafe_allow_html=True)

siren = data.current_siren()
if len(siren) != 9:
    st.info("Entrez le SIREN de votre entreprise (9 chiffres) dans la barre latérale.")
    st.stop()
if not data.siren_valid(siren):
    st.warning(f"Le numéro {siren} ne ressemble pas à un SIREN valide (sa clé de contrôle ne correspond pas, "
               "ou c'est un numéro de remplissage comme 999999999). Vérifiez-le dans la barre latérale.")
    st.stop()

ident = data.identity(siren, live=False) or {}
if ident.get("entrepreneur_individuel"):
    st.warning("Ce SIREN est celui d'un entrepreneur individuel : Offre unique ne construit pas le profil d'une personne.")
    st.stop()

prof = data.profile(siren)
if not prof:
    st.info("Aucun marché public gagné n'est enregistré pour ce SIREN dans les données (DECP) : "
            "impossible de déduire son métier. Essayez une autre entreprise.")
    st.stop()

t_all = data.tenders(siren)
avg = data.avg_rate()
name = ident.get("nom") or prof.get("name") or f"Entreprise {siren}"

# ------------------------------------------------------------------------------------------ header
st.markdown(f"## 🎯 Appels d'offres pour {ui.esc(name)}")
if t_all.empty:
    st.info("Aucun appel d'offres ouvert ou à venir ne correspond pour l'instant à votre historique.")
    st.stop()

level = str(t_all["match_level"].iloc[0])
st.caption("Classés par **chance qu'une seule offre soit déposée** : plus elle est haute, moins vous aurez de concurrents. "
           "Votre candidature y compte le plus." + ("" if level == "même métier, même département"
                                                     else f" Correspondance élargie : **{level}**."))

open_n = int((t_all["source"] == "BOAMP").sum())
soon = int(t_all["days_left"].between(0, 15).sum())
counts = t_all["reco"].value_counts().to_dict()
best = t_all.iloc[0]
k1, k2, k3, k4 = st.columns(4)
with k1:
    ui.kpi("Dans votre métier", len(t_all), "🎯", "appels d'offres et projets", tx.TEAL)
with k2:
    ui.kpi("Ouverts maintenant", open_n, "📬", "on peut candidater", "#0EA5E9")
with k3:
    ui.kpi("Clôture sous 15 jours", soon, "⏰", "à ne pas laisser passer", "#D97706")
with k4:
    ui.kpi("Meilleure chance", w.fr_pct(best["proba"]), "🏆",
           (f"{w.fr_num(best['proba'] / avg)} × la moyenne · " if avg else "") + str(w.buyer_name(best))[:40], "#16A34A")
st.markdown("")
st.markdown(w.reco_bar_html(counts), unsafe_allow_html=True)
st.caption("Règles fixes, testées sur les marchés 2026 (page Preuves).")

# ------------------------------------------------------------------------------------------ visual summary
with st.container(border=True):
    c1, c2, c3 = st.columns([4, 4, 6])
    with c1:
        st.markdown("**🏛️ Qui achète ?**")
        w.kind_donut(t_all, key=f"ap_donut_{siren}")
        st.markdown(w.kind_legend_html(t_all), unsafe_allow_html=True)
    with c2:
        st.markdown("**🧰 Quels types de marchés ?**")
        st.markdown(w.sector_bars_html(t_all), unsafe_allow_html=True)
    with c3:
        st.markdown("**⏳ Chance d'offre unique et temps restant**")
        w.chance_deadline_scatter(t_all, avg, key=f"ap_scatter_{siren}")
        n_late = int((t_all["days_left"] > w.HORIZON).sum())
        n_nodate = int(t_all["days_left"].isna().sum())
        notes_ = [f"Échelle des {w.HORIZON} prochains jours"
                  + (f" ; {plural(n_late, 'échéance')} plus lointaine{'s' if n_late > 1 else ''} "
                     f"{'sont regroupées' if n_late > 1 else 'est placée'} dans la bande grise « > {w.HORIZON} j »"
                     if n_late else "") + "."]
        if n_nodate:
            notes_.append(f"{plural(n_nodate, 'projet')} sans date limite connue "
                          f"{'ne sont pas' if n_nodate > 1 else 'n’est pas'} sur ce graphique.")
        notes_.append("Taille des points : montant estimé, quand il est publié.")
        st.caption(" ".join(notes_))

# ------------------------------------------------------------------------------------------ controls
f1, f2, f3, f4 = st.columns([4, 3, 3, 3])
with f1:
    how = st.segmented_control("Trier par", w.SORTS, default=w.SORTS[0], key="ap_sort") or w.SORTS[0]
with f2:
    recos = st.pills("Recommandation", ["Aller", "À étudier", "Passer"], selection_mode="multi",
                     format_func=lambda k: f"{tx.RECO[k].emoji} {k}", key="ap_reco")
with f3:
    kinds_present = [k for k in tx.BUYER_KINDS if k.key in set(t_all["buyer_kind"])]
    kinds = st.multiselect("Acheteur", [k.key for k in kinds_present], key="ap_kind",
                           format_func=lambda key: next(f"{k.emoji} {k.label}" for k in tx.BUYER_KINDS if k.key == key),
                           placeholder="Tous")
with f4:
    types = st.pills("Statut", ["Ouvert", "Projet"], selection_mode="multi", key="ap_type",
                     format_func=lambda x: "📬 Ouvert" if x == "Ouvert" else "🗓️ Projet")
g1, g2 = st.columns([4, 9])
with g1:
    secs_present = [s for s in tx.SECTORS if s.key in set(t_all["sector"])]
    secs = st.multiselect("Type de marché", [s.key for s in secs_present], key="ap_sec", placeholder="Tous",
                          format_func=lambda key: next(f"{s.emoji} {s.label}" for s in tx.SECTORS if s.key == key))
with g2:
    q = st.text_input("Rechercher", key="ap_q", placeholder="mot du titre ou de l'acheteur (ex. contrôle technique, Val-de-Marne)")

t = t_all
if recos:
    t = t[t["reco"].isin(recos)]
if kinds:
    t = t[t["buyer_kind"].isin(kinds)]
if types:
    t = t[t["kind"].isin(types)]
if secs:
    t = t[t["sector"].isin(secs)]
if q.strip():
    needle = q.strip().lower()
    hay = (t["libelle"].astype(str) + " " + t["buyer_name"].astype(str)).str.lower()
    t = t[hay.str.contains(needle, regex=False)]
t = w.sort_tenders(t, how)

if t.empty:
    st.info("Aucun appel d'offres ne correspond à ces filtres.")
    st.stop()

# selection: keep the chosen tender if still visible, else the first one (SENEO for the demo company)
codes = t["code"].astype(str).tolist()
sel_key = f"ap_sel_{siren}"
if st.session_state.get(sel_key) not in codes:
    st.session_state[sel_key] = codes[0]


def _select(code: str) -> None:
    st.session_state[sel_key] = code


left, right = st.columns([7, 5], gap="large")

# ------------------------------------------------------------------------------------------ list
with left:
    view = st.segmented_control("Affichage", ["Cartes", "Tableau"], default="Cartes", key="ap_view") or "Cartes"
    st.caption(f"{len(t)} appel{'s' if len(t) > 1 else ''} d'offres affiché{'s' if len(t) > 1 else ''} sur {len(t_all)}")
    if view == "Tableau":
        tbl = pd.DataFrame({
            "Reco": t["reco"].map(lambda k: f"{tx.RECO[k].emoji} {k}"),
            "Chance": (100 * t["proba"]).round().astype(int),
            "Achat": [w.title_of(r) for _, r in t.iterrows()],
            "Acheteur": [f"{w.buyer_tag(r).emoji} {w.buyer_name(r)}" for _, r in t.iterrows()],
            "Échéance": [w.deadline_text(r) for _, r in t.iterrows()],
            "Statut": t["kind"],
        })
        ev = st.dataframe(tbl, hide_index=True, width="stretch", height=min(42 + 35 * len(tbl), 620),
                          on_select="rerun", selection_mode="single-row", key=f"ap_tbl_{siren}",
                          column_config={
                              "Chance": st.column_config.ProgressColumn("Chance", format="%d %%",
                                                                        help="Chance qu'une seule offre soit déposée",
                                                                        min_value=0, max_value=60, width=110),
                              "Achat": st.column_config.TextColumn(width=320),
                              "Reco": st.column_config.TextColumn("Reco", width=105),
                              "Échéance": st.column_config.TextColumn(width=110),
                          })
        rows = ev.selection.rows if ev and ev.selection else []
        if rows and rows[0] < len(codes):
            st.session_state[sel_key] = codes[rows[0]]
    else:
        n_key = f"ap_n_{siren}"
        shown = st.session_state.get(n_key, PAGE)
        sel = st.session_state[sel_key]
        head = t.head(shown)
        st.markdown(w.cards_css([(c, k) for c, k in zip(head["code"], head["reco"])], sel), unsafe_allow_html=True)
        for _, r in head.iterrows():
            code = str(r["code"])
            with st.container(key=w.card_key(code)):
                st.markdown(w.card_top_html(r), unsafe_allow_html=True)
                a, b = st.columns([7, 2], vertical_alignment="center")
                a.markdown(w.chance_html(r["proba"], avg), unsafe_allow_html=True)
                if code == sel:
                    b.button("Affiché", key=f"ap_pick_{code}", icon=":material/check:", type="primary",
                             width="stretch", disabled=True)
                else:
                    b.button("Voir", key=f"ap_pick_{code}", icon=":material/arrow_forward:", on_click=_select,
                             args=(code,), width="stretch")
        if len(t) > shown:
            rest = len(t) - shown
            st.button(f"Afficher {min(PAGE, rest)} de plus ({plural(rest, 'restant')})", key="ap_more",
                      on_click=lambda: st.session_state.__setitem__(n_key, shown + PAGE))

# ------------------------------------------------------------------------------------------ detail
r = t[t["code"].astype(str) == st.session_state[sel_key]].iloc[0]
code = str(r["code"])
with right:
    with st.container(border=True):
        inc = ' <span class="ap-inc">🏅 Vous êtes le titulaire sortant</span>' if r.get("is_incumbent") else ""
        st.markdown(f'{ui.reco_badge_html(r["reco"])} {w.kind_tag_html(r)}{inc}', unsafe_allow_html=True)
        full_title = w.title_of(r)
        st.markdown(f'<div class="ap-dtitle" title="{ui.esc(full_title)}">{ui.esc(full_title)}</div>',
                    unsafe_allow_html=True)
        if len(full_title) > 170:
            with st.expander("Titre complet"):
                st.write(full_title)
        bt = w.buyer_tag(r)
        st.markdown(ui.chip_html(bt, w.buyer_name(r)[:60]) + ui.chip_html(tx.sector_of(r.get("cpv_div")))
                    + w.amount_chip_html(r) + " " + w.deadline_html(r), unsafe_allow_html=True)

        label, color = tx.chance_style(float(r["proba"]), avg)
        w.chance_gauge(float(r["proba"]), avg, color, key=f"ap_gauge_{code}")
        st.markdown(f"**Chance qu'une seule offre soit déposée** : {label}"
                    + (f" (moyenne des marchés : {round(100 * avg)} %)." if avg else "."))
        for s in w.fact_sentences(r, siren):
            st.markdown(f'<div class="ap-fact">{w.fact_emoji(s)} {ui.esc(s)}</div>', unsafe_allow_html=True)

        note = data.notes().get(f"{siren}:{code}")
        if note and note.get("verified") and str(note.get("note", "")).strip():
            st.markdown(f'<div class="ap-note">📝 {ui.esc(note["note"])}</div>', unsafe_allow_html=True)
            st.caption(f"Note rédigée par {note.get('model', 'un modèle de langue')} à partir des faits ci-dessus ; "
                       "chaque chiffre est vérifié.")
        else:
            st.markdown(f'<div class="ap-why">{tx.RECO[r["reco"]].emoji} <b>{ui.esc(r["reco"])}</b>, car '
                        f'{ui.esc(r["reason"])}.</div>', unsafe_allow_html=True)

        st.markdown("")
        b1, b2 = st.columns(2)
        link = r.get("lien_vers_la_consultation")
        if isinstance(link, str) and link.startswith("http"):
            b1.link_button("Voir l'avis", link, icon=":material/open_in_new:", width="stretch",
                           help="Avis BOAMP (DILA)" if r.get("source") == "BOAMP" else "Consultation de l'acheteur")
        follows = st.session_state.setdefault("ap_follows", {})
        fkey = f"{siren}:{code}"
        if fkey in follows:
            if b2.button("Suivi · retirer", key=f"ap_unf_{code}", icon=":material/check:", width="stretch"):
                follows.pop(fkey, None)
                st.rerun()
        elif b2.button("Suivre", key=f"ap_f_{code}", icon=":material/star:", width="stretch",
                       help="Ajouter à vos appels d'offres suivis (barre latérale)"):
            follows[fkey] = {"title": w.title_of(r, ""), "buyer": w.buyer_name(r), "reco": r["reco"],
                             "deadline": w.deadline_text(r), "chance": w.fr_pct(r["proba"])}
            st.rerun()

    with st.container(border=True):
        st.markdown("**📚 Derniers marchés comparables de cet acheteur**")
        eds, src = w.past_editions(r, data.hemicycle_history())
        if eds:
            w.editions_chart(eds, key=f"ap_eds_{code}")
            st.caption("Nombre d'offres reçues par marché · en vert : une seule offre.")
            past = pd.DataFrame({
                "Date": pd.to_datetime(pd.Series([e.get("date") for e in eds]), errors="coerce").dt.strftime("%d/%m/%Y").fillna(""),
                "Objet": [str(e.get("objet") or "") for e in eds],
                "Offres": [("" if e.get("offres") is None or pd.isna(e.get("offres")) or e["offres"] <= 0 else str(int(e["offres"])))
                           for e in eds],
                "Titulaire": [str(e.get("titulaire_nom") or "—") for e in eds],
            })
            with st.expander(f"Détail des {len(past)} marchés"):
                st.dataframe(past, hide_index=True, width="stretch")
            ui.source(src)
        else:
            st.caption("Aucun marché comparable de cet acheteur dans les données.")

    st.caption("ℹ️ Le score dit combien d'offres un marché reçoit d'habitude, pas si vous le gagnerez. "
               "Une offre unique ne signale pas en soi une irrégularité de l'acheteur.")
    ui.source("BOAMP (DILA) pour les appels d'offres ouverts ; APProch via l'API Hémicycle pour les projets d'achats ; "
              "DECP consolidées (data.gouv.fr) pour l'historique · Licence Ouverte 2.0")

# Followed tenders (st.session_state["ap_follows"]) are listed in the sidebar by app.py, on every page.
