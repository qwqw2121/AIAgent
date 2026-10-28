# check_vectorstore.py (放在项目根目录运行)
import sys
import os
from pathlib import Path

# 🌟 关键修复 1：强制禁用 GPU，避免 MX150 兼容性导致的底层崩溃
os.environ["CUDA_VISIBLE_DEVICES"] = "" 

ROOT_DIR = Path(__file__).parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from storage.vectorstore import get_retriever

print("=== 检查向量库检索 ===")
retriever = get_retriever()

# 🌟 关键修复 2：retriever.invoke 只接受 query 字符串或 {"query": "..."} 字典
# 如果需要限制数量，应该在 get_retriever() 内部设置 search_kwargs={"k": 3}
try:
    docs = retriever.invoke("LLM")
    
    if not docs:
        print("❌ 向量库为空！没有检索到任何数据。")
        print("👉 请检查你的数据入库脚本，确保 embed 成功 (status != 'embed_failed')。")
    else:
        print(f"✅ 成功检索到 {len(docs)} 条数据！")
        print("\n--- 第一条数据的 Metadata Keys ---")
        print(list(docs[0].metadata.keys()))
        print("\n--- 第一条数据的 Metadata Content ---")
        print(docs[0].metadata)
except Exception as e:
    print(f"❌ 检索失败: {e}")