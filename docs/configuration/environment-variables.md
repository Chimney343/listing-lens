# environment variables

Runtime settings are loaded from `.env` at repository root by `config/settings.py`.

Start from `.env.example`.

## Supported variables

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `ENV` | `development` | No | Runtime profile (`development` or `production`). |
| `DATABASE_URL` | none | Yes for DB-backed flows | PostgreSQL DSN used by storage and queue flows. |
| `PHOTO_STORAGE_BACKEND` | `filesystem` | No | Photo storage backend (`filesystem` or `s3`). |
| `PHOTO_BASE_PATH` | `/mnt/nvme/photos` | No | Base path for filesystem photo storage. |
| `LOG_LEVEL` | `INFO` | No | Application log level. |
| `JSON_LOGS` | `false` | No | Structured JSON logs when true. |
| `PII_ENABLED` | `true` | No | Enables PII filtering in pipeline paths that support it. |
| `USE_DB_SLUG_QUEUE` | `false` | No | Switches slug handoff from file mode to DB queue mode by default. |

## Notes

- `DATABASE_URL` is required whenever commands touch PostgreSQL.
- Scheduler and spider commands can override behavior via CLI or `-a` arguments, but
  `.env` remains the default baseline.
- S3 variables are reserved in `.env.example` for future support and are not yet part
  of the typed settings model.
