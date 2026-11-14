"""Align open BOAMP notices with the APProch columns used by scoring and the app.

    python src/prepare_boamp.py      -> data/clean/boamp.parquet
"""
from __future__ import annotations

import pandas as pd

from common import (CLEAN, RAW, TODAY, categorie_from_cpv, cpv_class, cpv_div, cpv_group, dept_from_code,
                    low, procedure_canon, siren_of)


def main():
    b = pd.read_parquet(RAW / "boamp.parquet")
    n0 = len(b)
    # keep calls for tender only (not corrections, results or pre-information notices)
    nat = b["nature_libelle"].map(low)
    keep = nat.str.contains("avis de marche|appel|concession", regex=True) & ~nat.str.contains(
        "rectif|resultat|attribution|annul|pre-?information|intention", regex=True)
    b = b[keep].copy()
    print(f"{n0:,} notices → {len(b):,} calls for tender (nature kept: {b['nature_libelle'].value_counts().head(3).to_dict()})")

    out = pd.DataFrame({
        "code": "BOAMP-" + b["idweb"].astype(str),
        "libelle": b["objet"].astype(str),
        "buyer_name": b["nomacheteur"],
        "buyer_siren": b["buyer_siret"].map(siren_of),
        "cpv_div": b["cpv"].map(cpv_div),
        "cpv_grp": b["cpv"].map(cpv_group),
        "cpv_cls": b["cpv"].map(cpv_class),
        "procedure_c": b["procedure_libelle"].map(procedure_canon),
        "amount_band": "NA", "duration_bin": "NA", "clause_sociale": 0, "clause_env": 0,
        "dept": [dept_from_code(d, "departement") if d else "NA" for d in b["dept_first"]],
        "departements": b["departements"],
        "pub_date": pd.to_datetime(b["dateparution"], errors="coerce", utc=True).dt.tz_localize(None),
        "due_date": pd.to_datetime(b["datelimitereponse"], errors="coerce", utc=True).dt.tz_localize(None),
        "lien_vers_la_consultation": b["url_avis"],
        "type_marche": b["type_marche"].astype(str),
        "source": "BOAMP",
    })
    out["categorie"] = out["cpv_div"].map(categorie_from_cpv)
    out = out[out["due_date"].isna() | (out["due_date"] >= TODAY)]
    out = out[out["cpv_div"] != "NA"]  # without a CPV code the trade matching cannot work
    print(f"{len(out):,} open calls for tender with a CPV code · buyer SIREN found: {out['buyer_siren'].notna().mean():.0%}"
          f" · top divisions: {out['cpv_div'].value_counts().head(5).to_dict()}")
    out.to_parquet(CLEAN / "boamp.parquet", index=False)
    print(f"saved {CLEAN / 'boamp.parquet'}")


if __name__ == "__main__":
    main()
