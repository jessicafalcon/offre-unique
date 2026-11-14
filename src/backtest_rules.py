"""Calibrate the score and backtest the go / no-go rules, without touching the production model.

    python src/backtest_rules.py            # both variants
    python src/backtest_rules.py --grid     # also print the threshold grid

Honest protocol:
- the evaluation model is refit on 2023–2024 only (artifacts/model*.txt is fit on all years, so it has seen the test years);
- the calibration (isotonic) and the thresholds are fit on 2025;
- the rules are reported on 2026, which neither has seen.
Writes artifacts/calibration{_boamp}.json (used by the app) and artifacts/rules_backtest.json.
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score

from common import ART, CAT_FEATURES, CLEAN, EXCLUDED_PROCEDURES, MIN_YEAR, SPLIT_YEAR, TODAY
from train import VARIANTS, encode, fit_model, to_model_frame

# Rule thresholds on the calibrated ratio (probability / average). Chosen on 2025 with --grid.
PASS_BELOW = 1.0   # below the average: more competitors than usual
GO_FROM = 1.5      # clearly above: go, if the buyer's own record agrees
BUYER_OK = 0.30


def buyer_history(train: pd.DataFrame, test: pd.DataFrame) -> pd.Series:
    """Single-bid share of the buyer's past contracts in the same CPV group (fallback: division), train years only.
    Mirrors hist_single_share in score.py."""
    grp = train.groupby(["buyer_siren", "cpv_grp"])["single_bid"].mean()
    div = train.groupby(["buyer_siren", "cpv_div"])["single_bid"].mean()
    k_grp = pd.MultiIndex.from_frame(test[["buyer_siren", "cpv_grp"]])
    k_div = pd.MultiIndex.from_frame(test[["buyer_siren", "cpv_div"]])
    h = pd.Series(grp.reindex(k_grp).to_numpy(), index=test.index)
    return h.fillna(pd.Series(div.reindex(k_div).to_numpy(), index=test.index))


def rule(ratio: np.ndarray, hist: pd.Series, pass_below: float, go_from: float) -> np.ndarray:
    buyer_ok = hist.isna().to_numpy() | (hist.to_numpy() >= BUYER_OK)
    out = np.where(ratio < pass_below, "Passer", "À étudier")
    return np.where((ratio >= go_from) & buyer_ok, "Aller", out)


def groups(y: np.ndarray, reco: np.ndarray) -> dict:
    return {k: {"n": int((reco == k).sum()), "single_rate": float(y[reco == k].mean()) if (reco == k).any() else None}
            for k in ("Aller", "À étudier", "Passer")}


def run(variant: str, lab: pd.DataFrame, categories: dict, grid: bool) -> dict:
    feats, suffix = VARIANTS[variant]
    train, test = lab[lab["year"] < SPLIT_YEAR], lab[lab["year"] >= SPLIT_YEAR]
    train_e, (test_e,), _ = encode(train, [test])
    model = fit_model(to_model_frame(train_e, categories, feats), train_e["single_bid"])
    p = model.predict_proba(to_model_frame(test_e, categories, feats))[:, 1]
    y = test_e["single_bid"].to_numpy()
    auc = roc_auc_score(y, p)
    ref = json.loads((ART / f"metrics{suffix}.json").read_text())
    print(f"[{variant}] AUC {auc:.4f} (metrics{suffix}.json: {ref['results']['model']['auc']:.4f})")
    if abs(auc - ref["results"]["model"]["auc"]) > 0.005:
        raise SystemExit("AUC does not match metrics.json: stopping.")

    cal_mask = (test_e["year"] == SPLIT_YEAR).to_numpy()   # 2025: fit calibration + thresholds
    rep_mask = ~cal_mask                                    # 2026: report
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(p[cal_mask], y[cal_mask])
    pc = iso.predict(p)
    avg = float(ref["test_single_bid_rate"])
    hist = buyer_history(train, test_e)
    ratio = pc / avg

    # calibration check on the report year, by decile
    d = pd.DataFrame({"raw": p[rep_mask], "cal": pc[rep_mask], "y": y[rep_mask]})
    d["dec"] = pd.qcut(d["raw"], 10, labels=False, duplicates="drop")
    calib_check = d.groupby("dec").agg(raw=("raw", "mean"), cal=("cal", "mean"), obs=("y", "mean")).round(3)
    print(calib_check.to_string())

    if grid:
        print("threshold grid on 2025 (Aller / À étudier / Passer single-bid rates, n):")
        for pb in (0.9, 1.0, 1.1, 1.2):
            for gf in (1.3, 1.5, 1.8, 2.0):
                g = groups(y[cal_mask], rule(ratio[cal_mask], hist[cal_mask], pb, gf))
                print(f"  pass<{pb} go>={gf}: " + " | ".join(
                    f"{k} {100 * v['single_rate']:.0f}% ({v['n']:,})" for k, v in g.items() if v["single_rate"] is not None))

    rep = groups(y[rep_mask], rule(ratio[rep_mask], hist[rep_mask], PASS_BELOW, GO_FROM))
    (ART / f"calibration{suffix}.json").write_text(json.dumps({
        "method": "isotonique, ajustée sur les marchés 2025 (modèle entraîné sur 2023–2024)",
        "x": [float(v) for v in iso.X_thresholds_], "y": [float(v) for v in iso.y_thresholds_],
    }))
    return {"auc_check": round(auc, 4), "report_rate": float(y[rep_mask].mean()), "n_report": int(rep_mask.sum()),
            "groups": rep, "calibration_2026": calib_check.reset_index(drop=True).to_dict(orient="list")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--variant", choices=list(VARIANTS))
    a = ap.parse_args()
    c = pd.read_parquet(CLEAN / "contracts.parquet")
    lab = c[c["valid_label"] & ~c["procedure_c"].isin(EXCLUDED_PROCEDURES)
            & c["year"].between(MIN_YEAR, TODAY.year)].copy()
    lab["single_bid"] = lab["single_bid"].astype(int)
    lab["buyer_siren"] = lab["buyer_siren"].fillna("NA")
    for col in CAT_FEATURES:
        lab[col] = lab[col].astype(str)
    categories = {col: sorted(lab[col].unique().tolist()) for col in CAT_FEATURES}

    out = {"years": "2026", "fit_years": "2025",
           "note": "sans la condition de département ; calibration et seuils choisis sur 2025",
           "thresholds": {"passer_sous": PASS_BELOW, "aller_des": GO_FROM, "acheteur_min": BUYER_OK}}
    for v in ([a.variant] if a.variant else list(VARIANTS)):
        out[v] = run(v, lab, categories, a.grid)
    p = ART / "rules_backtest.json"
    if p.exists() and a.variant:  # keep the other variant's results
        out = {**json.loads(p.read_text()), **out}
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({k: (v["groups"] if isinstance(v, dict) and "groups" in v else v) for k, v in out.items()},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
