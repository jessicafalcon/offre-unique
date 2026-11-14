"""Widgets of the "Appels d'offres" page (webdesign/views/appels.py). HTML snippets, sentences and charts.

    CSS                                 page-level styles (cards, chance bar, deadline pill)
    fr_num(x), fr_pct(p)                French number formatting
    deadline_html(row)                  "J-16" pill coloured by urgency, or the planned publication month
    chance_html(proba, avg)             coloured bar + % + wording (high chance = few competitors = opportunity)
    amount_chip_html(row)               amount band chip (BOAMP has no amount: "montant non publié")
    card_html(row, avg, selected)       one tender card
    reco_bar_html(counts)               stacked Aller / À étudier / Passer bar
    fact_sentences(row, siren)          Jessica's fact sentences (share over contracts with a known bid count)
    past_editions(row, hemi)            (editions, caption) from the Hémicycle cache, else the local DECP history
    editions_chart(eds, key)            bids per past comparable contract (ECharts bars)
    sort_tenders(t, how)                chance / deadline / amount / recommendation
"""
from __future__ import annotations

import html
import json
import re

import pandas as pd

from . import charts
from . import fmt
from . import taxonomy as tx
from .ui import chip_html, esc, reco_badge_html

CSS = """
<style>
.ap-card {background:#fff; border:1px solid #E2E8F0; border-radius:14px; padding:12px 14px 10px 14px;
          box-shadow:0 1px 2px rgba(15,23,42,.04);}
.ap-card.sel {background:#F0FDFA; border-color:#2E9E8F; box-shadow:0 0 0 2px #2E9E8F33;}
.ap-top {display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin-bottom:4px;}
.ap-title {font-weight:600; color:#0F172A; font-size:.98rem; line-height:1.3; margin:2px 0 6px 0;}
.ap-meta {color:#475569; font-size:.85rem; margin-bottom:6px;}
.ap-tag {display:inline-block; padding:1px 8px; border-radius:6px; font-size:.75rem; font-weight:600;
         background:#F1F5F9; color:#475569; border:1px solid #E2E8F0;}
.ap-tag.open {background:#ECFDF5; color:#047857; border-color:#A7F3D0;}
.ap-inc {display:inline-block; padding:1px 8px; border-radius:6px; font-size:.75rem; font-weight:600;
         background:#FEF3C7; color:#92400E; border:1px solid #FDE68A;}
.ap-dl {margin-left:auto; padding:1px 10px; border-radius:999px; font-size:.78rem; font-weight:600; color:#fff;}
.ap-chance {display:flex; align-items:center; gap:10px; font-size:.85rem; color:#475569; white-space:nowrap;}
.ap-chance .bar {flex:0 0 120px; height:10px; background:#F1F5F9; border-radius:999px; overflow:hidden;}
.ap-chance .bar > div {height:100%; border-radius:999px;}
.ap-chance b {color:#0F172A; font-size:1rem;}
.ap-recobar {display:flex; height:30px; border-radius:10px; overflow:hidden; font-size:.82rem; font-weight:600;
             color:#fff; gap:2px;}
.ap-recobar > div {display:flex; align-items:center; justify-content:center; white-space:nowrap; overflow:hidden;}
.ap-recolegend {display:flex; flex-wrap:wrap; gap:6px 18px; margin:8px 0 2px 0; font-size:.85rem; color:#475569;}
.ap-recolegend .it {display:flex; align-items:baseline; gap:6px;}
.ap-recolegend .dot {width:10px; height:10px; border-radius:3px; display:inline-block; align-self:center;}
.ap-recolegend b {color:#0F172A;}
.ap-legend {display:flex; flex-direction:column; gap:3px; font-size:.82rem; color:#334155; margin-top:-6px;}
.ap-legend .it {display:flex; align-items:center; gap:6px;}
.ap-legend .dot {width:10px; height:10px; border-radius:3px; flex:0 0 10px;}
.ap-legend .n {margin-left:auto; font-weight:600; color:#0F172A;}
.ap-sbs {display:flex; flex-direction:column; gap:10px; margin-top:6px;}
.ap-sb .lab {display:flex; justify-content:space-between; gap:8px; font-size:.84rem; color:#334155;}
.ap-sb .lab b {color:#0F172A;}
.ap-sb .bar {height:9px; background:#F1F5F9; border-radius:999px; overflow:hidden; margin-top:3px;}
.ap-sb .bar > div {height:100%; border-radius:999px;}
.ap-dtitle {font-weight:650; font-size:1.08rem; line-height:1.35; color:#0F172A; margin:6px 0 8px 0;
            display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden;}
.ap-fact {margin:2px 0; color:#334155;}
.ap-note {background:#F0FDFA; border-left:4px solid #2E9E8F; border-radius:8px; padding:10px 12px; color:#0F172A;}
.ap-why {background:#F8FAFC; border:1px dashed #CBD5E1; border-radius:8px; padding:8px 12px; color:#334155;}
</style>
"""


