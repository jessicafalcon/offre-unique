"""Load raw DECP + APProch, normalise them and build aligned features.

    python src/prepare.py                         # uses data/raw/decp.parquet (or .csv)
    python src/prepare.py --decp path/to/file.parquet

Writes:
    data/clean/contracts.parquet  one row per contract (buyer + id), with features and label
    data/clean/awards.parquet     one row per (contract, winning company): used for company profiles
    data/clean/approch.parquet    upcoming purchases with the same features
    artifacts/amount_edges.json   amount band edges taken from APProch
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from common import (ALIASES, ART, CLEAN, RAW, amount_to_band, approch_band_to_band, band_edges_from_approch,
                    categorie_from_cpv, cpv_class, cpv_div, cpv_group, dept_from_code, duration_bin, duration_months,
                    first_dept, missing_required, normalize_decp_columns, procedure_canon, siren_of, yes_no,
                    _norm_name)


def find_raw(name: str, override: str | None):
    if override:
        return override
    for ext in ("parquet", "csv"):
        p = RAW / f"{name}.{ext}"
        if p.exists():
            return str(p)
    raise SystemExit(f"No data/raw/{name}.parquet or .csv found")


def load_decp(path: str) -> pd.DataFrame:
    wanted = {a for alts in ALIASES.values() for a in alts} | set(ALIASES)
    if path.endswith(".parquet"):
        cols = pq.read_schema(path).names
        keep = [c for c in cols if _norm_name(c) in wanted or _norm_name(c).replace(".", "_") in wanted]
        df = pd.read_parquet(path, columns=keep or None)
    else:
        head = pd.read_csv(path, nrows=0, sep=None, engine="python")
        keep = [c for c in head.columns if _norm_name(c) in wanted]
        df = pd.read_csv(path, usecols=keep or None, sep=None, engine="python", dtype=str)
    df.columns = [c.replace(".", "_") for c in df.columns]
    return normalize_decp_columns(df)


def build_contract_features(d: pd.DataFrame, edges) -> pd.DataFrame:
    d = d.copy()
    d["buyer_siren"] = d["acheteur_id"].map(siren_of)
    d["cpv_div"] = d["codecpv"].map(cpv_div)
    d["cpv_grp"] = d["codecpv"].map(cpv_group)
    d["cpv_cls"] = d["codecpv"].map(cpv_class)
    d["categorie"] = d["cpv_div"].map(categorie_from_cpv)
    d["procedure_c"] = d["procedure"].map(procedure_canon)
    d["montant"] = pd.to_numeric(d["montant"], errors="coerce")
    d["amount_band"] = amount_to_band(d["montant"], edges)
    d["duration_m"] = pd.to_numeric(d.get("dureemois"), errors="coerce") if "dureemois" in d else np.nan
    d["duration_bin"] = duration_bin(d["duration_m"])
    tc = d["lieuexecution_typecode"] if "lieuexecution_typecode" in d else pd.Series("", index=d.index)
    lc = d["lieuexecution_code"] if "lieuexecution_code" in d else pd.Series("", index=d.index)
    d["dept"] = [dept_from_code(c, t) for c, t in zip(lc, tc)]
    d["clause_sociale"] = d["considerationssociales"].map(yes_no) if "considerationssociales" in d else 0
    d["clause_env"] = d["considerationsenvironnementales"].map(yes_no) if "considerationsenvironnementales" in d else 0
    d["date"] = pd.to_datetime(d["datenotification"], errors="coerce", utc=True).dt.tz_localize(None)
    d["year"] = d["date"].dt.year
    d["offres"] = pd.to_numeric(d["offresrecues"], errors="coerce")
    d["valid_label"] = d["offres"].between(1, 200)
    d["single_bid"] = (d["offres"] == 1).astype("Int64").where(d["valid_label"])
    d["excluded_procedure"] = d["procedure_c"].isin({"sans_pub"})
    return d


def build_approch_features(a: pd.DataFrame, edges) -> pd.DataFrame:
    a = a.rename(columns={c: _norm_name(c) for c in a.columns}).copy()
    g = lambda c: a[c] if c in a else pd.Series(np.nan, index=a.index)
    a["buyer_siren"] = g("siren_de_l_entite_acheteuse").map(siren_of)
    a["cpv_div"] = g("code_s_cpv").map(cpv_div)
    a["cpv_grp"] = g("code_s_cpv").map(cpv_group)
    a["cpv_cls"] = g("code_s_cpv").map(cpv_class)
    a["categorie"] = a["cpv_div"].map(categorie_from_cpv)
    a["procedure_c"] = g("type_de_procedure").map(procedure_canon)
    a["amount_band"] = approch_band_to_band(g("montant_estime_du_marche"), edges)
    a["duration_m"] = g("duree_previsionnelle_du_marche").map(duration_months)
    a["duration_bin"] = duration_bin(a["duration_m"])
    a["dept"] = g("departement_s_d_execution_du_marche").map(first_dept)
    a["clause_sociale"] = g("considerations_sociales").map(yes_no)
    a["clause_env"] = g("considerations_environnementales").map(yes_no)
    a["pub_date"] = pd.to_datetime(g("date_previsionnelle_de_publication"), errors="coerce", utc=True).dt.tz_localize(None)
    a["due_date"] = pd.to_datetime(g("date_cible_de_remise_des_offres"), errors="coerce", utc=True).dt.tz_localize(None)
    return a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decp")
    ap.add_argument("--approch")
    args = ap.parse_args()

    approch_raw = pd.read_parquet(find_raw("approch", args.approch))
    approch_raw.columns = [_norm_name(c) for c in approch_raw.columns]
    edges = band_edges_from_approch(approch_raw.get("montant_estime_du_marche", pd.Series(dtype=str)))
    (ART / "amount_edges.json").write_text(json.dumps(edges))
    print(f"amount band edges: {edges}")

    decp = load_decp(find_raw("decp", args.decp))
    miss = missing_required(decp)
    if miss:
        raise SystemExit(f"DECP is missing required columns {miss}. Columns found: {list(decp.columns)}\n"
                         "Add the right spelling to ALIASES in src/common.py")
    print(f"DECP raw rows: {len(decp):,}")

    if "idmodification" in decp:
        m = pd.to_numeric(decp["idmodification"], errors="coerce")
        decp = decp[m.isna() | (m == 0)]
        print(f"after keeping initial awards only: {len(decp):,}")

    decp = build_contract_features(decp, edges)

    # Awards: one row per winning company (titulaire_id_1..3, or one row per titulaire in other exports)
    tit_cols = [c for c in ("titulaire_id_1", "titulaire_id_2", "titulaire_id_3") if c in decp]
    keep = ["acheteur_id", "acheteur_nom", "buyer_siren", "id", "objet", "cpv_div", "cpv_grp", "cpv_cls", "categorie", "dept",
            "amount_band", "montant", "date", "year", "offres", "titulaire_nom"]
    keep = [c for c in keep if c in decp]
    awards = decp[keep + tit_cols].melt(id_vars=keep, value_vars=tit_cols, value_name="titulaire_id")
    awards["company_siren"] = awards["titulaire_id"].map(siren_of)
    awards = awards.dropna(subset=["company_siren"]).drop(columns=["variable"])
    awards = awards.drop_duplicates(subset=["acheteur_id", "id", "company_siren"])

    # Contracts: one row per (buyer, id)
    contracts = decp.drop_duplicates(subset=["acheteur_id", "id"])
    print(f"contracts after de-duplication on (acheteur_id, id): {len(contracts):,}")

    approch = build_approch_features(approch_raw, edges)

    contracts.to_parquet(CLEAN / "contracts.parquet", index=False)
    awards.to_parquet(CLEAN / "awards.parquet", index=False)
    approch.to_parquet(CLEAN / "approch.parquet", index=False)
    print(f"saved clean tables: {len(contracts):,} contracts, {len(awards):,} awards, {len(approch):,} upcoming purchases")


if __name__ == "__main__":
    main()
