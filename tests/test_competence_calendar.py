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
