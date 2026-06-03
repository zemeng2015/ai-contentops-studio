from __future__ import annotations

import importlib
import json
import mimetypes
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from contentops_core.models import ArtifactManifest, ArtifactMirrorRecord, RunRecord


class ArtifactWriter(Protocol):
    root: Path

    def prepare(self, run: RunRecord) -> None:
        """Prepare the destination for a run's artifacts."""

    def write_json(self, run: RunRecord, name: str, payload: BaseModel | dict[str, Any]) -> Path:
        """Write a JSON artifact."""

    def write_text(self, run: RunRecord, name: str, text: str) -> Path:
        """Write a text artifact."""

    def read_text(self, run: RunRecord, name: str) -> str:
        """Read a text artifact."""


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def prepare(self, run: RunRecord) -> None:
        run.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.write_json(run, "manifest.json", ArtifactManifest(run_id=run.id))

    def write_json(self, run: RunRecord, name: str, payload: BaseModel | dict[str, Any]) -> Path:
        path = run.artifact_dir / name
        if isinstance(payload, BaseModel):
            data = payload.model_dump(mode="json")
        else:
            data = payload
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def write_text(self, run: RunRecord, name: str, text: str) -> Path:
        path = run.artifact_dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def read_text(self, run: RunRecord, name: str) -> str:
        return (run.artifact_dir / name).read_text(encoding="utf-8")


class S3MirroringArtifactStore(ArtifactStore):
    """Filesystem artifact store that mirrors writes to S3 when configured.

    The local copy remains authoritative for tests, review, and retries. S3 mirroring is a
    production deployment option for workers running on ECS/Lambda.
    """

    def __init__(self, root: Path, bucket: str, prefix: str = "contentops-artifacts") -> None:
        super().__init__(root)
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def write_json(self, run: RunRecord, name: str, payload: BaseModel | dict[str, Any]) -> Path:
        path = super().write_json(run, name, payload)
        self._upload(path, run, name, "application/json")
        return path

    def write_text(self, run: RunRecord, name: str, text: str) -> Path:
        path = super().write_text(run, name, text)
        self._upload(path, run, name, "text/plain")
        return path

    def _upload(self, path: Path, run: RunRecord, name: str, content_type: str) -> None:
        key = f"{self.prefix}/{run.id}/{name}"
        try:
            boto3 = importlib.import_module("boto3")
        except ModuleNotFoundError as exc:
            self._append_mirror_record(
                run,
                ArtifactMirrorRecord(
                    run_id=run.id,
                    artifact_name=name,
                    provider="s3",
                    bucket=self.bucket,
                    key=key,
                    content_type=content_type,
                    status="failed",
                    error="boto3 is not installed",
                ),
            )
            raise RuntimeError(
                "boto3 is required for CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3. "
                "Install the aws extra with: pip install -e \".[aws]\""
            ) from exc
        client = boto3.client("s3")
        try:
            client.upload_file(
                str(path),
                self.bucket,
                key,
                ExtraArgs={"ContentType": content_type},
            )
        except Exception as exc:
            self._append_mirror_record(
                run,
                ArtifactMirrorRecord(
                    run_id=run.id,
                    artifact_name=name,
                    provider="s3",
                    bucket=self.bucket,
                    key=key,
                    content_type=content_type,
                    status="failed",
                    error=str(exc),
                ),
            )
            raise
        self._append_mirror_record(
            run,
            ArtifactMirrorRecord(
                run_id=run.id,
                artifact_name=name,
                provider="s3",
                bucket=self.bucket,
                key=key,
                content_type=content_type,
                status="mirrored",
            ),
        )

    @staticmethod
    def _append_mirror_record(run: RunRecord, record: ArtifactMirrorRecord) -> None:
        path = run.artifact_dir / "s3-mirror-log.json"
        if path.exists():
            records = json.loads(path.read_text(encoding="utf-8"))
        else:
            records = []
        records.append(record.model_dump(mode="json"))
        path.write_text(json.dumps(records, indent=2), encoding="utf-8")


def mirror_files_to_s3(
    paths: Iterable[Path],
    *,
    bucket: str,
    prefix: str,
    collection_id: str,
) -> list[ArtifactMirrorRecord]:
    """Mirror standalone operational artifacts to S3 and return audit records."""

    return [
        _mirror_file_to_s3(
            path=path,
            bucket=bucket,
            prefix=prefix,
            collection_id=collection_id,
        )
        for path in sorted(paths, key=lambda item: item.name)
        if path.is_file()
    ]


def write_s3_mirror_log(records: list[ArtifactMirrorRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([record.model_dump(mode="json") for record in records], indent=2),
        encoding="utf-8",
    )


def failed_s3_mirror_records(records: Iterable[ArtifactMirrorRecord]) -> list[ArtifactMirrorRecord]:
    return [record for record in records if record.status != "mirrored"]


def _mirror_file_to_s3(
    *,
    path: Path,
    bucket: str,
    prefix: str,
    collection_id: str,
) -> ArtifactMirrorRecord:
    key = f"{prefix.strip('/')}/{collection_id.strip('/')}/{path.name}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        boto3 = importlib.import_module("boto3")
    except ModuleNotFoundError:
        return ArtifactMirrorRecord(
            run_id=collection_id,
            artifact_name=path.name,
            provider="s3",
            bucket=bucket,
            key=key,
            content_type=content_type,
            status="failed",
            error=(
                "boto3 is required for CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3. "
                "Install the aws extra with: pip install -e \".[aws]\""
            ),
        )
    try:
        boto3.client("s3").upload_file(
            str(path),
            bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
    except Exception as exc:
        return ArtifactMirrorRecord(
            run_id=collection_id,
            artifact_name=path.name,
            provider="s3",
            bucket=bucket,
            key=key,
            content_type=content_type,
            status="failed",
            error=str(exc),
        )
    return ArtifactMirrorRecord(
        run_id=collection_id,
        artifact_name=path.name,
        provider="s3",
        bucket=bucket,
        key=key,
        content_type=content_type,
        status="mirrored",
    )
