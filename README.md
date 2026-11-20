1. Запуск.
sudo docker build -t team28:latest . && sudo docker run -d --name team28_app \
  -p 8000:8000 --memory=512m --memory-swap=512m \
  -e LLM_API_KEY="$LLM_API_KEY" team28:latest
curl -i http://localhost:8000/health   # 200 OK


Переменные: TEAM=team28, LLM_API_KEY (обязательна), LLM_BASE_URL,
LLM_MODEL=gpt-6-luna, HACK_API_URL.

2. Роли.
	zulmaala - бэкенд
	ilynarya - работа с данными
	shabbyjo - фронтенд
	sanoratr - дизайн и концепт вещи
3. ИИ.
- Qwen, Deepseek, ChatGPT - для работы с кодом.
- Claude, AutoClaw, Gemini для работы с визуальной частью.
4. Источники.
	Чужой код не использовали, в качестве источников использовались Qwen и DeepSeek.
5. Журнал решений.

. **Soft guess вместо `unknown`** — если prior ≥ 40%, отвечаем `conf=0.5`: верный ответ +0.5, неверный −0.25. Выгоднее, чем 0 за `unknown`. Для `bedtime`/`wake`/`sleep_hours` оставили `unknown` — разброс слишком большой.

. **Обёртка `{value, confidence}`** — сначала сделали плоский `profile`, но `Case3Answers.schema.json` её не принял. Переделали `_pack_week` — ответ проходит валидацию 30/30.

. **`try/except` на каждой неделе, а не на всём `/run`** — иначе одна битая неделя роняла весь прогон. Теперь падает только она, остальные считаются.

. **Таймаут LLM 15 сек** — на 5 секундах 4 недели из 30 уходили в `APITimeoutError`. 15 секунд + один retry — качество гипотез выросло, в лимит 45 минут укладываемся.

. **Один вызов LLM вместо трёх** — дешевле по токенам, быстрее, гипотезы не повторяются. Просим сразу JSON-массив из трёх.

. **`--workers 1` в Docker** — 4 воркера × ~150 МБ pandas = OOM при лимите 512 МБ. Плюс `MALLOC_ARENA_MAX=2` — без него память раздувается до 500+ МБ.

6. Концепт вещи: Умная серьга-кафф + умная подушка.
