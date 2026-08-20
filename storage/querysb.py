import sqlite3

conn = sqlite3.connect("storage/news.db")
cursor = conn.cursor()

cursor.execute("""
SELECT id, title, published, status, is_duplicate
FROM news
ORDER BY id
LIMIT 10
""")

for row in cursor.fetchall():
    print(row)

conn.close()