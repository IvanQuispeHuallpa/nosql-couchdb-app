import json
import os

import pytest
import requests
import responses

from app.couch import DEMO_TASKS, CouchStore, NotFound
from app.main import create_app

BASE = "http://couch.test"


class MemoryStore:
    """Doble en memoria con la misma interfaz que CouchStore (pruebas unitarias de la API)."""

    def __init__(self):
        self.docs, self.n = {}, 0

    def ensure_db(self): pass
    def ping(self): return True

    def create(self, title, tags):
        self.n += 1
        doc = {"_id": f"id{self.n}", "_rev": "1-x", "type": "task", "title": title, "status": "todo",
               "tags": tags, "created_at": f"2026-01-01T00:00:0{self.n}"}
        self.docs[doc["_id"]] = doc
        return doc

    def get(self, i):
        if i not in self.docs:
            raise NotFound(i)
        return self.docs[i]

    def update(self, i, changes):
        self.get(i).update(changes)
        return self.docs[i]

    def delete(self, i):
        self.get(i)
        del self.docs[i]

    def find(self, selector, limit=200):
        out = []
        for d in self.docs.values():
            if d["type"] != selector["type"]:
                continue
            if "status" in selector and d["status"] != selector["status"]:
                continue
            if "tags" in selector and selector["tags"]["$elemMatch"]["$eq"] not in d["tags"]:
                continue
            out.append(d)
        return out


@pytest.fixture
def client():
    return create_app(store=MemoryStore()).test_client()


def test_health(client):
    assert client.get("/health").get_json()["status"] == "ok"


def test_task_lifecycle(client):
    created = client.post("/api/tasks", json={"title": " Aprender CouchDB ", "tags": ["Db", " "]})
    assert created.status_code == 201
    task = created.get_json()
    assert task["title"] == "Aprender CouchDB" and task["tags"] == ["db"] and task["status"] == "todo"

    moved = client.patch(f"/api/tasks/{task['_id']}", json={"status": "done"})
    assert moved.get_json()["status"] == "done"
    assert client.get("/api/stats").get_json() == {"total": 1, "todo": 0, "doing": 0, "done": 1}

    assert client.delete(f"/api/tasks/{task['_id']}").get_json() == {"deleted": True}
    assert client.get("/api/tasks").get_json() == []


def test_validation_and_not_found(client):
    assert client.post("/api/tasks", json={"title": "  "}).status_code == 400
    assert client.patch("/api/tasks/x", json={"status": "nope"}).status_code == 400
    assert client.patch("/api/tasks/missing", json={"status": "done"}).status_code == 404
    assert client.delete("/api/tasks/missing").status_code == 404


def test_filters_by_status_and_tag(client):
    client.post("/api/tasks", json={"title": "a", "tags": ["infra"]})
    b = client.post("/api/tasks", json={"title": "b", "tags": ["ui"]}).get_json()
    client.patch(f"/api/tasks/{b['_id']}", json={"status": "doing"})
    assert [t["title"] for t in client.get("/api/tasks?tag=infra").get_json()] == ["a"]
    assert [t["title"] for t in client.get("/api/tasks?status=doing").get_json()] == ["b"]


# --- cliente HTTP de CouchDB (con respuestas simuladas) -----------------------
@responses.activate
def test_ensure_db_is_idempotent():
    responses.put(f"{BASE}/tasks", status=412)  # ya existía
    responses.post(f"{BASE}/tasks/_index", json={"result": "exists"})
    CouchStore(BASE, "tasks").ensure_db()
    assert "type-status" in responses.calls[1].request.body.decode()


@responses.activate
def test_update_reads_rev_then_puts_full_doc():
    responses.get(f"{BASE}/tasks/t1", json={"_id": "t1", "_rev": "1-a", "status": "todo"})
    responses.put(f"{BASE}/tasks/t1", json={"ok": True, "id": "t1", "rev": "2-b"})
    doc = CouchStore(BASE, "tasks").update("t1", {"status": "done"})
    assert doc["_rev"] == "2-b" and doc["status"] == "done"
    assert responses.calls[1].request.body.decode().count('"_rev": "1-a"') == 1


@responses.activate
def test_delete_passes_current_rev():
    responses.get(f"{BASE}/tasks/t1", json={"_id": "t1", "_rev": "3-c"})
    responses.delete(f"{BASE}/tasks/t1", json={"ok": True})
    CouchStore(BASE, "tasks").delete("t1")
    assert "rev=3-c" in responses.calls[1].request.url


