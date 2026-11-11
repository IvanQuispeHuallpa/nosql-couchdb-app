"""Cliente mínimo para Apache CouchDB / IBM Cloudant (API HTTP + JSON).

Usa solo `requests`. La misma clase funciona contra un CouchDB local y contra Cloudant,
porque ambos exponen la misma API REST.
"""
import os
from datetime import datetime, timezone

import requests


class NotFound(Exception):
    pass


class CouchStore:
    def __init__(self, url: str, db: str, user: str | None = None, password: str | None = None, timeout: float = 8):
        self.base = url.rstrip("/")
        self.db = db
        self.timeout = timeout
        self.http = requests.Session()
        if user:
            self.http.auth = (user, password or "")

    @classmethod
    def from_env(cls) -> "CouchStore":
        return cls(
            os.getenv("COUCHDB_URL", "http://localhost:5984"),
            os.getenv("COUCHDB_DB", "tasks"),
            os.getenv("COUCHDB_USER"),
            os.getenv("COUCHDB_PASSWORD"),
        )

    # --- utilidades ---------------------------------------------------------
    def _url(self, path: str = "") -> str:
        return f"{self.base}/{self.db}{path}"

    def ping(self) -> bool:
        r = self.http.get(self._url(), timeout=self.timeout)
        r.raise_for_status()
        return True

    def ensure_db(self) -> None:
        """Crea la base si no existe (PUT es idempotente: 412 = ya existía)."""
        r = self.http.put(self._url(), timeout=self.timeout)
        if r.status_code not in (201, 202, 412):
            r.raise_for_status()
        # Índice Mango para las consultas por tipo/estado (POST _index es idempotente).
        r = self.http.post(
            self._url("/_index"),
            json={"index": {"fields": ["type", "status"]}, "name": "type-status", "type": "json"},
            timeout=self.timeout,
        )
        r.raise_for_status()

    # --- CRUD ---------------------------------------------------------------
    def create(self, title: str, tags: list[str]) -> dict:
        doc = {
            "type": "task",
            "title": title,
            "status": "todo",
            "tags": tags,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        r = self.http.post(self._url(), json=doc, timeout=self.timeout)
        r.raise_for_status()
        body = r.json()
        return {**doc, "_id": body["id"], "_rev": body["rev"]}

    def get(self, doc_id: str) -> dict:
        r = self.http.get(self._url(f"/{doc_id}"), timeout=self.timeout)
        if r.status_code == 404:
            raise NotFound(doc_id)
        r.raise_for_status()
        return r.json()

    def update(self, doc_id: str, changes: dict) -> dict:
        """Lee el documento (para obtener _rev), aplica los cambios y lo guarda (control de concurrencia MVCC)."""
        doc = {**self.get(doc_id), **changes}
        r = self.http.put(self._url(f"/{doc_id}"), json=doc, timeout=self.timeout)
        r.raise_for_status()
        doc["_rev"] = r.json()["rev"]
        return doc

    def delete(self, doc_id: str) -> None:
        rev = self.get(doc_id)["_rev"]
        r = self.http.delete(self._url(f"/{doc_id}"), params={"rev": rev}, timeout=self.timeout)
        r.raise_for_status()

    def find(self, selector: dict, limit: int = 200) -> list[dict]:
        """Consulta Mango (_find): el filtrado ocurre en el servidor."""
        r = self.http.post(self._url("/_find"), json={"selector": selector, "limit": limit}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()["docs"]
