"""
⑤ LLM结构化分析
只处理第一轮去重后剩下的、状态为 extracted 的记录,
分析完写回数据库并置 status='analyzed'。
"""
import json
import os
import time
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Sequence, Union

try:
    from openai import OpenAI
except ImportError as e:
    raise ImportError("缺少依赖 openai，请先安装：pip install openai") from e
from dotenv import load_dotenv

# 设置路径
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "storage/news.db"

load_dotenv()
GLM_API_KEY = os.getenv("GLM_API_KEY")
if not GLM_API_KEY:
    raise ValueError("❌ GLM_API_KEY 未在 .env 中设置！")

client = OpenAI(
    api_key=GLM_API_KEY,
    base_url="https://open.bigmodel.cn/api/paas/v4",
)

MAX_CONTENT_CHARS = 3000


def get_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_by_status(conn: sqlite3.Connection, status: Union[str, Sequence[str]], limit: int = None) -> List[Dict[str, Any]]:
    """
    获取指定状态的记录，默认排除 is_duplicate=1 的重复记录。
    支持单个状态或多个状态（如 ('extracted', 'analyze_failed')）。
    """
    cursor = conn.cursor()

    statuses = [status] if isinstance(status, str) else list(status)
    placeholders = ', '.join(['?'] * len(statuses))

    query = f"""
        SELECT id, url, title, content, summary, source, 
               published, published_ts, crawl_time, status
        FROM news 
        WHERE status IN ({placeholders}) AND is_duplicate = 0
        ORDER BY published_ts DESC
    """

    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query, tuple(statuses))

    columns = [description[0] for description in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return rows


def update_fields(conn: sqlite3.Connection, news_id: int, fields: Dict[str, Any]) -> bool:
    """
    更新新闻记录的指定字段
    """
    if not fields:
        return False
    
    # keywords如果是列表，转为JSON字符串
    if 'keywords' in fields and isinstance(fields['keywords'], list):
        fields['keywords'] = json.dumps(fields['keywords'], ensure_ascii=False)
    
    set_clause = ', '.join([f"{key} = ?" for key in fields.keys()])
    values = list(fields.values())
    values.append(news_id)
    
    try:
        conn.execute(f"UPDATE news SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return True
    except Exception as e:
        print(f"更新失败: {e}")
        return False


def analyze_news(title: str, content: str) -> dict:
    """
    调用LLM分析新闻
    """
    # 如果content为空，使用title作为备用
    if not content or len(content.strip()) < 10:
        content = title
    
    content = content[:MAX_CONTENT_CHARS]
    
    prompt = f"""
            你是AI资讯分析专家。
            分析下面新闻：
            标题:
            {title}
            正文:
            {content}
            输出JSON:
            {{
            "summary": "",
            "category": "",
            "keywords": [],
            "importance": 1
            }}
            要求：
            - summary控制在80-120字，突出新闻的核心事实和影响
            - category从以下选择: 大模型发布|融资并购|政策监管|研究论文|产品发布|行业观点|其他
            - keywords 3-5个
            - importance范围1-10，10代表行业级重大事件(如头部公司发布新一代模型)，1代表边角小消息
            - summary必须是你对新闻事件的概括性转述，不能是原文的同义词替换或句式微调
            - 严禁逐句改写原文表述，要用你自己的语言重新组织信息
            """
    
    response = client.chat.completions.create(
        model="glm-4.7-flash",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    return json.loads(response.choices[0].message.content)


def run(sleep_sec: float = 0.5, max_retry: int = 2, limit: int = None):
    """
    运行LLM结构化分析
    
    Args:
        sleep_sec: 每次请求间隔秒数
        max_retry: 最大重试次数
        limit: 限制处理数量，None表示全部
    """
    conn = get_connection()
    
    try:
        # 获取待分析的记录，包括之前分析失败但可重试的新闻
        rows = fetch_by_status(conn, status=("extracted", "analyze_failed"), limit=limit)

        if not rows:
            print("✅ 没有待分析或可重试的新闻")
            return

        print(f"📊 待LLM分析/重试: {len(rows)} 条")
        
        success_count = 0
        fail_count = 0
        
        for i, row in enumerate(rows, 1):
            print(f"\n[{i}/{len(rows)}] 处理: {row['title'][:40]}...")
            
            # 准备内容：优先使用content，如果没有则用summary
            content = row.get("content") or row.get("summary") or ""
            
            result = None
            for attempt in range(max_retry + 1):
                try:
                    result = analyze_news(row["title"], content)
                    break
                except Exception as e:
                    print(f"  ⚠️ 第{attempt + 1}次调用失败: {e}")
                    if attempt < max_retry:
                        time.sleep(2)
            
            if result is None:
                print(f"  ❌ 分析失败")
                update_fields(conn, row["id"], {"status": "analyze_failed"})
                fail_count += 1
                continue
            
            # 更新数据库（使用正确的字段名）
            success = update_fields(conn, row["id"], {
                "summary": result.get("summary", ""),      # 使用 summary 而不是 llm_summary
                "llm_category": result.get("category", ""),
                "keywords": result.get("keywords", []),
                "importance": result.get("importance", 1),
                "status": "analyzed",
            })
            
            if success:
                success_count += 1
                print(f"  ✅ 分析完成: {result.get('category', 'N/A')} | 重要性: {result.get('importance', 1)}")
                print(f"  📝 摘要: {result.get('summary', '')[:50]}...")
            else:
                fail_count += 1
                print(f"  ❌ 更新数据库失败")
            
            # 避免API限流
            if i < len(rows):
                time.sleep(sleep_sec)
        
        # 统计结果
        print(f"\n📊 分析完成统计:")
        print(f"  ✅ 成功: {success_count}")
        print(f"  ❌ 失败: {fail_count}")
        print(f"  📝 总计: {len(rows)}")
        
    finally:
        conn.close()


def get_analysis_stats():
    """
    查看分析统计信息
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # 各状态统计
    cursor.execute("""
        SELECT status, COUNT(*) as count 
        FROM news 
        WHERE is_duplicate = 0
        GROUP BY status
    """)
    stats = {row[0]: row[1] for row in cursor.fetchall()}
    
    print("\n📊 数据库统计:")
    print(f"  待采集 (raw): {stats.get('raw', 0)}")
    print(f"  已提取 (extracted): {stats.get('extracted', 0)}")
    print(f"  已分析 (analyzed): {stats.get('analyzed', 0)}")
    print(f"  分析失败 (analyze_failed): {stats.get('analyze_failed', 0)}")
    print(f"  总计: {sum(stats.values())}")
    
    conn.close()
    return stats


if __name__ == "__main__":
    # 查看统计
    get_analysis_stats()
    
    # 运行分析（可以调整参数）
    # run(sleep_sec=0.5, max_retry=2)     # 处理所有
    # run(limit=10, sleep_sec=0.3)         # 只处理10条
    run(sleep_sec=0.3, max_retry=3)