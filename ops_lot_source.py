"""Fonte persistente das baixas por OP, material e LOTE (Relatório OPS).

Substitui o uso do KARDEX apenas na Conferência de Baixas. Cada
importação substitui SOMENTE as datas presentes no intervalo do arquivo;
o histórico fora desse intervalo é preservado. O KARDEX permanece intacto.
"""
from __future__ import annotations

import base64
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
import gzip
import hashlib
import io
import json
import re
from datetime import timezone

import requests

import inventory_db as db
import movements as mv

KEY = "fm_conferencia_ops_lotes_v1"
BACKUP_KEY = "fm_conferencia_ops_lotes_backup_v1"
FORMAT = "setta_ops_lotes_v1"
# A versão da FONTE permanece igual porque nenhuma regra de movimento mudou.
# A versão do LEITOR invalida apenas a prévia/cache de XLSX/XLTX.
VERSION = "2026-11-03.2"
PARSER_VERSION = "2026-11-04.1-HEADER-MAPPING"
# Na base OPS, RE1/TES 999 também representa baixa associada à OP.
# A exclusão anterior omitia 9.785 lançamentos do arquivo de referência,
# inclusive 16 UN do 06050080 na OP 26017801001 (20/10/2026).
# RE5/999 permanece fora até validação de sua natureza específica.
# PR0/010 continua excluído por representar apontamento de produção.
ISSUES = {("RE0", "520"), ("RE0", "550"), ("RE6", "550"), ("RE1", "999")}
RETURNS = {("DE0", "020")}
REQUIRED = {"B": "ORDPRODUCAO", "D": "PRODUTO", "F": "QUANTIDADE",
            "K": "DTEMISSAO", "N": "LOTE"}

# Nunca classificar um movimento como baixa sem identificar C (RE/DE) e
# O (TES). O Protheus pode alterar o texto ou a ordem das colunas: a
# conciliação precisa reconhecer o cabeçalho REAL, não supor posições.
HEADER_ALIASES = {
    "op": {"ORDPRODUCAO", "ORDEMPRODUCAO", "ORDEMDEPRODUCAO", "ORDDEPRODUCAO",
           "ORDPROD", "ORDEMPROD", "OP", "NUMOP", "NUMERODAOP"},
    "codigo": {"PRODUTO", "CODPRODUTO", "CODIGOPRODUTO",
               "CODMATERIAL", "CODIGOMATERIAL", "CODIGOITEM"},
    "quantidade": {"QUANTIDADE", "QTD", "QTDMOVIMENTADA",
                   "QUANTMOVIMENTADA", "QUANTIDADEMOVIMENTADA"},
    "data": {"DTEMISSAO", "DATAEMISSAO", "DTMOVIMENTO",
             "DATAMOVIMENTO", "DTBAIXA", "DATABAIXA"},
    "lote": {"LOTE", "NUMLOTE", "NUMEROLOTE", "LOTEPRODUTO",
             "CODLOTE", "CODIGOLOTE"},
    "movimento": {"TIPOREDE", "TIPOMOVIMENTO", "TIPOMOV",
                   "TIPOREQUISICAODEVOLUCAO"},
    "tes": {"TPMOVIMENTO", "TPMOVIM", "TES", "CODTES", "CODIGOTES",
            "TPMOV", "TIPOTES"},
}
HEADER_OPTIONAL = {"documento": {"DOCUMENTO", "DOC", "NUMDOCUMENTO"}}
PREFERRED_COLUMNS = {
    "op": "B", "codigo": "D", "quantidade": "F", "data": "K",
    "lote": "N", "movimento": "C", "tes": "O", "documento": "J",
}


def _header_token(value) -> str:
    return re.sub(r"[^A-Z0-9]", "", mv.normalized(value))


def _detect_header(cells: dict) -> dict[str, str] | None:
    """Exige sete papéis distintos; detecta aliases e colunas deslocadas.

    Em cabeçalhos ambíguos, só resolve quando a posição do layout original
    identifica inequivocamente uma das alternativas.
    """
    names = {col: _header_token(value) for col, value in cells.items()}
    resolved = {}
    for role, aliases in {**HEADER_ALIASES, **HEADER_OPTIONAL}.items():
        candidates = [col for col, name in names.items() if name in aliases]
        if not candidates:
            if role in HEADER_ALIASES:
                return None
            continue
        if len(candidates) == 1:
            resolved[role] = candidates[0]
        elif PREFERRED_COLUMNS[role] in candidates:
            resolved[role] = PREFERRED_COLUMNS[role]
        else:
            return None
    if len(set(resolved.values())) != len(resolved):
        return None
    return resolved


