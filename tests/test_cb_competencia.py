"""Regressões para competência de contagens físicas de chapas."""
from datetime import date
from email.message import EmailMessage
import unittest

from cb_parser import infer_chapas_competencia, parse_chapas_eml


class ChapaCompetenciaTests(unittest.TestCase):
    def test_late_october_count_belongs_to_october(self):
        self.assertEqual(infer_chapas_competencia(date(2026, 10, 29)),
                         date(2026, 10, 1))
        self.assertEqual(infer_chapas_competencia(date(2026, 10, 31)),
                         date(2026, 10, 1))

    def test_beginning_of_following_month_belongs_to_previous(self):
        self.assertEqual(infer_chapas_competencia(date(2026, 11, 3)),
                         date(2026, 10, 1))
        self.assertEqual(infer_chapas_competencia(date(2027, 1, 4)),
                         date(2026, 12, 1))

    def test_intermediate_or_missing_date_needs_explicit_confirmation(self):
        self.assertIsNone(infer_chapas_competencia(date(2026, 10, 15)))
        self.assertIsNone(infer_chapas_competencia(None))

    def test_realistic_email_table_does_not_shift_late_month_count(self):
        message = EmailMessage()
        message["Subject"] = "Contagem chapa"
        message.set_content("Contagem em anexo")
        message.add_alternative("""
            <html><body><table>
              <tr><td>Contagem de chapas 29/10/2026</td></tr>
              <tr><th>DIMENSÃO</th><th>DESCRIÇÃO</th>
                  <th>CHAPAS</th><th>PESO TOTAL</th></tr>
              <tr><td>2500X1200</td><td>#12 FINA FRIA</td>
                  <td>15</td><td>900,50</td></tr>
            </table></body></html>
        """, subtype="html")
        parsed = parse_chapas_eml(message.as_bytes(), "contagem.eml")
        self.assertEqual(parsed["data_contagem"], date(2026, 10, 29))
        self.assertEqual(parsed["competencia"], date(2026, 10, 1))
        self.assertEqual(parsed["tables_found"], 1)
        self.assertEqual(len(parsed["rows"]), 1)


if __name__ == "__main__":
    unittest.main()
