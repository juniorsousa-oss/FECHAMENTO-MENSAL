"""Monthly KARDEX revisions, independently scoped to each warehouse."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date, timedelta

VERSION = "2026-10-21.2"
POLICY = "MONTH_WAREHOUSE_V1"


def month_ranges(start: str, end: str):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last:
        raise ValueError("O início do período deve ser anterior ao fim.")
    current = first.replace(day=1)
    while current <= last:
        following = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
        yield current.isoformat()[:7], max(first, current).isoformat(), min(last, following - timedelta(days=1)).isoformat()
        current = following


def validate_scopes(values: list[dict]) -> list[dict]:
    scopes, seen = [], set()
    for value in values:
        month = str(value.get("competencia") or "")
        warehouse = str(value.get("armazem") or "").strip()
        start, end = str(value.get("periodo_inicio") or ""), str(value.get("periodo_fim") or "")
        date.fromisoformat(month + "-01")
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if not warehouse or start[:7] != month or end[:7] != month or first > last:
            raise ValueError("Competência, armazém ou cobertura inválida no KARDEX.")
        key = (month, warehouse, start, end)
        if key in seen:
            continue
        seen.add(key)
        scopes.append({"competencia": month, "armazem": warehouse, "periodo_inicio": start, "periodo_fim": end})
    if not scopes:
        raise ValueError("O KARDEX não informa competências e armazéns para importação.")
    return sorted(scopes, key=lambda s: (s["competencia"], s["armazem"]))


def import_scopes(imported: dict) -> list[dict]:
    meta, rows = imported["meta"], imported["rows"]
    if meta.get("politica"):
        if meta["politica"] != POLICY:
            raise ValueError("Política de importação KARDEX não reconhecida. Atualize o app.")
        return validate_scopes(meta.get("escopos") or [])
    warehouses = sorted({str(r["armazem"]) for r in rows})
    start = min([meta["periodo_inicio"]] + [r["data"] for r in rows])
    end = max([meta["periodo_fim"]] + [r["data"] for r in rows])
    return [{"competencia": month, "armazem": warehouse, "periodo_inicio": start, "periodo_fim": end}
            for month, start, end in month_ranges(start, end)
            for warehouse in warehouses]


def prepare_import(parsed: dict, start: str | None = None, end: str | None = None) -> dict:
    """A replacement owns whole months; its coverage ends at the supplied extraction date."""
    meta, rows = dict(parsed["meta"]), parsed["rows"]
    start = start or meta["periodo_inicio"]
    end = end or meta["periodo_fim"]
    restored = meta.get("coberturas_arquivo")
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first.day != 1 and not restored:
        raise ValueError("Para substituir um mês, envie o KARDEX completo desde o primeiro dia. Confira o início do relatório.")
    if first > last:
        raise ValueError("O início do período deve ser anterior ao fim.")
    if any(not start <= r["data"] <= end for r in rows):
        raise ValueError("Existem movimentações fora do período informado. Nenhum registro foi substituído.")
    if restored:
        scopes = validate_scopes(restored)
        if start != meta["periodo_inicio"] or end != meta["periodo_fim"]:
            raise ValueError("A restauração usa as coberturas registradas na base histórica, sem alterar seu período.")
    else:
        warehouses = sorted({r["armazem"] for r in rows})
        scopes = validate_scopes([{"competencia": month, "armazem": warehouse, "periodo_inicio": begin, "periodo_fim": finish}
                                  for month, begin, finish in month_ranges(start, end) for warehouse in warehouses])
    if any(not any(s["competencia"] == r["data"][:7] and s["armazem"] == r["armazem"]
                   and s["periodo_inicio"] <= r["data"] <= s["periodo_fim"] for s in scopes) for r in rows):
        raise ValueError("O arquivo contém registros fora das competências e armazéns declarados.")
    identity = json.dumps([POLICY, meta["sha256"], scopes], sort_keys=True, separators=(",", ":"))
    meta.update(politica=POLICY, escopos=scopes, periodo_inicio=start, periodo_fim=end,
                import_id=hashlib.sha256(identity.encode()).hexdigest(), lancamentos=len(rows),
                armazens=sorted({s["armazem"] for s in scopes}), competencias=sorted({s["competencia"] for s in scopes}))
    return {"meta": meta, "rows": rows}


def validate_batch(imports: list[dict]):
    used = {}
    for imported in imports:
        for key in {(s["competencia"], s["armazem"]) for s in import_scopes(imported)}:
            if key in used:
                raise ValueError(f"Dois arquivos cobrem {key[1]} / {key[0]}. Importe uma única versão completa por mês e armazém.")
            used[key] = imported["meta"]["arquivo_nome"]


def resolve(imports: list[dict]) -> dict:
    """The last committed replacement wins; legacy append-only reports keep their deduplication."""
    ordered = [p for _, p in sorted(enumerate(imports), key=lambda pair: (pair[1].get("_imported_at", ""), pair[0]))]
    scopes = [import_scopes(p) for p in ordered]
    owners = {}
    for index, imported in enumerate(ordered):
        if imported["meta"].get("politica") == POLICY:
            for scope in scopes[index]:
                owners[scope["competencia"], scope["armazem"]] = index
    active, coverage, registry = [], [], []
    for index, imported in enumerate(ordered):
        meta = imported["meta"]
        valid = [s for s in scopes[index] if owners.get((s["competencia"], s["armazem"]), index) == index]
        allowed = {(s["competencia"], s["armazem"]) for s in valid}
        rows = [r for r in imported["rows"] if (r["data"][:7], r["armazem"]) in allowed]
        counts = Counter((r["data"][:7], r["armazem"]) for r in rows)
        active.append({**imported, "rows": rows})
        for scope in valid:
            coverage.append({**scope, "arquivo_nome": meta["arquivo_nome"],
                             "lancamentos": counts[scope["competencia"], scope["armazem"]],
                             "import_id": meta.get("import_id", meta["sha256"])})
        registry.append({"arquivo": meta["arquivo_nome"], "importado_em": imported.get("_imported_at", ""),
                         "armazens": sorted({s["armazem"] for s in scopes[index]}),
                         "competencias": sorted({s["competencia"] for s in scopes[index]}),
                         "lancamentos": int(meta["lancamentos"]), "lancamentos_ativos": len(rows),
                         "status": "VIGENTE" if len(valid) == len(scopes[index]) else "SUBSTITUÍDO" if not valid else "PARCIALMENTE SUBSTITUÍDO",
                         "escopos_ativos": valid, "import_id": meta.get("import_id", meta["sha256"])})
    return {"imports": active, "coverage": coverage, "registry": registry}
