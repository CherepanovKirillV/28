"""
calibrate.py v2 — калибровка уверенности + what-if анализ.

Что нового по сравнению с v1:
    1. compute_profiles() с переопределением _CONFIDENCE / _PRIOR_CONFIDENCE / _PLACEHOLDER
    — можно прогнать несколько сценариев, не трогая файл calculator.py.
    2. Сценарий B: включить weekday_bedtime soft guess (conf=0.5).
    3. Сценарий C: то же + оптимальный placeholder для ±30 мин.
    4. Итоговая таблица: A vs B vs C и рекомендация.

Запуск:
    echo $PROJECT_28 выводит /mnt/c/Users/Траоре/Desktop/281
    env28 alias env28='cd "$PROJECT_28" && source .venv/bin/activate &&
    source set_env.sh && echo "28 env: ready (team28, venv active)"'
    python3 calibrate.py
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import explore_dev as ex
import calculator as calc

DATA_PATH = Path(__file__).resolve().parent / "data" / "case3_dev.json.json"

# Допуски из контракта кейса
TOL_TIME_MIN = 30
TOL_HOURS = 0.5


# ═══════════════════════════════════════════════════════════════════
# БАЗОВЫЕ ФУНКЦИИ (без изменений с v1)
# ═══════════════════════════════════════════════════════════════════

def check_value(ours, truth) -> bool:
    """Сравнение с допуском (время ±30 мин, float ±0.5, остальное — точно)."""
    if ours is None or truth is None:
        return False
    ours_s, truth_s = str(ours), str(truth)
    if ":" in ours_s and ":" in truth_s:
        try:
            h1, m1 = map(int, ours_s.split(":"))
            h2, m2 = map(int, truth_s.split(":"))
            d = abs(h1 * 60 + m1 - h2 * 60 - m2)
            return min(d, 24 * 60 - d) <= TOL_TIME_MIN
        except Exception:
            return False
    if isinstance(ours, (int, float)) and isinstance(truth, (int, float)):
        return abs(float(ours) - float(truth)) <= TOL_HOURS
    return ours == truth


def points(ok: bool, confidence: float) -> float:
    """Очки по правилам хакатона."""
    if confidence == 0:
        return 0.0
    if confidence >= 0.7:
        return 1.0 if ok else -1.0
    return 0.5 if ok else -0.25


# ═══════════════════════════════════════════════════════════════════
# ГЛАВНОЕ НОВОВВЕДЕНИЕ: пересчёт профилей с override-настройками
# ═══════════════════════════════════════════════════════════════════

def compute_profiles(
    df,
    weeks,
    tz_map,
    *,
    conf_override: dict | None = None,
    prior_override: dict | None = None,
    placeholder_override: dict | None = None,
) -> dict:
    """
    Пересчитывает профили всех недель с временными правками
    _CONFIDENCE / _PRIOR_CONFIDENCE / _PLACEHOLDER.
    После завершения восстанавливает оригинальные словари.

    ВАЖНО (почему clear+update, а не переприсваивание):
        calc._CONFIDENCE = old_conf НЕ сработает, если какие-то другие модули
        уже импортировали ссылку на старый dict. .clear() + .update() меняют
        содержимое того же объекта — ссылки остаются валидными.
    """
    old_conf = dict(calc._CONFIDENCE)
    old_prior = dict(calc._PRIOR_CONFIDENCE)
    old_ph = dict(calc._PLACEHOLDER)
    try:
        if conf_override:
            calc._CONFIDENCE.update(conf_override)
        if prior_override:
            calc._PRIOR_CONFIDENCE.update(prior_override)
        if placeholder_override:
            calc._PLACEHOLDER.update(placeholder_override)

        profiles = {}
        for week in weeks:
            df_w = ex.week_slice(df, week, tz_map)
            profiles[week["record_id"]] = calc.calculate_profile(
                df_w,
                tz_map[week["user_id"]],
                week["start_date"],
                week["end_date_exclusive"],
            )
        return profiles
    finally:
        calc._CONFIDENCE.clear()
        calc._CONFIDENCE.update(old_conf)
        calc._PRIOR_CONFIDENCE.clear()
        calc._PRIOR_CONFIDENCE.update(old_prior)
        calc._PLACEHOLDER.clear()
        calc._PLACEHOLDER.update(old_ph)


def evaluate(profiles: dict, ref_map: dict) -> tuple[dict, float]:
    """Считает очки по профилям. Возвращает (stats, total)."""
    stats = defaultdict(lambda: {
        "n": 0, "correct": 0, "wrong": 0, "unknown": 0, "pts": 0.0,
    })
    total = 0.0
    for rid, profile in profiles.items():
        ref = ref_map.get(rid, {})
        for field, val in profile.items():
            v, c = val["value"], val["confidence"]
            t = ref.get(field)
            s = stats[field]
            s["n"] += 1
            if c == 0:
                s["unknown"] += 1
                continue
            ok = check_value(v, t)
            s["correct" if ok else "wrong"] += 1
            p = points(ok, c)
            s["pts"] += p
            total += p
    return stats, total


# ═══════════════════════════════════════════════════════════════════
# Поиск лучшего placeholder для weekday_bedtime
# ═══════════════════════════════════════════════════════════════════

def find_best_bedtime_placeholder(ref_map: dict) -> tuple[str, int, int]:
    """
    Перебирает 'HH:MM' с шагом 15 мин от 21:00 до 02:00
    и возвращает то, что попадает в ±30 мин к максимуму reference.

    Возвращает (best_time, hits, total_refs).
    """
    refs = [
        r.get("weekday_bedtime")
        for r in ref_map.values()
        if r.get("weekday_bedtime")
    ]
    if not refs:
        return ("23:00", 0, 0)

    best_time, best_hits = "23:00", 0
    for offset in range(0, 5 * 60, 15):  # 5 часов × 4 слота в час
        t_min = (21 * 60 + offset) % (24 * 60)
        h, m = divmod(t_min, 60)
        candidate = f"{h:02d}:{m:02d}"
        hits = sum(1 for r in refs if check_value(candidate, r))
        if hits > best_hits:
            best_hits, best_time = hits, candidate
    return (best_time, best_hits, len(refs))


# ═══════════════════════════════════════════════════════════════════
# MAIN — три сценария
# ═══════════════════════════════════════════════════════════════════

def main() -> None:
    with DATA_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    df = ex.events_to_df(data)
    tz_map = ex.user_tz_map(data)
    weeks = data["dataset"]["weeks"]
    ref_map = {r["record_id"]: r["profile"] for r in data["reference"]["weeks"]}

    # ─────────────────────────────────────────────────────────────
    # СЦЕНАРИЙ A: baseline (текущий calculator.py)
    # ─────────────────────────────────────────────────────────────
    print(f"Считаем Сценарий A (baseline, {len(weeks)} недель)...")
    profiles_a = compute_profiles(df, weeks, tz_map)
    stats_a, total_a = evaluate(profiles_a, ref_map)

    print(f"\n{'=' * 90}")
    print(f"  СЦЕНАРИЙ A: BASELINE (как сейчас)")
    print(f"{'=' * 90}")
    print(f"  {'field':24s} {'n':>3s} {'cor':>4s} {'wrong':>6s} {'unk':>4s} "
        f"{'acc':>7s} {'pts':>8s}")
    print("-" * 90)
    for field in sorted(stats_a):
        s = stats_a[field]
        answered = s["n"] - s["unknown"]
        acc = s["correct"] / answered if answered else 0.0
        print(f"  {field:24s} {s['n']:>3d} {s['correct']:>4d} {s['wrong']:>6d} "
            f"{s['unknown']:>4d} {acc:>6.1%} {s['pts']:>+8.2f}")
    print("-" * 90)
    print(f"  {'ИТОГО':24s} {'':>3s} {'':>4s} {'':>6s} {'':>4s} {'':>7s} {total_a:>+8.2f}")

    # ─────────────────────────────────────────────────────────────
    # СЦЕНАРИЙ B: weekday_bedtime soft guess (conf=0.5)
    # ─────────────────────────────────────────────────────────────
    print(f"\n{'=' * 90}")
    print(f"  СЦЕНАРИЙ B: включить weekday_bedtime conf=0.5")
    print(f"  (в _CONFIDENCE для недель с данными И в _PRIOR_CONFIDENCE для недель без)")
    print(f"{'=' * 90}")

    profiles_b = compute_profiles(
        df, weeks, tz_map,
        conf_override={"weekday_bedtime": 0.5},
        prior_override={"weekday_bedtime": 0.5},
    )
    stats_b, total_b = evaluate(profiles_b, ref_map)

    # Показываем только изменения
    print(f"  Что изменилось относительно A:")
    for field in sorted(stats_b):
        if field not in stats_a:
            continue
        delta = stats_b[field]["pts"] - stats_a[field]["pts"]
        if abs(delta) < 0.01:
            continue
        s = stats_b[field]
        answered = s["n"] - s["unknown"]
        acc = s["correct"] / answered if answered else 0.0
        print(f"    {field:24s}  {stats_a[field]['pts']:>+7.2f} → {s['pts']:>+7.2f}  "
            f"(Δ {delta:>+6.2f} | acc={acc:>5.1%} | cor={s['correct']:>2d} wrong={s['wrong']:>2d} unk={s['unknown']})")

    print(f"\n  ИТОГО: {total_a:+.2f} → {total_b:+.2f}  (Δ {total_b - total_a:+.2f})")

    # ─────────────────────────────────────────────────────────────
    # СЦЕНАРИЙ C: B + лучший placeholder
    # ─────────────────────────────────────────────────────────────
    best_time, hits, total_refs = find_best_bedtime_placeholder(ref_map)
    print(f"\n{'=' * 90}")
    print(f"  СЦЕНАРИЙ C: B + placeholder='{best_time}' (оптимум для ±30 мин)")
    print(f"{'=' * 90}")

    # Показываем, насколько лучше лучший placeholder
    cur_hits = sum(1 for r in ref_map.values() if check_value("23:00", r.get("weekday_bedtime")))
    print(f"  Текущий '23:00'    → попадает {cur_hits}/{total_refs} ({cur_hits/total_refs:.1%})")
    print(f"  Лучший '{best_time}'  → попадает {hits}/{total_refs} ({hits/total_refs:.1%})")

    profiles_c = compute_profiles(
        df, weeks, tz_map,
        conf_override={"weekday_bedtime": 0.5},
        prior_override={"weekday_bedtime": 0.5},
        placeholder_override={"weekday_bedtime": best_time},
    )
    stats_c, total_c = evaluate(profiles_c, ref_map)
    print(f"\n  ИТОГО: {total_b:+.2f} → {total_c:+.2f}  (Δ {total_c - total_b:+.2f} от смены placeholder)")

    # ─────────────────────────────────────────────────────────────
    # СВОДКА
    # ─────────────────────────────────────────────────────────────
    print(f"\n{'=' * 90}")
    print(f"  СВОДКА")
    print(f"{'=' * 90}")
    print(f"  A (baseline):                            {total_a:>+8.2f}")
    print(f"  B (+ weekday_bedtime=0.5):               {total_b:>+8.2f}   (Δ {total_b - total_a:+.2f})")
    print(f"  C (B + placeholder='{best_time}'):        {total_c:>+8.2f}   (Δ {total_c - total_a:+.2f})")

    print(f"\n{'─' * 60}")
    if total_c > total_a + 0.5:
        print(f"  ✅ РЕКОМЕНДАЦИЯ: включить Сценарий C")
        print(f"     Прирост: +{total_c - total_a:.2f} очков")
        print(f"\n  Что изменить в calculator.py:")
        print(f"    1. _CONFIDENCE['weekday_bedtime'] = 0.5")
        print(f"    2. _PRIOR_CONFIDENCE['weekday_bedtime'] = 0.5")
        print(f"    3. _PLACEHOLDER['weekday_bedtime'] = '{best_time}'")
        print(f"\n  ⚠️  ВНИМАНИЕ: '{best_time}' оптимизирован на dev-наборе.")
        print(f"     На боевом наборе распределение может быть другим —")
        print(f"     проверь метрику повторно после деплоя.")
    else:
        print(f"  ⚠️  Прирост < 0.5 очков — оставить baseline (Сценарий A).")


if __name__ == "__main__":
    main()