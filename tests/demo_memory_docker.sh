#!/bin/bash
# tests/demo_memory_docker.sh
# Замер памяти контейнера с РЕАЛЬНЫМИ лимитами стенда
set -e

echo "═══ Memory test: docker stats с лимитом 512MB ═══"
echo ""

# Пересобрать (на случай изменений)
docker build -t team28:latest . -q

# Остановить старый
docker rm -f team28_demo 2>/dev/null || true

# Запустить с лимитами стенда
docker run -d --name team28_demo \
    -p 8001:8000 \
    --memory=512m --memory-swap=512m \
    -e TEAM=team28 \
    -e LLM_API_KEY=dummy-key \
    team28:latest

sleep 5

# Простой
echo "[1/3] Простой (после старта):"
docker stats --no-stream team28_demo | tail -1
echo ""

# Один /run локально (без реального API — эмулируем health-нагрузкой)
echo "[2/3] Под нагрузкой (100 health-пингов):"
for i in {1..100}; do
    curl -s http://localhost:8001/health > /dev/null &
done
wait
docker stats --no-stream team28_demo | tail -1
echo ""

# Проверить, что не упал
echo "[3/3] Проверка, что контейнер не упал:"
if docker inspect team28_demo --format='{{.State.Running}}' | grep -q true; then
    echo "  ✅ Контейнер жив"
    OOM=$(docker inspect team28_demo --format='{{.State.OOMKilled}}')
    if [ "$OOM" = "true" ]; then
        echo "  ❌ OOMKilled — память превышена"
        docker rm -f team28_demo
        exit 1
    else
        echo "  ✅ OOM не сработал"
    fi
else
    echo "  ❌ Контейнер упал"
    docker logs team28_demo 2>&1 | tail -20
    docker rm -f team28_demo
    exit 1
fi

docker rm -f team28_demo
echo ""
echo "✅ Память в норме"