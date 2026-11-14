"""ECharts helpers with the shared style (streamlit-echarts 0.7, ECharts 6).

    render(option, height=300, key=...)     draw any ECharts option with the shared font, palette and tooltip
    donut(items)                            items = [(label, value, colour), ...]
    hbar(items, unit="")                    horizontal bars, largest first
    gauge(value, ...)                       0-100 gauge
"""
from __future__ import annotations

from streamlit_echarts import st_echarts

from .taxonomy import INK, LINE, MUTED, PALETTE

FONT = "Work Sans, -apple-system, Segoe UI, sans-serif"


def styled(option: dict) -> dict:
    o = dict(option)
    o.setdefault("color", PALETTE)
    o.setdefault("textStyle", {"fontFamily": FONT, "color": INK})
    o.setdefault("tooltip", {"trigger": "item", "confine": True})
    o.setdefault("animationDuration", 600)
    return o


def render(option: dict, height: int = 300, key: str | None = None, **kw):
    return st_echarts(options=styled(option), height=f"{height}px", key=key, **kw)


def donut(items: list[tuple], height: int = 260, key: str | None = None, center_label: str = "", radius=("55%", "80%")):
    data = [{"name": lab, "value": v, "itemStyle": {"color": c}} for lab, v, c in items if v]
    return render({
        "tooltip": {"trigger": "item", "formatter": "{b} : {c} ({d} %)"},
        "title": {"text": center_label, "left": "center", "top": "center",
                  "textStyle": {"fontSize": 22, "fontWeight": 600, "color": INK}},
        "series": [{"type": "pie", "radius": list(radius), "avoidLabelOverlap": True,
                    "itemStyle": {"borderRadius": 6, "borderColor": "#fff", "borderWidth": 2},
                    "label": {"show": False}, "data": data}],
    }, height, key)


def hbar(items: list[tuple], height: int | None = None, key: str | None = None, unit: str = ""):
    """items = [(label, value, colour), ...], shown largest on top."""
    items = sorted([i for i in items if i[1]], key=lambda i: i[1])
    h = height or max(140, 34 * len(items) + 40)
    return render({
        "grid": {"left": 8, "right": 48, "top": 8, "bottom": 8, "containLabel": True},
        "xAxis": {"type": "value", "show": False, "minInterval": 1},
        "yAxis": {"type": "category", "data": [i[0] for i in items], "axisTick": {"show": False},
                  "axisLine": {"show": False}, "axisLabel": {"color": MUTED}},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "series": [{"type": "bar", "barWidth": 16, "label": {"show": True, "position": "right",
                                                             "formatter": "{c}" + unit, "color": INK},
                    "data": [{"value": i[1], "itemStyle": {"color": i[2], "borderRadius": [0, 6, 6, 0]}} for i in items]}],
    }, h, key)


def gauge(value: float, height: int = 220, key: str | None = None, color: str = "#2E9E8F", label: str = ""):
    return render({
        "series": [{"type": "gauge", "startAngle": 200, "endAngle": -20, "min": 0, "max": 100,
                    "progress": {"show": True, "width": 14, "itemStyle": {"color": color}},
                    "axisLine": {"lineStyle": {"width": 14, "color": [[1, LINE]]}},
                    "axisTick": {"show": False}, "splitLine": {"show": False}, "axisLabel": {"show": False},
                    "pointer": {"show": False}, "anchor": {"show": False},
                    "title": {"offsetCenter": [0, "35%"], "fontSize": 13, "color": MUTED},
                    "detail": {"valueAnimation": True, "offsetCenter": [0, "-5%"], "fontSize": 30,
                               "fontWeight": 600, "formatter": "{value} %", "color": INK},
                    "data": [{"value": round(value), "name": label}]}],
    }, height, key)
