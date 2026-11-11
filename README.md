# Tablero de tareas con Apache CouchDB

App de demostración Flask + **Apache CouchDB** (base de datos NoSQL orientada a documentos): tablero Kanban cuyas tareas son documentos JSON consultados con Mango (`_find`). Empaquetada con Docker, probada y desplegada automáticamente con GitHub Actions en Render, donde tanto la app como CouchDB corren como servicios del mismo Blueprint.

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

1. En Render: **New → Blueprint** con este repositorio. `render.yaml` crea dos servicios: `couchdb` (imagen oficial `couchdb:3.3`, contraseña generada) y `nosql-couchdb-app` (la app), y conecta la app a la base por la red privada de Render sin que tengas que copiar credenciales.
2. Copiar el *Deploy Hook* del servicio `nosql-couchdb-app` como secreto `RENDER_DEPLOY_HOOK_URL` y su URL pública como variable `APP_URL`.

**Limitaciones del plan gratuito:** Render no ofrece disco persistente, así que los datos de CouchDB se pierden cuando el servicio se reinicia o se duerme por inactividad (la app recrea la base y el índice sola). Además, los servicios se duermen tras 15 min sin tráfico y el primer acceso tarda cerca de un minuto. Para conservar los datos, usa un plan de pago con disco montado en `/opt/couchdb/data`.
