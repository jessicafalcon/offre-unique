"""Preuves: is the score any good, are the go / no-go rules any good, which model writes the notes.

Same content as the Preuves tab of the main app.py, redesigned. Every number is read from artifacts/
(metrics.json, metrics_boamp.json, rules_backtest.json, llm_benchmark.json, notes.json).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import data, ui
from lib import proof_widgets as pw
from lib import taxonomy as tx

metrics = data.metrics()
if not metrics:
    st.warning("Lancez `python src/train.py` pour générer les résultats.")
    st.stop()

res = metrics["results"]
avg = metrics["test_single_bid_rate"]
bt = data.backtest() or {}
main_bt = bt.get("main", {})
groups = main_bt.get("groups", {})
mb = data.metrics("_boamp")
ty, tey = metrics["train_years"], metrics["test_years"]

# ------------------------------------------------------------------------------------------ hero
st.markdown(
    f'<div class="ou-hero"><h2>🔬 Le score fonctionne-t-il ?</h2>'
    f'<div class="sub">Le modèle a appris sur les marchés de {ty[0]}–{ty[1]} ({pw.fr_int(metrics["n_train"])} marchés), '
    f'puis a été testé sur {pw.fr_int(metrics["n_test"])} marchés de {tey[0]}–{tey[1]} qu\'il n\'avait jamais vus.</div></div>',
    unsafe_allow_html=True)
st.write("")

top10 = res["model"]["precision_top10"]
k1, k2, k3, k4 = st.columns(4)
with k1:
    ui.kpi("Précision du score", pw.fr_pct(top10), "🎯", "parmi les 10 % de marchés jugés les plus à risque", tx.TEAL)
with k2:
    ui.kpi("Moyenne, sans score", pw.fr_pct(avg), "⚖️", f"marchés {tey[0]}–{tey[1]} à une seule offre", "#94A3B8")
with k3:
    ui.kpi("Gain sur la moyenne", f"× {pw.fr_num(top10 / avg)}", "🚀", "plus d'offres uniques repérées", "#16A34A")
with k4:
    ui.kpi("AUC", pw.fr_num(res["model"]["auc"], 2), "📈", "0,5 = hasard · 1 = parfait", "#6366F1")
st.write("")

# ------------------------------------------------------------------------------------------ score vs baselines + rules
left, right = st.columns(2, gap="large")
with left:
    st.markdown("#### Parmi les 10 % de marchés jugés les plus à risque, part de ceux qui n'ont reçu qu'une seule offre")
    pw.precision_bars(res, avg)
    ui.source(f"artifacts/metrics.json · test sur {pw.fr_int(metrics['n_test'])} marchés {tey[0]}–{tey[1]}")
with right:
    if groups:
        st.markdown(f"#### Les recommandations, testées sur les marchés {bt.get('years', '')}")
        pw.backtest_bars(groups, main_bt.get("report_rate"))
        st.caption(f"Seuils et calibration fixés sur {bt.get('fit_years', '')}, avant de regarder {bt.get('years', '')} : "
                   "part de marchés qui n'ont reçu qu'une offre. "
                   "Sans la condition « déjà gagné ce métier dans ce département », qui dépend de l'entreprise.")
        ui.source("artifacts/rules_backtest.json (src/backtest_rules.py)")

if mb:
    m = mb["results"]["model"]
    st.info(f"📭 **Appels d'offres ouverts (BOAMP)** : ces avis ne donnent ni montant ni durée, ils sont notés par une "
            f"version du score sans ces informations. Sur le même test : "
            f"**{round(100 * m['precision_top10'])} %** parmi les 10 % les plus à risque (AUC {pw.fr_num(m['auc'], 2)}).")

# ------------------------------------------------------------------------------------------ calibration
cal = main_bt.get("calibration_2026")
if cal:
    st.markdown("### 🎚️ Un score de 30 % veut dire environ 30 %")
    c1, c2 = st.columns([3, 2], gap="large")
    with c1:
        pw.calibration_chart(cal)
        ui.source(f"artifacts/rules_backtest.json · marchés {bt.get('years', '')} regroupés par dixième de score")
    with c2:
        st.write("")
        st.markdown(
            "Les sorties brutes du modèle étaient trop hautes. Elles sont **recalibrées** (régression isotonique "
            f"ajustée sur {bt.get('fit_years', '')}), puis vérifiées sur {bt.get('years', '')} : la courbe calibrée suit "
            "la diagonale.")
        st.markdown("Les pourcentages affichés dans l'application sont calibrés : un score de 30 % correspond "
                    "à environ 30 % d'offres uniques observées.")
        hi_raw, hi_cal, hi_obs = cal["raw"][-1], cal["cal"][-1], cal["obs"][-1]
        ui.kpi("Dixième le plus à risque", f"{pw.fr_pct(hi_cal)} affiché", "🎯",
               f"{pw.fr_pct(hi_obs)} observé · {pw.fr_pct(hi_raw)} avant calibration", tx.TEAL)

with st.expander("Détail technique"):
    names = {"model": "Notre score", "baseline_buyer_history": "Historique de l'acheteur",
             "baseline_cpv_category": "Taux de la catégorie"}
    tbl = pd.DataFrame({names[k]: v for k, v in res.items()}).T
    st.dataframe(pd.DataFrame({
        "AUC": tbl["auc"].map(lambda v: pw.fr_num(v, 3)),
        "Précision top 10 %": tbl["precision_top10"].map(lambda v: pw.fr_pct(v, 1)),
        "Brier": tbl["brier"].map(lambda v: pw.fr_num(v, 3)),
    }), width="stretch")
    st.caption("AUC : capacité à classer les marchés du plus au moins risqué (0,5 = hasard). "
               "Brier : erreur des probabilités (plus bas = mieux).")

# ------------------------------------------------------------------------------------------ LLM benchmark
bm = data.benchmark()
if bm:
    st.markdown("### ✍️ Quel modèle écrit les notes ?")
    st.write(f"Mêmes faits, même consigne, **une seule tentative** par note, sur {bm['n']} appels d'offres de "
             f"{bm['company']}. Une note est conforme si tous ses chiffres viennent des données, si elle garde la "
             "recommandation calculée par les règles, et si elle tient en 2 phrases et 45 mots, en français.")
    used = pw.notes_by_model()
    models = bm["models"]
    cols = st.columns(len(models))
    best = max(models.values(), key=lambda m: m["pass"]["tout"] / max(m["n"], 1))
    for col, (lab, m) in zip(cols, models.items()):
        share = m["pass"]["tout"] / max(m["n"], 1)
        color = tx.TEAL if m is best else ("#F59E0B" if share >= 0.5 else "#EF4444")
        usd = m.get("usd_per_1000_notes")
        sub = " · ".join(x for x in [
            f"{pw.fr_num(m['median_seconds'])} s par note" if m.get("median_seconds") else "",
            f"{usd:.2f} $ / 1 000 notes".replace(".", ",") if usd is not None else "coût n.d.",
            f"{used.get(m.get('model'), 0)} notes dans l'app" if used.get(m.get("model")) else ""] if x)
        with col:
            ui.kpi(lab, f"{m['pass']['tout']} / {m['n']}", "🏆" if m is best else "📝", sub, color)
    with st.expander("Détail des contrôles par modèle"):
        checks = {"chiffres": "Chiffres présents dans les données", "denominateur": "Bon dénominateur",
                  "verdict": "Recommandation inchangée", "format": "2 phrases, 45 mots", "francais": "En français"}
        st.dataframe(pd.DataFrame({lab: {v: f"{m['pass'].get(k, 0)} / {m['n']}" for k, v in checks.items()}
                                   for lab, m in models.items()}), width="stretch")
    st.caption("Les notes de l'application sont écrites par Gemma 4 31B (modèle ouvert, via Featherless). "
               + " ".join(bm.get("caveats", [])))
    ui.source("artifacts/llm_benchmark.json (src/benchmark_llm.py) · artifacts/notes.json")

# ------------------------------------------------------------------------------------------ sources and limits
s1, s2 = st.columns(2, gap="large")
with s1:
    st.markdown("### 📚 Sources")
    st.write("Projets d'achats publics (APProch) et derniers marchés de chaque acheteur (« Marchés publics notifiés »), "
             "via l'API Hémicycle ; historique complet pour l'entraînement du score : DECP consolidées (data.gouv.fr)"
             + ("; appels d'offres ouverts du BOAMP (DILA)" if pw.has_boamp() else "")
             + ". Licence Ouverte 2.0 (Etalab).")
with s2:
    st.markdown("### ⚠️ Limites")
    st.markdown(
        f"- Seuls {pw.share_labelled()} des marchés publiés indiquent le nombre d'offres reçues : le score apprend sur ceux-là.\n"
        + ("- Les appels d'offres ouverts (BOAMP) ne donnent pas de montant : leur score s'en passe.\n" if pw.has_boamp() else
           "- Les achats à venir (APProch) viennent surtout de l'État ; beaucoup de collectivités n'y publient pas.\n") +
        "- Le score décrit des régularités passées, pas des causes.\n"
        "- Un titulaire qui gagne plusieurs fois n'indique en soi aucune irrégularité.\n"
        "- Une offre unique ne signale pas en soi une irrégularité de l'acheteur : elle peut venir d'un marché étroit ou très spécialisé.\n"
        "- Le score dit combien d'offres un marché reçoit d'habitude, pas si vous le gagnerez."
    )
