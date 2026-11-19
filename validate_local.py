"""
Локальная проверка ответа /run на соответствие profile_fields_schema.
Схема описывает ОДИН профиль (11 полей), а не весь ответ {weeks: [...]}.
Поэтому валидируем каждую неделю отдельно.
"""
import json
import sys
from pathlib import Path

from jsonschema import validate, ValidationError

RESPONSE_PATH = Path("data") / "run_response.json"
DEV_PATH = Path("data") / "dev.json"


def load_schema() -> dict:
    """Достает profile_fields_schema из dev.json."""
    with DEV_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return data["dataset"]["profile_fields_schema"]


def validate_response(response: dict) -> bool:
    """
    Проверяет:
    1. В ответе есть массив 'weeks'.
    2. Каждая неделя имеет 'profile'.
    3. Каждый 'profile' соответствует profile_fields_schema.
    """
    # ── 1. Базовая структура ответа ─────────────────────
    if "weeks" not in response:
        print("❌ В ответе нет ключа 'weeks'")
        return False
    weeks = response["weeks"]
    if not isinstance(weeks, list):
        print("❌ 'weeks' должен быть массивом")
        return False
    if len(weeks) == 0:
        print("❌ 'weeks' пустой")
        return False

    schema = load_schema()

    # ── 2. Каждая неделя — отдельная проверка ───────────
    errors = 0
    for i, week in enumerate(weeks):
        rid = week.get("record_id", f"week_{i}")
        if "profile" not in week:
            print(f"❌ {rid}: нет ключа 'profile'")
            errors += 1
            continue
        try:
            validate(instance=week["profile"], schema=schema)
        except ValidationError as e:
            print(f"❌ {rid}: {e.message}")
            path = ".".join(str(p) for p in e.path) if e.path else "(корень профиля)"
            print(f"   Путь: {path}")
            errors += 1
            # Подсказка для самого частого случая
            if "is not valid under any of the given schemas" in str(e.message):
                print(f"   💡 Возможно, поле обёрнуто в {{value, confidence}},")
                print(f"      а схема ждёт плоское значение. См. ФИКС №2.")

    # ── 3. Итог ─────────────────────────────────────────
    if errors == 0:
        print(f"✅ Валидация пройдена: все {len(weeks)} профилей соответствуют схеме")
        return True
    print(f"\n❌ Провалено {errors} из {len(weeks)} недель")
    return False


def main():
    if not RESPONSE_PATH.exists():
        print(f"Файл {RESPONSE_PATH} не найден. Сначала сгенерируй ответ.")
        sys.exit(1)
    with RESPONSE_PATH.open(encoding="utf-8") as f:
        response = json.load(f)
    ok = validate_response(response)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()