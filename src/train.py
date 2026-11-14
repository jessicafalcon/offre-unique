"""Step 6: train the single-bid model with an honest time split, compare to baselines,
then refit on all labelled data for scoring upcoming purchases.

    python src/train.py
Writes artifacts/metrics.json (the Preuves tab), artifacts/model.txt, artifacts/encoders.pkl
"""
from __future__ import annotations

import json
import pickle

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import KFold

from common import ART, CAT_FEATURES, CLEAN, EXCLUDED_PROCEDURES, FEATURES, MIN_YEAR, SPLIT_YEAR, TODAY

ALPHA = 20  # smoothing strength for target encoding (pseudo-contracts at the global rate)

ENCODINGS = {  # feature -> grouping keys
    "buyer_rate": ["buyer_siren"],
    "buyer_cpv_rate": ["buyer_siren", "cpv_div"],
    "cpv_rate": ["cpv_grp"],
}


# ---------------------------------------------------------------------------
# Target encoding (smoothed rates), out-of-fold for the rows used to fit
# ---------------------------------------------------------------------------

def te_table(ref: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    return ref.groupby(keys, dropna=False)["single_bid"].agg(n="size", s="sum").reset_index()


def te_apply(df: pd.DataFrame, table: pd.DataFrame, keys: list[str], prior: float) -> tuple[pd.Series, pd.Series]:
    m = df[keys].merge(table, on=keys, how="left")
    n = m["n"].fillna(0).to_numpy()
    s = m["s"].fillna(0).to_numpy()
    rate = (s + ALPHA * prior) / (n + ALPHA)
    return pd.Series(rate, index=df.index), pd.Series(n, index=df.index)


def encode(fit_rows: pd.DataFrame, other: list[pd.DataFrame], k: int = 5, seed: int = 0):
    """Out-of-fold encodings for fit_rows; full-reference encodings for each frame in `other`."""
    fit_rows = fit_rows.copy()
    prior = float(fit_rows["single_bid"].mean())
    for feat in list(ENCODINGS) + ["buyer_n"]:
        fit_rows[feat] = np.nan
    kf = KFold(n_splits=k, shuffle=True, random_state=seed)
    for tr, va in kf.split(fit_rows):
        ref, tgt = fit_rows.iloc[tr], fit_rows.iloc[va]
        p = float(ref["single_bid"].mean())
        for feat, keys in ENCODINGS.items():
            rate, n = te_apply(tgt, te_table(ref, keys), keys, p)
            fit_rows.loc[tgt.index, feat] = rate.to_numpy()
            if feat == "buyer_rate":
                fit_rows.loc[tgt.index, "buyer_n"] = n.to_numpy()
    tables = {feat: te_table(fit_rows, keys) for feat, keys in ENCODINGS.items()}
    out = []
    for df in other:
        df = df.copy()
        for feat, keys in ENCODINGS.items():
            rate, n = te_apply(df, tables[feat], keys, prior)
            df[feat] = rate
            if feat == "buyer_rate":
                df["buyer_n"] = n
        out.append(df)
    return fit_rows, out, {"tables": tables, "prior": prior, "keys": ENCODINGS, "alpha": ALPHA}


# ---------------------------------------------------------------------------

# Features the BOAMP notices do not carry (amount, duration, clauses): the BOAMP variant is trained without them
BOAMP_DROP = ["amount_band", "duration_bin", "clause_sociale", "clause_env"]
VARIANTS = {"main": (FEATURES, ""), "boamp": ([f for f in FEATURES if f not in BOAMP_DROP], "_boamp")}


def to_model_frame(df: pd.DataFrame, categories: dict[str, list[str]], features: list[str] = FEATURES) -> pd.DataFrame:
    X = df[features].copy()
    for c in features:
        if c in CAT_FEATURES:
            X[c] = pd.Categorical(X[c].astype(str), categories=categories[c])
        else:
            X[c] = pd.to_numeric(X[c], errors="coerce").astype(float)
    return X


def fit_model(X: pd.DataFrame, y: pd.Series) -> lgb.LGBMClassifier:
    m = lgb.LGBMClassifier(
        n_estimators=400, learning_rate=0.05, num_leaves=63, min_child_samples=50,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
        cat_smooth=20, verbose=-1,
    )
    m.fit(X, y)
    return m


def precision_at(y: np.ndarray, p: np.ndarray, frac: float = 0.1) -> float:
    k = max(1, int(len(p) * frac))
    idx = np.argsort(-p)[:k]
    return float(y[idx].mean())


def scores(y: np.ndarray, p: np.ndarray) -> dict:
    return {
        "auc": float(roc_auc_score(y, p)),
        "avg_precision": float(average_precision_score(y, p)),
        "precision_top10": precision_at(y, p, 0.1),
        "brier": float(brier_score_loss(y, p)),
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=list(VARIANTS), default="main")
    variant = ap.parse_args().variant
    feats, suffix = VARIANTS[variant]
    print(f"variant: {variant} · features: {feats}")
    c = pd.read_parquet(CLEAN / "contracts.parquet")
    lab = c[c["valid_label"] & ~c["procedure_c"].isin(EXCLUDED_PROCEDURES)
            & c["year"].between(MIN_YEAR, TODAY.year)].copy()
    lab["single_bid"] = lab["single_bid"].astype(int)
    lab["buyer_siren"] = lab["buyer_siren"].fillna("NA")
    for col in CAT_FEATURES:
        lab[col] = lab[col].astype(str)
    print(f"labelled contracts used: {len(lab):,} (single-bid rate {lab['single_bid'].mean():.1%})")

    categories = {col: sorted(lab[col].unique().tolist()) for col in CAT_FEATURES}

    # ---- 1. Honest evaluation: train < SPLIT_YEAR, test >= SPLIT_YEAR
    train = lab[lab["year"] < SPLIT_YEAR]
    test = lab[lab["year"] >= SPLIT_YEAR]
    if len(test) < 500 or len(train) < 2000:
        raise SystemExit(f"Not enough data for a time split (train {len(train):,}, test {len(test):,}). "
                         f"Change SPLIT_YEAR in .env.")
    train_e, (test_e,), _ = encode(train, [test])
    model = fit_model(to_model_frame(train_e, categories, feats), train_e["single_bid"])
    y = test_e["single_bid"].to_numpy()
    p_model = model.predict_proba(to_model_frame(test_e, categories, feats))[:, 1]

    results = {
        "model": scores(y, p_model),
        "baseline_buyer_history": scores(y, test_e["buyer_rate"].to_numpy()),
        "baseline_cpv_category": scores(y, test_e["cpv_rate"].to_numpy()),
    }
    base_rate = float(y.mean())

    # calibration by decile (predicted vs observed)
    dec = pd.qcut(p_model, 10, labels=False, duplicates="drop")
    calib = pd.DataFrame({"p": p_model, "y": y, "d": dec}).groupby("d").agg(pred=("p", "mean"), obs=("y", "mean"))

    imp = pd.Series(model.booster_.feature_importance("gain"), index=feats).sort_values(ascending=False)

    metrics = {
        "variant": variant, "features": feats,
        "split_year": SPLIT_YEAR,
        "n_train": int(len(train)), "n_test": int(len(test)),
        "train_years": [int(train["year"].min()), int(train["year"].max())],
        "test_years": [int(test["year"].min()), int(test["year"].max())],
        "test_single_bid_rate": base_rate,
        "results": results,
        "calibration": calib.round(4).reset_index(drop=True).to_dict(orient="list"),
        "importance_gain": (imp / imp.sum()).round(4).to_dict(),
    }
    print(json.dumps({k: v for k, v in metrics.items() if k in ("n_train", "n_test", "results")}, indent=2))

    # ---- 2. Final model on all labelled data, for scoring upcoming purchases
    all_e, _, enc = encode(lab, [])
    final = fit_model(to_model_frame(all_e, categories, feats), all_e["single_bid"])
    final.booster_.save_model(str(ART / f"model{suffix}.txt"))
    with open(ART / f"encoders{suffix}.pkl", "wb") as f:
        pickle.dump({"enc": enc, "categories": categories, "features": feats}, f)
    (ART / f"metrics{suffix}.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"saved model, encoders and metrics to {ART}")


if __name__ == "__main__":
    main()
