# rag/prompt.py


SYSTEM_PROMPT = """
你是一个 AI 资讯分析助手。

你的任务是根据提供的新闻资料回答用户问题。

要求：

1. 只能根据提供的新闻资料回答。
2. 不要编造新闻中没有的信息。
3. 如果资料不足，明确告诉用户。
4. 回答时尽量综合多个新闻来源。
5. 如果不同新闻存在不同观点，需要明确说明。
6. 回答简洁、准确、有条理。
"""


def build_prompt(
    query,
    documents
):

    context_parts = []

    for i, doc in enumerate(
        documents,
        start=1
    ):

        context_parts.append(
            f"""
[新闻{i}]
news_id: {doc['news_id']}
相似度: {doc['similarity']:.4f}

{doc['text']}
"""
        )

    context = "\n".join(
        context_parts
    )

    return f"""
用户问题：

{query}


新闻资料：

{context}


请根据以上新闻资料回答用户问题。
"""