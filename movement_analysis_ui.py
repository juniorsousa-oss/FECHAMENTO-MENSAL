"""Movement analysis using the Dashboard's shared SETTA layout."""
from __future__ import annotations

import hashlib
import html
import math
from datetime import date

import pandas as pd
import streamlit as st

import movement_store as store
import movements as mv

AREAS = ["Visão geral", "Grupos e TES", "Por OP", "Movimentações", "Classificação"]
MONEY_COLUMNS = {"valor_entrada": "Entrada (R$)", "valor_saida": "Saída (R$)", "liquido_valor": "Variação (R$)"}
NAMES = {"grupo_analise": "Grupo", "subgrupo_analise": "Subgrupo / condição", "tes": "TES", "descricao_tes": "Descrição principal",
         "lancamentos": "Movimentos", "produtos": "Produtos", "tes_distintas": "TES distintas", "competencia": "Competência",
         "op_identificada": "OP", "documentos": "Documentos", "primeira_data": "Primeiro movimento", "ultima_data": "Último movimento",
         "enderecamentos": "Movimentos de endereço", **MONEY_COLUMNS}


def cash(value) -> str:
    text = f"{abs(float(value or 0)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {'-' if float(value or 0) < 0 else ''}{text}"


def count(value) -> str:
    return f"{int(value):,}".replace(",", ".")


def quantity(value) -> str:
    return format(mv.decimal(value), ",f").replace(",", "X").replace(".", ",").replace("X", ".")


def band(kicker, title, note=""):
    st.markdown(
        '<div class="section-band">'
        f'<div class="section-band-kicker">{html.escape(kicker)}</div>'
        f'<div class="section-band-title">{html.escape(title)}</div>'
        f'<div class="section-band-note">{html.escape(note)}</div></div>', unsafe_allow_html=True,
    )


def cards(items):
    cells = ['<div class="summary-grid">']
    for label, value in items:
        cells.append('<div class="summary-card">'
                     f'<div class="summary-card-label">{html.escape(label)}</div>'
                     f'<div class="summary-card-value">{html.escape(value)}</div></div>')
    st.markdown("".join(cells) + "</div>", unsafe_allow_html=True)


@st.cache_data(show_spinner=False, ttl=45)
def _imports():
    return store.list_imports()


@st.cache_resource(show_spinner=False, ttl=300, max_entries=2)
def _model(tokens: tuple, version: str):
    del version
    return mv.build_model([store.load_import(key) for key, updated in tokens])


def _reload():
    _imports.clear()
    _model.clear()


def _selected(key):
    state = st.session_state.get(key) or {}
    selected = state.get("selection") or {}
    rows = selected.get("rows") or []
    return int(rows[0]) if rows else None


def _group_selected(key, names):
    position = _selected(key)
    if position is None or position >= len(names):
        return
    st.session_state.fm_mov_groups = [names[position]]
    st.session_state.fm_mov_tes = []
    st.session_state.fm_mov_subgroups = []
    st.session_state.fm_mov_area = "Grupos e TES"


def _tes_selected(key, values):
    position = _selected(key)
    if position is None or position >= len(values):
        return
    group, tes, subgroup = values[position]
    st.session_state.fm_mov_groups = [group]
    st.session_state.fm_mov_tes = [tes]
    st.session_state.fm_mov_subgroups = [subgroup]
    st.session_state.fm_mov_area = "Movimentações"
    st.session_state.fm_mov_page = 1


def _op_selected(key, values):
    position = _selected(key)
    if position is None or position >= len(values):
        return
    st.session_state.fm_mov_op = values[position]
    st.session_state.fm_mov_area = "Movimentações"
    st.session_state.fm_mov_page = 1


def _clear_filters():
    for key in ("fm_mov_groups", "fm_mov_tes", "fm_mov_subgroups", "fm_mov_categories"):
        st.session_state[key] = []
    for key in ("fm_mov_search", "fm_mov_op", "fm_mov_cc"):
        st.session_state[key] = ""
    st.session_state.fm_mov_page = 1


