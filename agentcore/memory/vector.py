"""AgentCore — memory/vector.py
Vector store adapter. MVP: numpy cosine similarity over embeddings kept in
memory and mirrored to SQLite (chunks.embedding BLOB). Swap-in for Chroma /
Qdrant / sqlite-vec later behind this same interface.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np


@dataclass
class VectorItem:
    id: int
    vector: list[float]
    metadata: dict = field(default_factory=dict)


class VectorStore:
    """In-process store with numpy cosine search. `load()`/`save()` to SQLite."""

    def __init__(self) -> None:
        self._items: dict[int, VectorItem] = {}

    # -- lifecycle ----------------------------------------------------------
    def load(self, rows: list[tuple]) -> None:
        """rows: [(id, embedding_bytes_or_none, metadata_json)]"""
        self._items.clear()
        for rid, emb_bytes, meta_json in rows:
            if not emb_bytes:
                continue
            try:
                vec = np.frombuffer(emb_bytes, dtype=np.float32)
                self._items[rid] = VectorItem(id=rid, vector=vec.tolist(),
                                              metadata=json.loads(meta_json or "{}"))
            except Exception:
                continue

    def add(self, item_id: int, vector: list[float], metadata: dict | None = None) -> None:
        self._items[item_id] = VectorItem(id=item_id, vector=vector, metadata=metadata or {})

    def remove(self, item_id: int) -> None:
        self._items.pop(item_id, None)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)

    # -- search ------------------------------------------------------------
    def search(self, query_vector: list[float], top_k: int = 5,
               min_score: float = 0.0) -> list[tuple[float, VectorItem]]:
        if not self._items or not query_vector:
            return []
        q = np.asarray(query_vector, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []
        q = q / q_norm
        scored: list[tuple[float, VectorItem]] = []
        for item in self._items.values():
            v = np.asarray(item.vector, dtype=np.float32)
            norm = np.linalg.norm(v)
            if norm == 0:
                continue
            score = float(np.dot(q, v / norm))
            if score >= min_score:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]

    def similarity(self, a: list[float], b: list[float]) -> float:
        if not a or not b:
            return 0.0
        va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
        na, nb = np.linalg.norm(va), np.linalg.norm(vb)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(va / na, vb / nb))
