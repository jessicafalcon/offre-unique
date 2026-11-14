"""Helpers for the "Votre entreprise" page (views/entreprise.py): formatting, HTML blocks and charts.

Uses only the shared lib (taxonomy, charts, ui, fmt); nothing here reads files except through lib.data.
"""
from __future__ import annotations

import pandas as pd

from . import charts
from . import fmt
from . import taxonomy as tx
from .ui import esc, people_html

try:  # built by the data fork; fall back to the bare NAF code
    from .naf import naf_label as _naf_label
except Exception:  # noqa: BLE001
    _naf_label = None

DEPTS = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence", "05": "Hautes-Alpes",
    "06": "Alpes-Maritimes", "07": "Ardèche", "08": "Ardennes", "09": "Ariège", "10": "Aube", "11": "Aude",
    "12": "Aveyron", "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal", "16": "Charente",
    "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze", "20": "Corse", "21": "Côte-d'Or", "22": "Côtes-d'Armor",
    "23": "Creuse", "24": "Dordogne", "25": "Doubs", "26": "Drôme", "27": "Eure", "28": "Eure-et-Loir",
    "29": "Finistère", "30": "Gard", "31": "Haute-Garonne", "32": "Gers", "33": "Gironde", "34": "Hérault",
    "35": "Ille-et-Vilaine", "36": "Indre", "37": "Indre-et-Loire", "38": "Isère", "39": "Jura", "40": "Landes",
    "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire", "44": "Loire-Atlantique", "45": "Loiret", "46": "Lot",
    "47": "Lot-et-Garonne", "48": "Lozère", "49": "Maine-et-Loire", "50": "Manche", "51": "Marne",
    "52": "Haute-Marne", "53": "Mayenne", "54": "Meurthe-et-Moselle", "55": "Meuse", "56": "Morbihan",
    "57": "Moselle", "58": "Nièvre", "59": "Nord", "60": "Oise", "61": "Orne", "62": "Pas-de-Calais",
    "63": "Puy-de-Dôme", "64": "Pyrénées-Atlantiques", "65": "Hautes-Pyrénées", "66": "Pyrénées-Orientales",
    "67": "Bas-Rhin", "68": "Haut-Rhin", "69": "Rhône", "70": "Haute-Saône", "71": "Saône-et-Loire", "72": "Sarthe",
    "73": "Savoie", "74": "Haute-Savoie", "75": "Paris", "76": "Seine-Maritime", "77": "Seine-et-Marne",
    "78": "Yvelines", "79": "Deux-Sèvres", "80": "Somme", "81": "Tarn", "82": "Tarn-et-Garonne", "83": "Var",
    "84": "Vaucluse", "85": "Vendée", "86": "Vienne", "87": "Haute-Vienne", "88": "Vosges", "89": "Yonne",
    "90": "Territoire de Belfort", "91": "Essonne", "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis",
    "94": "Val-de-Marne", "95": "Val-d'Oise", "971": "Guadeloupe", "972": "Martinique", "973": "Guyane",
    "974": "La Réunion", "976": "Mayotte",
}

LABELS = {"rge": ("🌿", "RGE"), "ess": ("🤝", "ESS"), "societe_mission": ("🎯", "Société à mission"),
          "organisme_formation": ("🎓", "Organisme de formation"), "qualiopi": ("✅", "Qualiopi")}

SOURCE_DECP = "DECP consolidées (data.gouv.fr), marchés notifiés · Licence Ouverte 2.0"
SMALL_TRACK = 5   # below this many wins, show a compact list instead of charts

# ------------------------------------------------------------------------------------------- formatting
fr_int = fmt.fr_int
fmt_eur = fmt.fr_eur
plural = fmt.plural


def siren_valid(s: str) -> bool:
    from .data import siren_valid as _valid
    return _valid(s)


def dept_label(d) -> str:
    d = str(d or "")
    return f"{DEPTS[d]} ({d})" if d in DEPTS else (f"Dépt {d}" if d and d != "NA" else "Non précisé")


def naf_text(naf) -> str:
    if not naf:
        return ""
    if _naf_label:
        try:
            lab = _naf_label(naf)
            if lab:
                return str(lab)
        except Exception:  # noqa: BLE001
            pass
    return f"Activité NAF {naf}"


def pretty_name(prof: dict | None, ident: dict | None, siren: str) -> str:
    n = (prof or {}).get("name") or (ident or {}).get("nom")
    if not n:
        return f"Entreprise {siren}"
    return n.title() if n.isupper() else n


def bar_height(n_items: int) -> int:
    """Height of a horizontal bar chart: proportional to the number of bars, no big empty area."""
    return max(110, 34 * n_items + 30)


