"""Prévia do lote único sem substituição de históricos."""
from pathlib import Path
from tempfile import TemporaryDirectory

import streamlit as st

import central_movement_feeds as feeds
from central_closing_bundle import SOURCES, compile_preview

PREVIEW_KEY = "fm_closing_central_preview"
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024


def render_central_closing_bundle():
    st.subheader("Lote da Gestão de API")
    st.caption("Envie OPS e Kardex S2, EP e E2 pela Gestão de API.")
    state = feeds.state_or_empty()
    versions = tuple((key, state.get(key, {}).get("token")) for key in SOURCES)
    ready = all(state.get(key, {}).get("current") for key in SOURCES)
    for key in SOURCES:
        st.caption(feeds.describe(key, state.get(key) or {"status": "SEM CARGA"}))
    result = st.session_state.get(PREVIEW_KEY)
    if result and (not ready or result["versions"] != versions):
        st.session_state.pop(PREVIEW_KEY, None)
        result = None
    if not ready:
        st.info("Aguardando as quatro fontes para gerar o relatório.")
    if st.button("Gerar relatório consolidado", type="primary", disabled=not ready, key="fm_central_compile"):
        try:
            with st.spinner("Consolidando fontes da Central..."), TemporaryDirectory() as folder:
                target = Path(folder) / "fechamento.json.gz"
                counts = compile_preview(
                    target, sources=state, load_parsed=feeds.parse_current_source,
                    verify_current=feeds.verify_current, max_bytes=MAX_DOWNLOAD_BYTES,
                )
                result = {"versions": versions, "counts": counts, "data": target.read_bytes()}
            st.session_state[PREVIEW_KEY] = result
        except Exception as exc:
            st.session_state.pop(PREVIEW_KEY, None)
            result = None
            st.error(f"Lote não gerado: {exc}")
    if result:
        counts = result["counts"]
        st.success(f"{sum(counts.values()):,} registros de 4 fontes. Nenhuma base foi alterada.".replace(",", "."))
        st.download_button(
            "Baixar relatório consolidado", data=result["data"],
            file_name="fechamento_consolidado.json.gz",
            mime="application/gzip", on_click="ignore",
            key="fm_central_bundle_download",
        )
