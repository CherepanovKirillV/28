"""
Генерация 3 гипотез об образе жизни пользователя.

СТРАТЕГИЯ:
1. ОДИН вызов LLM — ОДИН ответ с массивом из 3 гипотез.
   (System prompt просит "РОВНО 3 гипотезы, JSON-массив".)
2. Если LLM упала / тормозит / вернула мусор — fallback без сети.
3. Медицинские термины вырезаются пост-фильтром (двойная защита).
4. Формат гипотез соответствует Case3Answers.schema.json:
   [{"text": "...", "confidence": 0.8}, ...] × 3
"""
import json
import logging
import os
import re

# ПОЧЕМУ ТАК:
# - OpenAI — клиент
# - APIError — базовое исключение (сеть, 4xx/5xx)
# - APITimeoutError — ИМЕННО таймаут (openai.Timeout — это httpx-конфиг, НЕ исключение)
from openai import OpenAI, APIError, APITimeoutError

logger = logging.getLogger(__name__)

MEDICAL_STOP_WORDS = [
    "диагноз", "болезнь", "синдром", "лечение", "доза", "препарат",
    "терапия", "инсомния", "апноэ", "депрессия", "бессонница", "расстройство",
]

_SAFE_HYPOTHESIS = {
    "text": "Твой режим дня имеет особенности, которые можно мягко скорректировать для улучшения самочувствия.",
    "confidence": 0.5,
}


# ─────────────────────────────────────────────────────────────
# ГЛАВНАЯ ФУНКЦИЯ
# ─────────────────────────────────────────────────────────────
def generate_hypotheses(profile: dict) -> list[dict]:
    """
    Возвращает РОВНО 3 гипотезы формата {text, confidence}.
    Один вызов LLM → один ответ с массивом из 3 штук.
    При любой ошибке — fallback без сети.
    """
    try:
        hypotheses = _get_llm_hypotheses(profile)
    except Exception as e:
        # Ловим ВСЁ: APIError, APITimeoutError, TypeError, JSONDecodeError, что угодно.
        # Exception — родитель всех «обычных» ошибок, дополнительно перечислять не нужно.
        logger.warning("LLM вызов не удался (%s). Используем fallback.", type(e).__name__)
        hypotheses = _get_fallback_hypotheses(profile)

    # Пост-фильтр: вырезаем мед. термины (вторая линия защиты)
    filtered = []
    for h in hypotheses:
        text = (h.get("text") or "").lower()
        if any(w in text for w in MEDICAL_STOP_WORDS):
            logger.warning("Гипотеза содержит мед. термин — заменена")
            filtered.append(_SAFE_HYPOTHESIS.copy())
        else:
            filtered.append(h)

    # Гарантируем ровно 3
    while len(filtered) < 3:
        filtered.append(_SAFE_HYPOTHESIS.copy())

    # Нормализация: text ≤ 500 символов, confidence ∈ [0.0, 1.0]
    result = []
    for h in filtered[:3]:
        result.append({
            "text": str(h.get("text", ""))[:500],
            "confidence": max(0.0, min(1.0, float(h.get("confidence", 0.5)))),
        })
    return result


def validate_output(profile: dict, hypotheses: list) -> bool:
    """Проверяет, что ответ готов к отдаче наружу."""
    if not isinstance(hypotheses, list) or len(hypotheses) != 3:
        return False

    for h in hypotheses:
        if not isinstance(h, dict) or "text" not in h or "confidence" not in h:
            return False
        text = str(h["text"]).lower()
        if any(w in text for w in MEDICAL_STOP_WORDS):
            return False
        conf = h["confidence"]
        if isinstance(conf, bool):
            return False
        if not isinstance(conf, (int, float)) or not (0.0 <= conf <= 1.0):
            return False

    for field, val in profile.items():
        if not isinstance(val, dict) or "value" not in val or "confidence" not in val:
            return False
        conf = val["confidence"]
        if isinstance(conf, bool):
            return False
        if not isinstance(conf, (int, float)) or not (0.0 <= conf <= 1.0):
            return False

    return True


