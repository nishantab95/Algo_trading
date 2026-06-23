from __future__ import annotations

from app.search.app_search import search_rows


class AppSearchService:
    def __init__(self,database,indexer=None) -> None: self.database,self.indexer=database,indexer
    def search(self,query:str,filters:dict|None=None,limit:int=30): return search_rows(self.database,query,filters,limit)
    def suggestions(self,prefix:str=""):
        rows=self.database.query("SELECT title,result_type,source_id FROM app_search_index WHERE LOWER(title) LIKE ? ORDER BY updated_at DESC LIMIT 12",(f"{prefix.lower()}%",))
        return rows
    def reindex(self): return self.indexer.reindex() if self.indexer else {"documents":0,"warnings":["No indexer configured"]}
