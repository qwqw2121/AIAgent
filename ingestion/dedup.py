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

# DB_PATH = Path("storage/news.db")
import os
DB_PATH = os.getenv("NEWS_DB_PATH", Path(__file__).parent.parent / "storage/news.db")

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
        
TITLE_SIM_THRESHOLD = 0.85  # difflib相似度阈值,超过视为同一事件
DONE = "status NOT IN ('raw','extract_failed')"   # 已提取过正文的记录

def _fetch_window(conn, start_ts, end_ts):
    """窗口内所有未被标重、已提取的记录(含已 deduped 的),用作对照"""
    return conn.execute(f"""
        SELECT id, title, title_hash, status, published_ts FROM news
        WHERE is_duplicate = 0 AND {DONE}
          AND published_ts >= ? AND published_ts < ?
        ORDER BY id
    """, (start_ts, end_ts)).fetchall()


def _mark_dup(conn, dup_id, keep_id):
    conn.execute(
        "UPDATE news SET is_duplicate=1, duplicate_of=?, status='duplicate' WHERE id=?",
        (keep_id, dup_id),
    )



def dedup_exact(conn, start_ts, end_ts):
    groups = defaultdict(list)
    for id_, _t, h, st, _ts in _fetch_window(conn, start_ts, end_ts):
        if h:
            groups[h].append((id_, st))

    n = 0
    for items in groups.values():
        if len(items) < 2:
            continue
        # 优先保留已经处理过的,其次保留 id 最小的
        processed = [i for i, st in items if st != "extracted"]
        keep = min(processed) if processed else min(i for i, _ in items)
        for id_, st in items:
            if id_ != keep and st == "extracted":   # 只标记待处理的,不动已处理的
                _mark_dup(conn, id_, keep)
                n += 1
    conn.commit()
    return n


def dedup_fuzzy(conn, start_ts, end_ts):
    items = _fetch_window(conn, start_ts, end_ts)
    # 精确去重已经标过的不在 items 里了(is_duplicate=1),不用额外处理
    marked, n = set(), 0
    for j in range(len(items)):
        id_j, title_j, _h, st_j, _ts = items[j]
        if st_j != "extracted" or id_j in marked:
            continue
        for i in range(j):
            id_i, title_i = items[i][0], items[i][1]
            if id_i in marked:
                continue
            sm = difflib.SequenceMatcher(None, title_i, title_j)
            if (sm.real_quick_ratio() >= TITLE_SIM_THRESHOLD
                    and sm.quick_ratio() >= TITLE_SIM_THRESHOLD
                    and sm.ratio() >= TITLE_SIM_THRESHOLD):
                _mark_dup(conn, id_j, id_i)
                marked.add(id_j)
                n += 1
                break
    conn.commit()
    return n


def mark_deduped(conn, start_ts, end_ts):
    cur = conn.execute("""
        UPDATE news SET status='deduped'
        WHERE status='extracted' AND is_duplicate=0
          AND published_ts >= ? AND published_ts < ?
    """, (start_ts, end_ts))
    conn.commit()
    return cur.rowcount


from pipeline.utils import day_bounds_ts, SQL_TZ
from storage.db import get_connection
def run(start_ts=None, end_ts=None):
    conn = get_connection()          # 原来是 init_db()

    if start_ts is not None:
        windows = [(start_ts, end_ts)]          # 只处理指定窗口
    else:
        days = [r[0] for r in conn.execute(f"""
            SELECT DISTINCT date(published_ts,'unixepoch','{SQL_TZ}')
            FROM news
            WHERE status='extracted' AND published_ts IS NOT NULL
            ORDER BY 1
        """)]
        windows = [day_bounds_ts(d) for d in days]

    exact = fuzzy = survived = 0
    for s, e in windows:
        exact += dedup_exact(conn, s, e)
        fuzzy += dedup_fuzzy(conn, s, e)
        survived += mark_deduped(conn, s, e)

    if start_ts is None:    # 只在全量模式下放行无发布时间的数据
        conn.execute("UPDATE news SET status='deduped' WHERE status='extracted' AND published_ts IS NULL")
        conn.commit()
    conn.close()
    return {"days": len(windows), "exact_dup": exact, "fuzzy_dup": fuzzy, "survived": survived}

if __name__ == "__main__":
    run()