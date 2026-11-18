import os
import llm_generator

test_profile = {
    "phone_before_bed": {"value": True, "confidence": 0.8},
    "social_jetlag": {"value": True, "confidence": 0.7},
    "activity_level": {"value": "low", "confidence": 0.8},
    "sleep_duration": {"value": 6.5, "confidence": 0.7}
}
hyps = llm_generator.generate_hypotheses(test_profile)
print(f"Получено гипотез: {len(hyps)}")
for h in hyps:
    print(f"- {h['text']} (уверенность: {h['confidence']})")