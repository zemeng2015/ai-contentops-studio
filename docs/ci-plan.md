# Long-Term CI Plan

AI ContentOps Studio uses CI as an operational evidence system, not only a test runner. The goal is
to prove that code, workflow automation, release evidence, deployment infrastructure, and provider
readiness stay reviewable as the project grows.

## Current Completion Snapshot

- Core application: API, CLI, worker, review workflow, publishing, release evidence, and dashboards
  are implemented and covered by tests.
- Provider layer: local, URL, feed, discovery, search, GitHub, and OpenAI-compatible generation
  paths are represented, with optional live smoke checks.
- Operations: release gates, scheduled review packages, worker alert notifications, operations
  console snapshots, S3 mirroring evidence, and AWS Terraform are present.
- CI baseline: lint, type checking, migrations, worker dry-runs, deployment preflight, release
  evidence, release gate reports, tests, Docker build, container image vulnerability scan,
  Terraform fmt, and Terraform validate run on every push and pull request.

## Phase 1: Compatibility And Evidence Baseline

Status: complete.

- Run the main Python suite across Python 3.11, 3.12, and 3.13.
- Keep release evidence, deployment preflight, and release gate artifacts for every Python version.
- Keep Docker and Terraform validation as separate jobs so runtime and infrastructure failures are
  easy to triage.
- Preserve CI artifacts for deployment reviewers: deployment check, release evidence, and release
  gate checklist.

## Phase 2: Quality And Regression Signals

Status: complete.

- Add coverage reporting for core packages and API routes.
- Split slow API/dashboard tests from fast provider/unit tests while keeping a single required
  aggregate status.
- Add a small rendered dashboard smoke check that confirms key HTML pages render without 500s.
- Track release evidence size and artifact count over time to catch accidental evidence loss.

## Phase 3: Security And Supply Chain

Status: complete.

- Add dependency vulnerability scanning for Python dependencies.
- Add static checks for GitHub Actions permissions, secret usage, and unsafe shell patterns.
- Add container image vulnerability scanning after the Docker build.
- Add Terraform security checks for public exposure, encryption, and IAM privilege drift.

## Phase 4: Live Provider And Scheduled Operations

Status: complete.

- Keep the manual Integration Smoke workflow dry-run by default.
- Run live provider smoke checks only with explicit `workflow_dispatch` and configured secrets.
- Use scheduled ContentOps artifacts as review evidence, not direct publishing approval.
- Attach worker alert notifications, operations console snapshots, release gates, and scheduled
  review packages to every scheduled automation run.

## Phase 5: Release And Deployment Readiness

Status: complete.

- Require a passing release gate report before production deployment.
- Require a matching release approval record for protected deployment environments.
- Mirror release evidence and scheduled review packages to S3 in production.
- Compare release evidence from the candidate commit against the latest successful release to detect
  missing checks or artifact regressions.

## Phase 6: Container Image Assurance

Status: complete.

- Scan the built API image for high and critical vulnerabilities on every push and pull request.
- Publish the Grype JSON scan result and actionable vulnerability policy report as CI evidence for
  release reviewers.
- Fail CI only when a high or critical finding has a stable fix version available, so unrepaired
  upstream base-image findings remain visible without permanently blocking development.
- Keep the image runtime constrained with a slim Python base, no pip cache, non-root execution, and
  a healthcheck.

## Phase 7: Release Provenance And Image Publishing

Status: active.

- Publish approved API images to GitHub Container Registry from protected release workflows.
- Attach SBOM and provenance evidence to release artifacts.
- Keep image tags tied to immutable commit SHAs and reviewed release gate reports.
