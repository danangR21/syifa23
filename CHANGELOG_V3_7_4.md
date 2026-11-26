# V3.7.4 – NDB + RAN Multi-Database Auto Detection

## NDB changes
- Detect and read every supported NDB workbook within the selected NDB Area.
- Populate Site and eNodeB selectors from all NDB workbooks in that area.
- During Site Audit, search every NDB workbook independently for the selected Site/eNodeB.
- Select matching source with largest matching row count; newest snapshot wins ties.
- Display all matching NDB sources in the audit.
- Multi-Site Scan uses the same independent NDB detection.
- Database Status lists every NDB workbook in the selected area.

## RAN
- Preserve V3.7.3 independent multi-database RAN auto detection.

## Integrity
- No NDB or RAN source workbook is merged, overwritten, or modified.
- NDB Area folder semantics remain unchanged.
- Existing QC, Dump Config, Alarm, TA, map, audit, approval and report modules are retained.
