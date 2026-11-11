# Tablero de tareas con Apache CouchDB

App de demostración Flask + **Apache CouchDB** (base de datos NoSQL orientada a documentos): tablero Kanban cuyas tareas son documentos JSON consultados con Mango (`_find`). Empaquetada con Docker, probada y desplegada automáticamente con GitHub Actions en Render, usando IBM Cloudant como CouchDB en la nube.

- App en vivo: _pendiente — URL de Render_
- Base de datos NoSQL: CouchDB (sin Redis, MongoDB, Neo4j ni Prometheus)

## Ejecutar en local

```bash
docker compose up -d --build
docker compose exec app python scripts/seed.py
# abrir http://localhost:8000   (Fauxton, el panel de CouchDB: http://localhost:5984/_utils, usuario admin / change-me)
```

## API

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | comprueba la conexión con CouchDB |
| GET | `/api/tasks?status=&tag=` | lista tareas (consulta Mango en el servidor) |
| POST | `/api/tasks` | crea `{ "title": "...", "tags": ["..."] }` |
| PATCH | `/api/tasks/<id>` | cambia el estado `{ "status": "todo\|doing\|done" }` |
| DELETE | `/api/tasks/<id>` | borra una tarea |
| GET | `/api/stats` | conteo por estado |

Variables de entorno: ver `.env.example`.

## Pruebas

```bash
pip install -r requirements-dev.txt
python -m pytest -q                       # unitarias (sin base de datos)
COUCHDB_URL=http://localhost:5984 COUCHDB_USER=admin COUCHDB_PASSWORD=change-me python -m pytest -q   # + integración real
```

## Despliegue automatizado

`.github/workflows/ci-cd.yml` en cada push / PR:

1. **test**: pytest con un contenedor CouchDB real como servicio.
2. **docker**: `docker compose up --wait`, siembra datos y comprueba `/health` y `/api/stats`.
3. **deploy** (solo `main`): llama al *Deploy Hook* de Render y espera a que `/health` responda en la URL pública.

Secreto de GitHub requerido: `RENDER_DEPLOY_HOOK_URL`. Variable (Settings → Variables): `APP_URL`.

### Puesta en marcha en la nube

1. Crear una instancia gratuita de **IBM Cloudant** (plan Lite) y credenciales de servicio; copiar `url`, `username` y `password`.
2. En Render: **New → Blueprint** con este repositorio (`render.yaml`) y definir `COUCHDB_URL`, `COUCHDB_USER`, `COUCHDB_PASSWORD`.
3. Copiar el *Deploy Hook* del servicio como secreto `RENDER_DEPLOY_HOOK_URL` y la URL pública como variable `APP_URL`.
