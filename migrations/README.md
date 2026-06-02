# Database Migrations

AI ContentOps Studio keeps local development zero-config by allowing the repository layer to
create tables for SQLite. Production and shared environments should run Alembic migrations before
starting API or worker tasks.

```powershell
$env:CONTENTOPS_DATABASE_URL="postgresql+psycopg://contentops:password@host:5432/contentops"
alembic upgrade head
```

The migration environment reads `CONTENTOPS_DATABASE_URL` through `contentops_core.settings`.
For local checks, unset it to use `sqlite:///contentops.db` or point it at a temporary SQLite file.