# ------------------------------------------------------------------------------------------- HTML blocks
def hero_html(name: str, activity: str, place: str, since: str, chips: list[str]) -> str:
    meta = " · ".join(esc(x) for x in (activity, place, since) if x)
    chips_html = "".join(chips)
    return (f'<div class="ou-hero"><div style="font-size:.85rem;opacity:.8;text-transform:uppercase;'
            f'letter-spacing:.06em">Votre entreprise</div><h2 style="font-size:2.1rem;margin:4px 0 6px">{esc(name)}</h2>'
            f'<div class="sub">{meta}</div><div style="margin-top:12px">{chips_html}</div></div>')


def white_chip(emoji: str, text: str) -> str:
    return (f'<span class="ou-chip" style="background:rgba(255,255,255,.16);color:#fff;'
            f'border:1px solid rgba(255,255,255,.35)">{emoji} {esc(text)}</span>')


def size_card_html(size: tx.Tag, level: int, headcount: str, year, categorie, n_etab) -> str:
    big = 34 + 9 * max(level, 1)  # the pictogram grows with the company
    cat = {"PME": "PME", "ETI": "ETI", "GE": "Grande entreprise"}.get(str(categorie or ""), "")
    lines = [f"<b>{esc(headcount)}</b>" + (f" <span style='color:#94A3B8'>({esc(year)})</span>" if year else "")]
    if cat:
        lines.append(f"Catégorie Insee : <b>{esc(cat)}</b>")
    if n_etab:
        lines.append(f"🏬 {esc(plural(n_etab, 'établissement ouvert', 'établissements ouverts'))}")
    ladder = "".join(
        f'<span title="{esc(t.label)}" style="font-size:{14 + 4 * tx.SIZE_LEVEL[t.key]}px;'
        f'opacity:{1 if t.key == size.key else .25};margin-right:6px">{t.emoji}</span>'
        for t in tx.SIZES if t.key != "inconnue")
    return (f'<div class="ou-kpi" style="border-top:4px solid {size.color}">'
            f'<div class="lab">Taille</div>'
            f'<div style="display:flex;align-items:center;gap:14px;margin-top:6px">'
            f'<div style="font-size:{big}px;line-height:1">{size.emoji}</div>'
            f'<div><div class="val" style="font-size:1.25rem;color:{size.color}">{esc(size.label)}</div>'
            f'{people_html(level)}</div></div>'
            f'<div class="sub" style="margin-top:8px">{"<br>".join(lines)}</div>'
            f'<div style="margin-top:10px">{ladder}</div></div>')


def sector_card_html(main: tx.Tag, activity: str, shares: list[tuple[tx.Tag, float]]) -> str:
    bars = "".join(
        f'<div style="display:flex;align-items:center;gap:8px;margin:5px 0">'
        f'<span style="width:1.4em">{t.emoji}</span>'
        f'<span style="flex:0 0 46%;font-size:.85rem;color:#334155">{esc(t.label)}</span>'
        f'<span style="flex:1;background:#F1F5F9;border-radius:6px;height:10px">'
        f'<span style="display:block;width:{max(3, round(100 * s))}%;height:10px;border-radius:6px;background:{t.color}"></span></span>'
        f'<span style="width:3em;text-align:right;font-size:.85rem;font-weight:600">{round(100 * s)} %</span></div>'
        for t, s in shares)
    return (f'<div class="ou-kpi" style="border-top:4px solid {main.color}"><div class="lab">Secteur d\'activité</div>'
            f'<div style="display:flex;align-items:center;gap:12px;margin-top:6px">'
            f'<div style="font-size:46px;line-height:1">{main.emoji}</div>'
            f'<div><div class="val" style="font-size:1.25rem;color:{main.color}">{esc(main.label)}</div>'
            f'<div class="sub">{esc(activity)}</div></div></div>'
            f'<div class="sub" style="margin-top:10px">Ses marchés publics, par type :</div>{bars}</div>')


def finance_card_html(fin: dict, place: str) -> str:
    """Head office and turnover. Turnover only when > 0 (0 means missing); the net result is never shown."""
    rows = []
    for y in sorted(fin or {}, reverse=True):
        ca = (fin[y] or {}).get("ca")
        try:
            ca = float(ca)
        except (TypeError, ValueError):
            continue
        if ca > 0:
            rows.append(f"💶 Chiffre d'affaires {esc(y)} : <b>{esc(fmt_eur(ca))}</b>")
            break
    body = "<br>".join(rows) if rows else "Comptes non publiés dans les données ouvertes."
    return (f'<div class="ou-kpi" style="border-top:4px solid #6366F1"><div class="lab">Siège et comptes</div>'
            f'<div style="font-size:40px;line-height:1;margin-top:6px">📍</div>'
            f'<div class="val" style="font-size:1.15rem">{esc(place) or "Adresse non renseignée"}</div>'
            f'<div class="sub" style="margin-top:8px">{body}</div></div>')


