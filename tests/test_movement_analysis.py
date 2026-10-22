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

    def test_excel_preserves_original_ae_column_and_without_legacy_group_sheets(self):
        row = record(ae_original="OP00001234567", descricao="=NÃO É FÓRMULA")
        frame = mv.build_model([imported([row])])["frame"]
        output = mv.export_excel(frame)
        wb = openpyxl.load_workbook(io.BytesIO(output), read_only=True)
        self.assertEqual(wb.sheetnames, ["Por TES", "Mensal", "Por OP", "Movimentações"])
        sheet = wb["Movimentações"]
        self.assertEqual(sheet["AE1"].value, "AE original")
        self.assertEqual(sheet["AE2"].value, "OP00001234567")
        self.assertEqual(sheet["D1"].value, "Descrição TES")
        self.assertEqual(sheet["D2"].value, mv.rules()["tes"]["520"]["descricao"])
        self.assertNotEqual(sheet["W1"].value, "Tipo de TM")
        self.assertEqual(wb["Por TES"]["B1"].value, "Descrição TES")
        self.assertEqual(wb["Mensal"]["A2"].value, "10/2026")
        self.assertEqual(wb["Por OP"]["E2"].number_format, "dd/mm/yyyy")
        self.assertEqual(sheet["H2"].number_format, "dd/mm/yyyy")
        self.assertEqual(sheet["B2"].data_type, "s")
        self.assertEqual(sheet["H2"].value.date().isoformat(), "2026-10-01")
        wb.close()
        with ZipFile(io.BytesIO(output)) as archive:
            xml = archive.read("xl/worksheets/sheet4.xml").decode()
            self.assertNotIn('t="d"', xml)

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
