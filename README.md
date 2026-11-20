1. Запуск.
docker build -t team28:latest . && docker run -d --name team28_app \
  -p 8000:8000 --memory=512m --memory-swap=512m \
  -e LLM_API_KEY="$LLM_API_KEY" team28:latest
curl -i http://localhost:8000/health   # 200 OK
Клиент: cd client && npm install && npm run build → client/dist/.
Адрес backend задаётся через VITE_API_URL.

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
- отказались от действующих носимых устройств и решений.
- после сессии вопросов/ответов отказались от мобильного интерфейса.


6. Концепт вещи: Умная серьга-кафф + умная подушка.
