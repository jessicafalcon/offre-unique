"""Comment ça marche: the pipeline, step by step, with the real volumes.

Numbers come from parquet metadata (row counts, nothing loaded), artifacts/*.json and reports/data_check.md.
"""
from __future__ import annotations

import streamlit as st

from lib import data, ui
from lib import proof_widgets as pw
from lib import taxonomy as tx

rc = pw.row_count
metrics = data.metrics() or {}
bt = data.backtest() or {}
main_bt = bt.get("main", {})
bm = data.benchmark() or {}
notes_used = pw.notes_by_model()
hemi = data.hemicycle_history()

n_decp_raw = rc("data/raw/decp.parquet")
n_contracts = rc("data/clean/contracts.parquet")
n_awards = rc("data/clean/awards.parquet")
n_profiles = rc("data/clean/profiles.parquet")
n_boamp_raw, n_boamp = rc("data/raw/boamp.parquet"), rc("data/clean/scored_boamp.parquet")
n_approch_raw, n_approch = rc("data/raw/approch.parquet"), rc("data/clean/scored.parquet")
n_train, n_test = metrics.get("n_train"), metrics.get("n_test")
n_report = main_bt.get("n_report")
ty, tey = metrics.get("train_years", ["", ""]), metrics.get("test_years", ["", ""])

COL = ["#0EA5E9", "#6366F1", "#22C55E", tx.TEAL, "#F59E0B", "#EC4899", "#1E293B"]

# ------------------------------------------------------------------------------------------ hero + flow
st.markdown(
    '<div class="ou-hero"><h2>⚙️ Comment ça marche</h2>'
    '<div class="sub">Des données publiques ouvertes à une recommandation claire, en sept étapes. '
    'Chaque chiffre de cette page vient des fichiers du projet.</div></div>', unsafe_allow_html=True)
st.write("")
pw.flow([("📥", "Collecte", COL[0]), ("🧹", "Nettoyage", COL[1]), ("🧭", "Profil", COL[2]),
         ("🌲", "LightGBM", COL[3]), ("🎚️", "Calibration", COL[4]), ("✍️", "Note LLM", COL[5]),
         ("🎯", "Application", COL[6])], height=210)

# ------------------------------------------------------------------------------------------ volumes
st.markdown("### 📊 Des millions de lignes aux appels d'offres qui comptent")
f1, f2 = st.columns([3, 2], gap="large")
with f1:
    steps = [("Lignes DECP brutes", n_decp_raw, COL[0]), ("Marchés dédoublonnés", n_contracts, COL[1])]
    if n_train and n_test:
        steps.append((f"Avec nombre d'offres, {ty[0]}–{tey[1]}", n_train + n_test, COL[2]))
        steps.append((f"Test jamais vu, {tey[0]}–{tey[1]}", n_test, COL[3]))
    if n_report:
        steps.append((f"Test final {bt.get('years', '')}", n_report, COL[4]))
    pw.funnel([s for s in steps if s[1]])
    ui.source("parquet (nombre de lignes) · artifacts/metrics.json · artifacts/rules_backtest.json. "
              "Largeurs à l'échelle racine carrée pour que les petites étapes restent visibles.")
with f2:
    st.markdown("**Appels d'offres notés aujourd'hui**")
    tsteps = [(f"BOAMP ouverts", n_boamp or 0, "#0EA5E9"), (f"APProch à venir", n_approch or 0, "#6366F1")]
    ui.kpi("Appels d'offres notés", pw.fr_int(sum(n for _, n, _ in tsteps)), "🎯",
           " · ".join(f"{lab} {pw.fr_int(n)}" for lab, n, _ in tsteps), tx.TEAL)
    st.write("")
    ui.kpi("Entreprises profilées", pw.fr_int(n_profiles or 0), "🏭",
           f"à partir de {pw.fr_int(n_awards or 0)} attributions", "#22C55E")
    ui.source("data/clean/scored*.parquet, profiles.parquet, awards.parquet (métadonnées)")

st.divider()

# ------------------------------------------------------------------------------------------ steps 1-3
a, b, c = st.columns(3, gap="medium")
with a:
    pw.step_card(1, "📥", "Collecte des données publiques",
                 "Marchés passés (DECP, data.gouv.fr), avis ouverts (BOAMP, DILA), projets d'achats de l'État (APProch) "
                 "et derniers marchés de chaque acheteur en direct, via l'API Hémicycle ; identité des entreprises (Sirene).",
                 [(pw.fr_millions(n_decp_raw or 0), "lignes DECP"), (pw.fr_int(n_boamp_raw or 0), "avis BOAMP"),
                  (pw.fr_int(n_approch_raw or 0), "projets APProch"),
                  (pw.fr_int(len(hemi)), "historiques acheteurs Hémicycle en cache")],
                 COL[0], "data/raw/*.parquet, artifacts/hemicycle_history.json")
with b:
    pw.step_card(2, "🧹", "Nettoyage et appariement",
                 "Un marché par acheteur et identifiant, codes CPV et départements harmonisés, doublons d'avis retirés. "
                 "Les procédures <b>sans publicité ni mise en concurrence</b> sont exclues : une offre unique y est attendue.",
                 [(pw.fr_millions(n_contracts or 0), "marchés"), (pw.share_labelled(), "indiquent le nombre d'offres"),
                  (pw.fr_int(n_boamp or 0), "avis BOAMP avec un code CPV")],
                 COL[1], "data/clean/*.parquet, reports/data_check.md")
with c:
    pw.step_card(3, "🧭", "Profil de l'entreprise",
                 "À partir de ses marchés gagnés : son métier (classe CPV à 4 chiffres) et ses départements. "
                 "On cherche d'abord le même métier dans ses départements, puis on élargit seulement s'il y a trop peu "
                 "d'appels d'offres.",
                 [(pw.fr_int(n_profiles or 0), "entreprises profilées"), ("4", "niveaux de correspondance")],
                 COL[2], "data/clean/profiles.parquet · src/profiles.py")

