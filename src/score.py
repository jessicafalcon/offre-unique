"""Step 8: score every upcoming purchase and attach the buyer's history in that category.

    python src/score.py        -> data/clean/scored.parquet (the app only reads this + profiles)
"""
from __future__ import annotations

import json
import pickle

import lightgbm as lgb
import numpy as np
import pandas as pd

from common import ART, CAT_FEATURES, CLEAN, FEATURES
from profiles import upcoming
from train import te_apply, to_model_frame

FEATURE_LABELS = {
    "buyer_rate": "historique de l'acheteur",
    "buyer_cpv_rate": "historique de l'acheteur dans cette catégorie",
    "cpv_rate": "catégorie d'achat",
    "buyer_n": "nombre de marchés passés par l'acheteur",
    "procedure_c": "procédure",
    "amount_band": "montant",
    "duration_bin": "durée",
    "dept": "département",
    "cpv_div": "division CPV",
    "categorie": "type d'achat",
    "clause_sociale": "clause sociale",
    "clause_env": "clause environnementale",
}


def add_encodings(df: pd.DataFrame, enc: dict) -> pd.DataFrame:
    df = df.copy()
    df["buyer_siren"] = df["buyer_siren"].fillna("NA")
    for feat, keys in enc["keys"].items():
        rate, n = te_apply(df, enc["tables"][feat], keys, enc["prior"])
        df[feat] = rate
        if feat == "buyer_rate":
            df["buyer_n"] = n
    return df


def top_factors(contrib: np.ndarray, X: pd.DataFrame, k: int = 3) -> list[str]:
    feats = list(X.columns)
    out = []
    for i in range(len(X)):
        row = contrib[i, :-1]  # last column is the bias
        order = np.argsort(-np.abs(row))[:k]
        facts = []
        for j in order:
            f = feats[j]
            v = X.iloc[i][f]
            if isinstance(v, float) and f.endswith("rate"):
                v = f"{v:.0%}"
            elif f == "buyer_n":
                v = int(v)
            facts.append({"feature": f, "label": FEATURE_LABELS.get(f, f), "value": str(v),
                          "direction": "hausse" if row[j] > 0 else "baisse", "log_odds": round(float(row[j]), 3)})
        out.append(json.dumps(facts, ensure_ascii=False))
    return out


def history(purchases: pd.DataFrame, contracts: pd.DataFrame, awards: pd.DataFrame) -> pd.DataFrame:
    """Past contracts from the same buyer in the same CPV group (fallback: CPV division)."""
    plausible = contracts["year"].between(2015, pd.Timestamp.today().year + 1)  # drop junk dates (year 1, 201…)
    c = contracts[plausible & contracts["buyer_siren"].isin(set(purchases["buyer_siren"].dropna()))].copy()
    win = awards.drop_duplicates(subset=["acheteur_id", "id"])[["acheteur_id", "id", "company_siren"]
                                                                 + (["titulaire_nom"] if "titulaire_nom" in awards else [])]
    c = c.merge(win, on=["acheteur_id", "id"], how="left", suffixes=("", "_w"))
    c = c.sort_values("date", ascending=False)
    by_grp = {k: g for k, g in c.groupby(["buyer_siren", "cpv_grp"])}
    by_div = {k: g for k, g in c.groupby(["buyer_siren", "cpv_div"])}

    rows = []
    for b, grp, div in zip(purchases["buyer_siren"], purchases["cpv_grp"].astype(str), purchases["cpv_div"].astype(str)):
        h = by_grp.get((b, grp))
        level = "groupe CPV"
        if h is None or len(h) == 0:
            h, level = by_div.get((b, div)), "division CPV"
        if h is None or len(h) == 0:
            rows.append({"hist_n": 0, "hist_n_lab": 0, "hist_level": None, "hist_mean_offers": np.nan, "hist_single_share": np.nan,
                         "incumbent_siren": None, "incumbent_name": None, "incumbent_wins": 0, "incumbent_streak": 0,
                         "hist_editions": "[]"})
            continue
        lab = h[h["valid_label"]]
        winners = h["company_siren"].dropna()
        inc = winners.mode().iloc[0] if len(winners) else None
        streak = 0
        for s in h["company_siren"]:
            if s == inc:
                streak += 1
            else:
                break
        inc_name = None
        if inc is not None and "titulaire_nom" in h:
            names = h.loc[h["company_siren"] == inc, "titulaire_nom"].dropna()
            inc_name = str(names.iloc[0]) if len(names) else None
        eds = []
        for _, r in h.head(5).iterrows():
            eds.append({"date": None if pd.isna(r["date"]) else r["date"].strftime("%Y-%m-%d"),
                        "objet": str(r.get("objet", ""))[:140],
                        "offres": None if pd.isna(r["offres"]) else int(r["offres"]),
                        "titulaire_siren": r.get("company_siren"),
                        "titulaire_nom": r.get("titulaire_nom") if "titulaire_nom" in h else None,
                        "montant": None if pd.isna(r.get("montant")) else float(r["montant"])})
        rows.append({
            "hist_n": int(len(h)), "hist_n_lab": int(len(lab)), "hist_level": level,
            "hist_mean_offers": float(lab["offres"].mean()) if len(lab) else np.nan,
            "hist_single_share": float((lab["offres"] == 1).mean()) if len(lab) else np.nan,
            "incumbent_siren": inc, "incumbent_name": inc_name,
            "incumbent_wins": int((winners == inc).sum()) if inc else 0, "incumbent_streak": streak,
            "hist_editions": json.dumps(eds, ensure_ascii=False),
        })
    return pd.DataFrame(rows, index=purchases.index)


