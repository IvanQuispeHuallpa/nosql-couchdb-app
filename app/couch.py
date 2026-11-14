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


# Tareas de ejemplo: se insertan cada vez que la base se CREA (primer arranque o tras perderse
# por un reinicio en un plan sin disco), para que la demo nunca aparezca vacía.
DEMO_TASKS = [
    ("Diseñar el modelo de documentos", ["diseño"], "done"),
    ("Levantar CouchDB con Docker", ["docker", "infra"], "done"),
    ("Escribir las pruebas con pytest", ["calidad"], "doing"),
    ("Configurar el pipeline de GitHub Actions", ["ci", "infra"], "todo"),
    ("Desplegar en Render", ["nube", "infra"], "todo"),
]


class CouchStore:
    def __init__(self, url: str, db: str, user: str | None = None, password: str | None = None,
                 timeout: float = 15, seed: bool = True):
        self.base = _normalize(url)
        self.db = db
        self.timeout = timeout
        self.seed = seed
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
            seed=os.getenv("SEED_DEMO", "true").lower() != "false",
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

    def ensure_db(self) -> bool:
        """Crea la base si no existe (PUT es idempotente: 412 = ya existía) y su índice Mango.

        Si la base se acaba de crear, la rellena con DEMO_TASKS. Devuelve True si la creó.
        Con varios workers solo uno recibe el 201, así que los datos de demo no se duplican.
        """
        r = self.http.put(self._url(), timeout=self.timeout)
        if r.status_code not in (201, 202, 412):
            r.raise_for_status()
        created = r.status_code in (201, 202)
        # Índice Mango para las consultas por tipo/estado (POST _index es idempotente).
        r = self.http.post(
            self._url("/_index"),
            json={"index": {"fields": ["type", "status"]}, "name": "type-status", "type": "json"},
            timeout=self.timeout,
        )
        r.raise_for_status()
        if created and self.seed:
            for title, tags, status in DEMO_TASKS:
                self.create(title, tags, status)
        return created

    # --- CRUD ---------------------------------------------------------------
    def create(self, title: str, tags: list[str], status: str = "todo") -> dict:
        doc = {
            "type": "task",
            "title": title,
            "status": status,
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
