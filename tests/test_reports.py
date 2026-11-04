"""Regressões dos três relatórios e filtros, sem campos extras no Geral."""
from __future__ import annotations

from datetime import date
from io import BytesIO
import unittest
from unittest.mock import patch

import pandas as pd
from openpyxl import load_workbook

import reports


class ReportsTests(unittest.TestCase):
    def test_excel_quantities_use_general_without_trailing_comma(self):
        wb = reports._Excel()
        wb.sheet("Quantidades", ["Valor"], quantity={0})
        for value in (100, 100.0, 0, -2, 3.25):
            wb.add("Quantidades", [value])
        saved = load_workbook(BytesIO(wb.save()), read_only=True, data_only=True)
        try:
            values = list(saved.active.values)
            self.assertEqual([r[0] for r in values[1:]], [100, 100, 0, -2, 3.25])
            for number in range(2, 7):
                self.assertEqual(saved.active[f"A{number}"].number_format, "General")
        finally:
            saved.close()

    def test_prior_faturamento_filters_by_activity_without_extra_export_columns(self):
        model = {
            "as_of": "2026-10-31", "baixas_fonte": "OPS", "history_available": True,
            "ops": pd.DataFrame([
                {"op": "25027101001", "data_faturamento": "19/05/2026",
                 "divergencias": 0, "status_op": "NF EMITIDA"},
                {"op": "26000101001", "data_faturamento": "20/09/2026",
                 "divergencias": 0, "status_op": "NF EMITIDA"},
            ]),
            "items": pd.DataFrame([
                {"op": "25027101001", "codigo": "06050123", "tipo_material": "MP"},
                {"op": "26000101001", "codigo": "06050189", "tipo_material": "MP"},
            ]),
            "general": [
                {"op": "25027101001", "codigo": "06050123", "lote": "000001",
                 "necessaria": 1, "atendida": 1,
                 "descricao": "MATERIAL A", "responsavel_conferencia": "CONF",
                 "separacao": "2026-08-17", "conferencia": "2026-08-20"},
                {"op": "26000101001", "codigo": "06050189", "lote": "000001",
                 "necessaria": 3, "atendida": 3,
                 "descricao": "MATERIAL B", "responsavel_conferencia": "",
                 "separacao": "2026-09-10", "conferencia": ""},
            ],
            "movements": [],
        }
        start, end = date(2026, 8, 1), date(2026, 10, 31)
        diagnosis = reports.selection_diagnostics(model, start, end)
        self.assertEqual(diagnosis["selected"], {"26000101001"})
        self.assertEqual(reports.issue_rows(model, start, end)[0][0], "26000101001")
        old = reports.issue_rows(model, start, end, include_activity=True)
        self.assertEqual({r[0] for r in old}, {"25027101001", "26000101001"})
        self.assertEqual(len(reports.OP_COLUMNS), 25)
        self.assertEqual(reports.OP_COLUMNS[:12], [
            "OP", "Produtos totais", "Produtos separados",
            "Produtos conferidos", "Produtos baixados", "Produtos com alerta",
            "Cliente", "Condição", "Nota fiscal", "Faturamento", "Pátio",
            "Status da OP",
        ])
        self.assertEqual(reports.OP_COLUMNS[12:], [
            "Produto", "Descrição", "Lotes", "Qtd necessária",
            "Qtd separada", "Qtd conferida", "Qtd baixada",
            "Qtd pendente baixa", "Valor previsto da baixa (R$)",
            "Saldo no lote conferido", "Saldo G9-PROD",
            "Outros endereços", "Resultado",
        ])
        self.assertNotIn("Separações inferidas da conferência", reports.OP_COLUMNS)
        self.assertIn("Valor previsto da baixa (R$)", reports.OP_COLUMNS)
        self.assertNotIn("Data última atividade no período", reports.OP_COLUMNS)

    def test_october_billing_only_excludes_ni_and_other_months(self):
        """Relatório de outubro sem movimentações inclui SÓ faturamento em outubro."""
        info = [
            ("26001000001", "10/10/2026", ""),       # faturado outubro
            ("26001000002", "31/10/2026", ""),       # faturado outubro no limite
            ("26001000003", "NI", "2026-10-14"),     # movimentação outubro, sem NF
            ("26001000004", "N/I", "2026-10-15"),    # outra forma de NI
            ("26001000005", "", "2026-10-16"),       # faturamento vazio
            ("26001000006", "19/09/2026", "2026-10-20"), # NF anterior, atividade outubro
            ("26001000007", "01/11/2026", "2026-10-21"), # NF posterior, atividade outubro
            ("26001000008", "29/10/2026", None),     # NF outubro sem atividade
            ("26001000009", "DATA INVALIDA", "2026-10-25"),
        ]
        model = {
            "as_of": "2026-10-31",
            "baixas_fonte": "OPS", "history_available": True,
            "ops": pd.DataFrame([
                {"op": op, "data_faturamento": faturamento,
                 "status_op": "NF EMITIDA", "itens": 1,
                 "separados": 1, "conferidos": 1,
                 "baixados": 1, "divergencias": 0}
                for op, faturamento, _ in info
            ]),
            "items": pd.DataFrame([
                {"op": op, "codigo": "06050080", "lotes": "000000000",
                 "descricao": "MATERIAL", "necessaria": 1, "separada": 1,
                 "conferida": 1, "baixada": 1, "pendente": 0,
                 "status": "PRODUTO CONSUMIDO", "divergente": False}
                for op, _, _ in info
            ]),
            "general": [
                {"op": op, "separacao": activity, "conferencia": None}
                for op, _, activity in info if activity
            ],
            "movements": [],
        }
        start, end = date(2026, 10, 1), date(2026, 10, 31)
        only_billing = {"26001000001", "26001000002", "26001000008"}
        diagnosis = reports.selection_diagnostics(model, start, end)
        self.assertEqual(diagnosis["selected"], only_billing)
        self.assertEqual(len(diagnosis["excluded_missing_billing"]), 4)
        self.assertEqual(len(diagnosis["excluded_outside_billing"]), 2)
        self.assertEqual({r[0] for r in reports.issue_rows(model, start, end)},
                         only_billing)
        wb = load_workbook(
            BytesIO(reports.export_issues(model, start, end)),
            read_only=True, data_only=True,
        )
        try:
            rows = list(wb.active.values)
            self.assertEqual(len(rows), 4)
            self.assertEqual({r[0] for r in rows[1:]}, only_billing)
            self.assertEqual(len(rows[0]), 25)
        finally:
            wb.close()
        with_activity = reports.selection_diagnostics(
            model, start, end, include_activity=True)
        self.assertEqual(
            with_activity["selected"],
            {op for op, _, _ in info},
        )
        self.assertEqual(len(with_activity["added_by_activity"]), 6)
        self.assertEqual(
            {r[0] for r in reports.issue_rows(
                model, start, end, include_activity=True)},
            {op for op, _, _ in info},
        )

    def test_reports_ui_shows_explicit_movement_checkbox_default_false(self):
        from pathlib import Path
        content = (Path(__file__).resolve().parents[1] / "reports_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("fm_reports_include_activity", content)
        self.assertIn("INCLUIR TAMBÉM OPs COM MOVIMENTAÇÃO NO PERÍODO", content)
        self.assertIn("value=False, key=\"fm_reports_include_activity\"", content)
        self.assertNotIn("fm_reports_prior_billing", content)

    def test_excel_mirrors_expanded_op_and_colors_only_real_alerts(self):
        """Repetir cabeçalho e as 12 colunas expandidas; sem amarelo para OK."""
        model = {
            "as_of": "2026-10-31",
            "baixas_fonte": "OPS", "history_available": True,
            "ops": pd.DataFrame([{
                "op": "26015901001", "itens": 2, "separados": 2,
                "conferidos": 2, "baixados": 1, "divergencias": 1,
                "cliente": "SERRA VERDE", "condicao": "FINALIZADO",
                "nota_fiscal": "10255", "data_faturamento": "16/10/2026",
                "dias_patio": 18, "status_op": "FINALIZADO EM PÁTIO",
            }]),
            "catalog_prices": {"00041468": 21.76, "00000196": 21.76},
            "items": pd.DataFrame([
                {"op": "26015901001", "codigo": "00000196",
                 "descricao": "CABO DE CONEXAO", "lotes": "058405",
                 "necessaria": 6, "separada": 6, "conferida": 6,
                 "baixada": 6, "pendente": 0,
                 "saldo": 45, "saldo_g9_prod": 41,
                 "outros_enderecos": "", "status": "PRODUTO CONSUMIDO",
                 "historico_incompleto": True, "divergente": False,
                 "tipo_material": "MP"},
                {"op": "26015901001", "codigo": "00041468",
                 "descricao": "LONGARINA", "lotes": "062285, 062984",
                 "necessaria": 24, "separada": 12, "conferida": 10,
                 "baixada": 10, "pendente": 2,
                 "saldo": 0, "saldo_g9_prod": 0,
                 "outros_enderecos": "S2/G9-SEPA",
                 "status": "PRODUTO NÃO CONSUMIDO SEM SALDO PARA CONSUMO",
                 "historico_incompleto": False, "divergente": True,
                 "tipo_material": "MP"},
            ]),
        }
        records = reports.issue_detail_rows(model, {"26015901001"})
        self.assertEqual(len(records), 2)
        self.assertFalse(records[0][1])
        self.assertTrue(records[1][1])
        self.assertEqual(len(records[0][0]), 25)
        self.assertIsNone(records[0][0][20])
        self.assertEqual(records[1][0][20], 43.52)
        self.assertEqual(records[1][0][19], 2)
        self.assertEqual(records[0][0][:12], records[1][0][:12])
        self.assertEqual(records[0][0][0], "26015901001")
        self.assertEqual(records[0][0][12], "00000196")
        self.assertEqual(records[0][0][-1], "PRODUTO CONSUMIDO")

        data = reports.export_issues(model)
        excel = load_workbook(BytesIO(data), data_only=True)
        try:
            self.assertEqual(excel.sheetnames, ["Conferência de Baixas"])
            ws = excel.active
            self.assertEqual(ws.max_column, 25)
            self.assertEqual(ws.max_row, 3)
            self.assertEqual([c.value for c in ws[1]], reports.OP_COLUMNS)
            # O Excel representa string vazia como célula vazia (None).
            self.assertEqual([c.value for c in ws[2]], [
                None if value == "" else value for value in records[0][0]
            ])
            self.assertEqual([c.value for c in ws[3]], [
                None if value == "" else value for value in records[1][0]
            ])
            self.assertIsNone(ws["Y2"].fill.patternType)
            self.assertEqual(ws["Y3"].fill.patternType, "solid")
            self.assertTrue(ws["Y3"].fill.fgColor.rgb.endswith("FDE8E8"))
            self.assertEqual(ws["U3"].value, 43.52)
            self.assertIn("0.00", ws["U3"].number_format)
            self.assertIsNone(ws["U2"].value)
            self.assertEqual(ws["M2"].number_format, "General")
            self.assertEqual(ws["T3"].number_format, "General")
            self.assertEqual(ws.freeze_panes, "A2")
            self.assertEqual(ws.auto_filter.ref, "A1:Y3")
        finally:
            excel.close()

    def test_expected_value_matches_validated_r3_example(self):
        sample = {
            "as_of": "2026-10-31", "baixas_fonte": "OPS",
            "history_available": True,
            "catalog_prices": {"00703783": 21.76},
            "ops": pd.DataFrame([{
                "op": "26010006005", "itens": 1, "separados": 1,
                "conferidos": 1, "baixados": 0, "divergencias": 1,
                "data_faturamento": "30/09/2026",
            }]),
            "items": pd.DataFrame([{
                "op": "26010006005", "codigo": "00703783",
                "descricao": "FUSÍVEL NH", "lotes": "000000000",
                "necessaria": 3, "separada": 3, "conferida": 3,
                "baixada": 0, "pendente": 3, "divergente": True,
                "status": "PRODUTO NÃO CONSUMIDO COM SALDO NA PRODUÇÃO",
            }]),
        }
        row = reports.issue_rows(sample)[0]
        self.assertEqual(row[16], 3)  # Qtd separada
        self.assertEqual(row[17], 3)  # Qtd conferida
        self.assertEqual(row[19], 3)  # Qtd pendente baixa
        self.assertEqual(row[20], 65.28)  # CADASTROS 21,76 x 3 = R$65,28
        sample["catalog_prices"] = {}
        self.assertIsNone(reports.issue_rows(sample)[0][20])
        sample["catalog_prices"] = {"00703783": 21.76}
        sample["items"]["divergente"] = False
        self.assertIsNone(reports.issue_rows(sample)[0][20])

    def test_validated_r3_october_op_with_no_october_activity_is_included(self):
        # R3 continha 26015901001 / 00705997, NF em 16/10/2026.
        # O R8 baseado em atividade a excluía mesmo com faturamento no mês.
        model = {
            "as_of": "2026-10-31",
            "baixas_fonte": "OPS", "history_available": True,
            "catalog_prices": {"00705997": 40.62},
            "ops": pd.DataFrame([{
                "op": "26015901001", "data_faturamento": "16/10/2026",
                "itens": 17, "separados": 17, "conferidos": 17,
                "baixados": 16, "divergencias": 1,
            }]),
            "items": pd.DataFrame([{
                "op": "26015901001", "codigo": "00705997",
                "descricao": "CHAVE FIM DE CURSO COM SELETOR ROTATIVO",
                "lotes": "061463", "necessaria": 13,
                "separada": 13, "conferida": 13,
                "baixada": 10, "pendente": 3,
                "status": "PRODUTO NÃO CONSUMIDO COM SALDO NA PRODUÇÃO",
                "divergente": True,
            }]),
            "general": [],  # nenhuma atividade entre as datas filtradas
            "movements": [],
        }
        filtered = reports.issue_rows(
            model, date(2026, 10, 1), date(2026, 10, 31)
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0][0], "26015901001")
        self.assertEqual(filtered[0][12], "00705997")
        self.assertEqual(filtered[0][20], 121.86)

    def test_future_activity_beyond_mes_snapshot_is_excluded(self):
        model = {
            "as_of": "2026-10-21", "baixas_fonte": "OPS",
            "history_available": True,
            "ops": pd.DataFrame([{"op": "26000101001", "data_faturamento": "NI"}]),
            "general": [{
                "op": "26000101001", "codigo": "06050123", "lote": "000001",
                "necessaria": 1, "atendida": 1, "descricao": "MATERIAL",
                "responsavel_conferencia": "CONF",
                "separacao": "2026-11-02", "conferencia": "2026-11-02",
            }],
            "movements": [],
        }
        self.assertFalse(reports.issue_rows(
            model, date(2026, 8, 1), date(2026, 11, 3)))

    def test_stock_workbook_has_four_tabs_and_no_fake_initial_balance(self):
        entries, imports = [], []
        for month, total in ((8, 100.0), (9, 110.0), (10, 120.0)):
            day = date(2026, month, 1).isoformat()
            imports.append({"competencia": day, "status": "VALIDO",
                            "preview": month == 10})
            entries.extend([
                {"competencia": day, "dimensao": "TOTAL",
                 "chave": "TOTAL", "valor_total": total},
                {"competencia": day, "dimensao": "ARMZ",
                 "chave": "ARMZ:S2", "valor_total": total},
                {"competencia": day, "dimensao": "TP",
                 "chave": "TP:MP", "valor_total": total},
            ])
        found = reports.stock_data(entries, imports,
                                   date(2026, 9, 15), date(2026, 10, 20))
        self.assertEqual(len(found["Evolução Mensal"]), 2)
        self.assertEqual(found["Evolução Mensal"][0][1:4], [100.0, 110.0, 10.0])
        self.assertEqual(found["Evolução Mensal"][1][-1], "PRÉVIA")
        wb = load_workbook(BytesIO(reports.export_stock(entries, imports)),
                           read_only=True, data_only=True)
        try:
            self.assertEqual(wb.sheetnames, [
                "Resumo Geral", "Por Armazém", "Por Tipo", "Evolução Mensal"])
            self.assertIsNone(list(wb["Evolução Mensal"].values)[1][1])
        finally:
            wb.close()

    def test_kardex_filters_do_not_mutate_original_frame(self):
        frame = pd.DataFrame([
            {"data": "2026-10-03", "armazem": "S2", "tipo": "II", "tes": "520"},
            {"data": "2026-10-05", "armazem": "EP", "tipo": "EP", "tes": "520"},
            {"data": "2026-09-30", "armazem": "S2", "tipo": "MP", "tes": "020"},
        ])
        filtered = reports.filtered_kardex(
            frame, date(2026, 10, 1), date(2026, 10, 31),
            warehouses={"S2"}, types={"II"}, groups={"520"},
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(len(frame), 3)
        with patch("movements.export_excel", return_value=b"x") as excel:
            self.assertEqual(reports.export_kardex(filtered, {},
                                                   summary_only=True), b"x")
            self.assertTrue(excel.call_args.kwargs["summary_only"])


if __name__ == "__main__":
    unittest.main()
