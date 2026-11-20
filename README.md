# 1. Запуск.
## 1.1 Клонирование репозитория и переход в папку проекта

```bash
git clone https://github.com/CherepanovKirillV/28.git && cd 28
```

## 1.2 Создание файла .env с переменными окружения

Создай в корне проекта (рядом с Dockerfile) файл `.env` со следующим содержимым:

```env
# ── Обязательные ────────────────────────────────────────
TEAM=team28
LLM_API_KEY=твой_токен_прокси_нейросети
HACK_TEAM_TOKEN=токен_команды_для_Hack_API

# ── Необязательные (есть значения по умолчанию) ────────
LLM_BASE_URL=https://bifrost.be-healthy.tech/v1
LLM_MODEL=gpt-6-luna
HACK_API_URL=https://hack-api.be-healthy.tech
```

⚠️ Файл `.env` содержит секретный токен. Убедись, что он есть в `.gitignore` (не коммить в Git!).

## 1.3. Сборка Docker-образа

```bash
sudo docker build -t team28:latest .
```

Ожидаемо в конце вывода: `Successfully tagged team28:latest`

## 1.4. Запуск контейнера с лимитами стенда (512 МБ, без swap)

```bash
sudo docker run -d \
  --name team28_app \
  -p 8000:8000 \
  --memory=512m --memory-swap=512m \
  --env-file .env \
  team28:latest
```

## 1.5 Проверка на ЛОКАЛЬНОЙ машине (localhost)

```bash
# 5.1. Сервис жив?
curl -i http://localhost:8000/health
# Ожидаемо: HTTP/1.1 200 OK, {"team":"team28","status":"ok"}

# 5.2. Память в норме?
sudo docker stats --no-stream team28_app
# Ожидаемо: MEM USAGE < 450 MiB / 512 MiB

# 5.3. Логи без ошибок?
sudo docker logs team28_app 2>&1 | grep -E "ERROR|Traceback" || echo "✅ Ошибок нет"

# 5.4. Полный прогон /run (если есть HACK_TEAM_TOKEN)
curl -s -X POST http://localhost:8000/run \
  -H "Authorization: Bearer $HACK_TEAM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"case":3,"dataset_code":"case3-dev-v1"}' \
  -o /tmp/run_local.json --max-time 1800
python -c "import json; print('weeks:', len(json.load(open('/tmp/run_local.json'))['weeks']))"
# Ожидаемо: weeks: 30
```

## 1.6 Проверка на СТЕНДЕ хакатона

```bash
# 6.1. Стенд жив?
curl -i https://team28.hack.be-healthy.tech/health
# Ожидаемо: HTTP/2 200, {"team":"team28","status":"ok","version":"2.0-wrapper"}

# 6.2. Полный прогон на стенде
curl -s -X POST https://team28.hack.be-healthy.tech/run \
  -H "Authorization: Bearer $HACK_TEAM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"case":3,"dataset_code":"case3-dev-v1"}' \
  -o /tmp/run_stand.json --max-time 1800

# 6.3. Проверка структуры ответа стенда
python -c "
import json
d = json.load(open('/tmp/run_stand.json'))
w = d['weeks']
print('weeks:', len(w))
print('keys:', list(w[0].keys()))
print('bedtime:', w[0]['profile']['weekday_bedtime'])
"
# Ожидаемо:
#   weeks: 30
#   keys: ['record_id', 'profile', 'hypotheses']
#   bedtime: {'value': '23:00', 'confidence': 0.5}

# 6.4. Валидация против Case3Answers.schema.json
cp /tmp/run_stand.json data/run_response.json
python validate_local.py
# Ожидаемо: ✅ Валидация пройдена: 30 недель соответствуют Case3Answers.schema.json
```

# 2. Роли.
	zulmaala - бэкенд
	ilynarya - работа с данными
	shabbyjo - фронтенд
	sanoratr - дизайн и концепт вещи
# 3. ИИ.
- Qwen, Deepseek, ChatGPT - для работы с кодом.
- Claude, AutoClaw, Gemini для работы с визуальной частью.
# 4. Источники.
	Чужой код не использовали, в качестве источников использовались Qwen и DeepSeek.
# 5. Журнал решений.

**Soft guess вместо `unknown`** — если prior ≥ 40%, отвечаем `conf=0.5`: верный ответ +0.5, неверный −0.25. Выгоднее, чем 0 за `unknown`. Для `bedtime`/`wake`/`sleep_hours` оставили `unknown` — разброс слишком большой.

**Обёртка `{value, confidence}`** — сначала сделали плоский `profile`, но `Case3Answers.schema.json` её не принял. Переделали `_pack_week` — ответ проходит валидацию 30/30.

**`try/except` на каждой неделе, а не на всём `/run`** — иначе одна битая неделя роняла весь прогон. Теперь падает только она, остальные считаются.

**Таймаут LLM 15 сек** — на 5 секундах 4 недели из 30 уходили в `APITimeoutError`. 15 секунд + один retry — качество гипотез выросло, в лимит 45 минут укладываемся.

**Один вызов LLM вместо трёх** — дешевле по токенам, быстрее, гипотезы не повторяются. Просим сразу JSON-массив из трёх.

**`--workers 1` в Docker** — 4 воркера × ~150 МБ pandas = OOM при лимите 512 МБ. Плюс `MALLOC_ARENA_MAX=2` — без него память раздувается до 500+ МБ.

# 6. Концепт вещи: Умная серьга-кафф + умная подушка.