# ------------------------------------------------------------------------------------------ formatting
fr_num = fmt.fr_num
fr_pct = fmt.fr_pct


def fmt_date(d) -> str:
    return "" if pd.isna(d) else pd.Timestamp(d).strftime("%d/%m/%Y")


def _dl_color(days) -> str:
    if days is None or pd.isna(days):
        return "#94A3B8"
    d = int(days)
    if d < 0:
        return "#94A3B8"
    if d <= 3:
        return "#DC2626"
    if d <= 7:
        return "#EA580C"
    if d <= 15:
        return "#D97706"
    return "#475569"


def deadline_text(r) -> str:
    d = r.get("days_left")
    if d is not None and not pd.isna(d):
        d = int(d)
        return "clos" if d < 0 else ("dernier jour" if d == 0 else f"J-{d}")
    if pd.notna(r.get("pub_date")):
        return "publication " + pd.Timestamp(r["pub_date"]).strftime("%m/%Y")
    return "date à venir"


def deadline_html(r) -> str:
    col = _dl_color(r.get("days_left"))
    due = f"⏰ {deadline_text(r)}"
    if pd.notna(r.get("due_date")):
        due += f" · {fmt_date(r['due_date'])}"
    return f'<span class="ap-dl" style="background:{col}">{esc(due)}</span>'


def chance_html(proba: float, avg: float | None) -> str:
    label, _ = tx.chance_style(float(proba), avg)
    grad = tx.chance_gradient(float(proba))
    width = max(4, min(100, round(100 * float(proba) / 0.6)))  # 60 % fills the bar
    return (f'<div class="ap-chance"><div class="bar"><div style="width:{width}%;background:{grad}"></div></div>'
            f'<b>{fr_pct(proba)}</b><span>{esc(label)}</span></div>')


def amount_chip_html(r) -> str:
    if r.get("source") == "BOAMP":
        return '<span class="ou-chip" style="background:#F1F5F9;color:#64748B;border:1px solid #E2E8F0">💶 montant non publié</span>'
    rank, color, short = tx.amount_style(r.get("montant_estime_du_marche"))
    if rank < 0:
        return '<span class="ou-chip" style="background:#F1F5F9;color:#64748B;border:1px solid #E2E8F0">💶 montant inconnu</span>'
    fg = "#0C4A6E" if rank < 4 else "#FFFFFF"
    return f'<span class="ou-chip" style="background:{color};color:{fg};border:1px solid {color}">💶 {esc(short)}</span>'


def kind_tag_html(r) -> str:
    if r.get("source") == "BOAMP":
        return '<span class="ap-tag open">📬 Ouvert</span>'
    return '<span class="ap-tag">🗓️ Projet</span>'


def title_of(r, default: str = "Achat sans titre") -> str:
    """BOAMP titles carry HTML entities (&#039;): decode them once, the caller escapes for display."""
    t = r.get("libelle")
    return html.unescape(str(t)) if isinstance(t, str) and t.strip() else default


def buyer_tag(r) -> tx.Tag:
    return next((k for k in tx.BUYER_KINDS if k.key == r.get("buyer_kind")), tx.BUYER_KINDS[-1])


def buyer_name(r) -> str:
    n = r.get("buyer_name")
    return n if isinstance(n, str) and n.strip() else f"SIREN {r.get('buyer_siren')}"


def card_key(code) -> str:
    """Streamlit container key for a tender card (CSS class st-key-<key>)."""
    return "apc_" + re.sub(r"[^A-Za-z0-9_-]", "_", str(code))


