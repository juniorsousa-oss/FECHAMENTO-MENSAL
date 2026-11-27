from __future__ import annotations

import base64
from contextlib import contextmanager
from functools import lru_cache
from html import escape
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent
LOGO_FILE = ROOT / "config" / "logo_setta.svg"

CSS = """
<style>
.section-title{margin:0 0 1rem!important;color:#333333!important;font-size:1.28rem!important;font-weight:800!important;letter-spacing:-.02em}
.intro,.panel,.kpi-card{background:#fff;border:1px solid #e1e1e1;border-radius:8px}
.intro{padding:.9rem 1rem;color:#555c66;margin-bottom:1rem;box-shadow:0 3px 12px rgba(15,23,42,.035)}
.kpi-card{position:relative;min-height:116px;padding:16px 18px 15px;box-shadow:0 4px 16px rgba(15,23,42,.055);overflow:hidden}
.kpi-card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;background:var(--accent)}
.kpi-card.selected{outline:2px solid var(--accent);outline-offset:1px}
.kpi-header{display:flex;align-items:center;gap:8px;margin-bottom:11px}
.kpi-dot{width:9px;height:9px;border-radius:999px;background:var(--accent);box-shadow:0 0 0 4px var(--accent-soft)}
.kpi-label{color:#525252;font-size:.83rem;font-weight:700}
.kpi-value{color:#333333;font-size:2rem;font-weight:800;line-height:1;letter-spacing:-.035em}
.kpi-delta{margin-top:8px;color:#525252;font-size:.76rem}
.panel{padding:1.05rem 1.15rem;box-shadow:0 3px 12px rgba(15,23,42,.04)}
.panel-title{color:#333333;font-size:.94rem;font-weight:800;margin-bottom:.35rem}
.panel-text{color:#525252;font-size:.84rem;line-height:1.55}
.placeholder{border:1px dashed #d9d9d9;border-radius:8px;background:#fafafa;padding:1.2rem;color:#525252;font-size:.85rem}
.month-toolbar{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:.85rem}
.inventory-box{background:#fff;border:1px solid #e1e1e1;border-radius:8px;box-shadow:0 4px 16px rgba(15,23,42,.05);overflow:hidden}
.inventory-box-title{padding:.82rem 1rem;background:#e8e8e8;border-bottom:1px solid #d1d5db;text-align:center;font-size:.92rem;font-weight:900;color:#333333;letter-spacing:.025em;text-transform:uppercase}
.inventory-row{display:grid;grid-template-columns:minmax(150px,1.55fr) minmax(112px,.85fr);border-bottom:1px solid #e8e8e8;min-height:43px}
.inventory-row:last-child{border-bottom:0}
.inventory-label{display:flex;align-items:center;padding:.62rem .85rem;background:#f3f4f6;color:#333333;font-size:.76rem;font-weight:800;text-transform:uppercase}
.inventory-value{display:flex;align-items:center;justify-content:flex-end;padding:.62rem .85rem;color:#333333;font-size:.8rem;font-weight:800;background:#fff}
.inventory-value.negative{color:#b91c1c}
.inventory-value.positive{color:#166534}
.inventory-spacer{height:12px;background:#f0f0f0}
.mov-grid{display:grid;grid-template-columns:1.45fr .86fr .86fr;gap:.75rem;align-items:stretch}
.mov-col{background:#fff;border:1px solid #e1e1e1;border-radius:8px;overflow:hidden}
.mov-head{padding:.72rem .8rem;background:#e8e8e8;text-align:center;font-weight:900;font-size:.79rem;color:#333333;text-transform:uppercase;border-bottom:1px solid #d1d5db}
.mov-row{display:grid;grid-template-columns:minmax(130px,1.5fr) minmax(105px,.9fr);border-bottom:1px solid #e8e8e8;min-height:42px}
.mov-row:last-child{border-bottom:0}
.mov-label{display:flex;align-items:center;padding:.58rem .7rem;background:#f3f4f6;font-size:.71rem;font-weight:800;color:#333333;text-transform:uppercase}
.mov-value{display:flex;align-items:center;justify-content:flex-end;padding:.58rem .7rem;font-size:.75rem;font-weight:800;background:#fff;color:#333333}
.mov-value.negative{color:#b91c1c}
.mov-value.positive{color:#166534}
.history-title{margin-top:1.4rem!important}
.topic-divider{height:1px;background:#d9d9d9;margin:1.7rem 0 1.15rem;width:100%}
.section-band{margin:0 0 .95rem;padding:.82rem 1rem;background:#fff;border:1px solid #e1e1e1;border-left:4px solid #ffbb00;border-radius:8px;box-shadow:0 3px 12px rgba(15,23,42,.035)}
.section-band-kicker{font-size:.66rem;font-weight:800;letter-spacing:.085em;text-transform:uppercase;color:#765800;margin-bottom:.18rem}
.section-band-title{font-size:1.08rem;font-weight:900;color:#333333;letter-spacing:-.015em;line-height:1.2;text-transform:uppercase}
.section-band-note{margin-top:.26rem;color:#525252;font-size:.78rem;line-height:1.45}
.summary-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem;margin-bottom:.25rem}
.cb-kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.85rem;margin:.25rem 0 1rem}
.cb-compact-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.55rem;margin:.55rem 0 .55rem}
.cb-compact-stat{display:flex;align-items:center;justify-content:space-between;gap:.75rem;min-height:52px;padding:.55rem .75rem;background:#fff;border:1px solid #e1e1e1;border-radius:10px}
.cb-compact-stat span{font-size:.67rem;font-weight:800;letter-spacing:.035em;color:#525252}
.cb-compact-stat strong{font-size:1.32rem;line-height:1;color:#333333}
.cb-compact-stat-final{border-left:4px solid #333333}
/* Conferência de chapas e barramentos — hierarquia visual SETTA */
.cb-period-label{
  font-size:.71rem;font-weight:800;letter-spacing:.075em;
  color:#525252;text-transform:uppercase;margin:.8rem 0 .35rem;
}
.cb-overview-grid{
  display:grid;grid-template-columns:repeat(4,minmax(0,1fr));
  gap:14px;margin:1.15rem 0 1.15rem;
}
.cb-overview-card{
  min-width:0;display:flex;flex-direction:column;align-items:flex-start;
  min-height:114px;padding:16px 18px 14px;
  background:#fff;border:1px solid #e1e1e1;border-radius:8px;
  box-shadow:0 5px 18px rgba(15,23,42,.045);
}
.cb-overview-card span{
  font-size:.65rem;letter-spacing:.075em;font-weight:850;
  text-transform:uppercase;color:#525252;line-height:1.35;
}
.cb-overview-card strong{
  display:block;font-size:1.85rem;line-height:1.15;
  letter-spacing:-.035em;color:#333333;font-weight:850;margin:7px 0 5px;
}
.cb-overview-card small{font-size:.72rem;color:#595959;line-height:1.4}
.cb-overview-card-final{border-top:3px solid #333333;padding-top:14px}
.cb-stage-header{
  display:flex;align-items:center;gap:14px;min-height:80px;
  margin:2rem 0 1rem;padding:16px 20px;background:#fff;
  border:1px solid #e1e1e1;border-radius:8px;
  box-shadow:0 4px 16px rgba(15,23,42,.04);
}
.cb-stage-number{
  display:flex;align-items:center;justify-content:center;flex:none;
  width:40px;height:40px;background:#333333;color:#fff;
  border-radius:11px;font-size:.78rem;font-weight:800;
  letter-spacing:.04em;
}
.cb-stage-copy{min-width:0}
.cb-stage-name{
  color:#333333;font-size:.98rem;font-weight:850;
  text-transform:uppercase;letter-spacing:.012em;line-height:1.4;
}
.cb-stage-description{color:#718096;font-size:.76rem;line-height:1.5;margin-top:3px}
.cb-balance-grid{
  display:grid;grid-template-columns:repeat(2,minmax(0,1fr));
  gap:16px;margin:0 0 1.1rem;
}
.cb-balance-card{
  min-width:0;padding:20px 22px 22px;background:#fff;
  border:1px solid #e1e1e1;border-radius:8px;
  box-shadow:0 4px 16px rgba(15,23,42,.04);
}
.cb-balance-top{
  display:flex;align-items:center;justify-content:space-between;
  gap:10px;padding-bottom:15px;border-bottom:1px solid #e8e8e8;
}
.cb-balance-top strong{
  color:#333333;font-size:.82rem;letter-spacing:.055em;font-weight:850;
}
.cb-balance-top span{
  color:#595959;font-size:.65rem;letter-spacing:.045em;font-weight:750;
}
.cb-balance-pair{
  display:grid;grid-template-columns:repeat(2,minmax(0,1fr));
  gap:18px;padding-top:18px;
}
.cb-balance-pair>div{min-width:0}
.cb-balance-pair>div+div{border-left:1px solid #e8e8e8;padding-left:18px}
.cb-balance-pair span{
  display:block;font-size:.66rem;color:#525252;
  letter-spacing:.045em;text-transform:uppercase;font-weight:750;
  line-height:1.4;margin-bottom:8px;
}
.cb-balance-pair strong{
  display:block;overflow-wrap:anywhere;font-size:clamp(1rem,1.3vw,1.4rem);
  font-weight:800;letter-spacing:-.025em;line-height:1.25;color:#333333;
}
.cb-subsection-label{
  color:#525252;font-size:.73rem;letter-spacing:.07em;
  font-weight:850;text-transform:uppercase;
  margin:1.3rem 0 .8rem;
  padding:0 0 .55rem;border-bottom:1px solid #dce3eb;
}
.cb-kpi-grid{gap:14px!important;margin:1.2rem 0 1.6rem!important}
.cb-kpi{min-height:122px!important;padding:17px 19px!important;border-radius:8px!important}
.cb-kpi-label{font-size:.69rem!important}
.cb-kpi-value{font-size:1.48rem!important;margin-top:.3rem}
.cb-kpi-note{font-size:.73rem!important;line-height:1.5;margin-top:.48rem!important}
@media(max-width:1050px){
  .cb-overview-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .cb-balance-grid{grid-template-columns:1fr}
}
@media(max-width:560px){
  .cb-overview-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
  .cb-overview-card{padding:13px 12px;min-height:100px}
  .cb-overview-card strong{font-size:1.45rem}
  .cb-overview-card small{font-size:.66rem}
  .cb-stage-header{gap:10px;padding:12px;margin:1.45rem 0 .85rem}
  .cb-stage-number{width:34px;height:34px}
  .cb-stage-name{font-size:.85rem}
  .cb-stage-description{font-size:.7rem}
  .cb-balance-card{padding:15px 14px}
  .cb-balance-pair{gap:9px}
  .cb-balance-pair>div+div{padding-left:9px}
  .cb-balance-pair strong{font-size:.93rem}
}
.cb-tight-divider{margin:.85rem 0 .7rem!important}
.cb-compact-section-title{font-size:.82rem;font-weight:900;letter-spacing:.035em;color:#333333;margin:0 0 .45rem;text-transform:uppercase}
.cb-kpi{position:relative;background:#fff;border:1px solid #e1e1e1;border-radius:8px;box-shadow:0 3px 12px rgba(15,23,42,.04);padding:.85rem 1rem;overflow:hidden}
.cb-kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--cb-accent,#333333)}
.cb-kpi-label{font-size:.66rem;font-weight:900;letter-spacing:.04em;text-transform:uppercase;color:#525252;margin-bottom:.42rem}
.cb-kpi-value{font-size:1.25rem;font-weight:900;letter-spacing:-.02em;color:#333333}
.cb-kpi-note{margin-top:.3rem;font-size:.68rem;color:#595959}
.cb-source-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.85rem;margin:.3rem 0 1rem}
.cb-source-card{background:#fff;border:1px solid #e1e1e1;border-radius:8px;padding:.95rem 1rem;box-shadow:0 3px 12px rgba(15,23,42,.035)}
.cb-source-title{font-size:.8rem;font-weight:900;color:#333333;text-transform:uppercase;margin-bottom:.3rem}
.cb-source-text{font-size:.74rem;color:#525252;line-height:1.45}
.cb-source-tag{display:inline-flex;margin-top:.55rem;padding:.22rem .46rem;border-radius:999px;background:#f1f5f9;color:#525252;font-size:.64rem;font-weight:800}
.cb-inline-title{font-size:.92rem;font-weight:900;color:#333333;letter-spacing:-.01em;text-transform:uppercase;line-height:1.2;margin:.25rem 0 .35rem}
.cb-title-inline{display:flex;align-items:center;gap:.45rem;width:max-content;max-width:100%;margin:0 0 .45rem}
.cb-title-main{margin:0!important}
.cb-info-wrap{position:relative;display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;outline:none}
.cb-info-icon{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:999px;border:1px solid #d9d9d9;background:#fff;color:#525252;font-size:.7rem;font-weight:900;line-height:1;cursor:help;user-select:none}
.cb-info-wrap:hover .cb-info-icon,.cb-info-wrap:focus .cb-info-icon{border-color:#595959;color:#333333;background:#fafafa}
.cb-info-tooltip{position:absolute;left:50%;top:calc(100% + 9px);transform:translateX(-50%) translateY(-3px);width:360px;max-width:min(360px,80vw);padding:.8rem .9rem;background:#333333;color:#fff;border-radius:10px;box-shadow:0 10px 28px rgba(15,23,42,.22);opacity:0;visibility:hidden;pointer-events:none;z-index:9999;transition:opacity .14s ease,transform .14s ease;text-align:left}
.cb-info-tooltip::before{content:"";position:absolute;left:50%;top:-5px;width:10px;height:10px;background:#333333;transform:translateX(-50%) rotate(45deg)}
.cb-info-tooltip strong{display:block;font-size:.67rem;letter-spacing:.06em;margin-bottom:.35rem}
.cb-info-tooltip span{display:block;font-size:.72rem;line-height:1.5;color:#e8e8e8}
.cb-info-wrap:hover .cb-info-tooltip,.cb-info-wrap:focus .cb-info-tooltip{opacity:1;visibility:visible;transform:translateX(-50%) translateY(0)}
div[data-testid="stPopover"] button{min-height:28px!important;width:28px!important;height:28px!important;padding:0!important;border-radius:999px!important;border:1px solid #d8dde5!important;background:#fff!important;color:#525252!important;font-size:.92rem!important;font-weight:800!important;box-shadow:none!important}
div[data-testid="stPopover"] button:hover{background:#fafafa!important;border-color:#d9d9d9!important;color:#333333!important}
.summary-card{position:relative;background:#fff;border:1px solid #e1e1e1;border-radius:8px;box-shadow:0 4px 16px rgba(15,23,42,.05);padding:1rem 1.15rem 1.05rem;overflow:hidden}
.summary-card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;background:#333333}
.summary-card-label{font-size:.7rem;font-weight:900;letter-spacing:.045em;text-transform:uppercase;color:#525252;margin-bottom:.55rem}
.summary-card-value{font-size:1.65rem;font-weight:900;letter-spacing:-.025em;color:#333333;line-height:1.05}
.summary-card-value.negative{color:#b91c1c}
.summary-card-value.positive{color:#166534}
.tp-table{background:#fff;border:1px solid #e1e1e1;border-radius:8px;box-shadow:0 4px 16px rgba(15,23,42,.045);overflow:hidden}
.tp-table-row{display:grid;grid-template-columns:.72fr 1fr 1fr;min-height:44px;border-bottom:1px solid #e8e8e8;align-items:stretch}
.tp-table-row:last-child{border-bottom:0}
.tp-table-head{background:#e8e8e8;min-height:42px}
.tp-table-cell{display:flex;align-items:center;padding:.65rem .78rem;border-right:1px solid #e8e8e8;color:#374151;font-size:.76rem}
.tp-table-cell:last-child{border-right:0}
.tp-table-head .tp-table-cell{font-size:.7rem;font-weight:900;text-transform:uppercase;letter-spacing:.035em;color:#333333;justify-content:center}
.tp-table-type{font-weight:900;color:#333333;background:#fafafa}
.tp-table-money{justify-content:flex-end;font-weight:800;color:#333333}
.tp-table-total .tp-table-cell{background:#eef0f3;font-weight:900}
.history-wrap{background:#fff;border:1px solid #e1e1e1;border-radius:8px;box-shadow:0 4px 16px rgba(15,23,42,.045);overflow:hidden}
.history-row{display:grid;grid-template-columns:1.15fr 1fr 1fr 1fr .9fr;min-height:44px;border-bottom:1px solid #e8e8e8;align-items:stretch}
.history-row:last-child{border-bottom:0}
.history-head{background:#e8e8e8;min-height:42px}
.history-cell{display:flex;align-items:center;padding:.65rem .78rem;border-right:1px solid #e8e8e8;color:#374151;font-size:.76rem}
.history-cell:last-child{border-right:0}
.history-head .history-cell{font-size:.7rem;font-weight:900;text-transform:uppercase;letter-spacing:.035em;color:#333333}
.history-month{font-weight:800;color:#333333}
.history-money{justify-content:flex-end;font-weight:750;color:#333333}
.history-money.negative{color:#b91c1c}
.history-money.positive{color:#166534}
.validation-badge{display:inline-flex;align-items:center;justify-content:center;min-width:86px;padding:.28rem .5rem;border-radius:999px;font-size:.67rem;font-weight:900;letter-spacing:.02em;white-space:nowrap}
.validation-ok{background:#dcfce7;color:#166534;border:1px solid #bbf7d0}
.validation-pending{background:#fee2e2;color:#b91c1c;border:1px solid #fecaca}
.validation-note{margin-top:.7rem;padding:.72rem .85rem;border:1px solid #fde68a;background:#fffbeb;border-radius:10px;color:#92400e;font-size:.75rem;line-height:1.45}
.module-hero{background:#fff;border:1px solid #e1e1e1;border-radius:8px;padding:1.05rem 1.15rem;box-shadow:0 3px 12px rgba(15,23,42,.04);margin-bottom:1rem}
.module-hero strong{display:block;color:#333333;font-size:.96rem;margin-bottom:.3rem}
.module-hero span{color:#525252;font-size:.84rem;line-height:1.55}
.footer{text-align:center;color:#9298a1;font-size:.72rem;padding-top:1.2rem}
@media (max-width:1100px){
.api-status-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}
.api-overview{grid-template-columns:repeat(2,minmax(0,1fr))!important}
}
@media (max-width:900px){
div[data-testid="stHorizontalBlock"]{flex-wrap:wrap!important}
div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]{min-width:100%!important;width:100%!important;flex:1 1 100%!important}
.mov-grid{grid-template-columns:1fr!important}
.inventory-row,.mov-row{grid-template-columns:1fr!important}
.inventory-value,.mov-value{justify-content:flex-start!important;border-top:1px solid #eef0f3}
.summary-grid{grid-template-columns:1fr!important}
.cb-kpi-grid,.cb-source-grid,.api-status-grid,.api-overview{grid-template-columns:1fr!important}
.tp-table-row{grid-template-columns:1fr!important}
.tp-table-head{display:none!important}
.tp-table-cell{border-right:0!important;border-bottom:1px solid #eef0f3;justify-content:flex-start!important}
.tp-table-cell::before{content:attr(data-label);display:inline-block;min-width:115px;margin-right:.65rem;font-size:.65rem;font-weight:900;text-transform:uppercase;color:#525252}
.history-row{grid-template-columns:1fr!important}
.history-head{display:none!important}
.history-cell{border-right:0!important;border-bottom:1px solid #eef0f3;justify-content:flex-start!important}
.history-cell::before{content:attr(data-label);display:inline-block;min-width:118px;margin-right:.65rem;font-size:.65rem;font-weight:900;text-transform:uppercase;color:#525252}
}

</style>
"""


