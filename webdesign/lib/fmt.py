"""French number formatting shared by every page.

    fr_int(12345) -> "12 345"      fr_num(1.25) -> "1,3"      fr_pct(0.534) -> "53 %"
    fr_eur(24_300_000) -> "24,3 M€"                             plural(1, "marché") -> "1 marché"
"""
from __future__ import annotations

NBSP = " "  # narrow no-break space, as in French typography


def fr_int(n) -> str:
    try:
        return f"{int(round(float(n))):,}".replace(",", NBSP)
    except (TypeError, ValueError):
        return "—"


def fr_num(x, digits: int = 1) -> str:
    try:
        v = round(float(x), digits)
    except (TypeError, ValueError):
        return "—"
    s = str(int(v)) if v == int(v) else f"{v:.{digits}f}"
    return s.replace(".", ",")


def fr_pct(p, digits: int = 0) -> str:
    """Share in [0, 1] -> '53 %'."""
    try:
        return f"{fr_num(100 * float(p), digits)}{NBSP}%"
    except (TypeError, ValueError):
        return "—"


def fr_eur(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    if v >= 1e9:
        return f"{fr_num(v / 1e9)}{NBSP}Md€"
    if v >= 1e6:
        return f"{fr_num(v / 1e6)}{NBSP}M€"
    if v >= 1e3:
        return f"{fr_int(v / 1e3)}{NBSP}k€"
    return f"{fr_int(v)}{NBSP}€"


def plural(n, word: str, plural_word: str | None = None) -> str:
    """plural(1, 'marché') -> '1 marché'; plural(3, 'marché') -> '3 marchés'."""
    try:
        k = int(n)
    except (TypeError, ValueError):
        k = 0
    return f"{fr_int(k)} {word if k <= 1 else (plural_word or word + 's')}"
