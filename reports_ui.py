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
    registered = tuple(sorted(
        set(issue._warehouse_options(next(token for token in tokens if token[0] == "endereco")))
        | issue._history_warehouses(issue._imports())
    ))
    chosen = tuple(x for x in registered if not selected_warehouses or x in selected_warehouses)
    if not chosen:
        raise ValueError("Nenhum armazém selecionado possui fonte ENDEREÇO ou KARDEX.")
    imports = issue._imports()
    history_tokens = tuple((entry["chave"], str(entry.get("atualizado_em") or ""),
                            entry.get("meta") or {}) for entry in imports)
    model = issue._audit(tokens, history_tokens, chosen, issue.check.VERSION)
    master_records, master_meta = issue._optional_master_plan()
    catalog_types, catalog_meta = issue._optional_catalog_types()
    master_version = str(master_meta.get("source_version", master_meta.get("version", ""))) + str(master_meta.get("content_sha256") or master_meta.get("erro") or "")
    catalog_version = str(catalog_meta.get("source_version", catalog_meta.get("version", ""))) + str(catalog_meta.get("content_sha256") or catalog_meta.get("erro") or "")
    enriched = issue._operational_snapshot(
        tokens, history_tokens, chosen, master_version, catalog_version,
        stages.VERSION, model, master_records, catalog_types)
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
    st.markdown('<div class="section-title">RELATÓRIOS</div>', unsafe_allow_html=True)
    st.caption("Exporte o resumo do estoque, todas as OPs da conferência ou as movimentações KARDEX em arquivos independentes.")
    choice = st.radio("TIPO DE RELATÓRIO", REPORT_NAMES, key="fm_reports_kind",
                      horizontal=True)
    st.markdown("### Período e critérios")
    start, end, period_key = _date_controls()
    if not period_key:
        return

    extra = {}
    warehouses = []
    if choice != REPORT_NAMES[0]:
        try:
            sources = movement_store.list_imports()
            options = _known_warehouses(sources)
        except Exception as exc:
            options = []
            st.caption(f"Armazéns do histórico não disponíveis para seleção: {exc}")
        if options:
            warehouses = st.multiselect(
                "ARMAZÉNS (vazio = todos)", options, key="fm_reports_wh",
            )

    if choice == REPORT_NAMES[0]:
        st.caption("O Dashboard utiliza competências mensais. Datas intermediárias selecionam os meses correspondentes, não saldos diários.")
        if not imports:
            st.warning("Ainda não existem competências de estoque disponíveis para exportação.")
            return
        sheet_count = 4
    elif choice == REPORT_NAMES[1]:
        st.caption("Uma linha por OP/produto. O filtro de período seleciona a OP quando houver SEPARAÇÃO, CONFERÊNCIA ou BAIXA entre as datas. Os demais produtos da OP são preservados.")
        available_statuses = [
            stages.FINALIZADO_PATIO, stages.FINALIZADO_ENTREGUE,
            stages.NF_EMITIDA, stages.FINALIZADO, stages.REPORTADO,
            stages.EM_CONFERENCIA, stages.EM_SEPARACAO, stages.AGUARDANDO_INICIO,
        ]
        extra["status"] = st.selectbox(
            "STATUS DA OP", ["Todos os status"] + available_statuses,
            key="fm_reports_issue_status",
        )
        extra["alerts"] = st.checkbox(
            "Somente OPs com alerta", key="fm_reports_alerts",
        )
        extra["types"] = st.multiselect(
            "TIPOS DE MATERIAL (vazio = todos)", ["EP", "II", "MP", "PA", "PI", "NI"],
            key="fm_reports_types",
        )
        if extra["types"]:
            st.caption("O filtro de tipo limita os produtos exportados. Sem filtro, a OP selecionada sempre inclui todos os seus produtos.")
        sheet_count = 1
    else:
        extra["summary_only"] = st.radio(
            "NÍVEL DE APRESENTAÇÃO", ["Completo — grupos, OPs e movimentações",
                                      "Resumo gerencial — grupos e TES"],
            key="fm_reports_detail",
        ).startswith("Resumo")
        extra["types"] = st.multiselect(
            "TIPOS DE MATERIAL (vazio = todos)", ["EP", "II", "MP", "PA", "PI"],
            key="fm_reports_kardex_types",
        )
        try:
            group_cfg = movement._groups_read()
            group_options = [entry["nome"] for entry in group_cfg.get("grupos", [])]
            group_options.append("SEM GRUPO")
        except Exception:
            group_options = []
        extra["groups"] = st.multiselect(
            "GRUPOS GERENCIAIS (vazio = todos)", group_options,
            key="fm_reports_groups",
        )
        extra["tes"] = st.text_input(
            "TES (opcional, códigos separados por vírgula)", key="fm_reports_tes",
            placeholder="Ex.: 020, 520",
        )
        sheet_count = 1 if extra["summary_only"] else 3

    st.info(f"**{choice.upper()}** · {sheet_count} aba(s) · " +
            ("histórico completo" if start is None else f"{start:%d/%m/%Y} a {end:%d/%m/%Y}"))
    report_key = hashlib.sha256(repr((
        reports.EXPORT_SCHEMA_VERSION,
        choice, period_key, tuple(warehouses), extra,
        [(row.get("competencia"), row.get("status"), row.get("importado_em"))
         for row in imports] if choice == REPORT_NAMES[0] else None,
    )).encode("utf-8")).hexdigest()

    if st.button("PREPARAR RELATÓRIO EXCEL", type="primary", use_container_width=True,
                 key="fm_reports_prepare"):
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
                        st.warning("CADASTROS indisponível: a classificação de tipo de material pode estar incompleta.")
                    if model.get("catalog_price_meta", {}).get("erro"):
                        st.warning("Preço ULT. PRECO indisponível: previsões de baixa ficarão em branco quando não houver custo cadastrado.")
                    if not model.get("history_available"):
                        st.warning("KARDEX indisponível: as baixas desconhecidas não serão transformadas em zero.")
                    statuses = ({extra["status"]} if extra["status"] != "Todos os status" else None)
                    types = set(extra["types"]) if extra["types"] else None
                    rows = reports.issue_rows(
                        model, start, end, statuses=statuses,
                        alerts_only=extra["alerts"], material_types=types)
                    if not rows:
                        raise ValueError("Nenhuma OP com atividade ou produto corresponde ao recorte selecionado.")
                    data = reports.export_issues(
                        model, start, end, statuses=statuses,
                        alerts_only=extra["alerts"], material_types=types)
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
            st.session_state["fm_reports_ready"] = (
                report_key, data,
                f"{prefix}_SETTA_{period_key}_R3.xlsx"
                if choice == REPORT_NAMES[1]
                else f"{prefix}_SETTA_{period_key}.xlsx",
                records
            )
        except Exception as exc:
            st.session_state.pop("fm_reports_ready", None)
            st.error(f"Não foi possível preparar o relatório: {exc}")

    prepared = st.session_state.get("fm_reports_ready")
    if prepared and prepared[0] == report_key:
        st.success(f"Relatório preparado: {prepared[3]:,} registro(s).".replace(",", "."))
        st.download_button(
            "BAIXAR EXCEL", data=prepared[1], file_name=prepared[2], mime=MIME,
            use_container_width=True, key="fm_reports_download")
    st.caption("As exportações não alteram dados, regras, conferências ou os históricos persistidos.")
