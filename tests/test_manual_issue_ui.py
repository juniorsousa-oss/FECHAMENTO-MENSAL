"""Smoke test da seção de baixa manual isolada no Streamlit."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

import movement_analysis_ui as kardex


PROGRAM = '''
from datetime import date
from decimal import Decimal
import pandas as pd
import manual_issue_ui as ui
model = {
  "as_of": "2026-11-03", "history_available": True,
  "lot_items": pd.DataFrame([{
    "op": "26009201001", "codigo": "01040055", "lote": "060919",
    "necessaria": Decimal("9"), "baixada": Decimal("3")
  }]),
  "lot_ops": pd.DataFrame([{
    "op": "26009201001", "cliente": "SERRA VERDE",
    "data_faturamento": "31/10/2026"
  }]),
  "general": [{
    "op": "26009201001", "codigo": "01040055",
    "separacao": "2026-10-20", "conferencia": "2026-10-22"
  }],
  "stock": [{"codigo": "01040055", "endereco": "G9-PROD",
             "saldo": Decimal("0")}],
}
ui.render(model)
'''


class UIManualCandidatesTests(unittest.TestCase):
    def test_closed_section_does_not_fetch_kardex(self):
        with patch.object(kardex, "_imports") as imports, \
             patch.object(kardex, "_model") as kardex_model:
            app = AppTest.from_string(PROGRAM, default_timeout=20).run()
        self.assertFalse(app.exception)
        imports.assert_not_called()
        kardex_model.assert_not_called()
        self.assertTrue(any(
            "ABRIR ANÁLISE RETROATIVA" in t.label for t in app.toggle
        ))

    def test_explicit_analyze_then_export_does_not_mutate_source(self):
        registry = [{
            "chave": "fm_movimentacoes_import_v1_" + "a" * 64,
            "atualizado_em": "2026-11-04T10:00:00Z",
            "meta": {"arquivo_nome": "KARDEX-S2.xlsx"},
        }]
        frame = pd.DataFrame([{
            "data": "2026-10-25", "tes": "520",
            "codigo": "01040055", "qtd_saida": 5.0,
            "qtd_entrada": 0, "ae_original": "CC600307",
            "documento": "TESTE", "armazem": "S2",
            "descricao": "CONEXÃO HIDRÁULICA", "id_registro": "m-1",
            "arquivo_origem": "KARDEX-S2.xlsx", "linha_origem": 31,
        }])
        with patch.object(kardex, "_imports", return_value=registry) as loads, \
             patch.object(kardex, "_model", return_value={"frame": frame}) as model:
            app = AppTest.from_string(PROGRAM, default_timeout=30).run()
            next(t for t in app.toggle if "ABRIR ANÁLISE" in t.label).set_value(True).run()
            self.assertFalse(app.exception)
            loads.assert_not_called()
            model.assert_not_called()
            next(
                b for b in app.button
                if "ANALISAR E GERAR CANDIDATOS" in b.label
            ).click().run()
            self.assertFalse(app.exception)
            loads.assert_called_once()
            model.assert_called_once()
            self.assertEqual(len(app.dataframe), 1)
            table = app.dataframe[0].value
            self.assertEqual(len(table), 1)
            self.assertEqual(table.iloc[0]["OP candidata"], "26009201001")
            self.assertEqual(table.iloc[0]["Situação"],
                             "CANDIDATO ÚNICO — VALIDAR")
            # O AppTest não expõe st.download_button como app.button;
            # o arquivo pronto permanece disponível na sessão.
            ready = app.session_state["fm_manual_candidate_ready"]
            self.assertGreater(len(ready[2]), 100)
            self.assertEqual(ready[1]["summary"]["movimentos_elegiveis"], 1)


if __name__ == "__main__":
    unittest.main()