def _adjustments():
    _clear_filters()
    st.session_state.fm_mov_groups = [mv.ADJUSTMENT]
    st.session_state.fm_mov_area = "Grupos e TES"


def _all_groups():
    st.session_state.fm_mov_groups = []
    st.session_state.fm_mov_tes = []
    st.session_state.fm_mov_subgroups = []
    st.session_state.fm_mov_area = "Grupos e TES"


def _multiselect(label, options, key, format_func=None):
    if key in st.session_state:
        valid = [v for v in st.session_state[key] if v in options]
        if valid != st.session_state[key]:
            st.session_state[key] = valid
    args = {"format_func": format_func} if format_func else {}
    return st.multiselect(label, options, key=key, **args)


def _table(data: pd.DataFrame, key=None, on_select=None, height=600):
    shown = data.rename(columns=NAMES)
    fmt = {label: cash for label in MONEY_COLUMNS.values() if label in shown.columns}
    styled = shown.style.format(fmt, na_rep="—") if fmt else shown
    args = {"key": key} if key else {}
    if on_select:
        args.update(on_select=on_select, selection_mode="single-row")
    return st.dataframe(styled, hide_index=True, width="stretch",
                        height=min(height, max(120, 77 + 35*min(len(shown), 100))), **args)


def _view_token(frame, extra=""):
    digest = hashlib.sha256()
    digest.update(mv.rules()["versao"].encode())
    digest.update(extra.encode())
    digest.update("|".join(frame["id_registro"].tolist()).encode())
    return digest.hexdigest()[:16]


def _import_controls(imports):
    with st.expander("IMPORTAR RELATÓRIOS E ACESSAR O HISTÓRICO", expanded=not imports):
        st.caption("Importe os arquivos originais KARDEX (.xlsx/.xltx) ou a base histórica (.zip). O arquivo já importado é reconhecido pelo conteúdo.")
        with st.form("fm_mov_import_form", clear_on_submit=True):
            files = st.file_uploader("Relatórios de movimentação", type=["xlsx", "xltx", "zip"], accept_multiple_files=True, key="fm_mov_uploads")
            submitted = st.form_submit_button("IMPORTAR RELATÓRIOS", type="primary")
        if submitted:
            if not files:
                st.info("Selecione ao menos um relatório.")
            else:
                try:
                    with st.spinner("Conferindo os relatórios e salvando o histórico..."):
                        # Validate the complete selection before writing any of its files.
                        parsed = [mv.parse_report(file.getvalue(), file.name) for file in files]
                        known = list(imports); saved = unchanged = 0
                        for item in parsed:
                            result = store.save_import(item, known)
                            saved += result["saved"]; unchanged += not result["saved"]
                            known.append({"chave": result["key"]})
                    _reload()
                    st.session_state.fm_mov_flash = f"{saved} arquivo(s) salvo(s); {unchanged} já estavam no histórico."
                    st.rerun()
                except Exception as exc:
                    _reload()  # a previous file may have committed before a later transfer failed
                    st.error(f"A importação não foi concluída: {exc}. Reenviar arquivos já salvos não duplica movimentos.")
        if imports:
            history = pd.DataFrame([{"Arquivo": (i.get("meta") or {}).get("arquivo_nome"),
                                     "De": (i.get("meta") or {}).get("periodo_inicio"),
                                     "Até": (i.get("meta") or {}).get("periodo_fim"),
                                     "Movimentos no arquivo": (i.get("meta") or {}).get("lancamentos"),
                                     "Importado em": str(i.get("atualizado_em") or "")[:19].replace("T", " ")}
                                    for i in imports])
            st.dataframe(history, hide_index=True, width="stretch")


