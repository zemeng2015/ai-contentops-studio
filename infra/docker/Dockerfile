FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY apps ./apps
COPY packages ./packages
COPY alembic.ini ./
COPY migrations ./migrations
COPY infra/docker/entrypoint.py ./infra/docker/entrypoint.py

RUN pip install --no-cache-dir .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3).read()"

ENTRYPOINT ["python", "infra/docker/entrypoint.py"]
CMD ["uvicorn", "contentops_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
