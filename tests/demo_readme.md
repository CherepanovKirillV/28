# Демо для жюри — шпаргалка

## Порядок показа (20 минут)

### 1. Pre-flight (30 сек, ДО выступления)
- [ ] `bash tests/pre_demo_check.sh` → всё зелёное
- [ ] Открыт терминал, `source set_env.sh` выполнен
- [ ] Открыт `tests/demo_readme.md` (этот файл)
- [ ] Открыт `main.py` на функции `run_endpoint`

### 2. Открытие (2 мин)
**Что говорим:**
> «Сервис получает датасет с 30 неделями событий wearable/phone/smart_home,
> считает 11 полей профиля, генерирует 3 гипотезы через LLM + fallback,
> отдаёт schema-compliant JSON. Локальный скор +163 очка, валидация 30/30.»

**Что показываем:**
```bash
curl -s https://team28.hack.be-healthy.tech/health
# {"team":"team28","status":"ok"}

3. Архитектура (3 мин)
Открываем main.py, показываем:

run_endpoint — оркестратор

_pack_week — упаковка по схеме

try/except на каждой неделе — безопасность

Фраза: «main.py ничего не считает сам — только координирует calculator + llm_generator».

4. Расчёт 11 полей (3 мин)
Открываем calculator.py, показываем:

calculate_profile — вход/выход

_CONFIDENCE / _PRIOR_CONFIDENCE — калибровка

Фраза: «Каждое поле — value + confidence. Если данных нет — soft guess с conf=0.5, лучше +0.5/−0.25, чем 0».

5. LLM + fallback (3 мин)
Запускаем:

bash
python tests/demo_fallback.py
Фраза: «LLM обёрнута в три уровня: таймаут 5с, fallback без сети, пост-фильтр медицины. Ни один сбой не роняет /run».

6. End-to-end live (5 мин)
Запускаем:

bash
python tests/demo_api_scenarios.py --skip-slow   # 30 сек
Затем:

bash
python tests/demo_api_scenarios.py --only run_happy   # 3–15 мин
Фраза: «Обработка ошибок — 400 на битый JSON, 502 на отказ апстрима, 0 ошибок 500 на весь путь».

7. Память (2 мин)
Запускаем:

bash
python tests/demo_memory.py
Фраза: «Пик ~250 МБ при лимите 512 — запас 50%. Достигается --workers 1, MALLOC_ARENA_MAX=2, del + gc.collect.»

8. Резюме (1 мин)
Фраза:

«Три инварианта:

Никогда не отдаём 500 на /run — отдаём 200 с fallback.

Никогда не теряем очки на unknown — soft guess с conf=0.5.

Никогда не зависим от LLM — fallback даёт текст и без неё.

Локальный скор +163, schema 30/30, память ~250 МБ, время ~5 минут.»