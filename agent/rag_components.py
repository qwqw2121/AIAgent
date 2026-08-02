from __future__ import annotations

import hashlib
import math
import pickle
import re
from pathlib import Path

from langchain_community.document_loaders import CSVLoader
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter


class HashEmbeddings(Embeddings):
    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_text(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_text(text)

    def _embed_text(self, text: str) -> list[float]:
        tokens = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", text.lower())
        vector = [0.0] * self.dimensions
        if not tokens:
            return vector

        for token in tokens:
            index = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % self.dimensions
            vector[index] += 1.0

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]


def load_news_documents(csv_path: Path) -> list[Document]:
    loader = CSVLoader(file_path=str(csv_path), encoding="utf-8")
    raw_docs = loader.load()
    normalized_docs: list[Document] = []

    for raw in raw_docs:
        fields = _parse_fields(raw.page_content)
        content = (
            f"标题: {fields.get('title', '')}\n"
            f"来源: {fields.get('source', '')}\n"
            f"发布时间: {fields.get('published_at', '')}\n"
            f"分类: {fields.get('category', '')}\n"
            f"摘要: {fields.get('summary', '')}"
        )
        metadata = {
            "title": fields.get("title", ""),
            "source": fields.get("source", ""),
            "published_at": fields.get("published_at", ""),
            "category": fields.get("category", ""),
            "url": fields.get("url", ""),
            "row": raw.metadata.get("row"),
        }
        normalized_docs.append(Document(page_content=content, metadata=metadata))

    return normalized_docs


def split_documents(documents: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=300,
        chunk_overlap=50,
        separators=["\n\n", "\n", "。", ".", " "],
    )
    chunks = splitter.split_documents(documents)
    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = index
    return chunks


def build_vector_store(chunks: list[Document]) -> InMemoryVectorStore:
    embedding = HashEmbeddings(dimensions=384)
    vector_store = InMemoryVectorStore(embedding=embedding)
    vector_store.add_documents(chunks)
    return vector_store


def save_vector_store(vector_store: InMemoryVectorStore, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as f:
        pickle.dump(vector_store, f)


def load_vector_store(input_path: Path) -> InMemoryVectorStore:
    with input_path.open("rb") as f:
        obj = pickle.load(f)
    if not isinstance(obj, InMemoryVectorStore):
        raise TypeError("Invalid vector store object loaded from disk.")
    return obj


def answer_with_context(question: str, retrieved_docs: list[Document]) -> str:
    if not retrieved_docs:
        return "未检索到相关内容，请尝试换一种问法。"

    lines = [f"问题：{question}", "", "基于检索到的资料，给出结论："]
    for i, doc in enumerate(retrieved_docs[:3], start=1):
        title = doc.metadata.get("title", "未知标题")
        source = doc.metadata.get("source", "未知来源")
        published_at = doc.metadata.get("published_at", "未知时间")
        category = doc.metadata.get("category", "未分类")
        url = doc.metadata.get("url", "")
        lines.append(
            f"{i}. [{category}] {title}（{source}，{published_at}）\n"
            f"   摘要片段：{doc.page_content[:180]}...\n"
            f"   链接：{url}"
        )
    lines.append("")
    lines.append("说明：当前最小系统使用哈希向量嵌入，回答为基于召回内容的提炼。后续可替换为高质量 Embedding+LLM 以提升效果。")
    return "\n".join(lines)


def _parse_fields(page_content: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in page_content.splitlines():
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        fields[key.strip()] = value.strip()
    return fields
