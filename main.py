"""
FastAPI-приложение для хакатона (кейс 3: анализ профиля здоровья).

ПРИНЦИПЫ:
1. Никогда не отдавать 500 на /run — падение одной недели не убивает остальные.
2. Память < 512 МБ — большие объекты освобождаем через del + gc.collect.
3. Ответ соответствует Case3Answers.schema.json:
      profile.<field> = {value, confidence}
      hypotheses = ровно 3 × {text, confidence}
      в неделе ТОЛЬКО record_id, profile, hypotheses
      value = "unknown", если confidence == 0
"""
import gc
import logging
import os
import re

import pandas as pd
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

import calculator
import llm_generator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

TEAM = os.environ.get("TEAM", "team28")
HACK_API_URL = os.environ.get("HACK_API_URL", "https://hack-api.be-healthy.tech").rstrip("/")


# ─────────────────────────────────────────────────────────────
# Справочники допустимых значений по Case3Answers.schema.json.
# Нужны, чтобы если calculator вернёт опечатку (например "midnight"
# вместо "00:00"), она превратилась в "unknown", а не сломала схему.
# ─────────────────────────────────────────────────────────────
_ENUM_FIELDS = {
    "chronotype":      {"early", "intermediate", "late"},
    "activity_level":  {"low", "medium", "high"},
    "sedentary_hours": {"lt6", "6to9", "gt9"},
    "training_days":   {"0", "1to2", "3plus"},
    "movement_index":  {"lt50", "50to70", "70to85", "85plus"},
}
_BOOL_FIELDS = {"social_jetlag", "works_from_home", "phone_before_sleep"}
_TIME_FIELDS = {"weekday_bedtime", "weekday_wake_time"}
_TIME_PATTERN = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


def _normalize_value(field: str, value, confidence: float):
    if confidence == 0:
        return "unknown"

    if field in _ENUM_FIELDS:
        return value if value in _ENUM_FIELDS[field] else "unknown"

    if field in _BOOL_FIELDS:
        return value if isinstance(value, bool) else "unknown"

    if field in _TIME_FIELDS:
        return value if isinstance(value, str) and _TIME_PATTERN.match(value) else "unknown"

    if field == "average_sleep_hours":
        try:
            v = float(value)
            return v if 0.0 <= v <= 24.0 else "unknown"
        except (TypeError, ValueError):
            return "unknown"

    return value  # неизвестное поле — пропускаем как есть (страховка на будущее)

def _pack_week(rid: str, profile: dict, hypotheses: list[dict]) -> dict:
    normalized_profile = {}
    for field, val in profile.items():
        conf = max(0.0, min(1.0, float(val["confidence"])))
        normalized_profile[field] = {
            "value": _normalize_value(field, val["value"], conf),
            "confidence": conf,
        }

    # Нормализуем гипотезы до 3 штук {text, confidence}
    hyps = []
    for h in (hypotheses or [])[:3]:
        txt = str(h.get("text", "")).strip()
        if not txt:
            continue
        c = max(0.0, min(1.0, float(h.get("confidence", 0.5))))
        hyps.append({"text": txt[:500], "confidence": c})

    # Добиваем безопасной, если пришло меньше 3
    _SAFE = {
        "text": "Твой режим дня имеет особенности, которые можно мягко скорректировать.",
        "confidence": 0.5,
    }
    while len(hyps) < 3:
        hyps.append(dict(_SAFE))

    return {
        "record_id": rid,
        "profile": normalized_profile,
        "hypotheses": hyps,
    }


@app.get("/")
@app.get("/health")
def health():
    return {"team": TEAM, "status": "ok"}


@app.post("/run")
async def run_endpoint(request: Request):
    # ── 1. Разбор запроса ────────────────────────────────────
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    case = body.get("case")
    dataset_code = body.get("dataset_code")
    auth = request.headers.get("Authorization")

    if not case or not dataset_code or not auth:
        raise HTTPException(status_code=400, detail="Missing case, dataset_code, or Authorization")

    # ── 2. Скачивание данных с API хакатона ──────────────────
    try:
        resp = requests.get(
            f"{HACK_API_URL}/case/{case}/getData",
            headers={"Authorization": auth},
            params={"dataset_code": dataset_code},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        logger.error("API request failed: %s", type(e).__name__)
        raise HTTPException(status_code=502, detail="Upstream API error")
    except Exception as e:
        logger.error("Parse error: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Internal error")

    # ── 3. Извлечение полей + освобождение памяти ────────────
    try:
        ds = data["dataset"]
        weeks = ds["weeks"]
        users_list = ds["users"]
        events = ds["events"]
    except KeyError as e:
        logger.error("Missing dataset key: %s", e)
        raise HTTPException(status_code=500, detail="Unexpected dataset structure")

    users = {u["user_id"]: u.get("timezone", "Europe/Moscow") for u in users_list}

    del users_list
    del data
    gc.collect()

    # ── 4. events → DataFrame ────────────────────────────────
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
    del events
    gc.collect()

    df = pd.DataFrame(rows)
    del rows
    gc.collect()

    if not df.empty:
        df["started_at"] = pd.to_datetime(df["started_at"], utc=True)

    # ── 5. Обработка каждой недели ───────────────────────────
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
                logger.warning("Validation failed for %s, using fallback", rid)
                hypotheses = llm_generator._get_fallback_hypotheses(profile)

            result_weeks.append(_pack_week(rid, profile, hypotheses))

            del week_df
        except Exception as e:
            # Одна неделя упала — теряем только её, не все 30.
            logger.error("Week %s failed: %s", rid, type(e).__name__)
            fb_profile = calculator.unknown_profile()
            fb_hypotheses = llm_generator._get_fallback_hypotheses(fb_profile)
            result_weeks.append(_pack_week(rid, fb_profile, fb_hypotheses))

        gc.collect()

    return JSONResponse(content={"weeks": result_weeks})