def _header_diagnostic(rows: list[tuple]) -> str:
    if not rows:
        return "Nenhuma linha legível foi encontrada no arquivo."
    closest = max(
        rows,
        key=lambda entry: sum(
            _header_token(c) in aliases
            for aliases in HEADER_ALIASES.values()
            for c in entry[2].values()
        ),
    )
    sheet, number, cells = closest
    sample = " | ".join(
        f"{col}: {str(value).strip()[:36]}"
        for col, value in list(cells.items())[:17]
    )
    return (
        f"Cabeçalho OPS não localizado. Linha mais próxima: aba {sheet!r}, "
        f"linha {number}. Colunas encontradas: {sample}. "
        "Necessário identificar OP, Produto, Quantidade, Data, Lote, "
        "Tipo RE/DE e TES/TP Movimento. O histórico anterior não foi alterado."
    )



def lot(value) -> str:
    """Mantém zeros à esquerda e não confunde vazio com lote fictício."""
    raw = str(value or "").strip()
    if re.fullmatch(r"\d+\.0+", raw):
        raw = raw.split(".")[0]
    return raw


def _op(value) -> str:
    match = re.fullmatch(r"(?:OP[\s:/-]*)?(\d+)(?:\.0+)?",
                         str(value or "").strip(), re.IGNORECASE)
    return match.group(1) if match else ""


def parse(raw: bytes, file_name: str) -> dict:
    if not file_name.lower().endswith((".xlsx", ".xltx")):
        raise ValueError("Envie o relatório OPS em formato XLSX ou XLTX.")
    digest = hashlib.sha256(raw).hexdigest()
    maps = {}
    grouped = defaultdict(Decimal)
    representative = {}
    stats = Counter()
    dates = set()
    errors = []
    sample_headers = []
    for sheet, line, cells, epoch in mv._xml_rows(raw):
        found = _detect_header(cells)
        if found is not None:
            # Repetição do cabeçalho dentro da planilha é comum.
            maps[sheet] = found
            continue
        if sheet not in maps:
            # Limitar somente a amostragem para diagnóstico, nunca a
            # procura do cabeçalho, que percorre a planilha inteira.
            if len(sample_headers) < 30:
                sample_headers.append((sheet, line, cells))
            continue
        cols = maps[sheet]
        movement_type = str(cells.get(cols["movimento"]) or "").strip().upper()
        tes = mv.identifier(cells.get(cols["tes"]), 3)
        kind = (movement_type, tes)
        if kind not in ISSUES and kind not in RETURNS:
            stats["outros_movimentos_ignorados"] += 1
            if kind == ("RE5", "999"):
                stats["re5_999_pendentes_analise"] += 1
            continue
        try:
            op = _op(cells.get(cols["op"]))
            code = mv.identifier(cells.get(cols["codigo"]), 8)
            if not op or not re.fullmatch(r"\d{8}", code):
                raise ValueError("OP ou código de produto inválido")
            d = mv._date(cells.get(cols["data"]), epoch)
            quantity = mv.decimal(cells.get(cols["quantidade"]))
            if kind in ISSUES and quantity < 0:
                raise ValueError("requisição com quantidade negativa")
            if kind in RETURNS and quantity > 0:
                raise ValueError("devolução com sinal positivo")
            if not quantity:
                stats["quantidade_zero"] += 1
                continue
            lote = lot(cells.get(cols["lote"]))
            key = (op, code, lote, d, movement_type, tes)
            grouped[key] += quantity
            doc_col = cols.get("documento")
            representative.setdefault(
                key, (str(cells.get(doc_col) or "") if doc_col else "", line)
            )
            dates.add(d)
            stats["movimentos_validos"] += 1
            if kind == ("RE1", "999"):
                stats["re1_999_reconhecidos"] += 1
            if not lote:
                stats["movimentos_sem_lote"] += 1
        except (ValueError, TypeError) as exc:
            errors.append(f"{sheet}, linha {line}: {exc}")
            if len(errors) >= 20:
                break

    if not maps:
        raise ValueError(_header_diagnostic(sample_headers))
    if errors:
        raise ValueError(
            "O arquivo possui movimentações inconsistentes. Importação bloqueada: "
            + "; ".join(errors[:8])
        )
    if not grouped:
        raise ValueError("Não foram identificadas requisições/devoluções de OP válidas.")
    rows = []
    for key, qty in sorted(grouped.items()):
        if not qty:
            continue
        op, code, lote, day, movement_type, tes = key
        document, source_line = representative[key]
        rows.append({
            "op": op, "codigo": code, "lote": lote, "data": day,
            "tipo_movimento": movement_type, "tes": tes,
            "quantidade": str(qty), "documento": document,
            "linha_origem": source_line,
        })
    meta = {
        "arquivo_nome": file_name, "sha256": digest,
        "linhas_lidas": stats["movimentos_validos"] + stats["outros_movimentos_ignorados"]
                        + stats["quantidade_zero"],
        "movimentos_validos": stats["movimentos_validos"],
        "movimentos_sem_lote": stats["movimentos_sem_lote"],
        "re1_999_reconhecidos": stats["re1_999_reconhecidos"],
        "re5_999_pendentes_analise": stats["re5_999_pendentes_analise"],
        "outros_movimentos_ignorados": stats["outros_movimentos_ignorados"],
        "registros_consolidados_por_dia": len(rows),
        "periodo_inicio": min(dates), "periodo_fim": max(dates),
        "politica": "SUBSTITUIR_FOTOGRAFIA_COMPLETA",
        "versao": VERSION,
        "mapeamento_colunas": maps,
    }
    return {"meta": meta, "rows": rows}


