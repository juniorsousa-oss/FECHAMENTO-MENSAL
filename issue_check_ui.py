"""OP issue checks in the existing Dashboard layout."""
from __future__ import annotations

import hashlib
import html
import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import central_fechamento_data as central
import issue_check as check
import movement_store
import movements as mv

SOURCE_KEYS = ("relatorio_geral", "endereco")
TZ = ZoneInfo("America/Sao_Paulo")
FILTERS = {"Todas": None, "Com divergências": "divergente",
           "Sem saldo e sem baixa suficiente": check.MISSING,
           "G9-PROD pendente de baixa": check.PROD_PENDING,
           "Saldo compartilhado insuficiente": check.SHARED,
           "OPs com baixas": "op_possui_baixa",
           "OPs sem baixas no histórico": "op_sem_baixa",
           "Baixa identificada": "BAIXA IDENTIFICADA",
           "Aguardando conferência ou separação": "aguardando",
           "Histórico incompleto": "historico_incompleto"}
LABELS = {"op": "OP", "codigo": "Produto", "descricao": "Descrição", "lotes": "Lotes",
          "necessaria": "Necessária", "atendida": "Atendida", "conferida": "Conferida",
          "baixada": "Baixada líquida (OP/produto)", "saida_bruta": "Saídas", "devolvida": "Entradas / devoluções",
          "pendente": "Pendente de baixa", "saldo": "Saldo nos lotes conferidos",
          "saldo_g9_prod": "Saldo G9-PROD", "sem_saldo": "Sem cobertura de saldo ou baixa",
          "em_g9_prod": "Pendente com saldo G9-PROD", "status": "Resultado",
          "historico_incompleto": "Histórico incompleto", "saldo_compartilhado": "Saldo compartilhado",
          "conflito_saldo": "Demanda compartilhada maior que saldo", "itens": "Registros",
          "itens_separados": "Separados", "itens_conferidos": "Conferidos",
          "lote": "Lote", "armazem": "Armazém", "endereco": "Endereço", "empenho": "Empenho",
          "pendente_minima": "Pendente mínima no lote", "pendente_maxima": "Pendente máxima no lote",
          "ops_com_demanda": "OPs com demanda no lote", "demanda_compartilhada_minima": "Demanda mínima de todas as OPs",
          "demanda_compartilhada_maxima": "Demanda máxima de todas as OPs", "linha_origem": "Linha de origem",
          "separacao": "Data de separação", "conferencia": "Data de conferência",
          "responsavel_separacao": "Responsável pela separação", "responsavel_conferencia": "Responsável pela conferência",
          "referencia": "Referência", "fornecedor": "Fornecedor", "pa": "P.A.", "descricao_pa": "Descrição P.A.",
          "reportado": "Reportado", "reporte": "Data de reporte", "pendencia_mes": "Pendente no MES",
          "data": "Data", "tes": "TES", "documento": "Documento", "qtd_entrada": "Entrada", "qtd_saida": "Saída",
          "ae_original": "AE original", "natureza": "Natureza", "arquivo_origem": "Arquivo de origem"}
QUANTITIES = {"necessaria", "atendida", "conferida", "baixada", "saida_bruta", "devolvida", "pendente", "saldo",
              "saldo_g9_prod", "sem_saldo", "em_g9_prod", "empenho", "pendente_minima", "pendente_maxima",
              "demanda_compartilhada_minima", "demanda_compartilhada_maxima", "pendencia_mes", "qtd_entrada", "qtd_saida"}


