"""Garante a exportação de todas as contagens, inclusive sem divergência."""
from __future__ import annotations

import ast
import io
from datetime import date
from pathlib import Path

import pandas as pd

source = Path(__file__).resolve().parents[1] / "streamlit_app.py"
parsed = ast.parse(source.read_text(encoding="utf-8"))
func = next(
    node for node in parsed.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "build_cb_protheus_movement_report"
)
scope = {
    "pd": pd,
    "io": io,
    "date": date,
    "month_label": lambda _: "OUTUBRO/2026",
}
exec(compile(ast.Module(body=[func], type_ignores=[]), str(source), "exec"), scope)
export = scope["build_cb_protheus_movement_report"]

base = {
    "categoria": "CHAPA",
    "descricao": "Material de teste",
    "um": "KG",
    "saldo_fechamento": 20,
    "saldo_atual": 20,
    "saldo_base_ajuste": 20,
    "base_origem": "FECHAMENTO",
    "custo_unitario": 10,
    "contagem_assumida_zero": False,
}
items = [
    {**base, "codigo": "A", "fisico": 20, "diferenca_qtd": 0, "previsao_valor": 0},
    {**base, "codigo": "B", "fisico": 23, "diferenca_qtd": 3, "previsao_valor": 30},
    {**base, "codigo": "C", "fisico": 18, "diferenca_qtd": -2, "previsao_valor": -20},
]
frame = pd.read_excel(io.BytesIO(export(items, date(2026, 10, 1))))
frame["CÓDIGO"] = frame["CÓDIGO"].astype(str)
by_code = frame.set_index("CÓDIGO")

assert len(frame) == 3, frame
assert by_code.loc["A", "AÇÃO PROTHEUS"] == "SEM MOVIMENTAÇÃO"
assert by_code.loc["A", "QUANTIDADE PROTHEUS"] == 0
assert by_code.loc["A", "SITUAÇÃO CONTAGEM"] == "CONFERIDO"
assert by_code.loc["A", "FÍSICO"] == 20
assert by_code.loc["B", "AÇÃO PROTHEUS"] == "INSERIR"
assert by_code.loc["B", "QUANTIDADE PROTHEUS"] == 3
assert by_code.loc["C", "AÇÃO PROTHEUS"] == "BAIXAR"
assert by_code.loc["C", "QUANTIDADE PROTHEUS"] == 2

# As contagens válidas e o saldo zero devem chegar à fotografia arquivada.
content = source.read_text(encoding="utf-8")
assert 'cb_report_snapshot = movement_comparison[' in content
assert 'movement_comparison["Físico"].notna()' in content
assert '_finalization_snapshot = cb_report_snapshot.copy()' in content
assert '_conferidos = _finalization_snapshot["Status"].eq("CONFERIDO")' in content
assert '"Diferença Qtd", "Diferença R$"' in content

schema = (source.parent / "supabase_schema.sql").read_text(encoding="utf-8")
assert "count(*) filter (where abs(coalesce(diferenca_qtd, 0)) > 1e-9)" in schema
# Contagens de competências antigas são recuperadas sem alterar o
# histórico de ajustes e sem inventar os saldos que não foram arquivados.
legacy_node = next(
    node for node in parsed.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "supplement_cb_historical_counts"
)
scope["normalize_code"] = lambda v: str(v or "").strip()
exec(compile(ast.Module(body=[legacy_node], type_ignores=[]), str(source), "exec"), scope)
merge = scope["supplement_cb_historical_counts"]
previous = [{**base, "codigo": "A", "fisico": 20, "diferenca_qtd": 2}]
counts = [
    {"codigo": "A", "fonte": "INTERNO_MANUAL", "quantidade_fisica": 20},
    {"codigo": "B", "fonte": "INTERNO_EXCEL", "quantidade_fisica": 4},
    {"codigo": "B", "fonte": "INTERNO_MANUAL", "quantidade_fisica": 5},
    {"codigo": "C", "fonte": "INTERNO_EXCEL", "quantidade_fisica": 7},
]
legacy = merge(
    previous, counts,
    [{"codigo": "C", "ativo": True}],
    [{"codigo": "B", "descricao": "Produto B", "categoria": "BARRA DE COBRE"}],
)
assert len(legacy) == 2, legacy
extra = next(item for item in legacy if item["codigo"] == "B")
assert extra["fisico"] == 5, extra
assert extra["saldo_fechamento"] is None
assert extra["diferenca_qtd"] == 0
assert "HISTÓRICA" in extra["situacao_contagem"]
legacy_report = pd.read_excel(io.BytesIO(export(legacy, date(2026, 9, 1))))
assert len(legacy_report) == 2
legacy_row = legacy_report.loc[legacy_report["CÓDIGO"] == "B"].iloc[0]
assert legacy_row["AÇÃO PROTHEUS"] == "SEM MOVIMENTAÇÃO"
assert pd.isna(legacy_row["SALDO FECHAMENTO"])
assert legacy_row["FÍSICO"] == 5

print("FECHAMENTO_RELATORIO_TODAS_CONTAGENS_OK")
