from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from ui import inject_css, kpi, logo_html, panel

TZ = ZoneInfo("America/Sao_Paulo")

st.set_page_config(
    page_title="Fechamento Mensal | Setta",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()

if "operator" not in st.session_state:
    st.session_state.operator = ""

if "app_title" not in st.session_state:
    st.session_state.app_title = "FECHAMENTO MENSAL"

if "app_subtitle" not in st.session_state:
    st.session_state.app_subtitle = (
        "Análises • Inventário • Divergências • Conferências • Fechamento"
    )


with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand">
            <div class="sidebar-brand-title">FECHAMENTO MENSAL</div>
            <div class="sidebar-brand-sub">Análises de inventário</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="sidebar-section-label">Navegação</div>',
        unsafe_allow_html=True,
    )

    page = st.radio(
        "Página",
        ["Dashboard", "Análises", "Configurações"],
        label_visibility="collapsed",
        format_func=lambda item: item.upper(),
    )

    st.divider()
    st.markdown(
        '<div class="sidebar-section-label">Operador</div>',
        unsafe_allow_html=True,
    )

    st.session_state.operator = st.text_input(
        "Nome do operador",
        value=st.session_state.operator,
        label_visibility="collapsed",
        placeholder="Informe o operador",
    )

    st.divider()
    st.markdown(
        '<div class="sidebar-section-label">Identidade visual</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="sidebar-logo-preview">{logo_html()}</div>',
        unsafe_allow_html=True,
    )
    st.caption("Mesmo padrão visual utilizado no NFS Setta.")

    st.divider()
    st.markdown(
        '<div class="sidebar-section-label">Informações</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="sidebar-info-card">
            <b>Data operacional</b><br>{datetime.now(TZ):%d/%m/%Y}<br><br>
            <b>Módulo</b><br>Fechamento mensal de inventário<br><br>
            <b>Status</b><br>Estrutura visual criada<br><br>
            <b>Versão</b><br>Protótipo 0.1
        </div>
        """,
        unsafe_allow_html=True,
    )


st.markdown(
    f'<div class="setta-logo-card">{logo_html()}</div>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<h1 class="app-title">{st.session_state.app_title} | SETTA</h1>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<p class="app-sub">{st.session_state.app_subtitle}</p>',
    unsafe_allow_html=True,
)


if page == "Dashboard":
    st.markdown(
        '<div class="section-title">Dashboard operacional</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="intro">
            Módulo destinado às análises e conferências do fechamento mensal de inventário.
            Nesta primeira etapa, a estrutura visual foi preparada para receber as regras do processo.
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi(
            "Itens analisados",
            0,
            "Aguardando base do fechamento",
            "#2563eb",
            "#dbeafe",
            True,
        )
    with c2:
        kpi(
            "Divergências",
            0,
            "Regras serão definidas na próxima etapa",
            "#dc2626",
            "#fee2e2",
        )
    with c3:
        kpi(
            "Ajustes pendentes",
            0,
            "Sem lógica aplicada nesta versão",
            "#d97706",
            "#ffedd5",
        )
    with c4:
        kpi(
            "Concluídos",
            0,
            "Fechamentos finalizados",
            "#16a34a",
            "#dcfce7",
        )

    st.markdown(
        '<div class="section-title" style="margin-top:1.65rem!important;">Visão geral do fechamento</div>',
        unsafe_allow_html=True,
    )

    left, right = st.columns(2)
    with left:
        panel(
            "Resumo de inventário",
            "Espaço reservado para indicadores, valores e divergências que serão definidos durante a customização do módulo.",
        )
    with right:
        panel(
            "Pendências do fechamento",
            "Espaço reservado para itens que exigirem conferência, correção ou tratativa antes do fechamento definitivo.",
        )

    st.markdown(
        '<div class="section-title" style="margin-top:1.65rem!important;">Base de análise</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="placeholder">
            A área de importação e as regras de cruzamento serão adicionadas na próxima etapa.
            Nenhuma regra de inventário foi presumida nesta versão.
        </div>
        """,
        unsafe_allow_html=True,
    )


elif page == "Análises":
    st.markdown(
        '<div class="section-title">Análises do fechamento mensal</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="intro">
            Área preparada para receber as análises específicas do fechamento mensal.
            A estrutura será construída conforme as bases, campos, conferências e regras que forem validadas.
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        panel(
            "Conferência de saldos",
            "Reservado para comparação entre saldo sistêmico, saldo físico e demais bases do inventário.",
        )
    with c2:
        panel(
            "Divergências",
            "Reservado para identificação, classificação e tratativa das diferenças encontradas.",
        )
    with c3:
        panel(
            "Fechamento",
            "Reservado para validações finais, indicadores e geração dos arquivos de fechamento.",
        )

    st.info(
        "Layout pronto. As regras de negócio ainda não foram implementadas nesta etapa."
    )


else:
    st.markdown(
        '<div class="section-title">Configurações</div>',
        unsafe_allow_html=True,
    )

    st.caption(
        "Esta área já segue o mesmo padrão do NFS Setta e será expandida conforme definirmos as customizações do módulo."
    )

    with st.container(border=True):
        st.markdown("#### Identidade do aplicativo")

        title = st.text_input(
            "Título principal",
            value=st.session_state.app_title,
        )
        subtitle = st.text_input(
            "Subtítulo",
            value=st.session_state.app_subtitle,
        )

        save = st.button(
            "SALVAR ALTERAÇÕES DA SESSÃO",
            type="primary",
            use_container_width=True,
        )

        if save:
            st.session_state.app_title = title.strip() or "FECHAMENTO MENSAL"
            st.session_state.app_subtitle = subtitle.strip()
            st.success("Identidade atualizada nesta sessão.")
            st.rerun()

    st.markdown(
        """
        <div class="placeholder">
            Persistência de configurações, usuários, integrações e parâmetros será adicionada somente quando
            a estrutura funcional do fechamento mensal for definida.
        </div>
        """,
        unsafe_allow_html=True,
    )


st.markdown(
    '<div class="footer">SETTA | Fechamento Mensal de Inventário</div>',
    unsafe_allow_html=True,
)
