from __future__ import annotations

import json
import re


class RAGRetriever:
    def __init__(self, database) -> None: self.database=database

    def search(self, query: str, source_type: str | None = None, limit: int = 10) -> list[dict]:
        tokens=[token for token in re.findall(r"[A-Za-z0-9_]+", query.lower()) if len(token)>1]
        if not tokens: return []
        where=" OR ".join("LOWER(d.title || ' ' || c.content) LIKE ?" for _ in tokens)
        params=[f"%{token}%" for token in tokens]
        if source_type: where=f"({where}) AND d.source_type=?"; params.append(source_type)
        rows=self.database.query(f"""SELECT d.source_type,d.source_id,d.title,c.content,d.metadata_json
            FROM rag_chunks c JOIN rag_documents d ON d.id=c.document_id WHERE {where} LIMIT ?""", (*params, max(limit*50,200)))
        results=[]
        for row in rows:
            haystack=f"{row['title']} {row['content']}".lower(); hits=sum(token in haystack for token in tokens); score=hits/len(tokens)
            source=row["source_type"].lower()
            if any(token in {source,source.replace("_definition",""),source.replace("_trade","")} or token.rstrip("s")==source for token in tokens): score += .75
            results.append({"source_type":row["source_type"],"source_id":row["source_id"],"title":row["title"],
                            "snippet":row["content"][:600],"score":round(score,4),"metadata":json.loads(row["metadata_json"] or "{}"),
                            "action_target":f"/{row['source_type']}/{row['source_id']}"})
        return sorted(results,key=lambda item:item["score"],reverse=True)[:limit]
