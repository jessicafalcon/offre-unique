"""Small visual components (HTML + CSS) shared by every page.

    inject_css()                         once per run (app.py does it)
    kpi(label, value, emoji, sub, color) a KPI card
    chip(tag, extra="")                  emoji + label pill in the tag's colour
    reco_badge(reco)                     Aller / À étudier / Passer badge
    people(level)                        1-5 person icons for company size
    source(text)                         source + licence line (required by the hackathon rules)
"""
from __future__ import annotations

import html as _html

import streamlit as st

from . import taxonomy as tx

CSS = """
<style>
.block-container {padding-top: 2rem; max-width: 1400px;}
h1, h2, h3 {letter-spacing: -0.01em;}
.ou-kpi {background:#fff; border:1px solid #E2E8F0; border-radius:14px; padding:14px 16px; height:100%;
         box-shadow:0 1px 2px rgba(15,23,42,.04);}
.ou-kpi .lab {color:#64748B; font-size:.74rem; font-weight:500; text-transform:uppercase; letter-spacing:.03em;
              word-break:normal; overflow-wrap:normal; hyphens:none; line-height:1.3;}
.ou-kpi .val {font-size:1.7rem; font-weight:650; color:#0F172A; line-height:1.2; margin-top:2px;}
.ou-kpi .sub {color:#64748B; font-size:.85rem; margin-top:2px;}
.ou-kpi .emo {float:right; font-size:1.6rem; line-height:1;}
.ou-chip {display:inline-flex; align-items:center; gap:.35em; padding:2px 10px; border-radius:999px;
          font-size:.82rem; font-weight:500; white-space:nowrap; margin:0 4px 4px 0;}
.ou-badge {display:inline-block; padding:3px 12px; border-radius:999px; font-weight:600; font-size:.85rem; color:#fff;}
.ou-people {font-size:1.25rem; letter-spacing:2px;}
.ou-people .off {opacity:.18; filter:grayscale(1);}
.ou-source {color:#94A3B8; font-size:.78rem; margin-top:4px;}
.ou-hero {background:linear-gradient(135deg,#2E9E8F 0%,#1E293B 100%); color:#fff; border-radius:18px; padding:22px 26px;}
.ou-hero h2 {color:#fff; margin:0;}
.ou-hero .sub {opacity:.85;}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(s) -> str:
    return _html.escape(str(s if s is not None else ""), quote=False)


def kpi(label: str, value, emoji: str = "", sub: str = "", color: str | None = None) -> None:
    style = f' style="border-top:4px solid {color}"' if color else ""
    st.markdown(f'<div class="ou-kpi"{style}><span class="emo">{emoji}</span><div class="lab">{esc(label)}</div>'
                f'<div class="val">{esc(value)}</div><div class="sub">{esc(sub)}</div></div>', unsafe_allow_html=True)


def chip_html(tag: tx.Tag, extra: str = "") -> str:
    return (f'<span class="ou-chip" style="background:{tag.color}1F;color:{tag.color};border:1px solid {tag.color}55">'
            f'{tag.emoji} {esc(tag.label)}{(" · " + esc(extra)) if extra else ""}</span>')


def chip(tag: tx.Tag, extra: str = "") -> None:
    st.markdown(chip_html(tag, extra), unsafe_allow_html=True)


def reco_badge_html(reco: str) -> str:
    t = tx.RECO.get(reco)
    if not t:
        return ""
    return f'<span class="ou-badge" style="background:{t.color}">{t.emoji} {esc(t.label)}</span>'


def people_html(level: int) -> str:
    on = "👤" * max(0, min(5, level))
    off = "👤" * (5 - max(0, min(5, level)))
    return f'<span class="ou-people">{on}<span class="off">{off}</span></span>'


def source(text: str) -> None:
    st.markdown(f'<div class="ou-source">Source : {esc(text)}</div>', unsafe_allow_html=True)
