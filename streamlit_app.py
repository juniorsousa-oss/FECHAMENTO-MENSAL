from __future__ import annotations

import base64
import html
import io
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

import inventory_db as db
import central_fechamento_data as central_data
from report_parser import parse_inventory_report, parse_inventory_balance_report
from cb_parser import (
    find_bar_catalog_matches,
    normalize_bar_identifier,
    normalize_code,
    parse_barramentos_excel,
    parse_cadastros,
    parse_chapas_eml,
    parse_interno_excel,
    resolve_chapa_rows,
)
from ui import inject_css, logo_html

ROOT = Path(__file__).parent
FAVICON_FILE = ROOT / "config" / "favicon_setta.b64"
TZ = ZoneInfo("America/Sao_Paulo")

CONNECTED_API_SOURCE_KEYS = {
    "analitico",
    "cadastros",
}

DEFAULT_CONFIG = {
    "title": "FECHAMENTO MENSAL",
    "subtitle": "Inventário • Conferências • Baixas • Movimentações • Fechamento",
    "sidebar_title": "FECHAMENTO MENSAL",
    "sidebar_subtitle": "Análises de inventário",
    "menu_labels": {
        "Dashboard": "DASHBOARD",
        "Conferência de chapas e barramentos": "CONFERÊNCIA DE CHAPAS E BARRAMENTOS",
        "Conferência de baixas": "CONFERÊNCIA DE BAIXAS",
        "Análise de movimentações": "ANÁLISE DE MOVIMENTAÇÕES",
        "Configurações": "CONFIGURAÇÕES",
    },
}

PAGES = [
    "Dashboard",
    "Conferência de chapas e barramentos",
    "Conferência de baixas",
    "Análise de movimentações",
    "Configurações",
]

MONTHS_PT = {
    1: "JANEIRO",
    2: "FEVEREIRO",
    3: "MARÇO",
    4: "ABRIL",
    5: "MAIO",
    6: "JUNHO",
    7: "JULHO",
    8: "AGOSTO",
    9: "SETEMBRO",
    10: "OUTUBRO",
    11: "NOVEMBRO",
    12: "DEZEMBRO",
}




CB_SOURCE_LABELS = {
    "CHAPAS_EMAIL": "CHAPAS · E-MAIL",
    "BARRAMENTOS_EXCEL": "BARRAMENTOS · EXCEL",
    "INTERNO_EXCEL": "ALMOXARIFADO · BARRAS",
    "INTERNO_MANUAL": "ALMOXARIFADO · MANUAL",
}


try:
    GLOBAL_VISUAL_CONFIG = central_data.load_visual_config()
except Exception:
    GLOBAL_VISUAL_CONFIG = {}


def browser_icon():
    try:
        raw = central_data.favicon_bytes(GLOBAL_VISUAL_CONFIG)
        if raw:
            image = Image.open(io.BytesIO(raw))
            image.load()
            return image
    except Exception:
        pass

    try:
        raw = base64.b64decode(
            FAVICON_FILE.read_text(encoding="utf-8").strip(),
            validate=True,
        )
        image = Image.open(io.BytesIO(raw))
        image.load()
        return image
    except Exception:
        return "📄"


st.set_page_config(
    page_title="FECHAMENTO MENSAL | SETTA",
    page_icon=browser_icon(),
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()


@st.cache_data(show_spinner=False, max_entries=4)
def cached_parse_cadastros(raw: bytes, file_name: str) -> dict:
    return parse_cadastros(raw, file_name)


@st.cache_data(show_spinner=False)
def build_almox_barras_model() -> bytes:
    output = io.BytesIO()
    model = pd.DataFrame(
        columns=["BARRAMENTO", "QUANTIDADE"]
    )
    with pd.ExcelWriter(
        output,
        engine="openpyxl",
    ) as writer:
        model.to_excel(
            writer,
            index=False,
            sheet_name="CONTAGEM",
        )

        ws = writer.book["CONTAGEM"]
        ws.freeze_panes = "A2"
        ws.column_dimensions["A"].width = 18
        ws.column_dimensions["B"].width = 18

    output.seek(0)
    return output.getvalue()


@st.cache_data(show_spinner=False, ttl=30)
def load_api_sources() -> list[dict]:
    sources = db.list_data_sources()
    return [
        row
        for row in sources
        if str(row.get("source_key") or "").strip().lower()
        in CONNECTED_API_SOURCE_KEYS
    ]



def month_start(value: date | datetime) -> date:
    return date(value.year, value.month, 1)


def previous_month(value: date) -> date:
    if value.month == 1:
        return date(value.year - 1, 12, 1)
    return date(value.year, value.month - 1, 1)


def closing_date(competencia: date) -> date:
    """Último dia do mês da competência, usado como data efetiva do fechamento."""
    if competencia.month == 12:
        next_month = date(competencia.year + 1, 1, 1)
    else:
        next_month = date(competencia.year, competencia.month + 1, 1)
    return next_month - timedelta(days=1)


def competencia_from_source_update(meta: dict) -> date:
    """A fonte atualizada no mês seguinte pertence ao fechamento anterior."""
    raw = str((meta or {}).get("last_update_at") or "").strip()
    if raw:
        try:
            updated_at = datetime.fromisoformat(
                raw.replace("Z", "+00:00")
            )
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=TZ)
            local_date = updated_at.astimezone(TZ).date()
            return previous_month(month_start(local_date))
        except Exception:
            pass

    return previous_month(
        month_start(datetime.now(TZ).date())
    )


def month_label(value: date) -> str:
    return f"{MONTHS_PT[value.month]}/{value.year}"


def money_br(value: object) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except Exception:
        return "—"
    sign = "-" if number < 0 else ""
    text = f"{abs(number):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sign}R$ {text}"


def delta_class(value: float | None) -> str:
    if value is None:
        return ""
    if value < 0:
        return " negative"
    if value > 0:
        return " positive"
    return ""


def stock_card(title: str, initial: float | None, final: float | None) -> str:
    summary = None if initial is None or final is None else final - initial
    return (
        '<div class="inventory-box">'
        f'<div class="inventory-box-title">{title}</div>'
        '<div class="inventory-row">'
        '<div class="inventory-label">Inicial</div>'
        f'<div class="inventory-value">{money_br(initial)}</div>'
        '</div>'
        '<div class="inventory-row">'
        '<div class="inventory-label">Final</div>'
        f'<div class="inventory-value">{money_br(final)}</div>'
        '</div>'
        '<div class="inventory-row">'
        '<div class="inventory-label">Resumo</div>'
        f'<div class="inventory-value{delta_class(summary)}">{money_br(summary)}</div>'
        '</div>'
        '</div>'
    )


