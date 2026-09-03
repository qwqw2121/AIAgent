# ==========================================
# 前端 Dockerfile (Next.js 开发环境)
# ==========================================

# 1. 使用官方 Node.js Alpine 轻量级镜像
FROM node:20-alpine AS build

# 2. 设置工作目录
WORKDIR /app

# 3. 复制 package 配置文件
# 注意：因为 docker-compose 中的 build context 是项目根目录，所以路径带 frontend/
COPY frontend/package.json frontend/package-lock.json* ./

# 4. 安装依赖
# 如果有 package-lock.json 使用 npm ci (速度快且严格)，否则 fallback 到 npm install
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
COPY frontend/ ./
RUN npm run build

FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public

# 5. 暴露 Next.js 开发服务器端口
EXPOSE 3000

# 6. 默认启动命令 (启动 Next.js 开发模式)
CMD ["npm", "run", "start"]