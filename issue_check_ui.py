"""OP issue checks in the existing Dashboard layout."""
from __future__ import annotations

import hashlib
import html
import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import central_fechamento_data as central
import issue_check as check
import movement_store
import movements as mv
import master_plan
import operational_status as op_rules
import catalog_types

SOURCE_KEYS = ("relatorio_geral", "endereco")
MASTER_SOURCE_KEY = "for001"
TZ = ZoneInfo("America/Sao_Paulo")
FILTERS = {
    "Todos": None,
    "Com alertas": "divergente",
    "Sem alertas": "sem_alertas",
    "Não consumido · produção": op_rules.NAO_CONSUMIDO_G9,
    "Não consumido · outros endereços": op_rules.NAO_CONSUMIDO_OUTRO,
    "Não consumido · sem saldo": op_rules.NAO_CONSUMIDO_SEM,
    "Separado aguardando conferência": op_rules.SEPARADO_SEM_CONFERENCIA,
    "Aguardando separação": op_rules.AGUARDANDO_SEPARACAO,
    "Baixa maior que a necessidade": op_rules.BAIXA_ACIMA_NECESSIDADE,
}

LABELS = {"op": "OP", "codigo": "Produto", "descricao": "Descrição", "lotes": "Lotes",
          "necessaria": "Qtd necessária", "atendida": "Qtd atendida MES", "separada": "Qtd separada", "conferida": "Qtd conferida",
          "baixada": "Qtd baixada", "saida_bruta": "Saídas", "devolvida": "Entradas / devoluções",
          "pendente": "Qtd pendente baixa", "saldo": "Saldo no lote conferido",
          "saldo_g9_prod": "Saldo G9-PROD", "outros_enderecos": "Outros endereços", "sem_saldo": "Sem cobertura de saldo ou baixa",
          "em_g9_prod": "Pendente com saldo G9-PROD", "status": "Resultado",
          "historico_incompleto": "Histórico incompleto", "saldo_compartilhado": "Saldo compartilhado",
          "conflito_saldo": "Demanda compartilhada maior que saldo", "itens": "Registros",
          "itens_separados": "Separados", "itens_conferidos": "Conferidos",
          "lote": "Lote", "armazem": "Armazém", "endereco": "Endereço", "empenho": "Empenho",
          "tipo_material": "Tipo material",
          "pendente_minima": "Pendente mínima no lote", "pendente_maxima": "Pendente máxima no lote",
          "ops_com_demanda": "OPs com demanda no lote", "demanda_compartilhada_minima": "Demanda mínima de todas as OPs",
          "demanda_compartilhada_maxima": "Demanda máxima de todas as OPs", "linha_origem": "Linha de origem",
          "separacao": "Data de separação", "conferencia": "Data de conferência",
          "responsavel_separacao": "Responsável pela separação", "responsavel_conferencia": "Responsável pela conferência",
          "referencia": "Referência", "fornecedor": "Fornecedor", "pa": "P.A.", "descricao_pa": "Descrição P.A.",
          "reportado": "Reportado", "reporte": "Data de reporte", "pendencia_mes": "Pendente no MES",
          "data": "Data", "tes": "TES", "documento": "Documento", "qtd_entrada": "Entrada", "qtd_saida": "Saída",
          "ae_original": "AE original", "natureza": "Natureza", "arquivo_origem": "Arquivo de origem"}
QUANTITIES = {"necessaria", "atendida", "separada", "conferida", "baixada", "saida_bruta", "devolvida", "pendente", "saldo",
              "saldo_g9_prod", "sem_saldo", "em_g9_prod", "empenho", "pendente_minima", "pendente_maxima",
              "demanda_compartilhada_minima", "demanda_compartilhada_maxima", "pendencia_mes", "qtd_entrada", "qtd_saida"}