def quantity(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    number = f"{float(value):,.6f}".rstrip("0").rstrip(".")
    return number.replace(",", "X").replace(".", ",").replace("X", ".")


def count(value) -> str:
    return f"{int(value):,}".replace(",", ".")


def day(value) -> str:
    try:
        return datetime.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(value or "—")


def _band():
    st.markdown('<div class="section-band"><div class="section-band-kicker">CONFERÊNCIAS</div>'
                '<div class="section-band-title">CONFERÊNCIA DE BAIXAS</div>'
                '<div class="section-band-note">Materiais por OP · conferência do MES · saldo por lote e endereço · baixas do KARDEX.</div></div>',
                unsafe_allow_html=True)


def _cards(items):
    parts = ['<div class="cb-kpi-grid">']
    for label, value, note in items:
        parts.append('<div class="cb-kpi"><div class="cb-kpi-label">' + html.escape(label) + '</div>'
                     '<div class="cb-kpi-value">' + html.escape(value) + '</div>'
                     '<div class="cb-kpi-note">' + html.escape(note) + '</div></div>')
    st.markdown("".join(parts) + "</div>", unsafe_allow_html=True)


@st.cache_data(ttl=30, show_spinner=False)
def _states():
    result = central.api_call("bundle_state", {"source_keys": list(SOURCE_KEYS), "derived_keys": []}, timeout=30)
    sources = (result.get("data") or {}).get("sources") or []
    return {row["source_key"]: row for row in sources if row.get("source_key") in SOURCE_KEYS}


@st.cache_data(ttl=120, max_entries=6, show_spinner=False)
def _source(key: str, version: int, updated_at: str):
    del updated_at
    payload, meta = central.download_preferred_source(key)
    received_version = meta.get("source_version", meta.get("version"))
    if received_version is not None and int(received_version) != version:
        raise RuntimeError("A base foi atualizada durante a leitura. Atualize a conferência para carregar a mesma versão.")
    if str(meta.get("status") or "ATUALIZADO") != "ATUALIZADO":
        raise RuntimeError(f"A fonte {key} ainda não concluiu a atualização no Monitor API.")
    if payload["normalized"]:
        frame = central.normalized_frame(payload["pack"], sheet_contains="Geral" if key == "relatorio_geral" else None)
        rows = check.parse_general(frame) if key == "relatorio_geral" else check.parse_stock(frame)
    else:
        rows = check.parse_raw(payload["raw"], key)
    return rows, {k: v for k, v in meta.items() if k not in ("signed_url", "url")}


@st.cache_data(ttl=45, show_spinner=False)
def _imports():
    return movement_store.list_imports()


@st.cache_resource(max_entries=1, show_spinner=False)
def _history(tokens: tuple):
    entries = [{"chave": key, "atualizado_em": updated, "meta": meta} for key, updated, meta in tokens]
    packs = movement_store.load_history(entries)
    snapshot = mv.history_snapshot(packs)
    return snapshot["rows"], snapshot["coverage"], snapshot["duplicates"]


def _source_day(meta: dict) -> str:
    match = re.search(r"(\d{2})[-_](\d{2})[-_](\d{4})", str(meta.get("last_file_name") or ""))
    if match:
        return datetime.strptime("-".join(match.groups()), "%d-%m-%Y").date().isoformat()
    value = str(meta.get("last_update_at") or "")
    if not value:
        raise ValueError("Fonte sem data de atualização. Não é possível fixar a data da conferência.")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TZ).date().isoformat()


@st.cache_resource(ttl=120, max_entries=1, show_spinner=False)
def _audit(source_tokens: tuple, history_tokens: tuple, warehouses: tuple, version: str):
    del version
    sources, metas = {}, {}
    for key, source_version, updated in source_tokens:
        sources[key], metas[key] = _source(key, source_version, updated)
    rows, history_metas, duplicates = _history(history_tokens)
    as_of = min(_source_day(metas[key]) for key in SOURCE_KEYS)
    model = check.reconcile(sources["relatorio_geral"], sources["endereco"], rows,
                            history_metas=history_metas, as_of=as_of, warehouses=warehouses,
                            sources_same_day=len({_source_day(meta) for meta in metas.values()}) == 1)
    model["source_meta"] = metas
    model["history_meta"] = history_metas
    model["duplicates"] = duplicates
    return model


def _reload():
    _states.clear(); _source.clear(); _imports.clear(); _history.clear(); _audit.clear()


