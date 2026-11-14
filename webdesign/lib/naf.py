"""NAF rév. 2 code -> French label (all 5 levels), from webdesign/data/naf.json.

    naf_label("71.20B")  -> "Analyses, essais et inspections techniques"
    naf_label("7120B")   -> same (dots optional); unknown sub-class -> its class, group or division label; else ""
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

NAF_JSON = Path(__file__).resolve().parents[1] / "data" / "naf.json"
SOURCE = "Nomenclature NAF rév. 2 (Insee)"


@lru_cache(maxsize=1)
def _labels() -> dict:
    try:
        return json.loads(NAF_JSON.read_text(encoding="utf-8")).get("labels", {})
    except (OSError, ValueError):
        return {}


def normalize(code) -> str:
    """'7120B' / '71.20b' / ' 71.20B ' -> '71.20B'; '' if it does not look like a NAF code."""
    s = re.sub(r"[^0-9A-Za-z]", "", str(code or "")).upper()
    m = re.fullmatch(r"(\d{2})(\d{0,2})([A-Z]?)", s)
    if not m:
        return ""
    div, rest, letter = m.groups()
    if not rest:
        return div
    return f"{div}.{rest}{letter}"


def naf_label(code) -> str:
    c = normalize(code)
    if not c:
        return ""
    lab = _labels()
    for k in (c, c[:5], c[:4], c[:2]):  # sub-class, class, group, division
        if k in lab:
            return lab[k]
    return ""