# ─────────────────────────────────────────────────────────────
# ВЫЗОВ LLM — ОДИН запрос, ОДИН ответ с 3 гипотезами
# ─────────────────────────────────────────────────────────────
def _get_llm_hypotheses(profile: dict) -> list[dict]:
    """
    Делает ОДИН запрос к LLM. В ответ ожидает JSON-массив из 3 гипотез.
    Бросает любое исключение наверх — его ловит generate_hypotheses.

    ВАЖНО: timeout=5.0, max_retries=0 — если LLM тупит, сразу уходим в fallback.
    """
    client = OpenAI(
        base_url=os.environ.get("LLM_BASE_URL", "https://bifrost.be-healthy.tech/v1"),
        api_key=os.environ.get("LLM_API_KEY", "dummy-key"),
        timeout=5.0,
        max_retries=0,
    )

    system_prompt = (
        "Ты — эксперт по анализу образа жизни. Сгенерируй РОВНО 3 гипотезы об образе жизни. "
        "СТРОГО ЗАПРЕЩЕНЫ медицинские термины: диагноз, болезнь, синдром, лечение, доза, препарат, "
        "терапия, инсомния, апноэ, депрессия, бессонница. "
        "Гипотезы — о привычках, режиме, активности, использовании телефона. "
        "Ответ строго в формате JSON-массива РОВНО из 3 элементов: "
        '[{"text": "Текст гипотезы 1", "confidence": 0.8}, '
        '{"text": "Текст гипотезы 2", "confidence": 0.7}, '
        '{"text": "Текст гипотезы 3", "confidence": 0.9}]'
    )

    # Экономим токены: шлём только значения, без обёрток confidence
    clean_profile = {k: v["value"] for k, v in profile.items()}
    user_prompt = f"Профиль пользователя: {json.dumps(clean_profile, ensure_ascii=False)}"

    # ═══════════════════════════════════════════════════════════
    # ИСПРАВЛЕНИЕ: явный список сообщений, НЕ [...]
    # ═══════════════════════════════════════════════════════════
    response = client.chat.completions.create(
        model=os.environ.get("LLM_MODEL", "gpt-6-luna"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=600,
        temperature=0.3,
    )

    # AI-07: логируем расход токенов (одна строка на неделю в логах стенда)
    try:
        usage = response.usage
        logger.info(
            "LLM usage: prompt=%s completion=%s total=%s",
            getattr(usage, "prompt_tokens", "?"),
            getattr(usage, "completion_tokens", "?"),
            getattr(usage, "total_tokens", "?"),
        )
    except Exception:
        pass

    # Если ответ обрезан по max_tokens — не парсим, уходим в fallback
    if response.choices[0].finish_reason == "length":
        raise ValueError("LLM ответ обрезан")

    content = (response.choices[0].message.content or "").strip()

    # Срезаем markdown-обёртки ```json ... ```
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    parsed = json.loads(content)
    if not isinstance(parsed, list) or len(parsed) < 3:
        raise ValueError(f"LLM вернул {len(parsed) if isinstance(parsed, list) else 'не список'} элементов, нужно 3")

    # Возвращаем ровно 3 — остальное отбрасываем
    return [
        {"text": str(item.get("text", "")), "confidence": float(item.get("confidence", 0.5))}
        for item in parsed[:3]
    ]


# ─────────────────────────────────────────────────────────────
# FALLBACK — без сети, мгновенно
# ─────────────────────────────────────────────────────────────
def _get_fallback_hypotheses(profile: dict) -> list[dict]:
    """3 гипотезы по шаблонам на основе реальных полей профиля."""
    hypotheses = []

    # Гипотеза 1: телефон перед сном
    ph = profile.get("phone_before_sleep", {})
    if ph.get("confidence", 0) == 0:
        hypotheses.append({
            "text": "Ведение дневника вечернего использования телефона может помочь заметить закономерности.",
            "confidence": 0.3,
        })
    elif ph.get("value") is True:
        hypotheses.append({
            "text": "Ты часто используешь телефон поздно вечером — можно попробовать сдвинуть экранное время на час раньше.",
            "confidence": 0.75,
        })
    else:
        hypotheses.append({
            "text": "Ты хорошо контролируешь использование экрана в вечернее время.",
            "confidence": 0.6,
        })

    # Гипотеза 2: социальный джетлаг
    sj = profile.get("social_jetlag", {})
    if sj.get("confidence", 0) == 0:
        hypotheses.append({
            "text": "Отслеживание режима сна в выходные поможет увидеть, восстанавливаешься ли ты за неделю.",
            "confidence": 0.3,
        })
    elif sj.get("value") is True:
        hypotheses.append({
            "text": "По выходным ты ложишься значительно позже, чем в будни — это создаёт эффект «социального джетлага».",
            "confidence": 0.8,
        })
    else:
        hypotheses.append({
            "text": "Твой режим сна стабилен как в будни, так и в выходные.",
            "confidence": 0.7,
        })

    # Гипотеза 3: активность
    act = profile.get("activity_level", {})
    if act.get("confidence", 0) == 0:
        hypotheses.append({
            "text": "Твой уровень активности можно отслеживать по шагам, чтобы заметить сезонные колебания.",
            "confidence": 0.3,
        })
    elif act.get("value") == "low":
        hypotheses.append({
            "text": "Твой текущий уровень ежедневной активности можно мягко увеличить — хотя бы до 6-7 тысяч шагов.",
            "confidence": 0.65,
        })
    elif act.get("value") == "high":
        hypotheses.append({
            "text": "Ты поддерживаешь высокий уровень ежедневной физической активности — это отличная привычка.",
            "confidence": 0.8,
        })
    else:
        hypotheses.append({
            "text": "Твой профиль показывает потенциал для оптимизации ежедневных привычек.",
            "confidence": 0.5,
        })

    while len(hypotheses) < 3:
        hypotheses.append(_SAFE_HYPOTHESIS.copy())
    return hypotheses[:3]