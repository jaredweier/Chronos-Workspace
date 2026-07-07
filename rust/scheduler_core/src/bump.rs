use std::collections::{HashMap, HashSet};

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

use crate::coverage::compute_shift_coverage_counts;
use crate::rotation::{is_high_risk_night_ordinal, parse_ymd, RotationSchedule};
use crate::status::{Officer, OverrideMaps, officer_day_status};

#[derive(Clone)]
pub struct OfficerFull {
    pub id: i64,
    pub name: String,
    pub squad: String,
    pub shift_start: String,
    pub shift_end: String,
    pub active: bool,
}

fn is_night_shift(shift_start: &str) -> bool {
    let hour: i32 = shift_start
        .split(':')
        .next()
        .and_then(|h| h.parse().ok())
        .unwrap_or(12);
    hour >= 18 || hour < 6
}

fn shift_end_for(start: &str, shift_times: &[(String, String)]) -> String {
    for (s, e) in shift_times {
        if s == start {
            return e.clone();
        }
    }
    start.to_string()
}

fn parse_minutes(value: &str) -> i32 {
    let parts: Vec<&str> = value.split(':').collect();
    if parts.len() < 2 {
        return 0;
    }
    let h: i32 = parts[0].parse().unwrap_or(0);
    let m: i32 = parts[1].parse().unwrap_or(0);
    h * 60 + m
}

fn schedule_working(status: &str) -> bool {
    matches!(status, "working" | "covering" | "swapped" | "training")
}

fn replacement_shift_for_rules(officer: &OfficerFull, day_context: Option<&(String, String)>) -> String {
    if let Some((status, assigned)) = day_context {
        if schedule_working(status) && !assigned.is_empty() {
            return assigned.clone();
        }
    }
    officer.shift_start.clone()
}

fn can_cover_shift(replacement_start: &str, covered_start: &str, bump_rules: &HashMap<String, Vec<String>>) -> bool {
    if replacement_start.is_empty() || covered_start.is_empty() {
        return false;
    }
    bump_rules
        .get(covered_start)
        .map(|allowed| allowed.iter().any(|s| s == replacement_start))
        .unwrap_or(false)
}

fn assignment_exhausted(officer_id: i64, counts: &HashMap<i64, i32>, max_assignments: i32) -> bool {
    counts.get(&officer_id).copied().unwrap_or(0) >= max_assignments
}

fn rest_gap_hours(
    officer_id: i64,
    assignment_ordinal: i32,
    new_start: &str,
    new_end: &str,
    officers: &[OfficerFull],
    maps: &OverrideMaps,
    base_ordinal: i32,
    schedule: &RotationSchedule,
    shift_times: &[(String, String)],
) -> Option<f64> {
    let officer = officers.iter().find(|o| o.id == officer_id)?;
    let new_start_min = parse_minutes(new_start);
    let new_end_min = parse_minutes(new_end);
    let mut min_gap: Option<f64> = None;

    for delta in [-1i32, 1] {
        let adj_ord = assignment_ordinal + delta;
        let date_key = crate::status::ordinal_to_iso_public(adj_ord);
        let status = officer_day_status(
            &Officer {
                id: officer.id,
                squad: officer.squad.clone(),
                shift_start: officer.shift_start.clone(),
                active: officer.active,
            },
            &date_key,
            adj_ord,
            base_ordinal,
            schedule,
            maps,
        );
        if !matches!(status.as_str(), "working" | "covering" | "swapped") {
            continue;
        }
        let band_start = officer.shift_start.clone();
        let band_end = shift_end_for(&band_start, shift_times);
        let adj_start = parse_minutes(&band_start);
        let adj_end = parse_minutes(&band_end);

        let gap = if delta == -1 {
            let new_start_abs = assignment_ordinal * 1440 + new_start_min;
            let adj_end_abs = adj_ord * 1440 + if adj_end <= adj_start { adj_end + 1440 } else { adj_end };
            (new_start_abs - adj_end_abs) as f64 / 60.0
        } else {
            let adj_start_abs = adj_ord * 1440 + adj_start;
            let new_end_abs = assignment_ordinal * 1440
                + if new_end_min <= new_start_min {
                    new_end_min + 1440
                } else {
                    new_end_min
                };
            (adj_start_abs - new_end_abs) as f64 / 60.0
        };
        min_gap = Some(min_gap.map_or(gap, |g| g.min(gap)));
    }
    min_gap
}

