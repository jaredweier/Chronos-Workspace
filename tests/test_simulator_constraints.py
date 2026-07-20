import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import test_database


class SimulatorConstraintsTests(unittest.TestCase):
    def setUp(self):
        self._db_cm = test_database()
        self._db_cm.__enter__()

    def tearDown(self):
        self._db_cm.__exit__(None, None, None)

    def test_half_hour_shift_length(self):
        from simulator import SimulatorConfig, simulate_schedule

        cfg = SimulatorConfig(
            rotation_type="2-2-3 (14-day)",
            num_officers=12,
            shift_length_hours=10.5,
            annual_hours_target=2080,
            shift_starts=["06:00", "14:00", "22:00"],
            apply_department_rules=False,
            min_per_shift=1,
            simulation_days=14,
            auto_min_officers=False,
        )
        result = simulate_schedule(cfg)
        self.assertTrue(result.success, result.message)
        self.assertEqual(cfg.shift_length_hours, 10.5)

    def test_reject_non_half_hour(self):
        from simulator import SimulatorConfig, simulate_schedule

        cfg = SimulatorConfig(
            rotation_type="2-2-3 (14-day)",
            num_officers=8,
            shift_length_hours=10.25,
            annual_hours_target=2080,
            shift_starts=["06:00", "14:00"],
            apply_department_rules=False,
            auto_min_officers=False,
        )
        result = simulate_schedule(cfg)
        self.assertFalse(result.success)
        self.assertIn("0.5", result.message)

    def test_multi_block_variations_sim(self):
        from simulator import SimulatorConfig, simulate_schedule

        cfg = SimulatorConfig(
            rotation_type="2-2-3 (14-day)",
            num_officers=16,
            shift_length_hours=11.0,
            annual_hours_target=2080,
            shift_starts=["06:00", "14:00", "22:00"],
            apply_department_rules=False,
            min_per_shift=1,
            simulation_days=32,
            rotation_style="rotating",
            rotation_variations=["5-3,6-2", "5-2,6-3"],
            stagger_phases=True,
            auto_min_officers=False,
        )
        result = simulate_schedule(cfg)
        self.assertTrue(result.success, result.message)
        self.assertEqual(result.metrics.get("custom_patterns"), 2)

    def test_avoid_flsa_detects_heavy_pattern(self):
        from simulator import SimulatorConfig, simulate_schedule

        # 12h shifts, work almost every day → exceeds 171/28 quickly
        cfg = SimulatorConfig(
            rotation_type="2-2-3 (14-day)",
            num_officers=4,
            shift_length_hours=12.0,
            annual_hours_target=2080,
            shift_starts=["06:00"],
            apply_department_rules=False,
            min_per_shift=0,
            simulation_days=28,
            rotation_style="fixed",
            rotation_variations=["6-1"],  # heavy
            avoid_flsa_overtime=True,
            flsa_work_period_days=28,
            auto_min_officers=False,
        )
        result = simulate_schedule(cfg)
        self.assertTrue(result.success)
        # 6 on / 1 off → 24 work days in 28 → 288h >> 171
        self.assertGreater(result.metrics.get("flsa_violations", 0), 0)
        self.assertFalse(result.metrics.get("hard_constraints_ok", True))

    def test_auto_min_officers(self):
        from simulator import SimulatorConfig, simulate_schedule

        cfg = SimulatorConfig(
            rotation_type="2-2-3 (14-day)",
            num_officers=0,
            shift_length_hours=11.0,
            annual_hours_target=2080,
            shift_starts=["06:00", "14:00", "22:00"],
            apply_department_rules=False,
            min_per_shift=1,
            simulation_days=14,
            auto_min_officers=True,
        )
        result = simulate_schedule(cfg)
        self.assertTrue(result.success, result.message)
        self.assertTrue(result.metrics.get("auto_sized") or result.metrics.get("min_officers_required", 0) >= 1)

    def test_extra_window_metrics_tracked(self):
        from simulator import SimulatorConfig, simulate_schedule

        # High min on every day for a long window — likely some shortfall with few officers
        cfg = SimulatorConfig(
            rotation_type="2-2-3 (14-day)",
            num_officers=6,
            shift_length_hours=11.0,
            annual_hours_target=2080,
            shift_starts=["06:00", "14:00", "22:00"],
            apply_department_rules=False,
            min_per_shift=1,
            simulation_days=14,
            auto_min_officers=False,
            use_extra_windows=True,
            extra_windows=[
                {
                    "min_officers": 8,
                    "start_time": "00:00",
                    "end_time": "23:59",
                    "weekday": None,
                    "label": "always full",
                    "enabled": True,
                }
            ],
        )
        result = simulate_schedule(cfg)
        self.assertTrue(result.success, result.message)
        self.assertGreaterEqual(result.metrics.get("extra_windows_active", 0), 1)
        self.assertIn("extra_window_failures", result.metrics)
        # Unrealistic min 8 with 6 officers → expect failures
        self.assertGreater(result.metrics.get("extra_window_failures", 0), 0)

    def test_optimizer_respects_locked_min_per_shift(self):
        from logic.scheduling_sim import run_staffing_optimizer

        result = run_staffing_optimizer(
            rotation_types=["2-2-3 (14-day)"],
            officer_counts=[12, 16],
            min_per_shift_options=[2],
            shift_starts=["06:00", "14:00", "22:00"],
            shift_length_hours=11.0,
            annual_hours_target=2080,
            simulation_days=14,
        )
        self.assertTrue(result.get("success"), result.get("message"))
        for row in result.get("ranked") or []:
            self.assertEqual(int(row["min_per_shift"]), 2)
        applied = result.get("constraints_applied") or {}
        self.assertEqual(applied.get("min_per_shift_options"), [2])

    def test_optimizer_passes_coverage_247_constraint(self):
        from logic.scheduling_sim import run_staffing_optimizer

        result = run_staffing_optimizer(
            rotation_types=["2-2-3 (14-day)"],
            officer_counts=[16],
            min_per_shift_options=[1],
            shift_starts=["06:00", "14:00", "22:00"],
            shift_length_hours=11.0,
            annual_hours_target=2080,
            simulation_days=7,
            coverage_247=1,
            require_hard_ok=False,
        )
        applied = result.get("constraints_applied") or {}
        self.assertEqual(applied.get("coverage_247"), 1)
        # At least ran with constraint recorded
        self.assertGreaterEqual(result.get("scenarios_evaluated", 0), 1)

    def test_simulator_label_minimum_officers_per_shift(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent / "gui" / "pages" / "simulator"
        # Package split: page + panels (legacy monolithic simulator.py removed)
        parts = []
        for name in (
            "page.py",
            "options_panel.py",
            "publish_panel.py",
            "results_panel.py",
            "helpers.py",
        ):
            p = root / name
            if p.is_file():
                parts.append(p.read_text(encoding="utf-8"))
        text = "\n".join(parts)
        self.assertTrue(text.strip(), "simulator package sources missing")
        # Core product chrome + hard search wiring (package split may move labels)
        for needle in (
            "Minimum Officers Per Shift",
            "Requirements",
            "Coverage options",
            "Publish",
            "require_hard_ok=True",
            "Soften",
            "priority & weights",
            "estimate_staffing_search_space",
            "apply_department_rules=False",
            '"Fixed"',
            '"Rotating"',
            "6-2,5-3",
            "_set_enabled",
            "grid-template-columns:",
            "sim-lock-row",
            "explain_ranked_option",
            "Real-world 8h pack",
            "Load saved scenario",
            "export_search_audit_json",
            "Min officers",
            "format_checklist_line",
            "linear_progress",
            "Search history",
            "export_form_config_json",
            "Pin selected",
            "Share best",
            "Window failures",
            "constraint_weights",
            "Save → A",
        ):
            self.assertIn(needle, text, f"missing UI/wiring: {needle}")
        self.assertNotIn("plan_score", text)
        self.assertIn("search_depth", text)
        self.assertIn("sim-hero", text)
        self.assertIn("_paint_kpis", text)

    def test_pack_window_band_capacity_night(self):
        from logic.staffing_optimizer import (
            pack_meets_window_bands,
            pack_window_band_capacity,
        )

        # Classic 06/14/22: at least one band covers every overnight sample
        cap = pack_window_band_capacity(["06:00", "14:00", "22:00"], 8.0, "19:00", "03:00")
        self.assertGreaterEqual(cap, 1)
        self.assertTrue(
            pack_meets_window_bands(
                ["06:00", "14:00", "22:00"],
                8.0,
                [
                    {
                        "min_officers": 2,
                        "start_time": "19:00",
                        "end_time": "03:00",
                        "enabled": True,
                    }
                ],
                num_officers=8,
            )
        )
        # Evening pack denser (more bands)
        cap2 = pack_window_band_capacity(["06:00", "14:00", "19:00", "22:00"], 8.0, "19:00", "03:00")
        self.assertGreaterEqual(cap2, cap)
        # Day-only pack: no overnight cover
        self.assertFalse(
            pack_meets_window_bands(
                ["07:00", "15:00"],
                8.0,
                [
                    {
                        "min_officers": 2,
                        "start_time": "19:00",
                        "end_time": "03:00",
                        "enabled": True,
                    }
                ],
            )
        )
        # Need > N is impossible
        self.assertFalse(
            pack_meets_window_bands(
                ["06:00", "14:00", "22:00"],
                8.0,
                [
                    {
                        "min_officers": 8,
                        "start_time": "00:00",
                        "end_time": "23:59",
                        "enabled": True,
                    }
                ],
                num_officers=6,
            )
        )

    def test_optimizer_features_presets_and_exports(self):
        from logic.optimizer_features import (
            constraint_checklist,
            diversify_ranked,
            early_impossible_proof,
            export_ranked_options_csv,
            get_real_world_8h_preset,
            get_window_template,
            load_form_snapshot,
            multi_block_annual_lines,
            near_miss_deltas,
            save_form_snapshot,
            suggest_unlocks,
            why_best_lines,
        )

        p = get_real_world_8h_preset()
        self.assertEqual(p["shift_length_hours"], 8.0)
        self.assertEqual(len(get_window_template("fri_sat_night")), 2)
        self.assertIsNotNone(
            early_impossible_proof(
                num_officers=1,
                shift_length_hours=8,
                annual_hours_target=2008,
                annual_hours_variance=20,
                annual_hours_hard=True,
                rotation_variations=["6-2,5-3"],
                coverage_247=2,
                window_min=2,
            )
        )
        rows = diversify_ranked(
            [
                {"rank": 1, "shift_starts": ["06:00"], "num_officers": 8},
                {"rank": 2, "shift_starts": ["06:00"], "num_officers": 8},
                {"rank": 3, "shift_starts": ["07:00"], "num_officers": 9},
            ],
            limit=3,
        )
        self.assertEqual(len(rows), 3)
        cl = constraint_checklist({"hard_constraints_ok": True, "metrics": {"extra_window_failures": 0}})
        self.assertTrue(any(x.get("ok") for x in cl))
        miss = near_miss_deltas({"metrics": {"extra_window_failures": 2}})
        self.assertTrue(miss)
        tips = suggest_unlocks({"impossible": True, "failure_histogram": {"window": 3}})
        self.assertTrue(tips)
        why = why_best_lines({"best": {"hard_constraints_ok": True, "num_officers": 8, "shift_starts": ["06:00"]}})
        self.assertTrue(why)
        exp = export_ranked_options_csv([{"rank": 1, "num_officers": 8, "shift_starts": ["06:00"], "summary": "t"}])
        self.assertTrue(exp.get("success"), exp)
        self.assertTrue(exp.get("path"))
        ann = multi_block_annual_lines(["6-2,5-3", "6-3,5-2"], 8.0, target=2008, variance=20)
        self.assertTrue(any("200" in x for x in ann))
        self.assertTrue(save_form_snapshot({"length": "8"}).get("success"))
        self.assertEqual((load_form_snapshot() or {}).get("length"), "8")
        from logic.optimizer_features import (
            coverage_heat_grid,
            explain_window_failures,
            format_share_message,
            list_pinned_options,
            load_scenario_slots,
            pin_option,
            save_scenario_slot,
            weights_from_sliders,
        )

        self.assertTrue(pin_option({"rank": 1, "num_officers": 8, "shift_starts": ["06:00"]}).get("success"))
        self.assertGreaterEqual(len(list_pinned_options()), 1)
        self.assertTrue(save_scenario_slot("A", config={"num_officers": 8}).get("success"))
        self.assertIn("A", load_scenario_slots())
        self.assertTrue(
            any("Heat" in x or "coverage" in x.lower() or "No coverage" in x for x in coverage_heat_grid({}))
        )
        self.assertTrue(explain_window_failures({"metrics": {"extra_window_failures": 1}}))
        self.assertIn("Chronos", format_share_message({"message": "x", "best": {"num_officers": 8}}))
        w = weights_from_sliders({"windows": 55})
        self.assertEqual(w["windows"], 55.0)
        from logic.optimizer_features import export_coverage_heat_png

        heat = export_coverage_heat_png(
            {
                "coverage_by_day": [
                    {
                        "date": "2026-07-10",
                        "working_officers": 4,
                        "shift_counts": {"06:00": 2, "14:00": 1, "22:00": 1},
                    }
                ]
            }
        )
        self.assertTrue(heat.get("success"), heat)
        self.assertEqual(heat.get("format"), "png")
        self.assertTrue(str(heat.get("path") or "").endswith(".png"))

    def test_phase_priority_and_window_floor(self):
        """Priority phase set smaller than full; window floor uses min_officers."""
        from logic.plan_explain import explain_ranked_option, explain_staffing_result
        from logic.staffing_optimizer import (
            _window_body_floor,
            generate_phase_layouts,
        )

        pri = generate_phase_layouts(8, 14, mode="priority")
        full = generate_phase_layouts(8, 14, mode="full")
        self.assertGreaterEqual(len(full), len(pri))
        self.assertGreaterEqual(len(pri), 4)
        self.assertEqual(
            _window_body_floor(
                [{"min_officers": 2, "enabled": True}, {"min_officers": 3, "enabled": False}],
                use_windows=True,
            ),
            2,
        )
        lines = explain_ranked_option(
            {
                "shift_starts": ["06:00", "14:00", "19:00"],
                "rotation_variations": ["6-2,5-3", "6-3,5-2"],
                "hard_constraints_ok": True,
                "summary": "8 Officers · Meets Selected Constraints",
            }
        )
        joined = "\n".join(lines)
        self.assertIn("06:00", joined)
        self.assertIn("Multi-Block", joined)
        self.assertIn("Hard Constraints: Met", joined)
        exp = explain_staffing_result(
            {
                "success": True,
                "message": "Best Option: demo",
                "scenarios_evaluated": 42,
                "best": {
                    "rank": 1,
                    "num_officers": 8,
                    "shift_starts": ["06:00", "14:00", "22:00"],
                    "hard_constraints_ok": True,
                },
            }
        )
        self.assertTrue(any("Layouts Checked" in x for x in exp))
        self.assertTrue(any("Best Option" in x for x in exp))

    def test_real_world_eight_hour_multiblock_annual_and_nights(self):
        """8h + 6-2,5-3 ≈ 2008 annual; Fri/Sat night + 24/7 hard with 8 officers."""
        from logic.scheduling_sim import run_schedule_simulation, run_staffing_optimizer

        windows = [
            {
                "min_officers": 2,
                "start_time": "19:00",
                "end_time": "03:00",
                "weekday": 4,
                "label": "Friday Night",
                "enabled": True,
            },
            {
                "min_officers": 2,
                "start_time": "19:00",
                "end_time": "03:00",
                "weekday": 5,
                "label": "Saturday Night",
                "enabled": True,
            },
        ]
        # Pattern math: 11/16 * 365 * 8 = 2007.5
        result = run_schedule_simulation(
            rotation_type="2-2-3 (14-day)",
            num_officers=8,
            shift_length_hours=8.0,
            annual_hours_target=2008,
            shift_starts=["06:00", "14:00", "22:00"],
            min_per_shift=1,
            simulation_days=28,
            annual_hours_variance=20,
            annual_hours_hard=True,
            coverage_247=1,
            rotation_style="rotating",
            rotation_variations=["6-2,5-3", "6-3,5-2"],
            stagger_phases=True,
            auto_min_officers=False,
            apply_department_rules=False,
            use_extra_windows=True,
            extra_windows=windows,
        )
        self.assertTrue(result.get("success"), result.get("message"))
        m = result.get("metrics") or {}
        self.assertTrue(m.get("hard_constraints_ok"), m)
        self.assertEqual(int(m.get("extra_window_failures") or 0), 0)
        self.assertEqual(int(m.get("coverage_247_failures") or 0), 0)
        self.assertEqual(int(m.get("gap_events") or 0), 0)
        self.assertEqual(int(m.get("annual_band_outside") or 0), 0)
        # Year-average uses 365.25d → 11/16×365.25×8 ≈ 2008.9 (not exact 365)
        self.assertAlmostEqual(float(m.get("avg_annual_hours") or 0), 2008.9, delta=2.0)

        opt = run_staffing_optimizer(
            rotation_types=["2-2-3 (14-day)"],
            officer_counts=[7, 8, 9],
            min_per_shift_options=[1],
            shift_length_hours=8.0,
            shift_starts=["06:00", "14:00", "22:00"],
            annual_hours_target=2008,
            simulation_days=28,
            coverage_247=1,
            annual_hours_variance=20,
            annual_hours_hard=True,
            use_extra_windows=True,
            extra_windows=windows,
            require_hard_ok=True,
            rotation_style="rotating",
            rotation_variations=["6-2,5-3", "6-3,5-2"],
        )
        self.assertTrue(opt.get("success"), opt.get("message"))
        best = opt.get("best") or {}
        # Deep phase search can hard-OK at 7; never prefer under-min without hard_ok
        self.assertGreaterEqual(int(best.get("num_officers") or 0), 7)
        self.assertTrue(best.get("hard_constraints_ok"))
        self.assertNotIn("score", best)
        # Exhaustive space (no eval cap) — multi-block × N grid ≫ old ~10 product
        self.assertGreaterEqual(int(opt.get("scenarios_evaluated") or 0), 50)
        self.assertTrue(opt.get("search_exhaustive"))
        self.assertFalse(opt.get("budget_exhausted"))

    def test_generate_and_optimize_use_synthetic_rules(self):
        from logic.scheduling_sim import run_schedule_simulation, run_staffing_optimizer

        sim = run_schedule_simulation(
            rotation_type="2-2-3 (14-day)",
            num_officers=12,
            shift_length_hours=11.0,
            annual_hours_target=2080,
            shift_starts=["06:00", "14:00", "22:00"],
            min_per_shift=1,
            simulation_days=14,
            auto_min_officers=False,
        )
        self.assertTrue(sim.get("success"), sim.get("message"))
        self.assertIn("message", sim)
        self.assertFalse((sim.get("simulation_config") or {}).get("apply_department_rules", True))

        opt = run_staffing_optimizer(
            rotation_types=["2-2-3 (14-day)"],
            officer_counts=[12],
            min_per_shift_options=[1],
            shift_starts=["06:00", "14:00", "22:00"],
            shift_length_hours=11.0,
            annual_hours_target=2080,
            simulation_days=14,
            require_hard_ok=True,
        )
        self.assertTrue(opt.get("success"), opt.get("message"))
        self.assertGreaterEqual(opt.get("scenarios_kept", 0), 1)
        best = opt.get("best") or {}
        self.assertNotIn("score", best)

    def test_optimizer_hard_rejects_impossible_windows(self):
        from logic.scheduling_sim import run_staffing_optimizer

        windows = [
            {
                "min_officers": 8,
                "start_time": "00:00",
                "end_time": "23:59",
                "weekday": None,
                "label": "Always Full",
                "enabled": True,
            }
        ]
        hard = run_staffing_optimizer(
            rotation_types=["2-2-3 (14-day)"],
            officer_counts=[6],
            min_per_shift_options=[1],
            shift_starts=["06:00", "14:00", "22:00"],
            shift_length_hours=11.0,
            annual_hours_target=2080,
            simulation_days=7,
            use_extra_windows=True,
            extra_windows=windows,
            require_hard_ok=True,
        )
        self.assertFalse(hard.get("success"))
        self.assertTrue(hard.get("impossible"))
        self.assertGreaterEqual(hard.get("rejected_hard_constraints", 0), 1)
        # Must surface closest alternatives — not empty silence
        near = hard.get("near_misses") or []
        self.assertGreaterEqual(len(near), 1, "impossible search must return near-miss options")
        self.assertTrue(near[0].get("failed_constraints") or near[0].get("summary"))
        self.assertFalse(hard.get("budget_exhausted"))
        self.assertTrue(hard.get("search_exhaustive"))

        soft = run_staffing_optimizer(
            rotation_types=["2-2-3 (14-day)"],
            officer_counts=[6],
            min_per_shift_options=[1],
            shift_starts=["06:00", "14:00", "22:00"],
            shift_length_hours=11.0,
            annual_hours_target=2080,
            simulation_days=7,
            use_extra_windows=True,
            extra_windows=windows,
            require_hard_ok=False,
        )
        self.assertTrue(soft.get("success"), soft.get("message"))
        metrics = (soft.get("best") or {}).get("metrics") or {}
        self.assertGreater(metrics.get("extra_window_failures", 0), 0)

    def test_start_packs_half_hour_only(self):
        from logic.staffing_optimizer import generate_start_packs

        packs = generate_start_packs(8)
        self.assertGreaterEqual(len(packs), 3)
        for pack in packs:
            for start in pack:
                self.assertTrue(
                    start.endswith(":00") or start.endswith(":30"),
                    f"non half-hour start {start!r} in {pack}",
                )
        # Must model 2p + 7p style swings (not only equal 06/14/22)
        joined = ["|".join(p) for p in packs]
        self.assertTrue(
            any("19:00" in j and "14:00" in j for j in joined),
            f"expected 14:00+19:00 evening pack in {packs[:10]}",
        )

    def test_seven_officers_evening_starts_hard_ok(self):
        """7 officers + 24/7 min1 + Fri/Sat 19–03 min2 + 2008h rotating multi-block."""
        from logic.scheduling_sim import run_schedule_simulation, run_staffing_optimizer

        windows = [
            {
                "min_officers": 2,
                "start_time": "19:00",
                "end_time": "03:00",
                "weekday": 4,
                "label": "Friday Night",
                "enabled": True,
            },
            {
                "min_officers": 2,
                "start_time": "19:00",
                "end_time": "03:00",
                "weekday": 5,
                "label": "Saturday Night",
                "enabled": True,
            },
        ]
        # 4-band with 19:00 (2p/7p style) + daily rebalance among pack
        sim = run_schedule_simulation(
            rotation_type="2-2-3 (14-day)",
            num_officers=7,
            shift_length_hours=8.0,
            annual_hours_target=2008,
            shift_starts=["06:00", "14:00", "19:00", "22:00"],
            min_per_shift=1,
            simulation_days=28,
            annual_hours_variance=20,
            annual_hours_hard=True,
            coverage_247=1,
            rotation_style="rotating",
            rotation_variations=["6-2,5-3", "6-3,5-2"],
            stagger_phases=True,
            auto_min_officers=False,
            apply_department_rules=False,
            use_extra_windows=True,
            extra_windows=windows,
        )
        self.assertTrue(sim.get("success"), sim.get("message"))
        self.assertTrue((sim.get("metrics") or {}).get("hard_constraints_ok"))

        # Free starts must find ≥1 hard-OK pack at N=7 (rotation free enough via phases)
        opt = run_staffing_optimizer(
            rotation_types=["2-2-3 (14-day)"],
            officer_counts=[7],
            min_per_shift_options=[1],
            shift_length_hours=8.0,
            free_starts=True,
            annual_hours_target=2008,
            annual_hours_variance=20,
            annual_hours_hard=True,
            coverage_247=1,
            use_extra_windows=True,
            extra_windows=windows,
            require_hard_ok=True,
            rotation_style="rotating",
            rotation_variations=["6-2,5-3", "6-3,5-2"],
            stagger_phases=True,
        )
        self.assertTrue(opt.get("success"), opt.get("message"))
        best = opt.get("best") or {}
        self.assertEqual(int(best.get("num_officers") or 0), 7)
        ranked = opt.get("ranked") or []
        self.assertGreaterEqual(len(ranked), 1)
        packs = {tuple(r.get("shift_starts") or []) for r in ranked}
        # At least one pack includes evening capability (19:00 or 14+late)
        ok_pack = False
        for p in packs:
            hours = []
            for s in p:
                try:
                    hours.append(int(str(s).split(":")[0]))
                except ValueError:
                    pass
            if 19 in hours or (any(12 <= h < 19 for h in hours) and any(h >= 20 or h < 5 for h in hours)):
                ok_pack = True
        self.assertTrue(ok_pack, f"no evening-capable pack in {packs}")

    def test_optimizer_progress_and_cancel(self):
        from logic.scheduling_sim import run_staffing_optimizer

        phases = []

        def on_progress(info):
            if isinstance(info, dict) and info.get("phase"):
                phases.append(info["phase"])

        n = {"i": 0}

        def cancel():
            n["i"] += 1
            return n["i"] > 8

        cancelled = run_staffing_optimizer(
            rotation_types=["2-2-3 (14-day)"],
            officer_counts=[8, 9, 10],
            min_per_shift_options=[1],
            shift_length_hours=8.0,
            free_starts=True,
            rotation_style="rotating",
            rotation_variations=["6-2,5-3", "6-3,5-2"],
            require_hard_ok=True,
            progress_callback=on_progress,
            cancel_check=cancel,
        )
        self.assertTrue(cancelled.get("cancelled"))
        self.assertFalse(cancelled.get("search_exhaustive"))
        self.assertTrue(phases)

    def test_estimate_search_space_warns_when_unconstrained(self):
        from logic.scheduling_sim import estimate_staffing_search_space

        free = estimate_staffing_search_space(
            rotation_types=["2-2-3 (14-day)"],
            free_officer_counts=True,
            free_starts=True,
            free_lengths=True,
            min_per_shift_options=[1, 2],
            rotation_style="rotating",
            rotation_variations=["6-2,5-3", "6-3,5-2"],
        )
        self.assertGreater(free.get("total_layouts") or 0, 10_000)
        self.assertIn(free.get("risk"), ("high", "extreme"))
        self.assertTrue(free.get("requires_confirm"))
        self.assertTrue(free.get("warning"))

        locked = estimate_staffing_search_space(
            rotation_types=["2-2-3 (14-day)"],
            officer_counts=[8],
            min_per_shift_options=[1],
            shift_length_hours=8.0,
            shift_starts=["06:00", "14:00", "22:00"],
            rotation_style="rotating",
            rotation_variations=["6-2,5-3", "6-3,5-2"],
        )
        self.assertLess(locked.get("total_layouts") or 0, free.get("total_layouts") or 0)

    def test_export_simulation_csv_safe_path(self):
        import os

        from logic import export_simulation_csv
        from logic.scheduling_sim import run_schedule_simulation

        sim = run_schedule_simulation(
            rotation_type="2-2-3 (14-day)",
            num_officers=8,
            shift_length_hours=11.0,
            annual_hours_target=2080,
            shift_starts=["06:00", "14:00", "22:00"],
            min_per_shift=1,
            simulation_days=7,
            auto_min_officers=False,
        )
        self.assertTrue(sim.get("success"), sim.get("message"))
        exp = export_simulation_csv(sim)
        self.assertTrue(exp.get("success"), exp.get("message"))
        path = exp.get("path") or ""
        base = os.path.basename(path)
        self.assertTrue(base.startswith("simulation_"), path)
        self.assertNotIn("/", base)
        self.assertNotIn("\\", base)
        # ISO date fragment
        self.assertRegex(base, r"simulation_\d{4}-\d{2}-\d{2}\.csv")

    def test_implement_without_persistent_defaults(self):
        from logic import implement_optimized_plan
        from logic.scheduling_sim import run_schedule_simulation

        sim = run_schedule_simulation(
            rotation_type="2-2-3 (14-day)",
            num_officers=12,
            shift_length_hours=11.0,
            annual_hours_target=2080,
            shift_starts=["06:00", "14:00", "22:00"],
            min_per_shift=1,
            simulation_days=14,
            auto_min_officers=False,
        )
        self.assertTrue(sim.get("success"), sim.get("message"))
        cfg = sim.get("simulation_config") or {}
        r = implement_optimized_plan(
            start_date="7/20/26",
            result=sim,
            config=cfg,
            user_id=1,
            apply_officer_assignments=False,
            force_regenerate=True,
            save_as_defaults=False,
        )
        self.assertTrue(r.get("success"), r.get("message"))

    def test_home_nearby_start_flex_and_offday_default_off(self):
        """Home 19:00 may move ±hops on ON days; off-day coverage default OFF."""
        from simulator import (
            SimulatorConfig,
            assign_pack_starts_for_coverage,
            simulate_schedule,
        )

        pack = ["06:00", "14:00", "19:00", "22:00"]
        bands = assign_pack_starts_for_coverage(
            4,
            pack,
            8.0,
            home_starts=["19:00", "19:00", "19:00", "19:00"],
            fri_sat_window=True,
            nearby_hops=1,
        )
        starts = [b[0] for b in bands]
        self.assertEqual(len(starts), 4)
        self.assertIn("19:00", starts)

        windows = [
            {
                "min_officers": 2,
                "start_time": "19:00",
                "end_time": "03:00",
                "weekday": 4,
                "label": "Friday Night",
                "enabled": True,
            },
            {
                "min_officers": 2,
                "start_time": "19:00",
                "end_time": "03:00",
                "weekday": 5,
                "label": "Saturday Night",
                "enabled": True,
            },
        ]
        # Default: ON days only — offday must stay 0
        cfg = SimulatorConfig(
            rotation_type="2-2-3 (14-day)",
            num_officers=8,
            shift_length_hours=8.0,
            annual_hours_target=2008,
            shift_starts=pack,
            apply_department_rules=False,
            min_per_shift=1,
            simulation_days=28,
            annual_hours_variance=20,
            annual_hours_hard=True,
            coverage_247=1,
            rotation_style="rotating",
            rotation_variations=["6-2,5-3", "6-3,5-2"],
            stagger_phases=True,
            auto_min_officers=False,
            use_extra_windows=True,
            extra_windows=windows,
            nearby_start_hops=2,
            allow_offday_coverage=False,
        )
        result = simulate_schedule(cfg)
        self.assertTrue(result.success, result.message)
        m = result.metrics or {}
        self.assertTrue(m.get("hard_constraints_ok"), m)
        self.assertEqual(int(m.get("nearby_start_hops") or 0), 2)
        self.assertFalse(m.get("allow_offday_coverage"))
        self.assertEqual(int(m.get("offday_coverage_assignments") or 0), 0)

        # Opt-in off-day may assign OT (not required to fire, but flag must stick)
        cfg2 = SimulatorConfig(
            rotation_type="2-2-3 (14-day)",
            num_officers=6,
            shift_length_hours=8.0,
            annual_hours_target=2008,
            shift_starts=pack,
            apply_department_rules=False,
            min_per_shift=1,
            simulation_days=28,
            annual_hours_variance=20,
            annual_hours_hard=True,
            coverage_247=1,
            rotation_style="rotating",
            rotation_variations=["6-2,5-3", "6-3,5-2"],
            stagger_phases=True,
            auto_min_officers=False,
            use_extra_windows=True,
            extra_windows=windows,
            nearby_start_hops=1,
            allow_offday_coverage=True,
        )
        r2 = simulate_schedule(cfg2)
        self.assertTrue(r2.success, r2.message)
        m2 = r2.metrics or {}
        self.assertTrue(m2.get("allow_offday_coverage"))
        self.assertIn("offday_coverage_assignments", m2)


if __name__ == "__main__":
    unittest.main()
