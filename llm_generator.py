"""
Генерация 3 гипотез об образе жизни пользователя.
Стратегия:
1. Пытаемся спросить LLM (с жёстким таймаутом 5 сек).
2. Если LLM упала / тормозит / вернула мусор — без шума переключаемся
   на _get_fallback_hypotheses(), которая строит гипотезы по шаблонам
   из calculator.py.
3. Любые медицинские термины (диагноз, лечение и т.п.) вырезаются пост-фильтром.
"""
import json
import logging
import os
import re

# ПОЧЕМУ МЫ ТАК ИМПОРТИРУЕМ:
# - OpenAI — клиент
# - APIError — базовое исключение openai (сеть, 4xx/5xx)
# - APITimeoutError — ИМЕННО ТАЙМАУТ (а не Timeout!)
#   openai.Timeout — это httpx.Timeout, конфиг, а не исключение.
#   Если положить его в except () — Python упадёт с TypeError.
from openai import OpenAI, APIError, APITimeoutError

logger = logging.getLogger(__name__)

# Стоп-слова: если LLM их напишет, гипотеза подменяется безопасной.
# ПОЧЕМУ МЫ ЭТО ДЕЛАЕМ: юристы/медики не любят, когда бот "ставит диагноз".
MEDICAL_STOP_WORDS = [
    "диагноз", "болезнь", "синдром", "лечение", "доза", "препарат",
    "терапия", "инсомния", "апноэ", "депрессия", "бессонница", "расстройство",
]

# Безопасная заготовка — используется как последний резерв.
_SAFE_HYPOTHESIS = {
    "text": "Твой режим дня имеет особенности, которые можно мягко скорректировать для улучшения самочувствия.",
    "confidence": 0.5,
}