def card_top_html(r) -> str:
    """Upper part of a tender card: badges, title, buyer, chips. The chance bar and the button sit below it."""
    title = title_of(r)
    title = title if len(title) <= 160 else title[:159] + "…"
    bt = buyer_tag(r)
    inc = '<span class="ap-inc">🏅 Vous êtes le titulaire sortant</span>' if r.get("is_incumbent") else ""
    return (
        f'<div class="ap-top">{reco_badge_html(r["reco"])} {kind_tag_html(r)} {inc} {deadline_html(r)}</div>'
        f'<div class="ap-title">{esc(title)}</div>'
        f'<div class="ap-meta">{bt.emoji} {esc(buyer_name(r))}</div>'
        f'<div>{chip_html(tx.sector_of(r.get("cpv_div")))}{amount_chip_html(r)}</div>'
    )


def cards_css(rows: list, selected_code: str) -> str:
    """Per-card styles: the card is a keyed st.container, coloured by its recommendation; the selected one is tinted."""
    rules = []
    for code, reco in rows:
        sel = str(code) == str(selected_code)
        rules.append(
            f".st-key-{card_key(code)} {{background:{'#F0FDFA' if sel else '#FFFFFF'};"
            f"border:1px solid {'#2E9E8F' if sel else '#E2E8F0'} !important; border-left:6px solid {tx.RECO[reco].color} !important;"
            f"border-radius:14px; padding:12px 14px 8px 14px !important; gap:.35rem;"
            f"{'box-shadow:0 0 0 2px #2E9E8F33;' if sel else 'box-shadow:0 1px 2px rgba(15,23,42,.04);'}}}"
        )
    return "<style>" + "\n".join(rules) + "</style>"


def card_html(r, avg: float | None, selected: bool = False) -> str:
    """Whole card as one HTML block (kept for other pages / integration)."""
    return (f'<div class="ap-card{" sel" if selected else ""}" style="border-left:6px solid {tx.RECO[r["reco"]].color}">'
            f'{card_top_html(r)}{chance_html(r["proba"], avg)}</div>')


RECO_HINT = {"Aller": "peu de concurrents attendus, métier déjà exercé ici",
             "À étudier": "à regarder de près", "Passer": "concurrence habituelle ou forte"}


def reco_bar_html(counts: dict) -> str:
    """Stacked bar (counts only inside, every non-zero segment at least 7 % wide) + a legend row with labels."""
    total = sum(counts.values()) or 1
    parts, legend = [], []
    for k in ("Aller", "À étudier", "Passer"):
        n = int(counts.get(k, 0))
        t = tx.RECO[k]
        legend.append(f'<span class="it"><span class="dot" style="background:{t.color}"></span><b>{esc(k)} · {n}</b>'
                      f'<span>{esc(RECO_HINT[k])}</span></span>')
        if not n:
            continue
        share = n / total
        inside = f"{t.emoji} {esc(k)} · {n}" if share >= 0.22 else f"{n}"
        parts.append(f'<div style="flex:{max(7.0, 100 * share):.1f} 1 0;background:{t.color}" '
                     f'title="{esc(k)} : {n}">{inside}</div>')
    return f'<div class="ap-recobar">{"".join(parts)}</div><div class="ap-recolegend">{"".join(legend)}</div>'


