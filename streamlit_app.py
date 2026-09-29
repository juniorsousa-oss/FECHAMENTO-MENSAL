from __future__ import annotations

import base64
import io
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from PIL import Image

import db
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
    """Usa o favicon efetivamente salvo e exibido hoje no NFS Setta."""
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
    return date(value.year - 1, 12, 1) if value.month == 1 else date(value.year, value.month - 1, 1)


def next_month(value: date) -> date:
    return date(value.year + 1, 1, 1) if value.month == 12 else date(value.year, value.month + 1, 1)


def month_label(value: date) -> str:
    return f"{MONTHS_PT[value.month]}/{value.year}"


def money_br(value: object) -> str:
    try:
        number = float(value or 0)
    except Exception:
        number = 0.0
    sign = "-" if number < 0 else ""
    text = f"{abs(number):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sign}R$ {text}"


def percent_br(value: object) -> str:
    try:
        number = float(value or 0)
    except Exception:
        number = 0.0
    return f"{number:.2f}%".replace(".", ",")


def value_class(value: object) -> str:
    try:
        number = float(value or 0)
    except Exception:
        return ""
    if number < 0:
        return " negative"
    if number > 0:
        return " positive"
    return ""


def inventory_row(label: str, value: str, css_class: str = "") -> str:
    return (
        '<div class="inventory-row">'
        f'<div class="inventory-label">{label}</div>'
        f'<div class="inventory-value{css_class}">{value}</div>'
        "</div>"
    )


def movement_column(title: str, rows: list[tuple[str, float]]) -> str:
    body = []
    for label, value in rows:
        body.append(
            '<div class="mov-row">'
            f'<div class="mov-label">{label}</div>'
            f'<div class="mov-value{value_class(value)}">{money_br(value)}</div>'
            "</div>"
        )
    return (
        '<div class="mov-col">'
        f'<div class="mov-head">{title}</div>'
        + "".join(body)
        + "</div>"
    )


def blank_month(competencia: date, previous: dict | None = None) -> dict:
    previous = previous or {}
    return {
        "competencia": competencia.isoformat(),
        "faturamento": 0.0,
        "ei_s2": float(previous.get("ef_s2") or 0),
        "ef_s2": 0.0,
        "baixa_op_s2": 0.0,
        "ajustes_s2": 0.0,
        "compras_s2": 0.0,
        "transferencias_s2": 0.0,
        "vendas_s2": 0.0,
        "ei_ep": float(previous.get("ef_ep") or 0),
        "ef_ep": 0.0,
        "ei_pa": float(previous.get("ef_pa") or 0),
        "ef_pa": 0.0,
        "observacao": "",
    }


def month_totals(record: dict) -> dict:
    ei_s2 = float(record.get("ei_s2") or 0)
    ef_s2 = float(record.get("ef_s2") or 0)
    ei_ep = float(record.get("ei_ep") or 0)
    ef_ep = float(record.get("ef_ep") or 0)
    ei_pa = float(record.get("ei_pa") or 0)
    ef_pa = float(record.get("ef_pa") or 0)
    faturamento = float(record.get("faturamento") or 0)
    baixa = float(record.get("baixa_op_s2") or 0)

    ei_total = ei_s2 + ei_ep + ei_pa
    ef_total = ef_s2 + ef_ep + ef_pa
    variacao = ef_total - ei_total
    percentual_div = -(ei_total / ef_total * 100) if ef_total else 0.0
    percentual_produto_fat = abs(baixa) / faturamento * 100 if faturamento else 0.0

    return {
        "ei_total": ei_total,
        "ef_total": ef_total,
        "variacao": variacao,
        "percentual_div": percentual_div,
        "percentual_produto_fat": percentual_produto_fat,
        "resumo_s2": ef_s2 - ei_s2,
        "resumo_ep": ef_ep - ei_ep,
        "resumo_pa": ef_pa - ei_pa,
    }