def _clear_filters():
    st.session_state.fm_issue_search = ""
    st.session_state.fm_issue_filter = "Todas"
    st.session_state.fm_issue_page = 1


def _table(frame: pd.DataFrame, columns=None, *, key=None):
    if frame.empty:
        st.info("Nenhum registro neste recorte.")
        return
    source = frame.loc[:, [c for c in columns if c in frame]] if columns else frame
    shown = source.copy()
    for col in QUANTITIES.intersection(shown.columns):
        shown[col] = shown[col].map(lambda v: None if v is None or pd.isna(v) else float(v))
    for col in ("data", "separacao", "conferencia", "reporte"):
        if col in shown:
            shown[col] = pd.to_datetime(shown[col], errors="coerce")
    shown = shown.rename(columns=LABELS)
    fmt = {LABELS.get(col, col): quantity for col in QUANTITIES.intersection(source.columns)}
    for col in ("data", "separacao", "conferencia", "reporte"):
        if col in source:
            fmt[LABELS.get(col, col)] = lambda v, field=col: "—" if pd.isna(v) else v.strftime("%d/%m/%Y" if field == "data" else "%d/%m/%Y %H:%M")
    styled = shown.style.format(fmt, na_rep="—")
    if "status" in source:
        colors = ["background-color:#fffbeb;color:#92400e" if bool(r.get("historico_incompleto"))
                  else "background-color:#fef2f2;color:#991b1b" if bool(r.get("divergente")) else ""
                  for r in frame.to_dict("records")]
        styled = styled.apply(lambda _: colors, axis=0, subset=["Resultado"])
    st.dataframe(styled, hide_index=True, width="stretch", key=key,
                 height=min(620, max(120, 77 + 35 * min(len(shown), 100))),
                 column_config={"Descrição": st.column_config.TextColumn(width="large"),
                                "Resultado": st.column_config.TextColumn(width="large")})


def _filter(frame: pd.DataFrame, query: str, choice: str) -> pd.DataFrame:
    view = frame
    term = mv.normalized(query)
    if term:
        haystack = (view["op"] + " OP" + view["op"] + " " + view["codigo"] + " " + view["descricao"] + " " + view["lotes"]).map(mv.normalized)
        view = view.loc[haystack.str.contains(term, regex=False)]
    condition = FILTERS[choice]
    if condition in ("divergente", "historico_incompleto", "op_possui_baixa"):
        view = view.loc[view[condition]]
    elif condition == "op_sem_baixa":
        view = view.loc[~view["op_possui_baixa"]]
    elif condition == "aguardando":
        view = view.loc[view["itens_conferidos"] == 0]
    elif condition == "BAIXA IDENTIFICADA":
        view = view.loc[view["status"] == condition]
    elif condition:
        view = view.loc[view["alertas"].map(lambda values: condition in values)]
    return view.copy()