def quantity(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    number = f"{float(value):,.6f}".rstrip("0").rstrip(".")
    return number.replace(",", "X").replace(".", ",").replace("X", ".")


def count(value) -> str:
    return f"{int(value):,}".replace(",", ".")


def day(value) -> str:
    try:
        return datetime.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(value or "—")


def _band():
    st.markdown('<div class="section-band"><div class="section-band-kicker">CONFERÊNCIAS</div>'
                '<div class="section-band-title">CONFERÊNCIA DE BAIXAS</div>'
                '<div class="section-band-note">Consulte OPs, confira o consumo do KARDEX e identifique pendências por produto e endereço.</div></div>',
                unsafe_allow_html=True)
    st.markdown("""
    <style>
    .st-key-fm_issue_filters {
      background:#fff;border:1px solid #dce2e9;border-top:4px solid #121a2b;
      border-radius:15px;padding:1.15rem 1.35rem 1rem;margin:1.1rem 0 1.35rem;
      box-shadow:0 6px 20px rgba(15,23,42,.055);
    }
    .fm-issue-filter-heading {
      color:#131e30;font-size:.87rem;font-weight:850;letter-spacing:.035em;
      text-transform:uppercase;line-height:1.4;margin:0 0 .3rem;
    }
    .fm-issue-filter-subtitle {
      color:#66758a;font-size:.73rem;line-height:1.4;
      margin:0 0 1rem;
    }
    .st-key-fm_issue_date_filters {
      margin-top:.85rem;padding:1rem 0 0;
      border-top:1px solid #e6eaf0;
    }
    .fm-issue-date-title {
      color:#344054;font-weight:800;font-size:.72rem;
      letter-spacing:.065em;text-transform:uppercase;margin:0 0 .15rem;
    }
    .fm-issue-date-note {
      font-size:.71rem;color:#7b8797;margin:0 0 .7rem;
    }
    .st-key-fm_issue_filters label {
      font-size:.73rem!important;font-weight:650!important;
      color:#334155!important;
    }
    @media(max-width:640px){
      .st-key-fm_issue_filters {padding:.85rem!important}
    }
    [class*="st-key-fm_issue_op_alert_"] [data-testid="stButton"] button {
      background:#fff3f3!important;border:1px solid #f6c7ca!important;
      border-left:5px solid #ce3c48!important;color:#8b1d2c!important;
    }
    [class*="st-key-fm_issue_op_ok_"] [data-testid="stButton"] button {
      background:#fff!important;border:1px solid #dfe5ec!important;
      border-left:4px solid #111827!important;color:#18202f!important;
    }
    [class*="st-key-fm_issue_op_alert_"] [data-testid="stButton"] button,
    [class*="st-key-fm_issue_op_ok_"] [data-testid="stButton"] button {
      width:100%!important;min-height:47px!important;justify-content:flex-start!important;
      text-align:left!important;white-space:normal!important;border-radius:10px!important;
      padding:.72rem .95rem!important;box-shadow:0 2px 8px rgba(15,23,42,.025)!important;
    }
    [class*="st-key-fm_issue_op_alert_"] [data-testid="stButton"] button > div,
    [class*="st-key-fm_issue_op_ok_"] [data-testid="stButton"] button > div,
    [class*="st-key-fm_issue_op_alert_"] [data-testid="stMarkdownContainer"],
    [class*="st-key-fm_issue_op_ok_"] [data-testid="stMarkdownContainer"] {
      display:flex!important;justify-content:flex-start!important;
      align-items:center!important;width:100%!important;min-width:0!important;
      text-align:left!important;margin:0!important;padding:0!important;
    }
    [class*="st-key-fm_issue_op_alert_"] [data-testid="stButton"] button p,
    [class*="st-key-fm_issue_op_ok_"] [data-testid="stButton"] button p {
      width:100%!important;margin:0!important;padding:0!important;
      text-align:left!important;white-space:normal!important;
      font-size:.77rem!important;font-weight:750!important;line-height:1.6!important;
    }
    [class*="st-key-fm_issue_op_detail_"] {
      background:#fff;border:1px solid #dfe5ec;border-radius:12px;
      padding:1rem 1.05rem;margin:0 0 .65rem;
    }
    .st-key-fm_issue_ops{margin-top:1.15rem}
    /* SETTA | conferência: componentes de consulta visivelmente interativos */
    .st-key-fm_issue_filters {
      border:1px solid #d8dfe8!important;
      border-top:4px solid #141d2c!important;
      border-radius:18px!important;
      background:linear-gradient(180deg,#fff 0%,#fcfdff 100%)!important;
      padding:1.25rem 1.35rem 1.25rem!important;
      box-shadow:0 9px 26px rgba(15,23,42,.06)!important;
    }
    .st-key-fm_issue_filters [data-testid="stTextInput"] [data-baseweb="input"],
    .st-key-fm_issue_filters [data-testid="stDateInput"] [data-baseweb="input"],
    .st-key-fm_issue_filters [data-testid="stSelectbox"] [data-baseweb="select"] > div {
      background:#f8fafc!important;
      border:1.5px solid #c4cfdd!important;
      border-radius:11px!important;
      box-shadow:0 1px 3px rgba(15,23,42,.05)!important;
      min-height:46px!important;transition:border-color .14s,box-shadow .14s!important;
    }
    .st-key-fm_issue_filters [data-testid="stTextInput"] [data-baseweb="input"]:focus-within,
    .st-key-fm_issue_filters [data-testid="stDateInput"] [data-baseweb="input"]:focus-within,
    .st-key-fm_issue_filters [data-testid="stSelectbox"] [data-baseweb="select"] > div:focus-within {
      background:#fff!important;border-color:#273955!important;
      box-shadow:0 0 0 3px rgba(39,57,85,.12)!important;
    }
    .st-key-fm_issue_filters [data-testid="stTextInput"] input,
    .st-key-fm_issue_filters [data-testid="stDateInput"] input {
      color:#101827!important;min-height:42px!important;padding:0 .9rem!important;
      background:transparent!important;font-size:.87rem!important;
      font-weight:550!important;caret-color:#111827!important;
    }
    .st-key-fm_issue_filters [data-testid="stTextInput"] input::placeholder {
      color:#8793a3!important;opacity:1!important;font-weight:450!important;
    }
    .st-key-fm_issue_filters [data-testid="stSelectbox"] [data-baseweb="select"] > div {
      color:#172133!important;font-size:.87rem!important;
    }
    .st-key-fm_issue_filters label {font-size:.73rem!important;letter-spacing:.03em!important}
    .st-key-fm_issue_filters .fm-issue-filter-subtitle{margin-bottom:1.15rem!important}
    .st-key-fm_issue_date_filters {
      border-top:1px solid #e8edf3!important;margin-top:.65rem!important;
      padding-top:1rem!important;
    }
    .st-key-fm_issue_clear_filters button {
      min-height:45px!important;background:#fff!important;color:#26364d!important;
      border:1.5px solid #b8c4d3!important;border-radius:11px!important;
      font-size:.77rem!important;font-weight:800!important;
    }
    .st-key-fm_issue_clear_filters button:hover {
      border-color:#162238!important;background:#f5f7fb!important;
    }
    /* Painel de indicadores: compacto no celular, com 2 colunas em vez de 4 cartões gigantes */
    .st-key-fm_issue_summary .cb-kpi-grid{margin:.85rem 0 1.05rem!important;gap:.7rem!important}
    .st-key-fm_issue_summary .cb-kpi {
      min-height:94px!important;padding:14px 16px!important;
      border:1px solid #e0e6ee!important;border-radius:13px!important;
      box-shadow:0 3px 12px rgba(15,23,42,.035)!important;
    }
    .fm-issue-results-heading{
      margin:1.3rem 0 .75rem;display:flex;gap:12px;
      flex-wrap:wrap;align-items:baseline;justify-content:space-between;
      border-bottom:1px solid #dde4ed;padding-bottom:.65rem;
    }
    .fm-issue-results-heading strong{
      font-size:.96rem;font-weight:850;color:#142035;letter-spacing:.012em;
    }
    .fm-issue-results-heading span{font-size:.73rem;color:#68778b}
    .fm-issue-meta{
      display:grid;grid-template-columns:minmax(210px,2.1fr) repeat(4,minmax(80px,1fr)) minmax(160px,1.3fr);
      gap:.5rem 1.2rem;padding:.65rem .85rem .9rem;
      background:transparent;color:#475569;align-items:start;
    }
    .fm-issue-meta-item{min-width:0;overflow-wrap:anywhere}
    .fm-issue-meta-item b{
      display:block;font-size:.60rem;font-weight:850;color:#66788f;
      letter-spacing:.06em;text-transform:uppercase;margin-bottom:.15rem;
    }
    .fm-issue-meta-item span{display:block;font-size:.74rem;font-weight:650;color:#2c3a4e;line-height:1.4}
    .fm-issue-meta-item .fm-issue-status{
      color:#182638;font-weight:850;
    }
    [class*="st-key-fm_issue_op_alert_"],
    [class*="st-key-fm_issue_op_ok_"] {
      margin:.3rem 0 .65rem!important;border:1px solid #e1e6ed!important;
      border-radius:14px!important;background:#fff!important;
      box-shadow:0 4px 14px rgba(15,23,42,.035)!important;overflow:hidden;
    }
    [class*="st-key-fm_issue_op_alert_"]{border-color:#f2c8cc!important;background:#fffafb!important}
    [class*="st-key-fm_issue_op_alert_"] [data-testid="stButton"] button,
    [class*="st-key-fm_issue_op_ok_"] [data-testid="stButton"] button{
      border-radius:0!important;border-width:0 0 1px 5px!important;
      box-shadow:none!important;padding:.9rem 1rem!important;
      background:transparent!important;min-height:54px!important;
      color:#192538!important;
    }
    [class*="st-key-fm_issue_op_alert_"] [data-testid="stButton"] button {
      border-left-color:#c53a43!important;border-bottom-color:#f5dadd!important;
      color:#8f2932!important;
    }
    [class*="st-key-fm_issue_op_ok_"] [data-testid="stButton"] button {
      border-left-color:#1d2b40!important;border-bottom-color:#ecf0f5!important;
    }
    [class*="st-key-fm_issue_op_alert_"] [data-testid="stButton"] button p,
    [class*="st-key-fm_issue_op_ok_"] [data-testid="stButton"] button p {
      font-size:.78rem!important;font-weight:800!important;line-height:1.45!important;
    }
    .fm-issue-mobile-hint{display:none}
    @media(max-width:900px){
      /* Cabeçalho institucional mais enxuto apenas nesta tela */
      .setta-logo-card{min-height:77px!important;padding:.65rem 1rem!important;margin-bottom:1rem!important}
      .setta-logo-card img{max-height:56px!important;max-width:148px!important}
      .app-title{font-size:1.55rem!important;line-height:1.13!important;letter-spacing:-.035em!important}
      .app-sub{font-size:.72rem!important;line-height:1.35!important;margin-bottom:1.1rem!important}
      .st-key-fm_issue_filters{padding:1rem!important;border-radius:15px!important}
      .st-key-fm_issue_filters [data-testid="stHorizontalBlock"]{gap:.35rem!important}
      .st-key-fm_issue_date_filters [data-testid="stHorizontalBlock"]{display:flex!important;flex-wrap:wrap!important;gap:.65rem!important}
      .st-key-fm_issue_date_filters [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]{
        min-width:calc(50% - .4rem)!important;width:calc(50% - .4rem)!important;
        flex:1 1 calc(50% - .4rem)!important;
      }
      .st-key-fm_issue_date_filters .st-key-fm_issue_clear_filters{width:100%!important}
      .st-key-fm_issue_summary .cb-kpi-grid{
        grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:.6rem!important
      }
      .st-key-fm_issue_summary .cb-kpi{min-height:84px!important;padding:12px!important}
      .st-key-fm_issue_summary .cb-kpi-value{font-size:1.38rem!important}
      .fm-issue-meta{grid-template-columns:repeat(2,minmax(0,1fr));gap:.75rem;padding:.75rem!important}
      .fm-issue-meta-item:first-child{grid-column:1/-1}
      [class*="st-key-fm_issue_op_alert_"] [data-testid="stButton"] button,
      [class*="st-key-fm_issue_op_ok_"] [data-testid="stButton"] button{
        padding:.82rem .75rem!important;min-height:56px!important
      }
      .fm-issue-mobile-hint{display:block;color:#6b7889;font-size:.72rem;margin:.5rem 0}
    }
    </style>""", unsafe_allow_html=True)


def _cards(items):
    parts = ['<div class="cb-kpi-grid">']
    for label, value, note in items:
        parts.append('<div class="cb-kpi"><div class="cb-kpi-label">' + html.escape(label) + '</div>'
                     '<div class="cb-kpi-value">' + html.escape(value) + '</div>'
                     '<div class="cb-kpi-note">' + html.escape(note) + '</div></div>')
    st.markdown("".join(parts) + "</div>", unsafe_allow_html=True)


@st.cache_data(ttl=30, show_spinner=False)
def _states():
    result = central.api_call("bundle_state", {"source_keys": list(SOURCE_KEYS), "derived_keys": []}, timeout=30)
    sources = (result.get("data") or {}).get("sources") or []
    return {row["source_key"]: row for row in sources if row.get("source_key") in SOURCE_KEYS}


@st.cache_resource(max_entries=6, show_spinner=False)
def _source(key: str, version: int, updated_at: str):
    del updated_at
    payload, meta = central.download_preferred_source(key)
    received_version = meta.get("source_version", meta.get("version"))
    if received_version is not None and int(received_version) != version:
        raise RuntimeError("A base foi atualizada durante a leitura. Atualize a conferência para carregar a mesma versão.")
    if str(meta.get("status") or "ATUALIZADO") != "ATUALIZADO":
        raise RuntimeError(f"A fonte {key} ainda não concluiu a atualização no Monitor API.")
    if payload["normalized"]:
        frame = central.normalized_frame(payload["pack"], sheet_contains="Geral" if key == "relatorio_geral" else None)
        rows = check.parse_general(frame) if key == "relatorio_geral" else check.parse_stock(frame)
    else:
        rows = check.parse_raw(payload["raw"], key)
    return rows, {k: v for k, v in meta.items() if k not in ("signed_url", "url")}


@st.cache_resource(max_entries=3, show_spinner=False)
def _master_plan_records(version: int, updated_at: str):
    """Consulta FOR001 somente quando a versão da fonte é alterada."""
    del updated_at
    payload, meta = central.download_preferred_source(MASTER_SOURCE_KEY)
    remote_version = meta.get("source_version", meta.get("version"))
    if remote_version is not None and int(remote_version) != version:
        raise RuntimeError("O Plano Mestre mudou durante a leitura. Atualize a conferência.")
    if payload["normalized"]:
        frame = central.normalized_frame(payload["pack"], sheet_name="PAINEL")
        records = master_plan.parse_frame(frame)
    else:
        records = master_plan.parse_raw(payload["raw"])
    return records, {key: value for key, value in meta.items() if key not in ("signed_url", "url")}


@st.cache_resource(max_entries=3, show_spinner=False)
def _catalog_type_records(version: int, updated: str) -> tuple[dict[str, str], dict]:
    del updated
    payload, meta = central.download_preferred_source("cadastros")
    if payload["normalized"]:
        frame = central.normalized_frame(payload["pack"])
        types = catalog_types.parse_frame(frame)
    else:
        types = catalog_types.parse_raw(payload["raw"])
    actual_version = meta.get("source_version", meta.get("version"))
    if actual_version is not None and int(actual_version) != version:
        raise RuntimeError("CADASTROS alterado durante o carregamento.")
    safe_meta = {key: value for key, value in meta.items() if key not in ("signed_url", "url")}
    safe_meta["version"] = version
    return types, safe_meta


def _optional_catalog_types() -> tuple[dict[str, str], dict]:
    try:
        state = central.source_state_for("cadastros")
        if not state or str(state.get("status") or "").upper() != "ATUALIZADO":
            return {}, {"erro": "CADASTROS indisponível no Monitor de APIs"}
        return _catalog_type_records(
            int(state["version"]), str(state.get("last_update_at") or "")
        )
    except Exception as exc:
        return {}, {"erro": str(exc)}


def _optional_master_plan():
    """Falhas da fonte complementar não impedem a conferência de baixas."""
    try:
        state = central.source_state_for(MASTER_SOURCE_KEY)
        if not state or str(state.get("status") or "") != "ATUALIZADO":
            return {}, {"erro": "FOR001 não disponível no Monitor de APIs."}
        return _master_plan_records(
            int(state["version"]), str(state.get("last_update_at") or "")
        )
    except Exception as exc:
        return {}, {"erro": str(exc)}


@st.cache_data(ttl=120, show_spinner=False)
def _imports():
    return movement_store.list_imports()


@st.cache_resource(max_entries=1, show_spinner=False)
def _history(tokens: tuple):
    entries = [{"chave": key, "atualizado_em": updated, "meta": meta} for key, updated, meta in tokens]
    packs = movement_store.load_history(entries)
    snapshot = mv.history_snapshot(packs)
    return snapshot["rows"], snapshot["coverage"], snapshot["duplicates"]


@st.cache_data(ttl=600, max_entries=3, show_spinner=False)
def _warehouse_options(source_token: tuple) -> list[str]:
    """Devolve só os códigos: filtros não precisam copiar todo o estoque."""
    stock, _ = _source(*source_token)
    return sorted({row["armazem"] for row in stock})


def _source_day(meta: dict) -> str:
    match = re.search(r"(\d{2})[-_](\d{2})[-_](\d{4})", str(meta.get("last_file_name") or ""))
    if match:
        return datetime.strptime("-".join(match.groups()), "%d-%m-%Y").date().isoformat()
    value = str(meta.get("last_update_at") or "")
    if not value:
        raise ValueError("Fonte sem data de atualização. Não é possível fixar a data da conferência.")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TZ).date().isoformat()


