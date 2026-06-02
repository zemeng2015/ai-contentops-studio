# Integration Smoke Tests

The regular test suite is deterministic and does not require external credentials. Optional
integration smoke tests are available for operators who want to prove the live provider paths still
work against real services.

Run all live smoke tests:

```powershell
$env:CONTENTOPS_RUN_INTEGRATION="1"
$env:CONTENTOPS_OPENAI_API_KEY="..."
$env:CONTENTOPS_RESEARCH_SEARCH_API_KEY="..."
$env:CONTENTOPS_HOMEPAGE_REPO_PATH="C:\path\to\zack-ai-homepage"
pytest -m integration tests/test_integration_smoke.py
```

Run only the public feed smoke test:

```powershell
$env:CONTENTOPS_RUN_INTEGRATION="1"
pytest -m integration tests/test_integration_smoke.py -k feed
```

Environment variables:

- `CONTENTOPS_RUN_INTEGRATION=1`: required opt-in flag for every live smoke test
- `CONTENTOPS_OPENAI_API_KEY`: enables the OpenAI Responses API generation smoke test
- `CONTENTOPS_RESEARCH_SEARCH_API_KEY`: enables the Brave-compatible search smoke test
- `CONTENTOPS_HOMEPAGE_REPO_PATH`: enables a read-only homepage publisher plan check against the
  configured portfolio repository

These tests are intentionally smoke-level checks. They verify that provider credentials,
configuration, network access, and response parsing work, while the normal unit tests keep CI fast
and deterministic.
