"""Seção isolada e sob demanda para candidatos a baixa manual sem OP.

Não grava decisões nem altera status oficiais da conferência.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import manual_issue_candidates as candidates
import movement_analysis_ui as kardex
import movements as mv


def _summary_cards(meta: dict) -> None:
    cols = st.columns(4)
    values = (
        ("Baixas sem OP elegíveis", "movimentos_elegiveis"),
        ("Com OP candidata única", "movimentos_com_op_unica"),
        ("Com múltiplas OPs", "movimentos_ambiguos"),
        ("Sem correspondência", "movimentos_sem_correspondencia"),
    )
    for col, (label, key) in zip(cols, values):
        col.metric(label, f"{int(meta.get(key) or 0):,}".replace(",", "."))


def render(model: dict) -> None:
    st.markdown("---")
    st.markdown("### CONCILIAÇÃO ASSISTIDA · BAIXAS MANUAIS SEM OP")
    st.caption(
        "Análise experimental e somente leitura. Procura baixas TES 520/550 "
        "com vínculo explícito CC600307 no KARDEX e SEM OP na AE. "
        "Sugere possíveis OPs pelo produto e pela data de faturamento ou "
        "movimentação MES, sem reconhecer consumo automaticamente."
    )

    if not st.toggle(
        "ABRIR ANÁLISE RETROATIVA DO KARDEX",
        key="fm_manual_candidates_open",
        value=False,
    ):
        return

    if not model.get("history_available"):
        st.warning(
            "Relatório OPS ainda não está disponível. A análise não pode "
            "determinar pendências comprovadas da OP."
        )
        return

    reference = date.fromisoformat(model["as_of"][:10])
    prior_end = reference.replace(day=1) - timedelta(days=1)
    default_start = prior_end.replace(day=1)
    st.caption(
        "O KARDEX sem OP não identifica o lote da OP. Nenhuma sugestão "
        "será lançada na Conferência de Baixas, no OPS ou no banco. "
        "Saldo G9-PROD é a fotografia atual, não o saldo da data passada."
    )
    with st.form("fm_manual_candidate_form"):
        c1, c2 = st.columns(2)
        with c1:
            start = st.date_input(
                "Data inicial da baixa KARDEX",
                value=default_start, format="DD/MM/YYYY",
                key="fm_manual_candidate_start",
            )
        with c2:
            end = st.date_input(
                "Data final da baixa KARDEX",
                value=reference, format="DD/MM/YYYY",
                key="fm_manual_candidate_end",
            )
        with st.expander("CRITÉRIOS TEMPORAIS E SALDO · OPCIONAL", expanded=False):
            b, a = st.columns(2)
            with b:
                before = st.number_input(
                    "Dias antes do faturamento",
                    min_value=0, max_value=365, value=90, step=10,
                    key="fm_manual_before",
                )
            with a:
                after = st.number_input(
                    "Dias após o faturamento",
                    min_value=0, max_value=60, value=7, step=1,
                    key="fm_manual_after",
                )
            require_g9 = st.checkbox(
                "Priorizar OPs com saldo atual G9-PROD insuficiente",
                value=True, key="fm_manual_require_g9",
            )
            st.caption(
                "Se o faturamento for NI, a análise exige algum evento "
                "de separação/conferência em até 30 dias. "
                "O saldo atual não comprova a situação histórica."
            )
        calculate = st.form_submit_button(
            "ANALISAR E GERAR CANDIDATOS",
            type="primary", use_container_width=True,
        )

    if calculate:
        st.session_state.pop("fm_manual_candidate_ready", None)
        if isinstance(start, tuple) or isinstance(end, tuple) or start > end:
            st.error("Selecione um intervalo válido de datas.")
            return
        if start > reference:
            st.error(
                f"A data inicial é posterior à referência MES ({reference:%d/%m/%Y})."
            )
            return
        try:
            with st.spinner(
                "Lendo KARDEX persistido, selecionando baixas manuais "
                "e cruzando com as OPs sem modificar os históricos..."
            ):
                registry = kardex._imports()
                if not registry:
                    raise ValueError(
                        "Nenhum KARDEX histórico importado foi localizado."
                    )
                tokens = tuple(
                    (entry["chave"], entry.get("atualizado_em", ""),
                     entry.get("meta") or {})
                    for entry in registry
                )
                frame = kardex._model(
                    tokens, mv.rules()["versao"]
                    + candidates.VERSION,
                )["frame"]
                result = candidates.build(
                    model, frame, start=start, end=end,
                    before_days=int(before), after_days=int(after),
                    require_insufficient_g9=bool(require_g9),
                )
                workbook = candidates.export_excel(result)
                signature = hashlib.sha256(
                    repr((start, end, before, after, require_g9, tokens,
                          model.get("as_of"), candidates.VERSION)).encode()
                ).hexdigest()[:12]
                st.session_state["fm_manual_candidate_ready"] = (
                    signature, result, workbook, start, end,
                )
        except Exception as exc:
            st.error("A conciliação assistida não pôde ser gerada: " + str(exc))
            return

    ready = st.session_state.get("fm_manual_candidate_ready")
    if not ready:
        st.info(
            "Escolha o período e clique em ANALISAR. "
            "Nenhuma movimentação será atribuída automaticamente a uma OP."
        )
        return

    _, result, data, scope_start, scope_end = ready
    st.caption(
        f"Análise realizada para {scope_start:%d/%m/%Y} a "
        f"{scope_end:%d/%m/%Y} · referência MES: {reference:%d/%m/%Y}. "
        "Para alterar os critérios, gere uma nova análise."
    )
    _summary_cards(result["summary"])
    rows = result["rows"]
    if not rows:
        st.info(
            "Nenhuma baixa TES 520/550 CC600307 sem OP foi encontrada "
            "no intervalo informado."
        )
        return
    frame = pd.DataFrame(rows).rename(
        columns={key: label for label, key in candidates.COLUMNS}
    )
    with st.expander("CONSULTAR CANDIDATOS E AMBIGUIDADES", expanded=True):
        view_cols = [
            "Data da baixa", "Documento KARDEX", "TES", "CR",
            "Produto", "Quantidade manual", "OP candidata",
            "Faturamento", "Falta de consumo na OP",
            "Saldo atual G9-PROD", "OPs compatíveis com a baixa",
            "Situação",
        ]
        st.dataframe(
            frame[view_cols], use_container_width=True,
            height=min(570, 40 + max(1, min(len(frame), 17)) * 31),
            hide_index=True,
        )
        st.caption(
            "Uma mesma baixa pode aparecer em várias linhas quando "
            "houver múltiplas OPs candidatas. NÃO some essas linhas: "
            "elas são alternativas de associação, não baixas adicionais."
        )
    st.download_button(
        "BAIXAR EXCEL · BAIXAS MANUAIS CANDIDATAS",
        data=data,
        file_name=(
            f"BAIXAS_MANUAIS_CANDIDATAS_SETTA_"
            f"{scope_start:%Y%m%d}_{scope_end:%Y%m%d}.xlsx"
        ),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        key="fm_manual_candidates_download",
    )
    st.caption(
        "O Excel traz documento, data, produto, CR/TES, quantidade, "
        "OPs possíveis, faturamento, pendência OPS, saldo atual G9-PROD, "
        "origem e justificativa. A validação documental e qualquer atribuição "
        "à OP são etapas posteriores e não são automatizadas nesta fase."
    )
