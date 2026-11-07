import os
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

EMBED_MODEL = os.getenv("LLM_EMBEDING", "text-embedding-v3")
REQUEST_TIMEOUT = 30

_online_client = None


def get_online_client():
    global _online_client
    if _online_client is None:
        from openai import OpenAI
        api_key = os.getenv("LLM_API_KEY")
        base_url = os.getenv("LLM_BASE_URL")
        if not api_key or not base_url:
            raise ValueError("❌ 需要在 .env 中配置 LLM_API_KEY 和 LLM_BASE_URL")
        _online_client = OpenAI(
            api_key=api_key, base_url=base_url,
            timeout=REQUEST_TIMEOUT, max_retries=0,
        )
    return _online_client


def get_embedding(text: str) -> Optional[list]:
    try:
        resp = get_online_client().embeddings.create(model=EMBED_MODEL, input=text)
        return resp.data[0].embedding
    except Exception as e:
        print(f"❌ Embedding 生成失败: {e}", flush=True)
        return None


if __name__ == "__main__":
    vector = get_embedding("人工智能正在快速发展")
    print(vector)
    print(len(vector))
    print(vector[:5])