@responses.activate
def test_new_database_is_seeded_but_existing_one_is_not():
    responses.post(f"{BASE}/tasks/_index", json={"result": "created"})
    responses.post(f"{BASE}/tasks", json={"ok": True, "id": "x", "rev": "1-a"})

    responses.put(f"{BASE}/tasks", status=201)  # base nueva
    assert CouchStore(BASE, "tasks").ensure_db() is True
    inserted = [c for c in responses.calls if c.request.method == "POST" and c.request.url == f"{BASE}/tasks"]
    assert len(inserted) == len(DEMO_TASKS)
    assert {json.loads(c.request.body)["status"] for c in inserted} == {"todo", "doing", "done"}

    responses.replace(responses.PUT, f"{BASE}/tasks", status=412)  # ya existía: no duplica
    before = len(responses.calls)
    assert CouchStore(BASE, "tasks").ensure_db() is False
    assert all(c.request.url != f"{BASE}/tasks" or c.request.method != "POST" for c in responses.calls[before:])


@responses.activate
def test_seed_can_be_disabled():
    responses.put(f"{BASE}/tasks", status=201)
    responses.post(f"{BASE}/tasks/_index", json={"result": "created"})
    CouchStore(BASE, "tasks", seed=False).ensure_db()
    assert len(responses.calls) == 2  # solo crear base + índice


def test_api_returns_503_when_database_is_down():
    class Down(MemoryStore):
        def find(self, *a, **k):
            raise requests.ConnectionError("couchdb is asleep")

    r = create_app(store=Down()).test_client().get("/api/tasks")
    assert r.status_code == 503 and "unavailable" in r.get_json()["error"]


def test_url_without_scheme_gets_http():
    assert CouchStore("couchdb:5984", "tasks").base == "http://couchdb:5984"
    assert CouchStore("https://x.example.com/", "tasks").base == "https://x.example.com"


@responses.activate
def test_missing_database_is_recreated_and_request_retried():
    """Plan sin disco: si CouchDB se reinicia, la base desaparece; el cliente la recrea y reintenta."""
    gone = {"error": "not_found", "reason": "Database does not exist."}
    responses.post(f"{BASE}/tasks/_find", status=404, json=gone)
    responses.put(f"{BASE}/tasks", status=201, json={"ok": True})
    responses.post(f"{BASE}/tasks/_index", json={"result": "created"})
    responses.post(f"{BASE}/tasks/_find", json={"docs": []})
    assert CouchStore(BASE, "tasks", seed=False).find({"type": "task"}) == []
    assert [c.request.method for c in responses.calls] == ["POST", "PUT", "POST", "POST"]


@responses.activate
def test_get_missing_raises_not_found():
    responses.get(f"{BASE}/tasks/zz", status=404)
    with pytest.raises(NotFound):
        CouchStore(BASE, "tasks").get("zz")


# --- integración real: solo si hay un CouchDB accesible (CI / docker compose) --
def _couch_available():
    url = os.getenv("COUCHDB_URL")
    if not url:
        return False
    try:
        return requests.get(url, timeout=2).ok
    except requests.RequestException:
        return False


@pytest.mark.skipif(not _couch_available(), reason="define COUCHDB_URL apuntando a un CouchDB en ejecución")
def test_integration_against_real_couchdb():
    store = CouchStore(os.environ["COUCHDB_URL"], "tasks_ci_test", os.getenv("COUCHDB_USER"), os.getenv("COUCHDB_PASSWORD"), seed=False)
    requests.delete(store._url(), auth=store.http.auth)  # empieza limpio
    app = create_app(store=store).test_client()
    t = app.post("/api/tasks", json={"title": "real", "tags": ["ci"]}).get_json()
    assert app.get("/api/tasks?tag=ci").get_json()[0]["_id"] == t["_id"]
    assert app.patch(f"/api/tasks/{t['_id']}", json={"status": "doing"}).get_json()["status"] == "doing"
    assert app.get("/api/stats").get_json()["doing"] == 1
    assert app.delete(f"/api/tasks/{t['_id']}").status_code == 200
    requests.delete(store._url(), auth=store.http.auth)


@pytest.mark.skipif(not _couch_available(), reason="define COUCHDB_URL apuntando a un CouchDB en ejecución")
def test_integration_seeds_on_first_use_and_after_database_loss():
    """La demo 'parece persistente': base nueva → datos de ejemplo; base perdida → se restauran sin duplicarse."""
    store = CouchStore(os.environ["COUCHDB_URL"], "tasks_ci_seed", os.getenv("COUCHDB_USER"), os.getenv("COUCHDB_PASSWORD"))
    requests.delete(store._url(), auth=store.http.auth)
    app = create_app(store=store).test_client()
    assert app.get("/api/stats").get_json() == {"total": 5, "todo": 2, "doing": 1, "done": 2}
    assert app.get("/api/stats").get_json()["total"] == 5  # peticiones repetidas no duplican

    requests.delete(store._url(), auth=store.http.auth)  # simula reinicio de CouchDB sin disco
    assert app.get("/api/stats").get_json()["total"] == 5
    requests.delete(store._url(), auth=store.http.auth)
