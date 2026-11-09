# embedding/embed_news.py

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from threading import Lock
from typing import Optional

from storage.db import get_connection, update_fields
from embedding.vector_store import get_vector_store

vector_store = get_vector_store()

# =====================================================
# 1. 全局配置
# =====================================================
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "online").lower()
EMBED_MODEL = os.getenv("LLM_EMBEDING", "text-embedding-v3")
BGE_MODEL_PATH = os.getenv("BGE_MODEL_PATH", "/mnt/d/AI_Models/bge-m3")

MAX_WORKERS = 5               # 并发线程数；本地模式动态降到 2
RATE_LIMIT_PER_SEC = 3        # 全局每秒请求上限
MAX_RETRY = 2                 # 单次运行内单条重试次数
MAX_EMBED_ATTEMPTS = 3        # 跨运行累计失败上限，达到后不再捞起
BATCH_COMMIT = 20             # 每处理多少条提交一次
REQUEST_TIMEOUT = 60

print(f"🚀 Embedding 模式: {EMBEDDING_PROVIDER.upper()}")


# =====================================================
# 2. 全局限流器
# =====================================================
class RateLimiter:
    def __init__(self, per_sec: float):
        self.interval = 1.0 / per_sec
        self.lock = Lock()
        self.next_time = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            delay = self.next_time - now
            if delay > 0:
                time.sleep(delay)
            self.next_time = max(now, self.next_time) + self.interval


_rate_limiter = RateLimiter(RATE_LIMIT_PER_SEC)


# =====================================================
# 3. 引擎：本地 BGE-M3 / 在线 API
# =====================================================
_local_model = None
_online_client = None


def get_local_model():
    global _local_model
    if _local_model is None:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        print(f"🔄 正在加载本地 BGE-M3 模型: {BGE_MODEL_PATH} (CPU)")
        from FlagEmbedding import BGEM3FlagModel
        _local_model = BGEM3FlagModel(BGE_MODEL_PATH, use_fp16=False, device="cpu")
    return _local_model


def get_online_client():
    global _online_client
    if _online_client is None:
        from openai import OpenAI
        api_key = os.getenv("LLM_API_KEY")
        base_url = os.getenv("LLM_BASE_URL")
        if not api_key or not base_url:
            raise ValueError("❌ 使用在线 Embedding 需要在 .env 中配置 LLM_API_KEY 和 LLM_BASE_URL")
        _online_client = OpenAI(
            api_key=api_key, base_url=base_url,
            timeout=REQUEST_TIMEOUT, max_retries=0,
        )
    return _online_client


def get_embedding(text: str) -> Optional[list]:
    if not text or len(text.strip()) < 5:
        return None
    try:
        if EMBEDDING_PROVIDER == "online":
            resp = get_online_client().embeddings.create(model=EMBED_MODEL, input=text)
            return resp.data[0].embedding
        else:
            result = get_local_model().encode(text)
            emb = result["dense_vecs"]
            return emb.tolist() if hasattr(emb, "tolist") else list(emb)
    except Exception as e:
        print(f"❌ Embedding 生成失败 ({EMBEDDING_PROVIDER}): {e}", flush=True)
        return None


# =====================================================
# 4. 构造嵌入文本
# =====================================================
def build_embedding_text(row) -> str:
    title = str(row["title"]).strip() if row["title"] else "未知标题"
    summary = str(row["summary"]).strip() if row["summary"] else "无摘要"
    category = str(row["llm_category"]).strip() if row["llm_category"] else "未分类"

    keywords = row["keywords"] or []
    if isinstance(keywords, str):
        try:
            keywords = json.loads(keywords)
        except json.JSONDecodeError:
            keywords = [keywords]

    keywords_text = ", ".join(str(k) for k in keywords) if isinstance(keywords, list) else str(keywords)

    text = (
        f"标题：{title}\n"
        f"摘要：{summary}\n"
        f"分类：{category}\n"
        f"关键词：{keywords_text}"
    ).strip()
    return text or "无有效内容"


# =====================================================
# 5. 读取待处理新闻
# =====================================================
def load_news(conn, start_ts, end_ts):

    return conn.execute(
        """
        SELECT id, title, summary, llm_summary, llm_category, keywords,
               source, category, published, published_ts,
               COALESCE(embed_attempts, 0) AS embed_attempts
        FROM news
        WHERE status IN ('analyzed', 'embed_failed')
          AND is_duplicate = 0
          AND COALESCE(embed_attempts, 0) < ?
          AND published_ts >= ?
          AND published_ts < ?
        ORDER BY id
        """,
        (MAX_EMBED_ATTEMPTS, start_ts, end_ts),
    ).fetchall()
