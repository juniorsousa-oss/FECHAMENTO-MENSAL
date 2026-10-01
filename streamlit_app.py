from __future__ import annotations

import base64
import io
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

import inventory_db as db
import central_fechamento_data as central_data
from report_parser import parse_inventory_report, parse_inventory_balance_report
from cb_parser import (
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

DEFAULT_CONFIG = {
    "title": "FECHAMENTO MENSAL",
    "subtitle": "Inventário • Conferências • Baixas • Movimentações • Fechamento",
    "sidebar_title": "FECHAMENTO MENSAL",
    "sidebar_subtitle": "Análises de inventário",
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
    "INTERNO_EXCEL": "SETOR INTERNO · EXCEL",
    "INTERNO_MANUAL": "SETOR INTERNO · MANUAL",
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



def month_start(value: date | datetime) -> date:
    return date(value.year, value.month, 1)


def previous_month(value: date) -> date:
    if value.month == 1:
        return date(value.year - 1, 12, 1)
    return date(value.year, value.month - 1, 1)


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
    stock_items: list[dict],
    catalog: list[dict],
    counts: list[dict],
) -> pd.DataFrame:
    confirmed_catalog = {
        str(row.get("codigo") or "").strip(): row
        for row in catalog
        if bool(row.get("ativo", True))
        and str(row.get("status") or "").upper() == "CONFIRMADO"
    }

    base_by_code: dict[str, dict] = {}
    for codigo, item in confirmed_catalog.items():
        base_by_code[codigo] = {
            "codigo": codigo,
            "descricao": str(item.get("descricao") or "").strip(),
            "categoria": str(item.get("categoria") or "").strip(),
            "unidade": str(item.get("unidade") or "").strip(),
            "ult_preco": float(item.get("ult_preco") or 0),
            "armz": set(),
            "saldo_sistema": 0.0,
        }

    for row in stock_items:
        codigo = normalize_code(row.get("codigo"))
        if codigo not in base_by_code:
            continue

        current = base_by_code[codigo]
        if not current["descricao"]:
            current["descricao"] = str(
                row.get("descricao") or ""
            ).strip()

        armz = str(row.get("armz") or "").strip()
        if armz:
            current["armz"].add(armz)

        current["saldo_sistema"] += float(row.get("saldo") or 0)

    counts_by_code: dict[str, list[dict]] = {}
    for row in counts:
        codigo = normalize_code(row.get("codigo"))
        if codigo not in confirmed_catalog:
            continue
        counts_by_code.setdefault(codigo, []).append(row)

    result: list[dict] = []

    for codigo, item in sorted(base_by_code.items()):
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

        saldo = max(float(item["saldo_sistema"] or 0), 0.0)
        custo_unitario = float(item["ult_preco"] or 0)
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

        source_parts = []
        for row in item_counts:
            source_label = CB_SOURCE_LABELS.get(
                str(row.get("fonte") or ""),
                str(row.get("fonte") or ""),
            )
            source_parts.append(
                f"{source_label}: "
                + f"{float(row.get('quantidade_fisica') or 0):,.3f}"
                .replace(",", "X")
                .replace(".", ",")
                .replace("X", ".")
            )

        divergencia_qtd = (
            None if physical is None else physical - saldo
        )
        divergencia_rs = (
            None
            if divergencia_qtd is None or custo_unitario <= 0
            else divergencia_qtd * custo_unitario
        )

        if physical is None:
            status = "SEM CONTAGEM"
        elif abs(float(divergencia_qtd or 0)) <= 1e-9:
            status = "CONFERIDO"
        else:
            status = "DIVERGÊNCIA"

        if (
            physical is not None
            and saldo <= 0
            and physical > 0
        ):
            status = "DIVERGÊNCIA"

        result.append(
            {
                "Categoria": (
                    "CHAPA"
                    if item["categoria"] == "CHAPA"
                    else "BARRA DE COBRE"
                ),
                "Código": codigo,
                "Descrição": item["descricao"],
                "U.M.": item["unidade"],
                "ARMZ": ", ".join(sorted(item["armz"])),
                "Saldo sistema": saldo,
                "Físico": physical,
                "Divergência Qtd": divergencia_qtd,
                "Custo unitário": custo_unitario,
                "Origem custo": custo_origem,
                "Divergência R$": divergencia_rs,
                "Fontes físicas": " | ".join(source_parts),
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
            <div class="cb-kpi-label">DIVERGÊNCIA EM R$</div>
            <div class="cb-kpi-value">{money_br(divergence_rs)}</div>
            <div class="cb-kpi-note">Físico − sistema × custo unitário</div>
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

    st.session_state.app_cfg = {
        **DEFAULT_CONFIG,
        **remote_cfg,
        "logo_data": default_logo_data,
        "logo_mime": default_logo_mime,
    }

if "operator" not in st.session_state:
    st.session_state.operator = ""

cfg = st.session_state.app_cfg

query_page = str(st.query_params.get("pagina", "") or "").strip()
if "nav_page" not in st.session_state:
    st.session_state.nav_page = query_page if query_page in PAGES else PAGES[0]

with st.sidebar:
    st.markdown(
        f"""
        <div class="sidebar-brand">
            <div class="sidebar-brand-title">{cfg["sidebar_title"]}</div>
            <div class="sidebar-brand-sub">{cfg["sidebar_subtitle"]}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="sidebar-section-label">NAVEGAÇÃO</div>', unsafe_allow_html=True)

    page = st.radio(
        "Página",
        PAGES,
        label_visibility="collapsed",
        key="nav_page",
        format_func=lambda item: item.upper(),
    )

    if str(st.query_params.get("pagina", "") or "") != page:
        st.query_params["pagina"] = page

    st.divider()
    st.markdown('<div class="sidebar-section-label">OPERADOR</div>', unsafe_allow_html=True)
    st.session_state.operator = st.text_input(
        "Nome do operador",
        value=st.session_state.operator,
        label_visibility="collapsed",
        placeholder="INFORME O OPERADOR",
    )

    st.divider()
    st.markdown(
        """
        <div class="sidebar-info-card">
            <b>CENTRAL DE DADOS</b><br>
            ALIMENTAÇÃO AUTOMÁTICA<br>
            ANALÍTICO
        </div>
        """,
        unsafe_allow_html=True,
    )


st.markdown(
    f'<div class="setta-logo-card">{logo_html(str(cfg.get("logo_data") or ""), str(cfg.get("logo_mime") or "image/svg+xml"))}</div>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<h1 class="app-title">{cfg["title"]} | SETTA</h1>',
    unsafe_allow_html=True,
)
st.markdown(f'<p class="app-sub">{cfg["subtitle"]}</p>', unsafe_allow_html=True)

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
    st.markdown('<div class="section-title">Dashboard de estoque mensal</div>', unsafe_allow_html=True)
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

    st.markdown('<div class="topic-divider"></div>', unsafe_allow_html=True)
    section_band(
        "06 · FONTES",
        "CENTRAL DE DADOS",
        "",
    )
    render_central_status(central_context)
    if central_context.get("error"):
        st.warning(str(central_context.get("error")))



elif page == "Conferência de chapas e barramentos":
    st.markdown(
        '<div class="section-title">CONFERÊNCIA DE CHAPAS E BARRAMENTOS</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="module-hero">
            <strong>CONFERÊNCIA FÍSICO × SISTEMA</strong>
            <span>
                O CADASTROS define o universo de materiais. Neste módulo, o Relatório
                Analítico fornece somente o SALDO EM ESTOQUE da competência.
                O físico é formado pelas fontes de Chapas, Barramentos e Almoxarifado.
                Materiais novos passam por validação e, depois de confirmados, permanecem
                automaticamente na base dos próximos fechamentos.
            </span>
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
        )
        st.query_params["mes_cb"] = cb_month.strftime("%Y-%m")

        try:
            cb_stock_items = db.list_cb_system_balances(cb_month)
            cb_catalog = db.list_cb_catalog()
            cb_counts = db.list_cb_counts(cb_month)
            cb_mappings = db.list_cb_sheet_mappings()
            cb_imports = db.list_cb_imports(cb_month)
            cb_error = ""
        except Exception as exc:
            cb_stock_items = []
            cb_catalog = []
            cb_counts = []
            cb_mappings = []
            cb_imports = []
            cb_error = str(exc)

        if cb_error:
            st.error(
                f"Não foi possível carregar a conferência: {cb_error}"
            )

        if cb_month == current_competencia and central_balance_preview:
            cb_stock_items = central_balance_preview

        confirmed_catalog = [
            row
            for row in cb_catalog
            if str(row.get("status") or "").upper() == "CONFIRMADO"
        ]
        candidate_catalog = [
            row
            for row in cb_catalog
            if str(row.get("status") or "").upper() == "CANDIDATO"
        ]

        st.markdown(
            '<div class="topic-divider"></div>',
            unsafe_allow_html=True,
        )
        section_band(
            "01 · BASE MESTRE",
            "CADASTRO DE CHAPAS E BARRAS DE COBRE",
            "O CADASTROS fornece principalmente CÓDIGO e DESCRIÇÃO, com REFERÊNCIA e ÚLT. PREÇO quando disponíveis. CHAPA é sempre KG e BARRAMENTO é sempre MT. Novos candidatos só entram na base após validação.",
        )

        base_col1, base_col2, base_col3 = st.columns(3)
        base_col1.metric(
            "ITENS CONFIRMADOS",
            len(confirmed_catalog),
        )
        base_col2.metric(
            "NOVOS CANDIDATOS",
            len(candidate_catalog),
        )
        base_col3.metric(
            "SALDO SISTEMA",
            "OK" if cb_stock_items else "PENDENTE",
        )

        cadastro_file = st.file_uploader(
            "Atualizar base pelo relatório CADASTROS",
            type=["xlsx", "xltx"],
            key="cb_cadastros_file",
            help=(
                "O arquivo é reprocessado a cada fechamento. Novos códigos de chapa "
                "ou barra de cobre entram como candidatos para validação."
            ),
        )

        if cadastro_file is not None:
            try:
                cadastro_bytes = cadastro_file.getvalue()
                with st.spinner(
                    "Lendo somente os materiais candidatos a chapas e barras..."
                ):
                    parsed_cad = cached_parse_cadastros(
                        cadastro_bytes,
                        cadastro_file.name,
                    )

                ca, cb, cc, cd = st.columns(4)
                ca.metric(
                    "Base conhecida",
                    parsed_cad.get("known_codes_found", 0),
                )
                cb.metric(
                    "Novos candidatos",
                    parsed_cad.get("new_candidates_found", 0),
                )
                cc.metric(
                    "Total chapa/barra",
                    parsed_cad["total_candidates"],
                )
                cd.metric(
                    "Linhas descartadas",
                    parsed_cad.get("rows_discarded", 0),
                )

                if st.button(
                    "SINCRONIZAR CADASTROS",
                    type="primary",
                    use_container_width=True,
                    key="cb_sync_cad",
                ):
                    db.sync_cb_catalog(
                        parsed_cad["candidates"]
                    )
                    st.session_state["_cb_base_flash"] = (
                        "CADASTROS sincronizado. Novos materiais foram "
                        "incluídos como candidatos."
                    )
                    st.rerun()
            except Exception as exc:
                st.error(
                    f"Não foi possível ler o CADASTROS: {exc}"
                )

        flash_base = st.session_state.pop(
            "_cb_base_flash",
            None,
        )
        if flash_base:
            st.success(flash_base)

        if candidate_catalog:
            with st.expander(
                f"NOVOS MATERIAIS PARA VALIDAR ({len(candidate_catalog)})",
                expanded=True,
            ):
                select_all_candidates = st.checkbox(
                    "SELECIONAR TODOS",
                    value=True,
                    key="cb_select_all_candidates",
                    help=(
                        "Marcado por padrão. Desmarque para limpar a seleção "
                        "e escolher somente os materiais desejados."
                    ),
                )

                candidate_df = pd.DataFrame(
                    [
                        {
                            "Selecionar": bool(
                                select_all_candidates
                            ),
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
                            "Regra": row.get("regra_detectada"),
                        }
                        for row in candidate_catalog
                    ]
                )

                edited_candidates = st.data_editor(
                    candidate_df,
                    use_container_width=True,
                    hide_index=True,
                    disabled=[
                        "Código",
                        "Descrição",
                        "Referência",
                        "Últ. preço",
                        "Regra",
                    ],
                    column_config={
                        "Selecionar": st.column_config.CheckboxColumn(
                            "Selecionar"
                        ),
                        "Categoria": st.column_config.SelectboxColumn(
                            "Categoria",
                            options=[
                                "CHAPA",
                                "BARRA DE COBRE",
                            ],
                        ),
                    },
                    key="cb_candidates_editor",
                )

                selected_candidates = edited_candidates[
                    edited_candidates["Selecionar"] == True
                ]

                action_col1, action_col2 = st.columns(2)
                if action_col1.button(
                    "CONFIRMAR SELECIONADOS",
                    type="primary",
                    use_container_width=True,
                    key="cb_confirm_candidates",
                ):
                    if selected_candidates.empty:
                        st.warning(
                            "Selecione pelo menos um material."
                        )
                    else:
                        for _, row in selected_candidates.iterrows():
                            db.update_cb_catalog_status(
                                str(row["Código"]),
                                (
                                    "CHAPA"
                                    if row["Categoria"] == "CHAPA"
                                    else "BARRA_COBRE"
                                ),
                                "CONFIRMADO",
                            )
                        st.rerun()

                if action_col2.button(
                    "IGNORAR SELECIONADOS",
                    use_container_width=True,
                    key="cb_ignore_candidates",
                ):
                    if selected_candidates.empty:
                        st.warning(
                            "Selecione pelo menos um material."
                        )
                    else:
                        catalog_lookup = {
                            str(row.get("codigo")): row
                            for row in candidate_catalog
                        }
                        for _, row in selected_candidates.iterrows():
                            original = catalog_lookup.get(
                                str(row["Código"]),
                                {},
                            )
                            db.update_cb_catalog_status(
                                str(row["Código"]),
                                str(
                                    original.get("categoria")
                                    or "CHAPA"
                                ),
                                "IGNORADO",
                            )
                        st.rerun()

        if not cb_stock_items:
            st.warning(
                "A competência selecionada ainda não possui o SALDO SISTÊMICO "
                "da conferência de chapas e barramentos. Carregue abaixo o Relatório "
                "Analítico. Esta carga é independente do fechamento geral."
            )

            cb_analytic_file = st.file_uploader(
                "Carregar Relatório Analítico para saldo sistêmico",
                type=["xlsx", "xltx"],
                key="cb_analytic_file",
                help=(
                    "Neste módulo são usados apenas CODIGO e SALDO EM ESTOQUE. "
                    "Saldo negativo é convertido para zero. Valor/custo não bloqueia a carga."
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
                        "Nesta carga não são validados TP, custo, valor em estoque "
                        "ou regras do fechamento geral."
                    )

                    if st.button(
                        "SALVAR SALDO SISTÊMICO DESTA COMPETÊNCIA",
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
                            "Saldo sistêmico da conferência salvo."
                        )
                        st.rerun()
                except Exception as exc:
                    st.error(
                        f"Não foi possível ler o Relatório Analítico: {exc}"
                    )

        st.markdown(
            '<div class="topic-divider"></div>',
            unsafe_allow_html=True,
        )
        section_band(
            "02 · ALIMENTAÇÃO FÍSICA",
            "RECEBER CONTAGENS",
            "CHAPAS usa o e-mail .EML; BARRAMENTOS usa o Excel da produção; o setor interno aceita Excel ou lançamento manual. As fontes são complementares e são somadas por código.",
        )

        st.markdown(
            """
            <div class="cb-source-grid">
                <div class="cb-source-card">
                    <div class="cb-source-title">CHAPAS · E-MAIL</div>
                    <div class="cb-source-text">
                        Leitura automática da tabela DIMENSÃO / DESCRIÇÃO / CHAPAS / PESO TOTAL.
                        CHAPAS são sempre conferidas em KG, usando diretamente o PESO TOTAL informado no e-mail.
                    </div>
                    <div class="cb-source-tag">.EML AUTOMÁTICO</div>
                </div>
                <div class="cb-source-card">
                    <div class="cb-source-title">BARRAMENTOS · PRODUÇÃO</div>
                    <div class="cb-source-text">
                        Leitura automática de CODIGO, Barras (m) e Processado (m).
                        Físico Produção = Barras + Processado.
                    </div>
                    <div class="cb-source-tag">EXCEL AUTOMÁTICO</div>
                </div>
                <div class="cb-source-card">
                    <div class="cb-source-title">SETOR INTERNO</div>
                    <div class="cb-source-text">
                        Excel flexível com CODIGO + MTS/METROS/QUANTIDADE ou lançamento manual.
                        Essa parcela é somada às demais fontes do mesmo código.
                    </div>
                    <div class="cb-source-tag">EXCEL + MANUAL</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        tab_email, tab_bar, tab_internal = st.tabs(
            [
                "CHAPAS · E-MAIL",
                "BARRAMENTOS · EXCEL",
                "SETOR INTERNO",
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
                        st.caption(
                            "Competência detectada no e-mail: "
                            + month_label(detected_comp)
                            + f" · {parsed_email['tables_found']} tabela(s) de histórico encontrada(s)"
                        )

                    resolved_email = resolve_chapa_rows(
                        parsed_email["rows"],
                        cb_mappings,
                        cb_catalog,
                    )

                    em1, em2, em3 = st.columns(3)
                    em1.metric(
                        "Linhas do e-mail",
                        len(parsed_email["rows"]),
                    )
                    em2.metric(
                        "Vinculadas",
                        len(resolved_email["resolved"]),
                    )
                    em3.metric(
                        "Não vinculadas",
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
                            for row in cb_catalog
                            if row.get("categoria") == "CHAPA"
                            and row.get("status") == "CONFIRMADO"
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
                                    "Não há códigos de CHAPA confirmados na base mestre."
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
                                "A competência do e-mail não corresponde à "
                                "competência selecionada no módulo."
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
            )

            if bar_file is not None:
                try:
                    parsed_bar = parse_barramentos_excel(
                        bar_file.getvalue(),
                        bar_file.name,
                    )

                    catalog_bar = {
                        str(row.get("codigo")): row
                        for row in cb_catalog
                        if row.get("categoria") == "BARRA_COBRE"
                        and row.get("status") == "CONFIRMADO"
                    }

                    valid_bar_rows = []
                    bar_issues = []
                    for row in parsed_bar["rows"]:
                        code = normalize_code(row.get("codigo"))
                        item = catalog_bar.get(code)
                        if item is None:
                            bar_issues.append(
                                {
                                    "Código": code,
                                    "Modelo": row.get("modelo"),
                                    "Motivo": "CÓDIGO NÃO CONFIRMADO NA BASE MESTRE",
                                }
                            )
                            continue

                        valid_bar_rows.append(
                            {
                                "codigo": code,
                                "quantidade_fisica": float(
                                    row.get(
                                        "quantidade_fisica"
                                    )
                                    or 0
                                ),
                                "observacao": (
                                    f"{row.get('modelo') or ''} · "
                                    f"Barras {float(row.get('barras') or 0):.3f} m · "
                                    f"Processado {float(row.get('processado') or 0):.3f} m"
                                ),
                            }
                        )

                    br1, br2, br3 = st.columns(3)
                    br1.metric(
                        "Códigos encontrados",
                        parsed_bar["total_rows"],
                    )
                    br2.metric(
                        "Prontos para importar",
                        len(valid_bar_rows),
                    )
                    br3.metric(
                        "Pendências",
                        len(bar_issues),
                    )

                    if valid_bar_rows:
                        st.dataframe(
                            pd.DataFrame(valid_bar_rows).rename(
                                columns={
                                    "codigo": "Código",
                                    "quantidade_fisica": "Físico produção (m)",
                                    "observacao": "Detalhe",
                                }
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )

                    if bar_issues:
                        st.error(
                            "Existem códigos novos/não confirmados ou com "
                            "unidade incompatível. Atualize/valide a base mestre "
                            "antes de importar esta fonte."
                        )
                        st.dataframe(
                            pd.DataFrame(bar_issues),
                            use_container_width=True,
                            hide_index=True,
                        )
                    elif st.button(
                        "IMPORTAR BARRAMENTOS DA PRODUÇÃO",
                        type="primary",
                        use_container_width=True,
                        key="cb_import_bars",
                    ):
                        db.save_cb_counts_batch(
                            cb_month,
                            "BARRAMENTOS_EXCEL",
                            bar_file.name,
                            valid_bar_rows,
                        )
                        st.session_state["_cb_count_flash"] = (
                            "Contagem da produção de barramentos importada."
                        )
                        st.rerun()
                except Exception as exc:
                    st.error(
                        f"Não foi possível ler a planilha de barramentos: {exc}"
                    )

        with tab_internal:
            internal_file = st.file_uploader(
                "Planilha do setor interno",
                type=["xlsx", "xltx"],
                key="cb_internal_file",
                help=(
                    "O leitor procura automaticamente uma estrutura com "
                    "CODIGO e MTS/METROS/QUANTIDADE."
                ),
            )

            if internal_file is not None:
                try:
                    parsed_internal = parse_interno_excel(
                        internal_file.getvalue(),
                        internal_file.name,
                    )

                    confirmed_codes = {
                        str(row.get("codigo"))
                        for row in confirmed_catalog
                    }
                    internal_valid = []
                    internal_issues = []

                    for row in parsed_internal["rows"]:
                        code = normalize_code(row.get("codigo"))
                        if code not in confirmed_codes:
                            internal_issues.append(
                                {
                                    "Código": code,
                                    "Motivo": "CÓDIGO NÃO CONFIRMADO NA BASE MESTRE",
                                }
                            )
                        else:
                            internal_valid.append(
                                {
                                    "codigo": code,
                                    "quantidade_fisica": float(
                                        row.get(
                                            "quantidade_fisica"
                                        )
                                        or 0
                                    ),
                                    "observacao": (
                                        f"{parsed_internal['sheet']} · "
                                        f"coluna {parsed_internal['quantity_label']}"
                                    ),
                                }
                            )

                    in1, in2, in3 = st.columns(3)
                    in1.metric(
                        "Códigos encontrados",
                        parsed_internal["total_rows"],
                    )
                    in2.metric(
                        "Prontos para importar",
                        len(internal_valid),
                    )
                    in3.metric(
                        "Pendências",
                        len(internal_issues),
                    )

                    if internal_valid:
                        st.dataframe(
                            pd.DataFrame(internal_valid).rename(
                                columns={
                                    "codigo": "Código",
                                    "quantidade_fisica": "Físico interno",
                                    "observacao": "Origem",
                                }
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )

                    if internal_issues:
                        st.error(
                            "Existem códigos ainda não confirmados na base mestre."
                        )
                        st.dataframe(
                            pd.DataFrame(internal_issues),
                            use_container_width=True,
                            hide_index=True,
                        )
                    elif st.button(
                        "IMPORTAR CONTAGEM INTERNA",
                        type="primary",
                        use_container_width=True,
                        key="cb_import_internal",
                    ):
                        db.save_cb_counts_batch(
                            cb_month,
                            "INTERNO_EXCEL",
                            internal_file.name,
                            internal_valid,
                        )
                        st.session_state["_cb_count_flash"] = (
                            "Contagem interna importada."
                        )
                        st.rerun()
                except Exception as exc:
                    st.error(
                        f"Não foi possível ler a planilha interna: {exc}"
                    )

            st.markdown("#### LANÇAMENTO MANUAL")

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
                for row in confirmed_catalog
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
            "03 · CONFERÊNCIA",
            "CONSOLIDADO FÍSICO × SISTEMA",
            "Divergência Qtd = Físico − Sistema. O saldo sistêmico vem exclusivamente de SALDO EM ESTOQUE e valores negativos são tratados como zero. As fontes físicas são complementares e somadas por código. A estimativa em R$ usa o Últ. Preço do CADASTROS.",
        )

        if not cb_stock_items:
            st.info(
                "A conferência será liberada após o SALDO EM ESTOQUE "
                "do Relatório Analítico estar disponível nesta competência."
            )
        else:
            reconciliation = build_cb_reconciliation(
                cb_stock_items,
                cb_catalog,
                cb_counts,
            )

            if reconciliation.empty:
                st.info(
                    "Ainda não existem materiais confirmados na base mestre."
                )
            else:
                counted_mask = reconciliation["Físico"].notna()
                divergent_mask = (
                    reconciliation["Status"] == "DIVERGÊNCIA"
                )
                divergence_total = float(
                    reconciliation.loc[
                        divergent_mask,
                        "Divergência R$",
                    ].fillna(0).sum()
                )

                st.markdown(
                    cb_kpi_html(
                        len(reconciliation),
                        int(counted_mask.sum()),
                        int(divergent_mask.sum()),
                        divergence_total,
                    ),
                    unsafe_allow_html=True,
                )

                filter_category = st.multiselect(
                    "Categoria",
                    ["CHAPA", "BARRA DE COBRE"],
                    default=["CHAPA", "BARRA DE COBRE"],
                    key="cb_category_filter",
                )
                filter_status = st.multiselect(
                    "Status",
                    [
                        "DIVERGÊNCIA",
                        "CONFERIDO",
                        "SEM CONTAGEM",
                    ],
                    default=[
                        "DIVERGÊNCIA",
                        "CONFERIDO",
                        "SEM CONTAGEM",
                    ],
                    key="cb_status_filter",
                )

                shown = reconciliation[
                    reconciliation["Categoria"].isin(
                        filter_category
                    )
                    & reconciliation["Status"].isin(
                        filter_status
                    )
                ].copy()

                for col in [
                    "Saldo sistema",
                    "Físico",
                    "Divergência Qtd",
                ]:
                    shown[col] = shown[col].map(
                        lambda value: (
                            ""
                            if pd.isna(value)
                            else f"{float(value):,.6f}"
                            .replace(",", "X")
                            .replace(".", ",")
                            .replace("X", ".")
                        )
                    )

                for col in [
                    "Custo unitário",
                    "Divergência R$",
                ]:
                    shown[col] = shown[col].map(
                        lambda value: (
                            ""
                            if pd.isna(value)
                            else money_br(value)
                        )
                    )

                st.dataframe(
                    shown,
                    use_container_width=True,
                    hide_index=True,
                )

                st.markdown(
                    '<div class="topic-divider"></div>',
                    unsafe_allow_html=True,
                )
                section_band(
                    "04 · TRATATIVAS",
                    "PENDÊNCIAS DO FECHAMENTO",
                    "Exibe somente materiais com divergência ou sem contagem física para facilitar a correção antes do fechamento.",
                )

                pending = reconciliation[
                    reconciliation["Status"].isin(
                        ["DIVERGÊNCIA", "SEM CONTAGEM"]
                    )
                ].copy()

                if pending.empty:
                    st.success(
                        "Nenhuma pendência de chapas ou barramentos nesta competência."
                    )
                else:
                    st.dataframe(
                        pending[
                            [
                                "Categoria",
                                "Código",
                                "Descrição",
                                "U.M.",
                                "Saldo sistema",
                                "Físico",
                                "Divergência Qtd",
                                "Divergência R$",
                                "Status",
                            ]
                        ],
                        use_container_width=True,
                        hide_index=True,
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
    st.markdown('<div class="section-title">CONFIGURAÇÕES</div>', unsafe_allow_html=True)

    tab_api, tab_rules = st.tabs(
        ["ACOMPANHAMENTO DE API", "REGRAS"]
    )

    with tab_api:
        section_band(
            "01 · FONTES",
            "CENTRAL DE DADOS",
            "",
        )
        render_central_status(central_context)

        if central_context.get("error"):
            st.warning(str(central_context.get("error")))

        if st.button(
            "REPROCESSAR FONTE",
            use_container_width=True,
            key="fm_reprocess_central",
        ):
            load_central_analitico.clear()
            st.session_state["_force_central_fm"] = True
            st.rerun()

        render_manual_contingency(imports_by_month)

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
