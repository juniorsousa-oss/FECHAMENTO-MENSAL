from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from zipfile import ZipFile

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import movements as mv


def record(**values):
    row = {
        "codigo": "00001000", "descricao": "MATERIAL DE TESTE", "um": "UN",
        "tipo": "MP", "grupo": "0000", "armazem": "S2", "tes": "520",
        "data": "2026-10-01", "documento": "DOC1", "qtd_saida": "2",
        "valor_saida": "10", "qtd_entrada": None, "valor_entrada": None,
        "ae_original": "CC600307", "arquivo_origem": "teste.xlsx",
        "linha_origem": 3, "arquivo_sha256": "a" * 64,
        "saldo_pos_lancamento": "20", "valor_saldo_pos_lancamento": "100",
    }
    row.update(values)
    return mv.clean_record(row)


def imported(rows, digest="a"):
    return {
        "meta": {
            "sha256": digest * 64, "arquivo_nome": digest + ".xlsx",
            "lancamentos": len(rows), "periodo_inicio": "2026-10-01",
            "periodo_fim": "2026-10-31",
        },
        "rows": rows,
    }


class MovementAnalysisTests(unittest.TestCase):
    def test_no_old_groups_even_for_sheets_copper_op_cc_or_material_ii(self):
        rows = [
            record(descricao="BARRA DE COBRE ELETROLÍTICO", ae_original="OP00001234567"),
            record(tipo="II", codigo="00002000", documento="II"),
            record(tipo="PA", codigo="00003000", documento="PA"),
            record(ae_original="CC123456", documento="CC"),
        ]
        frame = mv.build_model([imported(rows)])["frame"]
        self.assertEqual(len(frame), 4)
        self.assertTrue((frame["grupo_analise"] == "").all())
        self.assertTrue((frame["subgrupo_analise"] == "").all())
        self.assertTrue((frame["regra_classificacao"] == "").all())
        self.assertTrue((frame["motivo_classificacao"] == "").all())
        self.assertEqual(frame.iloc[0].op_identificada, "OP00001234567")
        self.assertEqual(frame.iloc[3].cc_identificado, "123456")

    def test_all_descriptions_exactly_equal_tes_catalog(self):
        codes = ["020", "040", "520", "550", "999", "815"]
        frame = mv.build_model([imported([
            record(tes=code, documento=code) for code in codes
        ])])["frame"]
        for code, description in zip(frame["tes"], frame["descricao_tes"]):
            self.assertEqual(description, mv.rules()["tes"].get(
                code, {}).get("descricao", "NI - TES não localizada no cadastro"))
        self.assertEqual(frame["valor_saida"].tolist(), [10.] * len(codes))

    def test_raw_entries_and_exits_define_totals_without_automatic_compensation(self):
        incoming = record(tes="499", ae_original="SEM OP", documento="TRANSF",
                          qtd_entrada="2", valor_entrada="10",
                          qtd_saida=None, valor_saida=None)
        outgoing = record(tes="999", ae_original="OP00001234567", documento="TRANSF")
        result = mv.build_model([imported([incoming, outgoing])])
        frame = result["frame"]
        self.assertEqual(len(frame), 2)
        self.assertEqual(len(mv.effective(frame)), 2)
        self.assertEqual(result["pares_enderecamento"], [])
        self.assertFalse(frame["enderecamento_compensado"].any())
        self.assertEqual(float(frame["valor_saida"].sum()), 10.0)
        self.assertEqual(float(frame["valor_entrada"].sum()), 10.0)

    def test_tes_summary_does_not_split_by_product_type_op_or_cc(self):
        rows = [
            record(tes="520", documento="D1", tipo="II"),
            record(tes="520", documento="D2", tipo="PA", ae_original="OP00001234567"),
            record(tes="520", documento="D3", tipo="MP", ae_original="CC30000"),
        ]
        frame = mv.build_model([imported(rows)])["frame"]
        groups = mv.summarize(frame, ["tes", "descricao_tes"])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups.iloc[0]["lancamentos"], 3)
        self.assertEqual(groups.iloc[0]["valor_saida"], 30.0)

    def test_repeat_aware_overlap_and_idempotence(self):
        row = record()
        first = imported([row, row])
        later = imported([record(arquivo_origem="ano.xlsx", linha_origem=20)], "b")
        merged, duplicates = mv.merge_imports([first, later, first])
        self.assertEqual(len(merged), 2)
        self.assertEqual(duplicates, 3)
        self.assertEqual(len({r["id_registro"] for r in merged}), 2)

    def test_source_value_direction_is_not_inferred_from_tes(self):
        rows = [
            record(tes="020", tipo="PA", qtd_saida=None, valor_saida=None,
                   qtd_entrada="2", valor_entrada="10"),
            record(tes="020", descricao="CHAPA ACO", documento="OUTRO"),
        ]
        frame = mv.build_model([imported(rows)])["frame"]
        self.assertEqual(frame.valor_entrada.tolist(), [10, 0])
        self.assertEqual(frame.valor_saida.tolist(), [0, 10])
        self.assertEqual(set(frame.grupo_analise), {""})

    def test_original_ae_and_values_round_trip(self):
        row = record(ae_original=" OP00001234567 ", valor_saida="-12.34")
        restored = mv.unpack_import(mv.pack_import(imported([row])))["rows"][0]
        self.assertEqual(restored["ae_original"], " OP00001234567 ")
        self.assertEqual(restored["valor_saida"], "-12.34")

    def test_missing_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Data"):
            record(data=None)

    def test_excel_three_sheets_with_collapsible_groups_ops_and_screen_columns(self):
        import kardex_group_config as groups
        row = record(tes="999", ae_original="OP00001234567", descricao="=NÃO É FÓRMULA")
        frame = mv.build_model([imported([row])])["frame"]
        cfg = groups.create_group(groups.empty(), "CONSUMO OP", known_tes={"999"})
        cfg = groups.assign_group(cfg, cfg["grupos"][0]["id"], ["999"], known_tes={"999"})
        output = mv.export_excel(frame, group_config=cfg)
        wb = openpyxl.load_workbook(io.BytesIO(output))
        self.assertEqual(wb.sheetnames, ["Grupos e TES", "Por OP", "Movimentações"])

        grouped = wb["Grupos e TES"]
        self.assertEqual(grouped["A1"].value, "Grupo / TES")
        self.assertEqual(grouped["A2"].value, "CONSUMO OP")
        self.assertEqual(grouped["A3"].value, "TES 999")
        self.assertEqual(grouped["B3"].value, "SAÍDA DE INVENTÁRIO/CONSUMO OP")
        self.assertTrue(grouped.row_dimensions[2].collapsed)
        self.assertEqual(grouped.row_dimensions[3].outlineLevel, 1)
        self.assertTrue(grouped.row_dimensions[3].hidden)
        self.assertFalse(grouped.sheet_properties.outlinePr.summaryBelow)
        self.assertEqual(grouped["A4"].value, "TOTAL GERAL")
        self.assertEqual(grouped["G4"].value, 10.0)

        op = wb["Por OP"]
        self.assertEqual(op["A2"].value, "OP00001234567")
        self.assertEqual(op["F2"].value, 1)
        self.assertEqual(op["I2"].value, 10.0)
        self.assertTrue(op.row_dimensions[2].collapsed)
        self.assertEqual(op.row_dimensions[3].outlineLevel, 1)
        self.assertTrue(op.row_dimensions[3].hidden)
        self.assertEqual(op["A3"].value, "00001000")
        self.assertEqual(op["C3"].value, "999")
        self.assertEqual(op["G3"].value, 2.0)
        self.assertEqual(op["I3"].value, 10.0)
        self.assertEqual(op["M3"].value, "OP00001234567")
        self.assertEqual(op["J3"].number_format, "dd/mm/yyyy")

        ledger = wb["Movimentações"]
        self.assertEqual([ledger.cell(1, i).value for i in range(1, 13)], [
            "Data", "Código", "Produto", "Armazém", "TES", "Grupo",
            "Entrada (R$)", "Saída (R$)", "AE original", "Descrição TES",
            "Tipo do material", "Documento",
        ])
        self.assertEqual(ledger["F2"].value, "CONSUMO OP")
        self.assertEqual(ledger["I2"].value, "OP00001234567")
        self.assertEqual(ledger["B2"].value, "00001000")
        self.assertEqual(ledger["C2"].data_type, "s")
        self.assertEqual(ledger["C2"].value, "=NÃO É FÓRMULA")
        self.assertEqual(ledger["A2"].number_format, "dd/mm/yyyy")
        self.assertEqual(ledger["A2"].value.date().isoformat(), "2026-10-01")
        self.assertEqual(ledger["H2"].value, 10)
        self.assertEqual(ledger["H2"].number_format, '#,##0.00;[Red](#,##0.00)')
        self.assertEqual(ledger.auto_filter.ref, "A1:L2")
        wb.close()

    def test_excel_groups_reconcile_and_op_only_expands_actual_exits(self):
        import kardex_group_config as groups
        rows = [
            record(tes="520", documento="B1", ae_original="OP00001234567", qtd_saida="2", valor_saida="10"),
            record(tes="999", documento="B2", ae_original="OP00001234567", qtd_saida="3", valor_saida="20"),
            record(tes="499", documento="E1", ae_original="OP00001234567",
                   qtd_saida=None, valor_saida=None, qtd_entrada="1", valor_entrada="5"),
            record(tes="540", documento="E2", ae_original="OP00007654321",
                   qtd_saida=None, valor_saida=None, qtd_entrada="3", valor_entrada="40"),
            record(tes="010", documento="SEMOP", ae_original="CC200",
                   qtd_saida=None, valor_saida=None, qtd_entrada="1", valor_entrada="12"),
        ]
        frame = mv.build_model([imported(rows)])["frame"]
        config = groups.create_group(groups.empty(), "REQUISIÇÕES", known_tes={"520","999","499","540","010"})
        config = groups.assign_group(config, config["grupos"][0]["id"], ["520", "999"],
                                     known_tes={"520","999","499","540","010"})
        config = groups.create_group(config, "ENTRADAS", known_tes={"520","999","499","540","010"})
        config = groups.assign_group(config, config["grupos"][1]["id"], ["499"],
                                     known_tes={"520","999","499","540","010"})
        wb = openpyxl.load_workbook(io.BytesIO(mv.export_excel(frame, group_config=config)))
        summary = wb["Grupos e TES"]
        self.assertEqual(summary["A2"].value, "REQUISIÇÕES")
        self.assertEqual(summary["G2"].value, 30)
        self.assertEqual(summary["A5"].value, "ENTRADAS")
        self.assertEqual(summary["F5"].value, 5)
        self.assertIn("SEM GRUPO", [summary.cell(r,1).value for r in range(2, summary.max_row+1)])
        last = summary.max_row
        self.assertEqual(summary.cell(last,1).value, "TOTAL GERAL")
        self.assertEqual(summary.cell(last,4).value, 5)
        self.assertEqual(summary.cell(last,6).value, 57)
        self.assertEqual(summary.cell(last,7).value, 30)
        self.assertEqual(summary.cell(last,8).value, 27)

        ops = wb["Por OP"]
        positions = {ops.cell(r, 1).value: r for r in range(2, ops.max_row + 1)
                     if ops.cell(r, 1).value in ("OP00001234567", "OP00007654321")}
        self.assertEqual(len(positions), 2)
        first_pos = positions["OP00001234567"]
        second_pos = positions["OP00007654321"]
        self.assertEqual(ops.cell(first_pos, 6).value, 2)
        self.assertEqual(ops.cell(first_pos, 9).value, 30)
        self.assertEqual(second_pos-first_pos, 3)  # summary plus two actual baixa records
        self.assertEqual(ops.cell(second_pos, 6).value, 0)
        self.assertEqual(ops.cell(second_pos + 1, 2).value, "SEM BAIXAS NO RECORTE")
        movements_sheet = wb["Movimentações"]
        self.assertEqual(len(list(movements_sheet.values)), 6)
        self.assertEqual(movements_sheet["F1"].value, "Grupo")
        observed = {
            movements_sheet.cell(r, 5).value: movements_sheet.cell(r, 6).value
            for r in range(2, movements_sheet.max_row + 1)
        }
        self.assertEqual(observed["520"], "REQUISIÇÕES")
        self.assertEqual(observed["999"], "REQUISIÇÕES")
        self.assertEqual(observed["499"], "ENTRADAS")
        self.assertEqual(observed["540"], "SEM GRUPO")
        self.assertEqual(observed["010"], "SEM GRUPO")
        self.assertEqual(
            sum(movements_sheet.cell(r, 8).value or 0
                for r in range(2, movements_sheet.max_row + 1)), 30
        )
        wb.close()

    def test_exported_history_reimports_without_derived_classification(self):
        model = mv.build_model([imported([record()])])
        zipped = mv.export_history(model)
        restored = mv.parse_report(zipped, "backup.zip")
        self.assertNotIn("grupo_analise", restored["rows"][0])
        self.assertEqual(restored["rows"][0]["ae_original"], "CC600307")
        merged, duplicates = mv.merge_imports([imported([record()]), restored])
        self.assertEqual((len(merged), duplicates), (1, 1))


if __name__ == "__main__":
    unittest.main()
