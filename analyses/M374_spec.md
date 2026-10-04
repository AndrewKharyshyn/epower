# M374 spec: import guard for wire_gtr_seasonal.py (hazard found in M372)

Status: tooling only (Sonnet, medium per the effort table; known-answer test; no blind audit and no Director review: no figure, estimator, payload value or dashboard text changes).

## Defect (confirmed in M372)
`wire_gtr_seasonal.py` ran its whole wiring at import time. Any importer (`refresh_gtr_headline.py`, the M372 inventory attempt) therefore REWROTE `summary_arrays.json` as a side effect: re-created the `seasonalCharts.charts.GeneratorTractionRecon` entry from the payload's own `generatorTractionRecon` values and dumped the payload in compact form (a 139k-line diff when it happened by accident).

## Analysis before the change (so it cannot alter ingestion)
- `refresh_gtr_headline.py` imports `aggregate, wavg`, then recomputes and overwrites `generatorTractionRecon.{corpus, flows, driveTypeSplit, ...}` and `seasonalCharts...GeneratorTractionRecon.data.{all, warm, shoulder}` itself and writes the payload; the import-time wiring was therefore redundant for it. The only thing the import could change in the payload is the entry's metadata literals (`dependencyClass`, `pipelineClass`, `statisticalUnit`): the payload already holds exactly these values (checked equal).
- Control run of the real stage `refresh_gtr_headline.py` in two scratch directories on identical copies of the inputs, with the OLD module and the GUARDED module: the output `summary_arrays.json` is BYTE-IDENTICAL (sha256 f54df87a129091ec..., 1,694,467 bytes, both).

## Change
`wire_gtr_seasonal.py`: `wavg` and `aggregate` stay at module level (bodies carried over verbatim by script); the wiring moves into `main()` under `if __name__ == "__main__":`; the entry metadata literals become `ENTRY_META` (identical values) so a test can assert that the payload still carries them. `python wire_gtr_seasonal.py` behaves as before.

## Controls
`tests/synthetic/test_wire_gtr_import_guard.py`: (a) an import leaves the payload byte-identical and prints nothing; (b) `ENTRY_META` equals the payload's entry metadata (drift guard); (c) the script entry point still writes the entry; (d) `refresh_gtr_headline.py` still runs against the guarded module and is idempotent. `release_check.py`; payload, dashboard and `drive_master.csv` untouched.

## Out of scope
The `tools/m349_nan_offset_effect.py` exec workaround stays (it works unchanged); any change to how ingestion orders its stages.
