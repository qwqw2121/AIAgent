# backend/main.py
import sys
import os  
from pathlib import Path
# 添加项目根目录到 sys.path（而不是 backend 目录）
ROOT_DIR = Path(__file__).parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


from storage.db import (
    DB_PATH,
    init_db,
)
from backend.api.news import router as news_router
from backend.api.dashboard import router as dashboard_router
from backend.api.sources import router as sources_router
from backend.api.events import router as events_router
from backend.api.trends import router as trend_router
from backend.api.chat import router as chat_router
from backend.api.daily_reports import router as daily_reports_router

# ============================================================
# lifespan：启动时初始化 Agent（MCP stdio 连接 + 编译图，只做一次）
# ============================================================
from fastapi.responses import StreamingResponse

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # 建索引（幂等）
    try:
        from agent.graph import init_agent
        app.state.agent = await init_agent()
        print("✅ 问答 Agent 初始化完成")
    except Exception:
        import traceback
        traceback.print_exc()          # 打印完整堆栈，方便定位
        print("⚠️ 问答 Agent 初始化失败，详见上方堆栈")
        app.state.agent = None

    yield

    # 关闭时释放 MCP 持久会话
    try:
        from agent.graph import close_agent
        await close_agent()
    except Exception as e:
        print(f"⚠️ 关闭 Agent 失败: {e}")


app = FastAPI(title="AI News Agent API", version="0.4.0", lifespan=lifespan)

# 本地开发地址固定放行，线上地址通过环境变量 CORS_ORIGINS 配置（多个用英文逗号分隔）
_cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
_cors_origins += [
    o.strip().rstrip("/")
    for o in os.getenv("CORS_ORIGINS", "").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard_router)
app.include_router(sources_router)
app.include_router(events_router)
app.include_router(trend_router)
app.include_router(news_router)
app.include_router(chat_router)
app.include_router(daily_reports_router)


@app.get("/")
def root():
    return {"name": "AI News Agent API", "status": "running",
            "db": str(DB_PATH), "db_exists": Path(DB_PATH).exists(),
            "agent_ready": bool(getattr(app.state, "agent", None))}


@app.get("/api/health")
def health():
    return {"status": "ok", "db_exists": Path(DB_PATH).exists(),
            "db_path": str(DB_PATH),
            "agent_ready": bool(getattr(app.state, "agent", None))}


if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )