# V3.6.3 – Search-Only Dump Explorer

- Replaced full Dump Config workbook loading with a command search workflow.
- Search accepts Huawei sheet/command names (e.g. `DSP RETSUBUNIT`) and submits on Enter.
- Command catalog reads only XLSX workbook metadata (`workbook.xml`); it does not parse all command sheets.
- After a command is selected, only that worksheet XML is streamed and rows are filtered to the selected site/eNodeB.
- XLSX command reading uses streaming XML parsing, avoiding loading the entire 87-sheet workbook into Pandas/openpyxl.
- Command results are cached by source file fingerprint, command sheet, and selected site.
- Data display is paginated at 100 rows; the raw preview is capped at 1,000 rows while CSV download includes all filtered records.
- SCAN SITE does not access Dump Config content. Source workbooks remain read-only.