@st.cache_resource(max_entries=2, show_spinner=False)
def _audit(source_tokens: tuple, history_tokens: tuple, warehouses: tuple, version: str):
    del version
    sources, metas = {}, {}
    for key, source_version, updated in source_tokens:
        sources[key], metas[key] = _source(key, source_version, updated)
    rows, history_metas, duplicates = _history(history_tokens)
    as_of = min(_source_day(metas[key]) for key in SOURCE_KEYS)
    model = check.reconcile(sources["relatorio_geral"], sources["endereco"], rows,
                            history_metas=history_metas, as_of=as_of, warehouses=warehouses,
                            sources_same_day=len({_source_day(meta) for meta in metas.values()}) == 1,
                            accumulated_history=True)
    model["source_meta"] = metas
    model["history_meta"] = history_metas
    model["duplicates"] = duplicates
    return model


@st.cache_resource(max_entries=3, show_spinner=False)
def _operational_snapshot(source_tokens, history_tokens, warehouses,
                          master_version, catalog_version, rules_version,
                          _model, _records, _types):
    return op_rules.apply(_model, _records, _types)


def _reload():
    _states.clear(); _source.clear(); _warehouse_options.clear()
    _imports.clear(); _history.clear(); _audit.clear()
    _master_plan_records.clear()
    _catalog_type_records.clear()
    _operational_snapshot.clear()
    central.source_state_for.clear()


