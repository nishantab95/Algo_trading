from app.rag.indexer import RAGIndexer


class SearchIndex:
    def __init__(self, indexer: RAGIndexer) -> None: self.indexer=indexer
    def rebuild(self) -> dict: return self.indexer.reindex()
