"""Reference list for a tender application: a company's recent public contracts as an editable Word file.

Tenders ask candidates for their main references: the last 3 years for services and supplies, the last
5 years for works (arrêté du 22 mars 2019). This builds that list from the contracts the company has won
in DECP. Nothing is written by an LLM: every line is a published contract.

    python src/references.py 834709248          # writes references_834709248.docx in the current folder
"""
from __future__ import annotations

import io
import sys

import pandas as pd

MAX_ROWS = 50
YEARS = {"Travaux": 5}  # other categories: 3
SOURCE = "Source : DECP consolidées (data.gouv.fr), Licence Ouverte 2.0."


def reference_rows(awards: pd.DataFrame, siren: str, today: pd.Timestamp | None = None) -> tuple[pd.DataFrame, int]:
    """(rows to print, number of contracts inside the reference period). Most recent first, exact duplicates
    removed, capped at MAX_ROWS."""
    today = pd.Timestamp(today or pd.Timestamp.now()).normalize()
    w = awards[awards["company_siren"] == siren].copy()
    w["date"] = pd.to_datetime(w["date"], errors="coerce")
    w = w[w["date"].notna() & (w["date"] <= today)]
    years = w["categorie"].astype(str).map(YEARS).fillna(3).astype(int)
    start = pd.Series([today - pd.DateOffset(years=int(y)) for y in years], index=w.index, dtype="datetime64[ns]")
    w = w[w["date"] >= start]
    w = w.drop_duplicates(["acheteur_nom", "objet", "date", "montant"]).sort_values("date", ascending=False)
    return w.head(MAX_ROWS), len(w)


def _eur(v) -> str:
    return "" if pd.isna(v) or v <= 0 else f"{round(v):,}".replace(",", " ") + " €"


def reference_docx(awards: pd.DataFrame, siren: str, name: str | None, today: pd.Timestamp | None = None) -> bytes | None:
    """The Word file as bytes, or None if the company has no contract inside the reference period."""
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.shared import Pt

    rows, total = reference_rows(awards, siren, today)
    if rows.empty:
        return None
    today = pd.Timestamp(today or pd.Timestamp.now())
    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = sec.page_height, sec.page_width
    doc.styles["Normal"].font.size = Pt(9)

    doc.add_heading("Liste des principales références", level=1)
    doc.add_paragraph(f"{name or 'Entreprise'} · SIREN {siren}")
    has_works = (rows["categorie"].astype(str) == "Travaux").any()
    period = "5 dernières années pour les travaux, 3 pour les services et fournitures" if has_works else "3 dernières années"
    shown = (f"les {len(rows)} plus récents sur {total}" if total > len(rows)
             else f"{total} marché{'s' if total > 1 else ''}")
    doc.add_paragraph(f"Marchés publics attribués à l'entreprise ({period}) : {shown}.")

    cols = ["Date de notification", "Acheteur", "Objet du marché", "Dép.", "Montant déclaré (HT)",
            "Dates d'exécution (à compléter)", "Contact chez l'acheteur (à compléter)"]
    table = doc.add_table(rows=1, cols=len(cols))
    table.style = "Light Grid Accent 1"
    for cell, label in zip(table.rows[0].cells, cols):
        cell.text = label
    for r in rows.itertuples():
        dept = "" if str(r.dept) == "NA" else str(r.dept)
        vals = [f"{r.date:%d/%m/%Y}", "" if pd.isna(r.acheteur_nom) else str(r.acheteur_nom),
                "" if pd.isna(r.objet) else str(r.objet), dept, _eur(r.montant), "", ""]
        for cell, v in zip(table.add_row().cells, vals):
            cell.text = v

    doc.add_paragraph()
    doc.add_paragraph(
        "À vérifier avant envoi : les montants sont ceux déclarés par l'acheteur (pour un accord-cadre, c'est "
        "souvent le montant maximum, pas le montant exécuté). Complétez les dates d'exécution et le contact, "
        "retirez les marchés sans rapport avec la consultation et ajoutez vos références privées. Le règlement "
        "de la consultation précise la période et la forme attendues.")
    doc.add_paragraph(f"{SOURCE} Liste produite le {today:%d/%m/%Y}.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


if __name__ == "__main__":
    from common import CLEAN

    s = sys.argv[1]
    p = CLEAN / "awards_app.parquet"
    a = pd.read_parquet(p, filters=[("company_siren", "==", s)]) if p.exists() else pd.read_parquet(CLEAN / "awards.parquet")
    names = a.loc[a["company_siren"] == s, "titulaire_nom"].dropna()
    data = reference_docx(a, s, names.mode().iloc[0] if len(names) else None)
    if data is None:
        sys.exit("Aucun marché dans la période de référence.")
    out = f"references_{s}.docx"
    open(out, "wb").write(data)
    print(f"{out}: {len(data):,} octets")
