"""Slim copy of the awards table for the hosted app (Streamlit Community Cloud: about 1 GB of RAM, files < 100 MB).

    python src/build_app_data.py     # rerun after prepare.py: the app prefers these files when they exist

Writes data/clean/awards_app.parquet (only the columns the app shows, sorted by company so that one company's
rows are read without loading the 2 million others) and data/clean/company_counts.parquet (contracts per company,
for the name search). Row order inside a company is unchanged, so the app shows exactly the same results.
"""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from common import CLEAN

COLS = ["company_siren", "titulaire_nom", "cpv_div", "cpv_grp", "cpv_cls", "dept", "amount_band", "categorie",
        "date", "acheteur_nom", "objet", "montant", "offres"]


def main() -> None:
    a = pd.read_parquet(CLEAN / "awards.parquet")
    n = a["company_siren"].value_counts()  # same order as the app computed it (ties included)
    pd.DataFrame({"siren": n.index.astype(str), "n": n.to_numpy()}).to_parquet(CLEAN / "company_counts.parquet", index=False)
    s = a[[c for c in COLS if c in a]].sort_values("company_siren", kind="stable").reset_index(drop=True)
    out = CLEAN / "awards_app.parquet"
    pq.write_table(pa.Table.from_pandas(s, preserve_index=False), out, compression="zstd", compression_level=19,
                   row_group_size=20_000)
    print(f"{out.name}: {len(s):,} rows, {out.stat().st_size / 1e6:.0f} MB · company_counts: {len(n):,} companies")


if __name__ == "__main__":
    main()
