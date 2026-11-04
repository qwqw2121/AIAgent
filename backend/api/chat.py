import json
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage


router = APIRouter(prefix="/api", tags=["chat"])


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户问题")
    session_id: Optional[str] = Field(
        None, description="会话 ID，可选，便于前端追踪"
    )


@router.post("/chat")   #路由定义在独立的 APIRouter 中。
async def chat(req: AskRequest, request: Request):
    """Stream agent tokens and tool activity as Server-Sent Events."""

    # 从当前 FastAPI 应用中获取 Agent
    agent = getattr(request.app.state, "agent", None)

    if agent is None:
        raise HTTPException(
            status_code=503,
            detail="问答 Agent 未初始化，请检查 MCP 服务配置"
        )

    session_id = req.session_id or str(uuid.uuid4())

    config = {
        "configurable": {"thread_id": session_id},
        "recursion_limit": 10,
    }

    def sse(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    async def event_stream():
        # 先通知前端开始处理
        yield sse({"type": "tool", "name": ""})

        try:
            async for event in agent.astream_events(
                {"messages": [HumanMessage(content=req.question)]},
                config=config,
                version="v2",
            ):
                if await request.is_disconnected():
                    break

                event_type = event.get("event")
                metadata = event.get("metadata") or {}

                if (
                    event_type == "on_chat_model_stream"
                    and metadata.get("langgraph_node") == "agent"
                ):
                    chunk = event.get("data", {}).get("chunk")

                    # 跳过模型生成工具调用指令的内容
                    if getattr(chunk, "tool_call_chunks", None):
                        continue

                    content = getattr(chunk, "content", "")
                    if content:
                        yield sse({
                            "type": "token",
                            "content": content
                        })

                elif event_type == "on_tool_start":
                    yield sse({
                        "type": "tool",
                        "name": event.get("name", "")
                    })

                elif event_type == "on_tool_end":
                    yield sse({
                        "type": "tool_end",
                        "name": event.get("name", "")
                    })

            yield "data: [DONE]\n\n"

        except Exception as error:
            yield sse({
                "type": "error",
                "content": f"{type(error).__name__}: {error}"
            })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )