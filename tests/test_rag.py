from data_spear.rag import RAG, RAGAnswer

HITS = [
    {"id": "t:1", "score": 0.9, "fields": {"chunk_text": "alpha"}},
    {"id": "t:2", "score": 0.8, "fields": {"chunk_text": "beta"}},
]


class FakeStore:
    def __init__(self):
        self.calls = []

    def search(self, prompt, top_k=None):
        self.calls.append((prompt, top_k))
        return list(HITS)


class FakeLLM:
    def answer(self, prompt, hits, allow_destructive):
        return f"answer({prompt},{len(hits)},{allow_destructive})"

    def answer_events(self, prompt, hits, allow_destructive):
        yield {"type": "thinking", "text": "hm"}
        yield {"type": "final", "answer": "done"}


def test_answer_wires_store_and_llm():
    store = FakeStore()
    rag = RAG(store=store, llm=FakeLLM())
    result = rag.answer("q", top_k=3, allow_destructive=True)
    assert isinstance(result, RAGAnswer)
    assert result.answer == "answer(q,2,True)"
    assert result.hits == HITS
    assert store.calls == [("q", 3)]


def test_answer_events_attaches_hits_to_final():
    rag = RAG(store=FakeStore(), llm=FakeLLM())
    events = list(rag.answer_events("q"))
    assert events[0] == {"type": "retrieval", "count": 2}
    assert events[1] == {"type": "thinking", "text": "hm"}
    final = events[-1]
    assert final["type"] == "final"
    assert final["answer"] == "done"
    assert final["hits"] == HITS
