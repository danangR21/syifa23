# V3.7.4 Hotfix 1 – NDB Auto Detection Audit Flow

- Fixed NameError caused by stale `site_ndb` reference in single-site audit.
- NDB source is now detected before RAT inference; RAT is inferred from the selected matching NDB rows.
- Applied the same corrected order to Multi-Site Scan (removed stale `site_rows` reference).
- No source database files or workbook contents are changed.
