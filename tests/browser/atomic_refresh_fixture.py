"""Read-only Streamlit fixture for browser regression (no external sources)."""

import time

import streamlit as st

from ui import render_shell

st.set_page_config(initial_sidebar_state="collapsed")
route = st.session_state.get("mock_route", 0)
render_shell(title="Fechamento Mensal", page_label=["Dashboard", "Kardex"][route], route_id=route)
with st.sidebar, st.container(key="setta_route_list"):
    for i, name in enumerate(("Dashboard", "Kardex")):
        st.button(name, key=f"setta_nav_{i}", on_click=st.session_state.update,
                  kwargs={"mock_route": i})


def render_contents():
    show = st.toggle("Detalhes do período", key=f"detail_{route}")
    with st.expander("Filtros"):
        st.caption("Abertura local, sem rerun.")
    label = "Novo" if show else "Original"
    st.markdown(f'<p id="first-part">{label} · Primeira parte</p>', unsafe_allow_html=True)
    if show or route:
        time.sleep(.55)
    st.markdown(f'<p id="second-part">{label} · Segunda parte</p>', unsafe_allow_html=True)


@st.fragment
def fragment():
    with st.form("fixture_search"):
        term = st.text_input("Buscar OP")
        st.form_submit_button("Buscar")
    st.markdown(f'<p id="fragment-first">{term} · Cabeçalho do resultado</p>', unsafe_allow_html=True)
    if term:
        time.sleep(.55)
    st.markdown(f'<p id="fragment-second">{term} · Resultado completo</p>', unsafe_allow_html=True)


with st.container(key=f"fm_route_body_{route}"):
    render_contents()
    if route == 0:
        fragment()
    st.html(f'<span class="setta-ready-marker" data-setta-aba-pronta="{route}"></span>')
