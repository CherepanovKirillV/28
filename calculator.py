import pandas as pd
import numpy as np
from datetime import timedelta
from typing import Dict, Any

ASLEEP_STAGES = {"light", "deep", "rem"}

def calculate_profile(week_data: pd.DataFrame, tz: str, week_start: str, week_end: str) -> Dict[str, Any]:
    """
    Рассчитывает 11 полей профиля для одной недели.
    Возвращает словарь, готовый для вставки в JSON-ответ.
    """
    profile = {}
    
    # 1. Подготовка данных по сну (выделяем "ночи")
    nights = extract_nights(week_data, tz, week_start, week_end)
    # boundary = ночи, обрезанные началом или концом недели (их исключаем из средних значений)
    valid_nights = nights[~nights["is_boundary"]]
    weekdays = valid_nights[valid_nights["date_local"].apply(lambda d: d.weekday() < 5)]
    weekends = valid_nights[valid_nights["date_local"].apply(lambda d: d.weekday() >= 5)]
    
    # 2. weekday_bedtime и weekday_wake_time (медиана отбоя и подъёма в будни)
    if len(weekdays) >= 2:
        # Переводим время в минуты от 00:00 для корректного расчёта медианы
        median_bedtime_min = weekdays["bedtime"].apply(lambda ts: (ts.hour * 60 + ts.minute)).median()
        median_wake_min = weekdays["waketime"].apply(lambda ts: ts.hour * 60 + ts.minute).median()
        
        bedtime_str = f"{int(median_bedtime_min // 60):02d}:{int(median_bedtime_min % 60):02d}"
        wake_str = f"{int(median_wake_min // 60):02d}:{int(median_wake_min % 60):02d}"
        
        profile["weekday_bedtime"] = {"value": bedtime_str, "confidence": 0.8 if len(weekdays) >= 3 else 0.6}
        profile["weekday_wake_time"] = {"value": wake_str, "confidence": 0.8 if len(weekdays) >= 3 else 0.6}
    else:
        # ЗОЛОТОЕ ПРАВИЛО: лучше unknown, чем угадывать и получить -1 балл!
        profile["weekday_bedtime"] = {"value": "unknown", "confidence": 0.0}
        profile["weekday_wake_time"] = {"value": "unknown", "confidence": 0.0}

    # 3. sleep_duration (средняя продолжительность сна в часах)
    if not valid_nights.empty:
        avg_sleep = valid_nights["sleep_h"].mean()
        profile["sleep_duration"] = {"value": round(avg_sleep, 1), "confidence": 0.8 if len(valid_nights) >= 3 else 0.5}
    else:
        profile["sleep_duration"] = {"value": "unknown", "confidence": 0.0}

    # 4. chronotype (хронотип)
    if profile["weekday_wake_time"]["value"] != "unknown":
        wake_min = int(profile["weekday_wake_time"]["value"].split(":")[0]) * 60 + int(profile["weekday_wake_time"]["value"].split(":")[1])
        if wake_min < 390:  # До 06:30
            profile["chronotype"] = {"value": "early", "confidence": 0.7}
        elif wake_min > 480:  # После 08:00
            profile["chronotype"] = {"value": "late", "confidence": 0.7}
        else:
            profile["chronotype"] = {"value": "intermediate", "confidence": 0.8}
    else:
        profile["chronotype"] = {"value": "unknown", "confidence": 0.0}

    # 5. social_jetlag (сдвиг середины сна между буднями и выходными >= 1 часа)
    if len(weekdays) >= 2 and len(weekends) >= 2:
        # Середина сна = время отбоя + половина продолжительности сна
        mid_week = weekdays["bedtime"].apply(lambda ts: (ts.hour * 60 + ts.minute) + (weekdays["sleep_h"].mean() * 60) / 2).median()
        mid_weekend = weekends["bedtime"].apply(lambda ts: (ts.hour * 60 + ts.minute) + (weekends["sleep_h"].mean() * 60) / 2).median()
        
        diff = abs(mid_week - mid_weekend)
        # Учитываем переход через полночь (например, 01:00 и 23:00)
        if diff > 12 * 60:
            diff = 24 * 60 - diff
            
        profile["social_jetlag"] = {"value": bool(diff >= 60), "confidence": 0.7}
    else:
        profile["social_jetlag"] = {"value": "unknown", "confidence": 0.0}

    # 6. activity_level (уровень активности по средним шагам в день)
    wearable = week_data[week_data["source"] == "wearable"]
    if not wearable.empty:
        daily_steps = wearable.groupby(wearable["started_at"].dt.tz_convert(tz).dt.date)["steps"].sum()
        avg_steps = daily_steps.mean()
        if avg_steps < 5000:
            profile["activity_level"] = {"value": "low", "confidence": 0.8}
        elif avg_steps < 10000:
            profile["activity_level"] = {"value": "medium", "confidence": 0.8}
        else:
            profile["activity_level"] = {"value": "high", "confidence": 0.8}
    else:
        profile["activity_level"] = {"value": "unknown", "confidence": 0.0}

    # 7. sedentary_hours (эвристика на основе уровня активности)
    # Если точных данных о сидении нет, используем обратную корреляцию с шагами
    if profile["activity_level"]["value"] == "low":
        profile["sedentary_hours"] = {"value": ">9", "confidence": 0.6}
    elif profile["activity_level"]["value"] == "high":
        profile["sedentary_hours"] = {"value": "<6", "confidence": 0.6}
    else:
        profile["sedentary_hours"] = {"value": "6-9", "confidence": 0.6}

    # 8. workout_days (дни с высокой нагрузкой: пульс > 120 или шаги > 10000)
    if not wearable.empty:
        daily_max_bpm = wearable.groupby(wearable["started_at"].dt.tz_convert(tz).dt.date)["bpm"].max()
        workout_days_count = (daily_max_bpm > 120).sum()
        if workout_days_count == 0:
            profile["workout_days"] = {"value": "0", "confidence": 0.7}
        elif workout_days_count <= 2:
            profile["workout_days"] = {"value": "1-2", "confidence": 0.7}
        else:
            profile["workout_days"] = {"value": "3+", "confidence": 0.7}
    else:
        profile["workout_days"] = {"value": "unknown", "confidence": 0.0}

    # 9. work_from_home (присутствие дома в рабочее время 10:00–18:00 по будням)
    smart_home = week_data[week_data["source"] == "smart_home"]
    if not smart_home.empty:
        sh_local = smart_home.copy()
        sh_local["local_hour"] = sh_local["started_at"].dt.tz_convert(tz).dt.hour
        sh_local["is_weekday"] = sh_local["started_at"].dt.tz_convert(tz).dt.weekday < 5
        
        work_hours_presence = sh_local[(sh_local["is_weekday"]) & (sh_local["local_hour"] >= 10) & (sh_local["local_hour"] < 18)]
        # Если есть устойчивые записи о присутствии в это время
        if len(work_hours_presence) > 10: 
            profile["work_from_home"] = {"value": True, "confidence": 0.6}
        else:
            profile["work_from_home"] = {"value": False, "confidence": 0.6}
    else:
        profile["work_from_home"] = {"value": "unknown", "confidence": 0.0}

    # 10. phone_before_bed (экран после 23:00 ≥ 3 дней)
    phone = week_data[week_data["source"] == "phone"]
    if not phone.empty:
        phone_local = phone.copy()
        phone_local["local_hour"] = phone_local["started_at"].dt.tz_convert(tz).dt.hour
        late_screen = phone_local[(phone_local["local_hour"] >= 23) & (phone_local["screen_minutes"] > 0)]
        late_screen_days = late_screen.groupby(late_screen["started_at"].dt.tz_convert(tz).dt.date).size()
        
        if len(late_screen_days) >= 3:
            profile["phone_before_bed"] = {"value": True, "confidence": 0.8}
        else:
            profile["phone_before_bed"] = {"value": False, "confidence": 0.7}
    else:
        profile["phone_before_bed"] = {"value": "unknown", "confidence": 0.0}

    # 11. movement_index (упрощённая формула на основе шагов и тренировок)
    # Граница попадает в верхний интервал (например, 50 -> "50-70")
    if profile["activity_level"]["value"] != "unknown":
        score = 0
        if profile["activity_level"]["value"] == "high": score += 60
        elif profile["activity_level"]["value"] == "medium": score += 40
        else: score += 20
        
        if profile["workout_days"]["value"] == "3+": score += 30
        elif profile["workout_days"]["value"] == "1-2": score += 15
        
        score = min(100, score) # Ограничиваем максимумом 100
        
        if score >= 85:
            profile["movement_index"] = {"value": ">=85", "confidence": 0.7}
        elif score >= 70:
            profile["movement_index"] = {"value": "70-85", "confidence": 0.7}
        elif score >= 50:
            profile["movement_index"] = {"value": "50-70", "confidence": 0.7}
        else:
            profile["movement_index"] = {"value": "<50", "confidence": 0.7}
    else:
        profile["movement_index"] = {"value": "unknown", "confidence": 0.0}

    return profile


