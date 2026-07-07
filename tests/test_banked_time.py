import unittest
from datetime import date

from config import FLSA_207K_WORK_PERIOD_DAYS
from tests.helpers import get_any_officer, test_database


class BankedTimeTests(unittest.TestCase):
    def test_resolve_time_scope_month(self):
        with test_database():
            import logic

            start, end, label = logic.resolve_time_scope("month", date(2026, 7, 15))
            self.assertEqual(start, date(2026, 7, 1))
            self.assertEqual(end, date(2026, 7, 31))
            self.assertEqual(label, "July 2026")

    def test_banked_time_summary_includes_flsa(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            summary = logic.get_banked_time_summary(officer["id"], scope="pay_period", reference=date(2026, 7, 10))
            self.assertTrue(summary["success"])
            self.assertEqual(len(summary["banks"]), 4)
            self.assertTrue(summary["flsa"].get("enabled"))
            self.assertEqual(summary["flsa_work_period_days"], FLSA_207K_WORK_PERIOD_DAYS)

    def test_comp_earned_from_timecard_preview(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            p_start, _ = logic.get_pay_period(date(2026, 7, 10))
            save = logic.save_timecard_entry(
                officer["id"],
                "2026-07-10",
                8.0,
                entry_type="Comp Earned",
                period_start=p_start.isoformat(),
            )
            self.assertTrue(save["success"], save.get("message"))

            summary = logic.get_banked_time_summary(officer["id"], scope="pay_period", reference=p_start)
            comp = next(b for b in summary["banks"] if b["key"] == "comp")
            self.assertAlmostEqual(comp["earned"], 4.0, places=1)

            txns = logic.get_bank_transactions(officer["id"], "comp", scope="pay_period", reference=p_start)
            self.assertTrue(txns["success"])
            self.assertEqual(len(txns["transactions"]), 1)
            self.assertAlmostEqual(txns["totals"]["earned"], 4.0, places=1)

    def test_sick_used_from_timecard(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            from database import get_connection
            from logic.payroll import _ensure_officer_time_banks

            conn = get_connection()
            cursor = conn.cursor()
            _ensure_officer_time_banks(cursor, officer["id"], date(2026, 7, 10))
            cursor.execute(
                "UPDATE officer_time_banks SET sick_hours = 40 WHERE officer_id = ?",
                (officer["id"],),
            )
            conn.commit()
            conn.close()

            p_start, _ = logic.get_pay_period(date(2026, 7, 10))
            save = logic.save_timecard_entry(
                officer["id"],
                "2026-07-11",
                4.0,
                entry_type="Sick Time Used",
                period_start=p_start.isoformat(),
            )
            self.assertTrue(save["success"], save.get("message"))

            summary = logic.get_banked_time_summary(officer["id"], scope="pay_period", reference=p_start)
            sick = next(b for b in summary["banks"] if b["key"] == "sick")
            self.assertAlmostEqual(sick["used"], 4.0, places=1)

    def test_timecard_entries_for_year_scope(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            p_start, _ = logic.get_pay_period(date(2026, 7, 10))
            logic.save_timecard_entry(
                officer["id"],
                "2026-07-10",
                8.0,
                entry_type="Overtime Earned",
                period_start=p_start.isoformat(),
            )
            data = logic.get_timecard_entries_for_scope(officer["id"], scope="year", reference=date(2026, 7, 10))
            self.assertTrue(data["success"])
            self.assertGreaterEqual(data["entry_count"], 1)
            self.assertGreater(data["total_hours"], 0)


if __name__ == "__main__":
    unittest.main()