def _clear_filters():
    st.session_state.fm_issue_search = ""
    st.session_state.fm_issue_filter = "Todos"
    st.session_state.fm_issue_op_status = "Todos os status"
    st.session_state.fm_issue_invoice_start = None
    st.session_state.fm_issue_invoice_end = None
    st.session_state.fm_issue_page = 1


def _table(frame: pd.DataFrame, columns=None, *, key=None):
    if frame.empty:
        st.info("Nenhum registro neste recorte.")
        return
    source = frame.loc[:, [c for c in columns if c in frame]] if columns else frame
    shown = source.copy()
    for col in QUANTITIES.intersection(shown.columns):
        shown[col] = shown[col].map(lambda v: None if v is None or pd.isna(v) else float(v))
    for col in ("data", "separacao", "conferencia", "reporte"):
        if col in shown:
            shown[col] = pd.to_datetime(shown[col], errors="coerce")
    shown = shown.rename(columns=LABELS)
    fmt = {LABELS.get(col, col): quantity for col in QUANTITIES.intersection(source.columns)}
    for col in ("data", "separacao", "conferencia", "reporte"):
        if col in source:
            fmt[LABELS.get(col, col)] = lambda v, field=col: "—" if pd.isna(v) else v.strftime("%d/%m/%Y" if field == "data" else "%d/%m/%Y %H:%M")
    styled = shown.style.format(fmt, na_rep="—")
    if "status" in source:
        colors = ["background-color:#fffbeb;color:#92400e" if bool(r.get("historico_incompleto"))
                  else "background-color:#fef2f2;color:#991b1b" if bool(r.get("divergente")) else ""
                  for r in frame.to_dict("records")]
        styled = styled.apply(lambda _: colors, axis=0, subset=["Resultado"])
    st.dataframe(styled, hide_index=True, width="stretch", key=key,
                 height=min(620, max(120, 77 + 35 * min(len(shown), 100))),
                 column_config={"Descrição": st.column_config.TextColumn(width="large"),
                                "Outros endereços": st.column_config.TextColumn(width="large"),
                                "Resultado": st.column_config.TextColumn(width="large")})


def _filter(frame: pd.DataFrame, query: str, choice: str) -> pd.DataFrame:
    view = frame
    term = mv.normalized(query)
    if term:
        # Pesquisa restrita à OP. Localização de produto continua dentro da OP.
        op = term.removeprefix("OP").strip(" :-/")
        view = view.loc[view["op"].astype(str).str.contains(op, regex=False)]
    condition = FILTERS.get(choice)
    # O filtro seleciona as OPs, preservando todos os seus materiais na
    # conferência, inclusive as linhas normais de uma ordem com alertas.
    if condition == "divergente":
        eligible = view.loc[view["divergente"], "op"]
        view = view.loc[view["op"].isin(eligible)]
    elif condition == "sem_alertas":
        alerted = set(view.loc[view["divergente"], "op"])
        view = view.loc[~view["op"].isin(alerted)]
    elif condition:
        selected = view.loc[
            view["alertas"].map(lambda values: condition in values), "op"
        ]
        view = view.loc[view["op"].isin(selected)]
    return view.copy()


