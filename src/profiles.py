"""Step 7: company profiles from past wins, fit scoring, and demo-company candidates.

    python src/profiles.py         -> data/clean/profiles.parquet, reports/demo_candidates.csv

A profile is what a company has won before: CPV divisions, départements and amount bands.
The app recomputes the fit for whichever SIREN is typed in, using the same functions.
"""
from __future__ import annotations

import pandas as pd

from common import CLEAN, EXCLUDED_PROCEDURES, REPORTS, TODAY, cpv_label


def profile_of(awards: pd.DataFrame, siren: str) -> dict | None:
    w = awards[awards["company_siren"] == siren]
    if w.empty:
        return None
    share = lambda col: (w[col].astype(str).value_counts(normalize=True)).to_dict()
    name = None
    if "titulaire_nom" in w and w["titulaire_nom"].notna().any():
        name = w["titulaire_nom"].dropna().astype(str).mode().iloc[0]
    return {
        "siren": siren,
        "name": name,
        "n_wins": int(len(w)),
        "cpv_div": share("cpv_div"),
        "cpv_grp": share("cpv_grp"),
        "dept": share("dept"),
        "amount_band": share("amount_band"),
        "categorie": share("categorie"),
        "last_win": w["date"].max(),
    }


def fit_table(profile: dict, purchases: pd.DataFrame, awards: pd.DataFrame) -> pd.DataFrame:
    """Fit of each upcoming purchase for one company: shares plus counts of similar past wins."""
    w = awards[awards["company_siren"] == profile["siren"]]
    p = purchases.copy()
    p["fit_cpv"] = p["cpv_div"].astype(str).map(profile["cpv_div"]).fillna(0.0)
    p["fit_dept"] = p["dept"].astype(str).map(profile["dept"]).fillna(0.0)
    p["fit_amount"] = p["amount_band"].astype(str).map(profile["amount_band"]).fillna(0.0)
    p["fit"] = 0.6 * p["fit_cpv"] + 0.3 * p["fit_dept"] + 0.1 * p["fit_amount"]
    for col, suffix in (("cpv_div", ""), ("cpv_cls", "_cls")):
        if col not in w or col not in p:  # older clean files without cpv_cls: fall back to the division
            col = "cpv_div"
        n = w[col].astype(str).value_counts()
        n_dept = w.groupby([w[col].astype(str), w["dept"].astype(str)]).size()
        p[f"n_similar{suffix}"] = p[col].astype(str).map(n).fillna(0).astype(int)
        p[f"n_similar{suffix}_dept"] = [int(n_dept.get((c, d), 0)) for c, d in zip(p[col].astype(str), p["dept"].astype(str))]
    if "cpv_cls" in p:  # class "NA" is not a real match
        p.loc[p["cpv_cls"].astype(str) == "NA", ["n_similar_cls", "n_similar_cls_dept"]] = 0
    return p


# Tightest match first: same 4-digit CPV class in a département where the company has won, then looser.
MATCH_LEVELS = [
    ("n_similar_cls_dept", "n_similar_cls", "même métier, même département"),
    ("n_similar_cls", "n_similar_cls", "même métier, toute la France"),
    ("n_similar_dept", "n_similar", "même secteur, même département"),
    ("n_similar", "n_similar", "même secteur, toute la France"),
]


_TITLE_COLS = ("objet", "titre", "title", "intitule", "libelle", "object")
_BUYER_COLS = ("acheteur_siret", "acheteur_id", "buyer_id", "acheteur_siren", "acheteur_nom", "acheteur", "buyer_name", "buyer")


