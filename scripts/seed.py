"""Inserta tareas de demo en CouchDB (crea la base si no existe)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.couch import CouchStore  # noqa: E402

store = CouchStore.from_env()
store.ensure_db()
demo = [
    ("Diseñar el modelo de documentos", ["diseño"]),
    ("Levantar CouchDB con Docker", ["docker", "infra"]),
    ("Escribir las pruebas con pytest", ["calidad"]),
    ("Configurar el pipeline de GitHub Actions", ["ci", "infra"]),
    ("Desplegar en Render", ["nube", "infra"]),
]
for title, tags in demo:
    store.create(title, tags)
print("insertadas", len(store.find({"type": "task"})), "tareas")
