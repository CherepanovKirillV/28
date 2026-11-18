# calculator.py
"""
Расчёт 11 полей профиля из событий одной недели.
Возвращает словарь {field: {"value": ..., "confidence": ...}}.

Стратегия unknown:
  Схема строгая, null/"unknown" НЕ принимаются. При отсутствии данных
  отдаём most-likely placeholder с confidence=0.0 → 0 очков, но схема довольна.

Калибровки:
  - average_sleep_hours × 0.92: wearables переоценивают сон на 5–10%
  - weekday_bedtime conf=0.6: сенсор систематически «видит» сон раньше на 30–40 мин
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

ASLEEP_STAGES = {"light", "deep", "rem"}
SLEEP_EFFICIENCY = 0.92  # калибровка wearable
SEDENTARY_STEP_THRESHOLD = 50  # шагов за 10 мин: ниже = сидячий

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


def _unknown(field: str) -> dict[str, Any]:
    return {"value": _PLACEHOLDER[field], "confidence": 0.0}


def _known(value: Any, confidence: float) -> dict[str, Any]:
    return {"value": value, "confidence": max(0.0, min(1.0, round(confidence, 2)))}


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
) -> dict[str, Any]:
    """
    Тренировка = УСТОЙЧИВЫЙ bpm ≥ 120 (2+ подряд сэмпла = 20 мин)
                ИЛИ steps >= 12000 в день.
    Почему 2 подряд: один всплеск 120 = подъём по лестнице, не тренировка.
    Почему 12000: 10000 — порог «активного дня», а тренировка — это сверх нормы.
    """
    wear = week_data[week_data["source"] == "wearable"].copy()
    if wear.empty or "bpm" not in wear.columns or not wear["bpm"].notna().any():
        # нет bpm — только по шагам
        if daily.empty:
            return _unknown("training_days")
        high_step_days = set(daily[daily >= 12000].index)
    else:
        wear = wear.dropna(subset=["bpm"]).sort_values("started_at")
        wear["local_date"] = wear["started_at"].dt.tz_convert(tz).dt.date
        # устойчивый: текущий И следующий >= 120
        wear["bpm_hi"] = wear["bpm"] >= 120
        wear["bpm_hi_next"] = wear["bpm_hi"].shift(-1, fill_value=False)
        sustained = wear[wear["bpm_hi"] & wear["bpm_hi_next"]]
        sustained_days = set(sustained["local_date"])

        high_step_days = set(daily[daily >= 12000].index) if not daily.empty else set()
        high_step_days |= sustained_days

    n = len(high_step_days)
    if n == 0:
        value = "0"
    elif n <= 2:
        value = "1to2"
    else:
        value = "3plus"
    return _known(value, 0.7)


def _compute_sedentary_from_steps(
    week_data: pd.DataFrame, tz: str
) -> dict[str, Any]:
    """
    sedentary_hours — часы БОДРСТВОВАНИЯ с низкими шагами (<50 за 10-мин).
    НЕ производная от activity_level: можно много ходить и много сидеть.
    """
    wear = week_data[week_data["source"] == "wearable"].copy()
    if wear.empty or "steps" not in wear.columns:
        return _unknown("sedentary_hours")
    wear = wear.dropna(subset=["steps"])
    if wear.empty:
        return _unknown("sedentary_hours")

    wear["is_sleep"] = wear["sleep_stage"].isin(ASLEEP_STAGES)
    awake = wear[~wear["is_sleep"]]
    if len(awake) < 20:
        return _unknown("sedentary_hours")

    awake_local = awake["started_at"].dt.tz_convert(tz)
    n_days = awake_local.dt.date.nunique()
    sedentary_samples = (awake["steps"] < SEDENTARY_STEP_THRESHOLD).sum()
    per_day = sedentary_samples * 10 / 60 / max(n_days, 1)

    if per_day < 6:
        return _known("lt6", 0.7)
    elif per_day <= 9:
        return _known("6to9", 0.7)
    else:
        return _known("gt9", 0.7)


def calculate_profile(
    week_data: pd.DataFrame, tz: str, week_start: str, week_end: str
) -> dict[str, Any]:
    profile: dict[str, Any] = {}

    # ========== 1. Сон ==========
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

    # ========== 2. weekday_bedtime / wake ==========
    if len(weekdays) >= 2:
        bt = weekdays["bedtime"].apply(lambda ts: ts.hour * 60 + ts.minute).median()
        wt = weekdays["waketime"].apply(lambda ts: ts.hour * 60 + ts.minute).median()
        # bedtime: сенсор систематически раньше truth → ниже уверенность
        profile["weekday_bedtime"] = _known(_min_to_time_str(bt), 0.6)
        # wake: сенсор точен (±2 мин) → 0.8
        profile["weekday_wake_time"] = _known(_min_to_time_str(wt), 0.8)
    else:
        profile["weekday_bedtime"] = _unknown("weekday_bedtime")
        profile["weekday_wake_time"] = _unknown("weekday_wake_time")

    # ========== 3. average_sleep_hours (с калибровкой) ==========
    if not valid.empty and valid["sleep_h"].notna().any():
        avg_raw = float(valid["sleep_h"].mean())
        avg_cal = avg_raw * SLEEP_EFFICIENCY  # wearable overestimate
        profile["average_sleep_hours"] = _known(round(avg_cal, 2), 0.65)
    else:
        profile["average_sleep_hours"] = _unknown("average_sleep_hours")

    # ========== 4. chronotype ==========
    if profile["weekday_wake_time"]["confidence"] > 0:
        wake_min = _time_str_to_min(profile["weekday_wake_time"]["value"])
        if wake_min < 390:
            profile["chronotype"] = _known("early", 0.7)
        elif wake_min > 480:
            profile["chronotype"] = _known("late", 0.7)
        else:
            profile["chronotype"] = _known("intermediate", 0.8)
    else:
        profile["chronotype"] = _unknown("chronotype")

    # ========== 5. social_jetlag (≥1 weekend достаточно) ==========
    if len(weekdays) >= 2 and len(weekends) >= 1:
        def _midpoint(row):
            bt_norm = (row["bedtime"].hour * 60 + row["bedtime"].minute - 18 * 60) % (24 * 60)
            return bt_norm + row["sleep_h"] * 60 / 2

        mid_wd = weekdays.apply(_midpoint, axis=1).median()
        mid_we = weekends.apply(_midpoint, axis=1).median()
        diff = abs(mid_wd - mid_we)
        if diff > 12 * 60:
            diff = 24 * 60 - diff
        # 1 weekend ночь → уверенность 0.5; 2+ → 0.7
        conf = 0.7 if len(weekends) >= 2 else 0.5
        profile["social_jetlag"] = _known(bool(diff >= 60), conf)
    else:
        profile["social_jetlag"] = _unknown("social_jetlag")

    # ========== 6. activity_level ==========
    daily = _daily_steps(week_data, tz)
    if len(daily) >= 3:
        avg_steps = float(daily.mean())
        if avg_steps < 5000:
            profile["activity_level"] = _known("low", 0.8)
        elif avg_steps < 10000:
            profile["activity_level"] = _known("medium", 0.8)
        else:
            profile["activity_level"] = _known("high", 0.8)
    else:
        profile["activity_level"] = _unknown("activity_level")

    # ========== 7. sedentary_hours — напрямую из шагов ==========
    profile["sedentary_hours"] = _compute_sedentary_from_steps(week_data, tz)

    # ========== 8. training_days — строгая эвристика ==========
    profile["training_days"] = _compute_training_days_strict(week_data, tz, daily)

    # ========== 9. works_from_home ==========
    smart_home = week_data[week_data["source"] == "smart_home"] if "source" in week_data.columns else pd.DataFrame()
    if not smart_home.empty and "present" in smart_home.columns:
        sh = smart_home.copy()
        sh["local"] = sh["started_at"].dt.tz_convert(tz)
        sh["local_hour"] = sh["local"].dt.hour
        sh["is_weekday"] = sh["local"].dt.weekday < 5
        work_hours = sh[
            sh["is_weekday"]
            & (sh["local_hour"] >= 10)
            & (sh["local_hour"] < 18)
            & (sh["present"] == True)
        ]
        if not work_hours.empty:
            home_days = work_hours["local"].dt.date.nunique()
        else:
            home_days = 0
        profile["works_from_home"] = _known(home_days >= 3, 0.6)
    else:
        profile["works_from_home"] = _unknown("works_from_home")

    # ========== 10. phone_before_sleep ==========
    phone = week_data[week_data["source"] == "phone"] if "source" in week_data.columns else pd.DataFrame()
    if not phone.empty and "screen_minutes" in phone.columns:
        ph = phone.copy()
        ph["local"] = ph["started_at"].dt.tz_convert(tz)
        ph["local_hour"] = ph["local"].dt.hour
        late = ph[(ph["local_hour"] >= 23) & (ph["screen_minutes"] > 0)]
        late_days = late["local"].dt.date.nunique() if not late.empty else 0
        if late_days >= 3:
            profile["phone_before_sleep"] = _known(True, 0.8)
        else:
            profile["phone_before_sleep"] = _known(False, 0.7)
    else:
        profile["phone_before_sleep"] = _unknown("phone_before_sleep")

    # ========== 11. movement_index — от activity + training ==========
    if profile["activity_level"]["confidence"] == 0.0:
        profile["movement_index"] = _unknown("movement_index")
    else:
        score = 0
        if profile["activity_level"]["value"] == "high":
            score += 60
        elif profile["activity_level"]["value"] == "medium":
            score += 40
        else:
            score += 20

        train = profile["training_days"]
        if train["confidence"] > 0:
            if train["value"] == "3plus":
                score += 30
            elif train["value"] == "1to2":
                score += 15

        score = min(100, score)
        if score >= 85:
            profile["movement_index"] = _known("85plus", 0.7)
        elif score >= 70:
            profile["movement_index"] = _known("70to85", 0.7)
        elif score >= 50:
            profile["movement_index"] = _known("50to70", 0.7)
        else:
            profile["movement_index"] = _known("lt50", 0.7)

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
