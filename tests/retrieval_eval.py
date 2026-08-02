from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.rag_components import load_vector_store

VECTOR_PATH = PROJECT_ROOT / "storage" / "vector_store.pkl"

EVAL_SET = [
    ("最近哪些模型在代码生成上表现突出？", ["codegen", "编码", "编程", "模型"]),
    ("多模态大模型在医疗影像方向有哪些进展？", ["医疗", "影像", "多模态"]),
    ("有哪些文章讨论了Agent的记忆与规划能力？", ["agent", "规划", "记忆"]),
    ("检索增强生成RAG优化有哪些新方法？", ["rag", "检索", "增强"]),
    ("视频生成模型最近有什么代表性工作？", ["视频", "生成"]),
    ("开源小模型效率优化方面有什么新闻？", ["开源", "小模型", "效率"]),
    ("关于AI安全和对齐，有哪些值得关注的内容？", ["安全", "对齐", "风险"]),
    ("数据库+向量检索一体化有哪些实践？", ["向量", "数据库", "检索"]),
    ("语音大模型最近有哪些方向？", ["语音", "音频"]),
    ("机器人结合大模型有哪些最新进展？", ["机器人", "具身", "控制"]),
]


def main() -> None:
    vector_store = load_vector_store(VECTOR_PATH)
    retriever = vector_store.as_retriever(search_kwargs={"k": 3})

    hits = 0
    for index, (question, keywords) in enumerate(EVAL_SET, start=1):
        docs = retriever.invoke(question)
        merged = " ".join(doc.page_content.lower() for doc in docs)
        matched = any(keyword.lower() in merged for keyword in keywords)
        if matched:
            hits += 1

        print(f"[Q{index}] {question}")
        print(f"Matched: {'YES' if matched else 'NO'}")
        for i, doc in enumerate(docs, start=1):
            print(f"  {i}. {doc.metadata.get('title', 'N/A')} | {doc.metadata.get('category', 'N/A')}")
        print("-" * 80)

    print(f"Hit@3: {hits}/{len(EVAL_SET)} = {hits / len(EVAL_SET):.2%}")
    print("请结合输出进行人工判断：如果召回不准，记录误召回样本，为后续Embedding/切块调优做基线。")


if __name__ == "__main__":
    main()
