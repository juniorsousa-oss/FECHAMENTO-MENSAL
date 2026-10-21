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

AREAS = ["Visão geral", "Grupos e TES", "Por OP", "Movimentações", "Classificação", "Fontes e relatórios"]
AREA_LABELS = {"Visão geral": "Resumo", "Por OP": "Consulta por OP", "Movimentações": "Registros"}
FILTER_AREAS = {"Grupos e TES": "groups", "Por OP": "ops", "Movimentações": "ledger"}
FILTER_FIELDS = {"groups": "Grupo", "tes": "TES", "subgroups": "Condição", "search": "Busca",
                 "op": "OP", "cc": "CC / CR", "categories": "Categoria"}
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
    _set_filters("Grupos e TES", {"groups": [names[position]]})
    st.session_state.fm_mov_area = "Grupos e TES"


def _tes_selected(key, values):
    position = _selected(key)
    if position is None or position >= len(values):
        return
    group, tes, subgroup = values[position]
    _open_records({"groups": [group], "tes": [tes], "subgroups": [subgroup]}, "Grupos e TES")


def _op_selected(key, values):
    position = _selected(key)
    if position is None or position >= len(values):
        return
    _open_records({"op": values[position]}, "Por OP")


def _defaults():
    return {"groups": [], "tes": [], "subgroups": [], "categories": [], "search": "", "op": "", "cc": ""}


def _filter_key(area, field):
    return f"fm_mov_{FILTER_AREAS[area]}_{field}"


def _values(area):
    return {**_defaults(), **st.session_state.get("fm_mov_local_filters", {}).get(area, {})}


def _set_filters(area, values):
    current = {**_defaults(), **values}
    state = dict(st.session_state.get("fm_mov_local_filters", {}))
    state[area] = current
    st.session_state.fm_mov_local_filters = state
    # Called before rendering or from callbacks, including widgets not rendered in this area.
    for field, value in current.items():
        st.session_state[_filter_key(area, field)] = value
    st.session_state.fm_mov_page = 1


def _remember_filter(area, field, key):
    values = _values(area)
    values[field] = st.session_state[key]
    state = dict(st.session_state.get("fm_mov_local_filters", {}))
    state[area] = values
    st.session_state.fm_mov_local_filters = state
    st.session_state.fm_mov_page = 1


def _open_records(values, origin):
    _set_filters("Movimentações", values)
    st.session_state.fm_mov_record_origin = origin
    st.session_state.fm_mov_area = "Movimentações"


def _go_to(area):
    st.session_state.fm_mov_area = area


def _clear_filters(area):
    _set_filters(area, {})
    if area == "Movimentações":
        st.session_state.pop("fm_mov_record_origin", None)


def _adjustments():
    _set_filters("Grupos e TES", {"groups": [mv.ADJUSTMENT]})
    st.session_state.fm_mov_area = "Grupos e TES"


def _all_groups():
    _set_filters("Grupos e TES", {})
    st.session_state.fm_mov_area = "Grupos e TES"


def _multiselect(label, options, key, format_func=None):
    if key in st.session_state:
        valid = [v for v in st.session_state[key] if v in options]
        if valid != st.session_state[key]:
            st.session_state[key] = valid
    args = {"format_func": format_func} if format_func else {}
    return st.multiselect(label, options, key=key, **args)


def _local_input(area, field, label, *, options=None, placeholder=None):
    key = _filter_key(area, field)
    value = _values(area)[field]
    if options is not None:
        valid = [v for v in value if v in options]
        if valid != value:
            state = dict(st.session_state.get("fm_mov_local_filters", {}))
            state[area] = {**_values(area), field: valid}
            st.session_state.fm_mov_local_filters = state
        value = valid
    if key not in st.session_state or st.session_state[key] != value:
        st.session_state[key] = value
    args = {"key": key, "on_change": _remember_filter, "args": (area, field, key)}
    if options is None:
        return st.text_input(label, placeholder=placeholder, **args)
    return st.multiselect(label, options, placeholder="Todos", **args)


