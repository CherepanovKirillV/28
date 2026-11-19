"""
Локальная эмуляция /run без HTTP: читает data/case3_dev.json,
прогоняет calculator + llm_generator и сохраняет data/run_response.json
в ТОМ ЖЕ формате, что отдаёт main.py (Case3Answers.schema.json).

КЛЮЧЕВОЙ МОМЕНТ: используем _pack_week из main.py — единый источник правды
для формата ответа. Никакой дублирующей логики.
"""
# ── ФИКС импорта: добавляем корень проекта в sys.path ──
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
# ───────────────────────────────────────────────────────

import json

import pandas as pd

import calculator
import llm_generator
from main import _pack_week

DATA_PATH = Path("data") / "case3_dev.json"
OUT_PATH = Path("data") / "run_response.json"


def main():
    with DATA_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    users = {u["user_id"]: u.get("timezone", "Europe/Moscow") for u in data["dataset"]["users"]}
    events = data["dataset"]["events"]
    weeks = data["dataset"]["weeks"]

    # events → DataFrame (как в main.py)
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

    result_weeks = []
    for week in weeks:
        rid = week.get("record_id", "unknown")
        try:
            user_id = week["user_id"]
            tz = users.get(user_id, "Europe/Moscow")
            start = pd.Timestamp(week["start_date"], tz=tz).tz_convert("UTC")
            end = pd.Timestamp(week["end_date_exclusive"], tz=tz).tz_convert("UTC")
            mask = (
                (df["user_id"] == user_id)
                & (df["started_at"] >= start)
                & (df["started_at"] < end)
            )
            week_df = df.loc[mask].copy()

            profile = calculator.calculate_profile(
                week_df, tz, week["start_date"], week["end_date_exclusive"]
            )
            hypotheses = llm_generator.generate_hypotheses(profile)
            if not llm_generator.validate_output(profile, hypotheses):
                hypotheses = llm_generator._get_fallback_hypotheses(profile)

            result_weeks.append(_pack_week(rid, profile, hypotheses))

        except Exception as e:
            print(f"⚠️  {rid}: {type(e).__name__}: {e}")
            fb = calculator.unknown_profile()
            result_weeks.append(
                _pack_week(rid, fb, llm_generator._get_fallback_hypotheses(fb))
            )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump({"weeks": result_weeks}, f, ensure_ascii=False, indent=2)

    print(f"✅ Сохранено: {OUT_PATH}")
    print(f"   Недель: {len(result_weeks)}")
    if result_weeks:
        w0 = result_weeks[0]
        print(f"   Ключи недели[0]: {list(w0.keys())}")
        # Проверка формы: profile обёрнут в {value, confidence}
        f0 = list(w0["profile"].items())[0]
        print(f"   Пример profile[0]['{f0[0]}']: {f0[1]}")
        # Проверка: ровно 3 гипотезы
        print(f"   Гипотез в неделе[0]: {len(w0['hypotheses'])}")


if __name__ == "__main__":
    main()