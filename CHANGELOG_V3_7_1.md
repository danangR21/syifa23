# V3.7.1 – Dump Config Professional Viewer

## Dump Config presentation changes
- Replaced the plain wide-table-first presentation with a telecom configuration explorer layout.
- Added custom RF/network tower SVG identity mark and LTE/NR/RF/read-only badges.
- Added compact command/site/NE/parameter summary cards.
- Added focused default grid columns and optional full-column view.
- Added adjustable page size and clearer record-range indicator.
- Grouped selected-record parameters into Identity & Network Element, RF & Antenna, Operational Status, and Other Parameters.
- Added record identity and source-information panels.
- Kept full raw selected-command data in a collapsed section with full CSV export.
- Preserved search-first behavior: command sheet data is loaded only after the user searches/selects a command.
- Preserved read-only source handling; no source workbook is modified.

## Preserved modules
- SCAN SITE and existing NDB vs RAN checks.
- Current Alarm, TA, audit history, QC approval, Excel/PDF reporting.
- Search-Only Dump Config engine and file-signature cache.

## Validation
- Python compile check: PASS.
- Unit tests: 6/6 PASS.
- Streamlit visual runtime test: not performed in this build environment; please verify on the target Windows laptop.
