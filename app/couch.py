"""Cliente mínimo para Apache CouchDB (API HTTP + JSON).

Usa solo `requests`. Funciona contra un CouchDB local, uno desplegado en Render o un servicio
compatible (p. ej. IBM Cloudant), porque todos exponen la misma API REST.
"""
import os
from datetime import datetime, timezone

import requests


class NotFound(Exception):
    pass


def _normalize(url: str) -> str:
    """Render entrega el host interno sin esquema (p. ej. `couchdb:5984`): se asume http."""
    url = url.strip().rstrip("/")
    return url if url.startswith(("http://", "https://")) else f"http://{url}"


class CouchStore:
    def __init__(self, url: str, db: str, user: str | None = None, password: str | None = None, timeout: float = 15):
        self.base = _normalize(url)
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

    @staticmethod
    def _db_missing(r: requests.Response) -> bool:
        if r.status_code != 404:
            return False
        try:
            return "database does not exist" in str(r.json().get("reason", "")).lower()
        except ValueError:
            return False

    def _send(self, method: str, path: str = "", **kwargs) -> requests.Response:
        """Envía la petición. Si la base no existe (p. ej. CouchDB se reinició en un plan sin disco), la recrea y reintenta una vez."""
        r = self.http.request(method, self._url(path), timeout=self.timeout, **kwargs)
        if self._db_missing(r):
            self.ensure_db()
            r = self.http.request(method, self._url(path), timeout=self.timeout, **kwargs)
        return r

    def ping(self) -> bool:
        r = self._send("GET")
        r.raise_for_status()
        return True

    def ensure_db(self) -> None:
        """Crea la base si no existe (PUT es idempotente: 412 = ya existía) y su índice Mango."""
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
        r = self._send("POST", json=doc)
        r.raise_for_status()
        body = r.json()
        return {**doc, "_id": body["id"], "_rev": body["rev"]}

    def get(self, doc_id: str) -> dict:
        r = self._send("GET", f"/{doc_id}")
        if r.status_code == 404:
            raise NotFound(doc_id)
        r.raise_for_status()
        return r.json()

    def update(self, doc_id: str, changes: dict) -> dict:
        """Lee el documento (para obtener _rev), aplica los cambios y lo guarda (control de concurrencia MVCC)."""
        doc = {**self.get(doc_id), **changes}
        r = self._send("PUT", f"/{doc_id}", json=doc)
        r.raise_for_status()
        doc["_rev"] = r.json()["rev"]
        return doc

    def delete(self, doc_id: str) -> None:
        rev = self.get(doc_id)["_rev"]
        r = self._send("DELETE", f"/{doc_id}", params={"rev": rev})
        r.raise_for_status()

    def find(self, selector: dict, limit: int = 200) -> list[dict]:
        """Consulta Mango (_find): el filtrado ocurre en el servidor."""
        r = self._send("POST", "/_find", json={"selector": selector, "limit": limit})
        r.raise_for_status()
        return r.json()["docs"]
