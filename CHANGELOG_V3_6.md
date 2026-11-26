# V3.6 Final Release Changelog

- Removed all AI / local model / cloud inference dependencies and workflows.
- Preserved the V2 scan workflow and existing source-folder conventions.
- Added NDB Area selection using subfolders under `01_NDB`.
- Added parameter compliance and cell match-rate metrics.
- Added sequential multi-site batch scan and batch history.
- Added alarm severity summary and persistence of uncleared alarm findings.
- Added TA dominant index and P50/P80/P90/P95 estimated-distance metrics.
- Added site map with conditional sector wedges when NDB azimuth data exists.
- Added historical two-run comparison.
- Added manual QC approval workflow.
- Added Excel and PDF final report generation gated by APPROVED status.
- Added additive SQLite schema migration; existing `audit_runs` table is not dropped.

## V3.6.1 – Professional Dump Config Explorer
- Replaced the plain Dump Config expander list with a professional telecom-themed Huawei RAN Dump Explorer.
- Added LTE/NR visual identity, read-only indicator, command/NE selectors, summary metrics, parameter search, per-record parameter detail, source metadata, and raw-table/CSV export.
- Preserved original dump parsing and audit behavior; no source workbook write-back or configuration validation was added.

## V3.6.2 – SCAN SITE Performance Optimization
- Removed Dump Config workbook parsing from the SCAN SITE execution path. A large/multi-sheet dump database can no longer delay the core site scan just because the dump viewer is available.
- Dump Config is loaded on demand from an explicit button inside Dump Config Viewer; the existing read-only command explorer, site/eNodeB filtering, parameter detail, raw table and CSV exports remain available.
- Added Streamlit aggregate caching for Alarm and TA datasets using source fingerprints (path, nanosecond modification time, and file size).
- Added fingerprint-based caching for the Dump Config viewer dataset; changed/added source files produce a new cache key.
- Bounded aggregate cache entries to reduce unbounded memory growth.
- Added performance regression tests to ensure SCAN SITE does not eagerly invoke the Dump Config loader.
