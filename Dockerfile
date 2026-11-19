# python:3.10-slim — минимальный образ без компиляторов и dev-пакетов
FROM python:3.11-slim

WORKDIR /app

# Копируем ТОЛЬКО requirements — это кэшируемый слой.
# Пока requirements не изменился, pip не переустанавливает пакеты.
COPY requirements.txt .

# --no-cache-dir — не сохранять wheel-кэш pip
# rm -rf — дочистить возможные остатки
RUN pip install --no-cache-dir -r requirements.txt \
    && rm -rf /root/.cache/pip /tmp/*

# Копируем только рабочий код (data/ и тесты отсекает .dockerignore)
COPY main.py calculator.py llm_generator.py ./

EXPOSE 8000

# --workers 1 — КРИТИЧНО для 512 МБ:
# каждый uvicorn-воркер импортирует pandas (~150 МБ RAM).
# Два воркера = 300+ МБ и риск OOM. Один — безопасно.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]