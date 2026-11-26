# V3.7 Foundation – RAN Configuration Workbench

## Included
- Dark Enterprise theme and reusable UI theme module (`ui/theme.py`).
- Workbench product header and sidebar branding.
- Updated workspace hierarchy and target network element section labels.
- Existing V3.6.3 Search-Only Dump Config engine retained.
- Existing QC, alarm, TA, history, approval and report modules retained.
- Original source workbooks remain read-only.

## Architecture decision
This is an incremental modular-monolith foundation. UI presentation has been extracted into `ui/`; data engines remain in the original application modules for this release to reduce regression risk. Future releases can migrate modules one at a time behind stable interfaces.

## Not yet included
Configuration comparison, antenna intelligence, topology explorer, and advanced audit enhancements are roadmap items, not claimed as implemented in this foundation release.
