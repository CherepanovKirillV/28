# Sain Case 3 — React-интерфейс

Первая часть визуального интерфейса профиля недели по предоставленному макету:

- 11 карточек заполняются из `weeks[].profile`;
- три гипотезы берутся из `weeks[].hypotheses`;
- можно переключаться между всеми неделями ответа;
- `confidence` управляет прогрессом карточек и знака Сэйн;
- `unknown` отображается как отсутствие данных.

## Запуск

Из корня общего репозитория:

```bash
cd frontend
pnpm install
pnpm run dev
```

## Проверки

```bash
pnpm run typecheck
pnpm test
pnpm run build
```

## Backend API

Типизированные методы для `GET /`, `GET /health` и `POST /run` находятся в
`src/api/client.ts`. Адрес бэкенда задаётся через `VITE_API_BASE_URL`. В dev переменную
можно оставить пустой: Vite проксирует `/run` и `/health` на `http://localhost:8000`.

При открытии страницы фронтенд автоматически отправляет `POST /run`. Код датасета
задаётся через `VITE_DATASET_CODE` (по умолчанию `case3-dev-v1`). Bearer-токен хранится
только на бэкенде в `HACK_TEAM_TOKEN` и не попадает в браузерный JavaScript.

## Контракт для backend

Типы актуального ответа `/run` находятся в `src/api/types.ts`; исходный mock и его
runtime-проверка сохранены отдельно для тестов контракта.

Корень ответа `/run`:

```json
{
  "weeks": [
    {
      "record_id": "case3-dev-week-001",
      "profile": {
        "chronotype": { "value": "late", "confidence": 0.91 }
      },
      "hypotheses": [
        { "text": "...", "confidence": 0.86 },
        { "text": "...", "confidence": 0.82 },
        { "text": "...", "confidence": 0.76 }
      ]
    }
  ]
}
```

Правила:

- `record_id` — непустая строка;
- в `profile` обязательны все 11 ключей из `PROFILE_FIELD_KEYS`;
- `value` — строка, число или строка `unknown`;
- `confidence` — число от 0 до 1;
- гипотез всегда ровно три, текст не пустой.
