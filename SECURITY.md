# Security Policy

## Supported Versions

This project is currently pre-1.0. Security fixes are applied to the `main` branch.

## Reporting a Vulnerability

Please do not open a public issue for sensitive security reports.

If you find a vulnerability, contact the maintainer directly through the GitHub profile associated
with this repository. Include:

- a concise description of the issue
- steps to reproduce
- affected configuration or deployment mode
- potential impact
- any suggested mitigation

## Security Notes

- Do not commit `.env` files, API keys, webhook URLs, database URLs, or generated artifact
  directories.
- Shared deployments should set `CONTENTOPS_OPERATOR_API_KEY`.
- Public dashboards or artifact routes should set `CONTENTOPS_REQUIRE_READ_API_KEY=true`.
- Production deployments should use Secrets Manager or an equivalent secret store for provider
  keys and database URLs.
- Release evidence and deployment manifests are designed to redact secrets, but operators should
  still review artifacts before sharing them externally.
