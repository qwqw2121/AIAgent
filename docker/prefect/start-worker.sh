#!/bin/sh
set -eu

until prefect work-pool inspect default-work-pool >/dev/null 2>&1; do
  prefect work-pool create default-work-pool --type process >/dev/null 2>&1 || true
  sleep 2
done

python pipeline/deployments.py
exec prefect worker start --pool default-work-pool --name ai-news-worker