def _filters(frame, imports):
    months = sorted(frame["competencia"].unique())
    requested = str(st.query_params.get("mes") or "")
    if "fm_mov_month" not in st.session_state:
        st.session_state.fm_mov_month = requested if requested in months else months[-1]
    if st.session_state.fm_mov_month not in months:
        st.session_state.fm_mov_month = months[-1]
    first, second, third = st.columns([1.05, 1.5, 1])
    with first:
        month = st.selectbox("Competência analisada", months, format_func=lambda m:m[5:]+"/"+m[:4], key="fm_mov_month")
    with second:
        mode = st.selectbox("Período da análise", ["MÊS SELECIONADO", "ACUMULADO DO ANO", "TODO O HISTÓRICO"], key="fm_mov_period")
    selected_date = date.fromisoformat(month+"-01")
    if mode == "MÊS SELECIONADO":
        view = frame.loc[frame["competencia"] == month]
    elif mode == "ACUMULADO DO ANO":
        view = frame.loc[frame["competencia"].between(month[:4]+"-01", month)]
    else:
        view = frame
    if str(st.query_params.get("mes") or "") != month:
        st.query_params["mes"] = month
    with third:
        warehouses = sorted(view["armazem"].unique())
        if len(warehouses) > 1:
            chosen = _multiselect("Armazéns", warehouses, "fm_mov_warehouses")
            if chosen:
                view = view.loc[view["armazem"].isin(chosen)]
        else:
            st.markdown("**ARMAZÉM**")
            st.write(warehouses[0] if warehouses else "—")
    coverage_end = max((str((i.get("meta") or {}).get("periodo_fim") or "") for i in imports), default="")
    if coverage_end and coverage_end[:7] == month:
        if selected_date.month == 12:
            next_month = date(selected_date.year+1, 1, 1)
        else:
            next_month = date(selected_date.year, selected_date.month+1, 1)
        from datetime import timedelta
        if coverage_end < (next_month - timedelta(days=1)).isoformat():
            st.caption(f"PERÍODO PARCIAL · histórico disponível até {date.fromisoformat(coverage_end).strftime('%d/%m/%Y')}.")
    warehouse_view = view
    a, b, c = st.columns([1.25, 1, 1.5])
    with a:
        group_options = sorted(view["grupo_analise"].unique())
        groups = _multiselect("Grupo de análise", group_options, "fm_mov_groups")
    if groups:
        view = view.loc[view["grupo_analise"].isin(groups)]
    with b:
        tes = _multiselect("TES", sorted(view["tes"].unique()), "fm_mov_tes")
    if tes:
        view = view.loc[view["tes"].isin(tes)]
    with c:
        search = st.text_input("Produto, documento ou vínculo AE", key="fm_mov_search", placeholder="Código, descrição, documento ou OP")
    if search.strip():
        view = view.loc[view["_search"].str.contains(mv.normalized(search), regex=False)]
    expanded = bool(st.session_state.get("fm_mov_subgroups") or st.session_state.get("fm_mov_op") or st.session_state.get("fm_mov_cc"))
    with st.expander("FILTROS ADICIONAIS", expanded=expanded):
        a, b = st.columns(2)
        with a:
            subs = _multiselect("Subgrupo / condição", sorted(view["subgrupo_analise"].unique()), "fm_mov_subgroups")
            op = st.text_input("OP", key="fm_mov_op", placeholder="OP ou número completo/parcial")
        with b:
            cc = st.text_input("CC / CR", key="fm_mov_cc", placeholder="Ex.: 600307")
            categories = _multiselect("Categoria do produto", sorted(view["tipo"].unique()), "fm_mov_categories")
    if subs:
        view = view.loc[view["subgrupo_analise"].isin(subs)]
    if op.strip():
        view = view.loc[view["op_identificada"].str.contains(op.strip().upper(), regex=False)]
    if cc.strip():
        view = view.loc[view["cc_identificado"].str.contains(cc.strip(), regex=False)]
    if categories:
        view = view.loc[view["tipo"].isin(categories)]
    st.button("LIMPAR FILTROS", key="fm_mov_clear", on_click=_clear_filters)
    if not view.empty:
        start, end = date.fromisoformat(view["data"].min()), date.fromisoformat(view["data"].max())
        st.caption(f"MOVIMENTOS DO RECORTE · {start:%d/%m/%Y} A {end:%d/%m/%Y}.")
    return view.copy(), warehouse_view