#在 Python 的数据库操作（如 sqlite3）中，? 是参数占位符（Placeholder）。

# =====================================================
# 6. 单条工作单元（工作线程调用，不碰数据库）
# =====================================================
def _embed_one(row) -> tuple:
    text = build_embedding_text(row)
    for attempt in range(MAX_RETRY + 1):
        try:
            _rate_limiter.wait()
            emb = get_embedding(text)
            if emb is not None:
                return row["id"], text, emb
        except Exception as e:
            print(f"  ⚠️ id={row['id']} 第{attempt + 1}次失败: {e}", flush=True)
        if attempt < MAX_RETRY:
            time.sleep(2 ** attempt)
    return row["id"], text, None


# =====================================================
# 7. 测试
# =====================================================
def test_embedding() -> bool:
    print(f"\n🧪 测试 Embedding ({EMBEDDING_PROVIDER})...")
    start = time.time()
    emb = get_embedding("测试文本：这是一条关于AI的新闻")
    cost = time.time() - start
    if emb:
        print(f"   ✅ 成功生成向量 (耗时: {cost:.2f}s, 维度: {len(emb)})")
        return True
    print("   ❌ 测试失败")
    return False


# =====================================================
# 8. 主流程
# =====================================================
def run(start_ts, end_ts, skip_test: bool = False) -> dict:
    workers = MAX_WORKERS
    if EMBEDDING_PROVIDER == "local":
        get_local_model()   # 预加载，避免线程池内重复加载
        workers = 2         # 本地推理并发不宜过高

    if not skip_test and not test_embedding():
        print("❌ Embedding 测试失败，请检查配置")
        return {"total": 0, "success": 0, "failed": 0, "error": "embedding test failed"}

    conn = get_connection(row_factory=True)
    try:
        news_list = load_news(conn, start_ts, end_ts)
        total = len(news_list)
        print(f"\n📊 待向量化新闻：{total} 条")
        if not total:
            return {"total": 0, "success": 0, "failed": 0}

        ok = fail = 0
        try:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {ex.submit(_embed_one, r): r for r in news_list}
                for i, fut in enumerate(as_completed(futures), 1):
                    row = futures[fut]
                    news_id = row["id"]
                    try:
                        _, text, emb = fut.result()
                    except Exception as e:
                        text, emb = None, None
                        print(f"  ❌ id={news_id} 异常: {e}", flush=True)

                    attempts = (row["embed_attempts"] or 0) + 1

                    if emb is None:
                        # 只保留 embed_failed；达到上限后仅记录次数，不再被 load_news 捞起
                        update_fields(
                            conn, news_id,
                            {"status": "embed_failed", "embed_attempts": attempts},
                            commit=False,
                        )
                        fail += 1
                    else:
                        try:
                            published_ts = row["published_ts"]
                            if published_ts is None:
                                raise ValueError(
                                    f"新闻 ID={news_id} 缺少 published_ts，不能写入向量库"
                                )

                            vector_store.add_news(
                                news_id=news_id,
                                embedding=emb,
                                embedding_text=text,
                                metadata={
                                    "news_id": int(news_id),
                                    "title": row["title"] or "",
                                    "source": row["source"] or "",
                                    "category": row["category"] or "",
                                    "published": row["published"] or "",
                                    "published_at": row["published"] or "",
                                    "published_ts": int(published_ts),
                                },
                            )
                            update_fields(
                                conn, news_id,
                                {"status": "embedded", "embed_attempts": attempts},
                                commit=False,
                            )
                            ok += 1
                        except Exception as e:
                            print(f"  ❌ id={news_id} 写向量库失败: {e}", flush=True)
                            update_fields(
                                conn, news_id,
                                {"status": "embed_failed", "embed_attempts": attempts},
                                commit=False,
                            )
                            fail += 1

                    if i % BATCH_COMMIT == 0:
                        conn.commit()
                    print(f"[{i}/{total}] id={news_id} {'✅' if emb is not None else '❌'}", flush=True)
        finally:
            conn.commit()

        print(f"\n{'=' * 60}")
        print(f"📊 Embedding 完成: 成功 {ok}, 失败 {fail}, 总计 {total}")
        return {"total": total, "success": ok, "failed": fail}
    finally:
        conn.close()


if __name__ == "__main__":
    from pipeline.utils import day_bounds_ts
    s, e = day_bounds_ts((date.today() - timedelta(days=1)).isoformat())
    print(run(s, e))