# ------------------------------------------------------------------------------------------ facts
def fact_sentences(r, siren: str = "") -> list[str]:
    """Same facts as Jessica's app.py: the share with one bid is over contracts with a known bid count (n_lab)."""
    out = []
    n, nd = int(r.get("n_match") or 0), int(r.get("n_match_dept") or 0)
    s = "Correspond à l'un de vos contrats passés" if n == 1 else f"Correspond à {n} de vos contrats passés"
    out.append(s + (f", dont {nd} dans ce département." if nd and nd != n else (" dans ce département." if nd else ".")))
    eds = json.loads(r.get("hist_editions") or "[]")
    offers = [e["offres"] for e in eds[:3] if e.get("offres") is not None]
    hist_n = int(r.get("hist_n") or 0)
    if offers and all(o == 1 for o in offers):
        out.append(f"Les {len(offers)} derniers marchés comparables de cet acheteur n'ont reçu qu'une offre."
                   if len(offers) > 1 else "Le dernier marché comparable de cet acheteur n'a reçu qu'une offre.")
    elif hist_n > 0 and pd.notna(r.get("hist_single_share")):
        share = round(100 * float(r["hist_single_share"]))
        n_lab = int(r.get("hist_n_lab") or hist_n)
        lead = ("Sur son seul marché comparable dont le nombre d'offres est connu" if n_lab == 1
                else f"Sur ses {n_lab} marchés comparables dont le nombre d'offres est connu")
        mean = ""
        if pd.notna(r.get("hist_mean_offers")):
            m = float(r["hist_mean_offers"])
            mean = f" ({fr_num(m)} {'offre' if m < 2 else 'offres'} en moyenne)"
        if n_lab == 1 and pd.notna(r.get("hist_mean_offers")):
            k = int(round(float(r["hist_mean_offers"])))
            out.append("Le seul marché comparable de cet acheteur dont le nombre d'offres est connu "
                       + ("n'en a reçu qu'une." if k == 1 else f"en a reçu {k}."))
        else:
            out.append(f"{lead}, cet acheteur n'a reçu qu'une offre dans {share} % des cas{mean}.")
    elif hist_n > 0:
        marches = "un marché comparable" if hist_n == 1 else f"{hist_n} marchés comparables"
        out.append(f"Cet acheteur a passé {marches}, sans nombre d'offres renseigné.")
    else:
        out.append("Aucun marché comparable de cet acheteur dans les données.")
    streak = int(r.get("incumbent_streak") or 0)
    if r.get("is_incumbent") or (siren and str(r.get("incumbent_siren") or "").replace(".0", "")[:9] == siren[:9]):
        out.append("Vous êtes le titulaire sortant : ce marché est un renouvellement à défendre.")
    elif streak >= 2:
        out.append(f"Le même titulaire a gagné les {streak} dernières fois.")
    elif hist_n > 0:
        out.append("Pas de titulaire installé sur ce type de marché.")
    return out


def fact_emoji(s: str) -> str:
    if s.startswith("Correspond"):
        return "🧩"
    if "titulaire" in s:
        return "🏅"
    if "acheteur" in s.lower() or "marché" in s:
        return "📊"
    return "•"


# ------------------------------------------------------------------------------------------ past contracts
def past_editions(r, hemi: dict) -> tuple[list[dict], str]:
    h = hemi.get(str(r.get("code"))) if hemi else None
    if h and h.get("editions"):
        when_ = pd.Timestamp(h["fetched_at"]).strftime("%d/%m/%Y à %H:%M") if h.get("fetched_at") else ""
        return h["editions"], (f"En direct d'Hémicycle · jeu « Marchés publics notifiés » · consulté le {when_}"
                               " · Licence Ouverte 2.0")
    eds = json.loads(r.get("hist_editions") or "[]")
    return eds, "DECP consolidées (data.gouv.fr) · Licence Ouverte 2.0"


def editions_chart(eds: list[dict], key: str, height: int = 210):
    rows = [e for e in eds if e.get("date")][:8][::-1]  # oldest first
    if not rows:
        return None
    data = []
    for e in rows:
        o = e.get("offres")
        v = int(o) if o is not None and not pd.isna(o) and o > 0 else 0
        who = e.get("titulaire_nom") or "titulaire non renseigné"
        data.append({"value": v, "name": f"{str(e.get('objet') or '')[:70]} · {who}",
                     "itemStyle": {"color": "#16A34A" if v == 1 else ("#CBD5E1" if v == 0 else "#64748B"),
                                   "borderRadius": [6, 6, 0, 0]}})
    return charts.render({
        "grid": {"left": 8, "right": 8, "top": 24, "bottom": 8, "containLabel": True},
        "tooltip": {"trigger": "item", "formatter": "{b}<br/>{c} offre(s)"},
        "xAxis": {"type": "category", "data": [pd.Timestamp(e["date"]).strftime("%m/%Y") for e in rows],
                  "axisTick": {"show": False}, "axisLabel": {"color": tx.MUTED}},
        "yAxis": {"type": "value", "minInterval": 1, "name": "offres", "nameTextStyle": {"color": tx.MUTED},
                  "splitLine": {"lineStyle": {"color": tx.LINE}}},
        "series": [{"type": "bar", "barMaxWidth": 34, "data": data,
                    "label": {"show": True, "position": "top", "color": tx.INK,
                              "formatter": "{c}"}}],
    }, height, key)


