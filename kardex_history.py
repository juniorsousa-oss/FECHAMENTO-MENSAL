"""Monthly KARDEX revisions, independently scoped to each warehouse."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date, timedelta

VERSION = "2026-11-27.1"
POLICY = "MONTH_WAREHOUSE_V1"
INTERVAL_POLICY = "KARDEX_WAREHOUSE_INTERVAL_V1"
REPLACEMENT_POLICIES = {POLICY, INTERVAL_POLICY}


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
        if meta["politica"] not in REPLACEMENT_POLICIES:
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


def _days(start: str, end: str):
    current, last = date.fromisoformat(start), date.fromisoformat(end)
    while current <= last:
        yield current.isoformat()
        current += timedelta(days=1)


def replacement_days(meta):
    """O formato antigo possui o mês; o novo possui o intervalo real por armazém."""
    policy = meta.get("politica")
    if policy not in REPLACEMENT_POLICIES:
        return
    for scope in validate_scopes(meta.get("escopos") or []):
        start, end = scope["periodo_inicio"], scope["periodo_fim"]
        if policy == POLICY:
            first = date.fromisoformat(scope["competencia"] + "-01")
            after = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
            start, end = first.isoformat(), (after - timedelta(days=1)).isoformat()
        for day in _days(start, end):
            yield scope["armazem"], day


def day_owners(ordered):
    return {point: identifier
            for identifier, meta in ordered
            for point in replacement_days(meta)}


def _active_coverage(scope, owners, index):
    days = list(_days(scope["periodo_inicio"], scope["periodo_fim"]))
    segments = []
    start = stop = None
    for day in days:
        if owners.get((scope["armazem"], day), index) != index:
            if start:
                segments.append({**scope, "periodo_inicio": start, "periodo_fim": stop})
            start = stop = None
        else:
            start, stop = start or day, day
    if start:
        segments.append({**scope, "periodo_inicio": start, "periodo_fim": stop})
    return segments


def resolve(imports: list[dict]) -> dict:
    """A revisão mais recente possui somente os dias do escopo de sua política."""
    ordered = [p for _, p in sorted(enumerate(imports), key=lambda pair: (pair[1].get("_imported_at", ""), pair[0]))]
    scopes = [import_scopes(p) for p in ordered]
    owners = day_owners((i, p["meta"]) for i, p in enumerate(ordered))
    active, coverage, registry = [], [], []
    for index, imported in enumerate(ordered):
        meta = imported["meta"]
        valid = [part for scope in scopes[index] for part in _active_coverage(scope, owners, index)]
        rows = [r for r in imported["rows"] if owners.get((r["armazem"], r["data"]), index) == index]
        counts = Counter((r["armazem"], r["data"]) for r in rows)
        active.append({**imported, "rows": rows})
        for scope in valid:
            total = sum(counts[scope["armazem"], d] for d in _days(scope["periodo_inicio"], scope["periodo_fim"]))
            coverage.append({**scope, "arquivo_nome": meta["arquivo_nome"], "lancamentos": total,
                             "import_id": meta.get("import_id", meta["sha256"])})
        registry.append({"arquivo": meta["arquivo_nome"], "importado_em": imported.get("_imported_at", ""),
                         "armazens": sorted({s["armazem"] for s in scopes[index]}),
                         "competencias": sorted({s["competencia"] for s in scopes[index]}),
                         "lancamentos": int(meta["lancamentos"]), "lancamentos_ativos": len(rows),
                         "status": "VIGENTE" if valid == scopes[index] else "SUBSTITUÍDO" if not valid else "PARCIALMENTE SUBSTITUÍDO",
                         "escopos_ativos": valid, "import_id": meta.get("import_id", meta["sha256"])})
    return {"imports": active, "coverage": coverage, "registry": registry}


def merge_central_kardex(parts: dict, tokens: dict, *, current_month: str,
                         closed_months=()) -> dict:
    """Um único histórico Kardex, com cobertura e origem independentes por armazém."""
    warehouses = {"kardex_s2": "S2", "kardex_ep": "EP", "kardex_e2": "E2"}
    if set(parts) != set(warehouses) or set(tokens) != set(warehouses):
        raise ValueError("A base única requer Kardex S2, EP e E2. OPS é uma fonte separada.")
    if current_month in {str(m)[:7] for m in closed_months}:
        raise ValueError("A competência já está encerrada.")
    sources, rows, scopes = {}, [], []
    for key, warehouse in warehouses.items():
        item = parts[key]
        meta = item["meta"]
        if not tokens[key] or not meta.get("sha256") or not item["rows"]:
            raise ValueError("Fonte Kardex incompleta: " + warehouse)
        if {r["armazem"] for r in item["rows"]} != {warehouse}:
            raise ValueError("Armazém incompatível com a fonte: " + warehouse)
        if {r["data"][:7] for r in item["rows"]} != {current_month}:
            raise ValueError("O Kardex consolidado da Central aceita somente a competência aberta: "
                             + current_month)
        start, end = meta["periodo_inicio"], meta["periodo_fim"]
        if start[:7] != current_month or end[:7] != current_month:
            raise ValueError("Período incompatível com a competência aberta: " + warehouse)
        scopes.extend({"competencia": month, "armazem": warehouse, "periodo_inicio": a, "periodo_fim": b}
                      for month, a, b in month_ranges(start, end))
        rows.extend(item["rows"])
        sources[key] = {"armazem": warehouse, "token": tokens[key],
                        "arquivo_nome": meta["arquivo_nome"], "sha256": meta["sha256"],
                        "linhas": len(item["rows"]), "inicio": start, "fim": end}
    digest = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    start = min(s["periodo_inicio"] for s in scopes)
    end = max(s["periodo_fim"] for s in scopes)
    merged = prepare_import({
        "rows": rows,
        "meta": {"sha256": digest, "arquivo_nome": "Kardex consolidado — Central",
                 "periodo_inicio": start, "periodo_fim": end, "coberturas_arquivo": scopes,
                 "fontes_central": sources},
    }, start, end)
    merged["meta"]["politica"] = INTERVAL_POLICY
    merged["meta"]["import_id"] = hashlib.sha256((INTERVAL_POLICY + digest).encode()).hexdigest()
    return merged