st.write("")

# ------------------------------------------------------------------------------------------ step 4: model
st.markdown("### 🌲 Étape 4 · Le modèle LightGBM")
m1, m2 = st.columns([2, 3], gap="large")
with m1:
    res = metrics.get("results", {})
    auc = res.get("model", {}).get("auc")
    pw.step_card(4, "🌲", "Prédire le nombre de candidats",
                 "Un modèle de gradient boosting apprend, sur les marchés passés, quand un appel d'offres ne reçoit "
                 "qu'une offre. Les taux historiques de l'acheteur et de la catégorie sont calculés <b>hors échantillon</b> "
                 "pour ne pas tricher.",
                 [(pw.fr_num(auc, 2) if auc else "—", "AUC sur des marchés jamais vus"),
                  (pw.fr_int(n_train or 0), f"marchés d'apprentissage {ty[0]}–{ty[1]}"),
                  (str(len(metrics.get("features") or metrics.get("importance_gain") or [])), "variables")],
                 COL[3], "artifacts/metrics.json")
with m2:
    st.markdown("**Ce qui pèse le plus dans le score**")
    if metrics.get("importance_gain"):
        pw.importance_bars(metrics["importance_gain"])
        ui.source("artifacts/metrics.json (importance « gain » de LightGBM)")

if n_train and n_report and n_test:
    st.write("")
    st.markdown("**Un découpage dans le temps, comme dans la vraie vie** : le modèle n'a jamais vu l'avenir.")
    pw.split_bar(n_train, n_test - n_report, n_report,
                 (f"{ty[0]}–{ty[1]}", str(bt.get("fit_years", tey[0])), str(bt.get("years", tey[1]))))
    ui.source("artifacts/metrics.json · artifacts/rules_backtest.json")

st.write("")

# ------------------------------------------------------------------------------------------ step 5: calibration + rules
st.markdown("### 🎚️ Étape 5 · Calibration et règles go / no-go")
th = bt.get("thresholds", {})
g = main_bt.get("groups", {})
pb, gf, bmin = th.get("passer_sous", 1.0), th.get("aller_des", 1.5), th.get("acheteur_min", 0.3)


def outcome(k: str) -> str:
    v = g.get(k)
    return (f"Testé sur {bt.get('years', '')} : <b>{pw.fr_pct(v['single_rate'])}</b> d'offres uniques "
            f"({pw.fr_int(v['n'])} marchés)") if v else ""


r1, r2, r3 = st.columns(3, gap="medium")
with r1:
    pw.rule_card("Aller", f"Chance d'offre unique au moins <b>{pw.fr_num(gf)} fois la moyenne</b>, métier déjà exercé dans "
                          f"le département, acheteur qui reçoit souvent une seule offre (≥ {round(100 * bmin)} %). "
                          "Ou : l'entreprise est le titulaire sortant.", outcome("Aller"))
with r2:
    pw.rule_card("À étudier", "Au-dessus de la moyenne, mais une condition manque : département nouveau, acheteur qui reçoit "
                              "souvent plusieurs offres, ou même titulaire sur les dernières éditions.", outcome("À étudier"))
with r3:
    pw.rule_card("Passer", f"Chance d'offre unique <b>sous {pw.fr_num(pb)} fois la moyenne</b> : la concurrence sera "
                           "habituelle ou forte.", outcome("Passer"))
st.caption(f"Le score brut est recalibré (régression isotonique sur {bt.get('fit_years', '')}) ; les seuils sont choisis "
           f"sur {bt.get('fit_years', '')} et vérifiés sur {bt.get('years', '')}. Les règles sont explicites : le LLM ne "
           "décide jamais.")
ui.source("artifacts/rules_backtest.json · src/explain.py (recommend)")

st.write("")

# ------------------------------------------------------------------------------------------ steps 6-7
d1, d2 = st.columns(2, gap="medium")
with d1:
    gem = bm.get("models", {}).get("Gemma 4 31B (Featherless, open-weight)", {})
    figs = []
    if gem:
        figs.append((f"{gem['pass']['tout']} / {gem['n']}", "notes conformes au premier essai (Gemma 4 31B)"))
    for model, n in notes_used.most_common():
        figs.append((pw.fr_int(n), f"notes vérifiées écrites par {model}"))
    pw.step_card(6, "✍️", "Une note claire, chiffres vérifiés",
                 "Un modèle de langage ouvert (Gemma 4 via Featherless) rédige deux phrases à partir des faits calculés. "
                 "Chaque chiffre de la note doit figurer dans les faits, la recommandation ne peut pas changer : "
                 "sinon la note est refusée.", figs, COL[5], "artifacts/llm_benchmark.json · artifacts/notes.json")
with d2:
    pw.step_card(7, "🎯", "L'application",
                 "La PME entre son SIREN : son profil, les appels d'offres de son métier classés du moins au plus disputé, "
                 "avec Aller / À étudier / Passer, la note, l'historique de l'acheteur et un suivi des échéances.",
                 [(pw.fr_int((n_boamp or 0) + (n_approch or 0)), "appels d'offres notés"),
                  (pw.fr_int(n_profiles or 0), "entreprises qui peuvent l'utiliser")],
                 COL[6], "data/clean/scored*.parquet, profiles.parquet")

st.divider()
st.caption("Toutes les sources sont ouvertes (Licence Ouverte 2.0, Etalab) : DECP consolidées (data.gouv.fr), BOAMP (DILA), "
           "APProch et Marchés publics notifiés via l'API Hémicycle, Sirene (Insee).")
