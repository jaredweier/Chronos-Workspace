import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import test_database


class ShiftAssignmentTests(unittest.TestCase):
    def setUp(self):
        self._db_cm = test_database()
        self._db_cm.__enter__()
        import logic

        self.logic = logic

    def tearDown(self):
        self._db_cm.__exit__(None, None, None)

    def test_monthly_generator_assigns_any_officer_to_any_shift_band(self):
        from logic.shift_assignment import distribute_shift_bands, get_shift_band_options
        from logic.snapshots import ensure_original_monthly_schedule, get_schedule_snapshot

        officers = [o for o in self.logic.get_officers_by_seniority() if o.get("active") == 1]
        bands = get_shift_band_options()
        self.assertGreaterEqual(len(bands), 2)

        result = ensure_original_monthly_schedule(2026, 7)
        self.assertTrue(result.get("success"), result.get("message"))

        snapshot = get_schedule_snapshot(2026, 7, "base")
        work_day = date(2026, 7, 1)
        working_rows = [
            r for r in snapshot["rows"] if r["assignment_date"] == work_day.isoformat() and r["status"] == "working"
        ]
        self.assertGreater(len(working_rows), 0)
        assigned_bands = {(r["assigned_shift_start"], r["assigned_shift_end"]) for r in working_rows}
        self.assertGreater(len(assigned_bands), 1, "Working officers should span multiple shift bands")

        sample = officers[: min(3, len(officers))]
        mapping = distribute_shift_bands(sample)
        self.assertEqual(len(mapping), len(sample))
        for _oid, band in mapping.items():
            self.assertIn(band, bands)

    def test_manual_snapshot_assignment_accepts_any_shift_band(self):
        from logic.snapshots import ensure_original_monthly_schedule, get_schedule_snapshot, set_snapshot_assignment

        ensure_original_monthly_schedule(2026, 8)
        sync = self.logic.sync_updated_schedule(2026, 8, user_id=1)
        self.assertTrue(sync.get("success"), sync.get("message"))
        officers = [o for o in self.logic.get_officers_by_seniority() if o.get("active") == 1]
        officer = officers[0]
        bands = self.logic.get_shift_band_options()
        target_band = bands[-1]

        result = set_snapshot_assignment(
            2026,
            8,
            "updated",
            "2026-08-05",
            officer["id"],
            "working",
            shift_start=target_band[0],
            shift_end=target_band[1],
        )
        self.assertTrue(result.get("success"), result.get("message"))

        snapshot = get_schedule_snapshot(2026, 8, "updated")
        row = next(
            r for r in snapshot["rows"] if r["officer_id"] == officer["id"] and r["assignment_date"] == "2026-08-05"
        )
        self.assertEqual(row["assigned_shift_start"], target_band[0])
        self.assertEqual(row["assigned_shift_end"], target_band[1])

    def test_simulator_uses_roster_with_flexible_shift_assignment(self):
        from simulator import SimulatorConfig, simulate_schedule

        result = simulate_schedule(
            SimulatorConfig(
                rotation_type="2-2-3 (Dodgeville 14-day)",
                num_officers=8,
                shift_length_hours=11.0,
                annual_hours_target=2080.0,
                shift_starts=["06:00", "10:00", "15:00", "19:00"],
                apply_department_rules=True,
            )
        )
        self.assertTrue(result.success, result.message)
        names = {slot.label for slot in result.officer_slots}
        self.assertFalse(names == {f"Officer {i}" for i in range(1, 9)})
        shift_starts = {slot.shift_start for slot in result.officer_slots}
        self.assertGreater(len(shift_starts), 1)


if __name__ == "__main__":
    unittest.main()
