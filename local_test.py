"""
Локальная симуляция стенда по data/dev.json.
Считает очки по правилам хакатона, чтобы ты видел результат
до пуша и не гонял curl каждый раз.
"""
import json
from pathlib import Path

import pandas as pd

import calculator
import llm_generator

DATA_PATH = Path(__file__).resolve().parent / "data" / "dev.json"

# Допуски из контракта кейса
TOL_TIME_MIN = 30   # для "HH:MM" — ±30 минут
TOL_HOURS = 0.5     # для average_sleep_hours — ±0.5 часа


def check_value(ours, truth) -> bool:
    """
    Сравнивает наш ответ с эталоном с учётом допусков.
    Без допусков любая ошибка в 1 минуту = "неверно", что не соответствует условиям.
    """
    if ours is None or truth is None:
        return False

    ours_s, truth_s = str(ours), str(truth)

    # Строки вида "23:00" сравниваем в минутах, учитывая переход через полночь
    if ":" in ours_s and ":" in truth_s:
        try:
            h1, m1 = map(int, ours_s.split(":"))
            h2, m2 = map(int, truth_s.split(":"))
            d = abs(h1 * 60 + m1 - h2 * 60 - m2)
            return min(d, 24 * 60 - d) <= TOL_TIME_MIN
        except Exception:
            return False

    # Числа с плавающей точкой — с допуском TOL_HOURS
    if isinstance(ours, (int, float)) and isinstance(truth, (int, float)):
        return abs(float(ours) - float(truth)) <= TOL_HOURS

    # Bool/enum — точное совпадение
    return ours == truth


def calc_points(ok: bool, conf: float) -> float:
    """
    Очки по правилам хакатона:
      верно + conf ≥ 0.7  → +1.0
      верно + conf < 0.7  → +0.5
      неверно + conf ≥ 0.7 → −1.0
      неверно + conf < 0.7 → −0.25
      unknown (conf=0)    → 0.0
    """
    if conf == 0:
        return 0.0
    if conf >= 0.7:
        return 1.0 if ok else -1.0
    return 0.5 if ok else -0.25


def main():
    with DATA_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    # Быстрая загрузка (как в main.py, но без gc — тут dev-набор маленький)
    users = {u["user_id"]: u.get("timezone", "Europe/Moscow") for u in data["dataset"]["users"]}
    events = data["dataset"]["events"]
    ref_map = {r["record_id"]: r["profile"] for r in data["reference"]["weeks"]}

    rows = []
    for e in events:
        p = e.get("payload") or {}
        rows.append({
            "user_id": e["user_id"],
            "started_at": e["started_at"],
            "source": e["source"],
            "bpm": p.get("bpm"),
            "steps": p.get("steps"),
            "sleep_stage": p.get("sleep_stage"),
            "screen_minutes": p.get("screen_minutes"),
            "present": p.get("present"),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df["started_at"] = pd.to_datetime(df["started_at"], utc=True)

    total_pts = 0.0
    field_stats = {}

    for week in data["dataset"]["weeks"]:
        rid = week["record_id"]
        user_id = week["user_id"]
        tz = users.get(user_id, "Europe/Moscow")

        start = pd.Timestamp(week["start_date"], tz=tz).tz_convert("UTC")
        end = pd.Timestamp(week["end_date_exclusive"], tz=tz).tz_convert("UTC")

        mask = (df["user_id"] == user_id) & (df["started_at"] >= start) & (df["started_at"] < end)
        week_df = df.loc[mask].copy()

        profile = calculator.calculate_profile(week_df, tz, week["start_date"], week["end_date_exclusive"])

        # Гипотезы НЕ влияют на очки профиля, но прогоняем их,
        # чтобы убедиться: LLM/fallback не крашатся.
        # Если хочешь ускорить тест — закомментируй строку ниже.
        _ = llm_generator.generate_hypotheses(profile)

        ref = ref_map.get(rid, {})

        for field, val in profile.items():
            if field not in field_stats:
                field_stats[field] = {"n": 0, "ok": 0, "pts": 0.0}

            field_stats[field]["n"] += 1
            ok = check_value(val["value"], ref.get(field))
            if ok:
                field_stats[field]["ok"] += 1

            pts = calc_points(ok, val["confidence"])
            field_stats[field]["pts"] += pts
            total_pts += pts

    # ── Вывод ────────────────────────────────────────────
    print(f"{'Поле':<24} {'N':>3} {'Точность':>8} {'Очки':>8}")
    print("-" * 45)
    for field, stats in sorted(field_stats.items()):
        acc = (stats["ok"] / stats["n"] * 100) if stats["n"] > 0 else 0
        print(f"{field:<24} {stats['n']:>3} {acc:>7.1f}% {stats['pts']:>+8.2f}")
    print("-" * 45)
    print(f"ИТОГО ОЧКОВ (LOCAL TEST): {total_pts:+.2f}")


if __name__ == "__main__":
    main()