def logo_html(data: str = "", mime: str = "image/svg+xml") -> str:
    if data:
        return f'<img src="data:{mime};base64,{data}" alt="Logo Setta">'
    if not LOGO_FILE.exists():
        return '<b style="font-size:2rem;letter-spacing:.08em">SETTA</b>'
    fallback = base64.b64encode(LOGO_FILE.read_bytes()).decode()
    return f'<img src="data:image/svg+xml;base64,{fallback}" alt="Logo Setta">'


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


@lru_cache(maxsize=2)
def _setta_asset_b64(name: str) -> str:
    return base64.b64encode((ROOT / "assets" / name).read_bytes()).decode("ascii")


def render_shell(*, title: str, page_label: str, route_id: int) -> None:
    """Visual reference: the fixed Setta shell shared by MRP and Inventário."""
    assets = ROOT / "assets"
    font = _setta_asset_b64("outfit-latin.woff2")
    logo = _setta_asset_b64("setta-logo-oficial.svg")
    css = (assets / "setta-fechamento.css").read_text(encoding="utf-8")
    navigation = (assets / "setta-fechamento-navigation.js").read_text(encoding="utf-8")
    st.html(
        f'<style id="setta-inv-shell-style">@font-face{{font-family:Outfit;'
        f'src:url(data:font/woff2;base64,{font}) format("woff2");font-weight:100 900;'
        f'font-display:swap}}{css}</style>'
        '<span class="setta-shell-marker" aria-hidden="true"></span>'
    )
    top = (
        '<header class="setta-inv-top" aria-label="Fechamento Mensal Setta">'
        '<button class="setta-drawer-toggle" type="button" aria-expanded="false" '
        'aria-controls="setta-fechamento-sidebar" aria-label="Abrir menu lateral"></button>'
        '<span class="setta-inv-mark">'
        f'<img src="data:image/svg+xml;base64,{logo}" alt="Setta">'
        f'</span><b>{escape(title)}</b><small>Gestão de estoque</small></header>'
        '<div class="setta-inv-route-loader" role="status" aria-live="polite">Atualizando…</div>'
    )
    st.html(top + f'<script>{navigation}</script>', unsafe_allow_javascript=True)
    st.html(
        f'<div class="setta-inv-intro" data-setta-route="{int(route_id)}">'
        f'<div class="setta-inv-breadcrumb">Fechamento mensal / {escape(page_label)}</div>'
        f'<h1>{escape(page_label)}</h1></div>'
    )


@contextmanager
def section_surface(name: str, selection: object):
    """Isolate the changing panel from its stable tab picker."""
    with st.container(key=f"fm_section_panel_{name}"):
        try:
            yield
        finally:
            st.html(
                f'<span class="setta-ready-marker" data-setta-section-ready="{escape(name)}" '
                f'data-setta-section-choice="{escape(str(selection), quote=True)}" aria-hidden="true"></span>'
            )