fn find_replacement(
    original_id: i64,
    shift_start: &str,
    officers: &[OfficerFull],
    assignment_counts: &HashMap<i64, i32>,
    max_assignments: i32,
    bump_rules: &HashMap<String, Vec<String>>,
    day_context: &HashMap<i64, (String, String)>,
    chain_replacements: &HashSet<i64>,
    shift_times: &[(String, String)],
    maps: &OverrideMaps,
    base_ordinal: i32,
    schedule: &RotationSchedule,
    min_rest_hours: f64,
    request_date: &str,
) -> Option<OfficerFull> {
    let req_ord = parse_ymd(request_date).ok()?;
    let coverage_end = shift_end_for(shift_start, shift_times);

    let mut candidates: Vec<&OfficerFull> = officers
        .iter()
        .filter(|o| {
            o.active
                && o.id != original_id
                && !chain_replacements.contains(&o.id)
                && !assignment_exhausted(o.id, assignment_counts, max_assignments)
                && can_cover_shift(
                    &replacement_shift_for_rules(o, day_context.get(&o.id)),
                    shift_start,
                    bump_rules,
                )
        })
        .collect();
    candidates.sort_by_key(|o| o.id);

    let mut on_duty = None;
    let mut off_rest_ok = None;
    let mut off_rest_bad = None;

    for off in candidates {
        let ctx = day_context.get(&off.id);
        let working = ctx.map(|(s, _)| schedule_working(s)).unwrap_or(false);
        if working {
            on_duty = on_duty.or(Some((*off).clone()));
        } else {
            let gap = rest_gap_hours(
                off.id,
                req_ord,
                shift_start,
                &coverage_end,
                officers,
                maps,
                base_ordinal,
                schedule,
                shift_times,
            );
            if gap.map_or(false, |g| g >= min_rest_hours) {
                off_rest_ok = off_rest_ok.or(Some((*off).clone()));
            } else {
                off_rest_bad = off_rest_bad.or(Some((*off).clone()));
            }
        }
    }
    off_rest_ok.or(off_rest_bad).or(on_duty)
}

fn night_minimum_uncovered(
    request_date: &str,
    squad: &str,
    shift_start: &str,
    officers: &[Officer],
    overrides_on_date: &[(i64, Option<i64>, Option<String>, String)],
    shift_starts: &[String],
    base_ordinal: i32,
    schedule: &RotationSchedule,
    night_minimum: i32,
) -> bool {
    if !is_high_risk_night_ordinal(parse_ymd(request_date).unwrap_or(0)) || !is_night_shift(shift_start) {
        return false;
    }
    let override_rows: Vec<(String, i64, Option<i64>, Option<String>)> = overrides_on_date
        .iter()
        .map(|(o, r, c, _)| (request_date.to_string(), *o, *r, c.clone()))
        .collect();
    let counts = compute_shift_coverage_counts(
        officers,
        &override_rows,
        request_date,
        request_date,
        shift_starts,
        base_ordinal,
        schedule.cycle_length,
    )
    .unwrap_or_default();
    let current = counts
        .get(&(request_date.to_string(), squad.to_string(), shift_start.to_string()))
        .copied()
        .unwrap_or(0);
    current <= night_minimum
}

