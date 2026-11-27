"""Regressões: competência ainda aberta aparece sem importar o Analítico."""
import unittest
from datetime import date

from competence_calendar import selectable_months


class SelectableMonthsTests(unittest.TestCase):
    def test_october_between_september_saved_and_november_preview(self):
        months = selectable_months(
            [date(2026, 9, 1), date(2026, 11, 1)],
            date(2026, 11, 1),
            date(2026, 10, 1),
        )
        self.assertIn(date(2026, 10, 1), months)
        self.assertEqual(months[-2:], [date(2026, 10, 1), date(2026, 11, 1)])
        self.assertEqual(len(months), len(set(months)))

    def test_no_saved_closing_still_shows_open_month(self):
        months = selectable_months([], date(2026, 11, 1), date(2026, 10, 1))
        self.assertIn(date(2026, 10, 1), months)
        self.assertEqual(months[0], date(2026, 1, 1))

    def test_year_change_keeps_december_accessible(self):
        months = selectable_months(
            [date(2026, 11, 1)],
            date(2027, 1, 1),
            date(2026, 12, 1),
        )
        self.assertEqual(months[-3:], [
            date(2026, 11, 1),
            date(2026, 12, 1),
            date(2027, 1, 1),
        ])

    def test_historical_dates_before_first_month_not_reintroduced(self):
        months = selectable_months(
            [date(2025, 12, 1), date(2026, 9, 1)],
            date(2026, 11, 1),
            date(2026, 10, 1),
        )
        self.assertNotIn(date(2025, 12, 1), months)


if __name__ == "__main__":
    unittest.main()


class CurrentMonthDefaultsTests(unittest.TestCase):
    def test_current_month_is_default_even_without_import(self):
        from competence_calendar import default_analysis_month, selectable_months
        closed, current = date(2026, 10, 1), date(2026, 11, 1)
        available = selectable_months([closed], current, closed)
        for invalid in ("", "2026-13", "2000-01", None):
            self.assertEqual(default_analysis_month(invalid, available, current), current)
        self.assertEqual(default_analysis_month("2026-10", available, current), closed)

    def test_latest_closed_month_never_counts_current_month(self):
        from competence_calendar import latest_closed_month
        current = date(2026, 11, 1)
        self.assertEqual(latest_closed_month({"2026-09-01", "2026-10-01", "2026-11-01", "bad"}, current),
                         date(2026, 10, 1))
        self.assertIsNone(latest_closed_month({"2026-11-01"}, current))

    def test_stock_preview_requires_current_source_in_setta_timezone(self):
        from competence_calendar import snapshot_is_current
        nov = date(2026, 11, 1)
        self.assertFalse(snapshot_is_current({}, nov))
        self.assertFalse(snapshot_is_current({"last_update_at": "2026-11-01T02:00:00Z"}, nov))
        self.assertTrue(snapshot_is_current({"last_update_at": "2026-11-01T03:00:00Z"}, nov))
