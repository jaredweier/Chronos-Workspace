"""Persisted schedule simulator scenarios for reuse and shift-bid import."""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from database import connection
from logic.users import log_audit_action
from validators import normalize_optional_text


def save_simulator_scenario(
    name: str,
    *,
    config: Dict,
    result: Optional[Dict] = None,
    user_id: Optional[int] = None,
    notes: str = "",
    tags: Optional[List[str]] = None,
) -> Dict:
    label = normalize_optional_text(name) or "Simulator scenario"
    note_body = normalize_optional_text(notes) or ""
    tag_list = [str(t).strip() for t in (tags or []) if str(t).strip()]
    if tag_list:
        # Tags stored in notes prefix for schema compatibility (no migration)
        note_body = f"[tags:{','.join(tag_list)}] {note_body}".strip()
    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO simulator_scenarios (name, config_json, result_json, notes, created_by_user_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    label,
                    json.dumps(config or {}),
                    json.dumps(result) if result else None,
                    note_body,
                    user_id,
                ),
            )
            scenario_id = cursor.lastrowid
            conn.commit()
            log_audit_action("simulator.save_scenario", "simulator_scenario", scenario_id, user_id, label)
            return {"success": True, "scenario_id": scenario_id}
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}


def _parse_tags_from_notes(notes: Optional[str]) -> List[str]:
    raw = notes or ""
    if raw.startswith("[tags:") and "]" in raw:
        inner = raw[6 : raw.index("]")]
        return [t.strip() for t in inner.split(",") if t.strip()]
    return []


def list_simulator_scenarios(*, limit: int = 30, tag: Optional[str] = None) -> List[Dict]:
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, name, notes, created_at, created_by_user_id
            FROM simulator_scenarios
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(limit, 80) if tag else limit,),
        )
        rows = []
        for r in cursor.fetchall():
            d = dict(r)
            d["tags"] = _parse_tags_from_notes(d.get("notes"))
            if tag and tag not in d["tags"]:
                continue
            rows.append(d)
            if len(rows) >= limit:
                break
    return rows


def get_simulator_scenario(scenario_id: int) -> Optional[Dict]:
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM simulator_scenarios WHERE id = ?", (scenario_id,))
        row = cursor.fetchone()
    if not row:
        return None
    data = dict(row)
    for key in ("config_json", "result_json"):
        raw = data.get(key)
        if raw:
            try:
                data[key.replace("_json", "")] = json.loads(raw)
            except json.JSONDecodeError:
                data[key.replace("_json", "")] = {}
    return data


def load_simulator_scenario_for_bid(scenario_id: int) -> Dict:
    """Return a simulation result dict suitable for shift-bid import."""
    scenario = get_simulator_scenario(scenario_id)
    if not scenario:
        return {"success": False, "message": "Scenario not found"}
    result = scenario.get("result")
    if result and result.get("success"):
        result = dict(result)
        result["simulation_config"] = result.get("simulation_config") or scenario.get("config") or {}
        result["scenario_id"] = scenario_id
        result["scenario_name"] = scenario.get("name")
        return result

    config = scenario.get("config") or {}
    from logic.scheduling_sim import run_schedule_simulation

    rotation = config.get("rotation_type") or config.get("rotation") or "4-on-4-off"
    officers = int(config.get("num_officers") or config.get("target_officer_count") or 8)
    shift_length = float(config.get("shift_length_hours") or 10.0)
    annual_hours = float(config.get("annual_hours") or 2080.0)
    starts = config.get("shift_starts") or config.get("shift_start_times") or ["06:00"]
    if isinstance(starts, str):
        starts = [s.strip() for s in starts.split(",") if s.strip()]
    sim = run_schedule_simulation(
        rotation,
        officers,
        shift_length,
        annual_hours,
        starts,
        apply_department_rules=config.get("apply_department_rules", False),
        min_per_shift=int(config.get("min_per_shift") or 1),
    )
    if sim.get("success"):
        sim["scenario_id"] = scenario_id
        sim["scenario_name"] = scenario.get("name")
    return sim
