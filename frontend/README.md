# Sain Case 3 — фаза 0

Минимальный frontend-scaffold без дизайна. Эта папка закрывает только задачи фазы 0:

- **FE-01:** React + TypeScript + Vite; mock JSON по структуре ответа кейса 3.
- **FE-02:** зафиксированный контракт `answers[]`, `week_id`, 11 полей профиля и ровно 3 гипотезы.

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

## Контракт для backend

Полный пример находится в `public/mock/case3-answers.json`, типы и runtime-проверка — в
`src/contracts/case3.ts`.

Корень ответа:

```json
{
  "answers": [
    {
      "week_id": "case3-dev-week-001",
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

- `week_id` — непустая строка;
- в `profile` обязательны все 11 ключей из `PROFILE_FIELD_KEYS`;
- `value` — строка, число или строка `unknown`;
- `confidence` — число от 0 до 1;
- гипотез всегда ровно три, текст не пустой.