# ------------------------------------------------------------------------------------------ sorting
SORTS = ["Chance d'offre unique", "Échéance", "Montant", "Recommandation"]
_RECO_ORDER = {"Aller": 0, "À étudier": 1, "Passer": 2}


def sort_tenders(t: pd.DataFrame, how: str) -> pd.DataFrame:
    t = t.copy()
    if how == "Échéance":
        t["_k"] = t["days_left"].where(t["days_left"] >= 0)
        t = t.sort_values(["_k", "proba"], ascending=[True, False], na_position="last")
    elif how == "Montant":
        t = t.sort_values(["amount_rank", "proba"], ascending=[False, False])
    elif how == "Recommandation":
        t["_k"] = t["reco"].map(_RECO_ORDER)
        t = t.sort_values(["_k", "proba"], ascending=[True, False])
    else:
        t = t.sort_values("proba", ascending=False, kind="stable")
    return t.drop(columns=["_k"], errors="ignore").reset_index(drop=True)


# ------------------------------------------------------------------------------------------ overview charts
def kind_donut(t: pd.DataFrame, key: str):
    counts = t["buyer_kind"].value_counts()
    items = [(f"{k.emoji} {k.label}", int(counts.get(k.key, 0)), k.color) for k in tx.BUYER_KINDS]
    return charts.donut(items, height=210, key=key, center_label=str(len(t)))


def kind_legend_html(t: pd.DataFrame) -> str:
    """Legend under the buyer donut: colour, emoji, label and count, largest first."""
    counts = t["buyer_kind"].value_counts()
    rows = sorted([(k, int(counts.get(k.key, 0))) for k in tx.BUYER_KINDS if counts.get(k.key, 0)],
                  key=lambda x: -x[1])
    top, rest = rows[:6], rows[6:]
    html_rows = [f'<div class="it"><span class="dot" style="background:{k.color}"></span>{k.emoji} {esc(k.label)}'
                 f'<span class="n">{n}</span></div>' for k, n in top]
    if rest:
        html_rows.append(f'<div class="it" title="{esc(", ".join(k.label for k, _ in rest))}">'
                         f'<span class="dot" style="background:#CBD5E1"></span>'
                         f'+ {len(rest)} autre{"s" if len(rest) > 1 else ""} type{"s" if len(rest) > 1 else ""}'
                         f'<span class="n">{sum(n for _, n in rest)}</span></div>')
    return '<div class="ap-legend">' + "".join(html_rows) + "</div>"


def sector_bars_html(t: pd.DataFrame) -> str:
    """Tender counts per sector as HTML bars (label above, bar below): readable in a narrow column.
    With a single sector (e.g. all engineering), split by works / services / supplies instead."""
    counts = t["sector"].value_counts()
    if len(counts) >= 2:
        items = [(s.emoji, s.label, int(counts.get(s.key, 0)), s.color) for s in tx.SECTORS if counts.get(s.key, 0)]
    else:
        cat = t["categorie"].astype(str).replace({"NA": "Non précisé"}).value_counts()
        emo = {"Travaux": ("🛠️", "#F59E0B"), "Services": ("🤝", "#2E9E8F"), "Fournitures": ("📦", "#6366F1")}
        items = [(emo.get(c, ("📋", "#94A3B8"))[0], c, int(n), emo.get(c, ("📋", "#94A3B8"))[1]) for c, n in cat.items()]
    items = sorted(items, key=lambda i: -i[2])
    top, rest = items[:7], items[7:]
    if rest:
        top.append(("➕", f"{len(rest)} autres types", sum(i[2] for i in rest), "#CBD5E1"))
    mx = max([i[2] for i in top] or [1])
    rows = "".join(
        f'<div class="ap-sb"><div class="lab"><span>{e} {esc(lab)}</span><b>{fmt.fr_int(n)}</b></div>'
        f'<div class="bar"><div style="width:{max(2, round(100 * n / mx))}%;background:{c}"></div></div></div>'
        for e, lab, n, c in top)
    return f'<div class="ap-sbs">{rows}</div>'


