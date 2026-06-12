#RAG: Retrieval-Augmented Generation for Data-Spear
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from llm import LLM
from vector_store import VectorStore


@dataclass
class RAGAnswer:
    answer: str
    hits: list[dict]


class RAG:
    def __init__(self, store: VectorStore | None = None, llm: LLM | None = None) -> None:
        self.store = store or VectorStore()
        self.llm = llm or LLM()

    def answer(
        self,
        prompt: str,
        top_k: int | None = None,
        allow_destructive: bool = False,
    ) -> RAGAnswer:
        hits = self.store.search(prompt, top_k=top_k)
        text = self.llm.answer(prompt, hits, allow_destructive)
        return RAGAnswer(answer=text, hits=hits)

    def answer_events(
        self,
        prompt: str,
        top_k: int | None = None,
        allow_destructive: bool = False,
    ) -> Iterator[dict]:
        # Like `answer`, but yields agent progress events; the `final` event carries hits.
        hits = self.store.search(prompt, top_k=top_k)
        yield {"type": "retrieval", "count": len(hits)}
        for evt in self.llm.answer_events(prompt, hits, allow_destructive):
            if evt["type"] == "final":
                evt = {**evt, "hits": hits}
            yield evt
