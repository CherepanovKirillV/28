#!/usr/bin/env python3
"""
Калибровка уверенности: прогоняет все dev-недели, сравнивает с reference,
считает accuracy по каждому полю и симулирует очки.

Запуск:
    env28
    python calibrate.py
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import explore_dev as ex
import calculator as calc

DATA_PATH = Path(__file__).resolve().parent / "data" / "dev.json"

# Допуски из контракта кейса
TOL_TIME_MIN = 30     # для "HH:MM" — ±30 минут
TOL_HOURS = 0.5       # для average_sleep_hours — ±0.5 ч


def check_value(ours, truth) -> bool:
    """Сравнение с допуском (время ±30 мин, float ±0.5, остальное — точное)."""
    if ours is None or truth is None:
        return False

    # Время "HH:MM"
    ours_s, truth_s = str(ours), str(truth)
    if ":" in ours_s and ":" in truth_s:
        try:
            h1, m1 = map(int, ours_s.split(":"))
            h2, m2 = map(int, truth_s.split(":"))
            d = abs(h1 * 60 + m1 - h2 * 60 - m2)
            d = min(d, 24 * 60 - d)  # короче через полночь
            return d <= TOL_TIME_MIN
        except Exception:
            return False

    # Числа с плавающей точкой
    if isinstance(ours, (int, float)) and isinstance(truth, (int, float)):
        return abs(float(ours) - float(truth)) <= TOL_HOURS

    # Остальное — точное совпадение (строки enum, bool)
    return ours == truth


def points(ok: bool, confidence: float) -> float:
    """
    Очки по правилам README:
      верно + conf ≥ 0.7  → +1
      верно + conf < 0.7  → +0.5
      неверно + conf ≥ 0.7 → −1
      неверно + conf < 0.7 → −0.25
      unknown (conf=0)    → 0
    """
    if confidence == 0:
        return 0.0
    if confidence >= 0.7:
        return 1.0 if ok else -1.0
    return 0.5 if ok else -0.25


def recommend_confidence(acc: float) -> float:
    """Рекомендация по таблице: p>0.85 → 0.85, p>0.6 → 0.7, p>0.33 → 0.5, иначе 0."""
    if acc >= 0.85:
        return 0.85
    if acc >= 0.60:
        return 0.70
    if acc >= 0.40:
        return 0.55
    if acc >= 0.33:
        return 0.50
    return 0.0


def main() -> None:
    with DATA_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    df = ex.events_to_df(data)
    tz_map = ex.user_tz_map(data)
    weeks = data["dataset"]["weeks"]
    ref_map = {r["record_id"]: r["profile"] for r in data["reference"]["weeks"]}

    stats: dict[str, dict] = defaultdict(lambda: {
        "n": 0, "correct": 0, "wrong": 0, "unknown": 0,
        "pts_high_conf": 0.0, "pts_current": 0.0,
    })
    per_week_pts: list[float] = []
    errors: list[str] = []

    for week in weeks:
        rid = week["record_id"]
        try:
            df_w = ex.week_slice(df, week, tz_map)
            profile = calc.calculate_profile(
                df_w, tz_map[week["user_id"]],
                week["start_date"], week["end_date_exclusive"],
            )
        except Exception as e:
            errors.append(f"{rid}: {type(e).__name__}: {e}")
            continue

        ref = ref_map.get(rid)
        if ref is None:
            continue

        week_pts = 0.0
        for field, val in profile.items():
            v, c = val["value"], val["confidence"]
            t = ref.get(field)
            s = stats[field]
            s["n"] += 1

            if c == 0:
                s["unknown"] += 1
                continue

            ok = check_value(v, t)
            if ok:
                s["correct"] += 1
            else:
                s["wrong"] += 1

            p_cur = points(ok, c)
            p_hi = points(ok, 0.85)  # симуляция "если бы conf=0.85"
            s["pts_current"] += p_cur
            s["pts_high_conf"] += p_hi
            week_pts += p_cur

        per_week_pts.append(week_pts)

    # ---- Вывод ----
    print(f"\nВсего недель: {len(weeks)}")
    if errors:
        print(f"Ошибок при расчёте: {len(errors)}")
        for e in errors[:5]:
            print(f"  {e}")

    print(f"\n{'field':24s} {'n':>3s} {'cor':>4s} {'wrong':>6s} {'unk':>4s} "
          f"{'acc':>7s} {'pts_now':>8s} {'pts@0.85':>9s} {'rec_conf':>9s}")
    print("-" * 90)

    total_n = total_cor = total_unk = 0
    total_pts = 0.0
    total_pts_hi = 0.0
    for field in sorted(stats):
        s = stats[field]
        answered = s["n"] - s["unknown"]
        acc = s["correct"] / answered if answered else 0.0
        rec = recommend_confidence(acc)
        marker = ""
        if rec == 0:
            marker = " ⚠️"
        elif acc >= 0.85:
            marker = " ✅"
        elif acc >= 0.6:
            marker = " 🟡"
        else:
            marker = " 🔻"

        total_n += s["n"]
        total_cor += s["correct"]
        total_unk += s["unknown"]
        total_pts += s["pts_current"]
        total_pts_hi += s["pts_high_conf"]

        print(f"{field:24s} {s['n']:>3d} {s['correct']:>4d} {s['wrong']:>6d} "
              f"{s['unknown']:>4d} {acc:>6.1%} {s['pts_current']:>+8.2f} "
              f"{s['pts_high_conf']:>+9.2f} {rec:>9.2f}{marker}")

    print("-" * 90)
    print(f"Всего ответов: {total_n}, правильных: {total_cor}, unknown: {total_unk}")
    if total_n - total_unk > 0:
        print(f"Точность (без unknown): {total_cor / (total_n - total_unk):.1%}")

    print(f"\n{'ОЧКИ ПО НЕДЕЛЯМ':-^50}")
    if per_week_pts:
        print(f"  min   = {min(per_week_pts):+.2f}")
        print(f"  max   = {max(per_week_pts):+.2f}")
        print(f"  avg   = {sum(per_week_pts) / len(per_week_pts):+.2f} / неделя")
        print(f"  total = {sum(per_week_pts):+.2f} за {len(per_week_pts)} недель")

    print(f"\n{'ПРОГНОЗ':-^50}")
    print(f"  Текущие conf   → {total_pts:+.2f} очков")
    print(f"  Все conf=0.85  → {total_pts_hi:+.2f} очков (если бы не ошибались)")
    print(f"\n  Формула выбора conf по acc поля:")
    print(f"    acc ≥ 85%  → 0.85  (уверенно)")
    print(f"    acc ≥ 60%  → 0.70  (уверенно, но на грани)")
    print(f"    acc ≥ 40%  → 0.55  (мягко, штраф 0.25)")
    print(f"    acc ≥ 33%  → 0.50  (мягко)")
    print(f"    acc < 33%  → 0.00  (unknown, 0 очков)")


if __name__ == "__main__":
    main()
