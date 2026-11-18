"""
Исследование dev-набора кейса 3 — «идеальная» версия.

Что делает:
- Загружает data/dev.json (путь относительно файла, не CWD)
- Показывает структуру, распределения, примеры
- Для первой недели: wearable/phone/presence + графики
- Извлекает «ночи сна» с учётом TZ пользователя и стадий
- Сверяет наши расчёты с reference

Запуск:
    env28
    python explore_dev.py
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

DATA_PATH = Path(__file__).resolve().parent / "data" / "dev.json"

ASLEEP_STAGES = {"light", "deep", "rem"}
SAMPLE_MIN = 10  # wearable_sample шаг = 10 минут


# ============================== загрузка ==============================

def load_all() -> dict:
    with DATA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def user_tz_map(data: dict) -> dict[str, str]:
    """user_id -> timezone (Europe/Moscow и т.п.)."""
    return {u["user_id"]: u["timezone"] for u in data["dataset"]["users"]}


def events_to_df(data: dict) -> pd.DataFrame:
    """Все события → DataFrame. started_at/ended_at в UTC."""
    rows = []
    for e in data["dataset"]["events"]:
        p = e.get("payload") or {}
        rows.append({
            "event_id": e["event_id"],
            "user_id": e["user_id"],
            "started_at": e["started_at"],
            "ended_at": e.get("ended_at"),
            "source": e["source"],
            "type": e["type"],
            "bpm": p.get("bpm"),
            "steps": p.get("steps"),
            "sleep_stage": p.get("sleep_stage"),
            "screen_minutes": p.get("screen_minutes"),
            "charging": p.get("charging"),
            "room_id": p.get("room_id"),
            "present": p.get("present"),
            "movement": p.get("movement"),
        })
    df = pd.DataFrame(rows)
    df["started_at"] = pd.to_datetime(df["started_at"], utc=True)
    df["ended_at"] = pd.to_datetime(df["ended_at"], utc=True, errors="coerce")
    return df


def week_slice(df: pd.DataFrame, week: dict, tz_map: dict[str, str]) -> pd.DataFrame:
    """
    События пользователя за неделю.
    ВАЖНО: start_date/end_date_exclusive — ЛОКАЛЬНЫЕ даты пользователя.
    end_date_exclusive НЕ включается.
    """
    tz = tz_map[week["user_id"]]
    start = pd.Timestamp(week["start_date"], tz=tz).tz_convert("UTC")
    end = pd.Timestamp(week["end_date_exclusive"], tz=tz).tz_convert("UTC")
    mask = (
        (df["user_id"] == week["user_id"])
        & (df["started_at"] >= start)
        & (df["started_at"] < end)
    )
    return df.loc[mask].copy()


# ============================== сон ==============================

def extract_nights(
    w: pd.DataFrame, tz: str, week_start: date, week_end: date
) -> pd.DataFrame:
    """
    Один ряд на «ночь сна».
    - Считаем только стадии light/deep/rem (awake — не сон)
    - Склеиваем micro-пробуждения (разрыв < 60 мин)
    - is_boundary: ночь прижата к границе недели (может быть обрезана)
    - sleep_h = фактический сон (сумма минут asleep-стадий)
    """
    cols = ["date_local", "bedtime", "waketime", "time_in_bed_h", "sleep_h", "is_boundary"]
    empty = pd.DataFrame(columns=cols)
    if w.empty or not w["sleep_stage"].notna().any():
        return empty

    w = w.sort_values("started_at").copy()
    w["is_asleep"] = w["sleep_stage"].isin(ASLEEP_STAGES)
    w["local_start"] = w["started_at"].dt.tz_convert(tz)
    w["local_end"] = w["local_start"] + pd.Timedelta(minutes=SAMPLE_MIN)

    # Собираем серии asleep (разрыв > 60 мин = новая ночь)
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

    # Формируем строки + флаг boundary
    rows = []
    last_day = week_end - timedelta(days=1)
    for s, e, asleep_count in nights:
        tib_h = (e - s).total_seconds() / 3600
        sleep_h = asleep_count * SAMPLE_MIN / 60
        d = s.date()
        # хвост предыдущей ночи
        boundary = (d == week_start and s.hour < 6)
        # обрезано концом недели
        boundary = boundary or (e.date() >= week_end) or (d == last_day and s.hour >= 20)
        rows.append({
            "date_local": d,
            "bedtime": s,
            "waketime": e,
            "time_in_bed_h": round(tib_h, 2),
            "sleep_h": round(sleep_h, 2),
            "is_boundary": boundary,
        })
    return pd.DataFrame(rows)


def bedtime_to_min(ts) -> int:
    """Минуты от 18:00 (18:00=0, 00:00=360, 03:00=540) — для медианы отбоя."""
    t = ts.time()
    m = t.hour * 60 + t.minute
    return (m - 18 * 60) % (24 * 60)


def min_to_bedtime(m: float) -> str:
    total = int(round(m + 18 * 60)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def wake_to_min(ts) -> int:
    t = ts.time()
    return t.hour * 60 + t.minute


def min_to_wake(m: float) -> str:
    total = int(round(m)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


# ============================== вывод ==============================

def describe_week(df_week: pd.DataFrame, label: str) -> None:
    print(f"\n=== Неделя {label} ===")
    print(f"  событий: {len(df_week)}")
    print(f"  по source: {df_week['source'].value_counts().to_dict()}")
    print(f"  по type: {df_week['type'].value_counts().to_dict()}")


def show_wearable(df_week: pd.DataFrame, tz: str) -> None:
    w = df_week[df_week["source"] == "wearable"].copy()
    if w.empty:
        print("\n  wearable: НЕТ")
        return
    print(f"\n=== wearable_sample ({len(w)} событий) ===")
    print(f"  шаг (мин): {w['started_at'].diff().dt.total_seconds().median() / 60}")
    print(f"  sleep_stage: {w['sleep_stage'].value_counts().to_dict()}")
    print(f"  steps: сумма {w['steps'].sum():.0f}, медиана {w['steps'].median():.1f}")
    print(f"  bpm: min {w['bpm'].min():.0f}, max {w['bpm'].max():.0f}, медиана {w['bpm'].median():.0f}")
    w_local = w.copy()
    w_local["hour"] = w_local["started_at"].dt.tz_convert(tz).dt.hour
    by_hour = w_local.groupby("hour")["steps"].mean()
    print(f"  средние шаги по часам (TZ={tz}):")
    for h in range(24):
        v = by_hour.get(h, 0)
        bar = "█" * int(v / 20)
        print(f"    {h:02d}: {v:6.1f}  {bar}")


def show_phone(df_week: pd.DataFrame) -> None:
    p = df_week[df_week["source"] == "phone"].copy()
    if p.empty:
        print("\n  phone: НЕТ")
        return
    print(f"\n=== phone_sample ({len(p)} событий) ===")
    print(f"  шаг (мин): {p['started_at'].diff().dt.total_seconds().median() / 60}")
    print(f"  steps сумма: {p['steps'].sum():.0f}")
    print(f"  screen_minutes: сумма {p['screen_minutes'].sum():.0f}, медиана {p['screen_minutes'].median():.0f}")
    print(f"  charging True: {(p['charging'] == True).sum()} из {len(p)}")


def show_presence(df_week: pd.DataFrame) -> None:
    s = df_week[df_week["source"] == "smart_home"]
    if s.empty:
        print("\n  smart_home: НЕТ")
        return
    print(f"\n=== presence ({len(s)} событий) ===")
    print(f"  комнаты: {s['room_id'].value_counts().to_dict()}")
    print(f"  present True: {(s['present'] == True).sum()}, movement True: {(s['movement'] == True).sum()}")


def show_nights(nights: pd.DataFrame) -> None:
    if nights.empty:
        print("\n=== Ночи: НЕТ ===")
        return
    valid = nights[~nights["is_boundary"]]
    print(f"\n=== Ночи ({len(nights)} всего, {len(valid)} валидных) ===")
    print(nights.to_string(index=False))
    if not valid.empty:
        print(f"\n  Сон (по стадиям, без границ):")
        print(f"    среднее: {valid['sleep_h'].mean():.2f} ч")
        print(f"    медиана: {valid['sleep_h'].median():.2f} ч")


def show_reference(ref: dict) -> None:
    print(f"\n=== Reference для {ref['record_id']} ===")
    for k, v in ref["profile"].items():
        print(f"  {k:24s} {v!r}")
    if "rationale" in ref:
        print(f"  rationale: {ref['rationale'][:400]}")


def compare_with_reference(
    df_week: pd.DataFrame, nights: pd.DataFrame, ref: dict
) -> None:
    print("\n" + "=" * 60)
    print("СВЕРКА С REFERENCE")
    print("=" * 60)
    valid = nights[~nights["is_boundary"]] if not nights.empty else nights

    # Сон
    if not valid.empty:
        our_avg = valid["sleep_h"].mean()
        ref_avg = ref["profile"]["average_sleep_hours"]
        print(f"  average_sleep_hours:   {our_avg:.2f}  vs  {ref_avg:.2f}  (Δ {our_avg - ref_avg:+.2f})")

        weekday = valid[valid["date_local"].apply(lambda d: d.weekday() < 5)]
        if not weekday.empty:
            bt = weekday["bedtime"].apply(bedtime_to_min).median()
            wt = weekday["waketime"].apply(wake_to_min).median()
            print(f"  weekday_bedtime:       {min_to_bedtime(bt)}  vs  {ref['profile']['weekday_bedtime']}")
            print(f"  weekday_wake_time:     {min_to_wake(wt)}  vs  {ref['profile']['weekday_wake_time']}")

    # Шаги
    total_steps = df_week["steps"].sum() if not df_week.empty else 0
    avg_steps = total_steps / 7
    print(f"  шаги (среднее в день): {avg_steps:.0f}  (reference rationale упоминает 7524)")


# ============================== main ==============================

def main() -> None:
    data = load_all()
    df = events_to_df(data)
    tz_map = user_tz_map(data)

    print(f"Всего событий в df: {len(df)}")
    print(f"Память: {df.memory_usage(deep=True).sum() / 1024 / 1024:.2f} МБ")

    weeks = data["dataset"]["weeks"]
    week0 = weeks[0]
    user_tz = tz_map[week0["user_id"]]
    print(f"\nНеделя [0]: {week0['record_id']} (user={week0['user_id']}, tz={user_tz})")
    print(f"  start_date={week0['start_date']}, end_date_exclusive={week0['end_date_exclusive']}")
    print(f"  available_sources={week0['available_sources']}")

    df_w0 = week_slice(df, week0, tz_map)
    describe_week(df_w0, week0["record_id"])
    show_wearable(df_w0, user_tz)
    show_phone(df_w0)
    show_presence(df_w0)

    w = df_w0[df_w0["source"] == "wearable"]
    ws = pd.Timestamp(week0["start_date"]).date()
    we = pd.Timestamp(week0["end_date_exclusive"]).date()
    nights = extract_nights(w, user_tz, ws, we)
    show_nights(nights)

    ref = next(
        r for r in data["reference"]["weeks"] if r["record_id"] == week0["record_id"]
    )
    show_reference(ref)
    compare_with_reference(df_w0, nights, ref)

    # print("\n" + "=" * 60)
    # print("ПРОВЕРКА ПЕРЕД КОММИТОМ")
    # print("=" * 60)
    # print("  git status")
    # print("  git diff --staged --name-only   # убедись: НЕТ data/, секретов, .venv")
    # print("  git add main.py requirements.txt start.sh .gitignore explore_dev.py")
    # print("  git commit -m 'feat: ...'")
    # print("  git push origin main             # ← не забудь!")
    # print("  ⚠️  push → деплой на стенд. Проверь: curl .../health → 200")


if __name__ == "__main__":
    main()
