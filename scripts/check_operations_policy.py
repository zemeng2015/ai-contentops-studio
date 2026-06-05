from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class OperationsPolicyCheck:
    name: str
    status: str
    message: str


@dataclass(frozen=True)
class OperationsPolicyReport:
    status: str
    checks: list[OperationsPolicyCheck]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check live-provider and scheduled-operations workflow policy."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("operations-policy/operations-policy.json"),
        help="JSON file where the operations policy report will be written.",
    )
    args = parser.parse_args()

    report = check_operations_policy()
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


def check_operations_policy(repo_root: Path = Path(".")) -> OperationsPolicyReport:
    checks = [
        *_integration_smoke_checks(repo_root / ".github" / "workflows" / "integration-smoke.yml"),
        *_scheduled_workflow_checks(
            repo_root / ".github" / "workflows" / "scheduled-contentops.yml",
            repo_root / "pipelines",
        ),
    ]
    status = "pass" if all(check.status == "pass" for check in checks) else "fail"
    return OperationsPolicyReport(status=status, checks=checks)


def _integration_smoke_checks(path: Path) -> list[OperationsPolicyCheck]:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    trigger = workflow.get(True, {})
    text = path.read_text(encoding="utf-8")
    return [
        _pass_if(
            set(trigger) == {"workflow_dispatch"},
            "integration-smoke:manual-only",
            "Live provider smoke workflow can only be started manually.",
        ),
        _pass_if(
            _input_default(workflow, "dry_run") is True,
            "integration-smoke:dry-run-default",
            "Live provider smoke workflow defaults to dry-run mode.",
        ),
        _pass_if(
            _input_default(workflow, "force") is False,
            "integration-smoke:force-default",
            "Live provider smoke workflow does not force execution by default.",
        ),
        _pass_if(
            workflow.get("permissions") == {"contents": "read"},
            "integration-smoke:read-only-permissions",
            "Live provider smoke workflow has read-only repository permissions.",
        ),
        _pass_if(
            "CONTENTOPS_RUN_INTEGRATION: ${{ inputs.dry_run && '0' || '1' }}" in text,
            "integration-smoke:dry-run-env-gate",
            "Live provider execution is tied to the dry_run input.",
        ),
        _pass_if(
            "actions/upload-artifact@v7" in text and "artifacts/integration-smoke/*.json" in text,
            "integration-smoke:evidence-artifact",
            "Live provider smoke runs upload machine-readable evidence.",
        ),
    ]


def _scheduled_workflow_checks(path: Path, pipeline_dir: Path) -> list[OperationsPolicyCheck]:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")
    publish_intent_count = _scheduled_publish_intent_count(pipeline_dir)
    return [
        _pass_if(
            _input_default(workflow, "dry_run_only") is True,
            "scheduled:dry-run-default",
            "Manual scheduled workflow runs default to dry-run only.",
        ),
        _pass_if(
            _input_default(workflow, "create_review_issue") is False,
            "scheduled:issue-opt-in",
            "Review issue creation remains opt-in.",
        ),
        _pass_if(
            _input_default(workflow, "create_draft_pr") is False,
            "scheduled:pr-opt-in",
            "Draft PR creation remains opt-in.",
        ),
        _pass_if(
            text.count("--review-only") >= 2,
            "scheduled:review-only-execution",
            "Scheduled worker execution generates review packages without direct publish approval.",
        ),
        _pass_if(
            publish_intent_count == 0 or "--review-only" in text,
            "scheduled:publish-intent-guarded",
            "YAML publish intent is guarded by review-only scheduled execution.",
        ),
        _pass_if(
            text.count("contentops release-gate") >= 2,
            "scheduled:release-gate-evidence",
            "Scheduled jobs attach release gate snapshots.",
        ),
        _pass_if(
            text.count("contentops scheduled-workflow-verify") >= 2,
            "scheduled:manifest-verification",
            "Scheduled review manifests are verified before artifact upload.",
        ),
        _pass_if(
            text.count("contentops scheduled-workflow-archive") >= 2,
            "scheduled:review-package-archive",
            "Scheduled review packages are archived as evidence.",
        ),
        _pass_if(
            text.count("contentops operations-console") >= 2,
            "scheduled:operations-console",
            "Scheduled jobs attach operations console snapshots.",
        ),
        _pass_if(
            "if: always() && github.event_name == 'workflow_dispatch'" in text,
            "scheduled:manual-github-mutations",
            "GitHub issue and PR mutations are limited to manual dispatch runs.",
        ),
    ]


def _scheduled_publish_intent_count(pipeline_dir: Path) -> int:
    count = 0
    for path in pipeline_dir.glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        jobs = data.get("jobs", [])
        if not isinstance(jobs, list):
            continue
        count += sum(1 for job in jobs if isinstance(job, dict) and job.get("publish") is True)
    return count


def _input_default(workflow: dict[str, Any], input_name: str) -> Any:
    trigger = workflow.get(True, {})
    if not isinstance(trigger, dict):
        return None
    dispatch = trigger.get("workflow_dispatch", {})
    if not isinstance(dispatch, dict):
        return None
    inputs = dispatch.get("inputs", {})
    if not isinstance(inputs, dict):
        return None
    item = inputs.get(input_name, {})
    if not isinstance(item, dict):
        return None
    return item.get("default")


def _pass_if(condition: bool, name: str, message: str) -> OperationsPolicyCheck:
    return OperationsPolicyCheck(
        name=name,
        status="pass" if condition else "fail",
        message=message,
    )


if __name__ == "__main__":
    main()
