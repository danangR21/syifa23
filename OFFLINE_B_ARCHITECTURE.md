# RAN Concheck V3.7.5 BOTH — Offline Desktop + Android Design

## Confirmed product decision
- Windows desktop remains the baseline application and retains its existing QC behavior.
- Android is a dedicated native offline client; it is not a remote viewer of the desktop.
- Each device owns its own local source database and audit history.
- Daily database updates are manual, using a portable ZIP snapshot.
- No VPS, VPN, cloud database, or runtime internet dependency.

## Source snapshot format
A ZIP file must contain:
- database_Concheck/01_NDB/
- database_Concheck/02_RAN_Report/
- database_Concheck/03_Dump_Config/
- database_Concheck/04_Alarm/
- database_Concheck/05_TA/

Allowed source extensions: xlsx, xlsm, xls, csv.
The ZIP is a full snapshot, not an incremental patch. A new snapshot is staged and validated before activation. The previous active snapshot is retained as rollback material.

## Desktop implementation in this increment
`core/database_update.py` validates the ZIP structure, rejects path traversal and encrypted archives, enforces file-count/size limits, stages extraction, then atomically activates the replacement with a `.previous` rollback folder.

## Android implementation in this increment
`mobile_android/` contains a native Kotlin shell and an offline ZIP validation flow. This is only a foundation; it is not yet a production APK and does not yet run the complete QC engine.

## Database ownership
- Windows: existing `database/concheck_history.db` remains in place and is not overwritten by source snapshot import.
- Android: a separate app-private SQLite audit-history schema is included in the Android scaffold; its runtime use by the QC workflow is not yet integrated.
- Updating one device does not update the other device.
- Export/import of audit history between devices is not included unless separately requested.

## QC parity gate
Android must not be declared ready until the same synthetic golden test cases produce equivalent NDB/RAN comparison statuses, duplicate/conflict findings, alarm summaries, TA summaries, approvals, and report contents as Windows.
Manual review remains mandatory for unresolved identity conflicts. No automatic conflict winner selection is allowed.

## Security and operational safeguards
- Never package live operator data or the Windows history database inside the APK.
- Source files remain read-only; imported snapshots are copied to app-managed storage.
- Validate before replacing active data; preserve rollback.
- Keep each user's data local to their device.
- APK must be signed and tested on physical Android hardware before distribution.

## Delivery status
This increment provides the desktop snapshot updater and Android import-validation scaffold. It does not claim a complete offline Android QC application or an installable APK yet.
