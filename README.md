# RAN Concheck Analyzer V3.7.4

Automated RAN QC application built on the V2 baseline. This release does **not** use AI, cloud AI, Ollama, or any inference service. All validation and summaries are rule-based and deterministic.

## V3.6 features

1. **Existing V2 workflow retained**
   - Site / eNodeB / Alarm Source selection and SCAN SITE.
   - NDB vs RAN Report validation for 2G, 4G, and 5G using the configured mappings.
   - Current Alarm review with Name and Clearance Status.
   - Dump Config read-only viewer (no parameter validation).
   - TA distribution chart and reference-ring map.
   - Source manifest and SQLite audit history.
2. **NDB Multi-Database Auto Detection (V3.7.4)**
   - Detects every supported NDB workbook in the selected Area, including multiple files in the same folder.
   - Site and eNodeB selectors use the available records across all NDB files.
   - SCAN SITE searches each NDB workbook independently; no source files are merged.
   - When multiple files match, the source with the largest matching row count is selected; newest snapshot wins ties.
   - All matching NDB source files are shown in the audit and Source Manifest.
   - Files directly under `01_NDB/` appear as `Default / Root`; subfolders remain separate Areas.
3. **Compliance Score**
   - Parameter compliance counts mapped checks with values on both sides.
   - Cell match rate, missing cells, extra cells, and duplicate findings are separate metrics.
4. **Multi-Site Scan**
   - Sequential batch scan by selected NDB Area.
   - Each eNodeB is audited separately; an error on one site does not stop the batch.
   - Batch summary can be downloaded as CSV and is recorded in SQLite.
5. **Alarm Intelligence**
   - Severity distribution and Cleared / Uncleared counts.
   - Uncleared alarms are recorded as QC findings.
   - No automatic causal network-impact claim is made.
6. **TA Insight**
   - TA Index0–11 counts and percentages.
   - Dominant TA index and P50/P80/P90/P95 estimated distances.
   - Insight defaults to the latest available TA date.
   - TA distance is an estimate using a configurable bin step; confirm the step against the vendor/operator KPI definition.
7. **Site Configuration Map**
   - Site pin uses NDB longitude / latitude.
   - Sector wedges are drawn only if an azimuth field is available.
   - Recognized azimuth fields: `AZIMUTH`, `AZIMUTH_DEG`, `ANTENNA_AZIMUTH`, `BEARING`.
   - Beamwidth/radius defaults are illustrative only when their source columns are absent.
   - TA rings are distance references, not UE GPS points or actual coverage polygons.
8. **Historical Audit**
   - Recent audit history and two-run delta comparison.
   - V2 `audit_runs` table is preserved; V3.6 adds tables through additive migration.
9. **Manual QC Approval**
   - Reviewer can set APPROVED, REJECTED, or NEEDS REVISION with remarks.
   - Approval is stored against the Audit Run ID.
10. **Excel + PDF Report**
    - Final report generation is enabled only after the current run is manually APPROVED.
    - Excel includes summary, findings, cell comparison, alarm, TA, source data, and manifest sheets.
    - PDF includes summary, findings, alarm, TA, and approval details.
    - Reports are saved under `output_Concheck/<SITE>/` and can be downloaded from the app.

## Folder structure

```text
RAN_Concheck_Analyzer_V3_6/
├── app.py
├── modules/
│   └── v36_features.py
├── config/
│   └── audit_rules.json
├── database_Concheck/
│   ├── 01_NDB/
│   ├── 02_RAN_Report/
│   ├── 03_Dump_Config/
│   ├── 04_Alarm/
│   └── 05_TA/
├── database/
├── output_Concheck/
├── logs/
├── tests/
├── requirements.txt
└── Run_Concheck.bat
```

## Run on Windows

1. Extract the complete ZIP to a writable local folder.
2. Keep source files in their respective `database_Concheck` folders.
3. For area-based NDB, create a subfolder per Area inside `01_NDB`.
4. Double-click `Run_Concheck.bat`.
5. First launch creates `.venv` and installs requirements. Internet is needed for initial package installation; after packages are installed, app validation/reporting is local.

Recommended: Python 3.10 or newer. The app is designed for local Windows use. Do not place the working database on a network share while multiple users are writing to it.

## Data selection rules

- NDB: latest snapshot within the selected Area.
- RAN Report: latest snapshot globally.
- Alarm: merge all supported files/sheets and remove exact duplicate rows.
- TA: merge all supported CSV files and remove exact duplicate measurement rows.
- Dump Config: merge all workbook sheets as read-only viewer data.
- Source files are never edited by the application.

## Database compatibility

- Existing `database/concheck_history.db` and V2 `audit_runs` are preserved.
- New tables (`audit_findings`, `qc_approvals`, `report_history`, `multi_site_batches`, `schema_migrations`) are created additively.
- Keep a backup of the entire application folder before replacing an older version.

## Validation notes / limitations

- Parameter mappings are the initial mapping set based on the supplied sample workbook. Review `config/audit_rules.json` before production sign-off.
- A compliance percentage is calculated only over mapped checks with values available on both sides. Missing/extra cells and duplicates are shown separately.
- Alarm severity is descriptive; an alarm is not automatically attributed to a specific cell unless the source fields support that association.
- TA percentile distance is an approximate histogram-bin estimate, not a measured UE distance or UE location.
- Site sector wedges are displayed only when an azimuth field exists. Missing beamwidth/radius values use illustrative defaults and must be reviewed.
- Runtime testing with the full Streamlit UI requires installing `requirements.txt` on the target Windows PC. Source compilation and focused module tests are performed during packaging; local runtime behavior can still depend on the user's Python environment and source files.

### V3.6.1 Dump Config Explorer
The Dump Config Viewer now provides a telecom-themed command explorer with LTE/NR identity, summary metrics, command and NE selection, parameter/value search, selected-record detail, source metadata, and raw CSV export. It remains read-only and does not modify source dump workbooks.

### V3.6.2 Performance Optimization
- **SCAN SITE no longer parses the full Dump Config database.** This prevents a large collection of Huawei dump workbooks and sheets from blocking the main NDB/RAN + Alarm + TA scan.
- Dump Config remains available in the `Dump Config Viewer` tab and is loaded only after clicking **LOAD DUMP CONFIG FOR THIS SITE**.
- Alarm and TA aggregate datasets use Streamlit cache keyed by source path, modification timestamp (nanosecond precision), and file size. Updated or added files invalidate the corresponding cache.
- The Dump Config viewer dataset is cached after the first explicit load; source workbooks remain read-only.
- New regression tests verify that Dump Config loading stays outside the SCAN SITE handler.


## V3.7.4 release note
NDB and RAN Report now both use independent multi-database auto detection. NDB selection remains Area-aware. Source workbooks are read-only and never merged.