def _details(model, item):
    if item["alertas"]:
        message = "\n\n".join(item["alertas"])
        if item["historico_incompleto"]:
            st.warning(message + ". A conclusão depende da atualização do KARDEX.")
        else:
            st.error(message)
    st.markdown("**" + str(item["descricao"]) + "**")
    st.write(f"Conferida: **{quantity(item['conferida'])}** · Baixada líquida: **{quantity(item['baixada'])}** · Pendente: **{quantity(item['pendente'])}**")
    if item["saldo_compartilhado"]:
        st.info("O saldo deste produto e lote também é consultado por outras OPs. A conferência não reserva nem distribui esse saldo automaticamente.")
    source_tab, stock_tab, kardex_tab = st.tabs(["CONFERÊNCIA MES", "LOTES E ENDEREÇOS", "MOVIMENTOS KARDEX"])
    with source_tab:
        rows = pd.DataFrame([r for r in model["general"] if r["item_id"] == item["item_id"]])
        _table(rows, ["codigo", "lote", "necessaria", "atendida", "pendencia_mes", "separacao", "responsavel_separacao",
                      "conferencia", "responsavel_conferencia", "reportado", "reporte", "referencia", "linha_origem"])
    with stock_tab:
        lots = model["lots"].loc[model["lots"]["item_id"] == item["item_id"]]
        st.caption("As baixas do KARDEX são comparadas uma única vez no total do produto na OP. Não há atribuição de baixa a um lote específico.")
        _table(lots, ["lote", "conferida", "saldo", "saldo_g9_prod", "ops_com_demanda"])
        allowed_lots = {r["lote"] for r in model["general"] if r["item_id"] == item["item_id"]}
        addresses = pd.DataFrame([r for r in model["stock"] if r["codigo"] == item["codigo"] and r["lote"] in allowed_lots])
        _table(addresses, ["codigo", "lote", "armazem", "endereco", "saldo", "empenho", "linha_origem"])
    with kardex_tab:
        movements = pd.DataFrame([r for r in model["movements"] if r["op"] == item["op"] and r["codigo"] == item["codigo"]])
        if not movements.empty:
            movements = movements.sort_values(["data", "documento"], kind="stable")
        st.caption("Saídas menos entradas/devoluções da mesma OP e produto. TES 499/999 permanecem na consulta e não comprovam baixa de consumo.")
        _table(movements, ["data", "armazem", "tes", "documento", "qtd_entrada", "qtd_saida", "ae_original", "natureza", "arquivo_origem", "linha_origem"])


def _ops(model, view, token):
    rank = view.groupby("op")["divergente"].sum().sort_values(ascending=False, kind="stable")
    numbers = rank.index.tolist()
    left, right = st.columns([1, 1])
    with left:
        size = st.selectbox("OPs por página", [10, 25, 50], key="fm_issue_page_size")
    pages = max(1, math.ceil(len(numbers) / size))
    if st.session_state.get("fm_issue_view_token") != token:
        st.session_state.fm_issue_page = 1
        st.session_state.fm_issue_view_token = token
    if st.session_state.get("fm_issue_page", 1) > pages:
        st.session_state.fm_issue_page = pages
    with right:
        page = st.number_input("Página", min_value=1, max_value=pages, step=1, key="fm_issue_page")
    st.caption(f"{count(len(numbers))} OPs encontradas · página {page} de {pages}. Os contadores respeitam os filtros.")
    info = model["ops"].set_index("op").to_dict("index")
    for number in numbers[(page - 1) * size:page * size]:
        group = view.loc[view["op"] == number]
        total = int(group["itens"].sum())
        separated = int(group["itens_separados"].sum())
        confirmed = int(group["itens_conferidos"].sum())
        issues = int(group["divergente"].sum())
        title = f"OP {number} · {total} itens · {separated} separados · {confirmed} conferidos · {issues} materiais com alerta"
        with st.expander(title):
            context = info[number]
            st.caption(f"P.A.: {context['pa'] or '—'} · {context['descricao_pa'] or 'Descrição não informada'}")
            st.caption("Histórico da OP: " + ("possui baixas líquidas de material." if bool(group.iloc[0]["op_possui_baixa"]) else "nenhuma baixa líquida de material localizada."))
            _table(group, ["codigo", "descricao", "lotes", "necessaria", "atendida", "conferida", "baixada", "pendente",
                           "saldo", "saldo_g9_prod", "status", "historico_incompleto", "saldo_compartilhado"])
            index = group.set_index("item_id").to_dict("index")
            selected = st.selectbox("Detalhar material e evidências", group["item_id"].tolist(), index=None,
                                    format_func=lambda value, rows=index: (rows[value]["codigo"] or "SEM CÓDIGO") + " · " + rows[value]["descricao"],
                                    placeholder="Selecione um material", key=f"fm_issue_detail_{number}_{token}")
            if selected:
                item = group.loc[group["item_id"] == selected].iloc[0].to_dict()
                _details(model, item)


