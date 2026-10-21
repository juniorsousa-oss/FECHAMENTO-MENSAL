from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from zipfile import ZipFile

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import movements as mv


def record(**values):
    row = {"codigo": "00001000", "descricao": "MATERIAL DE TESTE", "um": "UN", "tipo": "MP", "grupo": "0000",
           "armazem": "S2", "tes": "520", "data": "2026-10-01", "documento": "DOC1", "qtd_saida": "2",
           "valor_saida": "10", "qtd_entrada": None, "valor_entrada": None, "ae_original": "CC600307",
           "arquivo_origem": "teste.xlsx", "linha_origem": 3, "arquivo_sha256": "a"*64,
           "saldo_pos_lancamento": "20", "valor_saldo_pos_lancamento": "100"}
    row.update(values)
    return mv.clean_record(row)


def imported(rows, digest="a"):
    return {"meta": {"sha256": digest*64, "arquivo_nome": digest+".xlsx", "lancamentos": len(rows),
                     "periodo_inicio": "2026-10-01", "periodo_fim": "2026-10-31"}, "rows": rows}


class MovementAnalysisTests(unittest.TestCase):
    def test_specific_material_precedes_op_and_consumption(self):
        rows = [record(descricao="BARRA DE COBRE ELETROLÍTICO 10 MM", ae_original="OP00001234567"),
                record(codigo="00002000", descricao="CHAPA POLICARBONATO", tipo="II", documento="DOC2")]
        frame = mv.build_model([imported(rows)])["frame"]
        self.assertEqual(set(frame.regra_classificacao), {mv.CLOSING_RULE})
        self.assertEqual(set(frame.grupo_analise), {mv.FLOW})
        self.assertEqual(frame.iloc[0].op_identificada, "OP00001234567")

    def test_confirmed_tes_subgroups_and_production_order_description(self):
        rows = [record(tes="040", documento="DEVOLUCAO"),
                record(tes="550", documento="GARANTIA"),
                record(tes="999", documento="CONSUMO")]
        frame = mv.build_model([imported(rows)])["frame"]
        self.assertEqual(frame["grupo_analise"].tolist(), [mv.FLOW] * 3)
        self.assertEqual(frame["subgrupo_analise"].tolist(),
                         ["RETORNO DE PRODUÇÃO", "AG, GARANTIA, ADEQUAÇÃO", "CONSUMO DE OPS"])
        self.assertEqual(frame["regra_classificacao"].tolist(),
                         ["040_SUBGRUPO_CONFIRMADO", "550_SUBGRUPO_CONFIRMADO", "999_SUBGRUPO_CONFIRMADO"])
        self.assertEqual(frame["descricao_tes"].tolist(),
                         ["DEVOLUCAO MES", "BAIXA PRODUCAO MES", "ORDEM DE PRODUÇÃO"])
        self.assertEqual(frame["valor_saida"].tolist(), [10, 10, 10])

    def test_flow_priority_and_remaining_pa_pi(self):
        rows = [record(ae_original="OP00001234567", tipo="PI"),
                record(ae_original="CC123456", documento="GR"),
                record(tipo="II", documento="II"), record(tipo="MC", documento="MC"),
                record(codigo=mv.rules()["materiais_h001"][0], tipo="MP", documento="H001"),
                record(tipo="PI", documento="PI"), record(documento="MP")]
        frame = mv.build_model([imported(rows)])["frame"]
        expected = ["520_OP_MANUAL", "520_CC_GERENCIAL", "520_CC_CONSUMO", "520_CC_CONSUMO",
                    "520_CC_CONSUMO", "520_BASE_A_VALIDAR", "520_BASE_A_VALIDAR"]
        self.assertEqual(frame.regra_classificacao.tolist(), expected)
        self.assertEqual(frame.iloc[2].subgrupo_analise, "MATERIAIS DE CONSUMO")
        self.assertEqual(frame.iloc[0].grupo_analise, mv.FLOW)
        self.assertEqual(frame.iloc[-2].grupo_analise, mv.ADJUSTMENT)
        self.assertEqual(frame.iloc[-1].grupo_analise, mv.ADJUSTMENT)

    def test_production_requires_tes_020_for_pa_and_pi(self):
        rows = [record(tes=tes, tipo=category, documento=tes + category)
                for tes in ("020", "520") for category in ("PA", "PI")]
        frame = mv.build_model([imported(rows)])["frame"]
        self.assertEqual(frame.grupo_analise.tolist(),
                         [mv.PRODUCTION, mv.PRODUCTION, mv.ADJUSTMENT, mv.ADJUSTMENT])
        self.assertEqual(frame.regra_classificacao.tolist(),
                         ["AJUSTE_PA_PI_PRODUCAO_INTERNA", "AJUSTE_PA_PI_PRODUCAO_INTERNA",
                          "520_BASE_A_VALIDAR", "520_BASE_A_VALIDAR"])
        self.assertEqual(frame.valor_saida.tolist(), [10, 10, 10, 10])
        self.assertEqual(frame.ae_original.tolist(), ["CC600307"] * 4)

    def test_finished_component_is_not_raw_copper_or_sheet(self):
        frame = mv.build_model([imported([record(descricao="PORCA PARA CHAPA DE COBRE")])])["frame"]
        self.assertEqual(frame.iloc[0].grupo_analise, mv.ADJUSTMENT)

    def test_020_production_and_closing(self):
        rows = [record(tes="020", tipo="PA", qtd_saida=None, valor_saida=None, qtd_entrada="2", valor_entrada="10"),
                record(tes="020", descricao="CHAPA ACO", documento="OUTRO")]
        frame = mv.build_model([imported(rows)])["frame"]
        self.assertEqual(frame.grupo_analise.tolist(), [mv.PRODUCTION, mv.FLOW])
        self.assertEqual(frame.valor_entrada.tolist(), [10, 0])
        self.assertEqual(frame.valor_saida.tolist(), [0, 10])  # direction comes from the report, not TES names

    def test_repeat_aware_overlap_and_idempotence(self):
        row = record()
        first = imported([row, row])
        later = imported([record(arquivo_origem="ano.xlsx", linha_origem=20)], "b")
        merged, duplicates = mv.merge_imports([first, later, first])
        self.assertEqual(len(merged), 2)
        self.assertEqual(duplicates, 3)
        self.assertEqual(len({r["id_registro"] for r in merged}), 2)

    def test_address_pair_ignores_op_and_is_one_to_one(self):
        incoming = record(tes="499", ae_original="SEM OP", qtd_entrada="2", valor_entrada="10", qtd_saida=None, valor_saida=None)
        outgoing = record(tes="999", ae_original="OP00001234567")
        model = mv.build_model([imported([incoming, outgoing, outgoing])])
        frame = model["frame"]
        self.assertEqual(int(frame.enderecamento_compensado.sum()), 2)
        self.assertEqual(len(mv.effective(frame)), 1)
        op = mv.summarize_ops(frame).iloc[0]
        self.assertEqual(op.lancamentos, 2)
        self.assertEqual(op.enderecamentos, 1)
        self.assertEqual(op.valor_saida, 10)

    def test_quantity_difference_is_review_not_automatic_exclusion(self):
        a = record(tes="499", qtd_entrada="2.001", valor_entrada="10", qtd_saida=None, valor_saida=None)
        b = record(tes="999", qtd_saida="2", valor_saida="10")
        model = mv.build_model([imported([a, b])])
        self.assertFalse(model["frame"].enderecamento_compensado.any())
        self.assertEqual(len(model["pares_enderecamento"]), 1)
        self.assertEqual(model["pares_enderecamento"][0]["diferenca"], "0.001")

    def test_unknown_group_uses_confirmed_description(self):
        frame = mv.build_model([imported([record(tes="499")])])["frame"]
        self.assertEqual(frame.iloc[0].grupo_analise, "ENDEREÇAMENTO")
        self.assertTrue(frame.iloc[0].grupo_provisorio)

    def test_original_ae_and_values_round_trip(self):
        row = record(ae_original=" OP00001234567 ", valor_saida="-12.34")
        pack = mv.pack_import(imported([row]))
        restored = mv.unpack_import(pack)["rows"][0]
        self.assertEqual(restored["ae_original"], " OP00001234567 ")
        self.assertEqual(restored["valor_saida"], "-12.34")

    def test_missing_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Data"):
            record(data=None)

    def test_excel_ae_column_and_numeric_dates(self):
        row = record(ae_original="OP00001234567", descricao="=NÃO É FÓRMULA")
        model = mv.build_model([imported([row])])
        output = mv.export_excel(model["frame"])
        wb = openpyxl.load_workbook(io.BytesIO(output), read_only=True)
        sheet = wb["Movimentações"]
        self.assertEqual(sheet["AE1"].value, "AE original")
        self.assertEqual(sheet["AE2"].value, "OP00001234567")
        self.assertEqual(sheet["B2"].data_type, "s")
        self.assertEqual(sheet["H2"].value.date().isoformat(), "2026-10-01")
        wb.close()
        with ZipFile(io.BytesIO(output)) as archive:
            xml = archive.read("xl/worksheets/sheet5.xml").decode()
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