# ─────────────────────────────────────────────────────────────
# ГЛАВНАЯ ФУНКЦИЯ: generate_hypotheses
# ─────────────────────────────────────────────────────────────
def generate_hypotheses(profile: dict) -> list[dict]:
    """
    Генерирует ровно 3 гипотезы.
    Пытается через LLM → при любой ошибке падает на fallback.
    Пост-фильтр вычищает медицинские термины и обрезает текст до 500 символов.
    """
    try:
        hypotheses = _get_llm_hypotheses(profile)
    except (APIError, APITimeoutError, Exception) as e:
        # ПОЧЕМУ МЫ ЛОВИМ СТОЛЬКО: любые проблемы LLM — не повод для 500.
        # APITimeoutError — таймаут; APIError — сеть/HTTP; Exception — всё остальное.
        logger.warning("LLM вызов не удался (%s). Используем fallback.", type(e).__name__)
        hypotheses = _get_fallback_hypotheses(profile)

    # Пост-фильтр: если вдруг LLM всё же протащила запрещённое слово —
    # заменяем гипотезу на безопасную.
    filtered = []
    for h in hypotheses:
        text = (h.get("text") or "").lower()
        if any(w in text for w in MEDICAL_STOP_WORDS):
            logger.warning("Гипотеза содержит мед. термин — заменена")
            # .copy() важно: иначе все три замены ссылались бы на ОДИН объект
            filtered.append(_SAFE_HYPOTHESIS.copy())
        else:
            filtered.append(h)

    # Гарантируем ровно 3 гипотезы (если LLM вернула 2 — добиваем третьей)
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
    """
    Проверяет, что ответ можно отдавать наружу.

    Что проверяем:
    1. hypotheses — список ровно из 3 элементов.
    2. В каждой гипотезе есть text (str) и confidence (float 0.0…1.0).
    3. В тексте нет медицинских стоп-слов.
    4. В profile каждое поле имеет value + confidence (float 0.0…1.0).

    Возвращает True — можно отдавать как есть.
    Возвращает False — main.py подменит на fallback.
    """
    # 1. Ровно 3 гипотезы
    if not isinstance(hypotheses, list) or len(hypotheses) != 3:
        return False

    # 2-3. Каждая гипотеза — правильный словарь без стоп-слов
    for h in hypotheses:
        if not isinstance(h, dict) or "text" not in h or "confidence" not in h:
            return False

        text = str(h["text"]).lower()
        if any(w in text for w in MEDICAL_STOP_WORDS):
            return False

        conf = h["confidence"]
        # isinstance(True, int) == True — поэтому проверяем bool отдельно!
        if isinstance(conf, bool):
            return False
        if not isinstance(conf, (int, float)) or not (0.0 <= conf <= 1.0):
            return False

    # 4. Профиль — все 11 полей корректны
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
# ВЫЗОВ LLM (с жёстким таймаутом 5 сек)
# ─────────────────────────────────────────────────────────────
def _get_llm_hypotheses(profile: dict) -> list[dict]:
    """
    Делает запрос к LLM. Бросает любое исключение наверх — его ловит generate_hypotheses.
    ВАЖНО: timeout=5.0 — если LLM тупит, запрос прерывается и мы уходим в fallback.
    """
    client = OpenAI(
        base_url=os.environ.get("LLM_BASE_URL", "https://bifrost.be-healthy.tech/v1"),
        api_key=os.environ.get("LLM_API_KEY", "dummy-key"),
        timeout=5.0,     # ПОЧЕМУ 5: стенд не ждёт долго, надо успевать в SLA
        max_retries=0,   # ПОЧЕМУ 0: ретраи увеличивают задержку, нам это не нужно
    )

    system_prompt = (
        "Ты — эксперт по анализу образа жизни. Сгенерируй РОВНО 3 гипотезы об образе жизни. "
        "СТРОГО ЗАПРЕЩЕНЫ медицинские термины: диагноз, болезнь, синдром, лечение, доза, препарат, "
        "терапия, инсомния, апноэ, депрессия, бессонница. "
        "Гипотезы — о привычках, режиме, активности, использовании телефона. "
        "Ответ строго в формате JSON-массива: "
        '[{"text": "Текст гипотезы", "confidence": 0.8}, ...]'
    )

    # Экономим токены: шлём только значения, без служебных полей confidence.
    clean_profile = {k: v["value"] for k, v in profile.items()}
    user_prompt = f"Профиль пользователя: {json.dumps(clean_profile, ensure_ascii=False)}"

    response = client.chat.completions.create(
        model=os.environ.get("LLM_MODEL", "gpt-6-luna"),
        messages=[...],
        max_tokens=600,
        temperature=0.3,
    )

    # AI-07: логируем расход токенов. response.usage содержит
    # prompt_tokens, completion_tokens, total_tokens.
    # В логах стенда увидим реальный расход на 30 недель.
    try:
        usage = response.usage
        logger.info(
            "LLM usage: prompt=%s completion=%s total=%s",
            getattr(usage, "prompt_tokens", "?"),
            getattr(usage, "completion_tokens", "?"),
            getattr(usage, "total_tokens", "?"),
        )
    except Exception:
        pass  # usage может отсутствовать в некоторых прокси-обёртках

    if response.choices[0].finish_reason == "length":
        raise ValueError("LLM ответ обрезан")

    content = (response.choices[0].message.content or "").strip()

    # LLM любит оборачивать JSON в ```json ... ``` — срезаем это.
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    parsed = json.loads(content)
    if not isinstance(parsed, list) or len(parsed) < 3:
        raise ValueError("LLM вернул не массив из 3+ элементов")

    return [
        {"text": str(item.get("text", "")), "confidence": float(item.get("confidence", 0.5))}
        for item in parsed[:3]
    ]


# ─────────────────────────────────────────────────────────────
# FALLBACK (когда LLM недоступна)
# ─────────────────────────────────────────────────────────────
def _get_fallback_hypotheses(profile: dict) -> list[dict]:
    """
    Генерирует 3 гипотезы по шаблонам, глядя на реальные поля профиля.
    Работает мгновенно и не требует сети.
    """
    hypotheses = []

    # --- Гипотеза 1: про телефон перед сном ---
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

    # --- Гипотеза 2: про социальный джетлаг ---
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

    # --- Гипотеза 3: про активность ---
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

    # Добиваем до 3, если вдруг чего-то не хватило.
    while len(hypotheses) < 3:
        hypotheses.append(_SAFE_HYPOTHESIS.copy())
    return hypotheses[:3]