def _apply_filters(frame, values):
    view = frame
    for field, column in (("groups", "grupo_analise"), ("tes", "tes"),
                          ("subgroups", "subgrupo_analise"), ("categories", "tipo")):
        if values.get(field):
            view = view.loc[view[column].isin(values[field])]
    search = mv.normalized(values.get("search", ""))
    if search:
        view = view.loc[view["_search"].str.contains(search, regex=False)]
    for field, column in (("op", "op_identificada"), ("cc", "cc_identificado")):
        text = str(values.get(field) or "").strip().upper()
        if text:
            view = view.loc[view[column].str.contains(text, regex=False)]
    return view.copy()


def _consultation_filters(frame, area):
    if area == "Grupos e TES":
        a, b = st.columns(2)
        with a:
            groups = _local_input(area, "groups", "Grupo de análise", options=sorted(frame["grupo_analise"].unique()))
        with b:
            options = frame.loc[frame["grupo_analise"].isin(groups)] if groups else frame
            _local_input(area, "tes", "TES", options=sorted(options["tes"].unique()))
    elif area == "Por OP":
        _local_input(area, "search", "Buscar OP ou material", placeholder="Número da OP, código ou descrição do produto")
    else:
        _local_input(area, "search", "Buscar nos registros", placeholder="Produto, documento ou vínculo AE")
        active = sum(bool(v) for k, v in _values(area).items() if k != "search")
        title = "REFINAR CONSULTA" + (f" · {active} filtro(s) ativo(s)" if active else "")
        with st.expander(title):
            a, b, c = st.columns(3)
            with a:
                _local_input(area, "groups", "Grupo de análise", options=sorted(frame["grupo_analise"].unique()))
                _local_input(area, "subgroups", "Subgrupo / condição", options=sorted(frame["subgrupo_analise"].unique()))
            with b:
                _local_input(area, "tes", "TES", options=sorted(frame["tes"].unique()))
                _local_input(area, "categories", "Categoria do produto", options=sorted(frame["tipo"].unique()))
            with c:
                _local_input(area, "op", "OP", placeholder="OP ou número completo/parcial")
                _local_input(area, "cc", "CC / CR", placeholder="Ex.: 600307")
    values = _values(area)
    # Read the current widget values as options can change when switching period or warehouse.
    for field in values:
        key = _filter_key(area, field)
        if key in st.session_state:
            values[field] = st.session_state[key]
    active = [f"{FILTER_FIELDS[k]}: {', '.join(v) if isinstance(v, list) else v}" for k, v in values.items() if v]
    if active:
        st.caption("FILTROS DESTA CONSULTA · " + " · ".join(active))
        st.button("LIMPAR CONSULTA", on_click=_clear_filters, args=(area,), key=f"fm_mov_clear_{FILTER_AREAS[area]}")
    return _apply_filters(frame, values)


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


