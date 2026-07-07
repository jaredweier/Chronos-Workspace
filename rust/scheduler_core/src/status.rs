use std::collections::{HashMap, HashSet};

use pyo3::prelude::*;

use crate::rotation::{cycle_day, parse_ymd, RotationSchedule};

#[derive(Clone)]
pub struct Officer {
    pub id: i64,
    pub squad: String,
    pub shift_start: String,
    pub active: bool,
}

pub struct OverrideMaps {
    pub bumped: HashMap<String, HashSet<i64>>,
    pub covering: HashMap<String, HashSet<i64>>,
    pub swapped: HashMap<String, HashSet<i64>>,
    pub bumped_status: HashMap<String, HashMap<i64, String>>,
}

pub fn officer_working_on_day(
    officer: &Officer,
    target_ordinal: i32,
    base_ordinal: i32,
    schedule: &RotationSchedule,
) -> bool {
    if !officer.active || officer.squad.is_empty() || officer.shift_start.is_empty() {
        return false;
    }
    let day = cycle_day(base_ordinal, target_ordinal, schedule.cycle_length);
    schedule.is_squad_working(&officer.squad, day)
}

pub fn officer_day_status(
    officer: &Officer,
    date_key: &str,
    target_ordinal: i32,
    base_ordinal: i32,
    schedule: &RotationSchedule,
    maps: &OverrideMaps,
) -> String {
    let id = officer.id;
    if maps
        .swapped
        .get(date_key)
        .map(|s| s.contains(&id))
        .unwrap_or(false)
    {
        return "swapped".to_string();
    }
    if maps.bumped.get(date_key).map(|s| s.contains(&id)).unwrap_or(false) {
        if let Some(statuses) = maps.bumped_status.get(date_key) {
            if let Some(status) = statuses.get(&id) {
                return status.clone();
            }
        }
        return "bumped".to_string();
    }
    if maps
        .covering
        .get(date_key)
        .map(|s| s.contains(&id))
        .unwrap_or(false)
    {
        return "covering".to_string();
    }
    if officer_working_on_day(officer, target_ordinal, base_ordinal, schedule) {
        return "working".to_string();
    }
    "off".to_string()
}

pub fn iter_dates(start: &str, end: &str) -> PyResult<Vec<(String, i32)>> {
    let start_ord = parse_ymd(start)?;
    let end_ord = parse_ymd(end)?;
    let mut out = Vec::new();
    let mut ord = start_ord;
    while ord <= end_ord {
        out.push((ordinal_to_iso(ord), ord));
        ord += 1;
    }
    Ok(out)
}

pub fn ordinal_to_iso_public(ordinal: i32) -> String {
    ordinal_to_iso(ordinal)
}

fn ordinal_to_iso(ordinal: i32) -> String {
    let z = ordinal + 719468;
    let era = if z >= 0 { z / 146097 } else { (z - 146096) / 146097 };
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = mp + if mp < 10 { 3 } else { -9 };
    let year = y + if m <= 2 { 1 } else { 0 };
    format!("{year:04}-{m:02}-{d:02}")
}