from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.rag.chunker import chunk_text
from app.rag.sources import database_sources, markdown_sources


class RAGIndexer:
    def __init__(self, database, project_root) -> None: self.database, self.project_root = database, project_root

    def reindex(self) -> dict:
        sources = [*markdown_sources(self.project_root), *database_sources(self.database)]
        now = datetime.now(timezone.utc).isoformat(); counts: dict[str, int] = {}; chunk_count = 0
        with self.database.transaction() as connection:
            for item in sources:
                content_hash = hashlib.sha256(item["content"].encode("utf-8")).hexdigest()
                connection.execute("""INSERT INTO rag_documents(source_type,source_id,title,content,metadata_json,content_hash,indexed_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source_type,source_id) DO UPDATE SET title=excluded.title,content=excluded.content,
                    metadata_json=excluded.metadata_json,content_hash=excluded.content_hash,indexed_at=excluded.indexed_at,updated_at=excluded.updated_at""",
                    (item["source_type"], item["source_id"], item["title"], item["content"], json.dumps(item["metadata"], default=str), content_hash, now, now))
                document_id = connection.execute("SELECT id FROM rag_documents WHERE source_type=? AND source_id=?", (item["source_type"], item["source_id"])).fetchone()[0]
                connection.execute("DELETE FROM rag_chunks WHERE document_id=?", (document_id,))
                for index, chunk in enumerate(chunk_text(item["content"])):
                    connection.execute("INSERT INTO rag_chunks(document_id,chunk_index,content,metadata_json,indexed_at) VALUES(?,?,?,?,?)", (document_id,index,chunk,json.dumps(item["metadata"],default=str),now)); chunk_count += 1
                summary = item["content"][:500]
                connection.execute("""INSERT INTO app_search_index(result_type,source_id,title,summary,keywords,metadata_json,updated_at)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(result_type,source_id) DO UPDATE SET title=excluded.title,summary=excluded.summary,
                    keywords=excluded.keywords,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at""",
                    (item["source_type"],item["source_id"],item["title"],summary,f"{item['title']} {item['content']}",json.dumps(item["metadata"],default=str),now))
                counts[item["source_type"]] = counts.get(item["source_type"], 0) + 1
        return {"documents": len(sources), "chunks": chunk_count, "by_source": counts, "indexed_at": now}

    def status(self) -> dict:
        rows=self.database.query("SELECT COUNT(*) count, MAX(indexed_at) last_indexed FROM rag_documents")
        chunks=self.database.query("SELECT COUNT(*) count FROM rag_chunks")[0]["count"]
        return {"documents": rows[0]["count"], "chunks": chunks, "last_indexed": rows[0]["last_indexed"]}
