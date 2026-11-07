#!/usr/bin/env bash
set -euo pipefail

[ -z "$(git status --porcelain)" ] || { echo "有未提交改动，先 commit"; exit 1; }

export TAG=$(git rev-parse --short HEAD)
export NEXT_PUBLIC_API_URL=

docker compose build backend frontend
docker compose push backend frontend

echo "已推送版本 $TAG"
echo "服务器上执行： sed -i 's/^TAG=.*/TAG=$TAG/' .env && docker compose pull && docker compose up -d"