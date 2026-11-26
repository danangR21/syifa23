# RAN Concheck Analyzer V3.7.5 BOTH Foundation

This is an isolated development foundation derived from the uploaded V3.7.4 source archive.

## Important
- Do not overwrite the V3.7.4 production folder with this package.
- This package intentionally excludes operator source data, live SQLite history, output reports, logs, `.venv`, and Python caches.
- To run the desktop app, first provision the required source-data folders and restore a separately backed-up history DB only in an approved environment.
- Default paths preserve the original V3.7.4 folder layout. VPS paths can be configured through environment variables.

## Windows desktop
1. Install Python 3.10+.
2. Provision authorized source data under `database_Concheck/`.
3. Restore `database/concheck_history.db` from a verified backup if continuing an existing environment.
4. Run `Run_Concheck.bat`.

## API development smoke test
1. Install requirements in a dedicated virtual environment.
2. Set `RAN_API_TOKEN` to a long random secret in the server environment.
3. Run `uvicorn api.main:app --host 127.0.0.1 --port 8000`.
4. Check `/health` and `/api/v1/version`.
5. Call `/api/v1/me` with `Authorization: Bearer <token>`.

Do not expose the development API directly to the public internet. Put it behind Nginx, HTTPS, firewall rules, and private VPN access.

## Hybrid database status
- Existing SQLite history is retained; no data migration is performed.
- `database/postgres_metadata_schema_v1.sql` is a reviewed-schema starting point only and is not automatically executed.
- PostgreSQL integration and role/session services are future gated work.
\n\n## Offline Desktop + Android direction\nSee `OFFLINE_B_ARCHITECTURE.md`. This release adds a validated full-snapshot updater for Windows and a native Android import-validation scaffold. Android QC execution and APK packaging are not complete yet.\n