def extract_nights(w: pd.DataFrame, tz: str, week_start: str, week_end: str) -> pd.DataFrame:
    """
    Вспомогательная функция: склеивает стадии сна в полноценные "ночи".
    Разрыв > 60 минут считается новой ночью.
    """
    cols = ["date_local", "bedtime", "waketime", "time_in_bed_h", "sleep_h", "is_boundary"]
    if w.empty or not w["sleep_stage"].notna().any():
        return pd.DataFrame(columns=cols)
    
    w = w.sort_values("started_at").copy()
    w["is_asleep"] = w["sleep_stage"].isin(ASLEEP_STAGES)
    w["local_start"] = w["started_at"].dt.tz_convert(tz)
    w["local_end"] = w["local_start"] + pd.Timedelta(minutes=10) # Шаг сэмпла 10 мин
    
    nights = []
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
        
        # Флаг границы: ночь прижата к началу или концу недели (может быть обрезана)
        boundary = (d == week_start_dt and s.hour < 6) or \
                   (e.date() >= week_end_dt) or \
                   (d == last_day and s.hour >= 20)
                   
        rows.append({
            "date_local": d,
            "bedtime": s,
            "waketime": e,
            "time_in_bed_h": round(tib_h, 2),
            "sleep_h": round(sleep_h, 2),
            "is_boundary": boundary,
        })
    return pd.DataFrame(rows)