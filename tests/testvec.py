import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from embedding.vector_store import get_vector_store

store = get_vector_store()

result = store.collection.get(
    limit=5,
    include=["metadatas"],
)

for metadata in result["metadatas"]:
    print(metadata)