def _ordered_groups(frame):
    grouped = mv.summarize(mv.effective(frame), ["grupo_analise"])
    order = {name:i for i, name in enumerate(mv.rules()["ordem_grupos"])}
    grouped["_order"] = grouped["grupo_analise"].map(order).fillna(999)
    return grouped.sort_values(["_order", "grupo_analise"]).drop(columns="_order").reset_index(drop=True)


def _groups_table(frame, token):
    summary = _ordered_groups(frame)
    key = "fm_mov_group_table_" + token
    names = summary["grupo_analise"].tolist()
    _table(summary[["grupo_analise", "tes_distintas", "lancamentos", "valor_entrada", "valor_saida", "liquido_valor"]],
           key=key, on_select=lambda:_group_selected(key, names))


def _overview(frame, token):
    current = mv.effective(frame)
    cards([("ENTRADAS EFETIVAS", cash(current["valor_entrada"].sum())), ("SAÍDAS EFETIVAS", cash(current["valor_saida"].sum())),
           ("VARIAÇÃO DO PERÍODO", cash(current["liquido_valor"].sum()))])
    st.caption(f"{count(len(frame))} registros · {count(frame.codigo.nunique())} produtos · {count(frame.tes.nunique())} TES distintas · "
               f"{count(frame.loc[frame.op_identificada != '', 'op_identificada'].nunique())} OPs. Variação = entradas − saídas.")
    band("01 · GRUPOS", "MOVIMENTAÇÕES POR GRUPO", "Selecione uma linha para abrir as TES e condições do grupo.")
    _groups_table(frame, token + "_overview")
    band("02 · HISTÓRICO", "EVOLUÇÃO MENSAL", "Valores consolidados dos movimentos efetivos no recorte selecionado.")
    monthly = mv.summarize(current, ["competencia"]).sort_values("competencia")
    _table(monthly[["competencia", "lancamentos", "valor_entrada", "valor_saida", "liquido_valor"]])


def _groups(frame, token):
    active = mv.effective(frame)
    band("02 · GRUPOS E TES", "CLASSIFICAÇÃO POR TES E CONDIÇÃO", "A mesma TES pode aparecer em mais de um grupo; cada movimento é contado uma vez.")
    if len(st.session_state.get("fm_mov_groups") or []) != 1:
        _groups_table(frame, token + "_groups")
        st.caption("Selecione um grupo na tabela ou use o filtro Grupo de análise para abrir suas condições.")
        return
    st.button("TODOS OS GRUPOS", key="fm_mov_all_groups", on_click=_all_groups)
    branches = mv.summarize(active, ["grupo_analise", "tes", "descricao_tes", "subgrupo_analise"])
    branches = branches.sort_values(["tes", "subgrupo_analise"]).reset_index(drop=True)
    key = "fm_mov_tes_table_" + token
    values = list(branches[["grupo_analise", "tes", "subgrupo_analise"]].itertuples(index=False, name=None))
    _table(branches[["tes", "descricao_tes", "subgrupo_analise", "lancamentos", "valor_entrada", "valor_saida", "liquido_valor"]],
           key=key, on_select=lambda:_tes_selected(key, values))
    st.caption("Selecione uma condição para consultar os movimentos que compõem seu valor.")


