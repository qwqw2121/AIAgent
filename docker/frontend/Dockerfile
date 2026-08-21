# ==========================================
# 前端 Dockerfile (Next.js 开发环境)
# ==========================================

# 1. 使用官方 Node.js Alpine 轻量级镜像
FROM node:20-alpine

# 2. 设置工作目录
WORKDIR /app

# 3. 复制 package 配置文件
# 注意：因为 docker-compose 中的 build context 是项目根目录，所以路径带 frontend/
COPY frontend/package.json frontend/package-lock.json* ./

# 4. 安装依赖
# 如果有 package-lock.json 使用 npm ci (速度快且严格)，否则 fallback 到 npm install
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# ⚠️ 注意：这里故意不 COPY 前端源码 (frontend/app, frontend/components 等)！
# 源码将通过 docker-compose.yml 的 volumes 挂载到 /app 目录，实现 Next.js 热更新。

# 5. 暴露 Next.js 开发服务器端口
EXPOSE 3000

# 6. 默认启动命令 (启动 Next.js 开发模式)
CMD ["npm", "run", "dev"]