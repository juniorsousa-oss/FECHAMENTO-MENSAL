from __future__ import annotations

from datetime import date
import os

import requests
import streamlit as st

DEFAULT_SUPABASE_URL = "https://cuixazpxkvniqldmmnth.supabase.co"
DEFAULT_SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImN1aXhhenB4a3ZuaXFsZG1tbnRoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1MTYwNTMsImV4cCI6MjEwMzA5MjA1M30.jNFaIG1FcDYnMAoVaI23UYMuRL1BpZmuqu_LPEYb88E"


def _secret(*names: str) -> str:
    for name in names:
        try:
            value = st.secrets.get(name)
            if value:
                return str(value).strip()
        except Exception:
            pass
        value = os.getenv(name)
        if value:
            return str(value).strip()
    try:
        supa = st.secrets.get("supabase", {})
        for name in names:
            for key in (name, name.lower(), name.replace("SUPABASE_", "").lower()):
                value = supa.get(key)
                if value:
                    return str(value).strip()
    except Exception:
        pass
    return ""


def supabase_url() -> str:
    return _secret("SUPABASE_URL") or DEFAULT_SUPABASE_URL


def supabase_key() -> str:
    return (
        _secret("SUPABASE_ANON_KEY", "SUPABASE_KEY", "SUPABASE_PUBLISHABLE_KEY")
        or DEFAULT_SUPABASE_ANON_KEY
    )


def configured() -> bool:
    return bool(supabase_url() and supabase_key())


def _headers(prefer: str | None = None) -> dict[str, str]:
    key = supabase_key()
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _raise(response: requests.Response) -> None:
    if response.ok:
        return
    try:
        payload = response.json()
        message = (
            payload.get("message")
            or payload.get("error")
            or payload.get("hint")
            or str(payload)
        )
    except Exception:
        message = response.text
    raise RuntimeError(f"Supabase HTTP {response.status_code}: {message}")


def rpc(name: str, payload: dict | None = None, timeout: int = 45):
    response = requests.post(
        f"{supabase_url()}/rest/v1/rpc/{name}",
        headers=_headers(),
        json=payload or {},
        timeout=timeout,
    )
    _raise(response)
    if not response.text.strip():
        return None
    return response.json()


def load_nfs_visual_config() -> dict:
    """Lê a identidade visual efetivamente salva pelo app NFS Setta."""
    response = requests.get(
        f"{supabase_url()}/rest/v1/nf_configuracoes",
        headers=_headers(),
        params={"select": "valor", "chave": "eq.app", "limit": "1"},
        timeout=20,
    )
    _raise(response)
    rows = response.json() or []
    if not rows:
        return {}
    value = rows[0].get("valor") or {}
    return value if isinstance(value, dict) else {}


def load_config() -> dict:
    response = requests.get(
        f"{supabase_url()}/rest/v1/fm_configuracoes",
        headers=_headers(),
        params={"select": "valor", "chave": "eq.app", "limit": "1"},
        timeout=20,
    )
    _raise(response)
    rows = response.json() or []
    if not rows:
        return {}
    value = rows[0].get("valor") or {}
    return value if isinstance(value, dict) else {}


def save_config(config: dict) -> None:
    rpc(
        "fm_salvar_configuracao",
        {"p_chave": "app", "p_valor": config},
        timeout=45,
    )


def list_months() -> list[dict]:
    response = requests.get(
        f"{supabase_url()}/rest/v1/fm_fechamentos_mensais",
        headers=_headers(),
        params={"select": "*", "order": "competencia.desc"},
        timeout=30,
    )
    _raise(response)
    return response.json() or []


def get_month(competencia: date) -> dict:
    month_key = competencia.replace(day=1).isoformat()
    response = requests.get(
        f"{supabase_url()}/rest/v1/fm_fechamentos_mensais",
        headers=_headers(),
        params={
            "select": "*",
            "competencia": f"eq.{month_key}",
            "limit": "1",
        },
        timeout=20,
    )
    _raise(response)
    rows = response.json() or []
    return rows[0] if rows else {}


def save_month(data: dict) -> None:
    competencia = data["competencia"]
    if isinstance(competencia, date):
        competencia = competencia.replace(day=1).isoformat()

    payload = {
        "p_competencia": competencia,
        "p_faturamento": float(data.get("faturamento") or 0),
        "p_ei_s2": float(data.get("ei_s2") or 0),
        "p_ef_s2": float(data.get("ef_s2") or 0),
        "p_baixa_op_s2": float(data.get("baixa_op_s2") or 0),
        "p_ajustes_s2": float(data.get("ajustes_s2") or 0),
        "p_compras_s2": float(data.get("compras_s2") or 0),
        "p_transferencias_s2": float(data.get("transferencias_s2") or 0),
        "p_vendas_s2": float(data.get("vendas_s2") or 0),
        "p_ei_ep": float(data.get("ei_ep") or 0),
        "p_ef_ep": float(data.get("ef_ep") or 0),
        "p_ei_pa": float(data.get("ei_pa") or 0),
        "p_ef_pa": float(data.get("ef_pa") or 0),
        "p_observacao": str(data.get("observacao") or ""),
    }
    rpc("fm_salvar_fechamento", payload, timeout=45)