def typology_html(counts: dict[str, int]) -> str:
    """Every buyer kind as a tile; the ones this company works with are lit, with their count."""
    tiles = []
    for t in tx.BUYER_KINDS:
        n = counts.get(t.key, 0)
        on = n > 0
        tiles.append(
            f'<div style="flex:1 1 150px;border-radius:12px;padding:10px 12px;'
            f'background:{t.color + "1A" if on else "#F8FAFC"};border:1px solid {t.color + "66" if on else "#E2E8F0"};'
            f'opacity:{1 if on else .55}">'
            f'<div style="font-size:1.6rem;line-height:1">{t.emoji}</div>'
            f'<div style="font-weight:600;font-size:.88rem;color:{t.color if on else "#64748B"};margin-top:4px">{esc(t.label)}</div>'
            f'<div style="font-size:.75rem;color:#64748B">{esc(t.hint)}</div>'
            f'<div style="font-size:.8rem;font-weight:600;margin-top:4px;color:#0F172A">'
            f'{esc(plural(n, "marché")) if on else "—"}</div></div>')
    return f'<div style="display:flex;flex-wrap:wrap;gap:8px">{"".join(tiles)}</div>'


def teaser_html(n: int, n_open: int, n_aller: int, n_etudier: int) -> str:
    title = plural(n, "appel d'offres", "appels d'offres")
    return (f'<div class="ou-kpi" style="border-left:6px solid #2E9E8F;display:flex;align-items:center;gap:18px">'
            f'<div style="font-size:44px">🎯</div><div><div class="val" style="font-size:1.3rem">'
            f'{esc(title)} dans votre métier</div>'
            f'<div class="sub">{esc(plural(n_open, "ouvert", "ouverts"))} maintenant · '
            f'<b style="color:#16A34A">🟢 {fr_int(n_aller)} à saisir</b> · '
            f'<b style="color:#D97706">🟡 {fr_int(n_etudier)} à étudier</b></div></div></div>')


def small_track_html(n: int) -> str:
    return (f'<div class="ou-kpi" style="border-left:6px solid #84CC16;display:flex;align-items:center;gap:16px">'
            f'<div style="font-size:40px">🌱</div><div><div class="val" style="font-size:1.1rem">Profil en construction</div>'
            f'<div class="sub">{esc(plural(n, "marché public remporté", "marchés publics remportés"))} pour l\'instant : '
            f'plus elle gagne de marchés, plus le portrait s\'affine.</div></div></div>')


def contracts_table(c: pd.DataFrame) -> pd.DataFrame:
    """Compact list of past wins for small track records: date, buyer (with kind emoji), object, amount."""
    kinds = {t.key: t for t in tx.BUYER_KINDS}
    return pd.DataFrame({
        "Date": pd.to_datetime(c["date"], errors="coerce").dt.strftime("%d/%m/%Y").fillna(""),
        "Acheteur": [f"{kinds.get(k, kinds['autre']).emoji} {n}" for k, n in
                     zip(c["buyer_kind"], c["acheteur_nom"].fillna(c["buyer_siren"]).astype(str))],
        "Objet": c["objet"].fillna("").astype(str),
        "Montant": pd.to_numeric(c["montant"], errors="coerce").map(lambda v: fmt_eur(v) if pd.notna(v) and v > 0 else "—"),
    })


def contracts_list_html(c: pd.DataFrame) -> str:
    """Wrapped list of the few past wins (no truncation), one card-like row per contract."""
    d = contracts_table(c)
    rows = "".join(
        f'<div style="display:grid;grid-template-columns:92px 1fr 90px;gap:12px;padding:10px 4px;'
        f'border-top:1px solid #E2E8F0">'
        f'<div style="color:#64748B;font-size:.85rem">{esc(r.Date)}</div>'
        f'<div><div style="font-weight:600;font-size:.9rem">{esc(r.Acheteur)}</div>'
        f'<div style="color:#334155;font-size:.88rem">{esc(r.Objet)}</div></div>'
        f'<div style="text-align:right;font-weight:600">{esc(r.Montant)}</div></div>'
        for r in d.itertuples())
    return (f'<div class="ou-kpi" style="padding:6px 14px">'
            f'<div style="display:grid;grid-template-columns:92px 1fr 90px;gap:12px;padding:6px 4px;color:#64748B;'
            f'font-size:.75rem;text-transform:uppercase;letter-spacing:.03em"><div>Date</div><div>Acheteur et objet</div>'
            f'<div style="text-align:right">Montant</div></div>{rows}</div>')


