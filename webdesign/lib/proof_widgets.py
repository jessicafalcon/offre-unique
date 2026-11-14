"""Widgets for the "Preuves" and "Comment ça marche" pages. Small files only (JSON + parquet metadata).

    fr_pct / fr_int / fr_num / fr_millions     French number formatting
    row_count(rel_path)                        parquet row count from metadata (no data loaded)
    share_labelled()                           share of DECP contracts with a usable bid count (reports/data_check.md)
    notes_by_model()                           {model id: n verified notes} from artifacts/notes.json
    precision_bars / backtest_bars / calibration_chart / importance_bars / split_bar / funnel / flow
    step_card(...)                             HTML card for one pipeline step
"""
from __future__ import annotations

import os
import re
from collections import Counter

import streamlit as st

from . import charts, data
from . import taxonomy as tx
from .ui import esc

ROOT = data.ROOT


# ------------------------------------------------------------------------------------------ formatting
def fr_int(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def fr_num(x, d: int = 1) -> str:
    x = round(float(x), d)
    return str(int(x)) if x == int(x) else f"{x:.{d}f}".replace(".", ",")


def fr_pct(x, d: int = 0) -> str:
    return f"{fr_num(100 * float(x), d)} %"


def fr_millions(n) -> str:
    return f"{fr_num(n / 1e6, 2)} M"


# ------------------------------------------------------------------------------------------ small facts from files
@st.cache_data
def row_count(rel: str) -> int | None:
    import pyarrow.parquet as pq
    p = ROOT / rel
    return pq.ParquetFile(p).metadata.num_rows if p.exists() else None


@st.cache_data
def share_labelled() -> str:
    """Same default as the main app (env SHARE_LABELLED, else '42 %'); refined from reports/data_check.md if present."""
    if os.environ.get("SHARE_LABELLED"):
        return os.environ["SHARE_LABELLED"]
    p = ROOT / "reports" / "data_check.md"
    try:
        m = re.search(r"`offresrecues` usable \(1–200\): ([\d.]+) %", p.read_text(encoding="utf-8"))
        return f"{round(float(m.group(1)))} %" if m else "42 %"
    except OSError:
        return "42 %"


def notes_by_model() -> Counter:
    return Counter(v.get("model") for v in data.notes().values() if v.get("verified"))


def has_boamp() -> bool:
    n = row_count("data/clean/scored_boamp.parquet")
    return bool(n)


FEATURE_LABELS = {
    "buyer_cpv_rate": "Historique de l'acheteur dans ce secteur",
    "dept": "Département",
    "buyer_rate": "Historique de l'acheteur",
    "cpv_rate": "Taux habituel de la catégorie d'achat",
    "cpv_div": "Secteur (division CPV)",
    "amount_band": "Montant",
    "duration_bin": "Durée du marché",
    "categorie": "Travaux, fournitures ou services",
    "clause_sociale": "Clause sociale",
    "clause_env": "Clause environnementale",
}


# ------------------------------------------------------------------------------------------ charts
def precision_bars(res: dict, avg: float, key: str = "prec"):
    rows = [("Notre score", res["model"]["precision_top10"], tx.TEAL),
            ("Historique de\nl'acheteur seul", res["baseline_buyer_history"]["precision_top10"], "#6366F1"),
            ("Taux de la\ncatégorie", res["baseline_cpv_category"]["precision_top10"], "#94A3B8"),
            ("Moyenne,\nsans score", avg, "#CBD5E1")]
    return charts.render({
        "grid": {"left": 56, "right": 16, "top": 30, "bottom": 52, "containLabel": False},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "xAxis": {"type": "category", "data": [r[0] for r in rows], "axisTick": {"show": False},
                  "axisLabel": {"interval": 0, "color": tx.MUTED, "lineHeight": 16, "margin": 10}},
        "yAxis": {"type": "value", "max": 100, "axisLabel": {"formatter": "{value} %", "color": tx.MUTED},
                  "splitLine": {"lineStyle": {"color": tx.LINE}}},
        "series": [{"type": "bar", "barWidth": "52%",
                    "label": {"show": True, "position": "top", "formatter": "{c} %", "fontWeight": 600, "fontSize": 15},
                    "data": [{"value": round(100 * v), "itemStyle": {"color": c, "borderRadius": [8, 8, 0, 0]}}
                             for _, v, c in rows]}],
    }, 320, key)


def backtest_bars(groups: dict, base_rate: float | None, key: str = "bt"):
    ks = [k for k in ("Aller", "À étudier", "Passer") if k in groups and groups[k].get("single_rate") is not None]
    series = {"type": "bar", "barWidth": "52%",
              "label": {"show": True, "position": "top", "formatter": "{c} %", "fontWeight": 600, "fontSize": 15},
              "data": [{"value": round(100 * groups[k]["single_rate"]), "name": k,
                        "n": groups[k]["n"], "itemStyle": {"color": tx.RECO[k].color, "borderRadius": [8, 8, 0, 0]}}
                       for k in ks]}
    if base_rate:
        series["markLine"] = {"symbol": "none", "silent": True,
                              "label": {"formatter": f"moyenne {round(100 * base_rate)} %", "color": tx.MUTED,
                                        "position": "insideEndTop", "fontSize": 12},
                              "lineStyle": {"type": "dashed", "color": tx.MUTED},
                              "data": [{"yAxis": round(100 * base_rate, 1)}]}
    return charts.render({
        "grid": {"left": 56, "right": 16, "top": 30, "bottom": 36, "containLabel": False},
        "tooltip": {"trigger": "item",
                    "formatter": "{b} : {c} % d'offres uniques<br/>" + " · ".join(
                        f"{k} : {fr_int(groups[k]['n'])} marchés" for k in ks)},
        "xAxis": {"type": "category", "data": [f"{tx.RECO[k].emoji} {k}" for k in ks], "axisTick": {"show": False},
                  "axisLabel": {"fontSize": 14, "fontWeight": 600, "color": tx.INK}},
        "yAxis": {"type": "value", "max": 60, "axisLabel": {"formatter": "{value} %", "color": tx.MUTED},
                  "splitLine": {"lineStyle": {"color": tx.LINE}}},
        "series": [series],
    }, 320, key)


def calibration_chart(cal: dict, key: str = "calib"):
    raw, calp, obs = cal["raw"], cal["cal"], cal["obs"]
    top = max(max(raw), max(obs), max(calp))
    lim = round(min(1.0, top + 0.05), 2)

    def pts(xs):
        return [[round(100 * x, 1), round(100 * y, 1)] for x, y in zip(xs, obs)]

    return charts.render({
        "grid": {"left": 70, "right": 24, "top": 16, "bottom": 82, "containLabel": False},
        "legend": {"bottom": 0, "textStyle": {"color": tx.MUTED}},
        "tooltip": {"trigger": "item"},
        "xAxis": {"type": "value", "min": 0, "max": round(100 * lim), "name": "probabilité affichée",
                  "nameLocation": "middle", "nameGap": 28, "nameTextStyle": {"color": tx.MUTED}, "axisLabel": {"formatter": "{value} %", "color": tx.MUTED},
                  "splitLine": {"lineStyle": {"color": tx.LINE}}},
        "yAxis": {"type": "value", "min": 0, "max": round(100 * lim), "name": "offres uniques observées",
                  "nameLocation": "middle", "nameGap": 50, "nameTextStyle": {"color": tx.MUTED},
                  "axisLabel": {"formatter": "{value} %", "color": tx.MUTED}, "splitLine": {"lineStyle": {"color": tx.LINE}}},
        "series": [
            {"name": "Parfaitement calibré", "type": "line", "symbol": "none", "silent": True,
             "itemStyle": {"color": "#CBD5E1"}, "lineStyle": {"type": "dashed", "color": "#CBD5E1"}, "data": [[0, 0], [round(100 * lim), round(100 * lim)]]},
            {"name": "Score brut (LightGBM)", "type": "line", "smooth": True, "symbolSize": 7,
             "itemStyle": {"color": "#F59E0B"}, "lineStyle": {"color": "#F59E0B", "width": 2}, "data": pts(raw)},
            {"name": "Score calibré (affiché)", "type": "line", "smooth": True, "symbolSize": 9,
             "itemStyle": {"color": tx.TEAL}, "lineStyle": {"color": tx.TEAL, "width": 3}, "data": pts(calp)},
        ],
    }, 360, key)


def importance_bars(imp: dict, key: str = "imp"):
    """Feature importances, largest on top; fixed label column (no clipping) and French decimal commas."""
    items = [(FEATURE_LABELS.get(k, k), 100 * v, tx.TEAL if i < 3 else "#94A3B8")
             for i, (k, v) in enumerate(sorted(imp.items(), key=lambda kv: -kv[1]))][::-1]
    return charts.render({
        "grid": {"left": 250, "right": 64, "top": 6, "bottom": 6, "containLabel": False},
        "tooltip": {"show": False},
        "xAxis": {"type": "value", "show": False},
        "yAxis": {"type": "category", "data": [i[0] for i in items], "axisTick": {"show": False},
                  "axisLine": {"show": False},
                  "axisLabel": {"color": tx.MUTED, "width": 240, "overflow": "break", "lineHeight": 15}},
        "series": [{"type": "bar", "barWidth": 16,
                    "data": [{"value": round(v, 1), "itemStyle": {"color": c, "borderRadius": [0, 6, 6, 0]},
                              "label": {"show": True, "position": "right", "color": tx.INK,
                                        "formatter": f"{fr_num(v)} %"}} for _, v, c in items]}],
    }, 34 * len(items) + 20, key)


def split_bar(n_train: int, n_fit: int, n_report: int, years: tuple[str, str, str], key: str = "split"):
    segs = [(f"Apprentissage {years[0]}", n_train, tx.TEAL), (f"Calibration et seuils {years[1]}", n_fit, "#F59E0B"),
            (f"Test final {years[2]}", n_report, "#16A34A")]
    return charts.render({
        "grid": {"left": 8, "right": 8, "top": 36, "bottom": 8, "containLabel": False},
        "legend": {"top": 0, "textStyle": {"color": tx.MUTED}},
        "tooltip": {"trigger": "item", "formatter": "{a} : {c} marchés"},
        "xAxis": {"type": "value", "show": False, "max": n_train + n_fit + n_report},
        "yAxis": {"type": "category", "data": [""], "show": False},
        "series": [{"name": lab, "type": "bar", "stack": "t", "barWidth": 46,
                    "itemStyle": {"color": c, "borderColor": "#fff", "borderWidth": 2, "borderRadius": 8},
                    "label": {"show": True, "formatter": fr_int(n), "color": "#fff", "fontWeight": 600},
                    "data": [n]} for lab, n, c in segs],
    }, 120, key)


def funnel(steps: list[tuple[str, int, str]], key: str = "funnel", height: int = 330):
    """steps = [(label, count, colour)]; widths use the square root so small steps stay visible.
    Labels sit outside, on the right, so the narrow layers never truncate them."""
    import math
    top = max(n for _, n, _ in steps)
    return charts.render({
        "tooltip": {"trigger": "item", "formatter": "{b}"},
        "series": [{"type": "funnel", "sort": "none", "left": 0, "width": "42%", "top": 6, "bottom": 6,
                    "minSize": "22%", "maxSize": "100%", "gap": 4, "funnelAlign": "center",
                    "label": {"show": True, "position": "right", "color": tx.MUTED, "fontSize": 12, "lineHeight": 16,
                              "rich": {"n": {"fontSize": 16, "fontWeight": 700, "color": tx.INK, "lineHeight": 20}}},
                    "labelLine": {"show": True, "length": 14, "lineStyle": {"color": "#CBD5E1"}},
                    "itemStyle": {"borderColor": "#fff", "borderWidth": 1, "borderRadius": 8},
                    "data": [{"name": lab, "value": round(100 * math.sqrt(n / top), 2),
                              "label": {"formatter": "{n|" + fr_int(n) + "}\n" + lab},
                              "itemStyle": {"color": c}} for lab, n, c in steps]}],
    }, height, key)


def flow(nodes: list[tuple[str, str, str]], key: str = "flow", height: int = 230):
    """Horizontal chain of steps: nodes = [(emoji, short label, colour)]."""
    n = len(nodes)
    gnodes = [{"name": f"{i + 1}. {lab}", "x": i * 100, "y": 0 if i % 2 == 0 else 40, "symbolSize": 82,
               "itemStyle": {"color": c, "shadowBlur": 12, "shadowColor": c + "66"},
               "label": {"show": True, "formatter": f"{{e|{emo}}}\n{{t|{lab}}}", "position": "inside",
                         "rich": {"e": {"fontSize": 26, "lineHeight": 32}, "t": {"fontSize": 11, "color": "#fff",
                                                                                 "fontWeight": 600, "width": 70,
                                                                                 "overflow": "break"}}}}
              for i, (emo, lab, c) in enumerate(nodes)]
    links = [{"source": gnodes[i]["name"], "target": gnodes[i + 1]["name"]} for i in range(n - 1)]
    return charts.render({
        "tooltip": {"show": False},
        "series": [{"type": "graph", "layout": "none", "roam": False, "data": gnodes, "links": links,
                    "edgeSymbol": ["none", "arrow"], "edgeSymbolSize": 12,
                    "lineStyle": {"color": "#94A3B8", "width": 3, "curveness": 0.15}, "left": 50, "right": 50}],
    }, height, key)


# ------------------------------------------------------------------------------------------ cards
def step_card(num: int, emoji: str, title: str, body: str, figures: list[tuple[str, str]], color: str,
              source: str = "") -> None:
    figs = "".join(f'<div style="margin-top:6px"><span style="font-size:1.35rem;font-weight:650;color:{color}">'
                   f'{esc(v)}</span> <span style="color:#64748B;font-size:.85rem">{esc(lab)}</span></div>'
                   for v, lab in figures)
    src = f'<div class="ou-source">Source : {esc(source)}</div>' if source else ""
    st.markdown(
        f'<div class="ou-kpi" style="border-top:5px solid {color}">'
        f'<span class="emo" style="font-size:2rem">{emoji}</span>'
        f'<div class="lab" style="color:{color}">Étape {num}</div>'
        f'<div style="font-size:1.15rem;font-weight:650;margin:2px 0 4px">{esc(title)}</div>'
        f'<div style="color:#334155;font-size:.92rem">{body}</div>{figs}{src}</div>',
        unsafe_allow_html=True)


def rule_card(reco: str, condition: str, result: str) -> None:
    t = tx.RECO[reco]
    st.markdown(
        f'<div class="ou-kpi" style="border-left:6px solid {t.color}">'
        f'<div style="font-size:1.2rem;font-weight:650;color:{t.color}">{t.emoji} {esc(reco)}</div>'
        f'<div style="color:#334155;font-size:.92rem;margin-top:4px">{condition}</div>'
        f'<div class="sub" style="margin-top:6px">{result}</div></div>', unsafe_allow_html=True)
