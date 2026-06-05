from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory


@dataclass(frozen=True)
class DashboardRouteCheck:
    path: str
    status_code: int
    bytes: int
    expected_text_found: bool


@dataclass(frozen=True)
class DashboardSmokeReport:
    status: str
    total_routes: int
    passed_routes: int
    routes: list[DashboardRouteCheck]


ROUTES = [
    ("/dashboard", "AI ContentOps Studio"),
    ("/dashboard/system-status", "System Status"),
    ("/dashboard/release-evidence", "Release Evidence"),
    ("/dashboard/operations?days=7&window_size=100", "Operations Console"),
    ("/dashboard/ops-trends?days=7", "Operations Trends"),
    ("/dashboard/ops-brief?days=7", "Operations Brief"),
    ("/dashboard/job-execution-trends?days=7", "Worker Execution Trends"),
    ("/dashboard/integration-smoke", "Integration Smoke"),
    ("/dashboard/retention?days=90&limit=100", "Retention Lifecycle"),
    ("/dashboard/worker-jobs", "Worker Job Catalog"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Render core dashboard pages in-process.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dashboard-smoke/dashboard-smoke.json"),
        help="JSON file where the dashboard smoke report will be written.",
    )
    args = parser.parse_args()

    report = run_dashboard_smoke()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "status": report.status,
                "total_routes": report.total_routes,
                "passed_routes": report.passed_routes,
                "routes": [asdict(route) for route in report.routes],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(asdict(report), indent=2))
    if report.status != "pass":
        raise SystemExit(1)


def run_dashboard_smoke() -> DashboardSmokeReport:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        os.environ.setdefault("CONTENTOPS_ARTIFACT_ROOT", str(root / "artifacts"))
        os.environ.setdefault("CONTENTOPS_DATABASE_URL", f"sqlite:///{root / 'contentops.db'}")
        os.environ.setdefault("CONTENTOPS_SITE_OUTPUT_DIR", str(root / "site"))

        from contentops_api.main import app  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        client = TestClient(app)
        checks = [
            _check_route(client, path, expected_text) for path, expected_text in ROUTES
        ]
    passed = sum(1 for check in checks if check.status_code == 200 and check.expected_text_found)
    status = "pass" if passed == len(checks) else "fail"
    return DashboardSmokeReport(
        status=status,
        total_routes=len(checks),
        passed_routes=passed,
        routes=checks,
    )


def _check_route(client: object, path: str, expected_text: str) -> DashboardRouteCheck:
    response = client.get(path)
    body = response.text
    return DashboardRouteCheck(
        path=path,
        status_code=response.status_code,
        bytes=len(response.content),
        expected_text_found=expected_text in body,
    )


if __name__ == "__main__":
    main()
