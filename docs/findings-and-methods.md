# Findings and methods (imported from Claude memory `findings-and-methods`, last updated 2026-09-17)

Read before interpreting or citing any figure. Some items may be superseded by later CHANGELOG milestones; the CHANGELOG
and disk are ground truth. Items marked (verify) were written before M264-M299.

## Architectural discoveries
- The HV battery is a power buffer. At 80-120 km/h the engine is on but simultaneously discharging the battery (~49% mean
  deficit); the metric was later reframed (M41) as an engine-on discharge share (SoC steering + load-point quantisation +
  transient blending), not proof of generator saturation.
- At >=140 km/h acute continuous discharge depletes the buffer within seconds to minutes; the 170 km/h limiter is read as an
  electrical-architecture ceiling, not a tyre/RPM limit.
- SoC operating band ~44-88% (44.5 pp span). The BMS controls the ceiling via motored/unfuelled engine dissipation at SoC >= ~78-80%.
- P(engine start) differs by ~307x between stationary and highway at matched SoC (the ratio rests on 7 stationary events; report the Wilson CI).
- Engine RPM has discrete setpoints: dominant ~2,000 rpm (best-BSFC fixed point), plus governed setpoints ~1,500 and ~1,589 rpm.
- Series hybrid makes "net draw" meaningless as an efficiency metric; gross throughput per 100 km is the workload metric (M35).

## Generator/traction reconstruction: method rules
- Generator->traction energy is not uniquely identifiable from measured channels (no generator PID). Path B (measured fuel flow ->
  RPM/load-conditioned BSFC surface -> generator -> DC-bus balance) is cross-checked against an independent Path A (road-load)
  estimate. Report the disagreement; do not tune to agree.
- 217 g/kWh is a floor/optimum (Nissan Tech Review No.89, X-Trail-direct), never a flat conversion factor; it is the hard minimum
  of a load/RPM-conditioned BSFC surface. Tech Review No.90 (50%-efficiency concept engine) is NOT the X-Trail engine.
- Fuel basis is E10 (density 751 g/L; LHV 41.15 MJ/kg for chemical energy/thermal efficiency only). Cold gate is oil-primary
  (oil < 55 C, coolant fallback); the old coolant+restart-timer gate mislabelled every series-hybrid engine restart as cold.
- `[VCM] Motor RPM` is rejected (M102): a linear image of the mis-scaled torque register (r~0.997 with torque, r~0.02 with speed).
- Language discipline (brief section 19): every generator/traction figure is estimated/reconstructed/model-derived, never measured;
  "generator-coincident" f_gen is a net power-balance allocation, not electron tracing.

## Scientific-integrity caveats
- `CAP_KWH=2.1` is `verified:false`; all capacity-dependent metrics carry this caveat.
- TOST "not established" is not "no degradation": the window is too short, not a finding of zero effect.
- The 20,000 GTC threshold has no validated pack-rated provenance (`SCENARIO_THRESHOLD_GTC`, `verified:false`).
- Rainflow DoD: ~52.7% of cycles <= 2% DoD (verify against current payload); k=2 Woehler damage sum ~10x lower than gross FCE.
- CONFIRMED battery-current sign error in `recon_engine.py` (audit 2026-09-17; verify resolution in CHANGELOG M258+): the recon frame
  computed `Pbatt = +V*(I_raw - offset)` labelled "+discharge", while the main pipeline defines discharge-positive as
  `P = -I_raw*V` (compute_drive_summary_v6, "M11: BMS current is charge-positive"). Correct discharge-positive: `-I_raw - I_off`.
  Byte-exact self-reproduction of `fuel_recon_master.csv` cannot detect a convention error; per-drive anchoring to master totals
  preserved aggregate energy while swapping temporal phase. Corrected f_gen moved ~0.60 -> ~0.48-0.50; the buffer thesis survives/
  strengthens; prose must say "roughly half", not "the majority". The live payload (2026-09-25) carries generatorTractionRecon.corpus.fGen = 0.477.
- Lesson: reproducibility (same code, same bytes) is not correctness. Gates must include independent recomputation and convention checks.

## Methodological rules
- All displayed dashboard figures bind to pipeline-computed `S.*` keys; hardcoded literals are an anti-pattern.
- Day-clustered bootstrap (seed 42, 4,000 draws), TOST/MDE, day-blocked cross-validation are the statistical backbone.
- Never call `run_pipeline()` during arrays-only updates (prevents ML column refit); use the additive-splice pattern: compute only the
  changed key, deep-diff, leaf-level splice.
- `drive_master.csv` MD5 is the corpus integrity anchor, verified unchanged at every milestone.
- ML16 freeze/restore (16 ML/domain columns) is mandatory for every ingestion.
- Always read CHANGELOG from disk as ground truth; in-memory state is frequently stale.
- `recompute_m119v2=False` is the default for routine ingestion (~11-12 min); `True` only on explicit request.
- Use `pdftotext -layout` for PDF text extraction; `str_replace` on multi-line targets must match byte-for-byte.
- jsdom validation: cycle all tabs with a full `await sleep(300)` per tab before targeting specific content.
- `_artifact_stamp` must be called after `constantProvenance` is assembled in the `arrays` dict.

## Multiplicity policy (M330, F30.r5)
- Exploratory families are labelled exploratory and carry no family-wise claim.
- A formal claim names ONE pre-registered primary estimand per family (spec before data, blind audit, Director decision).
- Secondary and sensitivity results are reported with their intervals and are never promoted after the fact.
- Method disagreement (for example Path A vs Path B) is reported, not tuned away.
