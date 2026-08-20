from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/rag", tags=["rag"])

class QueryRequest(BaseModel):
    question: str

@router.post("/query")
def query(request: QueryRequest):
    return {
        "implemented": False,
        "question": request.question,
        "message": "RAG 页面已连接到统一 API。下一步把你现有的 rag 检索函数接到这里，返回答案与新闻来源。",
        "sources": [],
    }
