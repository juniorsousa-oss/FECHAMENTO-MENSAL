"""Página central de relatórios — estoque, conferência de baixas e KARDEX."""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st

import issue_check_ui as issue
import movement_analysis_ui as movement
import movement_store
import movements as mv
import operational_status as stages
import reports


REPORT_NAMES = [
    "Estoque e Fechamento",
    "Conferência de Baixas",
    "Movimentações KARDEX",
]
MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _known_warehouses(imports: list[dict]) -> list[str]:
    found = set()
    for item in imports:
        meta = item.get("meta") or {}
        found.update(str(x).strip().upper() for x in meta.get("armazens") or [] if x)
        if meta.get("armazem"):
            found.add(str(meta["armazem"]).strip().upper())
        for subset in meta.get("escopos") or []:
            if subset.get("armazem"):
                found.add(str(subset["armazem"]).strip().upper())
    return sorted(found)


def _get_issue_model(selected_warehouses: tuple[str, ...] = ()) -> dict:
    """Exatamente as mesmas fontes, regras e caches da tela de conferência."""
    states = issue._states()
    for key in issue.SOURCE_KEYS:
        if key not in states or not states[key].get("available") or states[key].get("status") != "ATUALIZADO":
            raise RuntimeError(f"Fonte {key} indisponível ou desatualizada no Monitor de APIs.")
    tokens = tuple((key, int(states[key]["version"]), str(states[key].get("last_update_at") or ""))
                   for key in issue.SOURCE_KEYS)
    # O relatório OPS informa OP/produto/lote, mas não informa armazém.
    registered = tuple(sorted(
        set(issue._warehouse_options(next(token for token in tokens if token[0] == "endereco")))
    ))
    chosen = tuple(x for x in registered if not selected_warehouses or x in selected_warehouses)
    if not chosen:
        raise ValueError("Nenhum armazém selecionado possui fonte ENDEREÇO.")
    meta = issue._ops_meta()
    history_tokens = (
        (str(meta["sha256"]), str(meta.get("atualizado_em") or ""))
        if meta else ()
    )
    model = issue._audit(tokens, history_tokens, chosen, issue.check.VERSION)
    master_records, master_meta = issue._optional_master_plan()
    catalog_types, catalog_meta = issue._optional_catalog_types()
    master_version = str(master_meta.get("source_version", master_meta.get("version", ""))) + str(master_meta.get("content_sha256") or master_meta.get("erro") or "")
    catalog_version = str(catalog_meta.get("source_version", catalog_meta.get("version", ""))) + str(catalog_meta.get("content_sha256") or catalog_meta.get("erro") or "")
    enriched = issue._operational_snapshot(
        tokens, history_tokens, chosen, master_version, catalog_version,
        stages.VERSION + "|" + issue.lot_conference.VERSION,
        model, master_records, catalog_types)
    prices, price_meta = issue._optional_catalog_prices()
    return {**enriched, "master_plan_meta": master_meta,
            "catalog_meta": catalog_meta,
            "catalog_prices": prices, "catalog_price_meta": price_meta}


def _date_controls():
    mode = st.radio("Abrangência", ["Período personalizado", "Histórico completo"],
                    horizontal=True, key="fm_reports_scope")
    if mode == "Histórico completo":
        st.caption("Inclui todos os registros disponíveis nas fontes vigentes.")
        return None, None, "COMPLETO"
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    left, right = st.columns(2)
    with left:
        start = st.date_input("DATA INICIAL", value=date(today.year, today.month, 1),
                              format="DD/MM/YYYY", key="fm_reports_start")
    with right:
        end = st.date_input("DATA FINAL", value=today, format="DD/MM/YYYY",
                            key="fm_reports_end")
    if isinstance(start, tuple) or isinstance(end, tuple):
        st.warning("Selecione uma única data inicial e uma única data final.")
        return start, end, ""
    if start > end:
        st.error("A data inicial não pode ser posterior à data final.")
        return start, end, ""
    return start, end, f"{start:%Y%m%d}_{end:%Y%m%d}"