SOURCES = {  # source -> (clean file, model suffix, output file)
    "approch": ("approch.parquet", "", "scored.parquet"),
    "boamp": ("boamp.parquet", "_boamp", "scored_boamp.parquet"),
}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=list(SOURCES), default="approch")
    source = ap.parse_args().source
    clean_file, suffix, out_file = SOURCES[source]
    if not (ART / f"model{suffix}.txt").exists():
        raise SystemExit(f"artifacts/model{suffix}.txt missing: run python src/train.py"
                         + (" --variant boamp" if suffix else ""))
    with open(ART / f"encoders{suffix}.pkl", "rb") as f:
        saved = pickle.load(f)
    enc, categories = saved["enc"], saved["categories"]
    feats = saved.get("features", FEATURES)
    booster = lgb.Booster(model_file=str(ART / f"model{suffix}.txt"))

    purchases = upcoming(pd.read_parquet(CLEAN / clean_file))
    purchases = add_encodings(purchases, enc)
    for col in CAT_FEATURES:
        if col in purchases:
            purchases[col] = purchases[col].astype(str)
    X = to_model_frame(purchases, categories, feats)
    purchases["proba"] = booster.predict(X)
    purchases["factors"] = top_factors(booster.predict(X, pred_contrib=True), X)

    contracts = pd.read_parquet(CLEAN / "contracts.parquet")
    awards = pd.read_parquet(CLEAN / "awards.parquet")
    purchases = purchases.join(history(purchases, contracts, awards))
    if "buyer_name" not in purchases:
        purchases["buyer_name"] = None
    if "acheteur_nom" in contracts:  # fill missing buyer names from past contracts (BOAMP already has them)
        names = contracts.dropna(subset=["acheteur_nom"]).groupby("buyer_siren")["acheteur_nom"].agg(lambda s: s.mode().iloc[0])
        purchases["buyer_name"] = purchases["buyer_name"].fillna(purchases["buyer_siren"].map(names))
    purchases["source"] = "BOAMP" if source == "boamp" else "APProch"

    purchases.to_parquet(CLEAN / out_file, index=False)
    print(f"[{source}] scored {len(purchases):,} upcoming purchases; mean predicted single-bid risk {purchases['proba'].mean():.1%}")
    cols = [c for c in ["libelle", "buyer_name", "cpv_div", "dept", "proba", "hist_n"] if c in purchases]
    print(purchases.sort_values("proba", ascending=False)[cols].head(10)
          .assign(libelle=lambda d: d["libelle"].astype(str).str.slice(0, 60)).to_string(index=False))


if __name__ == "__main__":
    main()
