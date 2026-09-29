from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent
LOGO_FILE = ROOT / "config" / "logo_setta.svg"

CSS = """
<style>
[data-testid="stAppViewContainer"]{background:#f4f7fb!important}
[data-testid="stHeader"]{background:rgba(255,255,255,.96)!important}
.block-container{max-width:1780px!important;padding-top:3.2rem!important;padding-left:2.7rem!important;padding-right:2.7rem!important;padding-bottom:3rem!important;width:100%!important}
section[data-testid="stSidebar"]{background:#fff!important;border-right:1px solid #e8ebf0!important}
section[data-testid="stSidebar"] .block-container{padding-top:1.6rem!important;padding-left:1rem!important;padding-right:1rem!important}
.sidebar-brand{background:#f8fafc;border:1px solid #e5e8ee;border-radius:12px;padding:.9rem 1rem;margin:0 0 1.05rem 0}
.sidebar-brand-title{font-size:.92rem;font-weight:800;color:#111827;letter-spacing:-.01em}
.sidebar-brand-sub{margin-top:.18rem;font-size:.75rem;color:#6b7280}
.sidebar-section-label{margin:.25rem 0 .45rem;color:#374151;font-size:.76rem;font-weight:800;text-transform:uppercase;letter-spacing:.055em}
.sidebar-logo-preview{width:100%;min-height:82px;display:flex;justify-content:center;align-items:center;margin:.65rem 0 .5rem;padding:.65rem .8rem;background:#fff;border:1px dashed #d1d5db;border-radius:10px;box-sizing:border-box;overflow:hidden}
.sidebar-logo-preview img{display:block;width:auto;height:auto;max-width:140px;max-height:62px;object-fit:contain}
.sidebar-info-card{background:#f8fafc;border:1px solid #e5e8ee;border-radius:10px;padding:.75rem .85rem;color:#6b7280;font-size:.76rem;line-height:1.55}
section[data-testid="stSidebar"] div[role="radiogroup"]{display:flex;flex-direction:column;gap:.34rem}
section[data-testid="stSidebar"] div[role="radiogroup"] label{position:relative;width:100%;min-height:42px;display:flex!important;align-items:center!important;padding:.56rem .72rem .56rem .88rem!important;margin:0!important;border:1px solid transparent!important;border-radius:10px!important;background:transparent!important;cursor:pointer}
section[data-testid="stSidebar"] div[role="radiogroup"] label>div:first-child{position:absolute!important;opacity:0!important;width:0!important;height:0!important;overflow:hidden!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label p{margin:0!important;font-size:.83rem!important;font-weight:600!important;color:#374151!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label:hover{background:#f8fafc!important;border-color:#e5e7eb!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked){background:#111827!important;border-color:#111827!important;box-shadow:0 5px 14px rgba(17,24,39,.14)!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked)::before{content:"";position:absolute;left:.42rem;top:50%;width:4px;height:20px;border-radius:999px;background:#ef4444;transform:translateY(-50%)}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p{color:#fff!important;font-weight:700!important}
.setta-logo-card{width:100%;min-height:128px;display:flex;align-items:center;justify-content:center;background:#fff;border:1px solid #e5e8ee;border-radius:16px;box-shadow:0 4px 14px rgba(24,39,75,.08);box-sizing:border-box;margin:0 0 2.55rem;padding:1.1rem 2rem}
.setta-logo-card img{display:block;width:auto;height:auto;max-width:205px;max-height:86px;object-fit:contain}
.app-title{margin:0!important;padding:0!important;font-size:2.55rem!important;line-height:1.08!important;font-weight:800!important;letter-spacing:-.04em!important;color:#050505!important}
.app-sub{margin-top:.72rem!important;margin-bottom:1.65rem!important;color:#4f5661!important;font-size:.94rem!important}
.section-title{margin:0 0 1rem!important;color:#0f172a!important;font-size:1.28rem!important;font-weight:800!important;letter-spacing:-.02em}
.intro,.panel,.kpi-card{background:#fff;border:1px solid #e5e8ee;border-radius:14px}
.intro{padding:.9rem 1rem;color:#555c66;margin-bottom:1rem;box-shadow:0 3px 12px rgba(15,23,42,.035)}
.kpi-card{position:relative;min-height:116px;padding:16px 18px 15px;box-shadow:0 4px 16px rgba(15,23,42,.055);overflow:hidden}
.kpi-card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;background:var(--accent)}
.kpi-card.selected{outline:2px solid var(--accent);outline-offset:1px}
.kpi-header{display:flex;align-items:center;gap:8px;margin-bottom:11px}
.kpi-dot{width:9px;height:9px;border-radius:999px;background:var(--accent);box-shadow:0 0 0 4px var(--accent-soft)}
.kpi-label{color:#475569;font-size:.83rem;font-weight:700}
.kpi-value{color:#0f172a;font-size:2rem;font-weight:800;line-height:1;letter-spacing:-.035em}
.kpi-delta{margin-top:8px;color:#64748b;font-size:.76rem}
.panel{padding:1.05rem 1.15rem;box-shadow:0 3px 12px rgba(15,23,42,.04)}
.panel-title{color:#111827;font-size:.94rem;font-weight:800;margin-bottom:.35rem}
.panel-text{color:#667085;font-size:.84rem;line-height:1.55}
.placeholder{border:1px dashed #cbd5e1;border-radius:12px;background:#f8fafc;padding:1.2rem;color:#64748b;font-size:.85rem}
.footer{text-align:center;color:#9298a1;font-size:.72rem;padding-top:1.2rem}
@media (max-width:900px){
.block-container{padding-top:2rem!important;padding-left:1rem!important;padding-right:1rem!important;padding-bottom:2rem!important}
.setta-logo-card{min-height:105px;margin-bottom:1.8rem;padding:.9rem 1rem}
.setta-logo-card img{max-width:170px;max-height:72px}
.app-title{font-size:2rem!important}
div[data-testid="stHorizontalBlock"]{flex-wrap:wrap!important}
div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]{min-width:100%!important;width:100%!important;flex:1 1 100%!important}
}
</style>
"""


def logo_html() -> str:
    if not LOGO_FILE.exists():
        return '<b style="font-size:2rem;letter-spacing:.08em">SETTA</b>'
    data = base64.b64encode(LOGO_FILE.read_bytes()).decode()
    return f'<img src="data:image/svg+xml;base64,{data}" alt="Logo Setta">'


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def panel(title: str, text: str) -> None:
    st.markdown(
        f'<div class="panel"><div class="panel-title">{title}</div><div class="panel-text">{text}</div></div>',
        unsafe_allow_html=True,
    )


def kpi(label: str, value: int, detail: str, accent: str, soft: str, selected: bool = False) -> None:
    selected_class = " selected" if selected else ""
    st.markdown(
        f'<div class="kpi-card{selected_class}" style="--accent:{accent};--accent-soft:{soft}">'
        f'<div class="kpi-header"><span class="kpi-dot"></span><span class="kpi-label">{label}</span></div>'
        f'<div class="kpi-value">{value}</div><div class="kpi-delta">{detail}</div></div>',
        unsafe_allow_html=True,
    )
