import unittest
from datetime import date
from unittest.mock import Mock

from closing_dashboard import closing_status, read_quality_rows


class ClosingDashboardTests(unittest.TestCase):
    def test_live_preview_reads_actual_analitico_errors_not_historical_import(self):
        historical = Mock(return_value=[{"codigo": "nao-usar"}])
        nov = date(2026, 11, 1)
        out = read_quality_rows({"preview": True}, nov, nov, {}, {"errors": [{"codigo": "0001"}]}, historical)
        self.assertEqual(out, [{"codigo": "0001"}])
        historical.assert_not_called()

    def test_manual_and_history_use_their_own_sources(self):
        oct_, nov = date(2026, 10, 1), date(2026, 11, 1)
        historical = Mock(return_value=["arquivo"])
        out = read_quality_rows({"manual_snapshot": True, "preview": True}, oct_, nov,
                                {"errors": ["manual"]}, {"errors": ["preview"]}, historical)
        self.assertEqual(out, ["manual"])
        historical.assert_not_called()
        self.assertEqual(read_quality_rows({}, oct_, nov, {}, {}, historical), ["arquivo"])
        historical.assert_called_once_with(oct_)

    def test_saved_closing_does_not_inherit_current_analitico_errors(self):
        self.assertEqual(closing_status(saved=True, available=True, errors=True), "Já encerrada")
        self.assertEqual(closing_status(saved=True, available=False, errors=False), "Já encerrada")
        self.assertEqual(closing_status(saved=False, available=True, errors=True), "Bloqueada por pendências")
        self.assertEqual(closing_status(saved=False, available=True, errors=False), "Pronta para conferência")