def _pack(imported: dict) -> dict:
    rows = imported["rows"]
    encoded = json.dumps([
        [r[k] for k in (
            "op", "codigo", "lote", "data", "tipo_movimento",
            "tes", "quantidade", "documento", "linha_origem",
        )] for r in rows
    ], ensure_ascii=False, separators=(",", ":")).encode()
    payload = base64.b64encode(gzip.compress(encoded, compresslevel=6, mtime=0)).decode()
    return {"formato": FORMAT, "meta": dict(imported["meta"]),
            "encoding": "gzip+base64", "payload": payload}


def _unpack(packed: dict) -> dict:
    if packed.get("formato") != FORMAT or packed.get("encoding") != "gzip+base64":
        raise ValueError("Fotografia OPS incompatível; faça uma nova importação.")
    data = json.loads(gzip.decompress(base64.b64decode(packed["payload"], validate=True)))
    keys = ("op", "codigo", "lote", "data", "tipo_movimento",
            "tes", "quantidade", "documento", "linha_origem")
    rows = [dict(zip(keys, row)) for row in data]
    if len(rows) != int(packed["meta"]["registros_consolidados_por_dia"]):
        raise ValueError("Fotografia OPS corrompida: quantidade de registros difere do manifesto.")
    return {"meta": packed["meta"], "rows": rows}


def read_meta() -> dict:
    response = requests.get(
        f"{db.supabase_url()}/rest/v1/fm_configuracoes",
        headers=db._headers(),
        params={"select": "meta:valor->meta,atualizado_em",
                "chave": f"eq.{KEY}", "limit": "1"},
        timeout=30,
    )
    db._raise(response)
    values = response.json() or []
    if not values:
        return {}
    return {**(values[0].get("meta") or {}),
            "atualizado_em": str(values[0].get("atualizado_em") or "")}


def load() -> dict:
    response = requests.get(
        f"{db.supabase_url()}/rest/v1/fm_configuracoes",
        headers=db._headers(),
        params={"select": "valor", "chave": f"eq.{KEY}", "limit": "1"},
        timeout=90,
    )
    db._raise(response)
    values = response.json() or []
    if not values:
        return {}
    return _unpack(values[0]["valor"])


def _record_key(row: dict) -> tuple:
    return tuple(str(row.get(field) or "") for field in (
        "op", "codigo", "lote", "data", "tipo_movimento", "tes",
    ))