# ------------------------------------------------------------------------------------------- charts
def kind_donut(counts: dict[str, int], total: int, height: int, key: str):
    """Donut by buyer kind with a readable legend (emoji + label + count) on the right."""
    data = [{"name": f"{t.emoji} {t.label} · {fr_int(counts[t.key])}", "value": int(counts[t.key]),
             "itemStyle": {"color": t.color}} for t in tx.BUYER_KINDS if counts.get(t.key)]
    data.sort(key=lambda d: -d["value"])
    return charts.render({
        "tooltip": {"trigger": "item", "formatter": "{b} ({d} %)"},
        "title": {"text": fr_int(total), "subtext": "marchés", "left": "22%", "top": "40%", "textAlign": "center",
                  "itemGap": 2, "textStyle": {"fontSize": 22, "fontWeight": 600, "color": tx.INK},
                  "subtextStyle": {"fontSize": 11, "color": tx.MUTED}},
        "legend": {"orient": "vertical", "right": 4, "top": "middle", "icon": "circle", "itemWidth": 10,
                   "itemHeight": 10, "itemGap": 9, "textStyle": {"color": "#334155", "fontSize": 12}},
        "series": [{"type": "pie", "radius": ["46%", "70%"], "center": ["23%", "50%"], "avoidLabelOverlap": True,
                    "itemStyle": {"borderRadius": 6, "borderColor": "#fff", "borderWidth": 2},
                    "label": {"show": False}, "data": data}],
    }, height, key)


def ordered_hbar(items: list[tuple], height: int, key: str | None = None):
    """Horizontal bars kept in the given order (first on top), integer axis."""
    return charts.render({
        "grid": {"left": 8, "right": 40, "top": 6, "bottom": 6, "containLabel": True},
        "xAxis": {"type": "value", "show": False, "minInterval": 1},
        "yAxis": {"type": "category", "inverse": True, "data": [i[0] for i in items], "axisTick": {"show": False},
                  "axisLine": {"show": False}, "axisLabel": {"color": tx.MUTED}},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "series": [{"type": "bar", "barWidth": 16, "label": {"show": True, "position": "right", "color": tx.INK},
                    "data": [{"value": i[1], "itemStyle": {"color": i[2], "borderRadius": [0, 6, 6, 0]}} for i in items]}],
    }, height, key)


def amount_items(c: pd.DataFrame) -> list[tuple]:
    """(label, count, colour) per amount band, from the smallest to the largest band seen."""
    counts = c["amount_band_std"].value_counts()
    idx = [i for i, lab in enumerate(tx.AMOUNT_ORDER) if counts.get(lab, 0)]
    if not idx:
        return []
    return [(tx.AMOUNT_SHORT[i], int(counts.get(tx.AMOUNT_ORDER[i], 0)), tx.AMOUNT_COLORS[max(i, 2)])
            for i in range(min(idx), max(idx) + 1)]


def year_counts(c: pd.DataFrame) -> tuple[list[str], list[int]]:
    y = pd.to_numeric(c["year"], errors="coerce")
    y = y[(y >= 2015) & (y <= pd.Timestamp.today().year)].astype(int).value_counts().sort_index()
    if y.empty:
        return [], []
    years = list(range(int(y.index.min()), int(y.index.max()) + 1))
    return [str(k) for k in years], [int(y.get(k, 0)) for k in years]


def wins_per_year(years: list[str], vals: list[int], height: int, key: str):
    """Line with area for 3+ years, plain bars otherwise (a single-point line reads as empty)."""
    line = len(years) >= 3
    series = ({"type": "line", "smooth": True, "symbolSize": 9, "data": vals,
               "lineStyle": {"width": 3, "color": tx.TEAL}, "itemStyle": {"color": tx.TEAL},
               "label": {"show": True, "position": "top", "color": tx.INK},
               "areaStyle": {"color": {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
                                       "colorStops": [{"offset": 0, "color": "rgba(46,158,143,.35)"},
                                                      {"offset": 1, "color": "rgba(46,158,143,0)"}]}}}
              if line else
              {"type": "bar", "barMaxWidth": 40, "data": vals, "itemStyle": {"color": tx.TEAL, "borderRadius": [6, 6, 0, 0]},
               "label": {"show": True, "position": "top", "color": tx.INK}})
    return charts.render({
        "grid": {"left": 8, "right": 16, "top": 24, "bottom": 8, "containLabel": True},
        "xAxis": {"type": "category", "data": years, "axisTick": {"show": False}, "axisLabel": {"color": tx.MUTED}},
        "yAxis": {"type": "value", "minInterval": 1, "splitLine": {"lineStyle": {"color": tx.LINE}},
                  "axisLabel": {"color": tx.MUTED}},
        "tooltip": {"trigger": "axis"},
        "series": [series],
    }, height, key)