def _ops(frame, token):
    summary = mv.summarize_ops(frame)
    linked = frame.loc[frame["op_identificada"] != ""]
    cards([("OPS IDENTIFICADAS", count(len(summary))), ("MOVIMENTOS COM OP", count(len(linked))),
           ("SAÍDAS EFETIVAS COM OP", cash(mv.effective(linked)["valor_saida"].sum()))])
    band("03 · ORDENS DE PRODUÇÃO", "REGISTROS POR OP", "Selecione uma OP para consultar seus produtos, documentos e movimentações.")
    if summary.empty:
        st.info("Nenhuma movimentação com OP no recorte selecionado.")
        return
    key = "fm_mov_op_table_" + token
    values = summary["op_identificada"].tolist()
    _table(summary, key=key, on_select=lambda:_op_selected(key, values))


def _detail(row):
    band("REGISTRO ORIGINAL", row["codigo"] + " · " + row["descricao"], "Informações do relatório e motivo da classificação aplicada.")
    a, b, c = st.columns(3)
    with a:
        st.write("**DATA:** " + date.fromisoformat(row["data"]).strftime("%d/%m/%Y"))
        st.write("**TES:** " + row["tes"] + " · " + row["descricao_tes"])
        st.write("**DOCUMENTO:** " + row["documento"])
    with b:
        st.write("**ARMAZÉM:** " + row["armazem"])
        st.write("**CATEGORIA:** " + row["tipo"])
        st.write("**CC / CR:** " + (row["cc_identificado"] or "—"))
    with c:
        st.write("**AE ORIGINAL:**")
        st.code(row["ae_original"], language=None)
        st.write("**OP:** " + (row["op_identificada"] or "—"))
    st.write(f"**ENTRADA:** {quantity(row['qtd_entrada'])} {row['um']} · {cash(row['valor_entrada'])}")
    st.write(f"**SAÍDA:** {quantity(row['qtd_saida'])} {row['um']} · {cash(row['valor_saida'])}")
    st.write("**GRUPO:** " + row["grupo_analise"])
    st.write("**SUBGRUPO:** " + row["subgrupo_analise"])
    st.info(row["motivo_classificacao"])
    if row["enderecamento_compensado"]:
        st.info("Movimentação de endereço compensada. O registro permanece visível e não compõe as entradas ou saídas efetivas.")
    elif row["enderecamento_candidato"]:
        st.warning("Possível par de endereçamento com diferença de quantidade. O valor permanece nos totais até a conferência.")
    st.caption(f"Origem: {row['arquivo_origem']} · linha {int(row['linha_origem'])} · regra {row['versao_regra']}.")


def _ledger(frame, token):
    band("04 · REGISTRO", "MOVIMENTAÇÕES DO RELATÓRIO", "Selecione uma linha para abrir o registro original e o motivo da classificação.")
    st.caption(f"{count(len(frame))} registros encontrados. A exportação inclui todo o recorte, independentemente da página.")
    a, b = st.columns(2)
    with a:
        size = st.selectbox("Registros por página", [100, 250, 500], key="fm_mov_page_size")
    pages = max(1, math.ceil(len(frame) / size))
    if st.session_state.get("fm_mov_page", 1) > pages:
        st.session_state.fm_mov_page = pages
    with b:
        page = st.number_input("Página", min_value=1, max_value=pages, step=1, key="fm_mov_page")
    ordered = frame.sort_values(["data", "codigo", "linha_origem", "id_registro"], ascending=[False, True, True, True], kind="stable")
    visible = ordered.iloc[(page-1)*size:page*size]
    shown = pd.DataFrame({"Data": pd.to_datetime(visible["data"]).dt.date, "Código": visible["codigo"], "Produto": visible["descricao"],
                          "Armazém": visible["armazem"], "TES": visible["tes"], "Entrada (R$)": visible["valor_entrada"],
                          "Saída (R$)": visible["valor_saida"], "AE original": visible["ae_original"], "Grupo": visible["grupo_analise"],
                          "Subgrupo": visible["subgrupo_analise"], "Endereçamento compensado": visible["enderecamento_compensado"]})
    key = f"fm_mov_ledger_{token}_{page}_{size}"
    event = st.dataframe(shown, key=key, hide_index=True, width="stretch", height=600,
                         on_select="rerun", selection_mode="single-row",
                         column_config={"Data": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                        "Entrada (R$)": st.column_config.NumberColumn(format="%.2f"),
                                        "Saída (R$)": st.column_config.NumberColumn(format="%.2f")})
    selected = (event.get("selection") or {}).get("rows") or []
    if selected and selected[0] < len(visible):
        with st.expander("DETALHAMENTO DO REGISTRO", expanded=True):
            _detail(visible.iloc[selected[0]])


