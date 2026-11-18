"""
FastAPI-приложение для хакатона (кейс 3: анализ профиля здоровья).

КЛЮЧЕВЫЕ ПРИНЦИПЫ:
1. Никогда не отдавать 500 на /run — падение одной недели не должно
   убивать остальные 29 (0 очков за краш хуже, чем 0 очков за пустой ответ).
2. Память < 512 МБ — все большие объекты освобождаем сразу (del + gc.collect).
3. Формат ответа соответствует profile_fields_schema:
      profile — ПЛОСКИЕ значения (schema-compliant)
      confidence — отдельно (для скоринга)
      hypotheses + rationale — текст для пользователя
"""
import gc
import logging
import os

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


# ──────────────────────────────────────────────────────────────
# Вспомогательная функция сборки недели в правильный формат.
# Вынесена отдельно, чтобы не дублировать в try и except.
# ──────────────────────────────────────────────────────────────
def _pack_week(rid: str, profile: dict, hypotheses: list[dict]) -> dict:
    """
    Преобразует внутренний формат calculator в формат ответа /run.

    ВНУТРИ: {"chronotype": {"value": "early", "confidence": 0.85}}
    НАРУЖУ: {"chronotype": "early"}  — потому что схема profile_fields_schema
            требует ПЛОСКИЕ значения, а не обёртку {value, confidence}.
    Уверенность сохраняем отдельным словарём — для скоринга +1 / +0.5.
    """
    plain_profile = {field: val["value"] for field, val in profile.items()}
    confidences = {field: val["confidence"] for field, val in profile.items()}
    # rationale — на случай, если платформа ждёт строку (как в reference в dev.json)
    rationale_text = " ".join(h["text"] for h in hypotheses if h.get("text"))

    return {
        "record_id": rid,
        "profile": plain_profile,          # ← соответствует profile_fields_schema
        "confidence": confidences,         # ← отдельно, для скоринга
        "hypotheses": hypotheses,          # ← массив из 3 гипотез (наш формат)
        "rationale": rationale_text[:2000],# ← строка (defensive, совместимость с reference)
    }


# ──────────────────────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────────────────────
@app.get("/")
@app.get("/health")
def health():
    return {"team": TEAM, "status": "ok"}


# ──────────────────────────────────────────────────────────────
# Основной эндпоинт
# ──────────────────────────────────────────────────────────────
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

    # ── 3. Извлечение полей и освобождение памяти ────────────
    try:
        ds = data["dataset"]
        weeks = ds["weeks"]
        users_list = ds["users"]
        events = ds["events"]
    except KeyError as e:
        logger.error("Missing dataset key: %s", e)
        raise HTTPException(status_code=500, detail="Unexpected dataset structure")

    users = {u["user_id"]: u.get("timezone", "Europe/Moscow") for u in users_list}

    # del + gc.collect: data — огромный dict (~9 МБ JSON), держать не нужно
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

            # Расчёт 11 полей (внутри — обёртки {value, confidence})
            profile = calculator.calculate_profile(
                week_df, tz, week["start_date"], week["end_date_exclusive"]
            )

            # Генерация 3 гипотез (LLM + fallback + пост-фильтр)
            hypotheses = llm_generator.generate_hypotheses(profile)

            # Пост-фильтр: если LLM намусорила — заменяем fallback-ом
            if not llm_generator.validate_output(profile, hypotheses):
                logger.warning("Validation failed for %s, using fallback", rid)
                hypotheses = llm_generator._get_fallback_hypotheses(profile)

            # ФИКС: раздеваем profile, чтобы прошёл profile_fields_schema
            result_weeks.append(_pack_week(rid, profile, hypotheses))

            del week_df  # освобождаем срез — он больше не нужен
        except Exception as e:
            # Одна неделя упала — теряем только её, не все 30.
            logger.error("Week %s failed: %s", rid, type(e).__name__)
            fb_profile = calculator.unknown_profile()
            fb_hypotheses = llm_generator._get_fallback_hypotheses(fb_profile)
            result_weeks.append(_pack_week(rid, fb_profile, fb_hypotheses))

        # gc.collect после каждой недели — освобождаем временные объекты
        gc.collect()

    # ── 6. Отдача ответа ─────────────────────────────────────
    return JSONResponse(content={"weeks": result_weeks})