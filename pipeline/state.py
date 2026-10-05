from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class NewsStatus(str, Enum):
    RAW = "raw"
    EXTRACTED = "extracted"
    EXTRACT_FAILED = "extract_failed"
    DUPLICATE = "duplicate"
    DEDUPED = "deduped"
    ANALYZED = "analyzed"
    ANALYZE_FAILED = "analyze_failed"
    EMBEDDED = "embedded"
    EMBED_FAILED = "embed_failed"
    CLUSTERED = "clustered"
    REPORTED = "reported"


class CrawlMode(str, Enum):
    MONTH = "month"      # 按月抓取(初始化/补漏)
    RECENT = "recent"    # 最近 N 天(日常定时)


class PipelineState(BaseModel):
    # ---- 抓取参数 ----
    mode: CrawlMode = CrawlMode.RECENT
    year: Optional[int] = None
    month: Optional[int] = None
    lookback_days: int = 3

    # ---- 成本控制 ----
    max_analyze: int = 150        # 每次运行最多送 LLM 分析多少条
    per_source_cap: int = 30      # 单个来源每次最多分析多少条(防 arXiv 刷屏)
    max_report_days: int = 10     # 每次最多更新多少个日期的日报

    # ---- 运行信息 ----
    run_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    stage_stats: dict[str, dict] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)

    def since_ts(self) -> int:
        return int((self.run_at - timedelta(days=self.lookback_days)).timestamp())