pub fn suggest_bump_chain_py(
    py: Python<'_>,
    officers: Vec<OfficerFull>,
    overrides_on_date: &[(i64, Option<i64>, Option<String>, String)],
    original_officer_id: i64,
    request_date: &str,
    squad: &str,
    shift_start: &str,
    bump_rules: HashMap<String, Vec<String>>,
    shift_times: Vec<(String, String)>,
    day_context: HashMap<i64, (String, String)>,
    night_minimum: i32,
    min_rest_hours: f64,
    base_ordinal: i32,
    schedule: RotationSchedule,
    max_assignments_before_busy: i32,
    max_depth: usize,
) -> PyResult<PyObject> {
    let req_ord = parse_ymd(request_date)?;

    let mut maps = OverrideMaps {
        bumped: HashMap::new(),
        covering: HashMap::new(),
        swapped: HashMap::new(),
        bumped_status: HashMap::new(),
    };
    for (orig, repl, _cov, reason) in overrides_on_date {
        maps.bumped
            .entry(request_date.to_string())
            .or_default()
            .insert(*orig);
        if reason == "Shift Swap" {
            maps.swapped
                .entry(request_date.to_string())
                .or_default()
                .insert(*orig);
            if let Some(r) = repl {
                maps.swapped.entry(request_date.to_string()).or_default().insert(*r);
            }
            continue;
        }
        if let Some(r) = repl {
            maps.covering
                .entry(request_date.to_string())
                .or_default()
                .insert(*r);
        }
    }

    let mut assignment_counts: HashMap<i64, i32> = HashMap::new();
    for (_orig, repl, _cov, _reason) in overrides_on_date {
        if let Some(r) = repl {
            *assignment_counts.entry(*r).or_insert(0) += 1;
        }
    }

    let mut chain: Vec<(i64, i64)> = Vec::new();
    let mut steps: Vec<PyObject> = Vec::new();
    let mut current_id = original_officer_id;
    let mut current_shift = shift_start.to_string();
    let shift_starts: Vec<String> = shift_times.iter().map(|(s, _)| s.clone()).collect();
    let officer_rows: Vec<Officer> = officers
        .iter()
        .map(|o| Officer {
            id: o.id,
            squad: o.squad.clone(),
            shift_start: o.shift_start.clone(),
            active: o.active,
        })
        .collect();

    for _ in 0..max_depth {
        let chain_replacements: HashSet<i64> = chain.iter().map(|(_, r)| *r).collect();
        let Some(current) = officers.iter().find(|o| o.id == current_id) else {
            return dict_result(
                py,
                false,
                "Officer not found while planning coverage",
                true,
                Some("officer_missing"),
                steps,
                chain,
                None,
            );
        };

        let replacement = find_replacement(
            current_id,
            &current_shift,
            &officers,
            &assignment_counts,
            max_assignments_before_busy,
            &bump_rules,
            &day_context,
            &chain_replacements,
            &shift_times,
            &maps,
            base_ordinal,
            &schedule,
            min_rest_hours,
            request_date,
        );

        let Some(repl) = replacement else {
            if night_minimum_uncovered(
                request_date,
                squad,
                &current_shift,
                &officer_rows,
                overrides_on_date,
                &shift_starts,
                base_ordinal,
                &schedule,
                night_minimum,
            ) {
                return dict_result(
                    py,
                    false,
                    "Cannot cover shift — would drop night coverage below minimum on a high-risk night",
                    true,
                    Some("night_minimum"),
                    steps,
                    chain,
                    None,
                );
            }
            if chain.is_empty() {
                return dict_result(
                    py,
                    false,
                    "No replacement available on an allowed shift",
                    true,
                    Some("no_replacement"),
                    steps,
                    chain,
                    None,
                );
            }
            let msg = format!(
                "Cascade incomplete — no cover for {}'s {} shift after earlier assignments",
                current.name, current_shift
            );
            return dict_result(
                py,
                false,
                &msg,
                true,
                Some("cascade_incomplete"),
                steps,
                chain,
                None,
            );
        };

        let ctx = day_context.get(&repl.id);
        let on_duty = ctx.map(|(s, _)| schedule_working(s)).unwrap_or(false);
        let repl_shift = ctx
            .and_then(|(_, assigned)| if assigned.is_empty() { None } else { Some(assigned.clone()) })
            .unwrap_or_else(|| repl.shift_start.clone());

        let step = PyDict::new_bound(py);
        step.set_item("step_number", steps.len() + 1)?;
        step.set_item("original_officer_id", current_id)?;
        step.set_item("original_officer_name", &current.name)?;
        step.set_item("original_shift", &current_shift)?;
        step.set_item("replacement_officer_id", repl.id)?;
        step.set_item("replacement_officer_name", &repl.name)?;
        step.set_item("replacement_shift", &repl_shift)?;
        step.set_item("replacement_on_duty", on_duty)?;
        steps.push(step.into());

        chain.push((current_id, repl.id));
        *assignment_counts.entry(repl.id).or_insert(0) += 1;

        if !on_duty {
            let coverage_end = shift_end_for(&current_shift, &shift_times);
            let gap = rest_gap_hours(
                repl.id,
                req_ord,
                &current_shift,
                &coverage_end,
                &officers,
                &maps,
                base_ordinal,
                &schedule,
                &shift_times,
            );
            let primary_name = officers
                .iter()
                .find(|o| o.id == chain[0].1)
                .map(|o| o.name.as_str());
            if gap.map_or(true, |g| g < min_rest_hours) {
                let msg = format!(
                    "Minimum rest violation: {} has {:.1}h between shifts (minimum {:.0}h) — supervisor override required",
                    repl.name,
                    gap.unwrap_or(0.0),
                    min_rest_hours
                );
                return dict_result(
                    py,
                    false,
                    &msg,
                    true,
                    Some("minimum_rest"),
                    steps,
                    chain,
                    primary_name,
                );
            }
            let msg = format!("Auto-approve ready — {} assignment(s)", chain.len());
            return dict_result(py, true, &msg, false, None, steps, chain, primary_name);
        }

        current_id = repl.id;
        current_shift = repl_shift;
    }

    dict_result(
        py,
        false,
        "Coverage chain too deep — supervisor must assign manually",
        true,
        Some("cascade_too_deep"),
        steps,
        chain,
        None,
    )
}

fn dict_result(
    py: Python<'_>,
    success: bool,
    message: &str,
    requires_manual: bool,
    failure_reason: Option<&str>,
    steps: Vec<PyObject>,
    chain: Vec<(i64, i64)>,
    primary_name: Option<&str>,
) -> PyResult<PyObject> {
    let d = PyDict::new_bound(py);
    d.set_item("success", success)?;
    d.set_item("message", message)?;
    d.set_item("requires_manual", requires_manual)?;
    if let Some(r) = failure_reason {
        d.set_item("failure_reason", r)?;
    }
    let steps_list = PyList::empty_bound(py);
    for s in steps {
        steps_list.append(s)?;
    }
    d.set_item("steps", steps_list)?;
    let chain_list = PyList::empty_bound(py);
    for (a, b) in chain {
        let pair = PyList::empty_bound(py);
        pair.append(a)?;
        pair.append(b)?;
        chain_list.append(pair)?;
    }
    d.set_item("chain", chain_list)?;
    if let Some(name) = primary_name {
        d.set_item("primary_replacement_name", name)?;
    }
    Ok(d.into())
}