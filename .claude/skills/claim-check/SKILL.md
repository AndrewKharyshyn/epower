---
name: claim-check
description: Check article claims against the current pipeline outputs using docs/claim_register.csv. Use when preparing or revising the manuscript.
---

`docs/claim_register.csv` columns: claim_id, claim_text, figure, source_json_path, source_value_at_check, master_md5_at_check,
checked_on, auditor_model, signoff_andrii, status.

1. `python tools/claim_check.py` compares each row's `source_json_path` value now vs `source_value_at_check`
   (reads `summary_arrays.json`) and lists rows whose source changed or path vanished.
2. For changed rows only: dispatch `research-director` with the old/new value, CI and the claim text; article-bound
   changes also get an Opus blind audit. Wording follows `CLAUDE.md` language discipline.
3. Update the row (value, md5, date, auditor, sign-off) only after Andrii signs off. The Ukrainian companion article
   is edited manually by Andrii.
