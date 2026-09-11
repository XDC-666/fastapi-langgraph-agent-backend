"""Knowledge-base isolation, validation, and replacement regressions."""
import inspect

import pytest

from app.config import settings
from app.services import knowledge_service
from app.services.knowledge_service import add_document, retrieve_for_query
from tests.test_chat import register_and_login


class FakeVectorStore:
    def __init__(self):
        self.search_calls = []
        self.delete_calls = []
        self.add_calls = []

    def similarity_search(self, query, k, filter):
        self.search_calls.append((query, k, filter))
        return []

    def delete(self, **kwargs):
        self.delete_calls.append(kwargs)

    def add_texts(self, chunks, metadatas, ids):
        self.add_calls.append((list(chunks), list(metadatas), list(ids)))


def test_retrieve_for_query_requires_owner_id():
    parameter = inspect.signature(retrieve_for_query).parameters["owner_id"]
    assert parameter.default is inspect.Parameter.empty



def test_retrieve_rejects_explicit_missing_owner():
    with pytest.raises(ValueError, match="owner_id"):
        retrieve_for_query("private", owner_id=None)  # type: ignore[arg-type]

def test_retrieve_for_query_always_filters_owner(monkeypatch):
    store = FakeVectorStore()
    monkeypatch.setattr(knowledge_service, "get_vector_store", lambda: store)

    assert retrieve_for_query("private", owner_id=7, k=4) == ""
    assert store.search_calls == [("private", 4, {"owner_id": 7})]


def test_add_document_replaces_old_chunks_for_same_owner_and_filename(monkeypatch):
    store = FakeVectorStore()
    monkeypatch.setattr(knowledge_service, "get_vector_store", lambda: store)
    monkeypatch.setattr(knowledge_service.splitter, "split_text", lambda text: ["one", "two"])

    count = add_document("guide.txt", b"fresh body", owner_id=7)

    assert count == 2
    assert store.delete_calls == [
        {
            "where": {
                "$and": [
                    {"owner_id": {"$eq": 7}},
                    {"source": {"$eq": "guide.txt"}},
                ]
            }
        }
    ]
    assert store.add_calls[0][2] == ["7-guide.txt-0", "7-guide.txt-1"]


def test_add_document_rejects_text_that_parses_empty():
    with pytest.raises(ValueError, match="为空"):
        add_document("empty.txt", b"   \n\t", owner_id=1)


def test_upload_rejects_oversize_before_vectorization(client, monkeypatch):
    token = register_and_login(client, username="uploadbig")
    monkeypatch.setattr(settings, "MAX_KNOWLEDGE_UPLOAD_BYTES", 4)

    r = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("notes.txt", b"12345", "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 413


def test_upload_rejects_empty_file(client):
    token = register_and_login(client, username="uploadempty")
    r = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_upload_rejects_unsupported_extension(client):
    token = register_and_login(client, username="uploadext")
    r = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("payload.exe", b"abc", "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_knowledge_ask_bounds_k(client):
    token = register_and_login(client, username="askbounds")
    headers = {"Authorization": f"Bearer {token}"}

    assert client.post(
        "/api/v1/knowledge/ask", json={"query": "x", "k": 0}, headers=headers
    ).status_code == 422
    assert client.post(
        "/api/v1/knowledge/ask",
        json={"query": "x", "k": settings.MAX_KNOWLEDGE_K + 1},
        headers=headers,
    ).status_code == 422