def _classification(frame, model):
    band("05 · CLASSIFICAÇÃO", "REGRAS CONFIRMADAS", "A condição específica de chapas e barras tem prioridade sobre as condições genéricas da TES 520.")
    specs = [
        (mv.CLOSING_RULE, "020 / 520 · chapa ou barra de cobre", mv.FLOW, mv.CLOSING),
        ("520_OP_MANUAL", "520 · AE com OP", mv.FLOW, "BAIXA DE OP MANUAL"),
        ("520_CC_GERENCIAL", "520 · CC diferente de 600307", mv.FLOW, "ACERTO GERENCIAL"),
        ("520_CC_CONSUMO", "520 · CC 600307 e II, MC ou código da lista H0001", mv.FLOW, "MATERIAIS DE CONSUMO"),
        ("AJUSTE_PA_PI_PRODUCAO_INTERNA", "PA / PI que permanecia em Ajuste", mv.PRODUCTION, mv.PRODUCTION),
    ]
    active = mv.effective(frame)
    rows = [{"Ordem": i, "Condição": condition, "Grupo": group, "Subgrupo": sub,
             "Movimentos no recorte": int((active["regra_classificacao"] == code).sum())}
            for i, (code, condition, group, sub) in enumerate(specs, 1)]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    adjustments = active.loc[active["grupo_analise"] == mv.ADJUSTMENT]
    st.info(f"{count(len(adjustments))} movimentos permanecem em Ajuste de Estoque e aguardam refinamento das condições.")
    st.button("DETALHAR AJUSTES A REFINAR", on_click=_adjustments, disabled=adjustments.empty, key="fm_mov_adjustments")
    provisional = active.loc[active["grupo_provisorio"]]
    if not provisional.empty:
        with st.expander("GRUPOS PROVISÓRIOS POR DESCRIÇÃO DA TES"):
            _table(mv.summarize(provisional, ["tes", "descricao_tes", "grupo_analise"]))
    ids = set(frame["id_registro"])
    candidates = [pair for pair in model["pares_enderecamento"] if pair["entrada_id"] in ids or pair["saida_id"] in ids]
    with st.expander(f"PARES DE ENDEREÇAMENTO COM DIFERENÇA DE QUANTIDADE · {len(candidates)}"):
        if candidates:
            data = pd.DataFrame(candidates).drop(columns=["entrada_id", "saida_id"]).rename(columns={
                "codigo": "Código", "data": "Data", "documento": "Documento", "armazem": "Armazém", "um": "UM",
                "quantidade_entrada": "Quantidade entrada", "quantidade_saida": "Quantidade saída", "diferenca": "Diferença"})
            st.dataframe(data, hide_index=True, width="stretch")
            st.caption("Confira no sistema se as diferenças decorrem de arredondamento da mesma transferência. Esses pares continuam nos totais.")
        else:
            st.caption("Nenhum par nessas condições no recorte selecionado.")
    with st.expander("CRITÉRIOS GERAIS"):
        st.write("• A descrição principal da TES segue o cadastro confirmado.")
        st.write("• Uma TES sem grupo confirmado utiliza a descrição como grupo provisório.")
        st.write("• Pares 499/999 só deixam os totais efetivos quando compensam produto, armazém, documento, data, quantidade e valor. A presença de OP não impede a compensação.")
        st.write("• A coluna AE original é preservada, incluindo o número completo da OP.")
        st.caption(f"Regras {model['versao']} · {len(mv.rules()['materiais_h001'])} materiais vinculados à lista H0001.")


