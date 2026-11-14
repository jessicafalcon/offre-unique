"""Offre unique: upcoming public tenders where a company would face little competition.

    python -m streamlit run app.py
Reads only precomputed files: data/clean/scored.parquet, awards.parquet, artifacts/metrics.json, notes.json
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))
from common import ART, CLEAN  # noqa: E402
from profiles import describe_profile, fit_table, load_all_scored, profile_of, relevant  # noqa: E402

# Share of DECP contracts that report the number of bids (reports/data_check.md). Update if the data changes.
SHARE_LABELLED = os.environ.get("SHARE_LABELLED", "42 %")

st.set_page_config(page_title="Offre unique", layout="wide")


@st.cache_data
def load():
    scored = load_all_scored()
    awards = pd.read_parquet(CLEAN / "awards.parquet")
    metrics = json.loads((ART / "metrics.json").read_text()) if (ART / "metrics.json").exists() else None
    mb = ART / "metrics_boamp.json"
    metrics_boamp = json.loads(mb.read_text()) if mb.exists() else None
    return scored, awards, metrics, metrics_boamp


def load_notes() -> dict:
    p = ART / "notes.json"
    return json.loads(p.read_text()) if p.exists() else {}


FOLLOWS = ART / "follows.json"


def load_follows() -> dict:
    try:
        return json.loads(FOLLOWS.read_text()) if FOLLOWS.exists() else {}
    except (OSError, ValueError):
        return {}


def save_follows(f: dict) -> None:
    FOLLOWS.write_text(json.dumps(f, ensure_ascii=False, indent=1))


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
        return fmt_date(r["due_date"])
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
has_boamp = "source" in scored and (scored["source"] == "BOAMP").any()
avg = metrics["test_single_bid_rate"] if metrics else None

st.title("Offre unique")
st.caption("1 marché public sur 5 ne reçoit qu'une seule offre. Offre unique montre à une PME les appels d'offres "
           "de son métier qui manquent de candidats, là où sa candidature compte le plus. D'après les marchés passés"
           + (", les appels d'offres ouverts (BOAMP) et les projets d'achats de l'État (APProch)." if has_boamp
              else " et les projets d'achats publiés par l'État."))

tab_main, tab_proof = st.tabs(["Appels d'offres", "Preuves"])

with tab_main:
    siren = st.text_input("SIREN de votre entreprise", value=os.environ.get("DEMO_SIREN", ""), max_chars=14,
                          help="Réservé aux sociétés. N'entrez pas le SIREN d'un entrepreneur individuel : "
                               "son profil serait celui d'une personne.").strip()
    prof = profile_of(awards, siren[:9]) if siren else None
    if not siren:
        st.write("Entrez un SIREN pour voir les appels d'offres à venir qui vous correspondent.")
        st.stop()
    if not prof:
        st.write("Aucun marché gagné trouvé pour ce SIREN dans les données publiques.")
        st.stop()

    st.subheader(prof["name"] or f"Entreprise {prof['siren']}")
    st.caption(describe_profile(prof))

    t = fit_table(prof, scored, awards)
    t = relevant(t).sort_values("proba", ascending=False).reset_index(drop=True)
    if t.empty:
        st.write("Aucun achat à venir ne correspond à votre historique.")
        st.stop()

    left, right = st.columns([11, 9], gap="large")
    with left:
        n_open = int((t["source"] == "BOAMP").sum()) if "source" in t else 0
        head = f"{len(t)} appels d'offres dans votre métier, les moins disputés d'abord"
        if n_open:
            head += f" · {n_open} ouverts maintenant"
        st.caption(head)
        cols = {}
        if has_boamp:
            cols["Type"] = t["source"].map({"BOAMP": "Ouvert", "APProch": "Projet"}).fillna("Projet")
        view = pd.DataFrame({
            **cols,
            "Achat": t["libelle"].astype(str),
            "Acheteur": t["buyer_name"].fillna(t["buyer_siren"]).astype(str),
            "Échéance": [when(r) for _, r in t.iterrows()],
            "Offre unique": (100 * t["proba"]).round().astype(int).astype(str) + " %",
        })
        height = min(44 + 36 * len(view), 470)
        ev = st.dataframe(
            view, hide_index=True, width="stretch", height=height,
            on_select="rerun", selection_mode="single-row",
            column_config={
                "Type": st.column_config.TextColumn(width="small"),
                "Achat": st.column_config.TextColumn(width="large"),
                "Acheteur": st.column_config.TextColumn(width="medium"),
                "Échéance": st.column_config.TextColumn(width="small"),
                "Offre unique": st.column_config.TextColumn(width="small"),
            },
        )
        foot = "% = chance qu'une seule offre soit déposée"
        if avg is not None:
            foot += f" · moyenne : {round(100 * avg)} %"
        st.caption(foot)
        rows = ev.selection.rows if ev and ev.selection else []
        idx = rows[0] if rows else 0

    r = t.iloc[idx]
    with right:
        st.markdown(f"#### {r.get('libelle') or 'Achat sans titre'}")
        buyer = r.get("buyer_name") if isinstance(r.get("buyer_name"), str) else f"SIREN {r.get('buyer_siren')}"
        kind = "appel d'offres ouvert (BOAMP)" if r.get("source") == "BOAMP" else "projet d'achat (APProch)"
        meta = [kind, buyer, str(r.get("montant_estime_du_marche") or ""),
                duration_text(r.get("duree_previsionnelle_du_marche"))]
        if pd.notna(r.get("due_date")):
            meta.append(f"offres dues le {fmt_date(r['due_date'])}")
        elif pd.notna(r.get("pub_date")):
            meta.append(f"publication prévue en {pd.Timestamp(r['pub_date']).strftime('%m/%Y')}")
        st.caption(" · ".join(m for m in meta if m and m not in {"None", "nan"}))

        risk = round(100 * float(r["proba"]))
        risk_line = f"**{risk} %** de chances qu'une seule offre soit déposée"
        if avg:
            risk_line += f" ({fr_num(float(r['proba']) / avg)} × la moyenne)"
        st.markdown(risk_line)
        for s in fact_sentences(r, prof["siren"]):
            st.write(s)

        notes = load_notes()
        key = f"{prof['siren']}:{r.get('code')}"
        note = notes.get(key)
        st.divider()
        if note and note.get("verified") and note.get("note", "").strip():
            st.write(note["note"])
        elif st.button("Rédiger la note go / no-go"):
            try:
                from explain import facts_for, generate, save_cache
                res = generate(facts_for(r, prof))
                notes[key] = res
                save_cache(notes)
                st.write(res["note"] if res["verified"] else "Note écartée : elle contenait des chiffres absents des données.")
            except Exception as e:  # keep the demo alive if the API fails
                st.caption(f"Note indisponible ({e.__class__.__name__}).")

        c1, c2 = st.columns([1, 1])
        fkey = f"{prof['siren']}:{r.get('code')}"
        if fkey in load_follows():
            c1.button("✓ Suivi", disabled=True, key=f"fd_{fkey}")
        elif c1.button("Suivre cet appel d'offres", key=f"f_{fkey}"):
            link = r.get("lien_vers_la_consultation")
            f = load_follows()
            f[fkey] = {
                "title": str(r.get("libelle") or "Achat sans titre"),
                "buyer": buyer,
                "due": pd.Timestamp(r["due_date"]).isoformat() if pd.notna(r.get("due_date")) else None,
                "when": when(r),
                "risk": round(100 * float(r["proba"])),
                "reco": reco_of(note.get("note", "") if note else ""),
                "url": link if isinstance(link, str) and link.startswith("http") else "",
                "source": str(r.get("source") or ""),
                "followed_at": pd.Timestamp.now().isoformat(timespec="seconds"),
            }
            save_follows(f)
            st.rerun()
        if isinstance(r.get("lien_vers_la_consultation"), str) and r["lien_vers_la_consultation"].startswith("http"):
            c2.link_button("Voir l'avis BOAMP" if r.get("source") == "BOAMP" else "Voir la consultation",
                           r["lien_vers_la_consultation"])

        with st.expander("Détail des marchés passés"):
            eds = pd.DataFrame(json.loads(r.get("hist_editions") or "[]"))
            if not eds.empty:
                past = pd.DataFrame({
                    "Date": pd.to_datetime(eds["date"], errors="coerce").dt.strftime("%d/%m/%Y").fillna(""),
                    "Objet": eds["objet"].fillna("").astype(str),
                    "Offres": eds["offres"].map(lambda v: "" if pd.isna(v) or v <= 0 else str(int(v))),
                    "Titulaire": (eds["titulaire_nom"] if "titulaire_nom" in eds else pd.Series("", index=eds.index))
                    .fillna("—").replace({"None": "—", "": "—"}).astype(str),
                })
                st.dataframe(past, hide_index=True, width="stretch", column_config={
                    "Date": st.column_config.TextColumn(width="small"),
                    "Objet": st.column_config.TextColumn(width="large"),
                    "Offres": st.column_config.TextColumn(width="small"),
                    "Titulaire": st.column_config.TextColumn(width="medium"),
                })
            else:
                st.caption("Aucun marché comparable de cet acheteur dans les données.")

with tab_proof:
    if not metrics:
        st.write("Lancez `python src/train.py` pour générer les résultats.")
    else:
        res = metrics["results"]
        st.subheader("Le score fonctionne-t-il ?")
        st.write(f"Le modèle a appris sur les marchés de {metrics['train_years'][0]}–{metrics['train_years'][1]} "
                 f"({fr_int(metrics['n_train'])} marchés), puis a été testé sur {fr_int(metrics['n_test'])} marchés de "
                 f"{metrics['test_years'][0]}–{metrics['test_years'][1]} qu'il n'avait jamais vus.")
        st.write("Parmi les 10 % de marchés jugés les plus à risque, part de ceux qui n'ont reçu qu'une seule offre :")
        c1, c2, c3 = st.columns(3)
        c1.metric("Notre score", f"{round(100 * res['model']['precision_top10'])} %")
        c2.metric("Historique de l'acheteur seul", f"{round(100 * res['baseline_buyer_history']['precision_top10'])} %")
        c3.metric("Moyenne, sans score", f"{round(100 * avg)} %")
        bt_p = ART / "rules_backtest.json"
        if bt_p.exists():
            bt = json.loads(bt_p.read_text())
            g = bt.get("main", {}).get("groups", {})
            if g:
                st.write(f"**Les recommandations, testées sur les marchés {bt['years']}** (seuils et calibration fixés sur "
                         f"{bt['fit_years']}, avant de regarder {bt['years']}) : part de marchés qui n'ont reçu qu'une offre.")
                k1, k2, k3 = st.columns(3)
                for col, k in zip((k1, k2, k3), ("Aller", "À étudier", "Passer")):
                    col.metric(f"« {k} »", f"{round(100 * g[k]['single_rate'])} %", help=f"{fr_int(g[k]['n'])} marchés")
                st.caption("Sans la condition « déjà gagné ce métier dans ce département », qui dépend de l'entreprise. "
                           "Les pourcentages affichés dans l'application sont calibrés : un score de 30 % correspond "
                           "à environ 30 % d'offres uniques observées.")
        if metrics_boamp:
            mb = metrics_boamp["results"]
            st.caption(f"Appels d'offres ouverts (BOAMP) : ces avis ne donnent ni montant ni durée, ils sont notés par une "
                       f"version du score sans ces informations. Sur le même test : "
                       f"{round(100 * mb['model']['precision_top10'])} % parmi les 10 % les plus à risque.")
        with st.expander("Détail technique"):
            names = {"model": "Notre score", "baseline_buyer_history": "Historique de l'acheteur",
                     "baseline_cpv_category": "Taux de la catégorie"}
            tbl = pd.DataFrame({names[k]: v for k, v in res.items()}).T
            st.dataframe(pd.DataFrame({
                "AUC": tbl["auc"].round(3),
                "Précision top 10 %": (100 * tbl["precision_top10"]).round(1).astype(str) + " %",
                "Brier": tbl["brier"].round(3),
            }), width="stretch")
            st.caption("AUC : capacité à classer les marchés du plus au moins risqué (0,5 = hasard). "
                       "Brier : erreur des probabilités (plus bas = mieux).")
        st.subheader("Sources")
        st.write("Projets d'achats publics (APProch), via l'API Hémicycle ; marchés publics notifiés "
                 "(DECP consolidées, data.gouv.fr, également disponibles dans Hémicycle)"
                 + ("; appels d'offres ouverts du BOAMP (DILA)" if has_boamp else "")
                 + ". Licence Ouverte 2.0 (Etalab).")
        st.subheader("Limites")
        st.markdown(
            f"- Seuls {SHARE_LABELLED} des marchés publiés indiquent le nombre d'offres reçues : le score apprend sur ceux-là.\n"
            + ("- Les appels d'offres ouverts (BOAMP) ne donnent pas de montant : leur score s'en passe.\n" if has_boamp else
               "- Les achats à venir (APProch) viennent surtout de l'État ; beaucoup de collectivités n'y publient pas.\n") +
            "- Le score décrit des régularités passées, pas des causes.\n"
            "- Un titulaire qui gagne plusieurs fois n'indique en soi aucune irrégularité.\n"
            "- Une offre unique ne signale pas en soi une irrégularité de l'acheteur : elle peut venir d'un marché étroit ou très spécialisé.\n"
            "- Le score dit combien d'offres un marché reçoit d'habitude, pas si vous le gagnerez."
        )


if siren and prof:
    render_follows(prof["siren"])
