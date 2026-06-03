# Contributing

Thanks for your interest in AI ContentOps Studio. This project is organized as a production-shaped
AI application, so contributions should preserve the separation between domain logic, providers,
API routes, CLI commands, workers, and infrastructure.

## Development Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Run the local quality checks:

```powershell
python -m ruff check .
python -m mypy apps packages tests
python -m pytest
```

## Contribution Guidelines

- Keep provider-specific behavior behind provider interfaces.
- Keep generated run artifacts inspectable and deterministic where possible.
- Add or update tests for API, CLI, worker, or infrastructure changes.
- Update docs when behavior, configuration, or deployment steps change.
- Do not commit local databases, generated artifacts, secrets, virtual environments, or cache
  directories.

## Pull Request Checklist

- [ ] The change is scoped and documented.
- [ ] `ruff`, `mypy`, and `pytest` pass locally.
- [ ] New configuration is documented in README, docs, or `config/production.env.example`.
- [ ] New infrastructure resources are covered by `tests/test_infra_docs.py` when relevant.
- [ ] Screenshots or demo assets are updated when dashboard behavior changes.
