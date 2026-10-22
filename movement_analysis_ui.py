"""Movement analysis using the Dashboard's shared SETTA layout."""
from __future__ import annotations

import hashlib
import html
import math
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import movement_store as store
import movements as mv
import kardex_history as history

AREAS = ["Visão geral", "TES e descrições", "Por OP", "Movimentações", "Cadastro TES", "Fontes e relatórios"]
AREA_LABELS = {"Visão geral": "Resumo", "Por OP": "Consulta por OP", "Movimentações": "Registros", "TES e descrições": "TES"}
FILTER_AREAS = {"TES e descrições": "tes", "Por OP": "ops", "Movimentações": "ledger"}
FILTER_FIELDS = {"tes": "TES", "search": "Busca", "op": "OP", "cc": "CC / CR", "categories": "Tipo"}
MONEY_COLUMNS = {"valor_entrada": "Entrada (R$)", "valor_saida": "Saída (R$)", "liquido_valor": "Variação (R$)"}
NAMES = {"tes": "TES", "descricao_tes": "Descrição TES", "tipo_tm": "Tipo de TM",
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


@st.cache_data(show_spinner=False, ttl=60)
def _imports():
    return store.list_imports()


@st.cache_resource(show_spinner=False, ttl=600, max_entries=2)
def _model(tokens: tuple, version: str):
    del version
    entries = [{"chave": key, "atualizado_em": updated, "meta": meta} for key, updated, meta in tokens]
    return mv.build_model(store.load_history(entries))


def _reload():
    _imports.clear()
    _model.clear()
    issue_ui = sys.modules.get("issue_check_ui")
    if issue_ui:
        for name in ("_imports", "_history", "_audit"):
            getattr(issue_ui, name).clear()


def _selected(key):
    state = st.session_state.get(key) or {}
    selected = state.get("selection") or {}
    rows = selected.get("rows") or []
    return int(rows[0]) if rows else None


def _tes_selected(key, values):
    position = _selected(key)
    if position is None or position >= len(values):
        return
    _open_records({"tes": [values[position]]}, "TES e descrições")

def _op_selected(key, values):
    position = _selected(key)
    if position is None or position >= len(values):
        return
    _open_records({"op": values[position]}, "Por OP")


def _defaults():
    return {"tes": [], "categories": [], "search": "", "op": "", "cc": ""}


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


def _area_changed(key):
    selected = st.session_state.get(key)
    if selected in AREAS:
        st.session_state.fm_mov_area = selected
    # The navigation reflects its destination, including changes made by table selections.
    st.session_state.pop(key, None)


def _clear_filters(area):
    _set_filters(area, {})
    if area == "Movimentações":
        st.session_state.pop("fm_mov_record_origin", None)


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
    for field, column in (("tes", "tes"), ("categories", "tipo")):
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
    if area == "TES e descrições":
        a, b = st.columns([1.25, 2])
        with a:
            _local_input(area, "tes", "Códigos TES", options=sorted(frame["tes"].unique()))
        with b:
            _local_input(area, "search", "Localizar movimentação",
                         placeholder="Produto, documento, descrição ou OP")
    elif area == "Por OP":
        _local_input(area, "search", "Buscar OP ou material", placeholder="Número da OP, código ou descrição do produto")
    else:
        _local_input(area, "search", "Buscar nos registros", placeholder="Produto, documento ou vínculo AE")
        active = sum(bool(v) for k, v in _values(area).items() if k != "search")
        title = "REFINAR CONSULTA" + (f" · {active} filtro(s) ativo(s)" if active else "")
        with st.expander(title):
            a, b, c = st.columns(3)
            with a:
                _local_input(area, "tes", "Códigos TES", options=sorted(frame["tes"].unique()))
            with b:
                _local_input(area, "categories", "Tipo do material", options=sorted(frame["tipo"].unique()))
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


@st.cache_data(show_spinner=False, max_entries=6)
def _parse_import(raw: bytes, name: str):
    return mv.parse_report(raw, name)


def _import_controls(imports, model=None):
    st.markdown("**01 · IMPORTAR OU ATUALIZAR KARDEX**")
    st.caption("Importe arquivos XLSX/XLTX ou uma base histórica ZIP consolidada. Cada atualização afeta somente os meses e armazéns informados no próprio arquivo: o histórico S2 e outros armazéns ficam preservados quando não fizerem parte da importação.")
    st.info("Para acrescentar EP, 20 e E2 de janeiro a outubro, envie a base histórica consolidada ZIP. O sistema identificará os três armazéns e suas competências automaticamente. Verifique a prévia e confirme a importação uma única vez.")
    epoch = st.session_state.get("fm_mov_upload_epoch", 0)
    files = st.file_uploader("Relatórios KARDEX", type=["xlsx", "xltx", "zip"], accept_multiple_files=True,
                             key=f"fm_mov_uploads_{epoch}")
    if files:
        try:
            parsed, preview, seen = [], [], set()
            for file in files:
                item = _parse_import(file.getvalue(), file.name)
                meta = item["meta"]
                if meta["sha256"] in seen:
                    raise ValueError("O mesmo arquivo foi selecionado mais de uma vez. Mantenha apenas uma cópia.")
                seen.add(meta["sha256"])
                start = date.fromisoformat(meta["periodo_inicio"])
                if not meta.get("periodo_informado") and not meta.get("coberturas_arquivo"):
                    start = start.replace(day=1)
                end = date.fromisoformat(meta["periodo_fim"])
                with st.expander("CONFERIR PERÍODO · " + file.name):
                    st.caption("Confirme o período extraído no sistema. Os armazéns são identificados nos próprios registros.")
                    if meta.get("coberturas_arquivo"):
                        st.caption("Base consolidada com competências declaradas no manifesto. Meses sem lançamentos são preservados como cobertura com 0 registros. O período de cada armazém não será inferido a partir da data do último movimento.")
                    else:
                        a, b = st.columns(2)
                        with a:
                            start = st.date_input("Início do relatório completo", value=start, format="DD/MM/YYYY", key="fm_mov_from_" + meta["sha256"])
                        with b:
                            end = st.date_input("Dados até", value=end, format="DD/MM/YYYY", key="fm_mov_until_" + meta["sha256"])
                item = history.prepare_import(item, start.isoformat(), end.isoformat())
                parsed.append(item)
                scopes = {(s["competencia"], s["armazem"]) for s in item["meta"]["escopos"]}
                replaced = 0
                if model is not None and not model["frame"].empty:
                    replaced = sum((r.data[:7], r.armazem) in scopes for r in model["frame"].itertuples())
                preview.append({"Arquivo": file.name, "Armazéns": ", ".join(item["meta"]["armazens"]),
                                "Competências abrangidas": ", ".join(m[5:] + "/" + m[:4] for m in item["meta"]["competencias"]),
                                "Dados até": end.strftime("%d/%m/%Y"), "Novos registros": len(item["rows"]),
                                "Registros atuais no recorte": replaced})
            history.validate_batch(parsed)
            active_warehouses = sorted({warehouse for item in parsed for warehouse in item["meta"]["armazens"]})
            st.caption("Armazéns identificados nos novos arquivos: " + ", ".join(active_warehouses))
            if "S2" not in active_warehouses:
                st.caption("Preservação confirmada: o armazém S2 não faz parte desta substituição.")
        except Exception as exc:
            st.error(f"Confira os arquivos antes de importar: {exc}")
            return
        st.markdown("**PRÉVIA DA SUBSTITUIÇÃO**")
        st.dataframe(pd.DataFrame(preview), hide_index=True, width="stretch")
        st.info("Cada mês e armazém da prévia passará a usar exclusivamente o novo KARDEX, inclusive quando um lançamento antigo não constar mais no arquivo. As versões anteriores ficam registradas no histórico.")
        if st.button("IMPORTAR E SUBSTITUIR PERÍODOS", type="primary", key="fm_mov_commit_import"):
            try:
                with st.spinner("Gravando e conferindo os arquivos KARDEX..."):
                    known = store.list_imports()
                    saved = unchanged = 0
                    for item in parsed:
                        result = store.save_import(item, known)
                        saved += result["saved"]; unchanged += not result["saved"]
                        known = [k for k in known if k["chave"] != result["key"]]
                        known.append({"chave": result["key"], "meta": result["meta"]})
                _reload()
                st.session_state.fm_mov_upload_epoch = epoch + 1
                st.session_state.fm_mov_flash = f"{saved} arquivo(s) gravado(s) e ativado(s); {unchanged} já eram a versão vigente."
                st.rerun()
            except Exception as exc:
                _reload()
                st.error(f"Não foi possível concluir a importação: {exc}. Os arquivos que concluíram a gravação permanecem registrados. Reenvie a seleção para concluir os demais sem duplicação.")


def _warehouse_registry_overview(model) -> pd.DataFrame:
    """Resumo de armazéns ativos e pendentes, sem confundir cobertura com movimento."""
    frame = model.get("frame", pd.DataFrame())
    coverage = model.get("coverage_metas") or []
    current = {str(item["armazem"]) for item in coverage}
    if not frame.empty:
        current.update(str(value) for value in frame["armazem"].unique() if value)
    expected = {"S2", "EP", "20", "E2"}
    order = {"S2": 0, "EP": 1, "20": 2, "E2": 3}
    result = []
    for warehouse in sorted(current | expected, key=lambda w: (order.get(w, 100), w)):
        months = {item["competencia"] for item in coverage if str(item["armazem"]) == warehouse}
        periods = [item for item in coverage if str(item["armazem"]) == warehouse]
        relevant = frame.loc[frame["armazem"] == warehouse] if not frame.empty else frame
        total = len(relevant)
        latest = relevant["data"].max() if total else None
        result.append({
            "Armazém": warehouse,
            "Situação": "ATIVO" if months else "PENDENTE DE IMPORTAÇÃO",
            "Competências registradas": len(months),
            "Cobertura até": date.fromisoformat(max(p["periodo_fim"] for p in periods)).strftime("%d/%m/%Y") if periods else "NI",
            "Última movimentação": date.fromisoformat(str(latest)).strftime("%d/%m/%Y") if latest is not None else "SEM MOVIMENTAÇÕES",
            "Registros vigentes": total,
        })
    return pd.DataFrame(result)


def _import_registry(model):
    st.markdown("**02 · SITUAÇÃO DOS ARMAZÉNS**")
    st.caption("A cobertura representa o período declarado no relatório; a última movimentação pode ser anterior sem indicar erro. Armazéns pendentes não são contados como saldo ou baixa zero.")
    st.dataframe(_warehouse_registry_overview(model), hide_index=True, width="stretch")
    st.markdown("**03 · BASES VIGENTES POR MÊS E ARMAZÉM**")
    grouped = {}
    for meta in model.get("coverage_metas", []):
        grouped.setdefault((meta["competencia"], meta["armazem"]), []).append(meta)
    rows = []
    for (month, warehouse), sources in sorted(grouped.items(), key=lambda pair: (-int(pair[0][0].replace("-", "")), pair[0][1])):
        frame = model["frame"]
        amount = int(((frame["competencia"] == month) & (frame["armazem"] == warehouse)).sum()) if not frame.empty else 0
        periods = sorted({m["periodo_inicio"][8:] + "/" + m["periodo_inicio"][5:7] + " a " +
                          m["periodo_fim"][8:] + "/" + m["periodo_fim"][5:7] for m in sources})
        rows.append({"Competência": month[5:] + "/" + month[:4], "Armazém": warehouse,
                     "Registros vigentes": amount, "Cobertura declarada": " · ".join(periods),
                     "Arquivos em uso": " · ".join(dict.fromkeys(m["arquivo_nome"] for m in sources))})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    with st.expander("04 · HISTÓRICO DE IMPORTAÇÕES E VERSÕES SUBSTITUÍDAS"):
        recorded = []
        for item in reversed(model.get("import_registry", [])):
            updated = item["importado_em"]
            if updated:
                updated = datetime.fromisoformat(updated.replace("Z", "+00:00")).astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
            recorded.append({"Arquivo": item["arquivo"], "Situação": item["status"], "Armazéns": ", ".join(item["armazens"]),
                             "Competências": ", ".join(m[5:] + "/" + m[:4] for m in item["competencias"]),
                             "Registros no arquivo": item["lancamentos"], "Registros em uso": item["lancamentos_ativos"], "Importado em": updated})
        st.dataframe(pd.DataFrame(recorded), hide_index=True, width="stretch")
        st.caption("VIGENTE: arquivo em uso. PARCIALMENTE SUBSTITUÍDO: continua em uso em outros meses ou armazéns. SUBSTITUÍDO: registros fora da análise atual. Reimportar uma versão anterior a torna vigente novamente nos meses e armazéns da prévia.")


def _context(frame, imports, coverage=None):
    months = sorted(set(frame["competencia"].unique()) | {m["competencia"] for m in coverage or []})
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
            warehouses = sorted(set(frame["armazem"].unique()) | {m["armazem"] for m in coverage or []})
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
    if coverage is not None:
        covered = [m for m in coverage if mode == "TODO O HISTÓRICO" or
                   (m["competencia"] == month if mode == "MÊS SELECIONADO" else month[:4] + "-01" <= m["competencia"] <= month)]
        selected = chosen or warehouses
        ends = {warehouse: max((m["periodo_fim"] for m in covered if m["armazem"] == warehouse), default="") for warehouse in selected}
        coverage_end = min(ends.values(), default="")
        if len(ends) > 1 or any(not end for end in ends.values()):
            st.caption("COBERTURA KARDEX · " + " · ".join(warehouse + ": " +
                       ("até " + date.fromisoformat(end).strftime("%d/%m/%Y") if end else "sem arquivo no período") for warehouse, end in ends.items()))
    if coverage_end and coverage_end[:7] == month:
        if selected_date.month == 12:
            next_month = date(selected_date.year+1, 1, 1)
        else:
            next_month = date(selected_date.year, selected_date.month+1, 1)
        from datetime import timedelta
        if coverage_end < (next_month - timedelta(days=1)).isoformat():
            st.caption(f"PERÍODO PARCIAL · histórico disponível até {date.fromisoformat(coverage_end).strftime('%d/%m/%Y')}.")
    # O período e os armazéns continuam aplicados ao recorte, mas o texto
    # redundante de "BASE DA ANÁLISE" não é exibido no topo do KARDEX.
    return view.copy()


def _tes_summary(frame) -> pd.DataFrame:
    """Uma linha por TES e descrição, sem agrupamentos subjetivos."""
    result = mv.summarize(frame, ["tes", "descricao_tes"])
    confirmed = mv.rules()["tes"]
    result["tipo_tm"] = result["tes"].map(
        lambda code: confirmed.get(code, {}).get("tipo_tm") or "NI"
    )
    return result.sort_values(["tes", "descricao_tes"], kind="stable").reset_index(drop=True)


def _tes_table(frame, token):
    summary = _tes_summary(frame)
    if summary.empty:
        st.info("Nenhuma TES com movimentações neste recorte.")
        return
    key = "fm_mov_tes_table_" + token
    codes = summary["tes"].tolist()
    _table(
        summary[["tes", "tipo_tm", "descricao_tes", "lancamentos", "produtos",
                 "valor_entrada", "valor_saida", "liquido_valor"]],
        key=key, on_select=lambda: _tes_selected(key, codes),
        height=700,
    )
    st.caption("Selecione uma TES para consultar os registros originais que compõem os valores.")


def _overview(frame, token):
    cards([
        ("ENTRADAS DO KARDEX", cash(frame["valor_entrada"].sum())),
        ("SAÍDAS DO KARDEX", cash(frame["valor_saida"].sum())),
        ("VARIAÇÃO DO PERÍODO", cash(frame["liquido_valor"].sum())),
    ])
    unknown = int((frame["descricao_tes"] == "NI - TES não localizada no cadastro").sum())
    st.caption(
        f"{count(len(frame))} registros · {count(frame.codigo.nunique())} produtos · "
        f"{count(frame.tes.nunique())} TES distintas · "
        f"{count(frame.loc[frame.op_identificada != '', 'op_identificada'].nunique())} OPs. "
        "Totais sem exclusão ou reclassificação gerencial."
    )
    if unknown:
        st.warning(f"{count(unknown)} movimentações possuem TES sem descrição no cadastro de referência.")
    st.markdown("**MOVIMENTAÇÕES AGRUPADAS POR TES**")
    st.caption("Os registros são agrupados por código TES e descrição. O tipo TM é apenas informativo.")
    _tes_table(frame, token + "_overview")
    with st.expander("EVOLUÇÃO MENSAL DO PERÍODO"):
        monthly = mv.summarize(frame, ["competencia"]).sort_values("competencia")
        _table(monthly[["competencia", "lancamentos", "valor_entrada", "valor_saida", "liquido_valor"]])


def _tes(frame, token):
    st.caption("TES e descrição do cadastro de referência; os sete tipos TM informados são apenas metadados, sem regras por produto, OP ou CC.")
    _tes_table(frame, token)


def _ops(frame, token):
    summary = mv.summarize_ops(frame)
    linked = frame.loc[frame["op_identificada"] != ""]
    cards([("OPS IDENTIFICADAS", count(len(summary))), ("MOVIMENTOS COM OP", count(len(linked))),
           ("SAÍDAS KARDEX COM OP", cash(linked["valor_saida"].sum()))])
    if summary.empty:
        st.info("Nenhuma movimentação com OP no recorte selecionado.")
        return
    key = "fm_mov_op_table_" + token
    values = summary["op_identificada"].tolist()
    _table(summary[[
        "op_identificada", "lancamentos", "produtos", "documentos",
        "primeira_data", "ultima_data", "valor_entrada", "valor_saida",
    ]], key=key, on_select=lambda:_op_selected(key, values))


def _detail(row):
    band("REGISTRO ORIGINAL", row["codigo"] + " · " + row["descricao"],
         "Rastreabilidade das informações existentes no KARDEX, sem classificação gerencial.")
    a, b, c = st.columns(3)
    with a:
        st.write("**DATA:** " + date.fromisoformat(row["data"]).strftime("%d/%m/%Y"))
        st.write("**TES:** " + row["tes"])
        st.write("**DESCRIÇÃO TES:** " + row["descricao_tes"])
        st.write("**TIPO DE TM:** " + row.get("tipo_tm", "NI"))
        st.write("**DOCUMENTO:** " + row["documento"])
    with b:
        st.write("**ARMAZÉM:** " + row["armazem"])
        st.write("**TIPO DO MATERIAL:** " + row["tipo"])
        st.write("**CC / CR:** " + (row["cc_identificado"] or "—"))
    with c:
        st.write("**AE ORIGINAL:**")
        st.code(row["ae_original"], language=None)
        st.write("**OP:** " + (row["op_identificada"] or "—"))
    st.write(f"**ENTRADA:** {quantity(row['qtd_entrada'])} {row['um']} · {cash(row['valor_entrada'])}")
    st.write(f"**SAÍDA:** {quantity(row['qtd_saida'])} {row['um']} · {cash(row['valor_saida'])}")
    st.caption(f"Arquivo: {row['arquivo_origem']} · linha {int(row['linha_origem'])}.")


def _ledger(frame, token):
    st.caption(f"{count(len(frame))} registros encontrados. A exportação inclui todo o recorte, independentemente da página.")
    st.caption("Sem abatimentos, agrupamentos gerenciais ou compensações automáticas. Todos os lançamentos da fonte permanecem incluídos.")
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
                          "Saída (R$)": visible["valor_saida"], "AE original": visible["ae_original"],
                          "Descrição TES": visible["descricao_tes"], "Tipo de TM": visible["tipo_tm"],
                          "Tipo do material": visible["tipo"],
                          "Documento": visible["documento"]})
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