def _context(frame, imports):
    months = sorted(frame["competencia"].unique())
    requested = str(st.query_params.get("mes") or "")
    if "fm_mov_month" not in st.session_state:
        st.session_state.fm_mov_month = requested if requested in months else months[-1]
    if st.session_state.fm_mov_month not in months:
        st.session_state.fm_mov_month = months[-1]
    mode = st.session_state.get("fm_mov_period", "MÊS SELECIONADO")
    month = st.session_state.fm_mov_month
    modes = {"MÊS SELECIONADO": "Mensal", "ACUMULADO DO ANO": "Acumulado do ano", "TODO O HISTÓRICO": "Todo o histórico"}
    selected_warehouses = st.session_state.get("fm_mov_warehouses") or []
    label = f"PERÍODO E ARMAZÉM · {month[5:]}/{month[:4]} · {modes[mode]}"
    if selected_warehouses:
        label += " · " + ", ".join(selected_warehouses)
    with st.expander(label):
        first, second, third = st.columns([1.05, 1.5, 1])
        with first:
            month = st.selectbox("Competência analisada", months, format_func=lambda m:m[5:]+"/"+m[:4], key="fm_mov_month")
        with second:
            mode = st.selectbox("Período da análise", list(modes), key="fm_mov_period")
        with third:
            warehouses = sorted(frame["armazem"].unique())
            if len(warehouses) > 1:
                chosen = _multiselect("Armazéns", warehouses, "fm_mov_warehouses")
            else:
                chosen = warehouses
                st.markdown("**ARMAZÉM**")
                st.write(warehouses[0] if warehouses else "—")
    selected_date = date.fromisoformat(month+"-01")
    if mode == "MÊS SELECIONADO":
        view = frame.loc[frame["competencia"] == month]
    elif mode == "ACUMULADO DO ANO":
        view = frame.loc[frame["competencia"].between(month[:4]+"-01", month)]
    else:
        view = frame
    if str(st.query_params.get("mes") or "") != month:
        st.query_params["mes"] = month
    if chosen:
        view = view.loc[view["armazem"].isin(chosen)]
    coverage_end = max((str((i.get("meta") or {}).get("periodo_fim") or "") for i in imports), default="")
    if coverage_end and coverage_end[:7] == month:
        if selected_date.month == 12:
            next_month = date(selected_date.year+1, 1, 1)
        else:
            next_month = date(selected_date.year, selected_date.month+1, 1)
        from datetime import timedelta
        if coverage_end < (next_month - timedelta(days=1)).isoformat():
            st.caption(f"PERÍODO PARCIAL · histórico disponível até {date.fromisoformat(coverage_end).strftime('%d/%m/%Y')}.")
    if not view.empty:
        start, end = date.fromisoformat(view["data"].min()), date.fromisoformat(view["data"].max())
        st.caption(f"BASE DA ANÁLISE · {start:%d/%m/%Y} a {end:%d/%m/%Y} · armazém: {', '.join(sorted(view['armazem'].unique()))}.")
    return view.copy()


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
    st.markdown("**COMPOSIÇÃO POR GRUPO**")
    st.caption("Selecione um grupo para avançar às TES e condições que compõem seus valores.")
    _groups_table(frame, token + "_overview")
    with st.expander("EVOLUÇÃO MENSAL DO PERÍODO"):
        monthly = mv.summarize(current, ["competencia"]).sort_values("competencia")
        _table(monthly[["competencia", "lancamentos", "valor_entrada", "valor_saida", "liquido_valor"]])


