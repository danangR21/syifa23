# V3.7.5 BOTH Foundation — Increment 1

## Decisions
- Hybrid database strategy selected.
- Existing V3.7.4 SQLite audit history remains preserved and authoritative for legacy history.
- PostgreSQL is reserved for new shared identity/session/job/upload metadata in a later VPS phase.
- Dedicated mobile UI and private distribution remain the product direction.

## Implemented in this foundation package
- Added `core/settings.py` with environment-based data, output, SQLite history, and log paths.
- Updated only the path constants in `app.py`; defaults are identical to the V3.7.4 relative paths.
- Added FastAPI service skeleton: `/health`, `/api/v1/version`, and token-protected `/api/v1/me`.
- API token guard fails closed when `RAN_API_TOKEN` is not configured.
- Added PostgreSQL metadata schema proposal as SQL only; it is not auto-applied.
- Added `.env.example` and API development launcher.
- Added API foundation tests.
- Preserved the original QC functions and existing V3.7.4 modules.

## Not yet implemented
- Full username/password login, role-based authorization, password reset, session lifecycle.
- PostgreSQL connection, migration runner, and production backup/restore.
- API endpoints for site search, SCAN SITE, uploads, approvals, and report downloads.
- Dedicated mobile frontend, PWA manifest/service worker, APK, and iOS wrapper.
- Live VPS deployment and multi-user load testing.

## Validation performed
- Python compileall: PASS.
- Existing V3.7.4 unit tests: 6/6 PASS.
- API health/version smoke test: PASS.
- Protected API endpoint without configured token: correctly returns 503 (closed by default).
- Streamlit interactive end-to-end workflow and Windows device test: NOT RUN in this environment.

## Safety
- Live source workbooks, operational databases, generated reports, logs, `.venv`, and Python caches are excluded from this development package.
- The uploaded V3.7.4 source archive is not modified.
