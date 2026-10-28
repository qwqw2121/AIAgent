#!/bin/sh
set -eu
SERVER=user@1.2.3.4
REMOTE=~/ai-news

# 1. 服务器上生成一致性快照
ssh $SERVER "cd $REMOTE && docker compose exec -T backend python scripts/snapshot.py"

# 2. 拉到本地临时文件
rsync -avPz $SERVER:$REMOTE/storage/news.snapshot.db ./storage/news.db.new

# 3. 停本地服务、替换、重启
docker compose stop backend 2>/dev/null || true
mv ./storage/news.db.new ./storage/news.db
rm -f ./storage/news.db-wal ./storage/news.db-shm
docker compose start backend 2>/dev/null || true

