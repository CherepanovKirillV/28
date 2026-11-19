"""
Оценивает расход токенов на 1 неделю и на весь dev-набор (30 недель).
Использует tiktoken для приблизительного подсчёта.
НЕ входит в docker-образ (в .dockerignore).
"""
import json
from pathlib import Path

try:
    import tiktoken
    ENC = tiktoken.get_encoding("cl100k_base")
    def count_tokens(text: str) -> int:
        return len(ENC.encode(text))
except ImportError:
    print("⚠️  tiktoken не установлен — считаю по эвристике ~4 символа/токен")
    def count_tokens(text: str) -> int:
        return len(text) // 4

DATA_PATH = Path("data") / "dev.json"

SYSTEM_PROMPT = (
    "Ты — эксперт по анализу образа жизни. Сгенерируй РОВНО 3 гипотезы об образе жизни. "
    "СТРОГО ЗАПРЕЩЕНЫ медицинские термины: диагноз, болезнь, синдром, лечение, доза, препарат, "
    "терапия, инсомния, апноэ, депрессия, бессонница. "
    "Гипотезы — о привычках, режиме, активности, использовании телефона. "
    "Ответ строго в формате JSON-массива: "
    '[{"text": "Текст гипотезы", "confidence": 0.8}, ...]'
)

def main():
    with DATA_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    sys_tokens = count_tokens(SYSTEM_PROMPT)

    total_prompt = 0
    total_completion_estimate = 0
    n_weeks = len(data["dataset"]["weeks"])

    # Берём профили из reference (у них уже "плоские" значения — как мы шлём в LLM)
    for ref_week in data["reference"]["weeks"]:
        profile = ref_week.get("profile", {})
        user_prompt = f"Профиль пользователя: {json.dumps(profile, ensure_ascii=False)}"
        total_prompt += sys_tokens + count_tokens(user_prompt) + 10  # +10 служебные

    # Оценка ответа: 3 гипотезы × ~80 токенов + JSON-обёртка ≈ 280
    total_completion_estimate = n_weeks * 280

    print(f"{'─' * 50}")
    print(f"  Недель в dev-наборе: {n_weeks}")
    print(f"{'─' * 50}")
    print(f"  Средний prompt на неделю:  ~{total_prompt // n_weeks} токенов")
    print(f"  Оценка ответа на неделю:   ~280 токенов")
    print(f"{'─' * 50}")
    print(f"  ПРОМПТ всего (30 недель):  ~{total_prompt} токенов")
    print(f"  ОТВЕТ всего (30 недель):   ~{total_completion_estimate} токенов")
    print(f"  ИТОГО:                     ~{total_prompt + total_completion_estimate} токенов")
    print(f"{'─' * 50}")
    print(f"  ⚠️  Точный расход смотри в логах стенда по строке 'LLM usage'.")

if __name__ == "__main__":
    main()