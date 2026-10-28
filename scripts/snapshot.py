import sqlite3
src = sqlite3.connect("/app/storage/news.db")
dst = sqlite3.connect("/app/storage/news.snapshot.db")
src.backup(dst)
dst.close(); src.close()
print("snapshot ok")