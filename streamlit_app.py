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
from report_parser import parse_inventory_report
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


st.set_page_config(
    page_title="FECHAMENTO MENSAL | SETTA",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)


def browser_icon():
    try:
        visual = db.load_nfs_visual_config()
        data = str(visual.get("favicon_data") or "").strip()
        if data:
            raw = base64.b64decode(data, validate=True)
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


def month_start(value: date | datetime) -> date:
    return date(value.year, value.month, 1)


def previous_month(value: date) -> date:
    if value.month == 1:
        return date(value.year - 1, 12, 1)
    return date(value.year, value.month - 1, 1)


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


if "app_cfg" not in st.session_state:
    try:
        remote_cfg = db.load_config()
    except Exception:
        remote_cfg = {}

    try:
        nfs_visual = db.load_nfs_visual_config()
    except Exception:
        nfs_visual = {}

    try:
        fallback_logo_data = base64.b64encode(
            (ROOT / "config" / "logo_setta.svg").read_bytes()
        ).decode()
    except Exception:
        fallback_logo_data = ""

    default_logo_data = str(
        nfs_visual.get("logo_data") or fallback_logo_data
    )
    default_logo_mime = str(
        nfs_visual.get("logo_mime") or "image/svg+xml"
    )

    st.session_state.app_cfg = {
        **DEFAULT_CONFIG,
        "logo_data": default_logo_data,
        "logo_mime": default_logo_mime,
        **remote_cfg,
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

    st.markdown('<div class="sidebar-section-label">Navegação</div>', unsafe_allow_html=True)

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
    st.markdown('<div class="sidebar-section-label">Operador</div>', unsafe_allow_html=True)
    st.session_state.operator = st.text_input(
        "Nome do operador",
        value=st.session_state.operator,
        label_visibility="collapsed",
        placeholder="Informe o operador",
    )

    st.divider()
    st.markdown('<div class="sidebar-section-label">Identidade visual</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="sidebar-logo-preview">{logo_html(str(cfg.get("logo_data") or ""), str(cfg.get("logo_mime") or "image/svg+xml"))}</div>',
        unsafe_allow_html=True,
    )
    st.caption("Padrão visual Setta / NFS.")

    st.divider()
    st.markdown('<div class="sidebar-section-label">Informações</div>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="sidebar-info-card">
            <b>Data operacional</b><br>{datetime.now(TZ):%d/%m/%Y}<br><br>
            <b>Módulo</b><br>Fechamento mensal de inventário<br><br>
            <b>Alimentação</b><br>Relatório analítico de estoque<br><br>
            <b>Versão</b><br>Protótipo 0.3
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

try:
    imports = db.list_inventory_imports()
    summaries = db.list_inventory_summaries()
    data_error = ""
except Exception as exc:
    imports = []
    summaries = []
    data_error = str(exc)

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

    with st.expander("IMPORTAR NOVO FECHAMENTO", expanded=not visible_months):
        st.caption(
            "ALIMENTAÇÃO: o histórico é abastecido pelo relatório analítico de estoque. "
            "O sistema utiliza ARMZ para identificar o armazém, TP para o tipo do produto "
            "e VALOR EM ESTOQUE para o valor financeiro. O relatório deve conter também "
            "CODIGO e SALDO EM ESTOQUE e será bloqueado se houver saldo/custo zerado, "
            "negativo ou campos obrigatórios ausentes."
        )

        col_a, col_b = st.columns([0.8, 1.8])
        with col_a:
            competencia_input = st.date_input(
                "Competência",
                value=month_start(datetime.now(TZ).date()),
                format="DD/MM/YYYY",
                help="O dia é desconsiderado; a competência é gravada pelo mês/ano.",
            )
            competencia_input = month_start(competencia_input)
        with col_b:
            uploaded = st.file_uploader(
                "Relatório analítico",
                type=["xlsx", "xltx"],
                accept_multiple_files=False,
                help="O relatório deve conter CODIGO, TP, ARMZ, SALDO EM ESTOQUE e VALOR EM ESTOQUE.",
            )

        if uploaded is not None:
            try:
                parsed = parse_inventory_report(uploaded.getvalue(), uploaded.name)

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Linhas válidas", f"{parsed['valid_rows']:,}".replace(",", "."))
                m2.metric("Erros", parsed["invalid_rows"])
                m3.metric("Armazéns", len(parsed["warehouses"]))
                m4.metric("Valor válido", money_br(parsed["total_value"]))

                st.caption(
                    "Armazéns identificados: "
                    + ", ".join(parsed["warehouses"])
                    + " | Tipos identificados: "
                    + ", ".join(parsed["product_types"])
                )

                if parsed["errors"]:
                    st.error(
                        "IMPORTAÇÃO BLOQUEADA. O relatório possui produto sem saldo, sem custo, "
                        "valor/saldo negativo, TP/ARMZ ausente ou duplicidade. Corrija o relatório "
                        "antes de continuar a análise."
                    )
                    error_df = pd.DataFrame(parsed["errors"])
                    columns = [
                        column
                        for column in [
                            "linha",
                            "codigo",
                            "tp",
                            "armz",
                            "saldo",
                            "valor_estoque",
                            "descricao",
                            "motivo",
                        ]
                        if column in error_df.columns
                    ]
                    st.dataframe(
                        error_df[columns],
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    existing = imports_by_month.get(competencia_input.isoformat())
                    if existing:
                        st.warning(
                            f"Já existe fechamento para {month_label(competencia_input)}. "
                            "Ao confirmar, o relatório anterior será substituído."
                        )

                    if st.button(
                        "VALIDAR E IMPORTAR FECHAMENTO",
                        type="primary",
                        use_container_width=True,
                    ):
                        try:
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
                        except Exception as exc:
                            st.error(f"Não foi possível importar o fechamento: {exc}")
            except Exception as exc:
                st.error(f"Relatório inválido: {exc}")

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
            st.error(
                f"{month_label(selected_month)} possui pendência de qualidade no relatório "
                f"({int(import_info.get('linhas_invalidas') or 0)} item(ns)). "
                "A análise detalhada desta competência fica bloqueada até a correção."
            )
            historical_errors = db.list_import_errors(selected_month)
            if historical_errors:
                st.dataframe(
                    pd.DataFrame(historical_errors),
                    use_container_width=True,
                    hide_index=True,
                )
        else:
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


elif page == "Conferência de chapas e barramentos":
    st.markdown(
        '<div class="section-title">Conferência de chapas e barramentos</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="module-hero">
            <strong>Módulo preparado para a conferência física e sistêmica de chapas e barramentos.</strong>
            <span>As regras específicas serão definidas na próxima etapa.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info("Estrutura criada. Ainda não há regra de conferência aplicada.")


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
    st.markdown('<div class="section-title">Configurações</div>', unsafe_allow_html=True)
    st.caption(
        "As alterações desta página são persistidas no Supabase. "
        "A página atual e a competência analisada permanecem na URL."
    )

    with st.container(border=True):
        st.markdown("#### Identidade do aplicativo")
        title = st.text_input(
            "Título principal",
            value=str(cfg.get("title") or DEFAULT_CONFIG["title"]),
        )
        subtitle = st.text_input(
            "Subtítulo",
            value=str(cfg.get("subtitle") or DEFAULT_CONFIG["subtitle"]),
        )
        sidebar_title = st.text_input(
            "Título da barra lateral",
            value=str(cfg.get("sidebar_title") or DEFAULT_CONFIG["sidebar_title"]),
        )
        sidebar_subtitle = st.text_input(
            "Subtítulo da barra lateral",
            value=str(cfg.get("sidebar_subtitle") or DEFAULT_CONFIG["sidebar_subtitle"]),
        )

        if st.button("SALVAR CONFIGURAÇÕES", type="primary", use_container_width=True):
            new_cfg = dict(cfg)
            new_cfg.update(
                {
                    "title": title.strip() or DEFAULT_CONFIG["title"],
                    "subtitle": subtitle.strip() or DEFAULT_CONFIG["subtitle"],
                    "sidebar_title": sidebar_title.strip() or DEFAULT_CONFIG["sidebar_title"],
                    "sidebar_subtitle": sidebar_subtitle.strip() or DEFAULT_CONFIG["sidebar_subtitle"],
                }
            )
            try:
                db.save_config(new_cfg)
                st.session_state.app_cfg = {
                    **DEFAULT_CONFIG,
                    **new_cfg,
                }
                st.success("Configurações salvas permanentemente.")
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível salvar as configurações: {exc}")

    with st.container(border=True):
        st.markdown("#### Logo da empresa")
        st.caption(
            "A logo é exibida nas mesmas dimensões utilizadas no aplicativo de NFs. "
            "Ao trocar a imagem, o tamanho do card e o limite visual da logo permanecem fixos."
        )

        current_logo = str(cfg.get("logo_data") or "").strip()
        current_logo_mime = str(cfg.get("logo_mime") or "image/svg+xml")
        if current_logo:
            st.markdown(
                f'<div class="logo-preview"><img src="data:{current_logo_mime};base64,{current_logo}"></div>',
                unsafe_allow_html=True,
            )

        logo_upload = st.file_uploader(
            "Selecionar nova logo",
            type=["png", "jpg", "jpeg", "svg"],
            key="fm_logo_upload",
        )

        if logo_upload is not None:
            raw_logo = logo_upload.getvalue()
            if len(raw_logo) > 1_500_000:
                st.error("Logo acima de 1,5 MB.")
            else:
                mime = (
                    logo_upload.type
                    or (
                        "image/svg+xml"
                        if logo_upload.name.lower().endswith(".svg")
                        else "image/png"
                    )
                )
                encoded = base64.b64encode(raw_logo).decode()
                st.markdown(
                    f'<div class="logo-preview"><img src="data:{mime};base64,{encoded}"></div>',
                    unsafe_allow_html=True,
                )

                if st.button(
                    "SALVAR NOVA LOGO",
                    type="primary",
                    use_container_width=True,
                    key="save_fm_logo",
                ):
                    new_cfg = dict(cfg)
                    new_cfg.update(
                        logo_data=encoded,
                        logo_mime=mime,
                    )
                    try:
                        db.save_config(new_cfg)
                        st.session_state.app_cfg = {
                            **DEFAULT_CONFIG,
                            **new_cfg,
                        }
                        st.success("Nova logo salva permanentemente.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Não foi possível salvar a logo: {exc}")

        if st.button(
            "RESTAURAR LOGO PADRÃO SETTA",
            use_container_width=True,
            key="restore_fm_logo",
        ):
            try:
                default_logo = base64.b64encode(
                    (ROOT / "config" / "logo_setta.svg").read_bytes()
                ).decode()
                new_cfg = dict(cfg)
                new_cfg.update(
                    logo_data=default_logo,
                    logo_mime="image/svg+xml",
                )
                db.save_config(new_cfg)
                st.session_state.app_cfg = {
                    **DEFAULT_CONFIG,
                    **new_cfg,
                }
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível restaurar a logo padrão: {exc}")

    with st.container(border=True):
        st.markdown("#### Regras obrigatórias do relatório")
        st.markdown(
            """
            - CODIGO, TP, ARMZ, SALDO EM ESTOQUE e VALOR EM ESTOQUE são obrigatórios.
            - Produto sem saldo não é aceito.
            - Produto sem custo/valor não é aceito.
            - Saldo ou valor negativo não é aceito.
            - TP e ARMZ vazios não são aceitos.
            - Código duplicado no mesmo armazém bloqueia a importação.
            """
        )

    with st.container(border=True):
        st.markdown("#### Ícone do navegador")
        st.info(
            "O favicon continua sincronizado com o ícone efetivamente salvo no aplicativo NFS Setta."
        )


st.markdown(
    '<div class="footer">SETTA | Fechamento Mensal de Inventário</div>',
    unsafe_allow_html=True,
)