def list_inventory_imports() -> list[dict]:
    response = requests.get(
        f"{supabase_url()}/rest/v1/fm_importacoes",
        headers=_headers(),
        params={
            "select": "competencia,arquivo_nome,total_linhas,linhas_validas,linhas_invalidas,valor_total,status,importado_em",
            "order": "competencia.desc",
        },
        timeout=30,
    )
    _raise(response)
    return response.json() or []


def list_inventory_summaries() -> list[dict]:
    response = requests.get(
        f"{supabase_url()}/rest/v1/fm_estoque_resumos",
        headers=_headers(),
        params={
            "select": "competencia,dimensao,chave,armz,tp,valor_total,itens",
            "order": "competencia.asc,dimensao.asc,chave.asc",
        },
        timeout=30,
    )
    _raise(response)
    return response.json() or []


def list_import_errors(competencia: date | str) -> list[dict]:
    if isinstance(competencia, date):
        key = competencia.replace(day=1).isoformat()
    else:
        key = str(competencia)[:10]

    response = requests.get(
        f"{supabase_url()}/rest/v1/fm_importacao_erros",
        headers=_headers(),
        params={
            "select": "codigo,tp,armz,saldo,valor_estoque,descricao,motivo",
            "competencia": f"eq.{key}",
            "order": "codigo.asc",
        },
        timeout=20,
    )
    _raise(response)
    return response.json() or []


def import_inventory_report(
    competencia: date,
    file_name: str,
    rows: list[dict],
) -> dict:
    payload_rows = []
    for row in rows:
        payload_rows.append(
            {
                "codigo": str(row.get("codigo") or "").strip(),
                "tp": str(row.get("tp") or "").strip(),
                "armz": str(row.get("armz") or "").strip(),
                "saldo": float(row.get("saldo") or 0),
                "valor_estoque": float(row.get("valor_estoque") or 0),
                "descricao": str(row.get("descricao") or "").strip(),
                "descricao_armazem": str(
                    row.get("descricao_armazem") or ""
                ).strip(),
            }
        )

    result = rpc(
        "fm_importar_estoque",
        {
            "p_competencia": competencia.replace(day=1).isoformat(),
            "p_arquivo_nome": file_name,
            "p_rows": payload_rows,
        },
        timeout=120,
    )
    return result or {}



def list_inventory_items(competencia: date | str) -> list[dict]:
    if isinstance(competencia, date):
        key = competencia.replace(day=1).isoformat()
    else:
        key = str(competencia)[:10]

    response = requests.get(
        f"{supabase_url()}/rest/v1/fm_estoque_itens",
        headers=_headers(),
        params={
            "select": "codigo,tp,armz,saldo,valor_estoque,descricao,descricao_armazem",
            "competencia": f"eq.{key}",
            "order": "codigo.asc,armz.asc",
        },
        timeout=45,
    )
    _raise(response)
    return response.json() or []


def list_cb_catalog() -> list[dict]:
    response = requests.get(
        f"{supabase_url()}/rest/v1/fm_cb_catalogo",
        headers=_headers(),
        params={
            "select": "codigo,categoria,descricao,referencia,unidade,ult_preco,status,origem,regra_detectada,ativo,atualizado_em",
            "ativo": "eq.true",
            "order": "status.asc,categoria.asc,codigo.asc",
        },
        timeout=30,
    )
    _raise(response)
    return response.json() or []


def save_cb_catalog_item(
    codigo: str,
    categoria: str,
    descricao: str = "",
) -> None:
    rpc(
        "fm_cb_salvar_item_catalogo",
        {
            "p_codigo": str(codigo).strip(),
            "p_categoria": str(categoria).strip(),
            "p_descricao": str(descricao or "").strip(),
        },
        timeout=30,
    )


def list_cb_counts(competencia: date | str) -> list[dict]:
    if isinstance(competencia, date):
        key = competencia.replace(day=1).isoformat()
    else:
        key = str(competencia)[:10]

    response = requests.get(
        f"{supabase_url()}/rest/v1/fm_cb_contagens",
        headers=_headers(),
        params={
            "select": "id,competencia,fonte,codigo,quantidade_fisica,observacao,origem_ref,atualizado_em",
            "competencia": f"eq.{key}",
            "order": "fonte.asc,codigo.asc",
        },
        timeout=30,
    )
    _raise(response)
    return response.json() or []


def save_cb_count(
    competencia: date,
    fonte: str,
    codigo: str,
    quantidade_fisica: float,
    observacao: str = "",
    origem_ref: str = "",
) -> None:
    rpc(
        "fm_cb_salvar_contagem",
        {
            "p_competencia": competencia.replace(day=1).isoformat(),
            "p_fonte": str(fonte).strip(),
            "p_codigo": str(codigo).strip(),
            "p_quantidade_fisica": float(quantidade_fisica),
            "p_observacao": str(observacao or "").strip(),
            "p_origem_ref": str(origem_ref or "").strip(),
        },
        timeout=30,
    )



