import requests
from flask import Flask, jsonify, render_template, request

from .couch import CouchStore, NotFound

STATUSES = ("todo", "doing", "done")


def create_app(store=None) -> Flask:
    app = Flask(__name__, template_folder="../templates")
    app.config["STORE"] = store if store is not None else CouchStore.from_env()
    app.config["READY"] = False

    def db() -> CouchStore:
        s = app.config["STORE"]
        if not app.config["READY"]:  # crea la base la primera vez que se usa
            s.ensure_db()
            app.config["READY"] = True
        return s

    @app.errorhandler(requests.RequestException)
    def database_unavailable(_err):
        # CouchDB dormido o arrancando (plan gratuito): respuesta clara en vez de un 500 genérico.
        return {"error": "database unavailable, retry shortly"}, 503

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/health")
    def health():
        db().ping()
        return {"status": "ok", "database": "couchdb"}

    @app.get("/api/tasks")
    def list_tasks():
        selector = {"type": "task"}
        if request.args.get("status") in STATUSES:
            selector["status"] = request.args["status"]
        if request.args.get("tag"):
            selector["tags"] = {"$elemMatch": {"$eq": request.args["tag"]}}
        docs = db().find(selector)
        return jsonify(sorted(docs, key=lambda d: d["created_at"], reverse=True))

    @app.post("/api/tasks")
    def add_task():
        body = request.get_json(silent=True) or {}
        title = str(body.get("title", "")).strip()
        if not title:
            return {"error": "title is required"}, 400
        tags = [str(t).strip().lower() for t in body.get("tags", []) if str(t).strip()]
        return db().create(title, tags), 201

    @app.patch("/api/tasks/<task_id>")
    def update_task(task_id):
        status = (request.get_json(silent=True) or {}).get("status")
        if status not in STATUSES:
            return {"error": f"status must be one of {', '.join(STATUSES)}"}, 400
        try:
            return db().update(task_id, {"status": status})
        except NotFound:
            return {"error": "not found"}, 404

    @app.delete("/api/tasks/<task_id>")
    def delete_task(task_id):
        try:
            db().delete(task_id)
        except NotFound:
            return {"error": "not found"}, 404
        return {"deleted": True}

    @app.get("/api/stats")
    def stats():
        docs = db().find({"type": "task"}, limit=1000)
        counts = {s: 0 for s in STATUSES}
        for d in docs:
            counts[d["status"]] = counts.get(d["status"], 0) + 1
        return {"total": len(docs), **counts}

    return app
