import json

import pytest
from fastapi.testclient import TestClient

import data_spear.api.main as main
from data_spear.config import settings
from data_spear.rag import RAGAnswer

HITS = [{"id": "t:1", "score": 0.9, "fields": {"chunk_text": "alpha"}}]


class FakeRAG:
    def answer(self, prompt, top_k=None, allow_destructive=False):
        return RAGAnswer(answer=f"ok:{prompt}", hits=list(HITS))

    def answer_events(self, prompt, top_k=None, allow_destructive=False):
        yield {"type": "retrieval", "count": 1}
        yield {"type": "final", "answer": "streamed", "hits": list(HITS)}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "_rag", FakeRAG())
    return TestClient(main.app)


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_query_requires_prompt(client):
    r = client.post("/query", json={"prompt": "   "})
    assert r.status_code == 400


def test_query_happy_path(client):
    r = client.post("/query", json={"prompt": "hi"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "ok:hi"
    assert body["hits"] == [{"id": "t:1", "score": 0.9, "text": "alpha"}]


def test_query_stream_emits_sse_events(client):
    r = client.post("/query/stream", json={"prompt": "hi"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = [
        json.loads(line[len("data: "):])
        for line in r.text.splitlines()
        if line.startswith("data: ")
    ]
    assert events[0] == {"type": "retrieval", "count": 1}
    final = events[-1]
    assert final["type"] == "final"
    assert final["answer"] == "streamed"
    assert final["hits"] == [{"id": "t:1", "score": 0.9, "text": "alpha"}]


def test_ingest_with_no_sources_is_400(client):
    r = client.post("/ingest")
    assert r.status_code == 400
    assert "No sources configured" in r.json()["detail"]


def test_connect_rejects_unreachable_db(client):
    r = client.post(
        "/connect",
        json={"dsn": "postgresql://nouser@127.0.0.1:1/none?connect_timeout=1"},
    )
    assert r.status_code == 400
    assert "could not connect" in r.json()["detail"]


class TestAuth:
    @pytest.fixture
    def secured(self, client, monkeypatch):
        monkeypatch.setattr(settings, "api_token", "s3cret")
        return client

    def test_missing_token_rejected(self, secured):
        assert secured.post("/query", json={"prompt": "hi"}).status_code == 401

    def test_wrong_token_rejected(self, secured):
        r = secured.post(
            "/query", json={"prompt": "hi"},
            headers={"Authorization": "Bearer wrong"},
        )
        assert r.status_code == 401

    def test_correct_token_accepted(self, secured):
        r = secured.post(
            "/query", json={"prompt": "hi"},
            headers={"Authorization": "Bearer s3cret"},
        )
        assert r.status_code == 200

    def test_healthz_stays_open(self, secured):
        assert secured.get("/healthz").status_code == 200