def render_reports(*, summaries: list[dict], imports: list[dict]) -> None:
    """Três relatórios; período essencial visível, filtros secundários recolhidos.

    Preserva as chaves de sessão e todos os argumentos da exportação.
    As alterações são apenas visuais: não reclassificam ou alteram fontes.
    """
    st.markdown('<div class="section-title">RELATÓRIOS</div>', unsafe_allow_html=True)
    st.caption("Escolha o relatório, defina o período e prepare o arquivo Excel.")

    with st.container(border=True):
        st.markdown("**01 · RELATÓRIO**")
        choice = st.radio(
            "TIPO DE RELATÓRIO", REPORT_NAMES, horizontal=True,
            key="fm_reports_kind", label_visibility="collapsed",
        )
    with st.container(border=True):
        st.markdown("**02 · PERÍODO**")
        start, end, period_key = _date_controls()
    if not period_key:
        return

    extra = {}
    warehouses = []
    if choice == REPORT_NAMES[0]:
        st.caption(
            "Competências mensais: as datas selecionam meses de fechamento; "
            "não representam saldos diários."
        )
        if not imports:
            st.warning("Não há competências de estoque disponíveis para exportação.")
            return
        sheet_count = 4

    elif choice == REPORT_NAMES[1]:
        st.caption(
            "25 colunas · uma linha por OP + produto + lote. "
            "Por padrão, o período considera somente o faturamento."
        )
        left, right = st.columns(2, gap="medium")
        with left:
            extra["alerts"] = st.checkbox(
                "Somente OPs com alerta",
                key="fm_reports_alerts",
            )
        with right:
            extra["include_activity"] = st.checkbox(
                "Incluir OPs com atividade no período",
                value=False, key="fm_reports_include_activity",
                help=(
                    "Inclui OPs com separação, conferência ou baixa no período, "
                    "mesmo sem faturamento válido ou com faturamento fora dele."
                ),
            )
        with st.expander("FILTROS ADICIONAIS · opcional", expanded=False):
            col_status, col_type = st.columns(2, gap="medium")
            with col_status:
                available_statuses = [
                    stages.FINALIZADO_PATIO, stages.FINALIZADO_ENTREGUE,
                    stages.NF_EMITIDA, stages.FINALIZADO, stages.REPORTADO,
                    stages.EM_CONFERENCIA, stages.EM_SEPARACAO,
                    stages.AGUARDANDO_INICIO,
                ]
                extra["status"] = st.selectbox(
                    "Status da OP", ["Todos os status"] + available_statuses,
                    key="fm_reports_issue_status",
                )
            with col_type:
                extra["types"] = st.multiselect(
                    "Tipo de material", ["EP", "II", "MP", "PA", "PI", "NI"],
                    key="fm_reports_types", placeholder="Todos os tipos",
                )
            try:
                states = issue._states()
                entry = states.get("endereco") or {}
                token = (
                    "endereco", int(entry["version"]),
                    str(entry.get("last_update_at") or ""),
                )
                options = issue._warehouse_options(token)
            except Exception as exc:
                options = []
                st.caption("Armazéns indisponíveis: " + str(exc))
            if options:
                warehouses = st.multiselect(
                    "Armazéns", options, key="fm_reports_wh",
                    placeholder="Todos os armazéns",
                )
        active = []
        if extra["alerts"]:
            active.append("somente OPs com alerta")
        if extra["include_activity"]:
            active.append("atividade incluída")
        if extra["status"] != "Todos os status":
            active.append("status: " + extra["status"])
        if extra["types"]:
            active.append("tipos: " + ", ".join(extra["types"]))
        if warehouses:
            active.append("armazéns: " + ", ".join(warehouses))
        if active:
            st.caption("Filtros ativos · " + " · ".join(active))
        sheet_count = 1

    else:
        st.caption("Movimentações do KARDEX no período, por grupo e TES.")
        extra["summary_only"] = st.selectbox(
            "Apresentação",
            ["Completo — grupos, OPs e movimentações",
             "Resumo gerencial — grupos e TES"],
            key="fm_reports_detail",
        ).startswith("Resumo")
        with st.expander("FILTROS ADICIONAIS · opcional", expanded=False):
            try:
                sources = movement_store.list_imports()
                options = _known_warehouses(sources)
            except Exception as exc:
                options = []
                st.caption("Armazéns indisponíveis: " + str(exc))
            if options:
                warehouses = st.multiselect(
                    "Armazéns", options, key="fm_reports_wh",
                    placeholder="Todos os armazéns",
                )
            col_types, col_groups = st.columns(2, gap="medium")
            with col_types:
                extra["types"] = st.multiselect(
                    "Tipos de material", ["EP", "II", "MP", "PA", "PI"],
                    key="fm_reports_kardex_types", placeholder="Todos os tipos",
                )
            try:
                group_cfg = movement._groups_read()
                group_options = [
                    entry["nome"] for entry in group_cfg.get("grupos", [])
                ]
                group_options.append("SEM GRUPO")
            except Exception:
                group_options = []
            with col_groups:
                extra["groups"] = st.multiselect(
                    "Grupos gerenciais", group_options,
                    key="fm_reports_groups", placeholder="Todos os grupos",
                )
            extra["tes"] = st.text_input(
                "TES (opcional)", key="fm_reports_tes",
                placeholder="Ex.: 020, 520, 550",
            )
        active = []
        if warehouses:
            active.append("armazéns: " + ", ".join(warehouses))
        if extra["types"]:
            active.append("tipos: " + ", ".join(extra["types"]))
        if extra["groups"]:
            active.append("grupos: " + ", ".join(extra["groups"]))
        if extra["tes"].strip():
            active.append("TES: " + extra["tes"])
        if active:
            st.caption("Filtros ativos · " + " · ".join(active))
        sheet_count = 1 if extra["summary_only"] else 3

    period_label = (
        "Histórico completo" if start is None
        else f"{start:%d/%m/%Y} a {end:%d/%m/%Y}"
    )
    st.caption(f"**Resumo da exportação:** {choice} · {period_label} · {sheet_count} aba(s)")

    report_key = hashlib.sha256(repr((
        reports.EXPORT_SCHEMA_VERSION,
        choice, period_key, tuple(warehouses), extra,
        [(row.get("competencia"), row.get("status"), row.get("importado_em"))
         for row in imports] if choice == REPORT_NAMES[0] else None,
    )).encode("utf-8")).hexdigest()

    st.markdown("**03 · EXPORTAR**")
    btn_prepare, btn_download = st.columns(2, gap="medium")
    with btn_prepare:
        prepare_clicked = st.button(
            "PREPARAR EXCEL", type="primary", use_container_width=True,
            key="fm_reports_prepare",
        )
    if prepare_clicked:
        audit_notes = []
        try:
            with st.spinner("Preparando as informações do relatório selecionado..."):
                if choice == REPORT_NAMES[0]:
                    counts = reports.stock_data(summaries, imports, start, end)
                    if not counts["Resumo Geral"]:
                        raise ValueError("Nenhuma competência possui resumo de estoque no período escolhido.")
                    data = reports.export_stock(summaries, imports, start, end)
                    records = len(counts["Evolução Mensal"])
                    prefix = "ESTOQUE_FECHAMENTO"
                elif choice == REPORT_NAMES[1]:
                    model = _get_issue_model(tuple(warehouses))
                    if model.get("catalog_meta", {}).get("erro"):
                        audit_notes.append(
                            "CADASTROS indisponível: a classificação "
                            "de tipo de material pode estar incompleta."
                        )
                    if model.get("catalog_price_meta", {}).get("erro"):
                        audit_notes.append(
                            "Preços do CADASTROS indisponíveis: o Valor previsto "
                            "da baixa ficará vazio para itens sem preço válido. "
                            + str(model["catalog_price_meta"]["erro"])
                        )
                    if not model.get("history_available"):
                        raise ValueError(
                            "Relatório OPS obrigatório: sem fonte confiável não "
                            "é permitido exportar as baixas como zero."
                        )
                    audit = reports.selection_diagnostics(
                        model, start, end,
                        include_activity=extra["include_activity"],
                    )
                    missing = len(audit["excluded_missing_billing"])
                    outside = len(audit["excluded_outside_billing"])
                    if not extra["include_activity"] and (missing or outside):
                        audit_notes.append(
                            f"Filtro somente por faturamento: {missing} OP(s) "
                            "sem data válida (NI ou inválida) e "
                            f"{outside} OP(s) faturadas fora do período "
                            "não serão exportadas."
                        )
                    if extra["include_activity"]:
                        added = len(audit["added_by_activity"])
                        audit_notes.append(
                            f"Movimentações habilitadas: {added} OP(s) "
                            "adicionadas além das faturadas no período. "
                            "Essas OPs podem ter faturamento NI ou fora do mês."
                        )
                        if audit["unreadable_billing"]:
                            audit_notes.append(
                                f"{len(audit['unreadable_billing'])} OP(s) "
                                "incluídas por atividade têm faturamento "
                                "não reconhecido. Confira a fonte."
                            )
                    # O Relatório Geral é a base linha a linha. O OPS só informa baixas.
                    if end and model.get("as_of"):
                        reference = reports._date(model["as_of"])
                        if reference and end > reference:
                            audit_notes.append(
                                f"A fonte de conferência está posicionada em "
                                f"{reference:%d/%m/%Y}. Nenhum evento posterior "
                                "a essa data será usado para selecionar OPs."
                            )
                    statuses = ({extra["status"]} if extra["status"] != "Todos os status" else None)
                    types = set(extra["types"]) if extra["types"] else None
                    rows = reports.issue_rows(
                        model, start, end, statuses=statuses,
                        alerts_only=extra["alerts"], material_types=types,
                        include_activity=extra["include_activity"])
                    if not rows:
                        raise ValueError("Nenhuma OP com atividade ou produto corresponde ao recorte selecionado.")
                    data = reports.export_issues(
                        model, start, end, statuses=statuses,
                        alerts_only=extra["alerts"], material_types=types,
                        include_activity=extra["include_activity"])
                    records = len(rows)
                    prefix = "CONFERENCIA_BAIXAS"
                else:
                    imported = movement._imports()
                    if not imported:
                        raise ValueError("Nenhuma base KARDEX está registrada.")
                    tokens = tuple((item["chave"], item.get("atualizado_em", ""),
                                    item.get("meta") or {}) for item in imported)
                    model = movement._model(tokens, mv.rules()["versao"] + movement.history.VERSION)
                    group_config = movement._groups_read()
                    frame = reports.filtered_kardex(
                        model["frame"], start, end,
                        warehouses=set(warehouses) if warehouses else None,
                        types=set(extra["types"]) if extra["types"] else None,
                        groups=set(x.strip().zfill(3) for x in extra["tes"].split(",") if x.strip()) or None,
                        group_names=set(extra["groups"]) if extra["groups"] else None,
                        group_config=group_config)
                    if frame.empty:
                        raise ValueError("Nenhuma movimentação KARDEX corresponde ao recorte.")
                    data = reports.export_kardex(
                        frame, group_config,
                        summary_only=extra["summary_only"])
                    records = len(frame)
                    prefix = "KARDEX"
            st.session_state["fm_reports_audit_notes"] = (
                report_key, tuple(audit_notes),
            )
            st.session_state["fm_reports_ready"] = (
                report_key, data,
                f"{prefix}_SETTA_{period_key}_R15.xlsx"
                if choice == REPORT_NAMES[1]
                else f"{prefix}_SETTA_{period_key}.xlsx",
                records
            )
        except Exception as exc:
            st.session_state.pop("fm_reports_ready", None)
            st.session_state.pop("fm_reports_audit_notes", None)
            st.error(f"Não foi possível preparar o relatório: {exc}")

    prepared = st.session_state.get("fm_reports_ready")
    if prepared and prepared[0] == report_key:
        with btn_download:
            st.download_button(
                "BAIXAR EXCEL", data=prepared[1], file_name=prepared[2],
                mime=MIME, type="primary",
                use_container_width=True, key="fm_reports_download",
            )
        st.caption(
            f"Arquivo pronto · {prepared[3]:,} registros · "
            "dados originais preservados.".replace(",", ".")
        )
        notes = st.session_state.get("fm_reports_audit_notes")
        if notes and notes[0] == report_key and notes[1]:
            with st.expander("DETALHES DA SELEÇÃO E DAS FONTES", expanded=False):
                for note in notes[1]:
                    st.caption(note)
    else:
        st.caption("Prepare o Excel para habilitar o download.")

