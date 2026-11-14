"""SIREN input cleaning and validity check (ported from webdesign/lib/data.py on the webdesign/ui-redesign branch).

    from siren import clean_siren, siren_valid
    s = clean_siren(" 834 709 248 00012 ")   # -> "834709248" (spaces, dots, a full SIRET are accepted)
    siren_valid(s)                           # -> True

A SIREN is 9 digits whose Luhn key is correct. In the contract data, the 2.5 % of company SIRENs that fail the
key are typos: the ones checked (632041071, 451001561, 243659508) do not exist in the national register.
La Poste (356000000) is the known exception to the Luhn rule. Repeated-digit placeholders (999999999,
000000000...) are rejected; 123456789 already fails the key.
"""
from __future__ import annotations

import re

LA_POSTE = "356000000"


def clean_siren(raw) -> str:
    """Keep the digits only and the first 9 of them (a SIRET starts with the SIREN)."""
    return re.sub(r"\D", "", str(raw or ""))[:9]


def siren_valid(siren: str) -> bool:
    s = str(siren or "")
    if len(s) != 9 or not s.isdigit() or len(set(s)) == 1:
        return False
    if s == LA_POSTE:
        return True
    total = 0
    for i, ch in enumerate(reversed(s)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0