def _sources(model):
    rows = []
    for key, label in (("relatorio_geral", "RELATÓRIO GERAL"), ("endereco", "ENDEREÇO")):
        meta = model["source_meta"][key]
        rows.append({"Fonte": label, "Arquivo": meta.get("last_file_name"), "Versão": meta.get("source_version", meta.get("version")),
                     "Atualizada em": central.format_dt(meta.get("last_update_at")),
                     "Registros usados": len(model["general"] if key == "relatorio_geral" else model["stock"])})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if model["history_meta"]:
        st.dataframe(pd.DataFrame([{"Arquivo KARDEX": m["arquivo_nome"], "Armazém": m.get("armazem", "—"),
                                    "Competência": m.get("competencia", "—"), "De": day(m["periodo_inicio"]), "Até": day(m["periodo_fim"]),
                                    "Registros nesta cobertura": m["lancamentos"]} for m in model["history_meta"]]), hide_index=True, width="stretch")
        st.caption("A conferência utiliza somente as versões vigentes do KARDEX. A cobertura precisa atender a todos os armazéns selecionados.")
    st.markdown("**Critérios da conferência**")
    st.write("• Conferência identificada pela data de conferência do MES; a quantidade comparada é a atendida nessas linhas. Conferências parciais mantêm a necessária e a pendência visíveis.")
    st.write("• Estoque consultado por produto e lote nos armazéns selecionados. O saldo é a coluna Quantidade; o empenho aparece separado nas evidências.")
    st.write("• KARDEX vinculado por OP completa da AE e código do produto, sem filtro de CF. Saídas menos entradas/devoluções; transferências 499/999 não integram o consumo.")
    st.write("• O alerta de G9-PROD destaca quantidade conferida ainda pendente quando a OP já possui baixa líquida de algum material. OPs sem nenhuma baixa no histórico ficam identificadas à parte.")
    st.write("• A baixa é comparada com o total conferido do produto na OP. O lote é usado para consultar o saldo por endereço; sobra de outro lote não cobre automaticamente uma falta.")
    st.write("• O mesmo saldo não é reservado para várias OPs. Demandas compartilhadas e insuficiência conjunta são identificadas separadamente.")
    st.write("• Registros repetidos no MES são mantidos e somados. Sobreposição entre arquivos KARDEX é reconhecida sem duplicar movimentos.")
    st.write("• Diferenças de até 0,000001 são tratadas como precisão numérica. Os valores originais permanecem nas evidências.")
    st.caption(f"Referência da conferência: {day(model['as_of'])}. Movimentos posteriores à data da base são desconsiderados ({count(model['movimentos_apos_base'])}).")
    if model["duplicates"]:
        st.caption(f"Movimentos repetidos entre importações reconhecidos: {count(model['duplicates'])}.")
    if model["negative_stock_rows"]:
        st.warning(f"O relatório contém {count(model['negative_stock_rows'])} registros de saldo negativo nos armazéns selecionados. Eles foram mantidos no cálculo.")