def _exports(frame, model, token):
    with st.expander("EXPORTAR RELATÓRIO E BASE HISTÓRICA"):
        a, b = st.columns(2)
        with a:
            if st.button("PREPARAR EXCEL DO RECORTE", key="fm_mov_prepare_excel"):
                with st.spinner("Preparando o Excel com os registros do recorte..."):
                    st.session_state.fm_mov_excel = (token, mv.export_excel(frame))
            prepared = st.session_state.get("fm_mov_excel")
            if prepared and prepared[0] == token:
                st.download_button("BAIXAR EXCEL DO RECORTE", prepared[1], file_name="Analise_Movimentacoes.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="fm_mov_download_excel")
        with b:
            if st.button("PREPARAR BASE HISTÓRICA COMPLETA", key="fm_mov_prepare_history"):
                with st.spinner("Preparando a base histórica completa..."):
                    st.session_state.fm_mov_history = (model["token"], mv.export_history(model))
            prepared = st.session_state.get("fm_mov_history")
            if prepared and prepared[0] == model["token"]:
                st.download_button("BAIXAR BASE HISTÓRICA", prepared[1], file_name="Base_Historica_KARDEX.zip",
                                   mime="application/zip", key="fm_mov_download_history")
        st.caption("O Excel respeita os filtros e mantém a AE original na coluna AE. A base histórica contém todos os períodos importados.")


def render_movement_analysis():
    band("MOVIMENTAÇÕES", "ANÁLISE DE MOVIMENTAÇÕES", "Histórico KARDEX · grupos e TES · vínculos por OP · rastreabilidade de cada registro.")
    flash = st.session_state.pop("fm_mov_flash", None)
    if flash:
        st.success(flash)
    try:
        imports = _imports()
    except Exception as exc:
        st.error(f"Não foi possível carregar o histórico de movimentações: {exc}")
        st.button("RECARREGAR HISTÓRICO", key="fm_mov_retry", on_click=_reload)
        return
    _import_controls(imports)
    if not imports:
        st.info("Importe os relatórios KARDEX para iniciar a análise e formar o histórico.")
        return
    try:
        with st.spinner("Carregando o histórico de movimentações..."):
            tokens = tuple((i["chave"], i.get("atualizado_em", "")) for i in imports)
            model = _model(tokens, mv.rules()["versao"])
    except Exception as exc:
        st.error(f"Não foi possível conferir os registros do histórico: {exc}")
        st.button("RECARREGAR HISTÓRICO", key="fm_mov_model_retry", on_click=_reload)
        return
    frame = model["frame"]
    if frame.empty:
        st.info("O histórico não possui movimentações.")
        return
    view, scope = _filters(frame, imports)
    if view.empty:
        st.info("Nenhuma movimentação corresponde aos filtros selecionados.")
        return
    confirmed = int(view["enderecamento_compensado"].sum())
    if confirmed:
        st.caption(f"{count(confirmed)} registros de endereço compensados permanecem disponíveis na consulta e estão fora dos valores efetivos.")
    token = _view_token(view)
    area = st.radio("Área da análise", AREAS, horizontal=True, key="fm_mov_area", label_visibility="collapsed")
    if area == "Visão geral":
        _overview(view, token)
    elif area == "Grupos e TES":
        _groups(view, token)
    elif area == "Por OP":
        _ops(view, token)
    elif area == "Movimentações":
        _ledger(view, token)
    else:
        _classification(view, model)
    _exports(view, model, token)
    if model["duplicates"]:
        st.caption(f"Importações sobrepostas: {count(model['duplicates'])} repetições já reconhecidas na base histórica, sem soma em duplicidade.")
