# main.py
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


@app.get("/")
def root():
    return {"team": TEAM, "status": "ok"}


@app.get("/health")
def health():
    return {"team": TEAM, "status": "ok"}


@app.post("/run")
async def run_endpoint(request: Request):
    # 1. Парсинг тела
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    case = body.get("case")
    dataset_code = body.get("dataset_code")
    auth = request.headers.get("Authorization")

    if not case or not dataset_code or not auth:
        raise HTTPException(
            status_code=400,
            detail="Missing case, dataset_code, or Authorization",
        )

    # 2. Запрос данных
    try:
        resp = requests.get(
            f"{HACK_API_URL}/case/{case}/getData",
            headers={"Authorization": auth},
            params={"dataset_code": dataset_code},
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        logger.error("API request failed: %s", type(e).__name__)
        raise HTTPException(status_code=502, detail="Upstream API error")
    except Exception as e:
        logger.error("Parse error: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Internal error")

    # 3. Извлечение и освобождение памяти
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
    del data  # free everything else

    # 4. events → DataFrame (только нужные колонки, потом освобождаем events)
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

    df = pd.DataFrame(rows)
    del rows

    if not df.empty:
        df["started_at"] = pd.to_datetime(df["started_at"], utc=True)

    # 5. Обработка каждой недели
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

            result_weeks.append({
                "record_id": rid,  # ← record_id, не week_id!
                "profile": profile,
                "hypotheses": hypotheses,
            })
        except Exception as e:
            logger.error("Week %s failed: %s", rid, type(e).__name__)
            result_weeks.append({
                "record_id": rid,
                "profile": calculator.unknown_profile(),
                "hypotheses": [
                    {"text": "Недостаточно данных для формирования гипотезы.", "confidence": 0.0},
                    {"text": "Недостаточно данных для формирования гипотезы.", "confidence": 0.0},
                    {"text": "Недостаточно данных для формирования гипотезы.", "confidence": 0.0},
                ],
            })

    return JSONResponse(content={"weeks": result_weeks})
