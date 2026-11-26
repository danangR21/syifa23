# RAN Configuration Workbench – Blueprint

## Product direction
Dark Enterprise, local-first, read-only source data, deterministic QC, manual approval, modular monolith.

## Release roadmap
- V3.7: Workbench Foundation and UI design system.
- V3.8: Configuration Lab (site/device/sector comparison).
- V3.9: Antenna & RET Intelligence.
- V4.0: Network Topology and Geographic Explorer.
- V4.1: Advanced QC & Audit.
- V4.2: Engineering Intelligence and Reporting.

## Non-negotiable invariants
1. SCAN SITE must not parse Dump Config workbook contents.
2. Dump Config remains search-first and selected-sheet-only.
3. Original XLSX/CSV source files are read-only.
4. Existing QC, alarm, TA, history, approval and reporting features must pass regression tests.
5. Database migrations must be additive and backward-compatible.
6. New features must be isolated behind module/service interfaces.

## Target architecture
- `ui/`: theme, layouts, reusable components and navigation.
- `core/data/`: file registry, command index, cache and query services.
- `core/engine/`: comparison, correlation and deterministic rules.
- `modules/`: Dump Explorer, Configuration Lab, Antenna, Topology, QC, Analytics and Reports.
- `database/`: SQLite metadata/history; original files remain in `database_Concheck/`.

V3.7 only introduces the UI foundation. The deeper code migration is deliberately staged to avoid destabilizing the working V3.6.3 engine.