def _rows_hash(rows: list[dict]) -> str:
    """Fingerprint determinístico da fotografia COMPLETA, não só do upload."""
    encoded = json.dumps(
        [[str(row.get(k) or "") for k in (
            "op", "codigo", "lote", "data", "tipo_movimento", "tes",
            "quantidade", "documento", "linha_origem",
        )] for row in rows],
        separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def plan_period_replace(parsed: dict, existing: dict | None = None, *,
                        replace_mode: str = "period") -> dict:
    """Simula substituição apenas entre a primeira e última data do arquivo.

    O período é inclusivo. As movimentações de fora são PRESERVADAS;
    as movimentações antigas DENTRO do período são substituídas por
    todas as linhas válidas do novo arquivo. Nunca soma fotografias.
    """
    if replace_mode not in ("period", "op"):
        raise ValueError("Modo de substituição OPS inválido.")
    incoming_meta = parsed.get("meta") or {}
    if incoming_meta.get("versao") != VERSION:
        raise ValueError("Leitura OPS com regras desatualizadas; reimporte a planilha.")
    fresh = parsed.get("rows") or []
    if not fresh:
        raise ValueError("Novo OPS sem movimentações válidas.")
    if not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r.get("data") or ""))
               for r in fresh):
        raise ValueError("A fonte OPS contém datas inválidas.")
    start, end = min(r["data"] for r in fresh), max(r["data"] for r in fresh)
    if (incoming_meta.get("periodo_inicio") != start
            or incoming_meta.get("periodo_fim") != end):
        raise ValueError("Datas do manifesto OPS divergentes dos registros.")
    old_source = existing or {}
    old_rows = old_source.get("rows") or []
    old_meta = old_source.get("meta") or {}
    if old_source and (old_meta.get("versao") != VERSION
                       or not isinstance(old_rows, list)):
        raise ValueError("Fonte OPS anterior incompatível. A base não será alterada.")

    selected_ops = {r["op"] for r in fresh}
    if replace_mode == "op":
        # O arquivo é a fotografia COMPLETA das OPs incluídas. Remove as
        # movimentações anteriores dessas OPs, independentemente da data,
        # mas preserva integralmente todas as demais OPs.
        retained = [r for r in old_rows if r["op"] not in selected_ops]
        replaced = [r for r in old_rows if r["op"] in selected_ops]
    else:
        retained = [r for r in old_rows if not start <= r["data"] <= end]
        replaced = [r for r in old_rows if start <= r["data"] <= end]
    # O mesmo registro não pode coexistir em dois intervalos ou duplicar
    # quantidades. Permite reprocessar o mesmo arquivo quantas vezes quiser.
    merged = sorted([*retained, *fresh], key=_record_key)
    if len({_record_key(r) for r in merged}) != len(merged):
        raise ValueError("OPS duplicado após união dos períodos. Gravação bloqueada.")
    if len(merged) != len(retained) + len(fresh):
        raise RuntimeError("Falha na conservação dos registros históricos.")
    if replace_mode == "op":
        if any(r["op"] in selected_ops for r in retained):
            raise RuntimeError("Movimentação preservada pertence a uma OP substituída.")
    elif any(start <= r["data"] <= end for r in retained):
        raise RuntimeError("Movimentação preservada pertence ao período substituído.")

    digest = _rows_hash(merged)
    previous_digest = _rows_hash(sorted(old_rows, key=_record_key)) if old_rows else ""
    changed = digest != previous_digest
    # O conteúdo é o controle de idempotência, não o nome nem o SHA do XLSX.
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest = list(old_meta.get("importacoes_periodo") or [])[-29:]
    new_manifest = {
        "inicio": start, "fim": end,
        "modo_substituicao": replace_mode,
        "ops_afetadas": len(selected_ops),
        "arquivo": incoming_meta.get("arquivo_nome") or "",
        "sha256_arquivo": incoming_meta.get("sha256") or "",
        "preservados": len(retained),
        "substituidos": len(replaced),
        "novos": len(fresh),
        "total_apos": len(merged),
        "executado_em": updated_at,
    }
    if changed:
        manifest.append(new_manifest)
    result_meta = {
        **incoming_meta,
        "arquivo_nome": incoming_meta.get("arquivo_nome") or "OPS",
        "sha256": digest,
        "sha256_ultimo_arquivo": incoming_meta.get("sha256") or "",
        "movimentos_validos": len(merged),
        "registros_consolidados_por_dia": len(merged),
        "movimentos_validos_ultimo_arquivo": int(
            incoming_meta.get("movimentos_validos") or 0
        ),
        "re1_999_reconhecidos": sum(
            1 for r in merged
            if r.get("tipo_movimento") == "RE1" and r.get("tes") == "999"
        ),
        "movimentos_sem_lote": sum(1 for r in merged if not r.get("lote")),
        "periodo_inicio": min(r["data"] for r in merged),
        "periodo_fim": max(r["data"] for r in merged),
        "politica": ("SUBSTITUIR_OPS_DO_ARQUIVO" if replace_mode == "op"
                    else "SUBSTITUIR_SOMENTE_PERIODO_INCLUSIVO"),
        "intervalo_ultima_importacao": {"inicio": start, "fim": end},
        "registros_preservados_ultima_importacao": len(retained),
        "registros_substituidos_ultima_importacao": len(replaced),
        "registros_novos_ultima_importacao": len(fresh),
        "importacoes_periodo": manifest,
    }
    if not changed and old_meta:
        result_meta = old_meta  # evitar alterar metadados em reenvio idêntico
    return {
        "candidate": {"meta": result_meta, "rows": merged},
        "impact": {
            "periodo_inicio": start, "periodo_fim": end,
            "modo_substituicao": replace_mode,
            "ops_afetadas": len(selected_ops),
            "historico_anterior": len(old_rows),
            "preservados": len(retained),
            "substituidos": len(replaced),
            "novos": len(fresh),
            "apos_substituicao": len(merged),
            "alterou": changed,
            "sha256_anterior": old_meta.get("sha256") or "",
            "alerta_reducao_no_periodo": (
                len(replaced) > 0 and len(fresh) < len(replaced) * 0.8
            ),
        },
    }


