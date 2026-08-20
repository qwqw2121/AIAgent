from fastapi import APIRouter

router = APIRouter(prefix="/api/reports", tags=["reports"])

@router.get("/daily")
def daily_report():
    return {
        "implemented": False,
        "message": "日报页面已经预留。下一步将把当天新闻、热点事件和 LLM 总结组合成 Daily Brief。",
    }

@router.get("/monthly")
def monthly_report():
    return {
        "implemented": False,
        "message": "月报页面已经预留。下一步将按月份聚合新闻、事件和趋势。",
    }
