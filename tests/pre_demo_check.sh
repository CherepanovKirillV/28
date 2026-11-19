#!/bin/bash
# tests/pre_demo_check.sh
# Запуск: bash tests/pre_demo_check.sh
# Время: 2–15 минут (зависит от /run)
# Требует: HACK_TEAM_TOKEN в env (source set_env.sh)

set -e

STEND="https://team28.hack.be-healthy.tech"
TOKEN="${HACK_TEAM_TOKEN}"

if [ -z "$TOKEN" ]; then
    echo "❌ HACK_TEAM_TOKEN не задан. Выполни: source set_env.sh"
    exit 1
fi

echo "════════════════════════════════════════════════════════"
echo "  PRE-DEMO CHECK"
echo "  Стенд: $STEND"
echo "════════════════════════════════════════════════════════"
echo ""

# ── 1. Health: сервис жив? ───────────────────────────────
echo "[1/7] Health..."
HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$STEND/health")
if [ "$HTTP" = "200" ]; then
    echo "  ✅ 200 OK"
else
    echo "  ❌ HTTP $HTTP"
    exit 1
fi

# ── 2. /run: обрабатывает запрос? ────────────────────────
echo "[2/7] POST /run (может занять до 15 минут)..."
HTTP=$(curl -s -o /tmp/case3_dev.json -w "%{http_code}" --max-time 1800 \
    -X POST "$STEND/run" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"case": 3, "dataset_code": "case3-dev-v1"}')
if [ "$HTTP" = "200" ]; then
    echo "  ✅ 200 OK"
else
    echo "  ❌ HTTP $HTTP"
    head -c 500 /tmp/case3_dev.json
    exit 1
fi

# ── 3. 30 недель в ответе? ───────────────────────────────
echo "[3/7] Количество недель..."
WEEKS=$(python -c "import json; print(len(json.load(open('/tmp/case3_dev.json'))['weeks']))" 2>/dev/null || echo "0")
if [ "$WEEKS" = "30" ]; then
    echo "  ✅ weeks=30"
else
    echo "  ❌ weeks=$WEEKS"
    exit 1
fi

# ── 4. profile плоский? ──────────────────────────────────
echo "[4/7] Формат profile (плоский vs обёртка)..."
FLAT=$(python -c "
import json
d = json.load(open('/tmp/case3_dev.json'))
p = d['weeks'][0]['profile']
v = p['chronotype']
print('flat' if isinstance(v, str) else 'wrapped')
" 2>/dev/null || echo "error")
if [ "$FLAT" = "flat" ]; then
    echo "  ✅ profile плоский (chronotype=$v → str)"
else
    echo "  ❌ profile обёрнут в {value, confidence} — не пройдёт схему"
    exit 1
fi

# ── 5. Валидация схемы ──────────────────────────────────
echo "[5/7] Валидация против profile_fields_schema..."
mkdir -p data
cp /tmp/case3_dev.json data/run_response.json
if python validate_local.py 2>&1 | grep -q "✅"; then
    echo "  ✅ 30/30 профилей прошли схему"
else
    echo "  ❌ Схема не прошла:"
    python validate_local.py 2>&1 | head -5
    exit 1
fi

# ── 6. Локальный скор ───────────────────────────────────
echo "[6/7] Локальный скор..."
SCORE=$(python local_test.py 2>/dev/null | grep "ИТОГО" | awk '{print $NF}')
if [ -n "$SCORE" ]; then
    echo "  ✅ $SCORE очков"
else
    echo "  ⚠️  не удалось посчитать (возможно, data/dev.json не скачан)"
fi

# ── 7. Health повторно (сервис не упал от /run) ─────────
echo "[7/7] Health после /run (проверка, что не упал)..."
HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$STEND/health")
if [ "$HTTP" = "200" ]; then
    echo "  ✅ 200 OK — сервис держит нагрузку"
else
    echo "  ❌ сервис упал после /run (HTTP $HTTP) — OOM или баг"
    exit 1
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo "  ✅ ВСЁ ГОТОВО К ПОКАЗУ"
echo "════════════════════════════════════════════════════════"