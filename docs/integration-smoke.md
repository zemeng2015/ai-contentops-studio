# Integration Smoke Tests

The regular test suite is deterministic and does not require external credentials. Optional
integration smoke tests are available for operators who want to prove the live provider paths still
work against real services.

Plan the live smoke run from the current environment:

```powershell
contentops integration-smoke-plan --json
```

The same report is available from `GET /integration-smoke-plan`. It lists each provider smoke
selector, the required environment variables, and any missing values before an operator opts into
the live pytest run.

Run all live smoke tests and persist a machine-readable report:

```powershell
$env:CONTENTOPS_RUN_INTEGRATION="1"
$env:CONTENTOPS_OPENAI_API_KEY="..."
$env:CONTENTOPS_RESEARCH_SEARCH_API_KEY="..."
$env:CONTENTOPS_HOMEPAGE_REPO_PATH="C:\path\to\zack-ai-homepage"
contentops integration-smoke-run --output artifacts/integration-smoke/report.json --json
```

Run only the public feed smoke test:

```powershell
$env:CONTENTOPS_RUN_INTEGRATION="1"
contentops integration-smoke-run --selector feed --output artifacts/integration-smoke/feed.json
```

The runner executes each provider smoke path separately and records status, command, exit code,
duration, missing environment variables, and stdout/stderr tails. Use `--dry-run` to write the
planned commands without executing pytest, or `--force` to run pytest even when the planner sees
missing environment variables.

GitHub Actions includes a manual `Integration Smoke` workflow. It defaults to dry-run mode and
uploads `plan.json`, `report.json`, and the command stdout as workflow artifacts. To run live
provider checks from GitHub, add repository secrets named `CONTENTOPS_OPENAI_API_KEY` and
`CONTENTOPS_RESEARCH_SEARCH_API_KEY`, then trigger the workflow with `dry_run=false`. If a runner
has access to a checked-out homepage repository, set the repository variable
`CONTENTOPS_HOMEPAGE_REPO_PATH` before selecting the `homepage` smoke check.

Environment variables:

- `CONTENTOPS_RUN_INTEGRATION=1`: required opt-in flag for every live smoke test
- `CONTENTOPS_OPENAI_API_KEY`: enables the OpenAI Responses API generation smoke test
- `CONTENTOPS_RESEARCH_SEARCH_API_KEY`: enables the Brave-compatible search smoke test
- `CONTENTOPS_HOMEPAGE_REPO_PATH`: enables a read-only homepage publisher plan check against the
  configured portfolio repository

These tests are intentionally smoke-level checks. They verify that provider credentials,
configuration, network access, and response parsing work, while the normal unit tests keep CI fast
and deterministic.
