"""
Печатает profile_fields_schema из dev.json, чтобы понять,
что именно проверяет валидатор.
"""
import json
from pathlib import Path

DATA = Path("data/dev.json")

with DATA.open(encoding="utf-8") as f:
    data = json.load(f)

schema = data["dataset"]["profile_fields_schema"]

print("=== ВЕРХНИЙ УРОВЕНЬ СХЕМЫ ===")
print(f"type: {schema.get('type')}")
print(f"required: {schema.get('required')}")
print(f"additionalProperties: {schema.get('additionalProperties')}")
print(f"properties (ключи): {list(schema.get('properties', {}).keys())}")

# Посмотрим на каждое поле внутри properties
print("\n=== ПОЛЯ ВНУТРИ properties ===")
for name, spec in schema.get("properties", {}).items():
    if "anyOf" in spec:
        opts = [o.get("const") for o in spec["anyOf"]]
        print(f"  {name}: enum {opts}")
    elif spec.get("type") == "number":
        print(f"  {name}: number [{spec.get('minimum')}..{spec.get('maximum')}]")
    elif spec.get("type") == "boolean":
        print(f"  {name}: boolean")
    elif "pattern" in spec:
        print(f"  {name}: string pattern {spec['pattern']}")
    elif spec.get("type") == "object":
        print(f"  {name}: object -> keys: {list(spec.get('properties', {}).keys())}")
    elif spec.get("type") == "array":
        print(f"  {name}: array of {spec.get('items', {}).get('type', '?')}")
    else:
        print(f"  {name}: {spec.get('type', '?')}")