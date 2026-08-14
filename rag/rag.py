# rag/rag.py

import os

from openai import OpenAI
from pathlib import Path
from retriever import retrieve
from dotenv import load_dotenv


from prompt import (
    SYSTEM_PROMPT,
    build_prompt
)

# 设置路径
BASE_DIR = Path(__file__).parent.parent

load_dotenv()


# ============================================================
# LLM 配置
# ============================================================

API_KEY = os.getenv(
    "LLM_API_KEY"
)

BASE_URL = os.getenv(
    "LLM_BASE_URL"
)

MODEL_NAME = os.getenv(
    "LLM_MODEL"
)


# ============================================================
# Client
# ============================================================

client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL
)


# ============================================================
# RAG
# ============================================================

def ask(query):

    # --------------------------------------------------------
    # 1. Retrieval
    # --------------------------------------------------------

    documents = retrieve(
        query,
        top_k=5
    )

    if not documents:

        return "没有找到相关的新闻资料。"

    # --------------------------------------------------------
    # 2. 构造 Prompt
    # --------------------------------------------------------

    prompt = build_prompt(
        query,
        documents
    )

    # --------------------------------------------------------
    # 3. LLM
    # --------------------------------------------------------

    response = client.chat.completions.create(
        model=MODEL_NAME,

        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },

            {
                "role": "user",
                "content": prompt
            }
        ],

        temperature=0.2
    )

    answer = (
        response
        .choices[0]
        .message
        .content
    )

    return answer


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":

    print("=" * 60)
    print("AI News RAG")
    print("=" * 60)

    while True:

        query = input(
            "\n请输入问题（输入 q 退出）："
        )

        if query.lower() == "q":
            break

        try:

            answer = ask(query)

            print()
            print("回答：")
            print(answer)

        except Exception as e:

            print(
                f"❌ RAG失败：{e}"
            )