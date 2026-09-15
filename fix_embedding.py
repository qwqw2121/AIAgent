# fix_embedding.py
import sys
import sqlite3
from pathlib import Path

# 确保项目根目录在 sys.path 中
ROOT_DIR = Path(__file__).parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

DB_PATH = Path("storage/news.db")

from storage.vectorstore import upsert_news


def fix_embeddings(limit: int = None, commit_every: int = 20):
    print(f"🚀 开始修复向量库数据 (本次处理 {limit if limit else '全部'} 条)...\n")

    if not DB_PATH.exists():
        print(f"❌ 找不到数据库文件: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 关键改动 1：处理 analyzed + embed_failed + NULL
    # analyzed 是 LLM 分析完但还没 embed 的，embed_failed 是之前 embed 失败的
    sql = """
        SELECT id, title, summary, source, url, llm_category, importance
        FROM news
        WHERE status IN ('analyzed', 'embed_failed', 'embedded')
           OR status IS NULL
        ORDER BY id
    """
    params = []

    # 关键改动 2：只有 limit 有值时才拼 LIMIT，避免 None 导致 datatype mismatch
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    cursor.execute(sql, params)
    rows = cursor.fetchall()
    total = len(rows)

    if not rows:
        print("✅ 没有需要修复的数据。")
        conn.close()
        return

    print(f"📊 共 {total} 条待处理\n")

    success_count = 0
    fail_count = 0

    for i, row in enumerate(rows, 1):
        news_id = row["id"]
        title = row["title"] or ""
        summary = row["summary"] or ""

        metadata = {
            "title": title,
            "source": row["source"],
            "url": row["url"],
            "llm_category": row["llm_category"],
            "importance": row["importance"],
        }

        try:
            print(f"  ⏳ [{i}/{total}] id={news_id} {title[:40]}...")
            upsert_news(
                news_id=news_id,
                title=title,
                summary=summary,
                metadata=metadata,
            )
            cursor.execute("UPDATE news SET status = 'embedded' WHERE id = ?", (news_id,))
            success_count += 1
            print(f"  ✅ [{i}/{total}] id={news_id} 成功")

        except Exception as e:
            print(f"  ❌ [{i}/{total}] id={news_id} 失败: {e}")
            # 关键改动 3：失败时标记 embed_failed，下次可重试
            cursor.execute("UPDATE news SET status = 'embed_failed' WHERE id = ?", (news_id,))
            fail_count += 1

        # 定期提交，避免中途崩溃丢进度
        if i % commit_every == 0:
            conn.commit()
            print(f"  💾 已提交 {i}/{total}")

    conn.commit()
    conn.close()

    print(f"\n🎉 完成！成功 {success_count}，失败 {fail_count}，共 {total}")
    print("👉 现在可以运行 `python check_vectorstore.py` 验证检索。")


if __name__ == "__main__":
    # 先小批量测试：
    # fix_embeddings(limit=3)
    # 确认流程没问题后，全量：
    fix_embeddings()