"""Consolidação somente leitura das fontes da Gestão de API."""
from __future__ import annotations

import gzip
import io
import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable

FORMAT = "SETTA_FECHAMENTO_MENSAL_V1"
SOURCES = ("ops", "kardex_s2", "kardex_ep", "kardex_e2")
SELECT_META = ("arquivo_nome", "sha256", "periodo_inicio", "periodo_fim")


def compile_preview(
    destination: str | Path,
    *,
    sources: dict,
    load_parsed: Callable,
    verify_current: Callable,
    max_bytes: int | None = None,
) -> dict:
    """Compila um JSON versionado, sem escrever em históricos ou no Supabase.

    O destino só é substituído depois de conferir todas as versões novamente.
    Carrega uma fonte por vez, sem juntar os registros de todos os armazéns em RAM.
    """
    versions = {}
    for key in SOURCES:
        entry = sources.get(key) or {}
        token = entry.get("token")
        if not entry.get("current") or not isinstance(token, str) or not re.fullmatch(r"v[1-9]\d*\|[^|]+", token):
            raise ValueError(f"Fonte pendente ou sem versão válida: {key}.")
        versions[key] = token

    destination = Path(destination)
    temporary = None
    counts = {}
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    try:
        # Arquivo atômico no mesmo sistema de arquivos; um lote recusado
        # não apaga nem substitui a última cópia válida.
        with NamedTemporaryFile(dir=destination.parent, delete=False) as raw:
            temporary = raw.name
            with gzip.GzipFile(fileobj=raw, filename="", mode="wb", mtime=0) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8") as out:
                    out.write('{"format":')
                    out.write(encoder.encode(FORMAT))
                    out.write(',"sources":{')
                    for i, (key, token) in enumerate(versions.items()):
                        parsed = load_parsed(key, token)
                        rows, meta = parsed["rows"], parsed["meta"]
                        if not rows or any(not meta.get(field) for field in SELECT_META):
                            raise ValueError(f"Fonte sem linhas ou metadados necessários: {key}.")
                        counts[key] = len(rows)
                        provenance = {
                            "source_token": token,
                            "row_count": counts[key],
                            **{field: meta[field] for field in SELECT_META},
                        }
                        if i:
                            out.write(",")
                        out.write(encoder.encode(key))
                        out.write(':{"metadata":')
                        out.write(encoder.encode(provenance))
                        out.write(',"rows":[')
                        for index, row in enumerate(rows):
                            if index:
                                out.write(",")
                            out.write(encoder.encode(row))
                        out.write("]}")
                        del parsed, rows, meta
                    out.write("}}")
        if max_bytes is not None and Path(temporary).stat().st_size > max_bytes:
            raise ValueError("Relatório consolidado acima do limite de download do app.")
        for key, token in versions.items():
            verify_current(key, token)
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)
    return counts
