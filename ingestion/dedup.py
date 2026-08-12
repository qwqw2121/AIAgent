"""
去重: 标题hash精确去重 + 相似新闻聚类

跑在 extract_content.py 之后,只处理正文提取成功的记录。

第一步: title_hash 精确去重
    抓取阶段(crawl.py)已经给每条新闻算好了 title_hash(标题归一化后的md5)。
    这里按 title_hash 分组,同一个hash只保留最早入库的一条(id最小),
    其余标记 is_duplicate=1。这一步抓的是"标题完全一样"的情况
    (比如同一篇文章被多个RSS源重复收录,或者你重复跑了抓取脚本)。

第二步: 同日标题模糊相似度聚类
    抓"标题不完全一样,但明显讲的是同一件事"的情况,比如:
    "OpenAI发布GPT-6" vs "OpenAI正式发布GPT-6大模型,性能大幅提升"
    用 difflib 算字符串相似度,不需要调用任何模型,成本几乎为0。
    按发布日期分桶比较,避免全库O(n^2)两两比较。

    注意: 这一步只能抓"标题字面接近"的重复,抓不住"标题完全不同但讲同一件事"
    (比如中英文报道、不同角度切入的报道)。那种要靠后面embedding语义聚类,
    是更后置的步骤,数据量大、跑起来更贵,先靠这两轮低成本去重把明显的重复过滤掉。
"""
import difflib
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DB_PATH = Path("storage/news.db")

TITLE_SIM_THRESHOLD = 0.85  # difflib相似度阈值,超过视为同一事件


def ensure_columns(conn):
    cursor = conn.execute("PRAGMA table_info(news)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    to_add = []
    if "is_duplicate" not in existing_cols:
        to_add.append("ALTER TABLE news ADD COLUMN is_duplicate INTEGER DEFAULT 0")
    if "duplicate_of" not in existing_cols:
        to_add.append("ALTER TABLE news ADD COLUMN duplicate_of INTEGER")
    for sql in to_add:
        conn.execute(sql)
    if to_add:
        conn.commit()


def dedup_exact(conn):
    """按 title_hash 精确去重,同hash只留id最小的一条"""
    rows = conn.execute("""
        SELECT id, title_hash FROM news
        WHERE extract_status IN ('ok_trafilatura', 'ok_readability')
          AND is_duplicate = 0
    """).fetchall()

    groups = defaultdict(list)
    for news_id, title_hash in rows:
        if title_hash:  # 防止空hash的记录被误分到同一组
            groups[title_hash].append(news_id)

    dup_count = 0
    for title_hash, ids in groups.items():
        if len(ids) <= 1:
            continue
        ids_sorted = sorted(ids)
        keep_id = ids_sorted[0]
        for dup_id in ids_sorted[1:]:
            conn.execute(
                "UPDATE news SET is_duplicate=1, duplicate_of=? WHERE id=?",
                (keep_id, dup_id),
            )
            dup_count += 1

    conn.commit()
    print(f"精确去重(title_hash): 标记 {dup_count} 条重复")


def title_similarity(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def dedup_fuzzy(conn):
    """同一天内标题模糊相似度聚类"""
    rows = conn.execute("""
        SELECT id, title, published_ts FROM news
        WHERE extract_status IN ('ok_trafilatura', 'ok_readability')
          AND is_duplicate = 0
    """).fetchall()

    # 按发布日期分桶,减少两两比较规模
    buckets = defaultdict(list)
    for news_id, title, published_ts in rows:
        if published_ts:
            day = datetime.utcfromtimestamp(published_ts).strftime("%Y-%m-%d")
        else:
            day = "unknown"
        buckets[day].append((news_id, title))

    dup_count = 0
    for day, items in buckets.items():
        items = sorted(items, key=lambda x: x[0])  # 按id排序,保留更早入库的
        n = len(items)
        marked_dup = set()

        for i in range(n):
            if items[i][0] in marked_dup:
                continue
            for j in range(i + 1, n):
                if items[j][0] in marked_dup:
                    continue
                sim = title_similarity(items[i][1], items[j][1])
                if sim >= TITLE_SIM_THRESHOLD:
                    conn.execute(
                        "UPDATE news SET is_duplicate=1, duplicate_of=? WHERE id=?",
                        (items[i][0], items[j][0]),
                    )
                    marked_dup.add(items[j][0])
                    dup_count += 1

    conn.commit()
    print(f"模糊去重(标题相似度): 标记 {dup_count} 条重复")


def run():
    conn = sqlite3.connect(DB_PATH)
    ensure_columns(conn)

    dedup_exact(conn)   # 先做精确去重,减少后面模糊比较的数据量
    dedup_fuzzy(conn)

    conn.close()
    print("去重完成")


if __name__ == "__main__":
    run()