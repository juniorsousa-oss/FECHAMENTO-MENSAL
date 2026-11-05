"""Indicador oficial de acurácia de estoque por competência (persistido)."""
from __future__ import annotations

import re

import streamlit as st
import pandas as pd

import inventory_db as db
import kardex_adjustments as adjustments

CONFIG_KEY = "fm_acuracia_estoque_v1"


def accuracy(total: int, adjustments: int) -> float:
    if total <= 0 or adjustments < 0 or adjustments > total:
        raise ValueError("A quantidade de ajustes deve estar entre 0 e os itens conferidos.")
    return (total - adjustments) / total


@st.cache_data(ttl=60, show_spinner=False)
def load() -> dict:
    import requests
    response = requests.get(
        f"{db.supabase_url()}/rest/v1/fm_configuracoes",
        headers=db._headers(),
        params={"select": "valor", "chave": f"eq.{CONFIG_KEY}", "limit": "1"},
        timeout=20,
    )
    db._raise(response)
    data = response.json() or []
    obj = data[0].get("valor") if data else {}
    return obj if isinstance(obj, dict) else {}


def save_month(month: str, total: int, count: int, note: str = "") -> dict:
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("Competência inválida.")
    rate = accuracy(int(total), int(count))
    confirmed = adjustments.load_registry().get("meses", {}).get(month)
    if confirmed is not None and len(confirmed) != int(count):
        raise ValueError(
            f"O indicador informa {count} ajustes, mas o KARDEX possui "
            f"{len(confirmed)} movimentos confirmados. Regularize antes de gravar."
        )
    current = load()
    months = dict(current.get("meses") or {})
    months[month] = {
        "itens_conferidos": int(total),
        "ajustes_confirmados": int(count),
        "itens_sem_ajuste": int(total) - int(count),
        "acuracia": round(rate * 100, 6),
        "status": "FECHADO",
        "armazem": "S2",
        "observacao": str(note or "").strip()[:400],
    }
    data = {"versao": 1, "meses": months}
    db.rpc("fm_salvar_configuracao",
           {"p_chave": CONFIG_KEY, "p_valor": data}, timeout=45)
    load.clear()
    verified = load()
    if verified.get("meses", {}).get(month) != months[month]:
        raise RuntimeError("O indicador não foi confirmado no banco de dados.")
    return months[month]


def render() -> None:
    st.caption(
        "ACURÁCIA (%) = (ITENS CONFERIDOS − AJUSTES CONFIRMADOS) / "
        "ITENS CONFERIDOS × 100. Ajustes são os movimentos expressamente "
        "validados no Kardex, sem incluir material de consumo."
    )
    try:
        records = load().get("meses") or {}
        registry = adjustments.load_registry()
    except Exception as exc:
        st.error("Não foi possível consultar o histórico de acurácia: " + str(exc))
        return
    if records:
        display = []
        for month, row in sorted(records.items(), reverse=True):
            display.append({
                "Competência": month[5:7] + "/" + month[:4],
                "Armazém": row.get("armazem") or "S2",
                "Itens conferidos": row.get("itens_conferidos"),
                "Ajustes confirmados": row.get("ajustes_confirmados"),
                "Itens sem ajuste": row.get("itens_sem_ajuste"),
                "Acurácia (%)": row.get("acuracia"),
                "Situação": row.get("status"),
            })
        st.dataframe(
            pd.DataFrame(display), hide_index=True, use_container_width=True,
            column_config={
                "Acurácia (%)": st.column_config.NumberColumn(
                    "Acurácia (%)", format="%.2f%%"
                )
            },
        )
        latest = display[0]
        left, mid, right = st.columns(3)
        left.metric("ACURÁCIA · " + latest["Armazém"] + " · " + latest["Competência"],
                    f"{float(latest['Acurácia (%)']):.2f}%".replace(".", ","))
        mid.metric("ITENS CONFERIDOS", latest["Itens conferidos"])
        right.metric("AJUSTES REAIS", latest["Ajustes confirmados"])
    else:
        st.info("Nenhum indicador de acurácia registrado.")

    options = sorted(set(records) | set(registry.get("meses") or {}), reverse=True)
    if not options:
        options = ["2026-10"]
    with st.expander("REGISTRAR OU CORRIGIR INDICADOR", expanded=False):
        month = st.selectbox(
            "Competência", options,
            format_func=lambda text: text[5:] + "/" + text[:4],
            key="fm_accuracy_month",
        )
        data = records.get(month) or {}
        verified_count = len((registry.get("meses") or {}).get(month, []))
        st.caption(
            f"Ajustes confirmados no KARDEX para {month}: {verified_count}. "
            "Para alterar essa relação, utilize Configurações → Alimentadores → Ajustes de Estoque."
        )
        with st.form("fm_accuracy_save"):
            total = st.number_input(
                "Itens conferidos", min_value=1, step=1,
                value=max(1, int(data.get("itens_conferidos") or 1)),
            )
            count = st.number_input(
                "Ajustes confirmados", min_value=0, step=1,
                value=int(data.get("ajustes_confirmados") or verified_count),
            )
            note = st.text_input(
                "Observação", value=str(data.get("observacao") or ""),
            )
            submit = st.form_submit_button("GRAVAR INDICADOR DE ACURÁCIA",
                                           type="primary")
        if submit:
            try:
                save_month(month, int(total), int(count), note)
                st.success("Indicador de acurácia gravado e conferido.")
                st.rerun()
            except Exception as exc:
                st.error("Indicador não gravado: " + str(exc))
