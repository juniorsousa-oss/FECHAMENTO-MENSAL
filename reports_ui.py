"""Página central de relatórios — estoque, conferência de baixas e KARDEX."""
from __future__ import annotations

import hashlib
from calendar import monthrange
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


class _SemDados(ValueError):
    """O recorte é válido, mas não contém registros exportáveis."""


def _trace_context(choice, period, start, end, warehouses, extra):
    trace = [
        ("Relatório", choice),
        ("Período solicitado", period),
        ("Competência do recorte", f"{start:%m/%Y} a {end:%m/%Y}" if start and end else "Histórico completo"),
        ("Gerado em (Brasília)", datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")),
    ]
    if choice != REPORT_NAMES[0]:
        trace.append(("Filtro · Armazéns", warehouses or "Todos os disponíveis"))
        trace.append(("Filtro · Tipos de material", extra.get("types") or "Todos os tipos"))
    if choice == REPORT_NAMES[1]:
        trace.extend([
            ("Filtro · Status da OP", extra["status"]),
            ("Filtro · Somente OPs com alerta", "Sim" if extra["alerts"] else "Não"),
            ("Filtro · Critério do período", "Faturamento ou atividade" if extra["include_activity"] else "Faturamento"),
        ])
    if choice == REPORT_NAMES[2]:
        trace.extend([
            ("Filtro · Apresentação", "Resumo gerencial" if extra["summary_only"] else "Completo"),
            ("Filtro · Grupos", extra["groups"] or "Todos os grupos"),
            ("Filtro · TES", extra["tes"].strip() or "Todas as TES"),
        ])
    return trace


def _stock_trace(imports, months):
    selected = {datetime.strptime(month, "%m/%Y").date() for month in months}
    baselines = {date(m.year - (m.month == 1), m.month - 1 or 12, 1) for m in selected} - selected
    result = [("Competências exportadas", sorted(months, key=lambda m: m[3:] + m[:2]))]
    for entry in sorted(imports, key=lambda item: str(item.get("competencia") or "")):
        month = reports._date(entry.get("competencia"))
        if month not in selected | baselines:
            continue
        label = "Fonte " + month.strftime("%m/%Y")
        if month in baselines:
            label += " · saldo inicial"
        elif entry.get("preview"):
            label += " · prévia"
        source = reports.trace_source(label, entry)
        if source:
            result.append(source)
    return result


def _kardex_trace(model, frame, start, end):
    scopes = set(zip(frame["competencia"].astype(str), frame["armazem"].astype(str)))
    result = [("Competências exportadas", sorted({month for month, _ in scopes})),
              ("Versão das regras de classificação", model.get("versao"))]
    by_id = {row.get("import_id"): row for row in model.get("import_registry") or []}
    for entry in model.get("coverage_metas") or []:
        month, warehouse = entry["competencia"], entry["armazem"]
        if (month, warehouse) not in scopes:
            continue
        begin, finish = reports._date(entry["periodo_inicio"]), reports._date(entry["periodo_fim"])
        if (start and finish and finish < start) or (end and begin and begin > end):
            continue
        known = {**entry, "importado_em": by_id.get(entry.get("import_id"), {}).get("importado_em")}
        source = reports.trace_source(f"Fonte KARDEX · {month} / {warehouse}", known)
        if source:
            result.append(source)
    return result


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
    refs = [
        reports.trace_source(
            "Fonte " + {"relatorio_geral": "Relatório Geral", "endereco": "ENDEREÇO"}.get(key, key),
            (model.get("source_meta") or {}).get(key) or states[key], version=version,
        )
        for key, version, _ in tokens
    ]
    for label, reference in [
        ("OPS", next(iter(model.get("history_meta") or []), meta or {})),
        ("Plano Mestre", master_meta),
        ("CADASTROS · Tipos", catalog_meta),
        ("CADASTROS · Preços", price_meta),
    ]:
        if reference and not reference.get("erro") and reference.get("available") is not False:
            refs.append(reports.trace_source("Fonte " + label, reference))
    return {**enriched, "master_plan_meta": master_meta,
            "export_source_trace": [ref for ref in refs if ref],
            "catalog_meta": catalog_meta,
            "catalog_prices": prices, "catalog_price_meta": price_meta}


def _month_bounds(competence: date, today: date) -> tuple[date, date]:
    start = competence.replace(day=1)
    last = start.replace(day=monthrange(start.year, start.month)[1])
    return start, min(last, today) if start <= today <= last else last


def _date_controls(competence: date | None = None):
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    default_start, default_end = _month_bounds(competence or today, today)
    period_display = st.empty()
    with st.expander("Mais opções"):
        mode = st.radio(
            "Período", ["Mês em análise", "Período personalizado", "Histórico completo"],
            horizontal=True, key="fm_reports_period_mode",
        )
        if mode == "Histórico completo":
            period_display.caption("Histórico completo")
            return None, None, "COMPLETO"
        if mode == "Mês em análise":
            period_display.caption(f"Mês em análise · {default_start:%m/%Y}")
            return default_start, default_end, f"{default_start:%Y%m%d}_{default_end:%Y%m%d}"
        left, right = st.columns(2)
        with left:
            start = st.date_input("Data inicial", value=default_start,
                                  format="DD/MM/YYYY", key="fm_reports_start")
        with right:
            end = st.date_input("Data final", value=default_end,
                                format="DD/MM/YYYY", key="fm_reports_end")
        if not isinstance(start, date) or not isinstance(end, date):
            st.warning("Informe uma data inicial e uma final.")
            return start, end, ""
        if start > end:
            st.error("A data inicial não pode ser posterior à data final.")
            return start, end, ""
        period_display.caption(f"Período · {start:%d/%m/%Y} a {end:%d/%m/%Y}")
        return start, end, f"{start:%Y%m%d}_{end:%Y%m%d}"


def _has_stock_summary(summaries, imports, start, end):
    registered = {str(row.get("competencia") or "")[:10] for row in imports}
    for row in summaries:
        if row.get("dimensao") != "TOTAL" or row.get("chave") != "TOTAL":
            continue
        raw = str(row.get("competencia") or "")[:10]
        if raw not in registered or (day := reports._date(raw)) is None:
            continue
        month = (day.year, day.month)
        if ((start is None or month >= (start.year, start.month))
                and (end is None or month <= (end.year, end.month))):
            return True
    return False


def _clear_prepared():
    st.session_state.pop("fm_reports_ready", None)
    st.session_state.pop("fm_reports_audit_notes", None)
    st.session_state.pop("fm_reports_error", None)


def render_reports(*, summaries: list[dict], imports: list[dict], competence: date | None = None) -> None:
    """Três relatórios; período essencial visível, filtros secundários recolhidos.

    Preserva as chaves de sessão e todos os argumentos da exportação.
    As alterações são apenas visuais: não reclassificam ou alteram fontes.
    """
    choice = st.radio(
        "Relatório", REPORT_NAMES, horizontal=True, key="fm_reports_kind",
    )
    start, end, period_key = _date_controls(competence)
    if not period_key:
        return

    extra = {}
    warehouses = []
    if choice == REPORT_NAMES[0]:
        if not _has_stock_summary(summaries, imports, start, end):
            if start and (start.year, start.month) == (end.year, end.month):
                st.info(f"Sem dados de estoque para {start:%m/%Y}.")
            elif start:
                st.info("Sem dados de estoque no período selecionado.")
            else:
                st.info("Sem dados de estoque no histórico disponível.")
            return

    elif choice == REPORT_NAMES[1]:
        with st.expander("Filtros do relatório", expanded=False):
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

    else:
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

    period_label = (
        "Histórico completo" if start is None
        else f"{start:%d/%m/%Y} a {end:%d/%m/%Y}"
    )

    report_key = hashlib.sha256(repr((
        reports.EXPORT_SCHEMA_VERSION,
        choice, period_key, tuple(warehouses), extra,
        [(row.get("competencia"), row.get("status"), row.get("importado_em"))
         for row in imports] if choice == REPORT_NAMES[0] else None,
    )).encode("utf-8")).hexdigest()

    action = st.empty()
    prepared = st.session_state.get("fm_reports_ready")
    ready = prepared and prepared[0] == report_key
    prepare_clicked = not ready and action.button(
        "Gerar Excel", type="primary", key="fm_reports_prepare",
    )
    if prepare_clicked:
        audit_notes = []
        trace = _trace_context(choice, period_label, start, end, warehouses, extra)
        st.session_state.pop("fm_reports_error", None)
        try:
            with st.spinner("Gerando Excel…"):
                if choice == REPORT_NAMES[0]:
                    counts = reports.stock_data(summaries, imports, start, end)
                    if not counts["Resumo Geral"]:
                        raise _SemDados("Nenhuma competência possui resumo de estoque no período escolhido.")
                    trace.extend(_stock_trace(imports, [row[0] for row in counts["Evolução Mensal"]]))
                    data = reports.export_stock(summaries, imports, start, end, trace=trace)
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
                        raise _SemDados("Nenhuma OP ou material corresponde ao recorte selecionado.")
                    date_column = reports.OP_COLUMNS.index("Faturamento")
                    bills = {day.strftime("%Y-%m") for row in rows if (day := reports._date(row[date_column]))}
                    trace.extend([
                        ("Competências de faturamento das linhas", ", ".join(f"{month[5:]}/{month[:4]}" for month in sorted(bills)) or "Nenhuma data válida nas linhas"),
                        ("Base de data da OP", "Consulte Faturamento em cada linha; pode estar vazio quando incluída por atividade."),
                        ("Data de referência da conferência", model.get("as_of")),
                        ("Armazéns efetivamente consultados", model.get("warehouses")),
                    ])
                    trace.extend(model.get("export_source_trace") or [])
                    data = reports.export_issues(
                        model, start, end, statuses=statuses,
                        alerts_only=extra["alerts"], material_types=types,
                        include_activity=extra["include_activity"], trace=trace)
                    records = len(rows)
                    prefix = "CONFERENCIA_BAIXAS"
                else:
                    imported = movement._imports()
                    if not imported:
                        raise _SemDados("Nenhuma base KARDEX está registrada.")
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
                        raise _SemDados("Nenhuma movimentação KARDEX corresponde ao recorte.")
                    trace.extend(_kardex_trace(model, frame, start, end))
                    data = reports.export_kardex(
                        frame, group_config,
                        summary_only=extra["summary_only"], trace=trace)
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
            st.session_state["fm_reports_error"] = (report_key, isinstance(exc, _SemDados), str(exc))

    prepared = st.session_state.get("fm_reports_ready")
    if prepared and prepared[0] == report_key:
        action.download_button(
            "Baixar Excel", data=prepared[1], file_name=prepared[2],
            mime=MIME, type="primary", on_click="ignore", key="fm_reports_download",
        )
        units = ("competência", "competências") if choice == REPORT_NAMES[0] else ("registro", "registros")
        st.caption(f"Pronto para baixar · {prepared[3]:,} {units[prepared[3] != 1]}.".replace(",", "."))
        notes = st.session_state.get("fm_reports_audit_notes")
        with st.expander("Detalhes da exportação", expanded=False):
            st.caption(f"{period_label} · Planilha com aba Rastreabilidade")
            if notes and notes[0] == report_key:
                for note in notes[1]:
                    st.caption(note)
            st.button("Preparar outro arquivo", on_click=_clear_prepared, key="fm_reports_reset")
    else:
        failure = st.session_state.get("fm_reports_error")
        if failure and failure[0] == report_key:
            if failure[1]:
                st.info(f"Sem dados · {failure[2]}")
            else:
                st.error(f"Não foi possível gerar o Excel: {failure[2]}")