def _groups(frame, token):
    active = mv.effective(frame)
    if frame["grupo_analise"].nunique() != 1:
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
    st.caption(f"{count(len(frame))} registros encontrados. A exportação inclui todo o recorte, independentemente da página.")
    if st.session_state.get("fm_mov_page_token") != token:
        st.session_state.fm_mov_page = 1
        st.session_state.fm_mov_page_token = token
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
    specs = [
        (mv.CLOSING_RULE, "020 / 520 · chapa ou barra de cobre", mv.FLOW, mv.CLOSING),
        ("520_OP_MANUAL", "520 · AE com OP", mv.FLOW, "BAIXA DE OP MANUAL"),
        ("520_CC_GERENCIAL", "520 · CC diferente de 600307", mv.FLOW, "ACERTO GERENCIAL"),
        ("520_CC_CONSUMO", "520 · CC 600307 e II, MC ou código da lista H0001", mv.FLOW, "MATERIAIS DE CONSUMO"),
        ("AJUSTE_PA_PI_PRODUCAO_INTERNA", "020 · PA / PI que permanecia em Ajuste", mv.PRODUCTION, mv.PRODUCTION),
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


def _exports(frame, model, token, *, include_history=True):
    title = "EXPORTAR RELATÓRIOS" if include_history else "EXPORTAR REGISTROS DESTA CONSULTA"
    with st.expander(title, expanded=include_history):
        columns = st.columns(2) if include_history else [st.container()]
        with columns[0]:
            st.markdown("**EXCEL DO PERÍODO**" if include_history else "**EXCEL DOS REGISTROS FILTRADOS**")
            st.caption(f"{count(len(frame))} registros · inclui os detalhamentos e a AE original.")
            if st.button("PREPARAR EXCEL DO RECORTE", key="fm_mov_prepare_excel"):
                with st.spinner("Preparando o Excel com os registros do recorte..."):
                    st.session_state.fm_mov_excel = (token, mv.export_excel(frame))
            prepared = st.session_state.get("fm_mov_excel")
            if prepared and prepared[0] == token:
                st.download_button("BAIXAR EXCEL DO RECORTE", prepared[1], file_name="Analise_Movimentacoes.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="fm_mov_download_excel")
        if include_history:
            with columns[1]:
                st.markdown("**BASE HISTÓRICA COMPLETA**")
                st.caption("Todos os arquivos e períodos importados, para backup ou reimportação.")
                if st.button("PREPARAR BASE HISTÓRICA COMPLETA", key="fm_mov_prepare_history"):
                    with st.spinner("Preparando a base histórica completa..."):
                        st.session_state.fm_mov_history = (model["token"], mv.export_history(model))
                prepared = st.session_state.get("fm_mov_history")
                if prepared and prepared[0] == model["token"]:
                    st.download_button("BAIXAR BASE HISTÓRICA", prepared[1], file_name="Base_Historica_KARDEX.zip",
                                       mime="application/zip", key="fm_mov_download_history")
            st.caption("O Excel usa o período e o armazém da base da análise. Para um recorte por produto, OP ou TES, exporte pela área Registros.")


def render_results(model, imports):
    scope = _context(model["frame"], imports)
    st.markdown('''<style>
    .st-key-fm_mov_area{margin:.1rem 0 .6rem}
    .st-key-fm_mov_area button{min-height:44px!important;border-radius:10px!important;font-weight:700!important}
    .st-key-fm_mov_area button[aria-pressed="true"]{background:#111827!important;color:#fff!important;border-color:#111827!important}
    .st-key-fm_mov_area button[aria-pressed="true"] p{color:#fff!important}
    </style>''', unsafe_allow_html=True)
    if st.session_state.get("fm_mov_area") not in AREAS:
        st.session_state.fm_mov_area = AREAS[0]
    area = st.segmented_control("Funções da análise", AREAS, key="fm_mov_area", selection_mode="single",
                                format_func=lambda value: AREA_LABELS.get(value, value),
                                label_visibility="collapsed", width="stretch") or AREAS[0]
    headers = {
        "Visão geral": ("01 · RESUMO", "RESULTADO DO PERÍODO", "Acompanhe entradas, saídas e a composição por grupo. Selecione um grupo para aprofundar a análise."),
        "Grupos e TES": ("02 · GRUPOS E TES", "ANÁLISE POR GRUPO E CONDIÇÃO", "Abra um grupo e selecione uma TES ou condição para consultar os registros que compõem o valor."),
        "Por OP": ("03 · ORDENS DE PRODUÇÃO", "CONSULTA POR OP", "Localize a OP e selecione sua linha para abrir os materiais, documentos e movimentações vinculados."),
        "Movimentações": ("04 · REGISTROS", "CONSULTA DOS MOVIMENTOS", "Busque um registro e selecione sua linha para conferir a AE original e o motivo da classificação."),
        "Classificação": ("05 · CLASSIFICAÇÃO", "REGRAS E AJUSTES A REFINAR", "Consulte os critérios aplicados e avance aos ajustes que ainda precisam de refinamento."),
        "Fontes e relatórios": ("06 · FONTES E RELATÓRIOS", "HISTÓRICO, IMPORTAÇÃO E EXPORTAÇÃO", "Consulte os arquivos utilizados, importe novos relatórios e gere o Excel ou a base histórica."),
    }
    band(*headers[area])
    if area == "Fontes e relatórios":
        _import_controls(imports)
        _exports(scope, model, _view_token(scope))
        if model["duplicates"]:
            st.caption(f"Importações sobrepostas: {count(model['duplicates'])} repetições reconhecidas, sem soma em duplicidade.")
        return
    view = _consultation_filters(scope, area) if area in FILTER_AREAS else scope
    if area == "Movimentações" and st.session_state.get("fm_mov_record_origin"):
        origin = st.session_state.fm_mov_record_origin
        st.button("← VOLTAR PARA " + AREA_LABELS.get(origin, origin).upper(),
                  on_click=_go_to, args=(origin,), key="fm_mov_back")
    if view.empty:
        st.info("Nenhuma movimentação corresponde a esta consulta. Ajuste os filtros ou o período da análise.")
        return
    token = _view_token(view, area)
    if area == "Visão geral":
        _overview(view, token)
    elif area == "Grupos e TES":
        _groups(view, token)
    elif area == "Por OP":
        _ops(view, token)
    elif area == "Movimentações":
        _ledger(view, token)
        _exports(view, model, token, include_history=False)
    else:
        _classification(view, model)
    confirmed = int(view["enderecamento_compensado"].sum())
    if confirmed:
        st.caption(f"{count(confirmed)} registros de endereço compensados permanecem na consulta e estão fora dos valores efetivos.")


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
    if not imports:
        _import_controls(imports)
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
    render_results(model, imports)