def _catalog(frame):
    """Cadastro de referência independente do recorte; nenhuma regra gerencial."""
    catalog = mv.rules()["tes"]
    counts = frame.groupby("tes", sort=False).size().to_dict()
    rows = [
        {
            "TES": code,
            "Tipo de TM": fields.get("tipo_tm") or "NI",
            "Descrição TES": fields["descricao"],
            "Movimentos no recorte": int(counts.get(code, 0)),
        }
        for code, fields in catalog.items()
    ]
    unknown = sorted(set(counts) - set(catalog))
    rows.extend({
        "TES": code,
        "Tipo de TM": "NI",
        "Descrição TES": "NI - TES não localizada no cadastro",
        "Movimentos no recorte": int(counts[code]),
    } for code in unknown)
    st.caption(
        f"{count(len(catalog))} TES no cadastro de referência · "
        f"{count(len(mv.tes_confirmed()))} códigos com tipo TM informado · "
        f"{count(len(unknown))} códigos movimentados sem correspondência. "
        "Tipo de TM é um atributo cadastral, não um grupo gerencial."
    )
    st.dataframe(
        pd.DataFrame(rows).sort_values("TES", kind="stable"),
        hide_index=True, width="stretch", height=600,
        column_config={
            "TES": st.column_config.TextColumn(width="small"),
            "Descrição TES": st.column_config.TextColumn(width="large"),
        },
    )
    st.caption(
        "Esta etapa usa apenas o cadastro TES. Não há regras por material, "
        "CC, OP, centro de custo ou classificação gerencial."
    )


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
                st.caption("Base consolidada vigente, com os períodos e armazéns em uso, para backup ou reimportação.")
                if st.button("PREPARAR BASE HISTÓRICA COMPLETA", key="fm_mov_prepare_history"):
                    with st.spinner("Preparando a base histórica completa..."):
                        st.session_state.fm_mov_history = (model["token"], mv.export_history(model))
                prepared = st.session_state.get("fm_mov_history")
                if prepared and prepared[0] == model["token"]:
                    st.download_button("BAIXAR BASE HISTÓRICA", prepared[1], file_name="Base_Historica_KARDEX.zip",
                                       mime="application/zip", key="fm_mov_download_history")
            st.caption("O Excel usa o período e o armazém da base da análise. Para um recorte por produto, OP ou TES, exporte pela área Registros.")


