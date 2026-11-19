#!/usr/bin/env python3
"""
Скачивает dev-набор кейса 3 и печатает структурированный отчёт.
Запускать локально. На стенд НЕ идёт (в docker-образ не кладём).
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

import requests

DATASET_CODE = "case3-dev-v1"
OUT_PATH = Path("data") / "dev.json"
CHUNK_SIZE = 64 * 1024
TIMEOUT = 120


def get_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        print(f"ERROR: {name} не задан. Сделай `source set_env.sh`.", file=sys.stderr)
        sys.exit(1)
    return value


def download(url: str, headers: dict, params: dict) -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"GET {url}  params={params}")
    with requests.get(url, headers=headers, params=params, stream=True, timeout=TIMEOUT) as r:
        if r.status_code != 200:
            print(f"HTTP {r.status_code}: {(r.text or '')[:500]}", file=sys.stderr)
            sys.exit(2)
        total = 0
        with OUT_PATH.open("wb") as f:
            for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
                    total += len(chunk)
    print(f"  → {OUT_PATH}  ({total / 1024 / 1024:.2f} МБ)")


def show_meta(ds: dict) -> None:
    print("\n=== 1. dataset.meta ===")
    for k, v in ds.get("meta", {}).items():
        print(f"  {k:24s} {v!r}")


def show_users(ds: dict) -> None:
    print("\n=== 2. users ===")
    users = ds.get("users", [])
    print(f"  всего: {len(users)}")
    tz = Counter(u.get("timezone") for u in users)
    for t, n in tz.most_common():
        print(f"  timezone {t!r}: {n}")


def show_events(ds: dict) -> None:
    print("\n=== 3. events ===")
    events = ds.get("events", [])
    print(f"  всего: {len(events)}")
    by_type = Counter()
    by_source = Counter()
    for e in events:
        by_type[e.get("type")] += 1
        by_source[e.get("source")] += 1
    print("  по type:")
    for t, n in by_type.most_common():
        print(f"    {t:20s} {n:6d}")
    print("  по source:")
    for s, n in by_source.most_common():
        print(f"    {s:20s} {n:6d}")
    # Пример payload для каждого type
    print("  пример payload по type:")
    seen = set()
    for e in events:
        t = e.get("type")
        if t in seen:
            continue
        seen.add(t)
        print(f"    {t}: {json.dumps(e.get('payload'), ensure_ascii=False)}")


def show_weeks(ds: dict) -> None:
    print("\n=== 4. weeks ===")
    weeks = ds.get("weeks", [])
    print(f"  всего: {len(weeks)}")
    print("  ключи: " + ", ".join(weeks[0].keys()) if weeks else "")
    combos = Counter(tuple(sorted(w.get("available_sources") or [])) for w in weeks)
    print("  распределение available_sources:")
    for combo, n in combos.most_common():
        print(f"    {n:3d} нед.: {list(combo)}")


def show_reference(ref: dict) -> None:
    print("\n=== 5. reference ===")
    meta = ref.get("meta", {})
    print(f"  meta: {meta}")
    weeks = ref.get("weeks", [])
    print(f"  недель: {len(weeks)}")
    if weeks:
        w = weeks[0]
        print(f"  [0] record_id: {w.get('record_id')}")
        print(f"  [0] profile: {json.dumps(w.get('profile'), ensure_ascii=False)}")
        print(f"  [0] rationale: {w.get('rationale', '')[:300]}")


def show_schema(ds: dict) -> None:
    print("\n=== 6. profile_fields_schema ===")
    schema = ds.get("profile_fields_schema", {})
    props = schema.get("properties", {})
    required = schema.get("required", [])
    print(f"  required ({len(required)}): {required}")
    print(f"  additionalProperties: {schema.get('additionalProperties')}")
    print("  поля:")
    for name, spec in props.items():
        if "anyOf" in spec:
            opts = [o.get("const") for o in spec["anyOf"]]
            print(f"    {name:24s} enum {opts}")
        elif spec.get("type") == "number":
            print(f"    {name:24s} number [{spec.get('minimum')}..{spec.get('maximum')}]")
        elif spec.get("type") == "boolean":
            print(f"    {name:24s} boolean")
        elif "pattern" in spec:
            print(f"    {name:24s} string pattern {spec['pattern']}")
        else:
            print(f"    {name:24s} {spec}")


def show_formula(ds: dict) -> None:
    print("\n=== 7. movement_index_formula ===")
    f = ds.get("movement_index_formula", {})
    for k in ("version", "status", "description", "expression",
              "missing_data_policy", "adaptation_status"):
        print(f"  {k}: {f.get(k)}")


def main() -> None:
    api_url = get_env("HACK_API_URL").rstrip("/")
    token = get_env("HACK_TEAM_TOKEN")
    url = f"{api_url}/case/3/getData"
    params = {"dataset_code": DATASET_CODE}
    headers = {"Authorization": f"Bearer {token}"}

    download(url, headers, params)

    print("Парсим JSON…")
    with OUT_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    ds = data.get("dataset", {})
    ref = data.get("reference", {})

    show_meta(ds)
    show_users(ds)
    show_events(ds)
    show_weeks(ds)
    show_reference(ref)
    show_schema(ds)
    show_formula(ds)

    print("\nГотово.")


if __name__ == "__main__":
    main()
