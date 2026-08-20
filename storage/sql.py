# update_status.py
import sqlite3
from pathlib import Path

DB_PATH = Path("storage/news.db")

def query_analyzed_count():
        # 连接数据库
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # ✅ 关键：启用字典访问
    cursor = conn.cursor()
    """查询 analyzed 状态的记录数"""
    
    # 1. 查询记录数
    cursor.execute("""
        SELECT COUNT(*) as count 
        FROM news 
        WHERE status = 'analyzed'
    """)
    count = cursor.fetchone()['count']
    print(f"📊 数据库中 analyzed 状态的记录数: {count} 条")

      # 2. 查询具体记录
    cursor.execute("""
        SELECT * 
        FROM news 
        WHERE status = 'analyzed'
        ORDER BY id DESC
    """)
    rows = cursor.fetchall()
    
    conn.close()
    return count, rows

def update_status_by_extract():
    """将 extract_status='ok_trafilatura' 的记录 status 更新为 'extracted'"""
    
    # 连接数据库
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 先查看有多少条记录会被更新
    cursor.execute("""
        SELECT COUNT(*) 
        FROM news 
        WHERE extract_status = 'ok_trafilatura' 
        AND status != 'extracted'
    """)
    count = cursor.fetchone()[0]
    
    print(f"📊 找到 {count} 条 extract_status='ok_trafilatura' 的记录")
    
    if count == 0:
        print("✅ 没有需要更新的记录")
        conn.close()
        return
    
    # 执行更新
    cursor.execute("""
        UPDATE news 
        SET status = 'extracted' 
        WHERE extract_status = 'ok_trafilatura'
    """)
    
    updated = cursor.rowcount
    conn.commit()
    
    # 验证更新结果
    cursor.execute("""
        SELECT status, COUNT(*) 
        FROM news 
        WHERE extract_status = 'ok_trafilatura'
        GROUP BY status
    """)
    results = cursor.fetchall()
    
    print(f"\n✅ 已更新 {updated} 条记录")
    print("\n📊 更新后统计:")
    for status, count in results:
        print(f"  {status}: {count} 条")
    
    conn.close()

# 使用
if __name__ == "__main__":
    count, records = query_analyzed_count()
    
    print(f"\n📝 详细记录 (共 {count} 条):")
    print("-" * 100)
    
    for i, row in enumerate(records, 1):
        print(f"\n[{i}] ID: {row['id']}")
        print(f"    标题: {row['title']}")
        print(f"    来源: {row['source']}")
        print(f"    分类: {row['llm_category']}")
        print(f"    重要性: {row['importance']}")
        print(f"    摘要: {row['summary'][:100]}..." if row['summary'] else "    摘要: 无")
        print(f"    关键词: {row['keywords']}")
        print(f"    发布时间: {row['published']}")
        print("-" * 50)