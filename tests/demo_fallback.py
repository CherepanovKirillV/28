# tests/demo_fallback.py
"""
Демонстрация надёжности llm_generator:
1. Обычный вызов (LLM работает).
2. Симуляция падения LLM → fallback срабатывает.
3. Симуляция «LLM вернула медицинский термин» → пост-фильтр вырезает.
4. Симуляция «LLM вернула 2 гипотезы вместо 3» → добиваем до 3.
"""
# ── ФИКС импорта: добавляем корень проекта в sys.path ──
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# ───────────────────────────────────────────────────────

from unittest.mock import patch

import llm_generator

# Пример профиля (как из calculator)
PROFILE = {
    "chronotype":         {"value": "intermediate", "confidence": 0.7},
    "weekday_wake_time":  {"value": "07:40", "confidence": 0.85},
    "average_sleep_hours":{"value": 8.15,    "confidence": 0.85},
    "social_jetlag":      {"value": False,   "confidence": 0.7},
    "activity_level":     {"value": "medium","confidence": 0.85},
    "sedentary_hours":    {"value": "gt9",   "confidence": 0.7},
    "training_days":      {"value": "1to2",  "confidence": 0.7},
    "works_from_home":    {"value": True,    "confidence": 0.55},
    "phone_before_sleep": {"value": False,   "confidence": 0.7},
    "movement_index":     {"value": "50to70","confidence": 0.55},
    "weekday_bedtime":    {"value": "23:00", "confidence": 0.0},
}


def case_1_normal():
    print("▶ Сценарий 1: LLM работает")
    h = llm_generator.generate_hypotheses(PROFILE)
    assert len(h) == 3
    for i, x in enumerate(h, 1):
        print(f"   {i}. [{x['confidence']:.2f}] {x['text'][:70]}...")
    print("   ✅ 3 гипотезы сгенерированы\n")


def case_2_llm_down():
    print("▶ Сценарий 2: LLM упала (TimeoutError)")
    with patch("llm_generator._get_llm_hypotheses", side_effect=TimeoutError("simulated")):
        h = llm_generator.generate_hypotheses(PROFILE)
    assert len(h) == 3, f"ожидалось 3, получили {len(h)}"
    print(f"   ✅ Fallback сработал: 3 гипотезы, первая: {h[0]['text'][:60]}...\n")


def case_3_medical_term():
    print("▶ Сценарий 3: LLM вернула 'диагноз'")
    bad = [
        {"text": "У вас вероятен диагноз бессонница", "confidence": 0.8},
        {"text": "Нужно лечение", "confidence": 0.7},
        {"text": "Нормальный текст", "confidence": 0.6},
    ]
    with patch("llm_generator._get_llm_hypotheses", return_value=bad):
        h = llm_generator.generate_hypotheses(PROFILE)
    for x in h:
        assert "диагноз" not in x["text"].lower(), "мед. термин просочился!"
        assert "лечение" not in x["text"].lower(), "мед. термин просочился!"
    print("   ✅ Пост-фильтр вырезал медицинские термины\n")


def case_4_short_response():
    print("▶ Сценарий 4: LLM вернула 2 гипотезы вместо 3")
    short = [
        {"text": "Первая", "confidence": 0.7},
        {"text": "Вторая", "confidence": 0.7},
    ]
    with patch("llm_generator._get_llm_hypotheses", return_value=short):
        h = llm_generator.generate_hypotheses(PROFILE)
    assert len(h) == 3, f"ожидалось 3, получили {len(h)}"
    print(f"   ✅ Добито до 3: {[x['text'][:20] for x in h]}\n")


def case_5_validate_output():
    print("▶ Сценарий 5: validate_output отбраковывает мусор")
    bad_profile = {"chronotype": "early"}  # обёртка отсутствует — должно провалиться
    good_hyp = [{"text": "ok", "confidence": 0.5}] * 3
    assert llm_generator.validate_output(bad_profile, good_hyp) is False, \
        "validate_output не поймал плохой profile"
    print("   ✅ validate_output(плохой profile) → False")

    good_profile = PROFILE
    bad_hyp = [{"text": "диагноз: простуда", "confidence": 0.5}] * 3
    assert llm_generator.validate_output(good_profile, bad_hyp) is False, \
        "validate_output не поймал мед. термин"
    print("   ✅ validate_output(мед. термин) → False")

    assert llm_generator.validate_output(good_profile, good_hyp) is True
    print("   ✅ validate_output(хорошие данные) → True\n")


CASES = [case_1_normal, case_2_llm_down, case_3_medical_term,
         case_4_short_response, case_5_validate_output]


def main():
    print("═══ Демонстрация надёжности LLM-генератора ═══\n")
    failed = 0
    for fn in CASES:
        try:
            fn()
        except Exception as e:
            print(f"   ❌ {type(e).__name__}: {e}\n")
            failed += 1
    if failed:
        print(f"❌ Провалено {failed} сценариев")
        raise SystemExit(1)
    print("✅ Все сценарии прошли — система устойчива к сбоям LLM")


if __name__ == "__main__":
    main()