if "app_cfg" not in st.session_state:
    try:
        remote_cfg = db.load_config()
    except Exception:
        remote_cfg = {}
    st.session_state.app_cfg = {**DEFAULT_CONFIG, **remote_cfg}

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
        f'<div class="sidebar-logo-preview">{logo_html()}</div>',
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
            <b>Persistência</b><br>Supabase habilitado<br><br>
            <b>Versão</b><br>Protótipo 0.2
        </div>
        """,
        unsafe_allow_html=True,
    )


st.markdown(f'<div class="setta-logo-card">{logo_html()}</div>', unsafe_allow_html=True)
st.markdown(
    f'<h1 class="app-title">{cfg["title"]} | SETTA</h1>',
    unsafe_allow_html=True,
)
st.markdown(f'<p class="app-sub">{cfg["subtitle"]}</p>', unsafe_allow_html=True)

try:
    month_rows = db.list_months()
    db_error = ""
except Exception as exc:
    month_rows = []
    db_error = str(exc)

month_by_key = {
    str(row.get("competencia") or "")[:10]: row
    for row in month_rows
    if str(row.get("competencia") or "").strip()
}

today_month = month_start(datetime.now(TZ).date())
first_option = date(today_month.year - 2, 1, 1)
last_option = date(today_month.year + 1, 12, 1)

month_options = []
cursor = first_option
while cursor <= last_option:
    month_options.append(cursor)
    cursor = next_month(cursor)

query_month = str(st.query_params.get("mes", "") or "").strip()
try:
    query_month_date = date.fromisoformat(query_month + "-01") if len(query_month) == 7 else None
except Exception:
    query_month_date = None

default_month = query_month_date if query_month_date in month_options else today_month

if "selected_month" not in st.session_state:
    st.session_state.selected_month = default_month


if page == "Dashboard":
    st.markdown('<div class="section-title">Dashboard mensal</div>', unsafe_allow_html=True)

    top1, top2 = st.columns([1.55, 1])
    with top1:
        selected_month = st.selectbox(
            "Competência",
            month_options,
            index=month_options.index(st.session_state.selected_month)
            if st.session_state.selected_month in month_options
            else month_options.index(today_month),
            format_func=month_label,
            key="dashboard_month",
        )
        st.session_state.selected_month = selected_month
        st.query_params["mes"] = selected_month.strftime("%Y-%m")
    with top2:
        saved = selected_month.isoformat() in month_by_key
        st.metric(
            "Situação da competência",
            "SALVA" if saved else "NÃO REGISTRADA",
        )

    previous = month_by_key.get(previous_month(selected_month).isoformat(), {})
    record = month_by_key.get(selected_month.isoformat()) or blank_month(selected_month, previous)
    totals = month_totals(record)

    if db_error:
        st.warning(f"Persistência temporariamente indisponível: {db_error}")

    summary_col, movements_col = st.columns([1.05, 2.35], gap="large")

    with summary_col:
        summary_html = (
            '<div class="inventory-box">'
            '<div class="inventory-box-title">Resumo do mês</div>'
            + inventory_row("Estoque inicial total", money_br(totals["ei_total"]))
            + inventory_row("Estoque final total", money_br(totals["ef_total"]))
            + inventory_row("Faturamento", money_br(record.get("faturamento")))
            + inventory_row(
                "Percentual Div. Est. Final/Inic",
                percent_br(totals["percentual_div"]),
                value_class(totals["percentual_div"]),
            )
            + inventory_row(
                "Percentual Produto/Fat",
                percent_br(totals["percentual_produto_fat"]),
                value_class(totals["percentual_produto_fat"]),
            )
            + inventory_row(
                "Variação de estoque",
                money_br(totals["variacao"]),
                value_class(totals["variacao"]),
            )
            + "</div>"
        )
        st.markdown(summary_html, unsafe_allow_html=True)

    with movements_col:
        s2_rows = [
            ("EI S2", float(record.get("ei_s2") or 0)),
            ("EF S2", float(record.get("ef_s2") or 0)),
            ("Baixa OP S2", float(record.get("baixa_op_s2") or 0)),
            ("Ajustes S2", float(record.get("ajustes_s2") or 0)),
            ("Compras S2", float(record.get("compras_s2") or 0)),
            (
                "Transf. de arm. / doação / venda",
                float(record.get("transferencias_s2") or 0),
            ),
            ("Vendas S2", float(record.get("vendas_s2") or 0)),
            ("Resumo S2", totals["resumo_s2"]),
        ]
        ep_rows = [
            ("EI EP", float(record.get("ei_ep") or 0)),
            ("EF EP", float(record.get("ef_ep") or 0)),
            ("Resumo EP", totals["resumo_ep"]),
        ]
        pa_rows = [
            ("EI PA", float(record.get("ei_pa") or 0)),
            ("EF PA", float(record.get("ef_pa") or 0)),
            ("Resumo PA", totals["resumo_pa"]),
        ]

        st.markdown(
            '<div class="inventory-box">'
            '<div class="inventory-box-title">Movimentações do mês</div>'
            '<div style="padding:.75rem">'
            '<div class="mov-grid">'
            + movement_column("S2", s2_rows)
            + movement_column("EP", ep_rows)
            + movement_column("PA", pa_rows)
            + "</div></div></div>",
            unsafe_allow_html=True,
        )

    with st.expander("REGISTRAR / EDITAR COMPETÊNCIA", expanded=not saved):
        st.caption(
            "Ao abrir uma competência ainda não cadastrada, o estoque inicial é sugerido "
            "a partir do estoque final do mês anterior. Todos os campos continuam editáveis."
        )

        f1, f2 = st.columns(2)
        faturamento = f1.number_input(
            "Faturamento",
            value=float(record.get("faturamento") or 0),
            step=1000.0,
            format="%.2f",
            key=f"fat_{selected_month}",
        )
        observacao = f2.text_input(
            "Observação",
            value=str(record.get("observacao") or ""),
            key=f"obs_{selected_month}",
        )

        st.markdown("#### S2")
        s21, s22, s23 = st.columns(3)
        ei_s2 = s21.number_input("EI S2", value=float(record.get("ei_s2") or 0), format="%.2f", key=f"ei_s2_{selected_month}")
        ef_s2 = s22.number_input("EF S2", value=float(record.get("ef_s2") or 0), format="%.2f", key=f"ef_s2_{selected_month}")
        baixa_op_s2 = s23.number_input("Baixa OP S2", value=float(record.get("baixa_op_s2") or 0), format="%.2f", key=f"baixa_{selected_month}")

        s24, s25 = st.columns(2)
        ajustes_s2 = s24.number_input("Ajustes S2", value=float(record.get("ajustes_s2") or 0), format="%.2f", key=f"ajustes_{selected_month}")
        compras_s2 = s25.number_input("Compras S2", value=float(record.get("compras_s2") or 0), format="%.2f", key=f"compras_{selected_month}")

        s26, s27 = st.columns(2)
        transferencias_s2 = s26.number_input(
            "Transf. de armazém / doação / venda",
            value=float(record.get("transferencias_s2") or 0),
            format="%.2f",
            key=f"transf_{selected_month}",
        )
        vendas_s2 = s27.number_input("Vendas S2", value=float(record.get("vendas_s2") or 0), format="%.2f", key=f"vendas_{selected_month}")

        st.markdown("#### EP e PA")
        e1, e2, p1, p2 = st.columns(4)
        ei_ep = e1.number_input("EI EP", value=float(record.get("ei_ep") or 0), format="%.2f", key=f"ei_ep_{selected_month}")
        ef_ep = e2.number_input("EF EP", value=float(record.get("ef_ep") or 0), format="%.2f", key=f"ef_ep_{selected_month}")
        ei_pa = p1.number_input("EI PA", value=float(record.get("ei_pa") or 0), format="%.2f", key=f"ei_pa_{selected_month}")
        ef_pa = p2.number_input("EF PA", value=float(record.get("ef_pa") or 0), format="%.2f", key=f"ef_pa_{selected_month}")

        if st.button(
            "SALVAR COMPETÊNCIA",
            type="primary",
            use_container_width=True,
            key=f"save_month_{selected_month}",
        ):
            try:
                db.save_month(
                    {
                        "competencia": selected_month,
                        "faturamento": faturamento,
                        "ei_s2": ei_s2,
                        "ef_s2": ef_s2,
                        "baixa_op_s2": baixa_op_s2,
                        "ajustes_s2": ajustes_s2,
                        "compras_s2": compras_s2,
                        "transferencias_s2": transferencias_s2,
                        "vendas_s2": vendas_s2,
                        "ei_ep": ei_ep,
                        "ef_ep": ef_ep,
                        "ei_pa": ei_pa,
                        "ef_pa": ef_pa,
                        "observacao": observacao,
                    }
                )
                st.session_state["_flash_month"] = f"{month_label(selected_month)} salva com sucesso."
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível salvar a competência: {exc}")

    if st.session_state.pop("_flash_month", None):
        st.success("Competência salva com sucesso.")

    st.markdown(
        '<div class="section-title history-title">Histórico mês a mês</div>',
        unsafe_allow_html=True,
    )

    history = []
    for row in month_rows:
        try:
            comp = date.fromisoformat(str(row.get("competencia"))[:10])
        except Exception:
            continue
        calc = month_totals(row)
        history.append(
            {
                "Competência": month_label(comp),
                "Estoque inicial": money_br(calc["ei_total"]),
                "Estoque final": money_br(calc["ef_total"]),
                "Variação": money_br(calc["variacao"]),
                "EI S2": money_br(row.get("ei_s2")),
                "EF S2": money_br(row.get("ef_s2")),
                "EI EP": money_br(row.get("ei_ep")),
                "EF EP": money_br(row.get("ef_ep")),
                "EI PA": money_br(row.get("ei_pa")),
                "EF PA": money_br(row.get("ef_pa")),
            }
        )

    if history:
        st.dataframe(pd.DataFrame(history), use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma competência foi salva ainda.")


elif page == "Conferência de chapas e barramentos":
    st.markdown(
        '<div class="section-title">Conferência de chapas e barramentos</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="module-hero">
            <strong>Módulo preparado para a conferência física e sistêmica de chapas e barramentos.</strong>
            <span>Na próxima etapa definiremos as planilhas de origem, códigos, medidas, unidades, custos e regras de correlação.</span>
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
            <strong>Módulo destinado à validação das baixas que impactam o fechamento do estoque.</strong>
            <span>Vamos definir os relatórios envolvidos, a chave de comparação, os tipos de baixa válidos e os alertas de divergência.</span>
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
            <strong>Análise das movimentações que explicam a variação do estoque no mês.</strong>
            <span>Esta área será usada para detalhar compras, baixas de OP, ajustes, transferências, doações, vendas e demais movimentos do período.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if month_rows:
        movement_table = []
        for row in month_rows:
            comp = date.fromisoformat(str(row.get("competencia"))[:10])
            calc = month_totals(row)
            movement_table.append(
                {
                    "Competência": month_label(comp),
                    "Baixa OP S2": money_br(row.get("baixa_op_s2")),
                    "Ajustes S2": money_br(row.get("ajustes_s2")),
                    "Compras S2": money_br(row.get("compras_s2")),
                    "Transferências": money_br(row.get("transferencias_s2")),
                    "Vendas S2": money_br(row.get("vendas_s2")),
                    "Variação total": money_br(calc["variacao"]),
                }
            )
        st.dataframe(pd.DataFrame(movement_table), use_container_width=True, hide_index=True)
    else:
        st.info("Salve a primeira competência no Dashboard para iniciar o histórico de movimentações.")


else:
    st.markdown('<div class="section-title">Configurações</div>', unsafe_allow_html=True)
    st.caption(
        "As alterações desta página agora são salvas no Supabase e permanecem após atualizar ou abrir o aplicativo novamente."
    )

    with st.container(border=True):
        st.markdown("#### Identidade do aplicativo")
        title = st.text_input("Título principal", value=str(cfg.get("title") or DEFAULT_CONFIG["title"]))
        subtitle = st.text_input("Subtítulo", value=str(cfg.get("subtitle") or DEFAULT_CONFIG["subtitle"]))
        sidebar_title = st.text_input(
            "Título da barra lateral",
            value=str(cfg.get("sidebar_title") or DEFAULT_CONFIG["sidebar_title"]),
        )
        sidebar_subtitle = st.text_input(
            "Subtítulo da barra lateral",
            value=str(cfg.get("sidebar_subtitle") or DEFAULT_CONFIG["sidebar_subtitle"]),
        )

        if st.button("SALVAR CONFIGURAÇÕES", type="primary", use_container_width=True):
            new_cfg = {
                "title": title.strip() or DEFAULT_CONFIG["title"],
                "subtitle": subtitle.strip() or DEFAULT_CONFIG["subtitle"],
                "sidebar_title": sidebar_title.strip() or DEFAULT_CONFIG["sidebar_title"],
                "sidebar_subtitle": sidebar_subtitle.strip() or DEFAULT_CONFIG["sidebar_subtitle"],
            }
            try:
                db.save_config(new_cfg)
                st.session_state.app_cfg = {**DEFAULT_CONFIG, **new_cfg}
                st.success("Configurações salvas permanentemente.")
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível salvar as configurações: {exc}")

    with st.container(border=True):
        st.markdown("#### Navegação")
        st.success(
            "A página atual e a competência selecionada são mantidas na URL. "
            "Ao atualizar o navegador, o aplicativo retorna ao mesmo ponto."
        )

    with st.container(border=True):
        st.markdown("#### Ícone do navegador")
        st.info(
            "O favicon deste aplicativo está sincronizado diretamente com o ícone que está salvo no NFS Setta. "
            "Assim os dois usam exatamente o mesmo arquivo e a mesma proporção visual."
        )


st.markdown(
    '<div class="footer">SETTA | Fechamento Mensal de Inventário</div>',
    unsafe_allow_html=True,
)
