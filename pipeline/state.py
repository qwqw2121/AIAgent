from datetime import date, datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from pipeline.utils import day_bounds_ts


class NewsStatus(str, Enum): #新闻处理状态
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
    UNCLUSTERED = "unclustered"   # 已聚类阶段处理，但未归入任何成型事件（低重要性或小事件过期）
    REPORTED = "reported"


class CrawlMode(str, Enum):  #抓取模式s
    MONTH = "month"      # 按月抓取(初始化/补漏)
    RECENT = "recent"    # 最近 N 天(日常定时)


class PipelineState(BaseModel):  #一次 Pipeline 运行的状态
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # ---- 唯一的业务输入 ----
    run_date: date                                   # 必填，UTC 自然日

    # ---- 成本控制 ----
    max_analyze: int = 150
    per_source_cap: int = 30

    # ---- 运行信息（只记录，不参与任何业务逻辑）----
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    stage_stats: dict[str, dict] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)

    @property
    def day(self) -> str:
        return self.run_date.isoformat()

    def day_range_ts(self) -> tuple[int, int]:
        return day_bounds_ts(self.day)