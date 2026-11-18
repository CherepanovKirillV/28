import os
import json
import re
from openai import OpenAI
from typing import List, Dict, Any

# 1. Список запрещённых медицинских терминов (приводим к нижнему регистру для проверки)
MEDICAL_STOP_WORDS = [
    "диагноз", "болезнь", "синдром", "лечение", "доза", "препарат", 
    "терапия", "инсомния", "апноэ", "депрессия", "бессонница", "расстройство"
]

def generate_hypotheses(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Генерирует ровно 3 гипотезы об образе жизни на основе профиля.
    Использует LLM с пост-фильтром и надёжным fallback.
    """
    # Попытка получить гипотезы от LLM
    try:
        hypotheses = _get_llm_hypotheses(profile)
    except Exception as e:
        print(f"[WARNING] LLM вызов не удался: {e}. Используем fallback.")
        hypotheses = _get_fallback_hypotheses(profile)
    
    # 2. Пост-фильтрация: проверяем каждую гипотезу на запрещённые слова
    filtered_hypotheses = []
    for hyp in hypotheses:
        text = hyp.get("text", "").lower()
        # Если найдено хотя бы одно стоп-слово как отдельное слово или часть слова
        if any(word in text for word in MEDICAL_STOP_WORDS):
            print(f"[WARNING] Гипотеза содержит мед. термин и заменена на fallback: {hyp.get('text')}")
            # Заменяем на безопасную шаблонную гипотезу
            filtered_hypotheses.append({
                "text": "Твой режим дня имеет особенности, которые можно мягко скорректировать для улучшения самочувствия.",
                "confidence": 0.5
            })
        else:
            filtered_hypotheses.append(hyp)
            
    # 3. Гарантируем, что вернётся ровно 3 гипотезы (обрезаем или дополняем)
    while len(filtered_hypotheses) < 3:
        filtered_hypotheses.append({
            "text": "Твой профиль показывает потенциал для оптимизации ежедневных привычек.",
            "confidence": 0.4
        })
        
    return filtered_hypotheses[:3]


def _get_llm_hypotheses(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Внутренняя функция для вызова LLM с правильными параметрами."""
    client = OpenAI(
        base_url=os.environ.get("LLM_BASE_URL", "https://bifrost.be-healthy.tech/v1"),
        api_key=os.environ.get("LLM_API_KEY", "dummy-key"),
        max_retries=0 # Мы сами контролируем логику, лишние авто-повторы съедят лимит
    )
    
    system_prompt = (
        "Ты — эксперт по анализу образа жизни. Сгенерируй ровно 3 гипотезы об образе жизни на основе профиля пользователя. "
        "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать медицинские термины: диагноз, болезнь, синдром, лечение, доза, препарат, "
        "терапия, инсомния, апноэ, депрессия, бессонница. "
        "Гипотезы должны быть о привычках, режиме, активности. "
        "Ответ должен быть СТРОГО в формате JSON-массива объектов: "
        '[{"text": "Текст гипотезы", "confidence": 0.8}, ...]'
    )
    
    user_prompt = f"Профиль пользователя: {json.dumps(profile, ensure_ascii=False)}"
    
    response = client.chat.completions.create(
        model=os.environ.get("LLM_MODEL", "gpt-6-luna"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        max_tokens=1200, # Запас на скрытые рассуждения модели (400-500 токенов) + ответ
        temperature=0.3, # Низкая температура для более стабильных и предсказуемых ответов
    )
    
    # Проверка на обрезку ответа (если модель не успела закончить JSON)
    if response.choices[0].finish_reason == "length":
        raise ValueError("LLM ответ обрезан (finish_reason='length')")
        
    content = response.choices[0].message.content
    
    # Попытка распарсить JSON из ответа (иногда модель оборачивает его в ```json ... ```)
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.endswith("```"):
        content = content[:-3]
        
    parsed = json.loads(content)
    
    # Валидация структуры ответа
    if not isinstance(parsed, list) or len(parsed) < 3:
        raise ValueError("LLM вернул некорректный формат JSON (не массив из 3 элементов)")
        
    return [
        {"text": str(item.get("text", "")), "confidence": float(item.get("confidence", 0.5))}
        for item in parsed[:3]
    ]


def _get_fallback_hypotheses(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Генерирует 3 безопасные гипотезы на основе правил, если LLM недоступен.
    Это наша страховка от ошибок 429/500.
    """
    hypotheses = []
    
    # Гипотеза 1: на основе телефона перед сном
    phone_val = profile.get("phone_before_bed", {}).get("value")
    if phone_val is True:
        hypotheses.append({"text": "Ты часто используешь телефон более часа после отбоя, что может влиять на качество засыпания.", "confidence": 0.75})
    else:
        hypotheses.append({"text": "Ты хорошо контролируешь использование экрана в вечернее время.", "confidence": 0.6})

    # Гипотеза 2: на основе социального джетлага
    jetlag_val = profile.get("social_jetlag", {}).get("value")
    if jetlag_val is True:
        hypotheses.append({"text": "По выходным ты спишь значительно дольше или ложишься позже, чем в будни.", "confidence": 0.8})
    else:
        hypotheses.append({"text": "Твой режим сна относительно стабилен как в будни, так и в выходные.", "confidence": 0.7})

    # Гипотеза 3: на основе уровня активности
    activity_val = profile.get("activity_level", {}).get("value")
    if activity_val == "low":
        hypotheses.append({"text": "Твой текущий уровень ежедневной активности можно мягко увеличить.", "confidence": 0.65})
    elif activity_val == "high":
        hypotheses.append({"text": "Ты поддерживаешь высокий уровень ежедневной физической активности.", "confidence": 0.8})
    else:
        hypotheses.append({"text": "Твой профиль показывает потенциал для оптимизации ежедневных привычек.", "confidence": 0.5})

    return hypotheses