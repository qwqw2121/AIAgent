'''⭐ 关键：共享状态的数据结构定义
 记录"这一次运行"的执行情况——比如这次跑，clean 阶段处理了多少条、
 报错了几条、要不要触发告警。它不需要装下所有文章数据，只需要装"运行时元信息"。
'''

# pipeline/state.py
from enum import Enum
from pydantic import BaseModel
from datetime import date

class NewsStatus(str, Enum):
    RAW = "raw"
    EXTRACTED = "extracted"
    EXTRACT_FAILED = "extract_failed"
    DEDUPED = "deduped"
    ANALYZED = "analyzed"
    ANALYZE_FAILED = "analyze_failed"
    EMBEDDED = "embedded"
    CLUSTERED = "clustered"
    REPORTED = "reported"

class PipelineState(BaseModel):
    run_date: date
    stage_stats: dict[str, dict] = {}
    errors: list[str] = []