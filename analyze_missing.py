#!/usr/bin/env python3
"""
Анализ отсутствующих источников и prior-распределений.
Помогает решить, какие поля можно "soft guess" с conf=0.5.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import explore_dev as ex
import calculator as calc

DATA_PATH = Path(__file__).resolve().parent / "data" / "dev.json"

TOL_TIME_MIN = 30
TOL_HOURS = 0.5


def check_value(ours, truth) -> bool:
    if ours is None or truth is None:
        return False
    ours_s, truth_s = str(ours), str(truth)
    if ":" in ours_s and ":" in truth_s:
        try:
            h1, m1 = map(int, ours_s.split(":"))
            h2, m2 = map(int, truth_s.split(":"))
            d = abs(h1 * 60 + m1 - h2 * 60 - m2)
            d = min(d, 24 * 60 - d)
            return d <= TOL_TIME_MIN
        except Exception:
            return False
    if isinstance(ours, (int, float)) and isinstance(truth, (int, float)):
        return abs(float(ours) - float(truth)) <= TOL_HOURS
    return ours == truth


def main() -> None:
    with DATA_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    df = ex.events_to_df(data)
    tz_map = ex.user_tz_map(data)
    weeks = data["dataset"]["weeks"]
    ref_map = {r["record_id"]: r["profile"] for r in data["reference"]["weeks"]}

    # ---- 1. Распределение reference по значениям ----
    print("=" * 70)
    print("1. РАСПРЕДЕЛЕНИЕ REFERENCE (для prior guessing)")
    print("=" * 70)
    ref_dist: dict[str, Counter] = defaultdict(Counter)
    for ref in ref_map.values():
        for field, val in ref.items():
            ref_dist[field][val] += 1

    prior_table: dict[str, tuple] = {}
    for field in sorted(ref_dist):
        dist = ref_dist[field]
        total = sum(dist.values())
        top_val, top_n = dist.most_common(1)[0]
        p = top_n / total
        verdict = "✅ soft guess" if p >= 0.40 else ("🟡 marginal" if p >= 0.33 else "❌ no guess")
        prior_table[field] = (top_val, p)
        print(f"  {field:24s} top={str(top_val):15s} p={p:.0%}  {verdict}")
        if len(dist) > 1:
            for v, n in dist.most_common(3):
                print(f"      {str(v):20s} {n:2d}/{total} = {n/total:.0%}")

    # ---- 2. Группы по источникам ----
    print("\n" + "=" * 70)
    print("2. ГРУППЫ ПО ИСТОЧНИКАМ")
    print("=" * 70)
    groups: dict[tuple, list] = defaultdict(list)
    for w in weeks:
        groups[tuple(sorted(w["available_sources"]))].append(w)

    for combo, ws in sorted(groups.items(), key=lambda x: -len(x[1])):
        print(f"  {len(ws):2d} нед: {list(combo)}")

    # ---- 3. Accuracy + unknown по группам ----
    print("\n" + "=" * 70)
    print("3. ACCURACY ПО ГРУППАМ (что мы знаем при каких источниках)")
    print("=" * 70)

    for combo, ws in sorted(groups.items(), key=lambda x: -len(x[1])):
        print(f"\n--- {list(combo)} ({len(ws)} нед) ---")
        stats: dict[str, dict] = defaultdict(lambda: {"ans": 0, "cor": 0, "unk": 0})
        for w in ws:
            rid = w["record_id"]
            try:
                df_w = ex.week_slice(df, w, tz_map)
                profile = calc.calculate_profile(
                    df_w, tz_map[w["user_id"]],
                    w["start_date"], w["end_date_exclusive"],
                )
            except Exception as e:
                print(f"  ERROR {rid}: {e}")
                continue
            ref = ref_map.get(rid, {})
            for field, val in profile.items():
                if val["confidence"] == 0:
                    stats[field]["unk"] += 1
                else:
                    stats[field]["ans"] += 1
                    if check_value(val["value"], ref.get(field)):
                        stats[field]["cor"] += 1

        for field in sorted(stats):
            s = stats[field]
            if s["ans"] > 0:
                acc = s["cor"] / s["ans"]
                print(f"  {field:24s} ans={s['ans']:2d} cor={s['cor']:2d} unk={s['unk']:2d} acc={acc:.0%}")
            else:
                print(f"  {field:24s} все unknown ({s['unk']})")

    # ---- 4. Рекомендация ----
    print("\n" + "=" * 70)
    print("4. РЕКОМЕНДАЦИЯ ПО _PRIOR_CONFIDENCE")
    print("=" * 70)
    print("  Для полей, где в группе много unknown, и prior p ≥ 0.40 — включаем soft guess.")
    print("  Формат:")
    print("    _PRIOR_CONFIDENCE = {")
    for field, (top_val, p) in sorted(prior_table.items()):
        conf = 0.5 if p >= 0.40 else 0.0
        marker = "👈" if conf > 0 else ""
        print(f"        \"{field}\": {conf},  # top={top_val}, p={p:.0%} {marker}")
    print("    }")


if __name__ == "__main__":
    main()
