"""Prepara la base de CouchDB. Si no existía, la crea y la rellena con las tareas de demo.

La app hace lo mismo sola en su primera petición; este script sirve para verificarlo
(p. ej. en CI) sin esperar al primer acceso.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.couch import CouchStore  # noqa: E402

store = CouchStore.from_env()
created = store.ensure_db()
print("base creada y sembrada" if created else "la base ya existía", "→", len(store.find({"type": "task"})), "tareas")