def _billing_date(value):
    """Data digitável (DD/MM/AAAA); vazio significa sem limite."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", text):
            raise ValueError("Informe a data no formato DD/MM/AAAA.")
        return datetime.strptime(text, "%d/%m/%Y").date()
    return pd.Timestamp(value).date()


def _invoice_bounds(raw_start: str, raw_end: str):
    """Não aplica períodos parciais ou invertidos sem avisar ao usuário."""
    try:
        start, end = _billing_date(raw_start), _billing_date(raw_end)
    except (ValueError, TypeError, OverflowError) as exc:
        return (), f"Data de faturamento inválida. Use DD/MM/AAAA. ({exc})"
    if start is not None and end is not None and start > end:
        return (), "A data inicial do faturamento não pode ser posterior à data final."
    return (start, end), ""


def _filter_op_status_invoice(view: pd.DataFrame, ops: pd.DataFrame,
                              status: str, invoice_period) -> pd.DataFrame:
    """Filtra a OP inteira por status e data real do faturamento, inclusiva."""
    selected = ops
    if status != "Todos os status":
        selected = selected.loc[selected["status_op"] == status]
    if invoice_period:
        values = list(invoice_period) if isinstance(invoice_period, (tuple, list)) else [invoice_period]
        dates = [_billing_date(value) for value in values]
        if len(dates) >= 2:
            minimum, maximum = dates[0], dates[1]
        else:
            minimum = maximum = dates[0]
        if minimum is not None or maximum is not None:
            issued = pd.to_datetime(
                selected["data_faturamento"].replace("NI", pd.NA),
                format="%d/%m/%Y", errors="coerce",
            )
            # NaT em TODAS as OPs mantém datetime64[ns]; comparar com
            # datetime.date nesse caso gera InvalidComparison no Pandas.
            # Timestamp evita esse problema sem trocar dia e mês.
            condition = pd.Series(True, index=selected.index)
            if minimum is not None:
                condition &= issued >= pd.Timestamp(minimum)
            if maximum is not None:
                condition &= issued <= pd.Timestamp(maximum)
            selected = selected.loc[condition]
    return view.loc[view["op"].isin(selected["op"])].copy()


def _details(model, item):
    if item["alertas"]:
        message = "\n\n".join(item["alertas"])
        if item["historico_incompleto"]:
            st.warning(message + ". A conclusão depende da atualização do KARDEX.")
        else:
            st.error(message)
    st.markdown("**" + str(item["descricao"]) + "**")
    st.write(f"Conferida: **{quantity(item['conferida'])}** · Baixada líquida: **{quantity(item['baixada'])}** · Pendente: **{quantity(item['pendente'])}**")
    if item["saldo_compartilhado"]:
        st.info("O saldo deste produto e lote também é consultado por outras OPs. A conferência não reserva nem distribui esse saldo automaticamente.")
    source_tab, stock_tab, kardex_tab = st.tabs(["CONFERÊNCIA MES", "LOTES E ENDEREÇOS", "MOVIMENTOS KARDEX"])
    with source_tab:
        rows = pd.DataFrame([r for r in model["general"] if r["item_id"] == item["item_id"]])
        _table(rows, ["codigo", "lote", "necessaria", "atendida", "pendencia_mes", "separacao", "responsavel_separacao",
                      "conferencia", "responsavel_conferencia", "reportado", "reporte", "referencia", "linha_origem"])
    with stock_tab:
        lots = model["lots"].loc[model["lots"]["item_id"] == item["item_id"]]
        st.caption("As baixas do KARDEX são comparadas uma única vez no total do produto na OP. Não há atribuição de baixa a um lote específico.")
        _table(lots, ["lote", "conferida", "saldo", "saldo_g9_prod", "ops_com_demanda"])
        allowed_lots = {r["lote"] for r in model["general"] if r["item_id"] == item["item_id"]}
        addresses = pd.DataFrame([r for r in model["stock"] if r["codigo"] == item["codigo"] and r["lote"] in allowed_lots])
        if item.get("outros_enderecos"):
            st.caption("Endereços alternativos ordenados pela cobertura da quantidade faltante no G9-PROD. Não são reservas de estoque.")
            st.info(item["outros_enderecos"])
        _table(addresses, ["codigo", "lote", "armazem", "endereco", "saldo", "empenho", "linha_origem"])
    with kardex_tab:
        movements = pd.DataFrame([r for r in model["movements"] if r["op"] == item["op"] and r["codigo"] == item["codigo"]])
        if not movements.empty:
            movements = movements.sort_values(["data", "documento"], kind="stable")
        st.caption("Consumo líquido = saídas − devoluções vinculadas à OP e ao produto; TES 999 sem compensação 499/999 conta como consumo. A nova classificação do produto depende do estágio da OP.")
        _table(movements, ["data", "armazem", "tes", "documento", "qtd_entrada", "qtd_saida", "ae_original", "natureza", "arquivo_origem", "linha_origem"])



def _move_issue_page(delta: int, pages: int):
    current = int(st.session_state.get("fm_issue_page", 1))
    st.session_state.fm_issue_page = min(max(current + delta, 1), pages)


def _toggle_issue_op(number: str):
    """Carrega os registros apenas da OP aberta, sem montar 10 tabelas invisíveis."""
    current = st.session_state.get("fm_issue_open_op")
    st.session_state.fm_issue_open_op = None if current == number else number


def _op_metadata(context: dict) -> str:
    """Resumo de faturamento por OP; seguro para renderização em HTML."""
    fields = [
        ("Cliente", context.get("cliente") or "NI"),
        ("Condição", context.get("condicao") or "NI"),
        ("Nota fiscal", context.get("nota_fiscal") or "NI"),
        ("Faturamento", context.get("data_faturamento") or "NI"),
        ("Pátio", context.get("dias_patio") or "NI"),
        ("Status da OP", context.get("status_op") or "NI"),
    ]
    return '<div class="fm-issue-meta">' + "".join(
        '<div class="fm-issue-meta-item"><b>' + html.escape(label)
        + '</b><span' + (' class="fm-issue-status"' if label == "Status da OP" else "")
        + '>' + html.escape(str(value)) + '</span></div>'
        for label, value in fields
    ) + "</div>"


def _ops(model, view, token):
    rank = view.groupby("op")["divergente"].sum().sort_values(ascending=False, kind="stable")
    numbers = rank.index.tolist()
    size = 10
    pages = max(1, math.ceil(len(numbers) / size))
    if st.session_state.get("fm_issue_view_token") != token:
        st.session_state.fm_issue_page = 1
        st.session_state.fm_issue_view_token = token
    page = min(int(st.session_state.get("fm_issue_page", 1)), pages)
    st.session_state.fm_issue_page = page
    info = model["ops"].set_index("op").to_dict("index")
    with st.container(key="fm_issue_ops"):
        for number in numbers[(page - 1) * size:page * size]:
            group = view.loc[view["op"] == number]
            context = info[number]
            total = int(context["itens"])
            separated = int(context["separados"])
            confirmed = int(context["conferidos"])
            discharged = int(context.get("baixados", 0))
            issues = int(context["divergencias"])
            summary = "ORDEM COM ALERTA" if issues else "ORDEM OK"
            title = (
                f"OP {number} | {total} PRODUTOS | {separated} SEPARADOS | "
                f"{confirmed} CONFERIDOS | {discharged} BAIXADOS | "
                f"{issues} ALERTAS — {summary}"
            )
            css_key = "fm_issue_op_alert_" if issues else "fm_issue_op_ok_"
            is_open = st.session_state.get("fm_issue_open_op") == number
            with st.container(key=css_key + number):
                st.button(
                    ("▼ " if is_open else "▶ ") + title,
                    key="fm_issue_select_" + number, use_container_width=True,
                    on_click=_toggle_issue_op, args=(number,),
                )
                st.markdown(_op_metadata(context), unsafe_allow_html=True)
            if is_open:
                with st.container(key="fm_issue_op_detail_" + number):
                    st.caption(f"P.A.: {context['pa'] or '—'} · {context['descricao_pa'] or 'Descrição não informada'}")
                    source_lines = int(context.get("linhas_mes", total))
                    if source_lines != total:
                        st.caption(
                            f"{source_lines} linhas no Relatório Geral do MES "
                            f"consolidadas em {total} produtos distintos nesta OP. "
                            "A tabela mostra uma linha por código; lotes e registros "
                            "originais permanecem disponíveis nas evidências."
                        )
                    if not bool(group.iloc[0]["op_possui_baixa"]):
                        st.caption("Não há consumo líquido identificado no histórico desta OP até a data de referência.")
                    st.markdown(
                        '<div class="fm-issue-mobile-hint">Deslize a tabela horizontalmente para consultar todas as colunas.</div>',
                        unsafe_allow_html=True,
                    )
                    _table(group, ["codigo", "descricao", "lotes", "necessaria", "separada",
                                   "conferida", "baixada", "pendente", "saldo", "saldo_g9_prod",
                                   "outros_enderecos", "status"])
                    index = group.set_index("item_id").to_dict("index")
                    selected = st.selectbox(
                        "DETALHAR MATERIAL E EVIDÊNCIAS",
                        group["item_id"].tolist(), index=None,
                        format_func=lambda value, rows=index: (
                            (rows[value]["codigo"] or "SEM CÓDIGO") + " · " + rows[value]["descricao"]),
                        placeholder="Selecione o material",
                        key=f"fm_issue_detail_{number}_{token}",
                    )
                    if selected:
                        item = group.loc[group["item_id"] == selected].iloc[0].to_dict()
                        _details(model, item)
    if pages > 1:
        previous, counter, following = st.columns([1, 2, 1])
        with previous:
            st.button("← ANTERIOR", key="fm_issue_prev", disabled=page <= 1,
                      on_click=_move_issue_page, args=(-1, pages), use_container_width=True)
        with counter:
            st.caption(f"PÁGINA {page} / {pages}")
        with following:
            st.button("PRÓXIMA →", key="fm_issue_next", disabled=page >= pages,
                      on_click=_move_issue_page, args=(1, pages), use_container_width=True)


def _sources(model):
    rows = []
    for key, label in (("relatorio_geral", "RELATÓRIO GERAL"), ("endereco", "ENDEREÇO")):
        meta = model["source_meta"][key]
        rows.append({"Fonte": label, "Arquivo": meta.get("last_file_name"), "Versão": meta.get("source_version", meta.get("version")),
                     "Atualizada em": central.format_dt(meta.get("last_update_at")),
                     "Registros usados": len(model["general"] if key == "relatorio_geral" else model["stock"])})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if model["history_meta"]:
        st.dataframe(pd.DataFrame([{"Arquivo KARDEX": m["arquivo_nome"], "Armazém": m.get("armazem", "—"),
                                    "Competência": m.get("competencia", "—"), "De": day(m["periodo_inicio"]), "Até": day(m["periodo_fim"]),
                                    "Registros nesta cobertura": m["lancamentos"]} for m in model["history_meta"]]), hide_index=True, width="stretch")
        st.caption("A conferência é acumulada desde o primeiro KARDEX disponível até a referência do MES. Cada armazém mantém cobertura própria; não é necessário que as datas dos arquivos coincidam. Versões mensais substituídas não são somadas novamente.")
    diagnostics = model.get("diagnostico_baixas") or {}
    if diagnostics:
        st.markdown("**Diagnóstico de vínculo das baixas**")
        st.caption(
            f"Movimentos no período: {count(diagnostics.get('movimentos_no_periodo', 0))} · "
            f"Com OP reconhecida: {count(diagnostics.get('movimentos_op_reconhecida', 0))} · "
            f"Saídas de consumo vinculadas: {count(diagnostics.get('consumos_vinculados', 0))} · "
            f"TES 999 de OP não compensadas: {count(diagnostics.get('tes_999_sem_compensacao', 0))} · "
            f"Linhas 499/999 compensadas: {count(diagnostics.get('enderecamentos_compensados', 0))}"
        )
    st.markdown("**Critérios da conferência**")
    st.write("• Conferência identificada pela data de conferência do MES; a quantidade comparada é a atendida nessas linhas. Conferências parciais mantêm a necessária e a pendência visíveis.")
    st.write("• Estoque consultado por produto e lote nos armazéns selecionados. O saldo é a coluna Quantidade; o empenho aparece separado nas evidências.")
    st.write("• Histórico KARDEX acumulado por OP completa da AE e código do produto, desde todas as importações vigentes anteriores à referência. Saídas de meses diferentes são somadas; entradas/devoluções são descontadas. Consumo inclui TES 999 não compensada. Pares 499/999 e TES 499 isolada não comprovam consumo.")
    st.write("• Prioridade da OP: dias de pátio numéricos → FINALIZADO EM PÁTIO; texto FINALIZADO E ENTREGUE → mesmo status; NF ou faturamento → NF EMITIDA; condição FINALIZADO → FINALIZADO; consumo líquido no KARDEX → REPORTADO; conferência → EM CONFERÊNCIA; separação → EM SEPARAÇÃO; caso contrário → AGUARDANDO INÍCIO.")
    st.write("• OP finalizada/faturada/reportada OU com algum consumo: a análise de baixa começa após a separação do produto. Havendo pendência, verifica G9-PROD dos lotes conferidos e endereços alternativos que cubram a falta; produtos ainda não separados não geram alerta.")
    st.write("• OP em andamento SEM nenhuma baixa: acompanha somente etapa do produto (conferido aguardando reporte, separado aguardando conferência ou aguardando separação), sem gerar alertas.")
    st.write("• A conferência de baixas é por OP e código do produto. Saldos por endereço consideram somente lotes efetivamente conferidos; nenhum saldo é reservado automaticamente para outras OPs.")
    st.write("• Baixa maior que a NECESSIDADE gera alerta, exceto para materiais Tipo II ou com necessidade zero e consumo positivo (FLUXO DE BARRAS).")
    st.write("• Produtos Tipo II do CADASTROS recebem 'MATERIAL DE CONSUMO' e não geram alertas, independentemente de separação, conferência ou baixa.")
    st.write("• Outros endereços só são exibidos se o saldo G9-PROD dos lotes conferidos não cobrir toda a quantidade separada.")
    st.write("• Registros repetidos no MES são mantidos e somados. Sobreposição entre arquivos KARDEX é reconhecida sem duplicar movimentos.")
    st.write("• Diferenças de até 0,000001 são tratadas como precisão numérica. Os valores originais permanecem nas evidências.")
    st.caption(f"Referência da conferência: {day(model['as_of'])}. Movimentos posteriores à data da base são desconsiderados ({count(model['movimentos_apos_base'])}).")
    if model["duplicates"]:
        st.caption(f"Movimentos repetidos entre importações reconhecidos: {count(model['duplicates'])}.")
    if model["negative_stock_rows"]:
        st.warning(f"O relatório contém {count(model['negative_stock_rows'])} registros de saldo negativo nos armazéns selecionados. Eles foram mantidos no cálculo.")
    catalog_meta = model.get("catalog_meta") or {}
    st.caption("Fonte Tipo de material: CADASTROS · " + (catalog_meta.get("last_file_name") or catalog_meta.get("erro") or "NI"))
    master_meta = model.get("master_plan_meta") or {}
    st.caption(
        "Plano Mestre FOR001: "
        + (master_meta.get("last_file_name") or master_meta.get("erro") or "NI")
        + " · Dados complementares sem correspondência são exibidos como NI."
    )



@st.fragment
def render_results(model):
    """Filtros e OPs atualizam em fragmento sem reconstruir o aplicativo inteiro."""
    if model.get("status_version") != op_rules.VERSION:
        # Compatibilidade de chamadas diretas e modelos anteriores: nunca
        # apresentar alertas legados na interface operacional.
        model = op_rules.apply(model)
    frame = model["items"]
    period = model["coverage"]
    if not model["history_available"]:
        st.warning("KARDEX não localizado para os armazéns selecionados. Baixas permanecem desconhecidas, não zeradas.")
    elif not model.get("accumulated_history") and not period["fim"]:
        st.warning("KARDEX sem cobertura de datas para os armazéns selecionados.")
    elif (not model.get("accumulated_history") and period["fim"]
          and period["fim"] < model["as_of"]):
        st.warning(f"KARDEX disponível até {day(period['fim'])}; bases de referência em {day(model['as_of'])}. Existem períodos sem cobertura.")
    dates = {_source_day(meta) for meta in model["source_meta"].values()}
    if len(dates) > 1:
        st.warning("Relatório Geral e Endereço com datas diferentes. Considerada a referência mais antiga.")
    if len(period["intervalos"]) > 1 and not model.get("accumulated_history"):
        st.warning("O histórico possui intervalos sem cobertura entre as importações KARDEX.")
    diagnostics = model.get("diagnostico_baixas") or {}
    if model.get("catalog_meta", {}).get("erro"):
        st.warning("CADASTROS indisponível: materiais Tipo II sem separação podem continuar em classificação provisória até atualização da fonte.")
    if (model.get("history_available") and diagnostics.get("movimentos_no_periodo", 0)
            and not diagnostics.get("consumos_vinculados", 0)):
        st.warning(
            "O KARDEX possui movimentações no período, mas nenhuma saída de consumo "
            "foi vinculada a uma OP nesta análise. Confira o conteúdo da coluna "
            "AE original, a data de referência e os armazéns selecionados antes "
            "de interpretar baixas zeradas como ausência de consumo."
        )

    # Compatibilidade com filtros de texto antigos salvos na sessão Streamlit:
    # o novo calendário exige date/None, nunca strings remanescentes.
    for date_key in ("fm_issue_invoice_start", "fm_issue_invoice_end"):
        existing = st.session_state.get(date_key)
        if isinstance(existing, str):
            try:
                st.session_state[date_key] = _billing_date(existing)
            except (ValueError, TypeError, OverflowError):
                st.session_state[date_key] = None

    with st.container(key="fm_issue_filters"):
        st.markdown(
            '<div class="fm-issue-filter-heading">FILTROS DA CONFERÊNCIA</div>'
            '<div class="fm-issue-filter-subtitle">'
            'Localize uma OP ou combine situação, alertas e faturamento.'
            '</div>', unsafe_allow_html=True,
        )
        fop, falert, fstatus = st.columns([1.7, 1.2, 1.3], gap="medium")
        with fop:
            query = st.text_input(
                "LOCALIZAR OP", key="fm_issue_search", placeholder="Número da OP"
            )
        with falert:
            choice = st.selectbox("ALERTAS", list(FILTERS), key="fm_issue_filter")
        with fstatus:
            statuses = ["Todos os status"] + [
                op_rules.FINALIZADO_PATIO, op_rules.FINALIZADO_ENTREGUE,
                op_rules.NF_EMITIDA, op_rules.FINALIZADO, op_rules.REPORTADO,
                op_rules.EM_CONFERENCIA, op_rules.EM_SEPARACAO,
                op_rules.AGUARDANDO_INICIO,
            ]
            selected_status = st.selectbox(
                "STATUS DA OP", statuses, key="fm_issue_op_status"
            )
        with st.container(key="fm_issue_date_filters"):
            st.markdown(
                '<div class="fm-issue-date-title">PERÍODO DE FATURAMENTO</div>'
                '<div class="fm-issue-date-note">'
                'Selecione as datas no calendário. O período filtra somente o faturamento das OPs.'
                '</div>', unsafe_allow_html=True,
            )
            c_from, c_to, c_clear = st.columns([1.25, 1.25, 2], gap="medium")
            with c_from:
                date_from_raw = st.date_input(
                    "DATA INICIAL", value=None, format="DD/MM/YYYY",
                    key="fm_issue_invoice_start",
                    help="Toque no campo ou ícone de calendário para escolher a data inicial.",
                )
            with c_to:
                date_to_raw = st.date_input(
                    "DATA FINAL", value=None, format="DD/MM/YYYY",
                    key="fm_issue_invoice_end",
                    help="Toque no campo ou ícone de calendário para escolher a data final.",
                )
            with c_clear:
                st.button(
                    "LIMPAR FILTROS", on_click=_clear_filters,
                    key="fm_issue_clear_filters", use_container_width=True,
                )

    invoice_period, invoice_error = _invoice_bounds(date_from_raw, date_to_raw)
    if invoice_error:
        st.warning(invoice_error + " O período não foi aplicado.")
    view = _filter_op_status_invoice(
        _filter(frame, query, choice), model["ops"], selected_status, invoice_period
    )
    with st.container(key="fm_issue_summary"):
        _cards([
            ("OPs encontradas", count(view["op"].nunique()), "Ordens no recorte"),
            ("Produtos", count(len(view)), "Códigos distintos por OP"),
            ("Separados", count(view["itens_separados"].gt(0).sum()), "Produtos com separação"),
            ("Conferidos", count(view["itens_conferidos"].gt(0).sum()), "Produtos com conferência"),
        ])
    alerts = view.loc[view["divergente"]]
    st.markdown(
        '<div class="fm-issue-results-heading"><strong>ORDENS DE PRODUÇÃO</strong>'
        f'<span>{count(alerts["op"].nunique())} OPs com alertas · '
        f'{count(len(alerts))} produtos para verificar · '
        f'Referência: {day(model["as_of"])}</span></div>',
        unsafe_allow_html=True,
    )
    token = hashlib.sha256(
        (op_rules.VERSION + query + choice + selected_status + str(invoice_period)
         + str(model["warehouses"]) + str(model["source_meta"]) + str(period)).encode()
    ).hexdigest()[:14]
    if view.empty:
        st.info("Nenhuma OP corresponde à pesquisa ou aos alertas selecionados.")
    else:
        _ops(model, view, token)

    st.markdown("---")
    report_key = hashlib.sha256((
        str(model.get("as_of")) + str(model.get("warehouses"))
        + str(model.get("history_meta")) + str(model.get("source_meta"))
        + op_rules.VERSION + str(model.get("master_plan_meta"))
    ).encode()).hexdigest()
    left, right = st.columns([1, 2])
    with left:
        if st.button("PREPARAR RELATÓRIO COMPLETO", use_container_width=True, key="fm_issue_prepare_report"):
            from issue_check_export import export_complete_report
            with st.spinner("Preparando o Excel completo com todas as OPs e evidências..."):
                data = export_complete_report(model)
            st.session_state["fm_issue_report_ready"] = (report_key, data)
    with right:
        st.caption("Exportação integral: todas as OPs, produtos, alertas, lotes, endereços, movimentações e fontes, sem limitar aos filtros ou à página.")
    prepared = st.session_state.get("fm_issue_report_ready")
    if prepared and prepared[0] == report_key:
        st.download_button(
            "BAIXAR RELATÓRIO COMPLETO · EXCEL",
            data=prepared[1],
            file_name="CONFERENCIA_BAIXAS_SETTA_" + model["as_of"] + ".xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="fm_issue_download_complete", use_container_width=True,
        )
    # st.expander executaria tabelas das fontes mesmo fechado; toggle
    # evita trabalho desnecessário em cada pesquisa ou abertura de OP.
    if st.toggle("FONTES, COBERTURA E CRITÉRIOS TÉCNICOS",
                 value=False, key="fm_issue_show_sources"):
        _sources(model)


def render_issue_check():
    _band()
    try:
        states = _states()
        for key in SOURCE_KEYS:
            if key not in states or not states[key].get("available") or states[key].get("status") != "ATUALIZADO":
                raise RuntimeError(f"Fonte {key} indisponível ou sem atualização concluída no Monitor API.")
        tokens = tuple((key, int(states[key]["version"]), str(states[key].get("last_update_at") or "")) for key in SOURCE_KEYS)
        # Abrangência automática: estoque disponível em ENDEREÇO e qualquer
        # armazém adicional já cadastrado no histórico KARDEX. Sem restringir
        # silenciosamente a conferência ao antigo padrão S2.
        options = _warehouse_options(next(t for t in tokens if t[0] == "endereco"))
        imports = _imports()
        import_warehouses = {
            str((entry.get("meta") or {}).get("armazem") or "").strip()
            for entry in imports
            if (entry.get("meta") or {}).get("armazem")
        }
        chosen = tuple(sorted(set(options) | import_warehouses))
        if not chosen:
            st.warning("Ainda não existem armazéns disponíveis nas fontes ENDEREÇO ou KARDEX.")
            return
        history_tokens = tuple(
            (i["chave"], str(i.get("atualizado_em") or ""), i.get("meta") or {})
            for i in imports
        )
        with st.spinner("Conferindo as OPs, os saldos por lote e as baixas registradas..."):
            model = _audit(tokens, history_tokens, tuple(sorted(chosen)), check.VERSION)
        # A regra operacional usa a fonte FOR001, mas nunca modifica a
        # reconciliação MES/KARDEX cacheada e nunca bloqueia sem a FOR001.
        master_records, master_meta = _optional_master_plan()
        types, catalog_meta = _optional_catalog_types()
        master_version = str(master_meta.get("source_version", master_meta.get("version", ""))) + str(master_meta.get("content_sha256") or master_meta.get("erro") or "")
        catalog_version = str(catalog_meta.get("source_version", catalog_meta.get("version", ""))) + str(catalog_meta.get("content_sha256") or catalog_meta.get("erro") or "")
        model = _operational_snapshot(
            tokens, history_tokens, tuple(sorted(chosen)),
            master_version, catalog_version, op_rules.VERSION,
            model, master_records, types,
        )
        render_results({**model, "master_plan_meta": master_meta, "catalog_meta": catalog_meta})
    except Exception as exc:
        st.error(f"Não foi possível concluir a conferência: {exc}")
        st.info("A ausência de uma fonte não é tratada como saldo zero ou ausência de baixa. Regularize a fonte no Monitor de APIs e recarregue o aplicativo.")
