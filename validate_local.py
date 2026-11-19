"""
Валидация ответа /run против Case3Answers.schema.json.
Схема описывает ВЕСЬ ответ {weeks: [...]}, поэтому валидируем response целиком.
"""
import json
import sys
from pathlib import Path

from jsonschema import validate, ValidationError

RESPONSE_PATH = Path("data") / "run_response.json"
SCHEMA_PATH = Path("data") / "Answers.schema.json"   # положи файл схемы сюда


def load_schema() -> dict:
    """Читает Case3Answers.schema.json как готовую JSON Schema."""
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def validate_response(response: dict) -> bool:
    if "weeks" not in response:
        print("❌ В ответе нет ключа 'weeks'")
        return False
    if not isinstance(response["weeks"], list) or not response["weeks"]:
        print("❌ 'weeks' пустой или не массив")
        return False

    schema = load_schema()
    try:
        validate(instance=response, schema=schema)
        print(f"✅ Валидация пройдена: {len(response['weeks'])} недель соответствуют Case3Answers.schema.json")
        return True
    except ValidationError as e:
        path = ".".join(str(p) for p in e.path) if e.path else "(корень)"
        print(f"❌ {e.message}")
        print(f"   Путь: {path}")
        msg = str(e.message).lower()
        if "additional properties" in msg:
            print("   💡 Лишний ключ. В неделе допустимы только record_id, profile, hypotheses.")
        elif "is not of type 'object'" in msg or "is not valid under any" in msg:
            print("   💡 Скорее всего, profile разделан. Схема ждёт {value, confidence}.")
        elif "is not of type 'string'" in msg:
            print("   💡 Вероятно, conf=0 должен давать 'unknown', а не число/bool.")
        return False


def main():
    if not RESPONSE_PATH.exists():
        print(f"❌ {RESPONSE_PATH} не найден. Сначала: python generate_local_response.py")
        sys.exit(1)
    if not SCHEMA_PATH.exists():
        print(f"❌ {SCHEMA_PATH} не найден. Положи Case3Answers.schema.json в data/")
        sys.exit(1)

    with RESPONSE_PATH.open(encoding="utf-8") as f:
        response = json.load(f)

    ok = validate_response(response)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()