def render_results(model):
    frame = model["items"]
    period = model["coverage"]
    if not model["history_available"]:
        st.warning("Nenhum KARDEX foi localizado para os armazéns selecionados. A consulta de materiais e saldos está disponível, mas a conferência de baixas aguarda histórico.")
    elif not period["fim"]:
        st.warning("Os armazéns selecionados não possuem um período comum de cobertura do KARDEX. Confira as fontes antes de concluir os alertas.")
    elif period["fim"] < model["as_of"]:
        st.warning(f"KARDEX disponível até {day(period['fim'])}; bases consultadas em {day(model['as_of'])}. Os alertas com histórico incompleto precisam de atualização do KARDEX antes da conclusão.")
    days = {_source_day(m) for m in model["source_meta"].values()}
    if len(days) > 1:
        st.warning("Relatório Geral e Endereço possuem datas de referência diferentes. A conferência usa a data mais antiga; atualize as duas bases para concluir a análise.")
    if len(period["intervalos"]) > 1:
        st.warning("Há intervalos sem cobertura entre os arquivos KARDEX. Consulte as fontes antes de concluir os alertas.")
    a, b, c = st.columns([2, 1.5, 1])
    with a:
        query = st.text_input("Buscar OP, produto, descrição ou lote", key="fm_issue_search")
    with b:
        choice = st.selectbox("Situação", list(FILTERS), key="fm_issue_filter")
    with c:
        st.button("LIMPAR FILTROS", on_click=_clear_filters, key="fm_issue_clear")
    view = _filter(frame, query, choice)
    _cards([("OPs encontradas", count(view["op"].nunique()), "Ordens no filtro"),
            ("Itens", count(view["itens"].sum()), "Registros de material no MES"),
            ("Separados", count(view["itens_separados"].sum()), "Com data de separação"),
            ("Conferidos", count(view["itens_conferidos"].sum()), "Com data de conferência")])
    alerts = view.loc[view["divergente"]]
    st.caption(f"{count(alerts['op'].nunique())} OPs com alertas · {count(len(alerts))} materiais com alerta. As quantidades são apresentadas por produto, sem somar unidades diferentes.")
    token = hashlib.sha256((check.VERSION + query + choice + str(model["warehouses"]) + str(model["source_meta"]) + str(period)).encode()).hexdigest()[:14]
    area = st.radio("Consulta", ["Por OP", "Divergências", "Fontes e critérios"], horizontal=True, key="fm_issue_area", label_visibility="collapsed")
    if area == "Fontes e critérios":
        _sources(model)
    elif view.empty:
        st.info("Nenhum material corresponde aos filtros selecionados.")
    elif area == "Por OP":
        _ops(model, view, token)
    else:
        _table(alerts, ["op", "codigo", "descricao", "lotes", "conferida", "baixada", "pendente", "saldo", "saldo_g9_prod",
                        "sem_saldo", "em_g9_prod", "status", "historico_incompleto", "saldo_compartilhado"])
        st.caption("Abra a OP na consulta Por OP e selecione o material para visualizar as linhas do MES, endereços e movimentos que originaram o alerta.")


def render_issue_check():
    _band()
    st.button("ATUALIZAR CONFERÊNCIA", on_click=_reload, key="fm_issue_reload")
    try:
        states = _states()
        for key in SOURCE_KEYS:
            if key not in states or not states[key].get("available") or states[key].get("status") != "ATUALIZADO":
                raise RuntimeError(f"Fonte {key} indisponível ou sem atualização concluída no Monitor API.")
        tokens = tuple((key, int(states[key]["version"]), str(states[key].get("last_update_at") or "")) for key in SOURCE_KEYS)
        with st.spinner("Lendo as bases diárias do Monitor API..."):
            stock, _ = _source(*next(t for t in tokens if t[0] == "endereco"))
        options = sorted({r["armazem"] for r in stock})
        if "fm_issue_warehouses" in st.session_state:
            st.session_state.fm_issue_warehouses = [w for w in st.session_state.fm_issue_warehouses if w in options]
        chosen = st.multiselect("Armazéns do saldo e do KARDEX", options, default=["S2"] if "S2" in options else options, key="fm_issue_warehouses")
        if not chosen:
            st.info("Selecione ao menos um armazém para conferir saldos e baixas.")
            return
        imports = _imports()
        history_tokens = tuple((i["chave"], str(i.get("atualizado_em") or ""), i.get("meta") or {}) for i in imports)
        with st.spinner("Conferindo as OPs, os saldos por lote e as baixas registradas..."):
            model = _audit(tokens, history_tokens, tuple(sorted(chosen)), check.VERSION)
        render_results(model)
    except Exception as exc:
        st.error(f"Não foi possível concluir a conferência: {exc}")
        st.info("A ausência de uma fonte não é tratada como saldo zero ou ausência de baixa. Use Atualizar conferência após regularizar a base.")
