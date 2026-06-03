# Demo Walkthrough

This path is for recruiters, reviewers, or operators who want to see the platform working before
reading the full architecture.

## Run with Docker Compose

```powershell
docker compose up --build -d api
docker compose run --rm demo-seed
```

Open the dashboard:

```text
http://localhost:8000/dashboard
```

The seed command creates three deterministic runs:

- one published run with a publish receipt and static site output
- one approved run ready to publish
- one `needs_review` run with source, evaluation, scorecard, incident, and artifact data

The same data is available through API and CLI surfaces:

```powershell
docker compose exec api contentops runs
docker compose exec api contentops ops-summary --json
docker compose exec api contentops content --json
docker compose exec api contentops release-readiness --json
```

For a recruiter-friendly overview with screenshots, architecture, sample articles, and a two-minute
demo script, see [Showcase Package](showcase.md).

Stop the demo:

```powershell
docker compose down
```

Remove seeded data:

```powershell
docker compose down -v
```

## Run Locally Without Docker

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
contentops demo-seed
uvicorn contentops_api.main:app --reload --app-dir apps/api
```

Then open:

```text
http://127.0.0.1:8000/dashboard
```

## What to Inspect

- Dashboard queue depth, operations summary, scorecards, incidents, and published content.
- Content calendar page at `/dashboard/worker-jobs` with review-first GitHub project update jobs.
- Worker execution detail pages that connect automation receipts back to generated runs.
- Run detail pages with workflow context, source audit, evaluation report, timeline, publish plan,
  and artifacts.
- `publish-receipt.json`, `publish-verification.json`, `audit-log.json`, and `generation-receipt.json`.
- Static site output under the configured site directory.
