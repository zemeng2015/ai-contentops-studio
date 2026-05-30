# AI ContentOps Studio

[English](README.md) | [中文](README.zh-CN.md)

AI ContentOps Studio is a production-shaped platform for technical research automation,
source-grounded content generation, quality evaluation, artifact tracking, and publishing.

It is designed to prove applied AI engineering skills beyond a prompt demo:

- multi-step LLM workflow orchestration
- source-grounded research packets
- content planning before generation
- deterministic quality evaluation
- observable run history and artifacts
- API, CLI, worker, and publisher boundaries
- local-first development with AWS-ready deployment primitives

## What it does

Given a topic, URL, or repository, the system creates a content run:

1. collect and normalize sources
2. extract engineering signals and claims
3. plan the article angle and outline
4. generate markdown and HTML drafts
5. evaluate groundedness, source coverage, career relevance, and publish readiness
6. publish to a static site target or keep the run in review
7. persist artifacts and run trace for inspection

The first pipeline is intentionally local and deterministic so it can run in CI without API keys.
Provider adapters are separated so OpenAI, search APIs, GitHub, or AWS services can be added
without rewriting the domain layer.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
contentops run --topic "LLM observability for enterprise RAG systems"
contentops runs
pytest
```

Start the API:

```powershell
uvicorn contentops_api.main:app --reload --app-dir apps/api
```

Then create a run:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/runs `
  -ContentType "application/json" `
  -Body '{"topic":"AI evaluation for RAG systems","publish":true}'
```

## Repository layout

```text
apps/
  api/                     FastAPI service
  cli/                     Typer command line interface
  worker/                  Background worker entrypoint
packages/
  core/                    Domain models, pipeline orchestration, artifact storage
  providers/               Research, model, search, and external system adapters
  evaluators/              Content quality and groundedness checks
  publishing/              Static site and GitHub Pages publishers
  observability/           Structured run tracing
pipelines/                 YAML pipeline definitions
docs/                      Architecture, deployment, and evaluation methodology
infra/                     Docker and AWS deployment notes
tests/                     Unit and integration tests
```

## Architecture principles

- The pipeline is stateful and inspectable. Every step writes an artifact.
- External services sit behind provider interfaces.
- Generated content is evaluated before it is published.
- Publishing is a state transition, not a side effect hidden inside generation.
- Local filesystem and SQLite are the default, with S3/RDS/EventBridge-ready boundaries.

## Current MVP

- Local research provider with deterministic source packets
- Markdown and HTML article generation
- Quality evaluation report
- SQLite run metadata
- Filesystem artifact store
- Static site publisher
- FastAPI `POST /runs` and `GET /runs`
- CLI `contentops run`, `contentops runs`, and `contentops show`
- pytest coverage for pipeline behavior
