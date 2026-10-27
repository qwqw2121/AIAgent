#!/bin/sh
set -eu
cd /app
export PYTHONPATH=/app

echo "等待 Prefect Server 并创建 work pool..."
until prefect work-pool inspect default-work-pool >/dev/null 2>&1; do
  prefect work-pool create default-work-pool --type process >/dev/null 2>&1 || true
  sleep 2
done

echo "注册 deployment..."
python pipeline/deployments.py

echo "启动 worker..."
exec prefect worker start --pool default-work-pool --name ai-news-worker