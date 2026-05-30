FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY apps ./apps
COPY packages ./packages

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "contentops_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

