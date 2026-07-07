import os
import tempfile
import unittest
from datetime import date

from permissions import role_has_permission
from tests.helpers import get_any_officer, test_database


class TimecardScheduleTests(unittest.TestCase):
    def test_permissions_stub(self):
        self.assertTrue(role_has_permission("Officer", "timecard.edit_own"))
        self.assertTrue(role_has_permission("Officer", "timecard.submit"))
        self.assertFalse(role_has_permission("Officer", "timecard.approve"))
        self.assertTrue(role_has_permission("Supervisor", "timecard.approve"))
        self.assertFalse(role_has_permission("Officer", "schedule.base.publish"))
        self.assertFalse(role_has_permission("Officer", "reports.view"))
        self.assertFalse(role_has_permission("Officer", "database.backup"))
        self.assertTrue(role_has_permission("Supervisor", "database.backup"))
        self.assertTrue(role_has_permission("Administration", "schedule.base.publish"))
        self.assertTrue(role_has_permission("Supervisor", "reports.view"))
        self.assertTrue(role_has_permission("Administration", "holidays.manage"))
        self.assertFalse(role_has_permission("Supervisor", "holidays.manage"))
        self.assertFalse(role_has_permission("Officer", "holidays.manage"))

    def test_pay_period_history(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            period_start, _ = logic.get_pay_period()
            logic.save_timecard_entry(
                officer["id"],
                period_start.isoformat(),
                8.0,
            )
            history = logic.get_pay_period_history(3)
            self.assertTrue(history["success"])
            self.assertGreaterEqual(len(history["periods"]), 1)
            self.assertEqual(history["periods"][0]["period_start"], period_start.isoformat())

    def test_pay_period_history_officer_scope(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            period_start, _ = logic.get_pay_period()
            logic.save_timecard_entry(officer["id"], period_start.isoformat(), 6.0)
            scoped = logic.get_pay_period_history(3, officer_id=officer["id"])
            self.assertEqual(len(scoped["periods"]), 1)
            self.assertEqual(scoped["periods"][0]["officer_count"], 1)
            self.assertEqual(scoped["periods"][0]["total_hours"], 6.0)

    def test_dodgeville_pay_period_anchor(self):
        with test_database():
            from datetime import date

            import logic

            start, end = logic.get_pay_period(date(2026, 7, 10))
            self.assertEqual(start, date(2026, 7, 6))
            self.assertEqual(end, date(2026, 7, 19))
            self.assertEqual((end - start).days, 13)
            rot_start, _ = logic.get_current_cycle_window(date(2026, 7, 10))
            self.assertNotEqual(start, rot_start)

    def test_pay_period_navigation(self):
        with test_database():
            from datetime import date

            import logic

            start, end = logic.get_pay_period(date(2026, 7, 10))
            prev_start, prev_end = logic.get_adjacent_pay_period(start, -1)
            self.assertEqual((prev_end - prev_start).days, 13)
            self.assertEqual(prev_start, date(2026, 6, 22))
            self.assertEqual(prev_end, date(2026, 7, 5))
            next_start, _ = logic.get_adjacent_pay_period(start, 1)
            self.assertEqual(next_start, date(2026, 7, 20))
            ref = date(2026, 7, 10)
            self.assertFalse(logic.is_future_pay_period(start, reference=ref))
            self.assertTrue(logic.is_future_pay_period(next_start, reference=ref))

    def test_overnight_shift_counts_in_start_period(self):
        with test_database():
            from datetime import date

            import logic

            officer = get_any_officer("A")
            shift_start_day = date(2026, 7, 5)
            result = logic.save_timecard_entry(
                officer["id"],
                shift_start_day.isoformat(),
                11.0,
                time_in="22:00",
                time_out="06:00",
            )
            self.assertTrue(result["success"], result.get("message"))
            self.assertTrue(result.get("overnight"))

            prior_period = logic.get_pay_period(shift_start_day)
            self.assertEqual(prior_period[0], date(2026, 6, 22))
            data = logic.get_timecard_period(officer["id"], prior_period[0])
            july5 = next(d for d in data["days"] if d["entry_date"] == shift_start_day.isoformat())
            self.assertTrue(july5.get("overnight"))
            self.assertEqual(july5["hours_worked"], 11.0)

            next_period = logic.get_pay_period(date(2026, 7, 6))
            self.assertEqual(next_period[0], date(2026, 7, 6))
            next_data = logic.get_timecard_period(officer["id"], next_period[0])
            self.assertFalse(
                any(
                    e.get("timecard_id")
                    for d in next_data["days"]
                    if d["entry_date"] == shift_start_day.isoformat()
                    for e in d.get("entries", [])
                )
            )

    def test_search_pay_period_by_date(self):
        with test_database():
            import logic

            result = logic.search_pay_period_by_date("05-07-2026")
            self.assertTrue(result["success"], result.get("message"))
            self.assertEqual(result["period_start"], "2026-06-22")
            self.assertEqual(result["period_end"], "2026-07-05")

            catalog = logic.list_pay_periods_catalog()
            self.assertTrue(catalog["success"])
            self.assertGreaterEqual(len(catalog["periods"]), 1)
            self.assertTrue(any(p.get("is_current") for p in catalog["periods"]))

    def test_timecard_save_and_import(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            period_start, _ = logic.get_pay_period()
            result = logic.save_timecard_entry(
                officer["id"],
                period_start.isoformat(),
                4.0,
                entry_type="Overtime Earned",
                notes="Test OT",
            )
            self.assertTrue(result["success"], result.get("message"))

            imported = logic.import_timecard_to_payroll(officer["id"], period_start.isoformat())
            self.assertTrue(imported["success"], imported.get("message"))
            entries = logic.get_payroll_entries(officer_id=officer["id"], limit=5)
            self.assertTrue(any(e["entry_type"] == "Overtime Earned" for e in entries))

    def test_multiple_timecard_entries_same_day(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            period_start, _ = logic.get_pay_period()
            day = period_start.isoformat()

            regular = logic.save_timecard_entry(
                officer["id"],
                day,
                8.0,
                entry_type="Regular Hours",
            )
            self.assertTrue(regular["success"], regular.get("message"))
            regular_id = regular["timecard_id"]

            ot = logic.save_timecard_entry(
                officer["id"],
                day,
                2.0,
                entry_type="Overtime Earned",
                notes="Court OT",
            )
            self.assertTrue(ot["success"], ot.get("message"))
            self.assertNotEqual(ot["timecard_id"], regular_id)

            data = logic.get_timecard_period(officer["id"], period_start)
            day_row = next(d for d in data["days"] if d["entry_date"] == day)
            self.assertEqual(len(day_row["entries"]), 2)
            types = {e["entry_type"] for e in day_row["entries"]}
            self.assertEqual(types, {"Regular Hours", "Overtime Earned"})

            update = logic.save_timecard_entry(
                officer["id"],
                day,
                8.5,
                entry_type="Regular Hours",
                timecard_id=regular_id,
            )
            self.assertTrue(update["success"], update.get("message"))

            removed = logic.delete_timecard_entry(ot["timecard_id"], officer["id"])
            self.assertTrue(removed["success"], removed.get("message"))
            data = logic.get_timecard_period(officer["id"], period_start)
            day_row = next(d for d in data["days"] if d["entry_date"] == day)
            self.assertEqual(len(day_row["entries"]), 1)
            self.assertEqual(day_row["entries"][0]["hours_worked"], 8.5)

    def test_ensure_original_monthly_schedule_auto_generates(self):
        with test_database():
            import logic

            year, month = 2026, 8
            before = logic.get_schedule_snapshot(year, month, "base")
            self.assertIsNone(before)

            result = logic.ensure_original_monthly_schedule(year, month)
            self.assertTrue(result["success"], result.get("message"))
            self.assertTrue(result.get("created"))

            snapshot = logic.get_schedule_snapshot(year, month, "base")
            self.assertIsNotNone(snapshot)
            self.assertEqual(snapshot["locked"], 1)
            self.assertGreater(len(snapshot["rows"]), 0)

            from logic.staffing_config import get_active_shift_time_values

            officer = logic.get_officers_by_seniority()[0]
            work_rows = [r for r in snapshot["rows"] if r["officer_id"] == officer["id"] and r["status"] == "working"]
            self.assertGreater(len(work_rows), 0)
            active_bands = get_active_shift_time_values()
            for row in work_rows:
                band = (row["assigned_shift_start"], row["assigned_shift_end"])
                self.assertIn(band, active_bands)

            again = logic.ensure_original_monthly_schedule(year, month)
            self.assertTrue(again["success"])
            self.assertFalse(again.get("created"))

    def test_live_schedule_auto_updates_on_day_off_approve(self):
        with test_database():
            import logic
            from tests.helpers import get_any_officer, off_date_for_squad

            officer = get_any_officer("A", "06:00")
            off_day = off_date_for_squad("A")
            year, month = off_day.year, off_day.month
            request_date = off_day.strftime("%Y-%m-%d")
            logic.ensure_original_monthly_schedule(year, month)
            before = logic.get_schedule_snapshot(year, month, "updated")
            self.assertIsNone(before)

            created = logic.create_day_off_request(officer["id"], request_date, "Vacation")
            self.assertTrue(created["success"])
            result = logic.process_day_off_request(created["request_id"], "approve")
            self.assertTrue(result.success, result.message)

            live = logic.get_schedule_snapshot(year, month, "updated")
            self.assertIsNotNone(live)
            self.assertGreater(len(live.get("rows", [])), 0)
            bumped = [
                r for r in live["rows"] if r["officer_id"] == officer["id"] and r["assignment_date"] == request_date
            ]
            self.assertEqual(len(bumped), 1)
            self.assertNotEqual(bumped[0]["status"], "working")

    def test_publish_base_and_sync_updated(self):
        with test_database():
            import logic
            from seed_data import seed_users_if_empty

            seed_users_if_empty()
            users = logic.list_login_users()
            admin = next(u for u in users if u["role"] == "Administration")

            year, month = date.today().year, date.today().month
            pub = logic.publish_base_schedule(year, month, admin["id"])
            self.assertTrue(pub["success"], pub.get("message"))

            base = logic.get_schedule_snapshot(year, month, "base")
            self.assertIsNotNone(base)
            self.assertEqual(base["locked"], 1)
            self.assertGreater(len(base["rows"]), 0)

            sync = logic.sync_updated_schedule(year, month, admin["id"])
            self.assertTrue(sync["success"], sync.get("message"))
            updated = logic.get_schedule_snapshot(year, month, "updated")
            self.assertIsNotNone(updated)

    def test_base_summary_without_snapshot(self):
        with test_database():
            import logic

            summary = logic.get_monthly_summary_from_snapshot(None, 2026, 6, "base")
            self.assertEqual(len(summary), 30)
            self.assertGreater(summary[0]["working_officers"], 0)

    def test_compare_base_updated_no_diff_after_sync(self):
        with test_database():
            import logic
            from seed_data import seed_users_if_empty

            seed_users_if_empty()
            admin = next(u for u in logic.list_login_users() if u["role"] == "Administration")
            year, month = date.today().year, date.today().month

            logic.publish_base_schedule(year, month, admin["id"])
            logic.sync_updated_schedule(year, month, admin["id"])
            result = logic.compare_base_updated_schedule(year, month)
            self.assertTrue(result["success"], result.get("message"))
            self.assertEqual(result["diff_count"], 0)

    def test_compare_base_updated_detects_manual_edit(self):
        with test_database():
            import logic
            from seed_data import seed_users_if_empty

            seed_users_if_empty()
            admin = next(u for u in logic.list_login_users() if u["role"] == "Administration")
            officer = get_any_officer("A")
            year, month = date.today().year, date.today().month
            work_day = None
            for day_num in range(1, 15):
                target = date(year, month, day_num)
                if logic.is_officer_working_on_day(officer["id"], target):
                    work_day = target
                    break
            self.assertIsNotNone(work_day, "Need a working day in first half of month")

            logic.publish_base_schedule(year, month, admin["id"])
            logic.sync_updated_schedule(year, month, admin["id"])
            logic.set_snapshot_assignment(
                year,
                month,
                "updated",
                work_day.isoformat(),
                officer["id"],
                "off",
                notes="Manual day off",
            )
            result = logic.compare_base_updated_schedule(year, month)
            self.assertTrue(result["success"], result.get("message"))
            self.assertGreaterEqual(result["diff_count"], 1)
            match = next(
                (d for d in result["diffs"] if d["officer_id"] == officer["id"]),
                None,
            )
            self.assertIsNotNone(match)
            self.assertEqual(match["base_status"], "working")
            self.assertEqual(match["updated_status"], "off")

    def test_compare_base_updated_officer_filter(self):
        with test_database():
            import logic
            from seed_data import seed_users_if_empty

            seed_users_if_empty()
            admin = next(u for u in logic.list_login_users() if u["role"] == "Administration")
            officer = get_any_officer("A")
            year, month = date.today().year, date.today().month
            work_day = None
            for day_num in range(1, 15):
                target = date(year, month, day_num)
                if logic.is_officer_working_on_day(officer["id"], target):
                    work_day = target
                    break
            self.assertIsNotNone(work_day)

            logic.publish_base_schedule(year, month, admin["id"])
            logic.sync_updated_schedule(year, month, admin["id"])
            logic.set_snapshot_assignment(
                year,
                month,
                "updated",
                work_day.isoformat(),
                officer["id"],
                "off",
                notes="Officer filter test",
            )
            all_result = logic.compare_base_updated_schedule(year, month)
            scoped = logic.compare_base_updated_schedule(year, month, officer_id=officer["id"])
            self.assertTrue(scoped["success"])
            self.assertGreaterEqual(all_result["diff_count"], scoped["diff_count"])
            self.assertGreaterEqual(scoped["diff_count"], 1)
            self.assertTrue(all(d["officer_id"] == officer["id"] for d in scoped["diffs"]))

    def test_export_schedule_diff_csv_officer_scope(self):
        with test_database():
            import logic
            from seed_data import seed_users_if_empty

            seed_users_if_empty()
            admin = next(u for u in logic.list_login_users() if u["role"] == "Administration")
            officer = get_any_officer("A")
            year, month = date.today().year, date.today().month
            work_day = None
            for day_num in range(1, 15):
                target = date(year, month, day_num)
                if logic.is_officer_working_on_day(officer["id"], target):
                    work_day = target
                    break
            self.assertIsNotNone(work_day)

            logic.publish_base_schedule(year, month, admin["id"])
            logic.sync_updated_schedule(year, month, admin["id"])
            logic.set_snapshot_assignment(
                year,
                month,
                "updated",
                work_day.isoformat(),
                officer["id"],
                "off",
                notes="Scoped CSV",
            )
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "scoped_diff.csv")
                result = logic.export_schedule_diff_csv(
                    year,
                    month,
                    path,
                    officer_id=officer["id"],
                )
                self.assertTrue(result["success"], result.get("message"))
                self.assertGreaterEqual(result["count"], 1)
                with open(path, encoding="utf-8") as fh:
                    content = fh.read()
                self.assertIn(officer["name"], content)

    def test_export_pay_period_history_csv(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            period_start, _ = logic.get_pay_period()
            logic.save_timecard_entry(officer["id"], period_start.isoformat(), 6.0)
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "history.csv")
                result = logic.export_pay_period_history_csv(
                    limit=3,
                    officer_id=officer["id"],
                    output_path=path,
                )
                self.assertTrue(result["success"], result.get("message"))
                self.assertGreaterEqual(result["count"], 1)
                with open(path, encoding="utf-8") as fh:
                    content = fh.read()
                self.assertIn("period_start", content)
                from validators import format_date

                self.assertIn(format_date(period_start), content)

    def test_timecard_prefill_from_live_schedule_after_day_off(self):
        with test_database():
            import logic
            from tests.helpers import get_any_officer, off_date_for_squad

            officer = get_any_officer("A", "06:00")
            off_day = off_date_for_squad("A")
            logic.ensure_original_monthly_schedule(off_day.year, off_day.month)
            request_date = off_day.strftime("%Y-%m-%d")
            created = logic.create_day_off_request(officer["id"], request_date, "Vacation")
            self.assertTrue(created["success"])
            result = logic.process_day_off_request(created["request_id"], "approve")
            self.assertTrue(result.success, result.message)

            live = logic.get_officer_live_schedule_day(officer["id"], off_day)
            self.assertFalse(live["scheduled"])
            self.assertIn(live["status"], ("leave", "bumped"))

            period_start, _ = logic.get_pay_period(off_day)
            prefill = logic.prefill_timecard_from_schedule(officer["id"], period_start)
            self.assertTrue(prefill["success"], prefill.get("message"))

            data = logic.get_timecard_period(officer["id"], period_start)
            day_row = next(d for d in data["days"] if d["entry_date"] == request_date)
            self.assertTrue(any(e.get("timecard_id") for e in day_row["entries"]))

    def test_timecard_approval_blocks_officer_edits(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            period_start, _ = logic.get_pay_period()
            day = period_start.isoformat()
            saved = logic.save_timecard_entry(officer["id"], day, 8.0)
            self.assertTrue(saved["success"], saved.get("message"))
            approved = logic.approve_timecard_period(officer["id"], period_start, user_id=1)
            self.assertTrue(approved["success"], approved.get("message"))

            blocked = logic.save_timecard_entry(
                officer["id"],
                day,
                7.5,
                timecard_id=saved["timecard_id"],
            )
            self.assertFalse(blocked["success"])
            self.assertIn("approved", blocked["message"].lower())

            override = logic.save_timecard_entry(
                officer["id"],
                day,
                7.5,
                timecard_id=saved["timecard_id"],
                override_approval=True,
            )
            self.assertTrue(override["success"], override.get("message"))

    def test_timecard_submit_and_supervisor_approve(self):
        with test_database():
            import logic
            from seed_data import seed_users_if_empty

            seed_users_if_empty()
            officer = get_any_officer("A")
            period_start, _ = logic.get_pay_period()
            logic.save_timecard_entry(officer["id"], period_start.isoformat(), 8.0)
            submitted = logic.submit_timecard_for_approval(officer["id"], period_start)
            self.assertTrue(submitted["success"], submitted.get("message"))
            approval = logic.get_timecard_approval(officer["id"], period_start)
            self.assertEqual(approval["status"], "Submitted")

            approved = logic.approve_timecard_period(officer["id"], period_start, user_id=1)
            self.assertTrue(approved["success"], approved.get("message"))
            self.assertTrue(logic.is_timecard_period_approved(officer["id"], period_start))

            summary = logic.list_timecard_approvals_for_period(period_start)
            self.assertTrue(summary["success"])
            row = next(r for r in summary["rows"] if r["officer_id"] == officer["id"])
            self.assertEqual(row["status"], "Approved")
            self.assertGreaterEqual(row["total_hours"], 8.0)

    def test_export_timecard_csv(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            period_start, _ = logic.get_pay_period()
            logic.save_timecard_entry(
                officer["id"],
                period_start.isoformat(),
                8.0,
            )
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "timecard.csv")
                result = logic.export_timecard_csv(
                    period_start=period_start,
                    officer_id=officer["id"],
                    output_path=path,
                )
                self.assertTrue(result["success"], result.get("message"))
                self.assertGreaterEqual(result["count"], 1)
                with open(path, encoding="utf-8") as fh:
                    content = fh.read()
                self.assertIn("officer_name", content)
                self.assertIn(officer["name"], content)


if __name__ == "__main__":
    unittest.main()
