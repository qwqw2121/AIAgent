# check_db.py (放在项目根目录运行)
import sqlite3
import sys
from pathlib import Path

# 假设你的 db.py 里定义了 DB_PATH，这里直接硬编码测试，请替换为你的真实路径
DB_PATH = Path("storage/news.db") # 👈 请修改为你实际的数据库路径

if not DB_PATH.exists():
    print(f"❌ 数据库文件不存在: {DB_PATH}")
    sys.exit(1)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row  # 让结果可以像字典一样通过列名访问
cursor = conn.cursor()

print("=== 1. 检查 news 表的前 3 条数据 ===")
cursor.execute("SELECT * FROM news LIMIT 3")
rows = cursor.fetchall()
if rows:
    print("列名:", rows[0].keys())
    for row in rows:
        print(dict(row))
else:
    print("⚠️ news 表为空！你需要先运行数据爬取/入库脚本。")

print("\n=== 2. 检查 daily_reports 表 ===")
cursor.execute("SELECT * FROM daily_reports LIMIT 3")
rows = cursor.fetchall()
if rows:
    print("列名:", rows[0].keys())
    for row in rows:
        print(dict(row))
else:
    print("⚠️ daily_reports 表为空！")

conn.close()