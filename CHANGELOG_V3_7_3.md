# V3.7.3 – RAN Report Multi-Database Auto Detection

- NDB site dropdown remains sourced from the selected NDB snapshot.
- Database Status lists every workbook in `database_Concheck/02_RAN_Report`.
- SCAN SITE checks each RAN workbook independently using the inferred RAT sheet and existing site/eNodeB filters.
- No source workbook is concatenated, modified, or merged.
- If multiple files match, one source is selected by highest matching-row count; ties prefer the newest snapshot. All matching sources and row counts are shown in the audit.
- Multi-Site Scan uses the same auto-detection function and records the selected source.
- NDB latest-per-area, Dump Config, Alarm, TA, QC, compliance, approvals, history, map, and reporting workflows are retained.

Validation: syntax compilation and existing unit tests are run during packaging. Runtime behavior still requires verification on the target Windows laptop and its database folder.