def chance_gauge(proba: float, avg: float | None, color: str, key: str, height: int = 140):
    """Compact half gauge: chance of a single bid, with '× la moyenne' under the value."""
    v = round(100 * float(proba))
    sub = f"{fr_num(float(proba) / avg)} × la moyenne" if avg else ""
    return charts.render({
        "series": [{"type": "gauge", "startAngle": 180, "endAngle": 0, "min": 0, "max": 100,
                    "center": ["50%", "88%"], "radius": "150%",
                    "progress": {"show": True, "width": 16, "itemStyle": {"color": color}},
                    "axisLine": {"lineStyle": {"width": 16, "color": [[1, tx.LINE]]}},
                    "axisTick": {"show": False}, "splitLine": {"show": False}, "axisLabel": {"show": False},
                    "pointer": {"show": False}, "anchor": {"show": False},
                    "title": {"show": True, "offsetCenter": [0, "-8%"], "fontSize": 12, "color": tx.MUTED},
                    "detail": {"offsetCenter": [0, "-32%"], "fontSize": 28, "fontWeight": 650,
                               "formatter": "{value} %", "color": tx.INK},
                    "data": [{"value": v, "name": sub}]}],
    }, height, key)


HORIZON = 90  # days shown on the scatter; later deadlines are pinned in a "> 90 j" band at the right edge


def chance_deadline_scatter(t: pd.DataFrame, avg: float | None, key: str, height: int = 300):
    """x = days left, readable up to HORIZON days; later ones (mostly APProch projects) pinned at the edge."""
    from streamlit_echarts import JsCode
    d = t[t["days_left"].notna() & (t["days_left"] >= 0)]
    series = []
    edge = HORIZON + 8
    for reco in ("Aller", "À étudier", "Passer"):
        g = d[d["reco"] == reco]
        if g.empty:
            continue
        pts = []
        for i, r in enumerate(g.itertuples()):
            days = int(r.days_left)
            x = days if days <= HORIZON else edge + ((i * 37) % 9 - 4) * 0.6  # small spread inside the band
            size = 12 if r.amount_rank < 0 else 10 + 4 * r.amount_rank
            title = html.unescape(str(r.libelle or ""))[:60]
            pts.append({"value": [round(x, 1), round(100 * float(r.proba))], "symbolSize": size,
                        "name": f"{title} · J-{days} · {round(100 * float(r.proba))} %"})
        series.append({"name": reco, "type": "scatter", "data": pts,
                       "itemStyle": {"color": tx.RECO[reco].color, "opacity": .85,
                                     "borderColor": "#fff", "borderWidth": 1}})
    if series:
        series[0]["markArea"] = {"silent": True, "itemStyle": {"color": "rgba(148,163,184,0.10)"},
                                 "data": [[{"xAxis": HORIZON + 3}, {"xAxis": edge + 5}]]}
    if avg and series:
        series[0]["markLine"] = {"silent": True, "symbol": "none", "lineStyle": {"type": "dashed", "color": tx.MUTED},
                                 "label": {"formatter": f"moyenne {round(100 * avg)} %", "color": tx.MUTED,
                                           "position": "insideEndTop"},
                                 "data": [{"yAxis": round(100 * avg)}]}
    ymax = max(30, int((d["proba"].max() if len(d) else 0.3) * 100 / 10 + 1) * 10)
    return charts.render({
        "grid": {"left": 12, "right": 12, "top": 14, "bottom": 54, "containLabel": True},
        "legend": {"bottom": 0, "textStyle": {"color": tx.MUTED}, "itemGap": 14},
        "tooltip": {"trigger": "item", "formatter": "{b}"},
        "xAxis": {"type": "value", "min": 0, "max": edge + 5, "interval": 15,
                  "name": "jours avant la date limite", "nameLocation": "middle", "nameGap": 26,
                  "nameTextStyle": {"color": tx.MUTED},
                  "axisLabel": {"color": tx.MUTED, "formatter": JsCode(
                      f"function(v){{return v<{HORIZON} ? v+' j' : '';}}")},
                  "splitLine": {"lineStyle": {"color": tx.LINE}}},
        "yAxis": {"type": "value", "min": 0, "max": ymax, "name": "chance d'offre unique (%)",
                  "nameLocation": "middle", "nameGap": 34, "nameTextStyle": {"color": tx.MUTED},
                  "axisLabel": {"color": tx.MUTED}, "splitLine": {"lineStyle": {"color": tx.LINE}}},
        "graphic": [{"type": "text", "right": 14, "bottom": 60,
                     "style": {"text": f"> {HORIZON} j", "fill": tx.MUTED, "font": "12px Work Sans, sans-serif"}}],
        "series": series,
    }, height, key)
