"""AgentCore — tools/local/knowledge.py
Knowledge tools: add files/dirs to the knowledge base and search it.
The agent uses these for RAG — the LLM never reads files directly.
"""
from __future__ import annotations

from typing import Any

from core.contracts import ToolResult
from memory.manager import MemoryManager
from tools.base import Tool


class KnowledgeAddTool(Tool):
    name = "knowledge_add"
    description = "Index a file (txt, md, pdf, code) into the knowledge base for later recall."
    parameters = {"type": "object",
                  "properties": {"path": {"type": "string",
                                          "description": "absolute or sandbox-relative file path"}},
                  "required": ["path"]}
    capability = "knowledge"
    idempotent = True

    def __init__(self, memory: MemoryManager) -> None:
        self.memory = memory

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        path = params.get("path", "")
        if not path:
            return ToolResult(ok=False, error="path required")
        result = await self.memory.add_knowledge(path)
        if not result.get("ok"):
            return ToolResult(ok=False, error=result.get("error", "ingest failed"))
        if result.get("skipped"):
            return ToolResult(ok=True, data={"skipped": True, "name": result.get("name")})
        return ToolResult(ok=True, data={"indexed": result.get("name"),
                                         "chunks": result.get("chunks", 0)})


class KnowledgeSearchTool(Tool):
    name = "knowledge_search"
    description = "Semantically search the indexed knowledge base (notes, PDFs, docs)."
    parameters = {"type": "object",
                  "properties": {"query": {"type": "string"},
                                 "top_k": {"type": "integer", "default": 5}},
                  "required": ["query"]}
    capability = "knowledge"
    idempotent = True

    def __init__(self, memory: MemoryManager) -> None:
        self.memory = memory

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        query = params.get("query", "")
        k = int(params.get("top_k", 5))
        hits = await self.memory.search_knowledge(query, top_k=k)
        return ToolResult(ok=True, data={"query": query, "hits": hits, "count": len(hits)})


def register_all(registry, memory: MemoryManager) -> None:
    registry.register(KnowledgeAddTool(memory))
    registry.register(KnowledgeSearchTool(memory))
