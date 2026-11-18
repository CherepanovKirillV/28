# calculator.py
"""
Расчёт 11 полей профиля из событий одной недели.
Возвращает {field: {"value": ..., "confidence": ...}}.

Confidence задаётся в _CONFIDENCE. Калибровка — по calibrate.py.
Стратегия: conf=0 (unknown) лучше, чем conf=0.7 при ошибке (−1 очко).
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

ASLEEP_STAGES = {"light", "deep", "rem"}
SLEEP_EFFICIENCY = 0.92
SEDENTARY_STEP_THRESHOLD = 50

_PLACEHOLDER: dict[str, Any] = {
    "chronotype": "intermediate",
    "weekday_bedtime": "23:00",
    "weekday_wake_time": "07:00",
    "average_sleep_hours": 7.5,
    "social_jetlag": False,
    "activity_level": "medium",
    "sedentary_hours": "6to9",
    "training_days": "1to2",
    "works_from_home": False,
    "phone_before_sleep": False,
    "movement_index": "50to70",
}

# Калибровка: обновляй после calibrate.py
_CONFIDENCE: dict[str, float] = {
    "chronotype": 0.85,
    "weekday_bedtime": 0.00,
    "weekday_wake_time": 0.85,
    "average_sleep_hours": 0.70,
    "social_jetlag": 0.70,
    "activity_level": 0.85,
    "sedentary_hours": 0.70,
    "training_days": 0.70,
    "works_from_home": 0.70,
    "phone_before_sleep": 0.85,
    "movement_index": 0.70,
}


def _conf(field: str) -> float:
    return _CONFIDENCE.get(field, 0.5)


def _unknown(field: str) -> dict[str, Any]:
    return {"value": _PLACEHOLDER[field], "confidence": 0.0}


def _known(field: str, value: Any) -> dict[str, Any]:
    return {
        "value": value,
        "confidence": max(0.0, min(1.0, round(_conf(field), 2))),
    }


def unknown_profile() -> dict[str, dict[str, Any]]:
    return {k: _unknown(k) for k in _PLACEHOLDER}


def _time_str_to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _min_to_time_str(m: float) -> str:
    total = int(round(m)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _daily_steps(week_data: pd.DataFrame, tz: str) -> pd.Series:
    if week_data.empty or "source" not in week_data.columns:
        return pd.Series(dtype=float)
    wear = week_data[week_data["source"] == "wearable"].dropna(subset=["steps"])
    if len(wear) >= 50:
        return wear.groupby(wear["started_at"].dt.tz_convert(tz).dt.date)["steps"].sum()
    phone = week_data[week_data["source"] == "phone"].dropna(subset=["steps"])
    if len(phone) >= 10:
        return phone.groupby(phone["started_at"].dt.tz_convert(tz).dt.date)["steps"].sum()
    return pd.Series(dtype=float)


def _compute_training_days_strict(
    week_data: pd.DataFrame, tz: str, daily: pd.Series
) -> tuple[str, int] | None:
    """Возвращает (value, n_days) или None если данных нет."""
    wear = week_data[week_data["source"] == "wearable"].copy()
    high_step_days: set = set()
    if not daily.empty:
        high_step_days = set(daily[daily >= 12000].index)

    sustained_days: set = set()
    if not wear.empty and "bpm" in wear.columns and wear["bpm"].notna().any():
        wear = wear.dropna(subset=["bpm"]).sort_values("started_at")
        wear["local_date"] = wear["started_at"].dt.tz_convert(tz).dt.date
        wear["bpm_hi"] = wear["bpm"] >= 120
        wear["bpm_hi_next"] = wear["bpm_hi"].shift(-1, fill_value=False)
        sustained = wear[wear["bpm_hi"] & wear["bpm_hi_next"]]
        sustained_days = set(sustained["local_date"])

    if not high_step_days and not sustained_days and daily.empty and wear.empty:
        return None

    all_days = high_step_days | sustained_days
    n = len(all_days)
    value = "0" if n == 0 else ("1to2" if n <= 2 else "3plus")
    return value, n


def _compute_sedentary_from_steps(
    week_data: pd.DataFrame, tz: str
) -> str | None:
    """Часы бодрствования с низкими шагами. Возвращает enum или None."""
    wear = week_data[week_data["source"] == "wearable"].copy()
    if wear.empty or "steps" not in wear.columns:
        return None
    wear = wear.dropna(subset=["steps"])
    if wear.empty:
        return None

    wear["is_sleep"] = wear["sleep_stage"].isin(ASLEEP_STAGES)
    awake = wear[~wear["is_sleep"]]
    if len(awake) < 20:
        return None

    awake_local = awake["started_at"].dt.tz_convert(tz)
    n_days = awake_local.dt.date.nunique()
    sedentary_samples = (awake["steps"] < SEDENTARY_STEP_THRESHOLD).sum()
    per_day = sedentary_samples * 10 / 60 / max(n_days, 1)

    if per_day < 6:
        return "lt6"
    if per_day <= 9:
        return "6to9"
    return "gt9"


def calculate_profile(
    week_data: pd.DataFrame, tz: str, week_start: str, week_end: str
) -> dict[str, Any]:
    profile: dict[str, Any] = {}

    # 1. Сон
    nights = extract_nights(week_data, tz, week_start, week_end)
    valid = nights[~nights["is_boundary"]] if not nights.empty else nights
    weekdays = (
        valid[valid["date_local"].apply(lambda d: d.weekday() < 5)]
        if not valid.empty else valid
    )
    weekends = (
        valid[valid["date_local"].apply(lambda d: d.weekday() >= 5)]
        if not valid.empty else valid
    )

    # 2. bedtime / wake
    if len(weekdays) >= 2:
        bt = weekdays["bedtime"].apply(lambda ts: ts.hour * 60 + ts.minute).median()
        wt = weekdays["waketime"].apply(lambda ts: ts.hour * 60 + ts.minute).median()
        profile["weekday_bedtime"] = _known("weekday_bedtime", _min_to_time_str(bt))
        profile["weekday_wake_time"] = _known("weekday_wake_time", _min_to_time_str(wt))
    else:
        profile["weekday_bedtime"] = _unknown("weekday_bedtime")
        profile["weekday_wake_time"] = _unknown("weekday_wake_time")

    # 3. average_sleep_hours
    if not valid.empty and valid["sleep_h"].notna().any():
        avg = float(valid["sleep_h"].mean()) * SLEEP_EFFICIENCY
        profile["average_sleep_hours"] = _known("average_sleep_hours", round(avg, 2))
    else:
        profile["average_sleep_hours"] = _unknown("average_sleep_hours")

    # 4. chronotype
    if profile["weekday_wake_time"]["confidence"] > 0:
        wake_min = _time_str_to_min(profile["weekday_wake_time"]["value"])
        if wake_min < 390:
            profile["chronotype"] = _known("chronotype", "early")
        elif wake_min > 480:
            profile["chronotype"] = _known("chronotype", "late")
        else:
            profile["chronotype"] = _known("chronotype", "intermediate")
    else:
        profile["chronotype"] = _unknown("chronotype")

    # 5. social_jetlag
    if len(weekdays) >= 2 and len(weekends) >= 1:
        def _midpoint(row):
            bt_norm = (row["bedtime"].hour * 60 + row["bedtime"].minute - 18 * 60) % (24 * 60)
            return bt_norm + row["sleep_h"] * 60 / 2

        mid_wd = weekdays.apply(_midpoint, axis=1).median()
        mid_we = weekends.apply(_midpoint, axis=1).median()
        diff = abs(mid_wd - mid_we)
        if diff > 12 * 60:
            diff = 24 * 60 - diff
        profile["social_jetlag"] = _known("social_jetlag", bool(diff >= 60))
    else:
        profile["social_jetlag"] = _unknown("social_jetlag")

    # 6. activity_level
    daily = _daily_steps(week_data, tz)
    if len(daily) >= 3:
        avg_steps = float(daily.mean())
        if avg_steps < 5000:
            profile["activity_level"] = _known("activity_level", "low")
        elif avg_steps < 10000:
            profile["activity_level"] = _known("activity_level", "medium")
        else:
            profile["activity_level"] = _known("activity_level", "high")
    else:
        profile["activity_level"] = _unknown("activity_level")

    # 7. sedentary_hours
    sed = _compute_sedentary_from_steps(week_data, tz)
    profile["sedentary_hours"] = (
        _known("sedentary_hours", sed) if sed else _unknown("sedentary_hours")
    )

    # 8. training_days
    tr = _compute_training_days_strict(week_data, tz, daily)
    profile["training_days"] = (
        _known("training_days", tr[0]) if tr else _unknown("training_days")
    )

    # 9. works_from_home
    smart_home = week_data[week_data["source"] == "smart_home"] if "source" in week_data.columns else pd.DataFrame()
    if not smart_home.empty and "present" in smart_home.columns:
        sh = smart_home.copy()
        sh["local"] = sh["started_at"].dt.tz_convert(tz)
        sh["local_hour"] = sh["local"].dt.hour
        sh["is_weekday"] = sh["local"].dt.weekday < 5
        wh = sh[
            sh["is_weekday"]
            & (sh["local_hour"] >= 10)
            & (sh["local_hour"] < 18)
            & (sh["present"] == True)
        ]
        home_days = wh["local"].dt.date.nunique() if not wh.empty else 0
        profile["works_from_home"] = _known("works_from_home", home_days >= 3)
    else:
        profile["works_from_home"] = _unknown("works_from_home")

    # 10. phone_before_sleep
    phone = week_data[week_data["source"] == "phone"] if "source" in week_data.columns else pd.DataFrame()
    if not phone.empty and "screen_minutes" in phone.columns:
        ph = phone.copy()
        ph["local"] = ph["started_at"].dt.tz_convert(tz)
        ph["local_hour"] = ph["local"].dt.hour
        late = ph[(ph["local_hour"] >= 23) & (ph["screen_minutes"] > 0)]
        late_days = late["local"].dt.date.nunique() if not late.empty else 0
        profile["phone_before_sleep"] = _known(
            "phone_before_sleep", bool(late_days >= 3)
        )
    else:
        profile["phone_before_sleep"] = _unknown("phone_before_sleep")

    # 11. movement_index
    if profile["activity_level"]["confidence"] == 0.0:
        profile["movement_index"] = _unknown("movement_index")
    else:
        score = {"high": 60, "medium": 40, "low": 20}.get(
            profile["activity_level"]["value"], 40
        )
        if profile["training_days"]["confidence"] > 0:
            if profile["training_days"]["value"] == "3plus":
                score += 30
            elif profile["training_days"]["value"] == "1to2":
                score += 15
        score = min(100, score)
        if score >= 85:
            val = "85plus"
        elif score >= 70:
            val = "70to85"
        elif score >= 50:
            val = "50to70"
        else:
            val = "lt50"
        profile["movement_index"] = _known("movement_index", val)

    return profile


def extract_nights(
    w: pd.DataFrame, tz: str, week_start: str, week_end: str
) -> pd.DataFrame:
    cols = ["date_local", "bedtime", "waketime", "time_in_bed_h", "sleep_h", "is_boundary"]
    if w.empty or "sleep_stage" not in w.columns or not w["sleep_stage"].notna().any():
        return pd.DataFrame(columns=cols)

    w = w.sort_values("started_at").copy()
    w["is_asleep"] = w["sleep_stage"].isin(ASLEEP_STAGES)
    w["local_start"] = w["started_at"].dt.tz_convert(tz)
    w["local_end"] = w["local_start"] + pd.Timedelta(minutes=10)

    nights: list[tuple] = []
    cur_start = None
    cur_last_end = None
    cur_asleep_count = 0

    for _, row in w.iterrows():
        if not row["is_asleep"]:
            continue
        ls, le = row["local_start"], row["local_end"]
        if cur_start is None:
            cur_start, cur_last_end, cur_asleep_count = ls, le, 1
            continue
        gap_min = (ls - cur_last_end).total_seconds() / 60
        if gap_min > 60:
            nights.append((cur_start, cur_last_end, cur_asleep_count))
            cur_start, cur_last_end, cur_asleep_count = ls, le, 1
        else:
            cur_last_end = le
            cur_asleep_count += 1
    if cur_start is not None:
        nights.append((cur_start, cur_last_end, cur_asleep_count))

    rows = []
    week_start_dt = pd.to_datetime(week_start).date()
    week_end_dt = pd.to_datetime(week_end).date()
    last_day = week_end_dt - timedelta(days=1)

    for s, e, asleep_count in nights:
        tib_h = (e - s).total_seconds() / 3600
        sleep_h = asleep_count * 10 / 60
        d = s.date()
        boundary = (
            (d == week_start_dt and s.hour < 6)
            or (e.date() >= week_end_dt)
            or (d == last_day and s.hour >= 20)
        )
        rows.append({
            "date_local": d,
            "bedtime": s,
            "waketime": e,
            "time_in_bed_h": round(tib_h, 2),
            "sleep_h": round(sleep_h, 2),
            "is_boundary": boundary,
        })

    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows)
