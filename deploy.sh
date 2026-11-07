#!/usr/bin/env bash
set -euo pipefail

[ -z "$(git status --porcelain)" ] || { echo "有未提交改动，先 commit"; exit 1; }

export TAG=$(git rev-parse --short HEAD)
export NEXT_PUBLIC_API_URL=

# 关闭 BuildKit，用经典构建器：直接使用本地已有的基础镜像，不再联网校验元数据
export DOCKER_BUILDKIT=0
export COMPOSE_DOCKER_CLI_BUILD=0

# 确保基础镜像在本地（已有则秒过）
docker pull node:20-alpine
docker pull python:3.11-slim

docker compose build backend frontend
docker compose push backend frontend

echo "已推送版本 $TAG"
echo "服务器上执行： sed -i 's/^TAG=.*/TAG=$TAG/' .env && docker compose pull && docker compose up -d"
