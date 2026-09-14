# agent/graph.py  
# Retrieve → Generate 两节点图,单 agent,  

import os # 🌟 新增：导入 os 模块
from dotenv import load_dotenv
load_dotenv() 

from langgraph.graph import StateGraph, END
from typing import TypedDict
from storage.vectorstore import get_retriever
from langchain_openai import ChatOpenAI

class AgentState(TypedDict):
    question: str
    docs: list
    answer: str

# 🌟 核心修改区：从环境变量读取配置
API_KEY = os.getenv("LLM_API_KEY")
BASE_URL = os.getenv("LLM_BASE_URL")
MODEL_NAME = os.getenv("LLM_MODEL")

# 检查环境变量是否读取成功（可选，方便排错）
if not API_KEY or not BASE_URL or not MODEL_NAME:
    raise ValueError("❌ 错误：请在 .env 文件中配置 LLM_API_KEY, LLM_BASE_URL, LLM_MODEL")

# 🌟 核心修改区：将环境变量传入 ChatOpenAI
llm = ChatOpenAI(
    model=MODEL_NAME,
    openai_api_key=API_KEY,
    base_url=BASE_URL,  # 注意：如果你的 langchain-openai 版本较老，这里可能需要改成 openai_api_base=BASE_URL
)

retriever = get_retriever()

def retrieve(state: AgentState):
    docs = retriever.invoke(state["question"])
    return {"docs": docs}

def generate(state: AgentState):
    context = "\n\n".join(d.page_content for d in state["docs"])
    prompt = f"根据以下资讯回答问题，引用来源。\n\n资讯:\n{context}\n\n问题: {state['question']}"
    resp = llm.invoke(prompt)
    return {"answer": resp.content}


graph = StateGraph(AgentState)
graph.add_node("retrieve", retrieve)
graph.add_node("generate", generate)
graph.set_entry_point("retrieve")
graph.add_edge("retrieve", "generate")
graph.add_edge("generate", END)

app = graph.compile()

if __name__ == "__main__":
    result = app.invoke({"question": "最近有哪些大模型发布的新闻？"})
    print(result["answer"])