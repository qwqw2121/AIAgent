# backend/main.py
import sys
import json
from pathlib import Path
from datetime import date, datetime
from contextlib import closing, asynccontextmanager
from typing import Optional

# 添加项目根目录到 sys.path（而不是 backend 目录）
ROOT_DIR = Path(__file__).parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from storage.db import (
    DB_PATH,
    get_connection,
    init_db,
    fetch_report_by_date,
    fetch_reports_range,
    fetch_news_by_ids,
)
from backend.api.news import router as news_router
from backend.api.dashboard import router as dashboard_router
from backend.api.sources import router as sources_router
from backend.api.events import router as events_router
from backend.api.reports import router as reports_router
from backend.api.rag import router as rag_router
from backend.api.trends import router as trend_router


# ============================================================
# lifespan：启动时初始化 Agent（MCP stdio 连接 + 编译图，只做一次）
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # 建索引（幂等）

    try:
        from agent.graph import init_agent
        app.state.agent = await init_agent()
        print("✅ 问答 Agent 初始化完成")
    except Exception as e:
        print(f"⚠️ 问答 Agent 初始化失败: {e}")
        app.state.agent = None

    yield


app = FastAPI(title="AI News Agent API", version="0.4.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(dashboard_router)
app.include_router(sources_router)
app.include_router(events_router)
app.include_router(reports_router)
app.include_router(rag_router)
app.include_router(trend_router)
app.include_router(news_router)

def get_db():
    """FastAPI 依赖注入：每个请求一个连接，保证关闭"""
    with closing(get_connection()) as conn:
        yield conn


def enrich_report_news(conn, report):
    """Use the stored news records to provide readable details for each event."""
    if not isinstance(report, dict):
        return report

    events = report.get("events", [])
    if not isinstance(events, list):
        return report

    news_ids = {
        news_id
        for event in events
        if isinstance(event, dict)
        for news_id in event.get("news_ids", [])
        if isinstance(news_id, int)
    }
    news_by_id = fetch_news_by_ids(conn, news_ids)

    for event in events:
        if not isinstance(event, dict):
            continue
        event["news"] = [
            news_by_id[news_id]
            for news_id in event.get("news_ids", [])
            if news_id in news_by_id
        ]

    return report


def report_response(conn, report_row):
    """把日报记录转为响应结构（enrich 复用同一个连接）"""
    report = enrich_report_news(conn, json.loads(report_row["report_json"]))
    return {
        "date": report_row["report_date"],
        "overview": report_row["overview"],
        "report": report,
    }


def _validate_date(d: str):
    try:
        datetime.strptime(d, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="日期格式错误，请使用 YYYY-MM-DD 格式"
        )


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


# ============================================================
#  问答入口
# ============================================================
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户问题")
    session_id: Optional[str] = Field(None, description="会话 ID，可选，便于前端追踪")


@app.post("/api/ask")
async def ask(req: AskRequest):
    """自然语言问答入口：内部由 LangGraph Agent 路由（知识检索 / 日报简报）"""
    agent = getattr(app.state, "agent", None)
    if agent is None:
        raise HTTPException(status_code=503, detail="问答 Agent 未初始化，请检查 MCP 服务配置")

    try:
        result = await agent.ainvoke({"question": req.question})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent 调用失败: {e}")

    return {
        "question": req.question,
        "session_id": req.session_id,
        "route": result.get("route"),
        "report_date": result.get("report_date"),
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
    }


# ============================================================
#  日报接口
#  ⚠️ 顺序要求：静态路径(today/range) 必须在 动态路径({report_date}) 之前，
#     否则 /today 会被 {report_date} 抢先匹配，报 "日期格式错误"。
# ============================================================

# 1. 静态：今天的日报
@app.get("/api/daily-report/today")
def get_today_daily_report(conn=Depends(get_db)):
    row = fetch_report_by_date(conn, date.today().isoformat())
    if not row:
        raise HTTPException(status_code=404, detail="今日日报尚未生成")
    return report_response(conn, row)


# 2. 静态：日期范围
@app.get("/api/daily-report/range")
def get_daily_report_range(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    conn=Depends(get_db),
):
    """获取日期范围内已经生成的日报。"""
    _validate_date(start_date)
    _validate_date(end_date)
    rows = fetch_reports_range(conn, start_date, end_date)
    return [report_response(conn, row) for row in rows]


# 3. 动态：指定日期的日报（必须放最后）
@app.get("/api/daily-report/{report_date}")
def get_daily_report(report_date: str, conn=Depends(get_db)):
    """获取指定日期的日报，格式 YYYY-MM-DD，例如 2026-08-15"""
    _validate_date(report_date)
    row = fetch_report_by_date(conn, report_date)
    if not row:
        raise HTTPException(status_code=404, detail=f"未找到 {report_date} 的日报")
    return report_response(conn, row)


import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )