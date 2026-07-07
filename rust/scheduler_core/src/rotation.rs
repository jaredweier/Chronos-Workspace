use std::collections::HashSet;

use pyo3::prelude::*;
use pyo3::types::PyDict;

const DEFAULT_SQUAD_A_DAYS: [i32; 7] = [1, 2, 5, 6, 7, 10, 11];

#[derive(Clone)]
pub enum RotationMode {
    SquadADays(HashSet<i32>),
    SquadPatterns {
        pattern_a: Vec<i32>,
        pattern_b: Vec<i32>,
    },
    EqualSplit {
        work_days_per_cycle: i32,
        squads: i32,
    },
}

#[derive(Clone)]
pub struct RotationSchedule {
    pub cycle_length: i32,
    pub mode: RotationMode,
}

impl RotationSchedule {
    pub fn dodgeville_default() -> Self {
        Self {
            cycle_length: 14,
            mode: RotationMode::SquadADays(DEFAULT_SQUAD_A_DAYS.into_iter().collect()),
        }
    }

    pub fn is_squad_working(&self, squad: &str, cycle_day: i32) -> bool {
        if squad != "A" && squad != "B" {
            return false;
        }
        if cycle_day < 1 || cycle_day > self.cycle_length {
            return false;
        }
        match &self.mode {
            RotationMode::SquadADays(days) => {
                let on_a = days.contains(&cycle_day);
                if squad == "A" {
                    on_a
                } else {
                    !on_a
                }
            }
            RotationMode::SquadPatterns {
                pattern_a,
                pattern_b,
            } => {
                let pattern = if squad == "A" {
                    pattern_a
                } else {
                    pattern_b
                };
                if pattern.is_empty() {
                    return false;
                }
                let idx = ((cycle_day - 1).rem_euclid(pattern.len() as i32)) as usize;
                pattern[idx] == 1
            }
            RotationMode::EqualSplit {
                work_days_per_cycle,
                squads,
            } => {
                let squads = (*squads).max(1);
                let half = work_days_per_cycle / squads;
                if squad == "A" {
                    ((cycle_day - 1) % self.cycle_length) < half
                } else {
                    let offset = self.cycle_length / squads;
                    ((cycle_day - 1 + offset) % self.cycle_length) < half
                }
            }
        }
    }

    pub fn squad_on_duty(&self, cycle_day: i32) -> &'static str {
        if self.is_squad_working("A", cycle_day) {
            "A"
        } else {
            "B"
        }
    }
}

pub fn rotation_schedule_from_py(dict: &Bound<'_, PyDict>) -> PyResult<RotationSchedule> {
    let cycle_length: i32 = dict.get_item("cycle_length")?.unwrap().extract()?;
    let mode: String = dict.get_item("mode")?.unwrap().extract()?;
    match mode.as_str() {
        "squad_a_days" => {
            let days: Vec<i32> = dict.get_item("squad_a_days")?.unwrap().extract()?;
            Ok(RotationSchedule {
                cycle_length,
                mode: RotationMode::SquadADays(days.into_iter().collect()),
            })
        }
        "squad_patterns" => {
            let pattern_a: Vec<i32> = dict.get_item("pattern_a")?.unwrap().extract()?;
            let pattern_b: Vec<i32> = dict.get_item("pattern_b")?.unwrap().extract()?;
            Ok(RotationSchedule {
                cycle_length,
                mode: RotationMode::SquadPatterns {
                    pattern_a,
                    pattern_b,
                },
            })
        }
        "equal_split" => {
            let work_days: i32 = dict
                .get_item("work_days_per_cycle")?
                .unwrap()
                .extract()?;
            let squads: i32 = dict.get_item("squads")?.unwrap().extract()?;
            Ok(RotationSchedule {
                cycle_length,
                mode: RotationMode::EqualSplit {
                    work_days_per_cycle: work_days,
                    squads,
                },
            })
        }
        other => Err(pyo3::exceptions::PyValueError::new_err(format!(
            "unknown rotation mode: {other}"
        ))),
    }
}

pub fn parse_ymd(value: &str) -> PyResult<i32> {
    let parts: Vec<&str> = value.split('-').collect();
    if parts.len() != 3 {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "invalid date: {value}"
        )));
    }
    let y: i32 = parts[0].parse().map_err(|_| {
        pyo3::exceptions::PyValueError::new_err(format!("invalid year in {value}"))
    })?;
    let m: u32 = parts[1].parse().map_err(|_| {
        pyo3::exceptions::PyValueError::new_err(format!("invalid month in {value}"))
    })?;
    let d: u32 = parts[2].parse().map_err(|_| {
        pyo3::exceptions::PyValueError::new_err(format!("invalid day in {value}"))
    })?;
    Ok(ymd_to_ordinal(y, m, d))
}

fn ymd_to_ordinal(year: i32, month: u32, day: u32) -> i32 {
    let mut y = year;
    let mut m = month as i32;
    if m <= 2 {
        y -= 1;
        m += 12;
    }
    let era = if y >= 0 { y / 400 } else { (y - 399) / 400 };
    let yoe = y - era * 400;
    let doy = (153 * (m - 3) + 2) / 5 + day as i32 - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

pub fn ordinal_to_weekday(ordinal: i32) -> u8 {
    ((ordinal + 1).rem_euclid(7)) as u8
}

pub fn is_high_risk_night_ordinal(ordinal: i32) -> bool {
    is_high_risk_night_weekday(ordinal_to_weekday(ordinal))
}

pub fn cycle_day(base_ordinal: i32, target_ordinal: i32, cycle_length: i32) -> i32 {
    let mut diff = target_ordinal - base_ordinal;
    if diff < 0 {
        let cycles = (-diff / cycle_length) + 1;
        diff += cycles * cycle_length;
    }
    (diff % cycle_length) + 1
}

pub fn squad_on_duty(cycle_day: i32) -> &'static str {
    RotationSchedule::dodgeville_default().squad_on_duty(cycle_day)
}

pub fn is_high_risk_night_weekday(weekday: u8) -> bool {
    weekday == 4 || weekday == 5
}

pub fn shift_number(shift_start: &str, shift_times: &[(String, String)]) -> i32 {
    for (idx, (start, _)) in shift_times.iter().enumerate() {
        if start == shift_start {
            return (idx + 1) as i32;
        }
    }
    let hour: i32 = shift_start
        .split(':')
        .next()
        .and_then(|h| h.parse().ok())
        .unwrap_or(0);
    (hour / 6) + 1
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dodgeville_squad_days() {
        let s = RotationSchedule::dodgeville_default();
        assert!(s.is_squad_working("A", 1));
        assert!(!s.is_squad_working("B", 1));
        assert_eq!(s.squad_on_duty(3), "B");
    }

    #[test]
    fn equal_split_pattern() {
        let s = RotationSchedule {
            cycle_length: 14,
            mode: RotationMode::EqualSplit {
                work_days_per_cycle: 7,
                squads: 2,
            },
        };
        assert!(s.is_squad_working("A", 1));
        assert!(s.is_squad_working("A", 7));
        assert!(!s.is_squad_working("A", 8));
        assert!(s.is_squad_working("B", 8));
    }
}