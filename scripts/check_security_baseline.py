from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SecurityCheck:
    name: str
    status: str
    message: str


@dataclass(frozen=True)
class SecurityBaselineReport:
    status: str
    checks: list[SecurityCheck]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check repository security posture that should remain true in CI."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("security-baseline/security-baseline.json"),
        help="JSON file where the security baseline report will be written.",
    )
    args = parser.parse_args()

    report = check_security_baseline()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "status": report.status,
                "checks": [asdict(check) for check in report.checks],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(asdict(report), indent=2))
    if report.status != "pass":
        raise SystemExit(1)


def check_security_baseline(repo_root: Path = Path(".")) -> SecurityBaselineReport:
    checks = [
        *_workflow_checks(repo_root / ".github" / "workflows"),
        *_terraform_checks(repo_root / "infra" / "aws" / "terraform" / "main.tf"),
        *_docker_checks(repo_root / "infra" / "docker" / "Dockerfile"),
    ]
    status = "pass" if all(check.status == "pass" for check in checks) else "fail"
    return SecurityBaselineReport(status=status, checks=checks)


def _workflow_checks(workflow_dir: Path) -> list[SecurityCheck]:
    checks: list[SecurityCheck] = []
    for path in sorted(workflow_dir.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        permissions = workflow.get("permissions")
        if not isinstance(permissions, dict):
            checks.append(_fail(f"{path.name}:permissions", "Workflow must define permissions."))
            continue
        if "pull_request_target" in workflow.get(True, {}):
            checks.append(
                _fail(
                    f"{path.name}:pull_request_target",
                    "pull_request_target is not allowed for this repository.",
                )
            )
        checks.append(
            _pass_if(
                "contents" in permissions,
                f"{path.name}:contents-permission",
                "Workflow declares explicit contents permission.",
            )
        )
        if path.name != "scheduled-contentops.yml":
            checks.append(
                _pass_if(
                    permissions == {"contents": "read"},
                    f"{path.name}:least-privilege",
                    "Non-publishing workflows must stay read-only.",
                )
            )
        else:
            checks.extend(_scheduled_workflow_checks(path, workflow))
        checks.extend(_action_reference_checks(path, workflow))
        if path.name == "ci.yml":
            checks.extend(_container_image_scan_checks(path, workflow))
    return checks


def _scheduled_workflow_checks(path: Path, workflow: dict[str, Any]) -> list[SecurityCheck]:
    text = path.read_text(encoding="utf-8")
    permissions = workflow.get("permissions", {})
    checks = [
        _pass_if(
            permissions == {
                "contents": "write",
                "issues": "write",
                "pull-requests": "write",
            },
            f"{path.name}:scoped-write-permissions",
            "Scheduled publishing workflow has only the write scopes it uses.",
        ),
        _pass_if(
            "default: true" in text and "dry_run_only" in text,
            f"{path.name}:dry-run-default",
            "Manual scheduled runs default to dry-run mode.",
        ),
        _pass_if(
            "create_review_issue" in text and "default: false" in text,
            f"{path.name}:manual-issue-default",
            "Review issue creation is opt-in.",
        ),
        _pass_if(
            "create_draft_pr" in text and "default: false" in text,
            f"{path.name}:manual-pr-default",
            "Draft PR creation is opt-in.",
        ),
    ]
    for block_name in ("Create review issue", "Create draft PR"):
        checks.append(
            _pass_if(
                block_name in text and "GH_TOKEN: ${{ github.token }}" in text,
                f"{path.name}:{block_name.casefold().replace(' ', '-')}-token",
                f"{block_name} step scopes the GitHub token to the step environment.",
            )
        )
    return checks


def _action_reference_checks(path: Path, workflow: dict[str, Any]) -> list[SecurityCheck]:
    checks: list[SecurityCheck] = []
    for job_name, job in workflow.get("jobs", {}).items():
        for index, step in enumerate(job.get("steps", [])):
            uses = step.get("uses")
            if not uses:
                continue
            checks.append(
                _pass_if(
                    "@" in uses and not uses.endswith("@main") and not uses.endswith("@master"),
                    f"{path.name}:{job_name}:action-{index}",
                    f"Action reference is versioned: {uses}",
                )
            )
    return checks


def _container_image_scan_checks(path: Path, workflow: dict[str, Any]) -> list[SecurityCheck]:
    text = path.read_text(encoding="utf-8")
    docker_job = workflow.get("jobs", {}).get("docker", {})
    docker_steps = docker_job.get("steps", []) if isinstance(docker_job, dict) else []
    scan_action_present = any(
        step.get("uses") == "anchore/scan-action@v7"
        for step in docker_steps
        if isinstance(step, dict)
    )
    return [
        _pass_if(
            "docker build -f infra/docker/Dockerfile -t ai-contentops-studio:ci ." in text,
            "ci:docker-image-build",
            "CI builds the API container image before scanning it.",
        ),
        _pass_if(
            scan_action_present,
            "ci:container-scanner-versioned",
            "CI uses a versioned Anchore scan action.",
        ),
        _pass_if(
            "image: ai-contentops-studio:ci" in text
            and "fail-build: false" in text
            and "severity-cutoff: high" in text,
            "ci:container-image-vulnerability-scan",
            "CI scans container images for high and critical vulnerabilities.",
        ),
        _pass_if(
            "scripts/check_container_vulnerability_report.py" in text
            and "container-image-policy.json" in text,
            "ci:container-vulnerability-policy-gate",
            "CI applies an actionable container vulnerability policy gate.",
        ),
        _pass_if(
            "security-baseline/container-image-grype.json" in text
            and "container-image-security" in text,
            "ci:container-scan-artifact",
            "CI publishes the container vulnerability scan report as an artifact.",
        ),
    ]


def _terraform_checks(main_tf: Path) -> list[SecurityCheck]:
    text = main_tf.read_text(encoding="utf-8")
    return [
        _pass_if(
            "storage_encrypted      = true" in text,
            "terraform:rds-encryption",
            "RDS metadata storage is encrypted.",
        ),
        _pass_if(
            "publicly_accessible    = false" in text,
            "terraform:rds-private",
            "RDS metadata database is not public.",
        ),
        _pass_if(
            "sqs_managed_sse_enabled    = true" in text,
            "terraform:sqs-encryption",
            "Scheduler DLQ uses managed server-side encryption.",
        ),
        _pass_if(
            "assign_public_ip = false" in text,
            "terraform:private-workers",
            "Scheduled ECS tasks do not receive public IP addresses.",
        ),
        _pass_if(
            "dead_letter_config" in text and "aws_sqs_queue.scheduler_dlq.arn" in text,
            "terraform:scheduler-dlq",
            "EventBridge Scheduler targets use a dead-letter queue.",
        ),
        _pass_if(
            '"*"' not in text,
            "terraform:no-wildcard-iam",
            "IAM policies avoid wildcard actions and resources.",
        ),
    ]


def _docker_checks(dockerfile: Path) -> list[SecurityCheck]:
    text = dockerfile.read_text(encoding="utf-8")
    return [
        _pass_if(
            "python:3.13-slim" in text,
            "docker:slim-base",
            "Runtime image uses a slim Python base.",
        ),
        _pass_if(
            "pip install --no-cache-dir" in text,
            "docker:no-cache-install",
            "Python dependencies are installed without pip cache.",
        ),
        _pass_if(
            "USER contentops" in text,
            "docker:non-root-user",
            "Container process runs as the contentops user.",
        ),
        _pass_if(
            "HEALTHCHECK" in text,
            "docker:healthcheck",
            "Runtime image exposes a healthcheck.",
        ),
    ]


def _pass_if(condition: bool, name: str, message: str) -> SecurityCheck:
    if condition:
        return SecurityCheck(name=name, status="pass", message=message)
    return _fail(name, message)


def _fail(name: str, message: str) -> SecurityCheck:
    return SecurityCheck(name=name, status="fail", message=message)


if __name__ == "__main__":
    main()
