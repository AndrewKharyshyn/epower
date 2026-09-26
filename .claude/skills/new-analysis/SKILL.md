---
name: new-analysis
description: Add or change an analysis/method (new dashboard figure, new estimator, changed eligibility). Enforces a pre-registered spec, a blind audit and a Director decision before anything is published.
---

1. Write `analyses/M###_spec.md` BEFORE any result exists (dispatch `research-director` for review): estimand,
   population and eligibility, method, CI type, resampling unit (calendar day), primary vs sensitivity analyses,
   accept/reject thresholds, what would falsify the claim. Commit the spec; results reference its hash.
2. Implement as a script (Sonnet), emitting JSON: n_drives, n_days, estimate, ci95, method flags, provenance
   (master MD5, script sha). Add a known-answer test under `tests/synthetic/` when the estimator is new.
3. Run the validation chain: py_compile, JSON round-trip, `node build_html.js`, `node validate_jsdom.js`, isolation diff
   (only intended keys changed), `python release_check.py`.
4. Dispatch `analytical-auditor` with claim + data path only (blind). Article-bound or thesis-level: use an Opus audit.
5. Dispatch `research-director` with spec + result JSON + audit JSON + `data_health.json`. Record deviations from the spec.
6. Update the dashboard/CHANGELOG (`tools/changelog_draft.py`), commit, tag.
