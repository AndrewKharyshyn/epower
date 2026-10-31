# M549 blind-audit brief (claim and data path only)

Task: reproduce, from the raw drive CSVs alone, per-drive temperature-probe ranking counts for the 23 drives listed in `analyses/M549_audit_sample.json` (`files`, master keys; the raw file in `raw/` matches a master key by the digits of its file name, e.g. key `20260511_185709.csv` = `raw/2026-05-11 18-57-09.csv`). Do not read `tools/probe_ranking.py`, `compute_summary_arrays.py`, `analyses/M549_check*.json`, `probe_cache/` or `summary_arrays.json` (the claim under audit lives there).

Channels: the four HV-battery temperature probes `[BMS] HV Battery Temperature Sensor 1..4 (℃)` = T1..T4 (app-reported, logged). Conventions of record: `docs/conventions_of_record.md` sections 2 and 3 (native per-column forward fill, limit 15 rows; plausibility mask -40..90 C applied after the fill; time stamps parsed with mixed formats; rows with unparseable time dropped; then a 1 Hz grid: resample to 1 s bins, aggregator = the LAST value of the natively filled series inside the bin, then `ffill(limit=15)` on the grid). A grid second is valid when all four probes have a value.

Definitions, per valid grid second, with K = the set of probes whose value equals the maximum (hot) or the minimum (cold), k = |K| (exact float equality):
- unique(p): seconds with K = {p}.  tied(p): seconds with p in K and k >= 2.  anyTie(p) = unique + tied.
- fractional(p): sum of 1/k over seconds with p in K.
- tieTime: seconds with k >= 2.  validSeconds: seconds with all four probes valid.
- legacy first-index (diagnostic): on the NATIVE filled rows (before the grid) with all four probes valid, the count of rows in which the lowest-index probe among those at the extreme is p.

Return one JSON file `M549_audit_result.json` in the scratchpad: for each of the 23 keys: validSeconds, and for hot and cold, per probe: unique, tied, fractionalSeconds (float), and tieTime; plus legacy first-index counts per probe (hot, cold) and legacy row count. Report any ambiguity you had to resolve (and how) instead of silently choosing. Stop condition: the 23 drives; do not extend to the corpus.