def render_results(model, imports):
    scope = _context(model["frame"], imports, model.get("coverage_metas"))
    st.markdown('''<style>
    .st-key-fm_mov_navigation{margin:.1rem 0 .6rem}
    .st-key-fm_mov_navigation button{min-height:44px!important;border-radius:10px!important;font-weight:700!important}
    .st-key-fm_mov_navigation button[aria-checked="true"]{background:#111827!important;color:#fff!important;border-color:#111827!important}
    .st-key-fm_mov_navigation button[aria-checked="true"] p{color:#fff!important}
    </style>''', unsafe_allow_html=True)
    area = st.session_state.get("fm_mov_area")
    # Usuários que ainda têm a navegação antiga em sessão chegam à aba equivalente.
    area = {"Grupos e TES": "TES e descrições", "Classificação": "Cadastro TES"}.get(area, area)
    if area not in AREAS:
        area = AREAS[0]
    st.session_state.fm_mov_area = area
    navigation_key = "fm_mov_nav_area_" + str(AREAS.index(area))
    with st.container(key="fm_mov_navigation"):
        st.segmented_control("Funções da análise", AREAS, key=navigation_key, selection_mode="single",
                             default=area, on_change=_area_changed, args=(navigation_key,),
                             format_func=lambda value: AREA_LABELS.get(value, value),
                             label_visibility="collapsed", width="stretch")
    headers = {
        "Visão geral": ("01 · VISÃO GERAL", "RESULTADO DO KARDEX", "Entradas, saídas e variação por TES, com os valores originais do histórico."),
        "TES e descrições": ("02 · TES", "MOVIMENTAÇÕES POR TES", "Uma linha por código e descrição do cadastro Protheus. Selecione para consultar os lançamentos."),
        "Por OP": ("03 · ORDENS DE PRODUÇÃO", "CONSULTA POR OP", "Localize OPs por sua identificação original e consulte os documentos vinculados."),
        "Movimentações": ("04 · REGISTROS", "MOVIMENTAÇÕES ORIGINAIS", "Consulte as informações do KARDEX sem classificação gerencial ou exclusões automáticas."),
        "Cadastro TES": ("05 · CADASTRO", "CATÁLOGO DE TES", "TES, descrições e tipos de movimentação confirmados, sem grupos gerenciais."),
        "Fontes e relatórios": ("06 · FONTES E RELATÓRIOS", "HISTÓRICO, IMPORTAÇÃO E EXPORTAÇÃO", "Registros originais, histórico de importações e relatórios por TES."),
    }
    band(*headers[area])
    if area == "Fontes e relatórios":
        _import_controls(imports, model)
        _import_registry(model)
        _exports(scope, model, _view_token(scope))
        if model["duplicates"]:
            st.caption(f"Importações sobrepostas: {count(model['duplicates'])} repetições reconhecidas, sem soma em duplicidade.")
        return
    view = _consultation_filters(scope, area) if area in FILTER_AREAS else scope
    if area == "Movimentações" and st.session_state.get("fm_mov_record_origin"):
        origin = st.session_state.fm_mov_record_origin
        st.button("← VOLTAR PARA " + AREA_LABELS.get(origin, origin).upper(),
                  on_click=_go_to, args=(origin,), key="fm_mov_back")
    if view.empty and area != "Cadastro TES":
        st.info("Nenhuma movimentação corresponde a esta consulta. Ajuste os filtros ou o período da análise.")
        return
    token = _view_token(view, area)
    if area == "Visão geral":
        _overview(view, token)
    elif area == "TES e descrições":
        _tes(view, token)
    elif area == "Por OP":
        _ops(view, token)
    elif area == "Movimentações":
        _ledger(view, token)
        _exports(view, model, token, include_history=False)
    elif area == "Cadastro TES":
        _catalog(view)


def render_movement_analysis():
    band("KARDEX", "MOVIMENTAÇÕES POR TES", "Histórico de entradas e saídas · descrição do cadastro Protheus · vínculos por OP · sem classificação gerencial.")
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
            tokens = tuple((i["chave"], i.get("atualizado_em", ""), i.get("meta") or {}) for i in imports)
            model = _model(tokens, mv.rules()["versao"] + history.VERSION)
    except Exception as exc:
        st.error(f"Não foi possível conferir os registros do histórico: {exc}")
        st.button("RECARREGAR HISTÓRICO", key="fm_mov_model_retry", on_click=_reload)
        return
    frame = model["frame"]
    if frame.empty:
        st.info("O histórico não possui movimentações.")
        _import_controls(imports, model)
        _import_registry(model)
        return
    render_results(model, imports)