def save(parsed: dict, *, expected_previous_sha: str | None = None,
         replace_mode: str = "period") -> dict:
    """Atualiza o período inclusivo do arquivo com cópia de segurança.

    Carrega a versão MAIS RECENTE no banco no ato de salvar. Se a tela foi
    aberta antes de outra importação, interrompe em vez de sobrepor dados.
    A verificação extra anterior ao RPC reduz a janela de concorrência;
    o mecanismo legado de configuração é o único escritor efetivo.
    """
    current = load()
    previous = (current.get("meta") or {}).get("sha256") or ""
    if expected_previous_sha is not None and previous != expected_previous_sha:
        raise RuntimeError(
            "A fonte OPS mudou desde a prévia. Recarregue a página para "
            "recalcular os períodos antes de confirmar."
        )
    planned = plan_period_replace(parsed, current, replace_mode=replace_mode)
    if not planned["impact"]["alterou"]:
        return {"saved": False, "meta": current["meta"],
                "impact": planned["impact"]}
    # O backup é criado ANTES de qualquer modificação da fonte principal.
    # Se a gravação falhar, o histórico anterior permanece restaurável.
    if current:
        db.rpc(
            "fm_salvar_configuracao",
            {"p_chave": BACKUP_KEY, "p_valor": _pack(current)},
            timeout=120,
        )
    # Não prosseguir se outra operação atualizou a base enquanto
    # preparávamos o backup.
    latest = read_meta()
    if (latest.get("sha256") or "") != previous:
        raise RuntimeError(
            "Outra importação OPS alterou a fonte durante a gravação. "
            "Nada foi substituído; refaça a conferência da prévia."
        )
    candidate = planned["candidate"]
    db.rpc(
        "fm_salvar_configuracao",
        {"p_chave": KEY, "p_valor": _pack(candidate)},
        timeout=120,
    )
    actual = read_meta()
    if (actual.get("sha256") != candidate["meta"]["sha256"]
            or actual.get("versao") != VERSION):
        raise RuntimeError(
            "A gravação OPS não foi confirmada com a assinatura esperada."
        )
    return {"saved": True, "meta": actual, "impact": planned["impact"]}


def movements_as_of(records: list[dict], reference: str, *, ops: set[str]) -> tuple[list[dict], int]:
    """Evidências filtradas à data-base, sem filtrar por armazém inexistente no OPS."""
    result = []
    future = 0
    for row in records:
        if row["data"] > reference:
            future += 1
            continue
        if row["op"] not in ops:
            continue
        amount = mv.decimal(row["quantidade"])
        if not amount:
            continue
        result.append({
            "op": row["op"], "codigo": row["codigo"], "lote": lot(row["lote"]),
            "data": row["data"], "tes": row["tes"], "tipo_movimento": row["tipo_movimento"],
            "qtd_saida": str(max(amount, 0)), "qtd_entrada": str(max(-amount, 0)),
            "quantidade": str(amount), "natureza": "BAIXA / DEVOLUÇÃO",
            "ae_original": "OP" + row["op"], "documento": row.get("documento") or "",
            "armazem": "", "arquivo_origem": "RELATÓRIO OPS",
            "linha_origem": row.get("linha_origem", 0),
        })
    return result, future
