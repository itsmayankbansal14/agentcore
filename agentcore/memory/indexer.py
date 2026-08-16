"""AgentCore — memory/indexer.py
Knowledge ingestion: files (txt/md/pdf) → chunk → embed → store.
Lexical search via SQLite FTS5 (fallback LIKE); semantic search via VectorStore.

All LLM-touching methods are async (they're called from the async agent loop);
CLI/tests wrap them in asyncio.run().
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

import numpy as np
import structlog

from database.connection import Database
from database.models import KnowledgeChunk, KnowledgeDocument
from llm.manager import LLMManager
from memory.vector import VectorStore

log = structlog.get_logger("agentcore.memory.indexer")

CHUNK_CHARS = 2000
CHUNK_OVERLAP = 200

SUPPORTED_EXTS = {".txt", ".md", ".markdown", ".pdf", ".py", ".json", ".csv", ".html", ".log"}


class KnowledgeIndexer:
    def __init__(self, db: Database, llm: LLMManager, vector: VectorStore) -> None:
        self.db = db
        self.llm = llm
        self.vector = vector

    # ------------------------------------------------------------------ text extraction
    @staticmethod
    def extract_text(path: Path) -> str | None:
        ext = path.suffix.lower()
        if ext == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            except Exception as e:  # noqa: BLE001
                log.warning("pdf extract failed", path=str(path), error=str(e))
                return None
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

    @staticmethod
    def chunk(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return []
        if len(text) <= size:
            return [text]
        chunks: list[str] = []
        start = 0
        step = max(1, size - overlap)
        while start < len(text):
            chunk = text[start:start + size]
            if chunk:
                chunks.append(chunk)
            start += step
        return chunks

    # ------------------------------------------------------------------ ingestion
    async def ingest_file(self, path: str | Path, mime: str = "") -> dict:
        p = Path(path).resolve()
        if not p.exists() or not p.is_file():
            return {"ok": False, "error": f"not a file: {p}"}
        text = self.extract_text(p)
        if not text:
            return {"ok": False, "error": f"could not extract text from {p.suffix}"}

        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        with self.db.session() as s:
            existing = s.query(KnowledgeDocument).filter_by(sha256=sha).first()
            if existing:
                return {"ok": True, "skipped": True, "doc": existing.id,
                        "name": p.name, "reason": "unchanged (same sha256)"}
            doc = KnowledgeDocument(name=p.name, path=str(p), mime=mime or p.suffix,
                                    sha256=sha, size=p.stat().st_size)
            s.add(doc)
            s.flush()
            chunks = self.chunk(text)
            embeddings = await self._embed_batch(chunks) if chunks else []
            for i, (chunk, vec) in enumerate(zip(chunks, embeddings)):
                s.add(KnowledgeChunk(doc_id=doc.id, chunk_index=i, content=chunk,
                                     embedding=self._pack(vec) if vec else None))
            s.commit()
            doc_id = doc.id
            chunk_ids = [c.id for c in s.query(KnowledgeChunk).filter_by(doc_id=doc_id).all()]
        # mirror into vector store + FTS
        for cid, chunk, vec in zip(chunk_ids, chunks, embeddings):
            if vec:
                self.vector.add(cid, vec, metadata={"doc": p.name})
        self._sync_fts()
        return {"ok": True, "doc": doc_id, "name": p.name, "chunks": len(chunks),
                "chars": len(text)}

    async def ingest_dir(self, path: str | Path, max_files: int = 50) -> dict:
        root = Path(path).resolve()
        results = {"ok": True, "root": str(root), "indexed": [], "skipped": [], "errors": []}
        if not root.is_dir():
            return {"ok": False, "error": f"not a dir: {root}"}
        for p in sorted(root.rglob("*")):
            if len(results["indexed"]) >= max_files:
                break
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                r = await self.ingest_file(p)
                if r.get("ok") and r.get("skipped"):
                    results["skipped"].append(p.name)
                elif r.get("ok"):
                    results["indexed"].append(f"{p.name} ({r['chunks']} chunks)")
                else:
                    results["errors"].append(f"{p.name}: {r.get('error')}")
        results["count"] = len(results["indexed"])
        return results

    # ------------------------------------------------------------------ embeddings
    async def _embed_batch(self, chunks: list[str]) -> list[list[float] | None]:
        out: list[list[float] | None] = []
        for c in chunks:
            try:
                out.append(await self.llm.embed(c))
            except Exception as e:  # noqa: BLE001
                log.warning("embed failed, lexical only", error=str(e))
                out.append(None)
        return out

    @staticmethod
    def _pack(vec: list[float]) -> bytes:
        return np.asarray(vec, dtype=np.float32).tobytes()

    # ------------------------------------------------------------------ search
    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        results: dict[int, float] = {}
        lexical = self._lexical_search(query, top_k=top_k)
        for chunk_id, score in lexical:
            results[chunk_id] = max(results.get(chunk_id, 0.0), score)
        try:
            qvec = await self.llm.embed(query)
            for score, item in self.vector.search(qvec, top_k=top_k, min_score=0.0):
                results[item.id] = max(results.get(item.id, 0.0), score)
        except Exception:  # noqa: BLE001
            pass
        top_ids = [cid for cid, _ in sorted(results.items(), key=lambda kv: kv[1],
                                            reverse=True)[:top_k]]
        out: list[dict] = []
        with self.db.session() as s:
            for cid in top_ids:
                chunk = s.get(KnowledgeChunk, cid)
                if chunk:
                    doc = s.get(KnowledgeDocument, chunk.doc_id)
                    out.append({"chunk_id": cid, "doc": doc.name if doc else "",
                                "content": chunk.content[:600],
                                "score": round(results[cid], 3)})
        return out

    def _lexical_search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        from sqlalchemy import text, or_
        with self.db.session() as s:
            try:
                q = " ".join(f'"{w}"' for w in query.split() if w)
                rows = s.execute(
                    text("SELECT rowid, bm25(knowledge_fts) AS rank FROM knowledge_fts "
                         "WHERE knowledge_fts MATCH :q ORDER BY rank LIMIT :k"),
                    {"q": q, "k": top_k}).all()
                if rows:
                    return [(int(r[0]), float(-r[1])) for r in rows]
            except Exception:  # noqa: BLE001 — FTS failure → LIKE fallback
                pass
            # per-word OR LIKE (phrase LIKE is too strict for free text)
            words = [w for w in query.split() if w][:6]
            if not words:
                return []
            q = s.query(KnowledgeChunk)
            q = q.filter(or_(*[KnowledgeChunk.content.ilike(f"%{w}%") for w in words]))
            rows = q.limit(top_k).all()
            return [(r.id, 1.0) for r in rows]

    def _sync_fts(self) -> None:
        try:
            with self.db.engine.begin() as conn:
                conn.exec_driver_sql(
                    "INSERT OR IGNORE INTO knowledge_fts(rowid, content) "
                    "SELECT id, content FROM knowledge_chunks")
        except Exception:  # noqa: BLE001
            pass
