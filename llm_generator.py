# llm_generator.py
import json
import logging
import os
import re

from openai import OpenAI

logger = logging.getLogger(__name__)

MEDICAL_STOP_WORDS = [
    "диагноз", "болезнь", "синдром", "лечение", "доза", "препарат",
    "терапия", "инсомния", "апноэ", "депрессия", "бессонница", "расстройство",
]

# Шаблон безопасной замены
_SAFE_HYPOTHESIS = {
    "text": "Твой режим дня имеет особенности, которые можно мягко скорректировать для улучшения самочувствия.",
    "confidence": 0.5,
}


def generate_hypotheses(profile: dict) -> list[dict]:
    """Генерирует ровно 3 гипотезы. LLM + пост-фильтр + fallback."""
    try:
        hypotheses = _get_llm_hypotheses(profile)
    except Exception as e:
        logger.warning("LLM вызов не удался: %s. Fallback.", type(e).__name__)
        hypotheses = _get_fallback_hypotheses(profile)

    # Пост-фильтр медицинских терминов
    filtered = []
    for h in hypotheses:
        text = (h.get("text") or "").lower()
        if any(w in text for w in MEDICAL_STOP_WORDS):
            logger.warning("Гипотеза содержит мед. термин — заменена")
            filtered.append(_SAFE_HYPOTHESIS.copy())
        else:
            filtered.append(h)

    # Гарантия 3 гипотез
    while len(filtered) < 3:
        filtered.append(_SAFE_HYPOTHESIS.copy())

    # Нормализация: только text/confidence, в диапазоне [0,1]
    result = []
    for h in filtered[:3]:
        result.append({
            "text": str(h.get("text", "")),
            "confidence": max(0.0, min(1.0, float(h.get("confidence", 0.5)))),
        })
    return result


def _get_llm_hypotheses(profile: dict) -> list[dict]:
    client = OpenAI(
        base_url=os.environ.get("LLM_BASE_URL", "https://bifrost.be-healthy.tech/v1"),
        api_key=os.environ.get("LLM_API_KEY", "dummy-key"),
        max_retries=0,
    )

    system_prompt = (
        "Ты — эксперт по анализу образа жизни. Сгенерируй РОВНО 3 гипотезы об образе жизни. "
        "СТРОГО ЗАПРЕЩЕНЫ медицинские термины: диагноз, болезнь, синдром, лечение, доза, препарат, "
        "терапия, инсомния, апноэ, депрессия, бессонница. "
        "Гипотезы — о привычках, режиме, активности, использовании телефона. "
        "Ответ строго в формате JSON-массива: "
        '[{"text": "Текст гипотезы", "confidence": 0.8}, ...]'
    )
    user_prompt = f"Профиль пользователя: {json.dumps(profile, ensure_ascii=False)}"

    response = client.chat.completions.create(
        model=os.environ.get("LLM_MODEL", "gpt-6-luna"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=1200,
        temperature=0.3,
    )

    if response.choices[0].finish_reason == "length":
        raise ValueError("LLM ответ обрезан (finish_reason='length')")

    content = (response.choices[0].message.content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

    parsed = json.loads(content)
    if not isinstance(parsed, list) or len(parsed) < 3:
        raise ValueError("LLM вернул не массив из 3+ элементов")

    return [
        {"text": str(item.get("text", "")), "confidence": float(item.get("confidence", 0.5))}
        for item in parsed[:3]
    ]


def _get_fallback_hypotheses(profile: dict) -> list[dict]:
    """3 безопасные гипотезы по правилам, если LLM недоступен. Учитывает confidence=0."""
    hypotheses: list[dict] = []

    # 1. phone_before_sleep (новое имя!)
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

    # 2. social_jetlag
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

    # 3. activity_level
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

    # Гарантия 3
    while len(hypotheses) < 3:
        hypotheses.append(_SAFE_HYPOTHESIS.copy())
    return hypotheses[:3]
