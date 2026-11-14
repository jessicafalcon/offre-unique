"""Step 4: is the data good enough? Prints a report and a GO / FALLBACK verdict.

    python src/check_data.py      -> reports/data_check.md
"""
from __future__ import annotations

import pandas as pd

from common import CLEAN, EXCLUDED_PROCEDURES, MIN_YEAR, REPORTS, SPLIT_YEAR, TODAY


def pct(x: float) -> str:
    return f"{100 * x:.1f} %"


def main():
    c = pd.read_parquet(CLEAN / "contracts.parquet")
    w = pd.read_parquet(CLEAN / "awards.parquet")
    a = pd.read_parquet(CLEAN / "approch.parquet")
    L = []
    say = lambda s="": (print(s), L.append(s))

    say("# Data check")
    say(f"\n## Past contracts (DECP)\n")
    say(f"- contracts: {len(c):,}")
    junk = ~c["year"].between(2015, TODAY.year + 1)
    say(f"- contracts with an implausible year (before 2015 or in the future): {int(junk.sum()):,} (ignored below)")
    c = c[~junk]
    say(f"- `offresrecues` usable (1–200): {pct(c['valid_label'].mean())}")
    lab = c[c["valid_label"]]
    say(f"- single-bid rate among usable rows: {pct(lab['single_bid'].mean())}")
    say(f"- `offresrecues` = 0 or missing: {pct((~c['valid_label']).mean())}")

    say("\n### Contracts and single-bid rate by year\n")
    by_year = lab.groupby("year").agg(n=("single_bid", "size"), single=("single_bid", "mean"))
    for y, r in by_year.iterrows():
        say(f"- {y:.0f}: {r.n:,} contracts, {pct(r.single)} single bid")

    say("\n### By procedure (canonical)\n")
    by_proc = lab.groupby("procedure_c").agg(n=("single_bid", "size"), single=("single_bid", "mean")).sort_values("n", ascending=False)
    for p, r in by_proc.iterrows():
        flag = "  ← excluded from training" if p == "sans_pub" else ""
        say(f"- {p}: {r.n:,} contracts, {pct(r.single)} single bid{flag}")
    raw_proc = c["procedure"].astype(str).value_counts().head(12)
    say("\nRaw procedure labels (check they map correctly in `procedure_canon`):")
    for p, n in raw_proc.items():
        say(f"- `{p}`: {n:,}")

    say("\n### Feature fill rates\n")
    for col in ["cpv_div", "amount_band", "duration_bin", "dept", "buyer_siren"]:
        filled = (c[col].astype(str) != "NA") & c[col].notna()
        say(f"- {col}: {pct(filled.mean())}")
    say(f"- awards with a company SIREN: {len(w):,} rows, {w['company_siren'].nunique():,} companies")

    say("\n## Upcoming purchases (APProch)\n")
    say(f"- rows: {len(a):,}")
    if "due_date" in a:
        future = (a["due_date"] >= TODAY) | (a["pub_date"] >= TODAY)
        say(f"- with a publication or deadline date from today on: {future.sum():,}")
    for col in ["cpv_div", "amount_band", "duration_bin", "dept", "buyer_siren", "procedure_c"]:
        filled = (a[col].astype(str) != "NA") & a[col].notna()
        say(f"- {col}: {pct(filled.mean())}")
    hist_buyers = set(lab["buyer_siren"].dropna())
    overlap = a["buyer_siren"].isin(hist_buyers).mean()
    say(f"- upcoming purchases whose buyer has past contracts: {pct(overlap)}")
    say("\nAPProch raw procedure labels:")
    if "type_de_procedure" in a:
        for p, n in a["type_de_procedure"].astype(str).value_counts().head(10).items():
            say(f"- `{p}`: {n:,}")
    if "duree_previsionnelle_du_marche" in a:
        say("\nAPProch duration examples (check `duration_months` parses them): "
            + ", ".join(f"`{v}`" for v in a["duree_previsionnelle_du_marche"].dropna().astype(str).unique()[:8]))
    if "montant_estime_du_marche" in a:
        say("APProch amount bands: " + ", ".join(f"`{v}`" for v in a["montant_estime_du_marche"].dropna().astype(str).unique()[:12]))

    usable = c["valid_label"].mean()
    model_rows = lab[~lab["procedure_c"].isin(EXCLUDED_PROCEDURES)]
    train_n = int(model_rows["year"].between(MIN_YEAR, SPLIT_YEAR - 1).sum())
    test_n = int((model_rows["year"] >= SPLIT_YEAR).sum())
    verdict_ok = train_n >= 20_000 and test_n >= 5_000 and overlap >= 0.3
    say("\n## Verdict\n")
    say(f"Training window: {MIN_YEAR}–{SPLIT_YEAR - 1} ({train_n:,} labelled contracts), "
        f"test: {SPLIT_YEAR} onwards ({test_n:,}). Share of contracts with a usable bid count: {pct(usable)}.")
    if verdict_ok:
        say(f"GO. Buyer overlap {pct(overlap)}. Mention in the limits that only contracts with a reported "
            f"number of bids ({pct(usable)}) are used.")
    else:
        say(f"FALLBACK to the descriptive version (rates by buyer and category as the score): need ≥ 20,000 "
            f"training and ≥ 5,000 test contracts and ≥ 30 % buyer overlap (now {pct(overlap)}).")
    (REPORTS / "data_check.md").write_text("\n".join(L), encoding="utf-8")
    print(f"\nreport saved to {REPORTS / 'data_check.md'}")


if __name__ == "__main__":
    main()
