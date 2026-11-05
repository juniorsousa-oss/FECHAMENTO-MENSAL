"""Testes das confirmações de inventário e leitura da marcação laranja."""
from __future__ import annotations
import io
import unittest
from zipfile import ZipFile

import pandas as pd

import kardex_adjustments as adj
import stock_accuracy


def sample_xlsx() -> bytes:
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    styles = f'''<styleSheet xmlns="{ns}"><fills count="3">
      <fill><patternFill patternType="none"/></fill>
      <fill><patternFill patternType="gray125"/></fill>
      <fill><patternFill patternType="solid"><fgColor theme="9"/></patternFill></fill>
    </fills><cellXfs count="2"><xf fillId="0"/><xf fillId="2"/></cellXfs></styleSheet>'''
    def cell(name, value, style=0):
        return (f'<c r="{name}" s="{style}" t="inlineStr"><is><t>'
                f'{value}</t></is></c>')
    header = ''.join(cell(col+"1", label) for col,label in (
        ("B","Código"), ("G","Subgrupo"), ("M","Documento")
    ))
    data = (
        cell("A2","46325") + cell("B2","00090129")
        + cell("D2","S2") + cell("E2","020")
        + cell("G2","AJUSTE DE ESTOQUE",1) + cell("M2","99LNZR")
    )
    without_highlight = (
        cell("A3","46325") + cell("B3","00090130")
        + cell("D3","S2") + cell("E3","520")
        + cell("G3","AJUSTE DE ESTOQUE") + cell("M3","99LNZS")
    )
    sheet = (f'<worksheet xmlns="{ns}"><sheetData>'
             f'<row r="1">{header}</row>'
             f'<row r="2">{data}</row>'
             f'<row r="3">{without_highlight}</row>'
             f'</sheetData></worksheet>')
    buffer = io.BytesIO()
    with ZipFile(buffer,"w") as archive:
        archive.writestr("xl/styles.xml",styles)
        archive.writestr("xl/worksheets/sheet1.xml",sheet)
    return buffer.getvalue()


class StockAdjustmentsTests(unittest.TestCase):
    def test_import_somente_celula_g_laranja(self):
        lines = adj.parse_orange_marked_excel(sample_xlsx())
        self.assertEqual(len(lines),1)
        self.assertEqual(lines[0]["chave"],"2026-10-30|S2|020|00090129|99LNZR")

    def test_nao_confundir_consumo_com_ajuste(self):
        data = pd.DataFrame([
            {"data":"2026-10-30","codigo":"00090129","armazem":"S2",
             "tes":"020","documento":"99LNZR","subgrupo_usuario":"AJUSTE DE ESTOQUE",
             "condicao_id":"kardex_cond_09_ajuste_estoque","valor_entrada":25,"valor_saida":0},
            {"data":"2026-10-30","codigo":"00090130","armazem":"S2",
             "tes":"520","documento":"99LNZS","subgrupo_usuario":"AJUSTE DE ESTOQUE",
             "condicao_id":"kardex_cond_14_ajuste_520_sem_op","valor_entrada":0,"valor_saida":80},
            {"data":"2026-10-30","codigo":"00090130","armazem":"EP",
             "tes":"520","documento":"99LNZS","subgrupo_usuario":"CONSUMO DE EPI",
             "condicao_id":"kardex_cond_11_epi_ep","valor_entrada":0,"valor_saida":5},
        ])
        registry = {"versao":1,"meses":{"2026-10":[
            "2026-10-30|S2|020|00090129|99LNZR"
        ]}}
        result = adj.apply_confirmed(data,registry)
        self.assertEqual(result["subgrupo_usuario"].tolist(),
                         ["AJUSTE DE ESTOQUE","MATERIAL DE CONSUMO","CONSUMO DE EPI"])
        self.assertEqual(result["ajuste_confirmado"].sum(),1)
        self.assertEqual(result["ajuste_reclassificado_consumo"].sum(),1)
        self.assertEqual(result[["valor_entrada","valor_saida"]].sum().tolist(),[25,85])
        self.assertEqual(len(result),len(data))

    def test_historico_anterior_a_outubro_preservado(self):
        anterior = pd.DataFrame([{
            "data":"2026-09-30", "codigo":"00090129", "armazem":"S2",
            "tes":"520", "documento":"99OLD1",
            "subgrupo_usuario":"AJUSTE DE ESTOQUE",
            "condicao_id":"kardex_cond_14_ajuste_520_sem_op",
        }])
        result = adj.apply_confirmed(anterior, adj.empty_registry())
        self.assertEqual(result.iloc[0]["subgrupo_usuario"], "AJUSTE DE ESTOQUE")
        self.assertFalse(bool(result.iloc[0]["ajuste_reclassificado_consumo"]))

    def test_somente_mes_e_chave_exatos(self):
        registry = adj.normalize_registry({"meses":{"2026-10":[
            "2026-10-30|S2|020|00090129|99LNZR"
        ]}})
        self.assertEqual(len(registry["meses"]["2026-10"]),1)
        with self.assertRaises(ValueError):
            adj.normalize_registry({"meses":{"2026-10":[
                "2026-11-01|S2|020|00090129|99LNZR"
            ]}})

    def test_acuracia_de_outubro(self):
        self.assertAlmostEqual(stock_accuracy.accuracy(4362,124)*100,97.157267308574)
        with self.assertRaises(ValueError):
            stock_accuracy.accuracy(10,11)


if __name__ == "__main__":
    unittest.main()
