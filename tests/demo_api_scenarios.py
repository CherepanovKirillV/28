# tests/demo_api_scenarios.py
"""
6 сценариев для онлайн-показа. Каждый — независимый.
Запуск:
    python tests/demo_api_scenarios.py
    python tests/demo_api_scenarios.py --only run_happy
"""
import argparse
import json
import os
import sys
import time

import requests

STEND = "https://team28.hack.be-healthy.tech"
TOKEN = os.environ.get("HACK_TEAM_TOKEN", "")


def _print(title: str, status: str = "ok"):
    icons = {"ok": "✅", "fail": "❌", "info": "ℹ️", "slow": "⏳"}
    print(f"{icons.get(status, '·')} {title}")


# ── Сценарий 1: сервис жив ──────────────────────────────
def scenario_health():
    """Жюри: 'А сервис вообще работает?'"""
    t0 = time.time()
    r = requests.get(f"{STEND}/health", timeout=10)
    dt = time.time() - t0
    assert r.status_code == 200, f"HTTP {r.status_code}"
    data = r.json()
    assert data.get("status") == "ok", data
    _print(f"/health → 200, {dt*1000:.0f}ms, {data}", "ok")


# ── Сценарий 2: основной путь ───────────────────────────
def scenario_run_happy():
    """Жюри: 'Покажи, что всё работает end-to-end'."""
    _print("POST /run (до 15 минут)...", "slow")
    t0 = time.time()
    r = requests.post(
        f"{STEND}/run",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"case": 3, "dataset_code": "case3-dev-v1"},
        timeout=1800,
    )
    dt = time.time() - t0
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
    data = r.json()
    weeks = data.get("weeks", [])
    assert len(weeks) == 30, f"weeks={len(weeks)}, ожидалось 30"

    # Сохраняем для последующих проверок
    with open("/tmp/demo_run.json", "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    w0 = weeks[0]
    _print(f"/run → 200, weeks=30, {dt:.1f}s", "ok")
    _print(f"  record_id: {w0.get('record_id')}", "info")
    _print(f"  profile keys: {list(w0.get('profile', {}).keys())[:3]}...", "info")


# ── Сценарий 3: битый JSON ──────────────────────────────
def scenario_bad_json():
    """Жюри: 'А если я пришлю мусор?' → 400, не 500."""
    r = requests.post(
        f"{STEND}/run",
        headers={"Authorization": f"Bearer {TOKEN}"},
        data="{this is not json",
        timeout=10,
    )
    assert r.status_code == 400, f"ожидалось 400, получили {r.status_code}"
    _print(f"битый JSON → {r.status_code} (правильно: 400, не 500)", "ok")


# ── Сценарий 4: нет токена ──────────────────────────────
def scenario_no_auth():
    """Жюри: 'А если токена нет?' → 400."""
    r = requests.post(
        f"{STEND}/run",
        json={"case": 3, "dataset_code": "case3-dev-v1"},
        timeout=10,
    )
    assert r.status_code == 400, f"ожидалось 400, получили {r.status_code}"
    _print(f"нет Authorization → {r.status_code} (правильно: 400)", "ok")


# ── Сценарий 5: не хватает поля ─────────────────────────
def scenario_missing_field():
    """Жюри: 'А если dataset_code забыли?' → 400."""
    r = requests.post(
        f"{STEND}/run",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"case": 3},  # нет dataset_code
        timeout=10,
    )
    assert r.status_code == 400, f"ожидалось 400, получили {r.status_code}"
    _print(f"нет dataset_code → {r.status_code} (правильно: 400)", "ok")


# ── Сценарий 6: несуществующий dataset ──────────────────
def scenario_unknown_dataset():
    """Жюри: 'А если dataset_code несуществующий?' → 502 от апстрима."""
    r = requests.post(
        f"{STEND}/run",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"case": 3, "dataset_code": "nonexistent-dataset-xyz"},
        timeout=30,
    )
    # 502 = Bad Gateway (апстрим ругнулся), не 500
    assert r.status_code in (400, 404, 502), f"неожиданный код: {r.status_code}"
    _print(f"неизвестный dataset → {r.status_code} (правильно: 4xx/502, не 500)", "ok")


# ── Runner ───────────────────────────────────────────────
SCENARIOS = {
    "health": scenario_health,
    "bad_json": scenario_bad_json,
    "no_auth": scenario_no_auth,
    "missing_field": scenario_missing_field,
    "unknown_dataset": scenario_unknown_dataset,
    "run_happy": scenario_run_happy,  # самый долгий — последним
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Только один сценарий по имени")
    parser.add_argument("--skip-slow", action="store_true", help="Пропустить /run (быстрый прогон)")
    args = parser.parse_args()

    if not TOKEN:
        print("❌ HACK_TEAM_TOKEN не задан. source set_env.sh")
        sys.exit(1)

    if args.only:
        if args.only not in SCENARIOS:
            print(f"❌ Неизвестный сценарий: {args.only}")
            print(f"   Доступно: {list(SCENARIOS.keys())}")
            sys.exit(1)
        scenarios = {args.only: SCENARIOS[args.only]}
    else:
        scenarios = SCENARIOS
        if args.skip_slow:
            scenarios = {k: v for k, v in scenarios.items() if k != "run_happy"}

    print(f"═══ Демо-сценарии ({len(scenarios)}) ═══")
    print()

    failed = 0
    for name, fn in scenarios.items():
        print(f"▶ {name}")
        try:
            fn()
        except AssertionError as e:
            _print(f"  ПРОВАЛ: {e}", "fail")
            failed += 1
        except Exception as e:
            _print(f"  ОШИБКА: {type(e).__name__}: {e}", "fail")
            failed += 1
        print()

    if failed:
        print(f"❌ Провалено {failed} из {len(scenarios)}")
        sys.exit(1)
    else:
        print(f"✅ Все {len(scenarios)} сценариев прошли")


if __name__ == "__main__":
    main()