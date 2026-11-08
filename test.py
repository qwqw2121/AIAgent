from retrieval.vector_search import vector_search
for r in vector_search("具身智能", 5):
    print(r["news_id"], r["url"])