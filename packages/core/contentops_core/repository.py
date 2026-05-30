from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime, String, Text, create_engine, func, or_, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.sql import Select

from contentops_core.models import RunRecord, RunStatus


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    topic: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    artifact_dir: Mapped[str] = mapped_column(Text)
    published_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RunRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, future=True)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

    def save(self, run: RunRecord) -> None:
        with self.session_factory() as session:
            row = session.get(RunRow, run.id)
            if row is None:
                row = RunRow(id=run.id)
                session.add(row)
            row.topic = run.topic
            row.slug = run.slug
            row.status = run.status.value
            row.artifact_dir = str(run.artifact_dir)
            row.published_url = run.published_url
            row.error = run.error
            row.created_at = run.created_at
            row.updated_at = run.updated_at
            session.commit()

    def list(
        self,
        limit: int = 20,
        offset: int = 0,
        status: RunStatus | None = None,
        query: str = "",
    ) -> list[RunRecord]:
        with self.session_factory() as session:
            statement = (
                self._filtered_statement(status=status, query=query)
                .order_by(RunRow.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            rows = session.scalars(statement).all()
            return [self._to_record(row) for row in rows]

    def count(self, status: RunStatus | None = None, query: str = "") -> int:
        with self.session_factory() as session:
            statement = (
                self._filtered_statement(status=status, query=query)
                .with_only_columns(func.count(), maintain_column_froms=True)
                .order_by(None)
            )
            return int(session.scalar(statement) or 0)

    def get(self, run_id: str) -> RunRecord | None:
        with self.session_factory() as session:
            row = session.get(RunRow, run_id)
            return self._to_record(row) if row else None

    @staticmethod
    def _filtered_statement(status: RunStatus | None, query: str) -> Select[tuple[RunRow]]:
        statement = select(RunRow)
        if status is not None:
            statement = statement.where(RunRow.status == status.value)
        normalized_query = query.strip()
        if normalized_query:
            pattern = f"%{normalized_query}%"
            statement = statement.where(
                or_(
                    RunRow.id.ilike(pattern),
                    RunRow.topic.ilike(pattern),
                    RunRow.slug.ilike(pattern),
                )
            )
        return statement

    @staticmethod
    def _to_record(row: RunRow) -> RunRecord:
        return RunRecord(
            id=row.id,
            topic=row.topic,
            slug=row.slug,
            status=RunStatus(row.status),
            artifact_dir=Path(row.artifact_dir),
            published_url=row.published_url,
            error=row.error,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
