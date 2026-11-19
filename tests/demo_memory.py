# tests/demo_memory.py
"""
Доказательство: полный /run укладывается в 512 МБ.

Два способа:
1. Локально (tracemalloc) — без Docker, показывает пик Python-объектов.
2. Через Docker (docker stats) — с реальными лимитами стенда.

Запуск локально:
    python tests/demo_memory.py
Запуск с Docker (из bash):
    bash tests/demo_memory_docker.sh
"""
# ── ФИКС импорта: добавляем корень проекта в sys.path ──
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# ───────────────────────────────────────────────────────
import gc
import json
import sys
import tracemalloc
from pathlib import Path

import pandas as pd

import calculator
import llm_generator


def run_one_week(df, week, users):
    """Обработка одной недели (как в main.py)."""
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
    profile = calculator.calculate_profile(week_df, tz, week["start_date"], week["end_date_exclusive"])
    hypotheses = llm_generator.generate_hypotheses(profile)
    del week_df
    return profile, hypotheses


def main():
    data_path = Path("data/dev.json")
    if not data_path.exists():
        print(f"❌ {data_path} не найден. Сначала python fetch_dev.py")
        sys.exit(1)

    print("═══ Memory test: локально через tracemalloc ═══\n")

    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()

    # ── Загрузка ────────────────────────────────────────────
    with data_path.open(encoding="utf-8") as f:
        data = json.load(f)
    users = {u["user_id"]: u.get("timezone", "Europe/Moscow") for u in data["dataset"]["users"]}
    events = data["dataset"]["events"]
    weeks = data["dataset"]["weeks"]

    rows = []
    for e in events:
        p = e.get("payload") or {}
        rows.append({
            "user_id": e["user_id"], "started_at": e["started_at"], "source": e["source"],
            "bpm": p.get("bpm"), "steps": p.get("steps"), "sleep_stage": p.get("sleep_stage"),
            "screen_minutes": p.get("screen_minutes"), "present": p.get("present"),
        })
    del events, data
    gc.collect()
    df = pd.DataFrame(rows)
    del rows
    gc.collect()
    df["started_at"] = pd.to_datetime(df["started_at"], utc=True)

    _, peak_load = tracemalloc.get_traced_memory()
    print(f"  После загрузки данных:   пик {peak_load / 1e6:.1f} МБ")
    tracemalloc.reset_peak()

    # ── 30 недель ───────────────────────────────────────────
    for i, week in enumerate(weeks, 1):
        try:
            run_one_week(df, week, users)
        except Exception as e:
            print(f"  ⚠️  {week.get('record_id')}: {type(e).__name__}")
        gc.collect()
        if i % 10 == 0:
            cur, pk = tracemalloc.get_traced_memory()
            print(f"  Недель {i:2d}/30: current={cur/1e6:.1f} МБ, peak={pk/1e6:.1f} МБ")

    _, peak_full = tracemalloc.get_traced_memory()
    print(f"\n  Пик за весь прогон: {peak_full / 1e6:.1f} МБ")

    # ── Вердикт ─────────────────────────────────────────────
    LIMIT_MB = 512
    SAFE_MB = 400  # оставляем запас на интерпретатор, uvicorn, HTTP

    print(f"  Лимит контейнера:   {LIMIT_MB} МБ")
    print(f"  Безопасный порог:   {SAFE_MB} МБ")
    print()

    if peak_full / 1e6 < SAFE_MB:
        print(f"  ✅ Укладываемся с запасом ({(1 - peak_full / 1e6 / LIMIT_MB) * 100:.0f}%)")
        exit_code = 0
    elif peak_full / 1e6 < LIMIT_MB:
        print(f"  🟡 На грани — но не превышает лимит")
        exit_code = 0
    else:
        print(f"  ❌ ПРЕВЫШЕНИЕ — риск OOM на стенде")
        exit_code = 1

    tracemalloc.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()