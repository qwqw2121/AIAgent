from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.rag_components import answer_with_context, load_vector_store

VECTOR_PATH = PROJECT_ROOT / "storage" / "vector_store.pkl"


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask a question against local AI news RAG index.")
    parser.add_argument("question", type=str, help="Question to ask.")
    parser.add_argument("--top-k", type=int, default=4, help="How many chunks to retrieve.")
    args = parser.parse_args()

    vector_store = load_vector_store(VECTOR_PATH)
    retriever = vector_store.as_retriever(search_kwargs={"k": args.top_k})
    docs = retriever.invoke(args.question)
    answer = answer_with_context(args.question, docs)

    print(answer)


if __name__ == "__main__":
    main()
