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
/* SIDEBAR SETTA — BLOCO ÚNICO
   Estrutura: 26 / 20 / 8 / 42 / 2 / 18 / 20 / 8 px */
section[data-testid="stSidebar"]{
  background:#fff!important;
  border-right:1px solid #e8ebf0!important;
  width:260px!important;
  min-width:260px!important;
  max-width:260px!important;
  flex-basis:260px!important;
}
section[data-testid="stSidebar"] .block-container{
  width:260px!important;
  min-width:260px!important;
  max-width:260px!important;
  box-sizing:border-box!important;
  padding:26px 16px!important;
}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{
  gap:0!important;
  row-gap:0!important;
}
section[data-testid="stSidebar"] .sidebar-brand{
  width:100%!important;
  box-sizing:border-box!important;
  background:#f8fafc!important;
  border:1px solid #e5e8ee!important;
  border-radius:12px!important;
  padding:14px 16px!important;
  margin:0!important;
}
section[data-testid="stSidebar"] .sidebar-brand-title{
  margin:0!important;
  padding:0!important;
  font-size:15px!important;
  line-height:18px!important;
  font-weight:800!important;
  color:#111827!important;
  letter-spacing:-.01em!important;
}
section[data-testid="stSidebar"] .sidebar-brand-sub{
  margin:3px 0 0 0!important;
  padding:0!important;
  font-size:12px!important;
  line-height:16px!important;
  font-weight:400!important;
  color:#6b7280!important;
}
section[data-testid="stSidebar"] .sidebar-brand-gap{
  display:block!important;
  width:100%!important;
  height:20px!important;
  min-height:20px!important;
  margin:0!important;
  padding:0!important;
}
section[data-testid="stSidebar"] .sidebar-section-label{
  display:block!important;
  margin:0!important;
  padding:0!important;
  color:#374151!important;
  font-size:12px!important;
  line-height:15px!important;
  font-weight:800!important;
  text-transform:uppercase!important;
  letter-spacing:.055em!important;
}
section[data-testid="stSidebar"] .sidebar-nav-label{
  margin:0!important;
  padding:0!important;
}
section[data-testid="stSidebar"] div[data-testid="stElementContainer"]:has(div[data-testid="stButton"]){
  margin:0 0 2px 0!important;
  padding:0!important;
}
section[data-testid="stSidebar"] .st-key-fm_nav_0{
  margin-top:8px!important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"]{
  width:100%!important;
  margin:0!important;
  padding:0!important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button{
  position:relative!important;
  display:flex!important;
  align-items:center!important;
  justify-content:flex-start!important;
  width:100%!important;
  height:42px!important;
  min-height:42px!important;
  max-height:42px!important;
  margin:0!important;
  padding:0 12px 0 24px!important;
  border-radius:10px!important;
  font-size:13px!important;
  line-height:16px!important;
  font-weight:500!important;
  text-align:left!important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button > div,
section[data-testid="stSidebar"] div[data-testid="stButton"] button p{
  width:100%!important;
  margin:0!important;
  padding:0!important;
  line-height:16px!important;
  text-align:left!important;
  white-space:normal!important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[data-testid="stBaseButton-secondary"]{
  background:transparent!important;
  border:1px solid transparent!important;
  color:#374151!important;
  box-shadow:none!important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[data-testid="stBaseButton-secondary"]:hover{
  background:#f8fafc!important;
  border-color:#e5e7eb!important;
  color:#111827!important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[data-testid="stBaseButton-primary"]{
  background:#111827!important;
  border:1px solid #111827!important;
  color:#fff!important;
  box-shadow:0 5px 14px rgba(17,24,39,.14)!important;
  font-weight:700!important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[data-testid="stBaseButton-primary"] p{
  color:#fff!important;
  font-weight:700!important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[data-testid="stBaseButton-primary"]::before{
  content:"";
  position:absolute;
  left:7px;
  top:50%;
  width:4px;
  height:20px;
  border-radius:999px;
  background:#ef4444;
  transform:translateY(-50%);
}
section[data-testid="stSidebar"] .sidebar-status-section{
  display:block!important;
  width:100%!important;
  margin:0!important;
  padding:0!important;
}
section[data-testid="stSidebar"] .sidebar-status-top-gap{
  display:block!important;
  width:100%!important;
  height:18px!important;
  min-height:18px!important;
  margin:0!important;
  padding:0!important;
}
section[data-testid="stSidebar"] .sidebar-divider{
  display:block!important;
  width:100%!important;
  height:1px!important;
  min-height:1px!important;
  margin:0 0 20px 0!important;
  padding:0!important;
  background:#d1d5db!important;
}
section[data-testid="stSidebar"] .sidebar-status-label{
  display:block!important;
  margin:0 0 8px 0!important;
  padding:0!important;
  line-height:15px!important;
}
section[data-testid="stSidebar"] .sidebar-status-card{
  display:block!important;
  width:100%!important;
  box-sizing:border-box!important;
  margin:0!important;
  padding:12px 14px!important;
  background:#f8fafc!important;
  border:1px solid #e5e8ee!important;
  border-radius:10px!important;
  color:#6b7280!important;
}
section[data-testid="stSidebar"] .sidebar-status-name{
  margin:0!important;
  padding:0!important;
  font-size:11px!important;
  line-height:14px!important;
  font-weight:800!important;
  color:#64748b!important;
  text-transform:uppercase!important;
  letter-spacing:.025em!important;
}
section[data-testid="stSidebar"] .sidebar-status-value{
  margin:4px 0 0 0!important;
  padding:0!important;
  font-size:13px!important;
  line-height:16px!important;
  font-weight:900!important;
  text-transform:uppercase!important;
}
section[data-testid="stSidebar"] .sidebar-status-value.status-ok{color:#16a34a!important}
section[data-testid="stSidebar"] .sidebar-status-value.status-warning{color:#f59e0b!important}
section[data-testid="stSidebar"] .sidebar-status-value.status-error{color:#ef4444!important}
section[data-testid="stSidebar"] .sidebar-status-meta{
  margin:6px 0 0 0!important;
  padding:0!important;
  color:#6b7280!important;
  font-size:11px!important;
  line-height:15px!important;
  text-transform:uppercase!important;
}

.api-status-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.75rem;margin:.15rem 0 1rem}
.api-status-card{position:relative;background:#fff;border:1px solid #dfe3e8;border-radius:11px;padding:.8rem .85rem .75rem;min-height:92px;box-sizing:border-box;box-shadow:0 3px 11px rgba(15,23,42,.035);overflow:hidden}
.api-status-card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--api-accent,#94a3b8)}
.api-status-name{font-size:.66rem;font-weight:900;letter-spacing:.035em;color:#64748b;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.api-status-value{margin-top:.42rem;font-size:.78rem;font-weight:900;color:#111827;text-transform:uppercase}
.api-status-meta{margin-top:.42rem;font-size:.61rem;line-height:1.35;color:#94a3b8}
.api-overview{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.75rem;margin:0 0 .9rem}
.api-overview-card{background:#fff;border:1px solid #dfe3e8;border-radius:11px;padding:.75rem .85rem}
.api-overview-label{font-size:.64rem;font-weight:900;color:#64748b;text-transform:uppercase}
.api-overview-value{margin-top:.28rem;font-size:1.08rem;font-weight:900;color:#111827}
.logo-preview{width:100%;min-height:150px;display:flex;align-items:center;justify-content:center;background:#fff;border:1px solid #e5e8ee;border-radius:12px;padding:1rem;box-sizing:border-box;margin:.5rem 0 1rem}
.logo-preview img{display:block;max-width:205px;max-height:86px;width:auto;height:auto;object-fit:contain}
section[data-testid="stSidebar"] div[role="radiogroup"]{display:flex!important;flex-direction:column!important;gap:.46rem!important;margin:0!important;padding:0!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label{position:relative;width:100%;min-height:40px;display:flex!important;align-items:center!important;gap:0!important;padding:.55rem .72rem .55rem .78rem!important;margin:0!important;border:1px solid #e5e8ee!important;border-radius:9px!important;background:#fff!important;cursor:pointer;box-sizing:border-box!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label>div:first-child,
section[data-testid="stSidebar"] div[role="radiogroup"] label [data-baseweb="radio"],
section[data-testid="stSidebar"] div[role="radiogroup"] label input[type="radio"],
section[data-testid="stSidebar"] div[role="radiogroup"] label svg{display:none!important;position:absolute!important;opacity:0!important;width:0!important;height:0!important;overflow:hidden!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label p{margin:0!important;font-size:.83rem!important;font-weight:600!important;color:#374151!important;white-space:normal!important;line-height:1.25!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label:hover{background:#f8fafc!important;border-color:#d7dce3!important}
section[data-testid="stSidebar"] div[data-testid="stButton"]{margin:0!important}
section[data-testid="stSidebar"] div[data-testid="stButton"] button{
  position:relative!important;
  min-height:42px!important;
  justify-content:flex-start!important;
  text-align:left!important;
  padding:.56rem .72rem .56rem calc(.88rem + 10px)!important;
  border-radius:10px!important;
  font-size:.83rem!important;
  font-weight:600!important;
  line-height:1.2!important;
  width:100%!important
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button > div{
  width:100%!important;
  text-align:left!important;
  justify-content:flex-start!important
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button p{
  width:100%!important;
  margin:0!important;
  text-align:left!important;
  white-space:normal!important
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[data-testid="stBaseButton-secondary"]{
  background:transparent!important;
  border:1px solid transparent!important;
  color:#374151!important;
  box-shadow:none!important
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[data-testid="stBaseButton-secondary"]:hover{
  background:#f8fafc!important;
  border-color:#e5e7eb!important;
  color:#111827!important
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[data-testid="stBaseButton-primary"]{
  background:#111827!important;
  border:1px solid #111827!important;
  color:#fff!important;
  box-shadow:0 5px 14px rgba(17,24,39,.14)!important;
  font-weight:700!important
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[data-testid="stBaseButton-primary"] p{
  color:#fff!important;
  font-weight:700!important
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[data-testid="stBaseButton-primary"]::before{
  content:"";
  position:absolute;
  left:.42rem;
  top:50%;
  width:4px;
  height:20px;
  border-radius:999px;
  background:#ef4444;
  transform:translateY(-50%)
}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked){background:#111827!important;border-color:#111827!important;box-shadow:0 5px 14px rgba(17,24,39,.14)!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked)::before{content:"";position:absolute;left:.42rem;top:50%;width:4px;height:20px;border-radius:999px;background:#ef4444;transform:translateY(-50%)}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p{color:#fff!important;font-weight:700!important}

[data-testid="stAppViewContainer"] > .main,
[data-testid="stAppViewContainer"] .main,
[data-testid="stMain"],
.stMain{width:100%!important;max-width:100%!important;margin-left:0!important;margin-right:0!important}
[data-testid="stAppViewContainer"] .main .block-container,
[data-testid="stMain"] .block-container,
.stMain .block-container{width:100%!important;max-width:100%!important;margin-left:0!important;margin-right:0!important}
section[data-testid="stSidebar"][aria-expanded="false"]{width:0!important;min-width:0!important;max-width:0!important;flex-basis:0!important}
.setta-logo-card{width:100%!important;min-height:128px!important;display:flex!important;align-items:center!important;justify-content:center!important;background:#fff!important;border:1px solid #e5e8ee!important;border-radius:16px!important;box-shadow:0 4px 14px rgba(24,39,75,.08)!important;box-sizing:border-box!important;margin:0 0 2.55rem 0!important;padding:1.1rem 2rem!important}
.setta-logo-card img{display:block!important;width:auto!important;height:auto!important;max-width:205px!important;max-height:86px!important;object-fit:contain!important}
.app-title{margin:0!important;padding:0!important;font-size:2.55rem!important;line-height:1.08!important;font-weight:800!important;letter-spacing:-.04em!important;color:#050505!important}
.app-sub{margin-top:.72rem!important;margin-bottom:1.65rem!important;color:#4f5661!important;font-size:.94rem!important;line-height:1.35!important}
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
.month-toolbar{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:.85rem}
.inventory-box{background:#fff;border:1px solid #dfe3e8;border-radius:14px;box-shadow:0 4px 16px rgba(15,23,42,.05);overflow:hidden}
.inventory-box-title{padding:.82rem 1rem;background:#e5e7eb;border-bottom:1px solid #d1d5db;text-align:center;font-size:.92rem;font-weight:900;color:#111827;letter-spacing:.025em;text-transform:uppercase}
.inventory-row{display:grid;grid-template-columns:minmax(150px,1.55fr) minmax(112px,.85fr);border-bottom:1px solid #e5e7eb;min-height:43px}
.inventory-row:last-child{border-bottom:0}
.inventory-label{display:flex;align-items:center;padding:.62rem .85rem;background:#f3f4f6;color:#111827;font-size:.76rem;font-weight:800;text-transform:uppercase}
.inventory-value{display:flex;align-items:center;justify-content:flex-end;padding:.62rem .85rem;color:#111827;font-size:.8rem;font-weight:800;background:#fff}
.inventory-value.negative{color:#b91c1c}
.inventory-value.positive{color:#166534}
.inventory-spacer{height:12px;background:#f4f7fb}
.mov-grid{display:grid;grid-template-columns:1.45fr .86fr .86fr;gap:.75rem;align-items:stretch}
.mov-col{background:#fff;border:1px solid #dfe3e8;border-radius:12px;overflow:hidden}
.mov-head{padding:.72rem .8rem;background:#e5e7eb;text-align:center;font-weight:900;font-size:.79rem;color:#111827;text-transform:uppercase;border-bottom:1px solid #d1d5db}
.mov-row{display:grid;grid-template-columns:minmax(130px,1.5fr) minmax(105px,.9fr);border-bottom:1px solid #e5e7eb;min-height:42px}
.mov-row:last-child{border-bottom:0}
.mov-label{display:flex;align-items:center;padding:.58rem .7rem;background:#f3f4f6;font-size:.71rem;font-weight:800;color:#111827;text-transform:uppercase}
.mov-value{display:flex;align-items:center;justify-content:flex-end;padding:.58rem .7rem;font-size:.75rem;font-weight:800;background:#fff;color:#111827}
.mov-value.negative{color:#b91c1c}
.mov-value.positive{color:#166534}
.history-title{margin-top:1.4rem!important}
.topic-divider{height:1px;background:#cbd5e1;margin:1.7rem 0 1.15rem;width:100%}
.section-band{margin:0 0 .95rem;padding:.82rem 1rem;background:#fff;border:1px solid #e5e8ee;border-left:5px solid #111827;border-radius:12px;box-shadow:0 3px 12px rgba(15,23,42,.035)}
.section-band-kicker{font-size:.66rem;font-weight:900;letter-spacing:.085em;text-transform:uppercase;color:#ef4444;margin-bottom:.18rem}
.section-band-title{font-size:1.08rem;font-weight:900;color:#111827;letter-spacing:-.015em;line-height:1.2;text-transform:uppercase}
.section-band-note{margin-top:.26rem;color:#667085;font-size:.78rem;line-height:1.45}
.summary-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem;margin-bottom:.25rem}
.cb-kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.85rem;margin:.25rem 0 1rem}
.cb-compact-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.55rem;margin:.55rem 0 .55rem}
.cb-compact-stat{display:flex;align-items:center;justify-content:space-between;gap:.75rem;min-height:52px;padding:.55rem .75rem;background:#fff;border:1px solid #dfe3e8;border-radius:10px}
.cb-compact-stat span{font-size:.67rem;font-weight:800;letter-spacing:.035em;color:#64748b}
.cb-compact-stat strong{font-size:1.32rem;line-height:1;color:#111827}
.cb-compact-stat-final{border-left:4px solid #111827}
.cb-tight-divider{margin:.85rem 0 .7rem!important}
.cb-compact-section-title{font-size:.82rem;font-weight:900;letter-spacing:.035em;color:#111827;margin:0 0 .45rem;text-transform:uppercase}
.cb-kpi{position:relative;background:#fff;border:1px solid #dfe3e8;border-radius:12px;box-shadow:0 3px 12px rgba(15,23,42,.04);padding:.85rem 1rem;overflow:hidden}
.cb-kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--cb-accent,#111827)}
.cb-kpi-label{font-size:.66rem;font-weight:900;letter-spacing:.04em;text-transform:uppercase;color:#64748b;margin-bottom:.42rem}
.cb-kpi-value{font-size:1.25rem;font-weight:900;letter-spacing:-.02em;color:#111827}
.cb-kpi-note{margin-top:.3rem;font-size:.68rem;color:#94a3b8}
.cb-source-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.85rem;margin:.3rem 0 1rem}
.cb-source-card{background:#fff;border:1px solid #dfe3e8;border-radius:12px;padding:.95rem 1rem;box-shadow:0 3px 12px rgba(15,23,42,.035)}
.cb-source-title{font-size:.8rem;font-weight:900;color:#111827;text-transform:uppercase;margin-bottom:.3rem}
.cb-source-text{font-size:.74rem;color:#667085;line-height:1.45}
.cb-source-tag{display:inline-flex;margin-top:.55rem;padding:.22rem .46rem;border-radius:999px;background:#f1f5f9;color:#475569;font-size:.64rem;font-weight:800}
.cb-inline-title{font-size:.92rem;font-weight:900;color:#111827;letter-spacing:-.01em;text-transform:uppercase;line-height:1.2;margin:.25rem 0 .35rem}
.cb-title-inline{display:flex;align-items:center;gap:.45rem;width:max-content;max-width:100%;margin:0 0 .45rem}
.cb-title-main{margin:0!important}
.cb-info-wrap{position:relative;display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;outline:none}
.cb-info-icon{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:999px;border:1px solid #cbd5e1;background:#fff;color:#64748b;font-size:.7rem;font-weight:900;line-height:1;cursor:help;user-select:none}
.cb-info-wrap:hover .cb-info-icon,.cb-info-wrap:focus .cb-info-icon{border-color:#94a3b8;color:#111827;background:#f8fafc}
.cb-info-tooltip{position:absolute;left:50%;top:calc(100% + 9px);transform:translateX(-50%) translateY(-3px);width:360px;max-width:min(360px,80vw);padding:.8rem .9rem;background:#111827;color:#fff;border-radius:10px;box-shadow:0 10px 28px rgba(15,23,42,.22);opacity:0;visibility:hidden;pointer-events:none;z-index:9999;transition:opacity .14s ease,transform .14s ease;text-align:left}
.cb-info-tooltip::before{content:"";position:absolute;left:50%;top:-5px;width:10px;height:10px;background:#111827;transform:translateX(-50%) rotate(45deg)}
.cb-info-tooltip strong{display:block;font-size:.67rem;letter-spacing:.06em;margin-bottom:.35rem}
.cb-info-tooltip span{display:block;font-size:.72rem;line-height:1.5;color:#e5e7eb}
.cb-info-wrap:hover .cb-info-tooltip,.cb-info-wrap:focus .cb-info-tooltip{opacity:1;visibility:visible;transform:translateX(-50%) translateY(0)}
div[data-testid="stPopover"] button{min-height:28px!important;width:28px!important;height:28px!important;padding:0!important;border-radius:999px!important;border:1px solid #d8dde5!important;background:#fff!important;color:#64748b!important;font-size:.92rem!important;font-weight:800!important;box-shadow:none!important}
div[data-testid="stPopover"] button:hover{background:#f8fafc!important;border-color:#cbd5e1!important;color:#111827!important}
.summary-card{position:relative;background:#fff;border:1px solid #dfe3e8;border-radius:14px;box-shadow:0 4px 16px rgba(15,23,42,.05);padding:1rem 1.15rem 1.05rem;overflow:hidden}
.summary-card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;background:#111827}
.summary-card-label{font-size:.7rem;font-weight:900;letter-spacing:.045em;text-transform:uppercase;color:#64748b;margin-bottom:.55rem}
.summary-card-value{font-size:1.65rem;font-weight:900;letter-spacing:-.025em;color:#111827;line-height:1.05}
.summary-card-value.negative{color:#b91c1c}
.summary-card-value.positive{color:#166534}
.tp-table{background:#fff;border:1px solid #dfe3e8;border-radius:14px;box-shadow:0 4px 16px rgba(15,23,42,.045);overflow:hidden}
.tp-table-row{display:grid;grid-template-columns:.72fr 1fr 1fr;min-height:44px;border-bottom:1px solid #e5e7eb;align-items:stretch}
.tp-table-row:last-child{border-bottom:0}
.tp-table-head{background:#e5e7eb;min-height:42px}
.tp-table-cell{display:flex;align-items:center;padding:.65rem .78rem;border-right:1px solid #e5e7eb;color:#374151;font-size:.76rem}
.tp-table-cell:last-child{border-right:0}
.tp-table-head .tp-table-cell{font-size:.7rem;font-weight:900;text-transform:uppercase;letter-spacing:.035em;color:#111827;justify-content:center}
.tp-table-type{font-weight:900;color:#111827;background:#f8fafc}
.tp-table-money{justify-content:flex-end;font-weight:800;color:#111827}
.tp-table-total .tp-table-cell{background:#eef0f3;font-weight:900}
.history-wrap{background:#fff;border:1px solid #dfe3e8;border-radius:14px;box-shadow:0 4px 16px rgba(15,23,42,.045);overflow:hidden}
.history-row{display:grid;grid-template-columns:1.15fr 1fr 1fr 1fr .9fr;min-height:44px;border-bottom:1px solid #e5e7eb;align-items:stretch}
.history-row:last-child{border-bottom:0}
.history-head{background:#e5e7eb;min-height:42px}
.history-cell{display:flex;align-items:center;padding:.65rem .78rem;border-right:1px solid #e5e7eb;color:#374151;font-size:.76rem}
.history-cell:last-child{border-right:0}
.history-head .history-cell{font-size:.7rem;font-weight:900;text-transform:uppercase;letter-spacing:.035em;color:#111827}
.history-month{font-weight:800;color:#111827}
.history-money{justify-content:flex-end;font-weight:750;color:#111827}
.history-money.negative{color:#b91c1c}
.history-money.positive{color:#166534}
.validation-badge{display:inline-flex;align-items:center;justify-content:center;min-width:86px;padding:.28rem .5rem;border-radius:999px;font-size:.67rem;font-weight:900;letter-spacing:.02em;white-space:nowrap}
.validation-ok{background:#dcfce7;color:#166534;border:1px solid #bbf7d0}
.validation-pending{background:#fee2e2;color:#b91c1c;border:1px solid #fecaca}
.validation-note{margin-top:.7rem;padding:.72rem .85rem;border:1px solid #fde68a;background:#fffbeb;border-radius:10px;color:#92400e;font-size:.75rem;line-height:1.45}
.module-hero{background:#fff;border:1px solid #e5e8ee;border-radius:14px;padding:1.05rem 1.15rem;box-shadow:0 3px 12px rgba(15,23,42,.04);margin-bottom:1rem}
.module-hero strong{display:block;color:#111827;font-size:.96rem;margin-bottom:.3rem}
.module-hero span{color:#667085;font-size:.84rem;line-height:1.55}
.footer{text-align:center;color:#9298a1;font-size:.72rem;padding-top:1.2rem}
@media (max-width:1100px){
.api-status-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}
.api-overview{grid-template-columns:repeat(2,minmax(0,1fr))!important}
}
@media (max-width:900px){
.block-container{padding-top:2rem!important;padding-left:1rem!important;padding-right:1rem!important;padding-bottom:2rem!important}
.setta-logo-card{min-height:105px;margin-bottom:1.8rem;padding:.9rem 1rem}
.setta-logo-card img{max-width:170px;max-height:72px}
.app-title{font-size:2rem!important}
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
.tp-table-cell::before{content:attr(data-label);display:inline-block;min-width:115px;margin-right:.65rem;font-size:.65rem;font-weight:900;text-transform:uppercase;color:#64748b}
.history-row{grid-template-columns:1fr!important}
.history-head{display:none!important}
.history-cell{border-right:0!important;border-bottom:1px solid #eef0f3;justify-content:flex-start!important}
.history-cell::before{content:attr(data-label);display:inline-block;min-width:118px;margin-right:.65rem;font-size:.65rem;font-weight:900;text-transform:uppercase;color:#64748b}
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