def _norm_title(s) -> str:
    import re, unicodedata
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"^(?=[\w./-]*\d)[\w./-]+\s+-\s+", "", s)  # leading reference, e.g. "26.AO.VD.061 - "
    s = re.sub(r"\bet\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def dedupe_tenders(t: pd.DataFrame) -> pd.DataFrame:
    # Same tender published twice (same buyer, same object once normalised): keep the highest score.
    title = next((c for c in _TITLE_COLS if c in t.columns), None)
    if title is None or t.empty:
        return t
    buyer = next((c for c in _BUYER_COLS if c in t.columns), None)
    key = t[title].map(_norm_title)
    if "buyer_siren" in t.columns:
        sid = t["buyer_siren"].astype(str).str.strip()
        fallback = t[buyer].astype(str) if buyer else ""
        key = sid.where(~sid.isin(["", "nan", "None", "<NA>"]), fallback) + "|" + key
    elif buyer:
        key = t[buyer].astype(str) + "|" + key
    order = t["proba"].sort_values(ascending=False).index if "proba" in t.columns else t.index
    first = ~key.loc[order].duplicated()
    return t.loc[first[first].index].sort_index()


def relevant(t: pd.DataFrame, min_rows: int = 5, min_wins: int = 2) -> pd.DataFrame:
    """Upcoming tenders that fit the company's trade, at the tightest level with at least `min_rows` tenders.

    Adds n_match (similar past wins), n_match_dept (same, in that département) and match_level.
    """
    for filt, count, label in MATCH_LEVELS:
        sel = t[(t[filt] > 0) & (t[count] >= min_wins)]
        if len(sel) >= min_rows or filt == "n_similar":
            if sel.empty and min_wins > 1:
                return relevant(t, min_rows, 1)
            sel = sel.copy()
            sel["n_match"] = sel[count]
            sel["n_match_dept"] = sel["n_similar_cls_dept"] if count == "n_similar_cls" else sel["n_similar_dept"]
            sel["match_level"] = label
            return dedupe_tenders(sel)
    return t.iloc[0:0]


def describe_profile(profile: dict, top: int = 2) -> str:
    """'Maintenance (CPV 50) · départements 93, 94' — plain sentence for the header."""
    cpvs = [k for k in list(profile["cpv_div"])[:top] if k != "NA"]
    depts = [k for k in list(profile["dept"])[:3] if k != "NA"]
    parts = []
    if cpvs:
        parts.append(", ".join(cpv_label(c) for c in cpvs))
    if depts:
        parts.append("départements " + ", ".join(depts))
    return " · ".join(parts) + f" · {profile['n_wins']} marchés gagnés"


def load_all_scored() -> pd.DataFrame:
    """Scored upcoming purchases from APProch (projects) and, if present, BOAMP (open calls for tender)."""
    parts = []
    for name, src in (("scored.parquet", "APProch"), ("scored_boamp.parquet", "BOAMP")):
        p = CLEAN / name
        if p.exists():
            d = pd.read_parquet(p)
            if "source" not in d:
                d["source"] = src
            parts.append(d)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def upcoming(purchases: pd.DataFrame) -> pd.DataFrame:
    has_date = purchases["due_date"].notna() | purchases["pub_date"].notna()
    future = (purchases["due_date"] >= TODAY) | (purchases["pub_date"] >= TODAY)
    single_by_design = purchases["procedure_c"].isin(EXCLUDED_PROCEDURES) if "procedure_c" in purchases else False
    return purchases[(future | ~has_date) & ~single_by_design]


def main():
    awards = pd.read_parquet(CLEAN / "awards.parquet")
    purchases = upcoming(pd.read_parquet(CLEAN / "approch.parquet"))

    g = awards.groupby("company_siren")
    prof = pd.DataFrame({
        "n_wins": g.size(),
        "top_cpv": g["cpv_div"].agg(lambda s: s.astype(str).mode().iloc[0]),
        "top_cpv_share": g["cpv_div"].agg(lambda s: s.astype(str).value_counts(normalize=True).iloc[0]),
        "top_dept": g["dept"].agg(lambda s: s.astype(str).mode().iloc[0]),
        "top_dept_share": g["dept"].agg(lambda s: s.astype(str).value_counts(normalize=True).iloc[0]),
        "last_win": g["date"].max(),
    }).reset_index()
    if "titulaire_nom" in awards:
        names = awards.dropna(subset=["titulaire_nom"]).groupby("company_siren")["titulaire_nom"].agg(lambda s: s.astype(str).mode().iloc[0])
        prof = prof.merge(names.rename("name"), on="company_siren", how="left")
    prof.to_parquet(CLEAN / "profiles.parquet", index=False)

    # Demo candidates: SME-sized track record, focused, with matching upcoming purchases
    cand = prof[(prof["n_wins"].between(10, 150)) & (prof["top_cpv_share"] >= 0.5) & (prof["top_dept_share"] >= 0.4)
                & (prof["top_cpv"] != "NA") & (prof["top_dept"] != "NA")].copy()
    counts = purchases.groupby([purchases["cpv_div"].astype(str), purchases["dept"].astype(str)]).size()
    cand["matching_upcoming"] = [int(counts.get((c, d), 0)) for c, d in zip(cand["top_cpv"], cand["top_dept"])]
    cand = cand[cand["matching_upcoming"] >= 5].sort_values(["matching_upcoming", "n_wins"], ascending=False)
    cand.head(30).to_csv(REPORTS / "demo_candidates.csv", index=False)
    print(f"{len(prof):,} company profiles; {len(cand):,} demo candidates")
    print(cand.head(10).to_string(index=False))
    print(f"\nPick one and set DEMO_SIREN=<siren> in .env (top 30 in {REPORTS / 'demo_candidates.csv'})")


if __name__ == "__main__":
    main()
