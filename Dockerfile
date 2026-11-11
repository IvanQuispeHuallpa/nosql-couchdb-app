FROM python:3.12-slim-bookworm

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY templates templates
COPY scripts scripts

ENV PORT=8000
RUN useradd -m appuser
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/health')"
CMD ["sh", "-c", "gunicorn app.wsgi:app --bind 0.0.0.0:${PORT} --workers 2"]