def sync_cb_catalog(rows: list[dict]) -> dict:
    result = rpc(
        "fm_cb_sincronizar_catalogo",
        {"p_rows": rows},
        timeout=120,
    )
    return result or {}


def update_cb_catalog_status(
    codigo: str,
    categoria: str,
    status: str,
) -> None:
    rpc(
        "fm_cb_atualizar_catalogo",
        {
            "p_codigo": str(codigo).strip(),
            "p_categoria": str(categoria).strip(),
            "p_status": str(status).strip(),
        },
        timeout=30,
    )


def list_cb_sheet_mappings() -> list[dict]:
    response = requests.get(
        f"{supabase_url()}/rest/v1/fm_cb_chapa_mapeamentos",
        headers=_headers(),
        params={
            "select": "id,dimensao_norm,descricao_norm,dimensao_origem,descricao_origem,codigo,status,origem,atualizado_em",
            "order": "descricao_norm.asc,dimensao_norm.asc",
        },
        timeout=30,
    )
    _raise(response)
    return response.json() or []


def save_cb_sheet_mapping(
    dimensao_norm: str,
    descricao_norm: str,
    dimensao_origem: str,
    descricao_origem: str,
    codigo: str,
    status: str = "CONFIRMADO",
    origem: str = "APP",
) -> None:
    rpc(
        "fm_cb_salvar_mapeamento_chapa",
        {
            "p_dimensao_norm": str(dimensao_norm or "*").strip(),
            "p_descricao_norm": str(descricao_norm or "").strip(),
            "p_dimensao_origem": str(dimensao_origem or "").strip(),
            "p_descricao_origem": str(descricao_origem or "").strip(),
            "p_codigo": str(codigo or "").strip(),
            "p_status": str(status or "CONFIRMADO").strip(),
            "p_origem": str(origem or "APP").strip(),
        },
        timeout=30,
    )


def save_cb_counts_batch(
    competencia: date,
    fonte: str,
    arquivo_nome: str,
    rows: list[dict],
) -> dict:
    payload = []
    for row in rows:
        payload.append(
            {
                "codigo": str(row.get("codigo") or "").strip(),
                "quantidade_fisica": float(
                    row.get("quantidade_fisica") or 0
                ),
                "observacao": str(
                    row.get("observacao") or ""
                ).strip(),
                "origem_ref": str(
                    row.get("origem_ref")
                    or arquivo_nome
                    or ""
                ).strip(),
            }
        )

    result = rpc(
        "fm_cb_salvar_contagens_lote",
        {
            "p_competencia": competencia.replace(day=1).isoformat(),
            "p_fonte": str(fonte).strip(),
            "p_arquivo_nome": str(arquivo_nome or "").strip(),
            "p_rows": payload,
        },
        timeout=120,
    )
    return result or {}


def list_cb_imports(
    competencia: date | str | None = None,
) -> list[dict]:
    params = {
        "select": "id,competencia,fonte,arquivo_nome,linhas,valor_fisico,pendencias,status,importado_em",
        "order": "importado_em.desc",
    }

    if competencia is not None:
        if isinstance(competencia, date):
            key = competencia.replace(day=1).isoformat()
        else:
            key = str(competencia)[:10]
        params["competencia"] = f"eq.{key}"

    response = requests.get(
        f"{supabase_url()}/rest/v1/fm_cb_importacoes",
        headers=_headers(),
        params=params,
        timeout=30,
    )
    _raise(response)
    return response.json() or []



def list_cb_system_balances(
    competencia: date | str,
) -> list[dict]:
    if isinstance(competencia, date):
        key = competencia.replace(day=1).isoformat()
    else:
        key = str(competencia)[:10]

    response = requests.get(
        f"{supabase_url()}/rest/v1/fm_cb_saldos_sistema",
        headers=_headers(),
        params={
            "select": "competencia,codigo,armz,saldo,descricao,arquivo_nome,importado_em",
            "competencia": f"eq.{key}",
            "order": "codigo.asc,armz.asc",
        },
        timeout=30,
    )
    _raise(response)
    return response.json() or []


def save_cb_system_balances(
    competencia: date,
    arquivo_nome: str,
    rows: list[dict],
) -> dict:
    payload = []
    for row in rows:
        payload.append(
            {
                "codigo": str(row.get("codigo") or "").strip(),
                "armz": str(row.get("armz") or "").strip(),
                "saldo": max(
                    float(row.get("saldo") or 0),
                    0.0,
                ),
                "descricao": str(
                    row.get("descricao") or ""
                ).strip(),
            }
        )

    result = rpc(
        "fm_cb_salvar_saldos_sistema",
        {
            "p_competencia": competencia.replace(day=1).isoformat(),
            "p_arquivo_nome": str(arquivo_nome or "").strip(),
            "p_rows": payload,
        },
        timeout=120,
    )
    return result or {}



def list_data_sources() -> list[dict]:
    result = rpc(
        "fm_list_data_sources_status",
        {},
        timeout=30,
    )
    return result or []