def section_band(kicker: str, title: str, note: str) -> None:
    st.markdown(
        f"""
        <div class="section-band">
            <div class="section-band-kicker">{kicker}</div>
            <div class="section-band-title">{title}</div>
            <div class="section-band-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )



@st.cache_data(show_spinner=False, ttl=60, max_entries=4)
def load_central_analitico(version_token: str) -> tuple[dict, dict, dict]:
    del version_token
    raw, meta = central_data.download_analitico()
    file_name = str(meta.get("last_file_name") or "ANALITICO.xltx")
    parsed = parse_inventory_report(raw, file_name)
    balance = parse_inventory_balance_report(raw, file_name)
    return parsed, balance, meta


@st.cache_data(show_spinner=False, ttl=300, max_entries=4)
def load_central_cadastros(
    version_token: str,
) -> tuple[dict, dict]:
    del version_token
    raw, meta = central_data.download_source("cadastros")
    file_name = str(
        meta.get("last_file_name") or "CADASTROS.xltx"
    )
    parsed = parse_cadastros(raw, file_name)
    return parsed, meta


def build_preview_summaries(competencia: date, rows: list[dict]) -> list[dict]:
    if not rows:
        return []

    frame = pd.DataFrame(rows).copy()
    frame["valor_estoque"] = pd.to_numeric(
        frame.get("valor_estoque"), errors="coerce"
    ).fillna(0.0)
    frame["armz"] = frame.get("armz", "").fillna("").astype(str).str.strip()
    frame["tp"] = frame.get("tp", "").fillna("").astype(str).str.strip()
    key = competencia.replace(day=1).isoformat()

    output = [
        {
            "competencia": key,
            "dimensao": "TOTAL",
            "chave": "TOTAL",
            "armz": None,
            "tp": None,
            "valor_total": float(frame["valor_estoque"].sum()),
            "itens": int(len(frame)),
        }
    ]

    for armz, group in frame.groupby("armz", dropna=False):
        if not str(armz).strip():
            continue
        output.append(
            {
                "competencia": key,
                "dimensao": "ARMZ",
                "chave": f"ARMZ:{armz}",
                "armz": str(armz),
                "tp": None,
                "valor_total": float(group["valor_estoque"].sum()),
                "itens": int(len(group)),
            }
        )

    for tp, group in frame.groupby("tp", dropna=False):
        if not str(tp).strip():
            continue
        output.append(
            {
                "competencia": key,
                "dimensao": "TP",
                "chave": f"TP:{tp}",
                "armz": None,
                "tp": str(tp),
                "valor_total": float(group["valor_estoque"].sum()),
                "itens": int(len(group)),
            }
        )

    for (armz, tp), group in frame.groupby(["armz", "tp"], dropna=False):
        if not str(armz).strip() or not str(tp).strip():
            continue
        output.append(
            {
                "competencia": key,
                "dimensao": "ARMZ_TP",
                "chave": f"ARMZ_TP:{armz}|{tp}",
                "armz": str(armz),
                "tp": str(tp),
                "valor_total": float(group["valor_estoque"].sum()),
                "itens": int(len(group)),
            }
        )

    return output


def central_analitico_context(force: bool = False) -> dict:
    try:
        meta = central_data.source_state()
    except Exception as exc:
        return {"available": False, "error": str(exc)}

    if not meta or not bool(meta.get("available", True)):
        return {"available": False, "meta": meta, "error": "ANALÍTICO indisponível."}

    token = central_data.source_token(meta)
    if force:
        load_central_analitico.clear()

    try:
        parsed, balance, download_meta = load_central_analitico(token)
        status = "ATUALIZADO" if not parsed.get("errors") else "ATENÇÃO"
        sync = central_data.sync_state()
        if (
            str(sync.get("version_token") or "") != token
            or str(sync.get("status") or "").upper() != status
        ):
            central_data.commit_sync(
                token,
                meta.get("last_update_at"),
                int(parsed.get("valid_rows") or 0),
                status=status,
                error_message=(
                    None
                    if status == "ATUALIZADO"
                    else f"{int(parsed.get('invalid_rows') or 0)} inconsistência(s)"
                ),
            )
        return {
            "available": True,
            "meta": {**meta, **download_meta},
            "token": token,
            "parsed": parsed,
            "balance": balance,
            "status": status,
        }
    except Exception as exc:
        try:
            central_data.commit_sync(
                token,
                meta.get("last_update_at"),
                0,
                status="ERRO",
                error_message=str(exc)[:1500],
            )
        except Exception:
            pass
        return {
            "available": False,
            "meta": meta,
            "token": token,
            "status": "ERRO",
            "error": str(exc),
        }


def central_cadastros_context(
    force: bool = False,
) -> dict:
    try:
        meta = central_data.source_state_for("cadastros")
    except Exception as exc:
        return {
            "available": False,
            "status": "ERRO",
            "error": str(exc),
        }

    if not meta or not bool(meta.get("available", True)):
        return {
            "available": False,
            "meta": meta,
            "status": "INDISPONÍVEL",
            "error": "CADASTROS indisponível na Central de Dados.",
        }

    token = central_data.source_token(meta)

    if force:
        load_central_cadastros.clear()

    try:
        parsed, download_meta = load_central_cadastros(
            token
        )
        sync = central_data.sync_state_for("cadastros")
        needs_sync = (
            force
            or str(sync.get("version_token") or "") != token
            or str(sync.get("status") or "").upper()
            != "ATUALIZADO"
        )

        if needs_sync:
            db.sync_cb_catalog(parsed["candidates"])
            central_data.commit_source_sync(
                "cadastros",
                token,
                meta.get("last_update_at"),
                int(parsed.get("total_candidates") or 0),
                status="ATUALIZADO",
            )

        return {
            "available": True,
            "meta": {**meta, **download_meta},
            "token": token,
            "parsed": parsed,
            "status": "ATUALIZADO",
            "synchronized": needs_sync,
        }
    except Exception as exc:
        try:
            central_data.commit_source_sync(
                "cadastros",
                token,
                meta.get("last_update_at"),
                0,
                status="ERRO",
                error_message=str(exc)[:1500],
            )
        except Exception:
            pass

        return {
            "available": False,
            "meta": meta,
            "token": token,
            "status": "ERRO",
            "error": str(exc),
        }


def render_central_status(context: dict) -> None:
    meta = context.get("meta") or {}
    parsed = context.get("parsed") or {}
    status = str(context.get("status") or "INDISPONÍVEL").upper()
    cols = st.columns(4)
    cols[0].metric("FONTE", "ANALÍTICO")
    cols[1].metric("STATUS", status)
    cols[2].metric("VERSÃO", f"V{int(meta.get('version') or 0)}")
    cols[3].metric(
        "REGISTROS",
        f"{int(parsed.get('valid_rows') or meta.get('rows_count') or 0):,}".replace(",", "."),
    )
    st.caption(
        "ÚLTIMA ATUALIZAÇÃO · "
        + central_data.format_dt(meta.get("last_update_at"))
    )


def render_manual_contingency(imports_by_month: dict[str, dict]) -> None:
    with st.expander("CONTINGÊNCIA MANUAL", expanded=False):
        col_a, col_b = st.columns([0.8, 1.8])
        with col_a:
            competencia_input = st.date_input(
                "COMPETÊNCIA",
                value=previous_month(
                    month_start(datetime.now(TZ).date())
                ),
                format="DD/MM/YYYY",
                key="fm_contingencia_competencia",
            )
            competencia_input = month_start(competencia_input)
        with col_b:
            uploaded = st.file_uploader(
                "RELATÓRIO ANALÍTICO",
                type=["xlsx", "xltx"],
                accept_multiple_files=False,
                key="fm_contingencia_analitico",
            )

        if uploaded is None:
            return

        try:
            parsed = parse_inventory_report(uploaded.getvalue(), uploaded.name)
        except Exception as exc:
            st.error(f"RELATÓRIO INVÁLIDO: {exc}")
            return

        m1, m2, m3 = st.columns(3)
        m1.metric("LINHAS VÁLIDAS", f"{parsed['valid_rows']:,}".replace(",", "."))
        m2.metric("ERROS", parsed["invalid_rows"])
        m3.metric("VALOR", money_br(parsed["total_value"]))

        has_errors = bool(parsed["errors"])
        if has_errors:
            st.warning(
                "INCONSISTÊNCIAS IDENTIFICADAS. A ANÁLISE PODE CONTINUAR, "
                "MAS O FECHAMENTO NÃO PODE SER GRAVADO."
            )
            st.dataframe(
                pd.DataFrame(parsed["errors"]),
                use_container_width=True,
                hide_index=True,
            )

        if imports_by_month.get(competencia_input.isoformat()):
            st.warning(f"{month_label(competencia_input)} JÁ POSSUI FECHAMENTO SALVO.")

        if st.button(
            "PROCESSAR CONTINGÊNCIA",
            type="primary",
            use_container_width=True,
            key="fm_processar_contingencia",
            disabled=has_errors,
        ):
            db.import_inventory_report(
                competencia_input,
                uploaded.name,
                parsed["rows"],
            )
            st.session_state["_import_ok"] = (
                f"{month_label(competencia_input)} importado com sucesso."
            )
            st.query_params["mes"] = competencia_input.strftime("%Y-%m")
            st.rerun()


def api_sources_summary(
    sources: list[dict],
    error: str = "",
) -> dict:
    if error:
        return {
            "status": "ERRO",
            "css": "error",
            "healthy": 0,
            "total": 0,
            "last_update": "—",
        }

    if not sources:
        return {
            "status": "INDISPONÍVEL",
            "css": "warn",
            "healthy": 0,
            "total": 0,
            "last_update": "—",
        }

    ok_statuses = {
        "ATUALIZADO",
        "VALIDO",
        "VÁLIDO",
        "OK",
        "ONLINE",
        "ATIVO",
    }
    bad_statuses = {
        "ERRO",
        "INDISPONIVEL",
        "INDISPONÍVEL",
        "OFFLINE",
        "FALHA",
    }

    statuses = [
        str(row.get("status") or "").strip().upper()
        for row in sources
    ]
    healthy = sum(status in ok_statuses for status in statuses)

    if any(status in bad_statuses for status in statuses):
        overall = "ERRO"
        css = "error"
    elif healthy == len(sources):
        overall = "ATUALIZADO"
        css = "ok"
    else:
        overall = "ATENÇÃO"
        css = "warn"

    latest_update = None
    for row in sources:
        raw = str(row.get("last_update_at") or "").strip()
        if not raw:
            continue
        stamp = pd.to_datetime(raw, errors="coerce", utc=True)
        if pd.isna(stamp):
            continue
        if latest_update is None or stamp > latest_update:
            latest_update = stamp

    latest_label = (
        central_data.format_dt(latest_update.isoformat())
        if latest_update is not None
        else "—"
    )

    return {
        "status": overall,
        "css": css,
        "healthy": healthy,
        "total": len(sources),
        "last_update": latest_label,
    }


def api_status_cards_html(
    sources: list[dict],
) -> str:
    cards = ['<div class="api-status-grid">']

    status_colors = {
        "ATUALIZADO": "#22c55e",
        "VALIDO": "#22c55e",
        "VÁLIDO": "#22c55e",
        "OK": "#22c55e",
        "ONLINE": "#22c55e",
        "ATIVO": "#22c55e",
        "ATENÇÃO": "#f59e0b",
        "PENDENCIA": "#f59e0b",
        "PENDÊNCIA": "#f59e0b",
        "ERRO": "#ef4444",
        "INDISPONIVEL": "#ef4444",
        "INDISPONÍVEL": "#ef4444",
        "OFFLINE": "#ef4444",
        "FALHA": "#ef4444",
    }

    for row in sources:
        name = html.escape(
            str(
                row.get("name")
                or row.get("source_key")
                or "FONTE"
            )
        )
        status = str(
            row.get("status") or "INDISPONÍVEL"
        ).strip().upper()
        accent = status_colors.get(status, "#94a3b8")
        version = int(row.get("version") or 0)
        rows_count = int(row.get("rows_count") or 0)
        rows_text = f"{rows_count:,}".replace(",", ".")
        updated = html.escape(
            central_data.format_dt(
                row.get("last_update_at")
            )
        )
        origin = html.escape(
            str(row.get("origin") or "—")
        )

        cards.append(
            '<div class="api-status-card" '
            f'style="--api-accent:{accent}">'
            f'<div class="api-status-name">{name}</div>'
            f'<div class="api-status-value">{html.escape(status)}</div>'
            '<div class="api-status-meta">'
            f'V{version} · {updated} · {rows_text} REGISTROS · {origin}'
            '</div>'
            '</div>'
        )

    cards.append("</div>")
    return "".join(cards)

def validation_badge(info: dict) -> str:
    status = str(info.get("status") or "").strip().upper()
    invalid = int(info.get("linhas_invalidas") or 0)
    if status == "VALIDO":
        return '<span class="validation-badge validation-ok">VALIDADO</span>'
    label = f"PENDÊNCIA · {invalid}" if invalid else "PENDÊNCIA"
    return f'<span class="validation-badge validation-pending">{label}</span>'


def history_table_html(
    months: list[date],
    lookup: dict[tuple[str, str, str], dict],
    imports_map: dict[str, dict],
) -> str:
    rows = [
        '<div class="history-wrap">',
        '<div class="history-row history-head">',
        '<div class="history-cell">Competência</div>',
        '<div class="history-cell">Estoque inicial</div>',
        '<div class="history-cell">Estoque final</div>',
        '<div class="history-cell">Resumo</div>',
        '<div class="history-cell">Validação</div>',
        '</div>',
    ]

    for competencia in months:
        current_value = dimension_value(
            lookup,
            competencia,
            "TOTAL",
            "TOTAL",
        )
        prev_comp = previous_month(competencia)
        prev_exists = prev_comp.isoformat() in imports_map
        initial_value = (
            dimension_value(lookup, prev_comp, "TOTAL", "TOTAL")
            if prev_exists
            else None
        )
        summary = (
            None
            if initial_value is None
            else current_value - initial_value
        )
        info = imports_map.get(competencia.isoformat(), {})

        rows.extend(
            [
                '<div class="history-row">',
                f'<div class="history-cell history-month" data-label="Competência">{month_label(competencia)}</div>',
                f'<div class="history-cell history-money" data-label="Estoque inicial">{money_br(initial_value)}</div>',
                f'<div class="history-cell history-money" data-label="Estoque final">{money_br(current_value)}</div>',
                f'<div class="history-cell history-money{delta_class(summary)}" data-label="Resumo">{money_br(summary)}</div>',
                f'<div class="history-cell" data-label="Validação">{validation_badge(info)}</div>',
                '</div>',
            ]
        )

    rows.append('</div>')
    return "".join(rows)


def summary_cards_html(
    initial_value: float | None,
    final_value: float | None,
) -> str:
    summary = (
        None
        if initial_value is None or final_value is None
        else final_value - initial_value
    )
    return (
        '<div class="summary-grid">'
        '<div class="summary-card">'
        '<div class="summary-card-label">ESTOQUE INICIAL TOTAL</div>'
        f'<div class="summary-card-value">{money_br(initial_value)}</div>'
        '</div>'
        '<div class="summary-card">'
        '<div class="summary-card-label">ESTOQUE FINAL TOTAL</div>'
        f'<div class="summary-card-value">{money_br(final_value)}</div>'
        '</div>'
        '<div class="summary-card">'
        '<div class="summary-card-label">RESUMO TOTAL</div>'
        f'<div class="summary-card-value{delta_class(summary)}">{money_br(summary)}</div>'
        '</div>'
        '</div>'
    )


def tp_comparison_html(
    product_types: list[str],
    previous: date,
    selected: date,
    previous_exists: bool,
    lookup: dict[tuple[str, str, str], dict],
) -> str:
    rows = [
        '<div class="tp-table">',
        '<div class="tp-table-row tp-table-head">',
        '<div class="tp-table-cell">TIPO</div>',
        f'<div class="tp-table-cell">{MONTHS_PT[previous.month] if previous_exists else "ESTOQUE INICIAL"}</div>',
        f'<div class="tp-table-cell">{MONTHS_PT[selected.month]}</div>',
        '</div>',
    ]

    initial_total = 0.0
    final_total = 0.0

    for tp in product_types:
        initial_value = (
            dimension_value(lookup, previous, "TP", f"TP:{tp}")
            if previous_exists
            else None
        )
        final_value = dimension_value(
            lookup,
            selected,
            "TP",
            f"TP:{tp}",
        )
        if initial_value is not None:
            initial_total += float(initial_value)
        final_total += float(final_value)

        rows.extend(
            [
                '<div class="tp-table-row">',
                f'<div class="tp-table-cell tp-table-type" data-label="TIPO">{tp}</div>',
                f'<div class="tp-table-cell tp-table-money" data-label="ANTERIOR">{money_br(initial_value)}</div>',
                f'<div class="tp-table-cell tp-table-money" data-label="ATUAL">{money_br(final_value)}</div>',
                '</div>',
            ]
        )

    rows.extend(
        [
            '<div class="tp-table-row tp-table-total">',
            '<div class="tp-table-cell tp-table-type" data-label="TIPO">TOTAL</div>',
            f'<div class="tp-table-cell tp-table-money" data-label="ANTERIOR">{money_br(initial_total if previous_exists else None)}</div>',
            f'<div class="tp-table-cell tp-table-money" data-label="ATUAL">{money_br(final_total)}</div>',
            '</div>',
            '</div>',
        ]
    )
    return "".join(rows)


def _export_font(size: int, bold: bool = False):
    """Fonte escalável robusta para o PNG exportado no Streamlit Cloud."""
    candidates = [
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
        if bold
        else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except Exception:
            continue

    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def export_tp_png(
    product_types: list[str],
    previous: date,
    selected: date,
    previous_exists: bool,
    lookup: dict[tuple[str, str, str], dict],
    config: dict,
) -> bytes:
    """Gera um resumo mensal compacto e pronto para envio à contabilidade."""
    width = 1100
    outer = 24
    header_h = 96
    month_h = 58
    row_h = 54
    total_h = 62
    footer_gap = 24

    ordered_types = [
        tp for tp in ["EP", "II", "MP", "PA", "PI"]
        if tp in product_types
    ]
    ordered_types += [
        tp for tp in product_types
        if tp not in ordered_types
    ]

    rows_count = len(ordered_types)
    height = (
        outer
        + header_h
        + month_h
        + rows_count * row_h
        + total_h
        + footer_gap
    )

    canvas = Image.new("RGB", (width, height), "#f7f8fa")
    draw = ImageDraw.Draw(canvas)

    x0 = outer
    x3 = width - outer
    table_w = x3 - x0

    type_w = 230
    month_w = (table_w - type_w) / 2

    x1 = x0 + type_w
    x2 = x1 + month_w

    y0 = outer
    y1 = y0 + header_h
    y2 = y1 + month_h
    body_bottom = y2 + rows_count * row_h
    y3 = body_bottom + total_h

    border = "#c9ced6"
    dark = "#111827"
    muted = "#667085"
    header_bg = "#f0f2f5"
    month_bg = "#5f6670"
    type_bg = "#f6f7f9"
    row_bg = "#ffffff"
    total_bg = "#e5e7eb"
    red = "#ef4444"

    title_font = _export_font(34, True)
    month_font = _export_font(20, True)
    type_font = _export_font(19, True)
    value_font = _export_font(19, False)
    total_font = _export_font(20, True)
    fallback_logo_font = _export_font(50, True)

    # Cartão principal
    draw.rounded_rectangle(
        (x0, y0, x3, y3),
        radius=14,
        fill="#ffffff",
        outline=border,
        width=2,
    )

    # Cabeçalho
    draw.rounded_rectangle(
        (x0, y0, x3, y1),
        radius=14,
        fill=header_bg,
    )
    draw.rectangle((x0, y1 - 14, x3, y1), fill=header_bg)

    # Detalhe da marca
    draw.rectangle((x0, y0, x0 + 5, y1), fill=red)

    logo_area_right = x0 + 285
    draw.line(
        (logo_area_right, y0 + 18, logo_area_right, y1 - 18),
        fill=border,
        width=2,
    )

    # Logo configurada
    logo_data = str(config.get("logo_data") or "").strip()
    logo_mime = str(config.get("logo_mime") or "").lower()
    logo_drawn = False

    if logo_data and "svg" not in logo_mime:
        try:
            raw = base64.b64decode(logo_data)
            logo = Image.open(io.BytesIO(raw)).convert("RGBA")
            logo.thumbnail((205, 64))
            logo_x = int(x0 + 28)
            logo_y = int(y0 + (header_h - logo.height) / 2)
            canvas.paste(logo, (logo_x, logo_y), logo)
            logo_drawn = True
        except Exception:
            logo_drawn = False

    if not logo_drawn:
        label = "Setta"
        bbox = draw.textbbox((0, 0), label, font=fallback_logo_font)
        label_h = bbox[3] - bbox[1]
        draw.text(
            (x0 + 34, y0 + (header_h - label_h) / 2 - 4),
            label,
            font=fallback_logo_font,
            fill="#2f3135",
        )

    # Título do relatório
    title = "VALOR EM ESTOQUE"
    bbox = draw.textbbox((0, 0), title, font=title_font)
    title_w = bbox[2] - bbox[0]
    title_h = bbox[3] - bbox[1]
    title_x = logo_area_right + ((x3 - logo_area_right) - title_w) / 2
    title_y = y0 + (header_h - title_h) / 2 - 3
    draw.text(
        (title_x, title_y),
        title,
        font=title_font,
        fill=dark,
    )

    # Cabeçalho da tabela
    draw.rectangle((x0, y1, x3, y2), fill=month_bg)

    previous_label = (
        MONTHS_PT[previous.month]
        if previous_exists
        else "ESTOQUE INICIAL"
    )
    selected_label = MONTHS_PT[selected.month]

    for label, left, right in [
        ("TIPO", x0, x1),
        (previous_label, x1, x2),
        (selected_label, x2, x3),
    ]:
        bbox = draw.textbbox((0, 0), label, font=month_font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(
            (
                left + (right - left - tw) / 2,
                y1 + (month_h - th) / 2 - 2,
            ),
            label,
            font=month_font,
            fill="#ffffff",
        )

    initial_total = 0.0
    final_total = 0.0

    y = y2
    for tp in ordered_types:
        initial_value = (
            dimension_value(
                lookup,
                previous,
                "TP",
                f"TP:{tp}",
            )
            if previous_exists
            else None
        )
        final_value = dimension_value(
            lookup,
            selected,
            "TP",
            f"TP:{tp}",
        )

        if initial_value is not None:
            initial_total += float(initial_value)
        final_total += float(final_value)

        draw.rectangle((x0, y, x1, y + row_h), fill=type_bg)
        draw.rectangle((x1, y, x3, y + row_h), fill=row_bg)

        # TP centralizado
        bbox = draw.textbbox((0, 0), tp, font=type_font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(
            (
                x0 + (x1 - x0 - tw) / 2,
                y + (row_h - th) / 2 - 2,
            ),
            tp,
            font=type_font,
            fill=dark,
        )

        # Valores alinhados à direita
        for value, left, right in [
            (money_br(initial_value), x1, x2),
            (money_br(final_value), x2, x3),
        ]:
            bbox = draw.textbbox((0, 0), value, font=value_font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.text(
                (
                    right - tw - 24,
                    y + (row_h - th) / 2 - 2,
                ),
                value,
                font=value_font,
                fill=dark,
            )

        y += row_h

    # Total
    draw.rectangle((x0, body_bottom, x3, y3), fill=total_bg)

    bbox = draw.textbbox((0, 0), "TOTAL", font=total_font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(
        (
            x0 + (x1 - x0 - tw) / 2,
            body_bottom + (total_h - th) / 2 - 2,
        ),
        "TOTAL",
        font=total_font,
        fill=dark,
    )

    for value, left, right in [
        (
            money_br(initial_total if previous_exists else None),
            x1,
            x2,
        ),
        (money_br(final_total), x2, x3),
    ]:
        bbox = draw.textbbox((0, 0), value, font=total_font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(
            (
                right - tw - 24,
                body_bottom + (total_h - th) / 2 - 2,
            ),
            value,
            font=total_font,
            fill=dark,
        )

    # Grade da tabela
    for x in [x0, x1, x2, x3]:
        draw.line((x, y1, x, y3), fill=border, width=1)

    draw.line((x0, y1, x3, y1), fill=border, width=1)
    draw.line((x0, y2, x3, y2), fill=border, width=1)

    line_y = y2
    for _ in range(rows_count):
        line_y += row_h
        draw.line((x0, line_y, x3, line_y), fill=border, width=1)

    draw.line((x0, body_bottom, x3, body_bottom), fill=border, width=1)
    draw.line((x0, y3, x3, y3), fill=border, width=1)

    output = io.BytesIO()
    canvas.save(
        output,
        format="PNG",
        optimize=True,
    )
    return output.getvalue()

def parse_competencia(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def summary_lookup(rows: list[dict]) -> dict[tuple[str, str, str], dict]:
    result: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        competencia = str(row.get("competencia") or "")[:10]
        dimensao = str(row.get("dimensao") or "")
        chave = str(row.get("chave") or "")
        result[(competencia, dimensao, chave)] = row
    return result


def dimension_rows(
    summaries: list[dict],
    competencia: date,
    dimension: str,
) -> list[dict]:
    key = competencia.isoformat()
    return [
        row
        for row in summaries
        if str(row.get("competencia") or "")[:10] == key
        and str(row.get("dimensao") or "") == dimension
    ]


def dimension_value(
    lookup: dict[tuple[str, str, str], dict],
    competencia: date,
    dimension: str,
    key: str,
) -> float:
    row = lookup.get((competencia.isoformat(), dimension, key))
    if not row:
        return 0.0
    return float(row.get("valor_total") or 0)


def build_cb_reconciliation(
    closing_stock_items: list[dict],
    current_stock_items: list[dict],
    catalog: list[dict],
    counts: list[dict],
) -> pd.DataFrame:
    # CADASTROS funciona como universo em standby. O item só entra na
    # análise final quando possui saldo sistêmico > 0 ou quando alguma
    # fonte física foi vinculada a ele.
    standby_catalog = {
        str(row.get("codigo") or "").strip(): row
        for row in catalog
        if bool(row.get("ativo", True))
        and str(row.get("status") or "").upper() != "IGNORADO"
    }

    stock_by_code: dict[str, dict] = {}
    for row in closing_stock_items:
        codigo = normalize_code(row.get("codigo"))
        if codigo not in standby_catalog:
            continue

        current = stock_by_code.setdefault(
            codigo,
            {
                "saldo": 0.0,
                "valor_estoque": 0.0,
                "armz": set(),
                "descricao": "",
            },
        )
        current["saldo"] += max(
            float(row.get("saldo") or 0),
            0.0,
        )
        current["valor_estoque"] += max(
            float(row.get("valor_estoque") or 0),
            0.0,
        )
        armz = str(row.get("armz") or "").strip()
        if armz:
            current["armz"].add(armz)
        if not current["descricao"]:
            current["descricao"] = str(
                row.get("descricao") or ""
            ).strip()

    current_by_code: dict[str, dict] = {}
    for row in current_stock_items:
        codigo = normalize_code(row.get("codigo"))
        if codigo not in standby_catalog:
            continue
        current = current_by_code.setdefault(
            codigo,
            {"saldo": 0.0},
        )
        current["saldo"] += max(
            float(row.get("saldo") or 0),
            0.0,
        )

    counts_by_code: dict[str, list[dict]] = {}
    for row in counts:
        codigo = normalize_code(row.get("codigo"))
        if codigo not in standby_catalog:
            continue
        counts_by_code.setdefault(codigo, []).append(row)

    # Base final de VISUALIZAÇÃO = saldo no fechamento, saldo atual
    # ou item presente em contagem. Isso garante que aumentos ocorridos
    # depois da virada também apareçam na comparação item a item.
    analysis_codes = {
        codigo
        for codigo, data in stock_by_code.items()
        if float(data.get("saldo") or 0) > 0
    }
    if current_stock_items:
        analysis_codes.update(
            codigo
            for codigo, data in current_by_code.items()
            if float(data.get("saldo") or 0) > 0
        )
    analysis_codes.update(counts_by_code.keys())

    result: list[dict] = []

    for codigo in sorted(analysis_codes):
        item = standby_catalog[codigo]
        stock_data = stock_by_code.get(
            codigo,
            {
                "saldo": 0.0,
                "valor_estoque": 0.0,
                "armz": set(),
                "descricao": "",
            },
        )
        raw_counts = counts_by_code.get(codigo, [])

        # O setor interno é alimentado por Excel OU manual.
        # Se houver lançamento manual para o mesmo código, ele substitui
        # a parcela do Excel interno, evitando dupla contagem.
        manual_internal = [
            row for row in raw_counts
            if str(row.get("fonte") or "") == "INTERNO_MANUAL"
        ]
        item_counts = [
            row for row in raw_counts
            if str(row.get("fonte") or "") not in {
                "INTERNO_EXCEL",
                "INTERNO_MANUAL",
            }
        ]
        if manual_internal:
            item_counts.extend(manual_internal)
        else:
            item_counts.extend(
                row for row in raw_counts
                if str(row.get("fonte") or "") == "INTERNO_EXCEL"
            )

        saldo = max(float(stock_data.get("saldo") or 0), 0.0)
        _has_current_snapshot = bool(current_stock_items)
        saldo_atual = (
            max(
                float((current_by_code.get(codigo) or {}).get("saldo") or 0),
                0.0,
            )
            if _has_current_snapshot
            else None
        )
        saldo_base_ajuste = (
            min(saldo, float(saldo_atual))
            if saldo_atual is not None
            else saldo
        )
        base_origem = (
            "ATUAL"
            if saldo_atual is not None
            and float(saldo_atual) < saldo - 1e-9
            else "FECHAMENTO"
        )
        variacao_saldo = (
            None
            if saldo_atual is None
            else float(saldo_atual) - saldo
        )
        valor_estoque = max(
            float(stock_data.get("valor_estoque") or 0),
            0.0,
        )

        # Prioridade de valorização:
        # 1) custo médio efetivo do estoque = valor em estoque / saldo;
        # 2) último preço do CADASTROS somente quando não houver valor
        #    de estoque utilizável para o material.
        if valor_estoque > 0 and saldo > 0:
            custo_unitario = valor_estoque / saldo
            custo_origem = "ANALÍTICO · VALOR / SALDO"
        else:
            custo_unitario = float(item.get("ult_preco") or 0)
            custo_origem = (
                "CADASTROS · ÚLT. PREÇO"
                if custo_unitario > 0
                else "SEM CUSTO"
            )

        physical = (
            sum(
                float(row.get("quantidade_fisica") or 0)
                for row in item_counts
            )
            if item_counts
            else None
        )
        consumo_informado = sum(
            float(row.get("consumo") or 0)
            for row in item_counts
            if str(row.get("fonte") or "")
            == "BARRAMENTOS_EXCEL"
        )

        source_parts = []
        for row in item_counts:
            source_label = CB_SOURCE_LABELS.get(
                str(row.get("fonte") or ""),
                str(row.get("fonte") or ""),
            )
            source_text = (
                f"{source_label}: "
                + f"{float(row.get('quantidade_fisica') or 0):,.3f}"
                .replace(",", "X")
                .replace(".", ",")
                .replace("X", ".")
            )
            row_consumo = float(row.get("consumo") or 0)
            if (
                str(row.get("fonte") or "")
                == "BARRAMENTOS_EXCEL"
                and row_consumo > 0
            ):
                source_text += (
                    " · consumo "
                    + f"{row_consumo:,.3f}"
                    .replace(",", "X")
                    .replace(".", ",")
                    .replace("X", ".")
                )
            source_parts.append(source_text)

        # Regra operacional: confrontar a contagem com o MENOR saldo
        # entre a posição do fechamento e a posição atual. Se uma baixa
        # posterior já reduziu o estoque, ela não deve ser baixada novamente.
        diferenca_qtd = (
            None
            if physical is None
            else physical - saldo_base_ajuste
        )
        diferenca_rs = (
            None
            if diferenca_qtd is None or custo_unitario <= 0
            else diferenca_qtd * custo_unitario
        )

        tolerancia_automatica = (
            item.get("categoria") == "BARRA_COBRE"
            and physical is not None
            and abs(float(diferenca_qtd or 0)) < 3.0
        )

        if physical is None:
            status = "SEM CONTAGEM"
        elif tolerancia_automatica:
            status = "CONFERIDO"
        elif abs(float(diferenca_qtd or 0)) <= 1e-9:
            status = "CONFERIDO"
        else:
            status = "DIVERGÊNCIA"

        descricao = str(
            item.get("descricao")
            or stock_data.get("descricao")
            or ""
        ).strip()

        result.append(
            {
                "Categoria": (
                    "CHAPA"
                    if item.get("categoria") == "CHAPA"
                    else "BARRA DE COBRE"
                ),
                "Código": codigo,
                "Descrição": descricao,
                "U.M.": (
                    "KG"
                    if item.get("categoria") == "CHAPA"
                    else "MT"
                ),
                "ARMZ": ", ".join(
                    sorted(stock_data.get("armz") or set())
                ),
                "Saldo fechamento": saldo,
                "Saldo atual": saldo_atual,
                "Variação atual x fechamento": variacao_saldo,
                "Saldo base ajuste": saldo_base_ajuste,
                "Base usada": base_origem,
                "Físico": physical,
                "Contagem assumida zero": False,
                "Consumo informado": (
                    consumo_informado
                    if item.get("categoria") == "BARRA_COBRE"
                    and consumo_informado > 0
                    else None
                ),
                "Diferença Qtd": diferenca_qtd,
                "Custo unitário": custo_unitario,
                "Origem custo": custo_origem,
                "Diferença R$": diferenca_rs,
                "Fontes físicas": " | ".join(source_parts),
                "Tolerância automática": tolerancia_automatica,
                "Status": status,
            }
        )

    return pd.DataFrame(result)

def cb_kpi_html(
    total_items: int,
    counted_items: int,
    divergent_items: int,
    divergence_rs: float,
) -> str:
    return f"""
    <div class="cb-kpi-grid">
        <div class="cb-kpi" style="--cb-accent:#2563eb">
            <div class="cb-kpi-label">ITENS DA BASE</div>
            <div class="cb-kpi-value">{total_items}</div>
            <div class="cb-kpi-note">Chapas e barras monitoradas</div>
        </div>
        <div class="cb-kpi" style="--cb-accent:#16a34a">
            <div class="cb-kpi-label">ITENS CONTADOS</div>
            <div class="cb-kpi-value">{counted_items}</div>
            <div class="cb-kpi-note">Com uma fonte física definida</div>
        </div>
        <div class="cb-kpi" style="--cb-accent:#dc2626">
            <div class="cb-kpi-label">DIVERGÊNCIAS</div>
            <div class="cb-kpi-value">{divergent_items}</div>
            <div class="cb-kpi-note">Quantidade física ≠ sistema</div>
        </div>
        <div class="cb-kpi" style="--cb-accent:#d97706">
            <div class="cb-kpi-label">DIFERENÇA EM R$</div>
            <div class="cb-kpi-value">{money_br(divergence_rs)}</div>
            <div class="cb-kpi-note">Físico − menor saldo × custo unitário</div>
        </div>
    </div>
    """


if "app_cfg" not in st.session_state:
    try:
        remote_cfg = db.load_config()
    except Exception:
        remote_cfg = {}

    try:
        fallback_logo_data = base64.b64encode(
            (ROOT / "config" / "logo_setta.svg").read_bytes()
        ).decode()
    except Exception:
        fallback_logo_data = ""

    default_logo_data = str(
        GLOBAL_VISUAL_CONFIG.get("logo_data") or fallback_logo_data
    )
    default_logo_mime = str(
        GLOBAL_VISUAL_CONFIG.get("logo_mime") or "image/svg+xml"
    )

    remote_menu_labels = remote_cfg.get("menu_labels")
    if not isinstance(remote_menu_labels, dict):
        remote_menu_labels = {}

    st.session_state.app_cfg = {
        **DEFAULT_CONFIG,
        **remote_cfg,
        "menu_labels": {
            **DEFAULT_CONFIG["menu_labels"],
            **remote_menu_labels,
        },
        "logo_data": default_logo_data,
        "logo_mime": default_logo_mime,
    }

cfg = st.session_state.app_cfg

try:
    api_sources = load_api_sources()
    api_sources_error = ""
except Exception as exc:
    api_sources = []
    api_sources_error = str(exc)

api_summary = api_sources_summary(
    api_sources,
    api_sources_error,
)

query_page = str(st.query_params.get("pagina", "") or "").strip()
if query_page in PAGES:
    st.session_state.nav_page = query_page
elif "nav_page" not in st.session_state:
    st.session_state.nav_page = PAGES[0]

page = str(st.session_state.get("nav_page") or PAGES[0])
if page not in PAGES:
    page = PAGES[0]
    st.session_state.nav_page = page

menu_labels = cfg.get("menu_labels") or {}
_sidebar_links = []
for internal_page in PAGES:
    label = str(
        menu_labels.get(internal_page)
        or DEFAULT_CONFIG["menu_labels"].get(internal_page, internal_page)
    ).strip()
    active = " active" if page == internal_page else ""
    href_page = html.escape(internal_page, quote=True)
    _sidebar_links.append(
        f'<a class="sidebar-nav-link{active}" href="?pagina={href_page}" target="_self">{html.escape(label)}</a>'
    )

_sidebar_status_class = {
    "ok": "status-ok",
    "warn": "status-warning",
    "error": "status-error",
}.get(str(api_summary.get("css") or ""), "status-warning")

_sidebar_html = (
    '<div class="setta-sidebar">'
    '<div class="sidebar-brand">'
      f'<div class="sidebar-brand-title">{html.escape(str(cfg["sidebar_title"]))}</div>'
      f'<div class="sidebar-brand-sub">{html.escape(str(cfg["sidebar_subtitle"]))}</div>'
    '</div>'
    '<div class="sidebar-section-label">NAVEGAÇÃO</div>'
    '<div class="sidebar-nav">' + "".join(_sidebar_links) + '</div>'
    '<div class="sidebar-divider"></div>'
    '<div class="sidebar-section-label">STATUS GERAL</div>'
    '<div class="sidebar-status-card">'
      '<div class="sidebar-status-name">CONEXÕES</div>'
      f'<div class="sidebar-status-value {_sidebar_status_class}">{html.escape(str(api_summary["status"]))}</div>'
      '<div class="sidebar-status-meta">'
        f'<div>ÚLTIMA ATUALIZAÇÃO: {html.escape(str(api_summary.get("last_update") or "—"))}</div>'
        f'<div>QNT DE BASES: {api_summary["healthy"]}/{api_summary["total"]}</div>'
      '</div>'
    '</div>'
    '</div>'
)

with st.sidebar:
    st.markdown(_sidebar_html, unsafe_allow_html=True)

st.markdown(
    f'<div class="setta-logo-card">{logo_html(str(cfg.get("logo_data") or ""), str(cfg.get("logo_mime") or "image/svg+xml"))}</div>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<h1 class="app-title">{cfg["title"]} | SETTA</h1>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<p class="app-sub">{str(cfg["subtitle"]).upper()}</p>',
    unsafe_allow_html=True,
)

_force_central_fm = bool(st.session_state.pop("_force_central_fm", False))
central_context = central_analitico_context(force=_force_central_fm)
current_competencia = competencia_from_source_update(
    central_context.get("meta") or {}
)
central_balance_preview = (
    (central_context.get("balance") or {}).get("rows") or []
    if central_context.get("available")
    else []
)

try:
    imports = db.list_inventory_imports()
    summaries = db.list_inventory_summaries()
    data_error = ""
except Exception as exc:
    imports = []
    summaries = []
    data_error = str(exc)

persisted_import_keys = {
    str(row.get("competencia") or "")[:10]
    for row in imports
}
central_parsed = central_context.get("parsed") or {}
if (
    central_context.get("available")
    and central_parsed.get("rows")
):
    current_key = current_competencia.isoformat()
    preview_errors = list(central_parsed.get("errors") or [])
    imports = [
        row for row in imports
        if str(row.get("competencia") or "")[:10] != current_key
    ]
    summaries = [
        row for row in summaries
        if str(row.get("competencia") or "")[:10] != current_key
    ]
    imports.append(
        {
            "competencia": current_key,
            "arquivo_nome": str(
                (central_context.get("meta") or {}).get("last_file_name")
                or "ANALITICO.xltx"
            ),
            "total_linhas": int(central_parsed.get("total_rows") or 0),
            "linhas_validas": int(central_parsed.get("valid_rows") or 0),
            "linhas_invalidas": int(central_parsed.get("invalid_rows") or len(preview_errors)),
            "valor_total": float(central_parsed.get("total_value") or 0),
            "status": "PENDENCIA" if preview_errors else "VALIDO",
            "importado_em": (central_context.get("meta") or {}).get("last_update_at"),
            "preview": True,
        }
    )
    summaries.extend(
        build_preview_summaries(
            current_competencia,
            central_parsed["rows"],
        )
    )

imports_by_month = {
    str(row.get("competencia") or "")[:10]: row
    for row in imports
}
summary_map = summary_lookup(summaries)
available_months = sorted(
    [
        parsed
        for parsed in (parse_competencia(row.get("competencia")) for row in imports)
        if parsed is not None
    ]
)

# Dezembro/2025 é mantido somente como base de abertura de janeiro/2026.
# Ele não aparece como competência analisável nem no histórico visual.
visible_months = [
    competencia
    for competencia in available_months
    if competencia >= date(2026, 1, 1)
]


if page == "Dashboard":
    if data_error:
        st.error(f"Não foi possível carregar a base do fechamento: {data_error}")

    flash = st.session_state.pop("_import_ok", None)
    if flash:
        st.success(flash)

    if not visible_months:
        st.info("Nenhum fechamento mensal visível foi importado ainda.")
    else:
        query_month = str(st.query_params.get("mes", "") or "").strip()
        query_date = None
        if len(query_month) == 7:
            try:
                query_date = date.fromisoformat(query_month + "-01")
            except Exception:
                query_date = None

        default_month = query_date if query_date in visible_months else visible_months[-1]

        selected_month = st.selectbox(
            "Competência analisada",
            visible_months,
            index=visible_months.index(default_month),
            format_func=month_label,
        )
        st.query_params["mes"] = selected_month.strftime("%Y-%m")

        import_info = imports_by_month.get(selected_month.isoformat(), {})
        status = str(import_info.get("status") or "")
        previous = previous_month(selected_month)
        previous_exists = previous.isoformat() in imports_by_month

        if status != "VALIDO":
            st.warning(
                f"{month_label(selected_month)} possui pendência de qualidade no relatório "
                f"({int(import_info.get('linhas_invalidas') or 0)} item(ns)). "
                "A análise permanece disponível com as linhas válidas; apenas a gravação do fechamento fica bloqueada."
            )
            if bool(import_info.get("preview")) and selected_month == current_competencia:
                historical_errors = list(central_parsed.get("errors") or [])
            else:
                historical_errors = db.list_import_errors(selected_month)
            if historical_errors:
                st.dataframe(
                    pd.DataFrame(historical_errors),
                    use_container_width=True,
                    hide_index=True,
                )

        previous_status = str(
            imports_by_month.get(previous.isoformat(), {}).get("status") or ""
        )
        if previous_exists and previous_status != "VALIDO":
            st.warning(
                f"O estoque inicial de {month_label(selected_month)} foi calculado a partir de "
                f"{month_label(previous)}, cuja base histórica possui pendência de qualidade. "
                "O valor exibido considera somente as linhas financeiramente válidas do relatório anterior."
            )

        st.markdown('<div class="topic-divider"></div>', unsafe_allow_html=True)

        section_band(
            "01 · VISÃO GERAL",
            "ANÁLISE TOTAL DA COMPETÊNCIA",
            "Compara o valor total do estoque do mês selecionado com o fechamento do mês imediatamente anterior.",
        )

        final_total = dimension_value(summary_map, selected_month, "TOTAL", "TOTAL")
        initial_total = (
            dimension_value(summary_map, previous, "TOTAL", "TOTAL")
            if previous_exists
            else None
        )

        st.markdown(
            summary_cards_html(
                initial_total,
                final_total,
            ),
            unsafe_allow_html=True,
        )

        st.markdown('<div class="topic-divider"></div>', unsafe_allow_html=True)

        section_band(
            "02 · ARMZ",
            "ESTOQUE POR ARMAZÉM",
            "ARMZ identifica o armazém do material. Cada cartão apresenta Estoque Inicial, Estoque Final e a variação do período.",
        )

        current_warehouses = {
            str(row.get("armz") or "")
            for row in dimension_rows(summaries, selected_month, "ARMZ")
        }
        previous_warehouses = (
            {
                str(row.get("armz") or "")
                for row in dimension_rows(summaries, previous, "ARMZ")
            }
            if previous_exists
            else set()
        )
        warehouses = sorted(current_warehouses | previous_warehouses)

        if warehouses:
            for start in range(0, len(warehouses), 3):
                columns = st.columns(3)
                for column, armz in zip(columns, warehouses[start : start + 3]):
                    initial_value = (
                        dimension_value(
                            summary_map,
                            previous,
                            "ARMZ",
                            f"ARMZ:{armz}",
                        )
                        if previous_exists
                        else None
                    )
                    final_value = dimension_value(
                        summary_map,
                        selected_month,
                        "ARMZ",
                        f"ARMZ:{armz}",
                    )
                    with column:
                        st.markdown(
                            stock_card(
                                f"ARMAZÉM {armz}",
                                initial_value,
                                final_value,
                            ),
                            unsafe_allow_html=True,
                        )

        st.markdown('<div class="topic-divider"></div>', unsafe_allow_html=True)

        section_band(
            "03 · TP",
            "ESTOQUE POR TIPO DE PRODUTO",
            "Comparação financeira do estoque por TP entre a competência anterior e a competência selecionada.",
        )

        current_types = {
            str(row.get("tp") or "")
            for row in dimension_rows(summaries, selected_month, "TP")
        }
        previous_types = (
            {
                str(row.get("tp") or "")
                for row in dimension_rows(summaries, previous, "TP")
            }
            if previous_exists
            else set()
        )
        product_types = sorted(current_types | previous_types)

        if product_types:
            st.markdown(
                tp_comparison_html(
                    product_types,
                    previous,
                    selected_month,
                    previous_exists,
                    summary_map,
                ),
                unsafe_allow_html=True,
            )

            png_data = export_tp_png(
                product_types,
                previous,
                selected_month,
                previous_exists,
                summary_map,
                cfg,
            )
            download_left, download_right = st.columns([3.3, 1])
            with download_right:
                st.download_button(
                    "EXPORTAR RESUMO PNG",
                    data=png_data,
                    file_name=(
                        "valor_em_estoque_"
                        + selected_month.strftime("%Y_%m")
                        + ".png"
                    ),
                    mime="image/png",
                    use_container_width=True,
                    key=f"download_tp_png_{selected_month.isoformat()}",
                )

        st.markdown('<div class="topic-divider"></div>', unsafe_allow_html=True)

        section_band(
            "04 · EVOLUÇÃO MENSAL",
            "HISTÓRICO DOS FECHAMENTOS",
            "Validação indica apenas a qualidade do relatório importado. VALIDADO = nenhuma inconsistência encontrada. PENDÊNCIA = existem itens sem custo, sem saldo, negativos ou com cadastro obrigatório ausente. Não é um status contábil ou de aprovação do fechamento.",
        )

        st.markdown(
            history_table_html(
                visible_months,
                summary_map,
                imports_by_month,
            ),
            unsafe_allow_html=True,
        )


    st.markdown('<div class="topic-divider"></div>', unsafe_allow_html=True)
    section_band(
        "05 · FECHAMENTO",
        "GRAVAR COMPETÊNCIA",
        "",
    )

    if (
        central_context.get("available")
        and central_parsed.get("rows")
    ):
        _has_closing_errors = bool(central_parsed.get("errors"))
        _is_saved_current = current_competencia.isoformat() in persisted_import_keys
        _save_label = (
            "ATUALIZAR FECHAMENTO DA COMPETÊNCIA"
            if _is_saved_current
            else "GRAVAR FECHAMENTO DA COMPETÊNCIA"
        )

        if _has_closing_errors:
            st.warning(
                "FECHAMENTO NÃO PODE SER GRAVADO ENQUANTO EXISTIREM INCONSISTÊNCIAS NO ANALÍTICO. "
                "TODAS AS ETAPAS DE ANÁLISE E CONFERÊNCIA PERMANECEM LIBERADAS."
            )

        if st.button(
            _save_label,
            type="primary",
            use_container_width=True,
            key="fm_save_current_central",
            disabled=_has_closing_errors,
        ):
            try:
                _source_name = str(
                    (central_context.get("meta") or {}).get("last_file_name")
                    or "ANALITICO.xltx"
                )
                db.import_inventory_report(
                    current_competencia,
                    _source_name,
                    central_parsed["rows"],
                )
                st.session_state["_import_ok"] = (
                    f"{month_label(current_competencia)} gravado com sucesso."
                )
                st.query_params["mes"] = current_competencia.strftime("%Y-%m")
                st.rerun()
            except Exception as exc:
                st.error(f"NÃO FOI POSSÍVEL GRAVAR O FECHAMENTO: {exc}")
    else:
        st.warning("ANALÍTICO DA CENTRAL INDISPONÍVEL.")


elif page == "Conferência de chapas e barramentos":
    st.markdown(
        """
        <div class="cb-title-inline">
            <div class="section-title cb-title-main">
                CONFERÊNCIA DE CHAPAS E BARRAMENTOS
            </div>
            <div class="cb-info-wrap" tabindex="0">
                <span class="cb-info-icon">i</span>
                <div class="cb-info-tooltip">
                    <strong>COMO FUNCIONA</strong>
                    <span>
                        O CADASTROS define o universo de materiais.
                        Neste módulo, o Relatório Analítico fornece somente o
                        SALDO EM ESTOQUE da competência.
                        O físico é formado pelas fontes de Chapas, Barramentos
                        e Almoxarifado. Materiais novos passam por validação e,
                        depois de confirmados, permanecem automaticamente na
                        base dos próximos fechamentos.
                    </span>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not visible_months:
        st.info(
            "Importe primeiro uma competência no Dashboard para utilizar esta conferência."
        )
    else:
        query_cb_month = str(
            st.query_params.get("mes_cb", "") or ""
        ).strip()
        cb_query_date = None
        if len(query_cb_month) == 7:
            try:
                cb_query_date = date.fromisoformat(
                    query_cb_month + "-01"
                )
            except Exception:
                cb_query_date = None

        cb_default_month = (
            cb_query_date
            if cb_query_date in visible_months
            else visible_months[-1]
        )

        cb_month = st.selectbox(
            "Competência da conferência",
            visible_months,
            index=visible_months.index(cb_default_month),
            format_func=month_label,
            key="cb_month",
            label_visibility="collapsed",
        )
        st.query_params["mes_cb"] = cb_month.strftime("%Y-%m")

        force_cadastros = bool(
            st.session_state.pop(
                "_force_cb_cadastros",
                False,
            )
        )
        cadastros_context = central_cadastros_context(
            force=force_cadastros
        )

        try:
            cb_closing_stock_items = db.list_cb_system_balances(cb_month)
            cb_catalog = db.list_cb_catalog()
            cb_counts = db.list_cb_counts(cb_month)
            cb_mappings = db.list_cb_sheet_mappings()
            cb_physical_mappings = db.list_cb_physical_mappings()
            cb_imports = db.list_cb_imports(cb_month)
            cb_exclusions = db.list_cb_exclusions(cb_month)
            cb_error = ""
        except Exception as exc:
            cb_closing_stock_items = []
            cb_catalog = []
            cb_counts = []
            cb_mappings = []
            cb_physical_mappings = []
            cb_imports = []
            cb_exclusions = []
            cb_error = str(exc)

        if cb_error:
            st.error(
                f"Não foi possível carregar a conferência: {cb_error}"
            )

        # O Analítico da Central representa o saldo sistêmico atual.
        # O saldo do fechamento é uma fotografia separada, alimentada manualmente
        # e persistida por competência.
        cb_current_stock_items = list(central_balance_preview or [])

        standby_catalog = [
            row
            for row in cb_catalog
            if bool(row.get("ativo", True))
            and str(row.get("status") or "").upper() != "IGNORADO"
        ]
        standby_lookup = {
            str(row.get("codigo") or "").strip(): row
            for row in standby_catalog
        }
        physical_mapping_lookup = {
            (
                str(row.get("fonte") or "").strip(),
                str(row.get("chave_origem") or "").strip(),
            ): str(row.get("codigo") or "").strip()
            for row in cb_physical_mappings
            if str(row.get("status") or "").upper() == "CONFIRMADO"
        }

        stock_positive_codes = set()
        for row in cb_closing_stock_items:
            code = normalize_code(row.get("codigo"))
            if (
                code in standby_lookup
                and max(float(row.get("saldo") or 0), 0.0) > 0
            ):
                stock_positive_codes.add(code)

        counted_codes = {
            normalize_code(row.get("codigo"))
            for row in cb_counts
            if normalize_code(row.get("codigo")) in standby_lookup
        }
        excluded_codes_current = {
            str(row.get("codigo") or "").strip()
            for row in cb_exclusions
            if bool(row.get("ativo", True))
        }
        source_analysis_codes = (
            stock_positive_codes | counted_codes
        )
        final_analysis_codes = (
            source_analysis_codes - excluded_codes_current
        )
        standby_only_codes = (
            set(standby_lookup) - source_analysis_codes
        )

        st.markdown(
            f"""
            <div class="cb-compact-stats">
                <div class="cb-compact-stat">
                    <span>CADASTROS</span>
                    <strong>{len(standby_catalog)}</strong>
                </div>
                <div class="cb-compact-stat">
                    <span>COM SALDO</span>
                    <strong>{len(stock_positive_codes)}</strong>
                </div>
                <div class="cb-compact-stat">
                    <span>EM CONTAGEM</span>
                    <strong>{len(counted_codes)}</strong>
                </div>
                <div class="cb-compact-stat cb-compact-stat-final">
                    <span>BASE FINAL</span>
                    <strong>{len(final_analysis_codes)}</strong>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        flash_base = st.session_state.pop(
            "_cb_base_flash",
            None,
        )
        if flash_base:
            st.success(flash_base)

        with st.expander(
            f"STANDBY · {len(standby_only_codes)} MATERIAIS",
            expanded=False,
        ):
            standby_view = pd.DataFrame(
                [
                    {
                        "Código": row.get("codigo"),
                        "Categoria": (
                            "CHAPA"
                            if row.get("categoria") == "CHAPA"
                            else "BARRA DE COBRE"
                        ),
                        "Descrição": row.get("descricao"),
                        "Referência": row.get("referencia") or "",
                        "Últ. preço": float(
                            row.get("ult_preco") or 0
                        ),
                    }
                    for row in standby_catalog
                    if str(row.get("codigo") or "").strip()
                    in standby_only_codes
                ]
            )
            if standby_view.empty:
                st.info(
                    "Todos os materiais compatíveis já participam da análise atual."
                )
            else:
                st.dataframe(
                    standby_view,
                    use_container_width=True,
                    hide_index=True,
                )

        _closing_day = closing_date(cb_month)
        _closing_label = _closing_day.strftime("%d/%m/%Y")
        _current_updated = central_data.format_dt(
            (central_context.get("meta") or {}).get("last_update_at")
        )

        st.markdown(
            '<div class="cb-compact-section-title">00 · SALDOS DO SISTEMA</div>',
            unsafe_allow_html=True,
        )

        def _saldo_categoria(rows, categoria):
            total = 0.0
            for row in rows:
                code = normalize_code(row.get("codigo"))
                item = standby_lookup.get(code) or {}
                if str(item.get("categoria") or "").upper() != categoria:
                    continue
                total += max(float(row.get("saldo") or 0), 0.0)
            return total

        _chapa_atual = _saldo_categoria(cb_current_stock_items, "CHAPA")
        _chapa_fechamento = _saldo_categoria(cb_closing_stock_items, "CHAPA")
        _barra_atual = _saldo_categoria(cb_current_stock_items, "BARRA_COBRE")
        _barra_fechamento = _saldo_categoria(cb_closing_stock_items, "BARRA_COBRE")

        _s1, _s2, _s3, _s4 = st.columns(4)
        _s1.metric(
            "CHAPAS · ATUAL",
            f"{_chapa_atual:,.3f} KG".replace(",", "X").replace(".", ",").replace("X", "."),
            help="Saldo atual das chapas monitoradas, vindo da Central de Dados.",
        )
        _s2.metric(
            f"CHAPAS · FECHAMENTO {_closing_label}",
            (
                f"{_chapa_fechamento:,.3f} KG".replace(",", "X").replace(".", ",").replace("X", ".")
                if cb_closing_stock_items
                else "NÃO INFORMADO"
            ),
            help="Saldo das chapas no último dia da competência. Base oficial do cálculo.",
        )
        _s3.metric(
            "BARRAMENTOS · ATUAL",
            f"{_barra_atual:,.3f} MT".replace(",", "X").replace(".", ",").replace("X", "."),
            help="Saldo atual dos barramentos monitorados, vindo da Central de Dados.",
        )
        _s4.metric(
            f"BARRAMENTOS · FECHAMENTO {_closing_label}",
            (
                f"{_barra_fechamento:,.3f} MT".replace(",", "X").replace(".", ",").replace("X", ".")
                if cb_closing_stock_items
                else "NÃO INFORMADO"
            ),
            help="Saldo dos barramentos no último dia da competência. Base oficial do cálculo.",
        )
        _chapa_variacao_total = _chapa_atual - _chapa_fechamento
        _barra_variacao_total = _barra_atual - _barra_fechamento

        st.caption(
            "SALDO ATUAL: Central de Dados"
            + (f" · {_current_updated}" if _current_updated and _current_updated != "—" else "")
            + f" · SALDO DO FECHAMENTO: posição de {_closing_label}. "
            + "VARIAÇÃO CHAPAS: "
            + f"{_chapa_variacao_total:+,.3f} KG".replace(",", "X").replace(".", ",").replace("X", ".")
            + " · VARIAÇÃO BARRAMENTOS: "
            + f"{_barra_variacao_total:+,.3f} MT".replace(",", "X").replace(".", ",").replace("X", ".")
            + ". NO CÁLCULO ITEM A ITEM, O SISTEMA USA O MENOR SALDO ENTRE FECHAMENTO E ATUAL."
        )

        if not cb_closing_stock_items:
            st.warning(
                f"O fechamento de {month_label(cb_month)} corresponde à posição de {_closing_label}. "
                "Carregue o Relatório Analítico extraído nessa data para liberar o cálculo definitivo."
            )

        with st.expander(
            (
                f"ALIMENTAR SALDO DO FECHAMENTO · {_closing_label}"
                if not cb_closing_stock_items
                else f"ATUALIZAR SALDO DO FECHAMENTO · {_closing_label}"
            ),
            expanded=not bool(cb_closing_stock_items),
        ):
            cb_analytic_file = st.file_uploader(
                f"Relatório Analítico da posição de {_closing_label}",
                type=["xlsx", "xltx"],
                key="cb_analytic_file",
                help=(
                    "Esta carga é a fotografia do último dia da competência. "
                    "O saldo atual continuará vindo automaticamente da Central de Dados."
                ),
            )

            if cb_analytic_file is not None:
                try:
                    parsed_cb_analytic = parse_inventory_balance_report(
                        cb_analytic_file.getvalue(),
                        cb_analytic_file.name,
                    )

                    sa, sb, sc = st.columns(3)
                    sa.metric(
                        "Linhas lidas",
                        parsed_cb_analytic["total_rows"],
                    )
                    sb.metric(
                        "Saldos negativos → 0",
                        parsed_cb_analytic["adjusted_negative"],
                    )
                    sc.metric(
                        "Saldos inválidos → 0",
                        parsed_cb_analytic["invalid_balance"],
                    )

                    st.caption(
                        "O VALOR EM ESTOQUE desta carga será usado para valorizar "
                        "as divergências do fechamento. O saldo atual não substitui esta fotografia."
                    )

                    if st.button(
                        "SALVAR SALDO DO FECHAMENTO",
                        type="primary",
                        use_container_width=True,
                        key="cb_save_analytic",
                    ):
                        db.save_cb_system_balances(
                            cb_month,
                            cb_analytic_file.name,
                            parsed_cb_analytic["rows"],
                        )
                        st.session_state["_cb_base_flash"] = (
                            f"Saldo do fechamento de {_closing_label} salvo."
                        )
                        st.rerun()
                except Exception as exc:
                    st.error(
                        f"Não foi possível ler o Relatório Analítico do fechamento: {exc}"
                    )

        st.markdown(
            '<div class="topic-divider cb-tight-divider"></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="cb-compact-section-title">01 · ALIMENTAÇÃO FÍSICA</div>',
            unsafe_allow_html=True,
        )

        tab_email, tab_bar, tab_internal = st.tabs(
            [
                "CHAPAS · E-MAIL",
                "BARRAMENTOS · EXCEL",
                "ALMOXARIFADO · BARRAS",
            ]
        )

        with tab_email:
            email_file = st.file_uploader(
                "E-mail do setor de chapas",
                type=["eml"],
                key="cb_chapas_eml",
                help=(
                    "Use preferencialmente o arquivo .EML. O leitor pega "
                    "automaticamente a tabela mais recente da conversa."
                ),
            )

            if email_file is not None:
                try:
                    parsed_email = parse_chapas_eml(
                        email_file.getvalue(),
                        email_file.name,
                    )

                    detected_comp = parsed_email.get(
                        "competencia"
                    )
                    if detected_comp:
                        _data_contagem = parsed_email.get("data_contagem")
                        _data_txt = (
                            _data_contagem.strftime("%d/%m/%Y")
                            if _data_contagem
                            else "—"
                        )
                        _fechamento_txt = closing_date(
                            detected_comp
                        ).strftime("%d/%m/%Y")
                        st.caption(
                            "Data da contagem: "
                            + _data_txt
                            + " · Fechamento considerado em: "
                            + _fechamento_txt
                            + " · Competência: "
                            + month_label(detected_comp)
                            + f" · {parsed_email['tables_found']} tabela(s) de histórico encontrada(s)"
                        )

                    resolved_email = resolve_chapa_rows(
                        parsed_email["rows"],
                        cb_mappings,
                        cb_catalog,
                    )

                    _email_total_chapas = sum(
                        max(float(row.get("chapas") or 0), 0.0)
                        for row in parsed_email["rows"]
                    )
                    _email_total_peso = sum(
                        max(float(row.get("peso_total") or 0), 0.0)
                        for row in parsed_email["rows"]
                    )

                    em1, em2, em3, em4, em5 = st.columns(5)
                    em1.metric(
                        "Linhas do e-mail",
                        len(parsed_email["rows"]),
                    )
                    em2.metric(
                        "Códigos consolidados",
                        len(resolved_email["resolved"]),
                    )
                    em3.metric(
                        "Quantidade física",
                        f"{_email_total_chapas:,.0f} chapas"
                        .replace(",", "."),
                    )
                    em4.metric(
                        "Peso físico",
                        f"{_email_total_peso:,.3f} kg"
                        .replace(",", "X")
                        .replace(".", ",")
                        .replace("X", "."),
                    )
                    em5.metric(
                        "Sem vínculo",
                        len(resolved_email["unresolved"]),
                    )

                    if resolved_email["unresolved"]:
                        st.warning(
                            "Existem descrições de chapas ainda não vinculadas "
                            "a um código Protheus. Resolva os vínculos abaixo; "
                            "depois disso eles ficarão salvos para os próximos meses."
                        )

                        chapa_options = [
                            row
                            for row in standby_catalog
                            if row.get("categoria") == "CHAPA"
                        ]
                        option_labels = [
                            f"{row.get('codigo')} · {row.get('descricao')}"
                            for row in chapa_options
                        ]

                        mapping_rows = []
                        for index, row in enumerate(
                            resolved_email["unresolved"]
                        ):
                            mapping_rows.append(
                                {
                                    "ID": index,
                                    "Dimensão": row.get("dimensao"),
                                    "Descrição": row.get("descricao"),
                                    "Chapas": row.get("chapas"),
                                    "Peso total": row.get("peso_total"),
                                    "Código Protheus": (
                                        option_labels[0]
                                        if option_labels
                                        else ""
                                    ),
                                }
                            )

                        mapping_df = pd.DataFrame(mapping_rows)
                        edited_mapping = st.data_editor(
                            mapping_df,
                            use_container_width=True,
                            hide_index=True,
                            disabled=[
                                "ID",
                                "Dimensão",
                                "Descrição",
                                "Chapas",
                                "Peso total",
                            ],
                            column_config={
                                "Código Protheus": st.column_config.SelectboxColumn(
                                    "Código Protheus",
                                    options=option_labels,
                                    required=True,
                                )
                            },
                            key="cb_mapping_editor",
                        )

                        if st.button(
                            "SALVAR VÍNCULOS DE CHAPAS",
                            type="primary",
                            use_container_width=True,
                            key="cb_save_sheet_maps",
                        ):
                            if not option_labels:
                                st.error(
                                    "Não há códigos de CHAPA disponíveis no standby do CADASTROS."
                                )
                            else:
                                for _, edit_row in edited_mapping.iterrows():
                                    source_row = resolved_email[
                                        "unresolved"
                                    ][int(edit_row["ID"])]
                                    selected_label = str(
                                        edit_row["Código Protheus"]
                                    )
                                    selected_code = selected_label.split(
                                        " · ",
                                        1,
                                    )[0].strip()

                                    db.save_cb_sheet_mapping(
                                        source_row.get(
                                            "dimensao_norm"
                                        )
                                        or "*",
                                        source_row.get(
                                            "descricao_norm"
                                        )
                                        or "",
                                        source_row.get(
                                            "dimensao"
                                        )
                                        or "",
                                        source_row.get(
                                            "descricao"
                                        )
                                        or "",
                                        selected_code,
                                        "CONFIRMADO",
                                        "APP · E-MAIL CHAPAS",
                                    )
                                st.rerun()
                    else:
                        preview_email = pd.DataFrame(
                            resolved_email["resolved"]
                        )
                        if not preview_email.empty:
                            st.dataframe(
                                preview_email.rename(
                                    columns={
                                        "codigo": "Código",
                                        "quantidade_fisica": "Físico",
                                        "observacao": "Origem",
                                    }
                                ),
                                use_container_width=True,
                                hide_index=True,
                            )

                        mismatch = (
                            detected_comp is not None
                            and detected_comp != cb_month
                        )
                        if mismatch:
                            st.error(
                                "A contagem pertence a outro fechamento. "
                                "Selecione a competência correspondente ao último dia do mês anterior."
                            )
                        elif st.button(
                            "IMPORTAR CONTAGEM DE CHAPAS",
                            type="primary",
                            use_container_width=True,
                            key="cb_import_email",
                        ):
                            db.save_cb_counts_batch(
                                cb_month,
                                "CHAPAS_EMAIL",
                                email_file.name,
                                resolved_email["resolved"],
                            )
                            st.session_state["_cb_count_flash"] = (
                                "Contagem de chapas importada."
                            )
                            st.rerun()
                except Exception as exc:
                    st.error(
                        f"Não foi possível ler o e-mail de chapas: {exc}"
                    )

        with tab_bar:
            bar_file = st.file_uploader(
                "Planilha da produção de barramentos",
                type=["xlsx", "xltx"],
                key="cb_barramentos_file",
                help=(
                    "Todos os itens do relatório precisam estar vinculados "
                    "a um código do CADASTROS antes da importação."
                ),
            )

            if bar_file is not None:
                try:
                    parsed_bar = parse_barramentos_excel(
                        bar_file.getvalue(),
                        bar_file.name,
                    )

                    catalog_bar = {
                        str(row.get("codigo") or "").strip(): row
                        for row in standby_catalog
                        if row.get("categoria") == "BARRA_COBRE"
                    }
                    cad_master_lookup = (
                        (cadastros_context.get("parsed") or {})
                        .get("master_lookup")
                        or {}
                    )

                    valid_bar_rows = []
                    bar_issues = []
                    auto_bar_catalog = {}

                    for row in parsed_bar["rows"]:
                        source_code = normalize_code(
                            row.get("codigo")
                        )

                        # 1) Já existe como barra no standby.
                        mapped_code = (
                            source_code
                            if source_code in catalog_bar
                            else ""
                        )

                        # 2) Já existe vínculo persistente de meses anteriores.
                        if not mapped_code:
                            mapped_code = physical_mapping_lookup.get(
                                (
                                    "BARRAMENTOS_EXCEL",
                                    source_code,
                                ),
                                "",
                            )

                        # 3) Correspondência direta com o CADASTROS.
                        # A própria origem BARRAMENTOS valida a categoria.
                        if (
                            not mapped_code
                            and source_code in cad_master_lookup
                        ):
                            mapped_code = source_code
                            cadastro_item = cad_master_lookup[source_code]
                            auto_bar_catalog[source_code] = {
                                "descricao": str(
                                    cadastro_item.get("descricao")
                                    or ""
                                ).strip(),
                                "referencia": str(
                                    cadastro_item.get("referencia")
                                    or row.get("modelo")
                                    or ""
                                ).strip(),
                                "ult_preco": float(
                                    cadastro_item.get("ult_preco")
                                    or 0
                                ),
                            }

                        item = (
                            catalog_bar.get(mapped_code)
                            or cad_master_lookup.get(mapped_code)
                        )
                        if item is None:
                            bar_issues.append(
                                {
                                    "Código origem": source_code,
                                    "Modelo": row.get("modelo"),
                                    "Físico (m)": float(
                                        row.get("quantidade_fisica")
                                        or 0
                                    ),
                                    "Consumo (m)": float(
                                        row.get("consumo")
                                        or 0
                                    ),
                                }
                            )
                            continue

                        quantidade = float(
                            row.get("quantidade_fisica")
                            or 0
                        )
                        consumo = float(
                            row.get("consumo")
                            or 0
                        )
                        criterio = str(
                            row.get("criterio")
                            or ""
                        ).strip()

                        valid_bar_rows.append(
                            {
                                "codigo": mapped_code,
                                "quantidade_fisica": quantidade,
                                "consumo": consumo,
                                "observacao": (
                                    f"{row.get('modelo') or ''} · "
                                    f"{criterio or 'CONTAGEM'} "
                                    f"{quantidade:.3f} m · "
                                    f"Consumo informado {consumo:.3f} m"
                                    + (
                                        f" · origem {source_code}"
                                        if mapped_code != source_code
                                        else ""
                                    )
                                ).strip(" ·"),
                            }
                        )

                    br1, br2, br3, br4 = st.columns(4)
                    br1.metric(
                        "Itens do relatório",
                        parsed_bar["total_rows"],
                    )
                    br2.metric(
                        "Vinculados",
                        len(valid_bar_rows),
                    )
                    br3.metric(
                        "Físico total",
                        f"{float(parsed_bar['total_metros']):,.3f} m"
                        .replace(",", "X")
                        .replace(".", ",")
                        .replace("X", "."),
                    )
                    br4.metric(
                        "Sem vínculo",
                        len(bar_issues),
                    )

                    st.caption(
                        "O CONSUMO é contexto para investigar divergências. "
                        "Não altera automaticamente o saldo nem a diferença. "
                        "Quando o código do relatório existir exatamente no "
                        "CADASTROS, o vínculo é automático."
                    )

                    if valid_bar_rows:
                        preview_bar = pd.DataFrame(
                            valid_bar_rows
                        ).rename(
                            columns={
                                "codigo": "Código sistema",
                                "quantidade_fisica": "Contagem (m)",
                                "consumo": "Consumo informado (m)",
                                "observacao": "Detalhe",
                            }
                        )
                        st.dataframe(
                            preview_bar,
                            use_container_width=True,
                            hide_index=True,
                        )

                    if bar_issues:
                        st.warning(
                            "A importação fica bloqueada até que TODOS os itens "
                            "do relatório possuam vínculo com um código do sistema."
                        )

                        bar_options = [
                            f"{row.get('codigo')} · {row.get('descricao')}"
                            for row in standby_catalog
                            if row.get("categoria") == "BARRA_COBRE"
                        ]
                        mapping_rows = []
                        for index, issue in enumerate(bar_issues):
                            mapping_rows.append(
                                {
                                    "ID": index,
                                    "Código origem": issue.get(
                                        "Código origem"
                                    ),
                                    "Modelo": issue.get("Modelo"),
                                    "Físico (m)": issue.get(
                                        "Físico (m)"
                                    ),
                                    "Consumo (m)": issue.get(
                                        "Consumo (m)"
                                    ),
                                    "Vincular ao código": "",
                                }
                            )

                        edited_bar_maps = st.data_editor(
                            pd.DataFrame(mapping_rows),
                            use_container_width=True,
                            hide_index=True,
                            disabled=[
                                "ID",
                                "Código origem",
                                "Modelo",
                                "Físico (m)",
                                "Consumo (m)",
                            ],
                            column_config={
                                "Vincular ao código": (
                                    st.column_config.SelectboxColumn(
                                        "Vincular ao código",
                                        options=[""] + bar_options,
                                        required=True,
                                    )
                                )
                            },
                            key="cb_bar_mapping_editor",
                        )

                        if st.button(
                            "SALVAR VÍNCULOS DOS BARRAMENTOS",
                            type="primary",
                            use_container_width=True,
                            key="cb_save_bar_maps",
                        ):
                            missing_links = edited_bar_maps[
                                edited_bar_maps[
                                    "Vincular ao código"
                                ].astype(str).str.strip() == ""
                            ]
                            if not missing_links.empty:
                                st.error(
                                    "Vincule todos os itens antes de salvar."
                                )
                            else:
                                for _, edit_row in (
                                    edited_bar_maps.iterrows()
                                ):
                                    source_issue = bar_issues[
                                        int(edit_row["ID"])
                                    ]
                                    selected_code = str(
                                        edit_row[
                                            "Vincular ao código"
                                        ]
                                    ).split(" · ", 1)[0].strip()

                                    db.save_cb_physical_mapping(
                                        "BARRAMENTOS_EXCEL",
                                        str(
                                            source_issue.get(
                                                "Código origem"
                                            )
                                            or ""
                                        ),
                                        str(
                                            source_issue.get(
                                                "Modelo"
                                            )
                                            or ""
                                        ),
                                        selected_code,
                                    )
                                st.session_state[
                                    "_cb_count_flash"
                                ] = (
                                    "Vínculos dos barramentos salvos."
                                )
                                st.rerun()

                    elif valid_bar_rows and st.button(
                        "IMPORTAR CONTAGEM DE BARRAMENTOS",
                        type="primary",
                        use_container_width=True,
                        key="cb_import_bars",
                    ):
                        # Se o código veio diretamente do CADASTROS e ainda
                        # não estava classificado no standby, a própria
                        # contagem de barramentos confirma sua categoria.
                        for auto_code, auto_item in (
                            auto_bar_catalog.items()
                        ):
                            db.confirm_cb_catalog_item(
                                auto_code,
                                "BARRA_COBRE",
                                auto_item.get("descricao") or "",
                                auto_item.get("referencia") or "",
                                float(
                                    auto_item.get("ult_preco")
                                    or 0
                                ),
                            )

                        db.save_cb_counts_batch(
                            cb_month,
                            "BARRAMENTOS_EXCEL",
                            bar_file.name,
                            valid_bar_rows,
                        )
                        st.session_state["_cb_count_flash"] = (
                            "Contagem de barramentos importada. "
                            "Todos os itens possuem vínculo com o sistema."
                        )
                        st.rerun()
                except Exception as exc:
                    st.error(
                        f"Não foi possível ler a planilha de barramentos: {exc}"
                    )

        with tab_internal:
            internal_file = st.file_uploader(
                "Planilha do almoxarifado de barras",
                type=["xlsx", "xltx"],
                key="cb_internal_file",
                help=(
                    "Layout recomendado: BARRAMENTO + QUANTIDADE. "
                    "BARRAMENTO pode ser código, referência ou medida em "
                    "mm/polegadas. QUANTIDADE é tratada como número de barras "
                    "de 3 m, salvo quando a célula indicar metros."
                ),
            )

            st.download_button(
                "RELATÓRIO MODELO",
                data=build_almox_barras_model(),
                file_name="MODELO_CONTAGEM_ALMOX_BARRAS.xlsx",
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                type="tertiary",
                use_container_width=False,
                key="cb_download_internal_model",
            )

            if internal_file is not None:
                try:
                    parsed_internal = parse_interno_excel(
                        internal_file.getvalue(),
                        internal_file.name,
                    )

                    internal_catalog_rows = [
                        row
                        for row in standby_catalog
                        if row.get("categoria") == "BARRA_COBRE"
                    ]
                    internal_catalog = {
                        str(row.get("codigo") or "").strip(): row
                        for row in internal_catalog_rows
                    }

                    internal_valid = []
                    internal_issues = []

                    for row in parsed_internal["rows"]:
                        source_key = str(
                            row.get("chave_origem") or ""
                        ).strip()
                        identifier = str(
                            row.get("identificador") or source_key
                        ).strip()
                        direct_code = str(
                            row.get("codigo_direto") or ""
                        ).strip()

                        mapped_code = (
                            direct_code
                            if direct_code in internal_catalog
                            else ""
                        )

                        if not mapped_code:
                            mapped_code = physical_mapping_lookup.get(
                                ("INTERNO_EXCEL", source_key),
                                "",
                            )

                        match_origin = ""
                        if mapped_code:
                            match_origin = (
                                "CÓDIGO"
                                if mapped_code == direct_code
                                else "VÍNCULO SALVO"
                            )

                        similarity = None
                        matched_dimension = ""

                        if not mapped_code:
                            auto_matches = find_bar_catalog_matches(
                                identifier,
                                internal_catalog_rows,
                            )

                            if auto_matches:
                                best_match = auto_matches[0]
                                mapped_code = str(
                                    best_match.get("codigo")
                                    or ""
                                ).strip()
                                similarity = float(
                                    best_match.get(
                                        "_match_similarity"
                                    )
                                    or 0
                                )
                                matched_dimension = str(
                                    best_match.get(
                                        "_match_dimension"
                                    )
                                    or ""
                                ).strip()

                                match_origin = str(
                                    best_match.get(
                                        "_match_mode"
                                    )
                                    or "SIMILARIDADE"
                                ).strip()

                                if similarity < 99.99:
                                    match_origin += (
                                        f" · {similarity:.2f}%"
                                    )
                            else:
                                internal_issues.append(
                                    {
                                        "Chave origem": source_key,
                                        "Barramento informado": identifier,
                                        "Quantidade informada": float(
                                            row.get(
                                                "quantidade_informada"
                                            )
                                            or 0
                                        ),
                                        "Leitura": str(
                                            row.get(
                                                "modo_quantidade"
                                            )
                                            or ""
                                        ),
                                        "Contagem calculada (m)": float(
                                            row.get(
                                                "quantidade_fisica"
                                            )
                                            or 0
                                        ),
                                        "Sugestões": "",
                                    }
                                )
                                continue

                        catalog_item = internal_catalog.get(
                            mapped_code,
                            {},
                        )
                        internal_valid.append(
                            {
                                "codigo": mapped_code,
                                "chave_origem": source_key,
                                "identificador": identifier,
                                "quantidade_informada": float(
                                    row.get(
                                        "quantidade_informada"
                                    )
                                    or 0
                                ),
                                "modo_quantidade": str(
                                    row.get(
                                        "modo_quantidade"
                                    )
                                    or ""
                                ),
                                "quantidade_fisica": float(
                                    row.get(
                                        "quantidade_fisica"
                                    )
                                    or 0
                                ),
                                "descricao": str(
                                    catalog_item.get(
                                        "descricao"
                                    )
                                    or ""
                                ).strip(),
                                "medida_encontrada": matched_dimension,
                                "similaridade": similarity,
                                "vinculo": match_origin,
                                "observacao": (
                                    f"{parsed_internal['sheet']} · "
                                    f"informado {identifier} · "
                                    f"{row.get('quantidade_origem') or ''} · "
                                    f"{match_origin}"
                                ).strip(" ·"),
                            }
                        )

                    in1, in2, in3 = st.columns(3)
                    in1.metric(
                        "Itens do relatório",
                        parsed_internal["total_rows"],
                    )
                    in2.metric(
                        "Vinculados",
                        len(internal_valid),
                    )
                    in3.metric(
                        "Sem vínculo",
                        len(internal_issues),
                    )

                    st.caption(
                        "Na coluna QUANTIDADE, o valor é tratado como número "
                        "de barras e convertido por × 3 m. Se a carga indicar "
                        "MTS/METROS, o valor é usado diretamente. Medidas em "
                        "milímetros e polegadas são comparadas automaticamente."
                    )

                    if internal_valid:
                        preview_internal = pd.DataFrame(
                            [
                                {
                                    "Barramento informado": row.get(
                                        "identificador"
                                    ),
                                    "Quantidade informada": row.get(
                                        "quantidade_informada"
                                    ),
                                    "Leitura": row.get(
                                        "modo_quantidade"
                                    ),
                                    "Contagem (m)": row.get(
                                        "quantidade_fisica"
                                    ),
                                    "Código sistema": row.get(
                                        "codigo"
                                    ),
                                    "Descrição": row.get(
                                        "descricao"
                                    ),
                                    "Medida encontrada": row.get(
                                        "medida_encontrada"
                                    ),
                                    "Semelhança": (
                                        (
                                            f"{float(row.get('similaridade')):.2f}%"
                                        )
                                        if row.get("similaridade") is not None
                                        else ""
                                    ),
                                    "Vínculo": row.get(
                                        "vinculo"
                                    ),
                                }
                                for row in internal_valid
                            ]
                        )
                        st.dataframe(
                            preview_internal,
                            use_container_width=True,
                            hide_index=True,
                        )

                    if internal_issues:
                        st.warning(
                            "A importação fica bloqueada até que TODOS os itens "
                            "da contagem do almoxarifado estejam vinculados."
                        )

                        internal_options = sorted(
                            [
                                (
                                    f"{row.get('codigo')} · "
                                    f"{row.get('descricao')}"
                                )
                                for row in internal_catalog_rows
                            ]
                        )

                        mapping_rows = [
                            {
                                "ID": index,
                                "Barramento informado": issue.get(
                                    "Barramento informado"
                                ),
                                "Quantidade informada": issue.get(
                                    "Quantidade informada"
                                ),
                                "Leitura": issue.get("Leitura"),
                                "Contagem (m)": issue.get(
                                    "Contagem calculada (m)"
                                ),
                                "Sugestões encontradas": issue.get(
                                    "Sugestões"
                                ),
                                "Vincular ao código": "",
                            }
                            for index, issue in enumerate(
                                internal_issues
                            )
                        ]

                        edited_internal_maps = st.data_editor(
                            pd.DataFrame(mapping_rows),
                            use_container_width=True,
                            hide_index=True,
                            disabled=[
                                "ID",
                                "Barramento informado",
                                "Quantidade informada",
                                "Leitura",
                                "Contagem (m)",
                                "Sugestões encontradas",
                            ],
                            column_config={
                                "Vincular ao código": (
                                    st.column_config.SelectboxColumn(
                                        "Vincular ao código",
                                        options=[""] + internal_options,
                                        required=True,
                                    )
                                )
                            },
                            key="cb_internal_mapping_editor",
                        )

                        if st.button(
                            "SALVAR VÍNCULOS DO ALMOXARIFADO",
                            type="primary",
                            use_container_width=True,
                            key="cb_save_internal_maps",
                        ):
                            missing_links = edited_internal_maps[
                                edited_internal_maps[
                                    "Vincular ao código"
                                ].astype(str).str.strip() == ""
                            ]
                            if not missing_links.empty:
                                st.error(
                                    "Vincule todos os itens antes de salvar."
                                )
                            else:
                                for _, edit_row in (
                                    edited_internal_maps.iterrows()
                                ):
                                    issue = internal_issues[
                                        int(edit_row["ID"])
                                    ]
                                    selected_code = str(
                                        edit_row[
                                            "Vincular ao código"
                                        ]
                                    ).split(" · ", 1)[0].strip()

                                    db.save_cb_physical_mapping(
                                        "INTERNO_EXCEL",
                                        str(
                                            issue.get(
                                                "Chave origem"
                                            )
                                            or ""
                                        ),
                                        str(
                                            issue.get(
                                                "Barramento informado"
                                            )
                                            or ""
                                        ),
                                        selected_code,
                                    )
                                st.session_state[
                                    "_cb_count_flash"
                                ] = (
                                    "Vínculos do almoxarifado salvos."
                                )
                                st.rerun()

                    elif internal_valid and st.button(
                        "IMPORTAR CONTAGEM DO ALMOXARIFADO",
                        type="primary",
                        use_container_width=True,
                        key="cb_import_internal",
                    ):
                        for linked_row in internal_valid:
                            if str(
                                linked_row.get("vinculo")
                                or ""
                            ) not in {
                                "CÓDIGO",
                                "VÍNCULO SALVO",
                            }:
                                db.save_cb_physical_mapping(
                                    "INTERNO_EXCEL",
                                    str(
                                        linked_row.get(
                                            "chave_origem"
                                        )
                                        or ""
                                    ),
                                    str(
                                        linked_row.get(
                                            "identificador"
                                        )
                                        or ""
                                    ),
                                    str(
                                        linked_row.get("codigo")
                                        or ""
                                    ),
                                )

                        db.save_cb_counts_batch(
                            cb_month,
                            "INTERNO_EXCEL",
                            internal_file.name,
                            internal_valid,
                        )
                        st.session_state["_cb_count_flash"] = (
                            "Contagem do almoxarifado importada. "
                            "Todos os itens possuem vínculo com o sistema."
                        )
                        st.rerun()
                except Exception as exc:
                    st.error(
                        f"Não foi possível processar a contagem do almoxarifado: {exc}"
                    )

            with st.expander(
                "LANÇAMENTO MANUAL",
                expanded=False,
            ):
                manual_options = [
                    (
                        str(row.get("codigo")),
                        str(row.get("descricao") or ""),
                        (
                            "KG"
                            if row.get("categoria") == "CHAPA"
                            else "MT"
                        ),
                    )
                    for row in standby_catalog
                    if row.get("categoria") == "BARRA_COBRE"
                ]
                manual_labels = [
                    f"{code} · {description} · {unit}"
                    for code, description, unit in manual_options
                ]

                if manual_labels:
                    manual_selected = st.selectbox(
                        "Material",
                        manual_labels,
                        key="cb_manual_code",
                    )
                    manual_code = manual_selected.split(
                        " · ",
                        1,
                    )[0].strip()
                    manual_unit = next(
                        (
                            unit
                            for code, _, unit in manual_options
                            if code == manual_code
                        ),
                        "",
                    )

                    manual_qty = st.number_input(
                        f"Quantidade física ({manual_unit or 'U.M.'})",
                        min_value=0.0,
                        value=0.0,
                        step=1.0,
                        format="%.6f",
                        key="cb_manual_qty",
                    )
                    manual_obs = st.text_input(
                        "Observação",
                        key="cb_manual_obs",
                    )

                    if st.button(
                        "SALVAR CONTAGEM MANUAL",
                        type="primary",
                        use_container_width=True,
                        key="cb_save_manual",
                    ):
                        db.save_cb_count(
                            cb_month,
                            "INTERNO_MANUAL",
                            manual_code,
                            manual_qty,
                            manual_obs,
                            "Lançamento manual no aplicativo",
                        )
                        st.session_state["_cb_count_flash"] = (
                            "Contagem manual salva."
                        )
                        st.rerun()

        flash_count = st.session_state.pop(
            "_cb_count_flash",
            None,
        )
        if flash_count:
            st.success(flash_count)

        if cb_imports:
            with st.expander("IMPORTAÇÕES DA COMPETÊNCIA"):
                imports_view = pd.DataFrame(cb_imports)
                if not imports_view.empty:
                    imports_view["fonte"] = imports_view[
                        "fonte"
                    ].map(
                        lambda value: CB_SOURCE_LABELS.get(
                            str(value),
                            str(value),
                        )
                    )
                    st.dataframe(
                        imports_view[
                            [
                                "fonte",
                                "arquivo_nome",
                                "linhas",
                                "importado_em",
                            ]
                        ].rename(
                            columns={
                                "fonte": "Fonte",
                                "arquivo_nome": "Arquivo",
                                "linhas": "Linhas",
                                "importado_em": "Importado em",
                            }
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )

        st.markdown(
            '<div class="topic-divider"></div>',
            unsafe_allow_html=True,
        )
        section_band(
            "02 · CONFERÊNCIA",
            "FECHAMENTO × CONTAGEM FÍSICA",
            "Diferença = Contagem física − menor saldo entre Fechamento e Atual. Isso evita repetir baixas já refletidas no saldo atual. Barras com |diferença| < 3 m são aceitas automaticamente.",
        )

        cb_adjustment_snapshot = pd.DataFrame()
        cb_missing_count = 0

        if not cb_closing_stock_items and not cb_counts:
            st.info(
                "A base final será formada quando houver saldo no Analítico "
                "ou alguma contagem física vinculada."
            )
        else:
            reconciliation = build_cb_reconciliation(
                cb_closing_stock_items,
                cb_current_stock_items,
                cb_catalog,
                cb_counts,
            )
            movement_comparison = reconciliation.copy()

            if not reconciliation.empty:
                saldo_num = pd.to_numeric(
                    reconciliation["Saldo fechamento"],
                    errors="coerce",
                ).fillna(0)
                saldo_atual_num = pd.to_numeric(
                    reconciliation["Saldo atual"],
                    errors="coerce",
                ).fillna(0)
                variacao_num = pd.to_numeric(
                    reconciliation["Variação atual x fechamento"],
                    errors="coerce",
                ).fillna(0)
                fisico_num = pd.to_numeric(
                    reconciliation["Físico"],
                    errors="coerce",
                ).fillna(0)
                diff_num = pd.to_numeric(
                    reconciliation["Diferença Qtd"],
                    errors="coerce",
                ).fillna(0)

                useful_mask = (
                    saldo_num.abs().gt(1e-9)
                    | saldo_atual_num.abs().gt(1e-9)
                    | variacao_num.abs().gt(1e-9)
                    | fisico_num.abs().gt(1e-9)
                    | diff_num.abs().gt(1e-9)
                )
                reconciliation = reconciliation[
                    useful_mask
                ].copy()

                # Barras com diferença inferior a uma barra padrão (3 m),
                # para mais ou para menos, são aceitas automaticamente e
                # deixam de compor a análise ativa.
                if "Tolerância automática" in reconciliation.columns:
                    reconciliation = reconciliation[
                        ~reconciliation[
                            "Tolerância automática"
                        ].fillna(False)
                    ].copy()

            if not movement_comparison.empty:
                _movement_view = movement_comparison.copy()
                _movement_view["Variação atual x fechamento"] = pd.to_numeric(
                    _movement_view["Variação atual x fechamento"],
                    errors="coerce",
                ).fillna(0)
                _movement_view = _movement_view[
                    _movement_view["Variação atual x fechamento"].abs() > 1e-9
                ].copy()

                if not _movement_view.empty:
                    _inc = int(
                        (_movement_view["Variação atual x fechamento"] > 0).sum()
                    )
                    _dec = int(
                        (_movement_view["Variação atual x fechamento"] < 0).sum()
                    )
                    st.caption(
                        f"MOVIMENTAÇÃO DESDE O FECHAMENTO: {_inc} ITEM(NS) AUMENTARAM "
                        f"E {_dec} ITEM(NS) REDUZIRAM O SALDO."
                    )
                    with st.expander(
                        "DETALHAR MOVIMENTAÇÃO · SALDO ATUAL × FECHAMENTO",
                        expanded=False,
                    ):
                        _movement_display = _movement_view[
                            [
                                "Categoria",
                                "Código",
                                "Descrição",
                                "U.M.",
                                "Saldo fechamento",
                                "Saldo atual",
                                "Variação atual x fechamento",
                                "Saldo base ajuste",
                                "Base usada",
                            ]
                        ].sort_values(
                            "Variação atual x fechamento",
                            ascending=False,
                        )
                        st.dataframe(
                            _movement_display,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "Saldo fechamento": st.column_config.NumberColumn(
                                    "Saldo fechamento",
                                    format="localized",
                                ),
                                "Saldo atual": st.column_config.NumberColumn(
                                    "Saldo atual",
                                    format="localized",
                                ),
                                "Variação atual x fechamento": st.column_config.NumberColumn(
                                    "Variação atual x fechamento",
                                    format="localized",
                                ),
                                "Saldo base ajuste": st.column_config.NumberColumn(
                                    "Saldo base ajuste",
                                    format="localized",
                                    help="Menor saldo entre Fechamento e Atual.",
                                ),
                            },
                        )

            excluded_codes = {
                str(row.get("codigo") or "").strip()
                for row in cb_exclusions
                if bool(row.get("ativo", True))
            }

            reconciliation_all = reconciliation.copy()

            if excluded_codes and not reconciliation.empty:
                reconciliation = reconciliation[
                    ~reconciliation["Código"].astype(str).isin(
                        excluded_codes
                    )
                ].copy()

            if not reconciliation.empty:
                cb_missing_count = int(
                    (reconciliation["Status"] == "SEM CONTAGEM").sum()
                )
                cb_adjustment_snapshot = reconciliation[
                    reconciliation["Status"] == "DIVERGÊNCIA"
                ].copy()

            if reconciliation.empty:
                st.info(
                    "Nenhum material com saldo, contagem ou diferença "
                    "permanece na análise desta competência."
                )
            else:
                if "cb_filter_applied_category" not in st.session_state:
                    st.session_state["cb_filter_applied_category"] = "TODOS"
                if "cb_filter_applied_status" not in st.session_state:
                    st.session_state["cb_filter_applied_status"] = "TODOS"
                if "cb_filter_applied_search" not in st.session_state:
                    st.session_state["cb_filter_applied_search"] = ""

                with st.form(
                    "cb_filters_form",
                    clear_on_submit=False,
                ):
                    (
                        filter_col1,
                        filter_col2,
                        filter_col3,
                        filter_col4,
                    ) = st.columns(
                        [1.05, 1.05, 1.35, 0.72]
                    )

                    with filter_col1:
                        draft_category = st.selectbox(
                            "Categoria",
                            [
                                "TODOS",
                                "CHAPA",
                                "BARRA DE COBRE",
                            ],
                            index=[
                                "TODOS",
                                "CHAPA",
                                "BARRA DE COBRE",
                            ].index(
                                st.session_state[
                                    "cb_filter_applied_category"
                                ]
                            ),
                            key="cb_filter_draft_category",
                        )

                    with filter_col2:
                        draft_status = st.selectbox(
                            "Status",
                            [
                                "TODOS",
                                "DIVERGÊNCIA",
                                "CONFERIDO",
                                "SEM CONTAGEM",
                            ],
                            index=[
                                "TODOS",
                                "DIVERGÊNCIA",
                                "CONFERIDO",
                                "SEM CONTAGEM",
                            ].index(
                                st.session_state[
                                    "cb_filter_applied_status"
                                ]
                            ),
                            key="cb_filter_draft_status",
                        )

                    with filter_col3:
                        draft_search = st.text_input(
                            "Código ou descrição",
                            value=st.session_state[
                                "cb_filter_applied_search"
                            ],
                            placeholder="Filtrar material",
                            key="cb_filter_draft_search",
                        ).strip()

                    with filter_col4:
                        st.markdown(
                            '<div style="height:28px"></div>',
                            unsafe_allow_html=True,
                        )
                        apply_filters = st.form_submit_button(
                            "APLICAR",
                            use_container_width=True,
                        )

                if apply_filters:
                    st.session_state[
                        "cb_filter_applied_category"
                    ] = draft_category
                    st.session_state[
                        "cb_filter_applied_status"
                    ] = draft_status
                    st.session_state[
                        "cb_filter_applied_search"
                    ] = draft_search

                filter_category = st.session_state[
                    "cb_filter_applied_category"
                ]
                filter_status = st.session_state[
                    "cb_filter_applied_status"
                ]
                filter_search = st.session_state[
                    "cb_filter_applied_search"
                ]

                shown = reconciliation.copy()

                if filter_category != "TODOS":
                    shown = shown[
                        shown["Categoria"] == filter_category
                    ]

                if filter_status != "TODOS":
                    shown = shown[
                        shown["Status"] == filter_status
                    ]

                if filter_search:
                    needle = filter_search.upper()
                    shown = shown[
                        shown["Código"].astype(str).str.upper().str.contains(
                            needle,
                            regex=False,
                        )
                        | shown["Descrição"].astype(str).str.upper().str.contains(
                            needle,
                            regex=False,
                        )
                    ]

                filtered_counted_mask = shown["Físico"].notna()
                filtered_divergent_mask = (
                    shown["Status"] == "DIVERGÊNCIA"
                )
                filtered_divergence_total = float(
                    shown.loc[
                        filtered_divergent_mask,
                        "Diferença R$",
                    ].fillna(0).abs().sum()
                )

                st.markdown(
                    cb_kpi_html(
                        len(shown),
                        int(filtered_counted_mask.sum()),
                        int(filtered_divergent_mask.sum()),
                        filtered_divergence_total,
                    ),
                    unsafe_allow_html=True,
                )

                shown_display = shown.copy()

                # Mantém os dados auxiliares no cálculo, mas não ocupa a
                # grade operacional com colunas que não precisam ser conferidas.
                shown_display = shown_display.drop(
                    columns=[
                        "ARMZ",
                        "Custo unitário",
                        "Origem custo",
                        "Fontes físicas",
                        "Tolerância automática",
                        "Contagem assumida zero",
                    ],
                    errors="ignore",
                )

                # Mantém todas as colunas quantitativas como números
                # reais. Isso permite classificação matemática correta no
                # data_editor e evita ordenação lexicográfica de textos.
                for col in [
                    "Saldo fechamento",
                    "Saldo atual",
                    "Variação atual x fechamento",
                    "Saldo base ajuste",
                    "Físico",
                    "Consumo informado",
                    "Diferença Qtd",
                    "Diferença R$",
                ]:
                    if col in shown_display.columns:
                        shown_display[col] = pd.to_numeric(
                            shown_display[col],
                            errors="coerce",
                        ).fillna(0.0)

                shown_display.insert(
                    0,
                    "Remover",
                    False,
                )

                with st.form(
                    "cb_remove_analysis_form",
                    clear_on_submit=False,
                ):
                    editable = st.data_editor(
                        shown_display,
                        use_container_width=True,
                        hide_index=True,
                        disabled=[
                            col
                            for col in shown_display.columns
                            if col != "Remover"
                        ],
                        column_config={
                            "Remover": st.column_config.CheckboxColumn(
                                "Remover",
                                help=(
                                    "Marque todos os itens desejados. "
                                    "A tela só será atualizada ao confirmar."
                                ),
                            ),
                            "Saldo fechamento": st.column_config.NumberColumn(
                                "Saldo fechamento",
                                format="localized",
                                help="Base oficial do cálculo. Posição do último dia da competência.",
                            ),
                            "Saldo atual": st.column_config.NumberColumn(
                                "Saldo atual",
                                format="localized",
                                help="Saldo do Analítico atual.",
                            ),
                            "Variação atual x fechamento": st.column_config.NumberColumn(
                                "Variação atual x fechamento",
                                format="localized",
                                help="Saldo atual menos saldo do fechamento.",
                            ),
                            "Saldo base ajuste": st.column_config.NumberColumn(
                                "Saldo base ajuste",
                                format="localized",
                                help="Menor saldo entre Fechamento e Atual. É a base usada para calcular a diferença.",
                            ),
                            "Base usada": st.column_config.TextColumn(
                                "Base usada",
                                help="ATUAL quando o saldo atual é menor; FECHAMENTO nos demais casos.",
                            ),
                            "Físico": st.column_config.NumberColumn(
                                "Físico",
                                format="localized",
                            ),
                            "Consumo informado": st.column_config.NumberColumn(
                                "Consumo informado",
                                format="localized",
                            ),
                            "Diferença Qtd": st.column_config.NumberColumn(
                                "Diferença Qtd",
                                format="localized",
                            ),
                            "Diferença R$": st.column_config.NumberColumn(
                                "Diferença R$",
                                format="R$ %.2f",
                            ),
                        },
                        key="cb_reconciliation_editor",
                    )

                    remove_submitted = st.form_submit_button(
                        "REMOVER SELECIONADOS DA ANÁLISE",
                        type="secondary",
                        use_container_width=True,
                    )

                if remove_submitted:
                    selected_to_remove = editable[
                        editable["Remover"] == True
                    ]

                    if selected_to_remove.empty:
                        st.warning(
                            "Selecione pelo menos um item para remover."
                        )
                    else:
                        for code in selected_to_remove[
                            "Código"
                        ].astype(str):
                            db.set_cb_exclusion(
                                cb_month,
                                code,
                                True,
                                "REMOVIDO MANUALMENTE NA CONFERÊNCIA",
                            )

                        st.session_state["_cb_count_flash"] = (
                            f"{len(selected_to_remove)} item(ns) removido(s) "
                            "da análise desta competência."
                        )
                        st.rerun()

            if excluded_codes:
                excluded_view = reconciliation_all[
                    reconciliation_all["Código"].astype(str).isin(
                        excluded_codes
                    )
                ].copy()

                with st.expander(
                    f"REMOVIDOS DA ANÁLISE · {len(excluded_codes)}",
                    expanded=False,
                ):
                    restore_options = [
                        (
                            f"{row['Código']} · {row['Descrição']}"
                        )
                        for _, row in excluded_view.iterrows()
                    ]

                    if restore_options:
                        restore_selected = st.selectbox(
                            "Restaurar item",
                            restore_options,
                            key="cb_restore_item",
                        )
                        restore_code = restore_selected.split(
                            " · ",
                            1,
                        )[0].strip()

                        if st.button(
                            "RESTAURAR NA ANÁLISE",
                            use_container_width=True,
                            key="cb_restore_analysis_item",
                        ):
                            db.set_cb_exclusion(
                                cb_month,
                                restore_code,
                                False,
                                "",
                            )
                            st.rerun()

        st.markdown(
            '<div class="topic-divider"></div>',
            unsafe_allow_html=True,
        )
        section_band(
            "03 · FINALIZAÇÃO",
            "REGISTRO MENSAL DOS AJUSTES",
            "Ao finalizar, o sistema grava uma fotografia dos ajustes de Chapas em KG e Barramentos em MT, incluindo a previsão financeira. O histórico permanece separado por competência.",
        )

        _adj_chapa = (
            cb_adjustment_snapshot[
                cb_adjustment_snapshot["Categoria"] == "CHAPA"
            ].copy()
            if not cb_adjustment_snapshot.empty
            else pd.DataFrame()
        )
        _adj_barra = (
            cb_adjustment_snapshot[
                cb_adjustment_snapshot["Categoria"] == "BARRA DE COBRE"
            ].copy()
            if not cb_adjustment_snapshot.empty
            else pd.DataFrame()
        )

        def _adj_sum(frame, column):
            if frame.empty or column not in frame.columns:
                return 0.0
            return float(
                pd.to_numeric(
                    frame[column],
                    errors="coerce",
                ).fillna(0).sum()
            )

        _chapa_qtd_prev = _adj_sum(_adj_chapa, "Diferença Qtd")
        _chapa_val_prev = _adj_sum(_adj_chapa, "Diferença R$")
        _barra_qtd_prev = _adj_sum(_adj_barra, "Diferença Qtd")
        _barra_val_prev = _adj_sum(_adj_barra, "Diferença R$")
        _total_val_prev = _chapa_val_prev + _barra_val_prev

        _fp1, _fp2, _fp3, _fp4, _fp5 = st.columns(5)
        _fp1.metric(
            "CHAPAS · AJUSTE",
            f"{_chapa_qtd_prev:+,.3f} KG"
            .replace(",", "X").replace(".", ",").replace("X", "."),
        )
        _fp2.metric(
            "CHAPAS · PREVISÃO",
            money_br(_chapa_val_prev),
        )
        _fp3.metric(
            "BARRAMENTOS · AJUSTE",
            f"{_barra_qtd_prev:+,.3f} MT"
            .replace(",", "X").replace(".", ",").replace("X", "."),
        )
        _fp4.metric(
            "BARRAMENTOS · PREVISÃO",
            money_br(_barra_val_prev),
        )
        _fp5.metric(
            "IMPACTO LÍQUIDO PREVISTO",
            money_br(_total_val_prev),
        )

        st.caption(
            "SINAL POSITIVO = entrada/acréscimo de estoque · "
            "SINAL NEGATIVO = baixa/redução. A previsão em R$ usa o custo "
            "unitário registrado na conferência no momento da finalização."
        )

        try:
            _adjustment_history = db.list_cb_adjustment_history()
            _adjustment_history_error = ""
        except Exception as exc:
            _adjustment_history = []
            _adjustment_history_error = str(exc)

        _current_adjustment_record = next(
            (
                row
                for row in _adjustment_history
                if str(row.get("competencia") or "")[:10]
                == cb_month.isoformat()
            ),
            None,
        )

        if _current_adjustment_record:
            st.success(
                "AJUSTES DE "
                + month_label(cb_month)
                + " JÁ REGISTRADOS · última gravação "
                + central_data.format_dt(
                    _current_adjustment_record.get("atualizado_em")
                    or _current_adjustment_record.get("finalizado_em")
                )
            )

        _can_finalize_adjustments = (
            bool(cb_closing_stock_items)
            and cb_missing_count == 0
        )

        if cb_missing_count > 0:
            st.warning(
                f"Existem {cb_missing_count} material(is) sem contagem. "
                "O registro mensal só é liberado após concluir ou remover "
                "essas pendências da análise."
            )
        elif not cb_closing_stock_items:
            st.warning(
                "Carregue o saldo do fechamento antes de registrar os ajustes."
            )

        _finalize_label = (
            "ATUALIZAR REGISTRO DOS AJUSTES"
            if _current_adjustment_record
            else "FINALIZAR E REGISTRAR AJUSTES"
        )

        if st.button(
            _finalize_label,
            type="primary",
            use_container_width=True,
            disabled=not _can_finalize_adjustments,
            key="cb_finalize_adjustments",
        ):
            _rows_to_save = (
                cb_adjustment_snapshot.to_dict("records")
                if not cb_adjustment_snapshot.empty
                else []
            )
            db.finalize_cb_adjustments(
                cb_month,
                closing_date(cb_month),
                _rows_to_save,
            )
            st.session_state["_cb_count_flash"] = (
                "Ajustes de "
                + month_label(cb_month)
                + " registrados no histórico mensal."
            )
            st.rerun()

        if _adjustment_history_error:
            st.warning(
                "Não foi possível carregar o histórico de ajustes: "
                + _adjustment_history_error
            )
        elif _adjustment_history:
            with st.expander(
                "HISTÓRICO DE AJUSTES · MÊS A MÊS",
                expanded=False,
            ):
                _history_rows = []
                for row in _adjustment_history:
                    _comp = pd.to_datetime(
                        row.get("competencia"),
                        errors="coerce",
                    )
                    _label = (
                        month_label(_comp.date())
                        if not pd.isna(_comp)
                        else str(row.get("competencia") or "")
                    )
                    _history_rows.append(
                        {
                            "Competência": _label,
                            "Chapas · ajuste (KG)": (
                                float(row.get("chapas_entrada_qtd") or 0)
                                - float(row.get("chapas_saida_qtd") or 0)
                            ),
                            "Chapas · previsão (R$)": (
                                float(row.get("chapas_entrada_valor") or 0)
                                - float(row.get("chapas_saida_valor") or 0)
                            ),
                            "Barramentos · ajuste (MT)": (
                                float(row.get("barramentos_entrada_qtd") or 0)
                                - float(row.get("barramentos_saida_qtd") or 0)
                            ),
                            "Barramentos · previsão (R$)": (
                                float(row.get("barramentos_entrada_valor") or 0)
                                - float(row.get("barramentos_saida_valor") or 0)
                            ),
                            "Impacto líquido (R$)": float(
                                row.get("previsao_valor_liquido") or 0
                            ),
                            "Movimentação prevista (R$)": float(
                                row.get("previsao_valor_movimentado") or 0
                            ),
                            "Itens": int(row.get("itens_ajuste") or 0),
                            "Finalizado em": central_data.format_dt(
                                row.get("finalizado_em")
                            ),
                        }
                    )

                st.dataframe(
                    pd.DataFrame(_history_rows),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Chapas · ajuste (KG)": st.column_config.NumberColumn(
                            "Chapas · ajuste (KG)",
                            format="localized",
                        ),
                        "Chapas · previsão (R$)": st.column_config.NumberColumn(
                            "Chapas · previsão (R$)",
                            format="R$ %.2f",
                        ),
                        "Barramentos · ajuste (MT)": st.column_config.NumberColumn(
                            "Barramentos · ajuste (MT)",
                            format="localized",
                        ),
                        "Barramentos · previsão (R$)": st.column_config.NumberColumn(
                            "Barramentos · previsão (R$)",
                            format="R$ %.2f",
                        ),
                        "Impacto líquido (R$)": st.column_config.NumberColumn(
                            "Impacto líquido (R$)",
                            format="R$ %.2f",
                        ),
                        "Movimentação prevista (R$)": st.column_config.NumberColumn(
                            "Movimentação prevista (R$)",
                            format="R$ %.2f",
                        ),
                    },
                )

                _history_month_options = [
                    str(row.get("competencia") or "")[:10]
                    for row in _adjustment_history
                ]
                _history_month_selected = st.selectbox(
                    "Detalhar competência",
                    _history_month_options,
                    format_func=lambda value: month_label(
                        date.fromisoformat(value)
                    ),
                    key="cb_adjustment_history_month",
                )

                try:
                    _history_items = db.list_cb_adjustment_items(
                        _history_month_selected
                    )
                except Exception as exc:
                    _history_items = []
                    st.warning(
                        "Não foi possível carregar os itens do histórico: "
                        + str(exc)
                    )

                if _history_items:
                    _history_items_df = pd.DataFrame(_history_items).rename(
                        columns={
                            "codigo": "Código",
                            "categoria": "Categoria",
                            "descricao": "Descrição",
                            "um": "U.M.",
                            "saldo_fechamento": "Saldo fechamento",
                            "fisico": "Físico",
                            "diferenca_qtd": "Ajuste Qtd",
                            "custo_unitario": "Custo unitário",
                            "previsao_valor": "Previsão R$",
                        }
                    )
                    st.dataframe(
                        _history_items_df[
                            [
                                "Categoria",
                                "Código",
                                "Descrição",
                                "U.M.",
                                "Saldo fechamento",
                                "Físico",
                                "Ajuste Qtd",
                                "Custo unitário",
                                "Previsão R$",
                            ]
                        ],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Saldo fechamento": st.column_config.NumberColumn(
                                "Saldo fechamento",
                                format="localized",
                            ),
                            "Físico": st.column_config.NumberColumn(
                                "Físico",
                                format="localized",
                            ),
                            "Ajuste Qtd": st.column_config.NumberColumn(
                                "Ajuste Qtd",
                                format="localized",
                            ),
                            "Custo unitário": st.column_config.NumberColumn(
                                "Custo unitário",
                                format="R$ %.4f",
                            ),
                            "Previsão R$": st.column_config.NumberColumn(
                                "Previsão R$",
                                format="R$ %.2f",
                            ),
                        },
                    )

elif page == "Conferência de baixas":
    st.markdown(
        '<div class="section-title">Conferência de baixas</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="module-hero">
            <strong>Módulo destinado à validação das baixas que impactam o fechamento.</strong>
            <span>As fontes, chaves e regras da conferência serão definidas depois.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info("Estrutura criada. Ainda não há regra de conferência aplicada.")


elif page == "Análise de movimentações":
    st.markdown(
        '<div class="section-title">Análise de movimentações</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="module-hero">
            <strong>As movimentações ainda não foram definidas.</strong>
            <span>Por enquanto, este módulo permanece sem cálculos para não assumir regras antes da validação do processo.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


else:
    st.markdown(
        '<div class="section-title">CONFIGURAÇÕES</div>',
        unsafe_allow_html=True,
    )

    tab_api, tab_menu, tab_rules = st.tabs(
        ["STATUS API", "MENU", "REGRAS"]
    )

    with tab_api:
        section_band(
            "01 · FONTES",
            "CENTRAL DE DADOS",
            "Monitoramento centralizado de todas as conexões automáticas do ecossistema Setta.",
        )

        if api_sources_error:
            st.error(
                "NÃO FOI POSSÍVEL CONSULTAR O STATUS DAS FONTES: "
                + api_sources_error
            )
        else:
            last_update_values = [
                str(row.get("last_update_at") or "")
                for row in api_sources
                if row.get("last_update_at")
            ]
            last_update = (
                max(last_update_values)
                if last_update_values
                else ""
            )

            st.markdown(
                f"""
                <div class="api-overview">
                    <div class="api-overview-card">
                        <div class="api-overview-label">STATUS GERAL</div>
                        <div class="api-overview-value">{api_summary["status"]}</div>
                    </div>
                    <div class="api-overview-card">
                        <div class="api-overview-label">FONTES</div>
                        <div class="api-overview-value">{api_summary["total"]}</div>
                    </div>
                    <div class="api-overview-card">
                        <div class="api-overview-label">ATUALIZADAS</div>
                        <div class="api-overview-value">{api_summary["healthy"]}</div>
                    </div>
                    <div class="api-overview-card">
                        <div class="api-overview-label">ÚLTIMA ATUALIZAÇÃO</div>
                        <div class="api-overview-value" style="font-size:.82rem">
                            {html.escape(central_data.format_dt(last_update))}
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.markdown(
                api_status_cards_html(api_sources),
                unsafe_allow_html=True,
            )

        control_a, control_b, control_c = st.columns(3)

        if control_a.button(
            "ATUALIZAR STATUS",
            use_container_width=True,
            key="fm_refresh_api_status",
        ):
            load_api_sources.clear()
            st.rerun()

        if control_b.button(
            "REPROCESSAR ANALÍTICO",
            use_container_width=True,
            key="fm_reprocess_analitico",
        ):
            load_central_analitico.clear()
            load_api_sources.clear()
            st.session_state["_force_central_fm"] = True
            st.rerun()

        if control_c.button(
            "REPROCESSAR CADASTROS",
            use_container_width=True,
            key="fm_reprocess_cadastros",
        ):
            load_central_cadastros.clear()
            result = central_cadastros_context(force=True)
            load_api_sources.clear()
            if result.get("available"):
                st.session_state["_api_flash"] = (
                    "CADASTROS REPROCESSADO COM SUCESSO."
                )
            else:
                st.session_state["_api_flash"] = (
                    "FALHA AO REPROCESSAR CADASTROS: "
                    + str(result.get("error") or "")
                )
            st.rerun()

        api_flash = st.session_state.pop(
            "_api_flash",
            None,
        )
        if api_flash:
            if api_flash.startswith("FALHA"):
                st.error(api_flash)
            else:
                st.success(api_flash)

        st.markdown(
            '<div class="topic-divider"></div>',
            unsafe_allow_html=True,
        )
        section_band(
            "02 · CONTINGÊNCIA",
            "ALIMENTAÇÃO E RECUPERAÇÃO",
            "As telas operacionais não exibem mais detalhes de conexão. Alimentação manual e recuperação ficam concentradas aqui.",
        )

        render_manual_contingency(imports_by_month)

    with tab_menu:
        section_band(
            "01 · NAVEGAÇÃO",
            "NOMES DOS BOTÕES",
            "Altere somente o texto exibido no menu lateral. A identificação interna das páginas permanece fixa para preservar a navegação e as regras do aplicativo.",
        )

        current_menu_labels = cfg.get("menu_labels") or {}

        with st.form("fm_menu_labels_form"):
            edited_menu_labels = {}

            for internal_page in PAGES:
                edited_menu_labels[internal_page] = st.text_input(
                    internal_page.upper(),
                    value=str(
                        current_menu_labels.get(
                            internal_page,
                            DEFAULT_CONFIG["menu_labels"].get(
                                internal_page,
                                internal_page,
                            ),
                        )
                    ),
                    key=(
                        "cfg_menu_"
                        + internal_page.lower()
                        .replace(" ", "_")
                        .replace("ç", "c")
                        .replace("ã", "a")
                        .replace("á", "a")
                        .replace("é", "e")
                    ),
                )

            save_menu = st.form_submit_button(
                "SALVAR NOMES DO MENU",
                type="primary",
                use_container_width=True,
            )

        if save_menu:
            normalized_menu_labels = {
                internal_page: (
                    str(
                        edited_menu_labels.get(
                            internal_page,
                            "",
                        )
                    ).strip()
                    or DEFAULT_CONFIG["menu_labels"].get(
                        internal_page,
                        internal_page,
                    )
                )
                for internal_page in PAGES
            }

            new_config = {
                **cfg,
                "menu_labels": normalized_menu_labels,
            }

            try:
                db.save_config(new_config)
                st.session_state.app_cfg = new_config
                st.session_state["_menu_cfg_saved"] = True
                st.rerun()
            except Exception as exc:
                st.error(
                    "NÃO FOI POSSÍVEL SALVAR OS NOMES DO MENU: "
                    + str(exc)
                )

        if st.session_state.pop(
            "_menu_cfg_saved",
            False,
        ):
            st.success(
                "NOMES DO MENU ATUALIZADOS COM SUCESSO."
            )

        if st.button(
            "RESTAURAR NOMES PADRÃO",
            use_container_width=True,
            key="fm_restore_menu_labels",
        ):
            restored_config = {
                **cfg,
                "menu_labels": {
                    **DEFAULT_CONFIG["menu_labels"],
                },
            }
            try:
                db.save_config(restored_config)
                st.session_state.app_cfg = restored_config
                st.rerun()
            except Exception as exc:
                st.error(
                    "NÃO FOI POSSÍVEL RESTAURAR O MENU: "
                    + str(exc)
                )

    with tab_rules:
        section_band(
            "01 · REGRAS",
            "VALIDAÇÃO DO ANALÍTICO",
            "",
        )
        st.markdown(
            """
            - CODIGO, TP, ARMZ, SALDO EM ESTOQUE E VALOR EM ESTOQUE SÃO OBRIGATÓRIOS.
            - SALDO OU VALOR NEGATIVO BLOQUEIA SOMENTE A GRAVAÇÃO DO FECHAMENTO.
            - TP OU ARMZ VAZIO BLOQUEIA SOMENTE A GRAVAÇÃO DO FECHAMENTO.
            - CÓDIGO DUPLICADO NO MESMO ARMAZÉM BLOQUEIA SOMENTE A GRAVAÇÃO DO FECHAMENTO.
            - ANÁLISES, COMPARAÇÕES E CONFERÊNCIAS CONTINUAM DISPONÍVEIS MESMO COM INCONSISTÊNCIAS.
            """
        )


st.markdown(
    '<div class="footer">SETTA | Fechamento Mensal de Inventário</div>',
    unsafe_allow_html=True,
)
