# Study overview (imported from Claude memory `overview`, last updated 2026-09-20; trimmed of stale "current state")

For the CURRENT state run `python tools/state.py` (as of 2026-09-25: CHANGELOG head M294-M299, 446 drives, `drive_master.csv` MD5 `0bcfc400d8ce2a0b15cdc7f3ddd8efff`).

## Purpose and thesis
Longitudinal OBD-II telemetry study of a Nissan X-Trail T33 e-POWER (FWD), a series hybrid whose HV battery works as a power buffer, not an energy reservoir.
Evidence: narrow SoC band (~44-88%), high-speed engine-on discharge share, buffer-impulse transients at engine starts, SoC-gated engine control.
Targets: Applied Energy or IEEE TVT. Interactive React/JSX dashboard (`xtrail_summary.jsx` -> `xtrail_dashboard.html`). The Ukrainian companion article is manual and out of scope for code changes.

## Vehicle and hardware
- X-Trail T33 e-POWER FWD, registered 2024-08-07. HV pack ~2.1 kWh, NMC-family, 96S (`CAP_KWH=2.1`, `verified:false`). Cell supplier Vehicle Energy Japan (VE-J).
- `VEHICLE_MASS_KG` is class-conditional (M124): highway/mixed_highway 2000 kg; urban/mixed 1860/1920 kg per filename MD5.
- Two-pass current-sensor offset ~ -0.4 A (recalibrates each ingestion); FWD estimate is SoC-anchored.

## e-4ORCE cross-validation rail
- 9 AWD drives on a segregated rail (`ingest_e4orce.py`, `crosscheck_vehicles.py`); pack shared with the FWD car; CAP-dependent columns admitted via `_CAP_ADMITTED` (M128/M135).
- Self-estimated offset -0.5474 A (CI [-0.70, -0.29]); main-rail -0.4130 A lies inside. Cross-vehicle analyses #1-#5 complete (M129-M133); #6 (acceleration) permanently deferred (AWD-confounded).

## Generator->traction reconstruction sub-study
- Model-derived (Path B: fuel flow -> BSFC surface with 217 g/kWh floor -> generator brake -> DC-bus balance), modules `fuel_recon.py`, `recon_engine.py`, `model_constants.py`; `drive_master.csv` read-only.
- Fuel channel caveats: fuel-flow PID on a minority of drives (urban/cold-skewed); highway f_gen rests on few drives.
- P_aux is directly measured at standstill (Parasitic Draws / `auxLoadAmbient`, median ~1.2 kW, scaling 1.0->1.9 kW with ambient); in-motion aux is not separable.
- History: the M245-M249 headline f_gen 0.60-0.69 was invalidated by a battery-current sign error (see findings-and-methods.md); live payload f_gen = 0.477 (2026-09-25).
- Pending: BEV side-by-side (section 17); engine load/MAP in `classify_regime()`; E10-vs-E0 anchor residual; fuel/oil/AFR/MAP pipeline integration; rebuilding per-second sub-analyses (speedSplit, simultaneity, crossval, rpmFinding, sensitivity) to the current basis (files `speed_split.py`, `simultaneity_gtr.py`, `crossval_gtr.py`, `sensitivity_gtr.py`, `rpm_opt_pass.py` now exist).

## Statistics and degradation
- Power fade (`powerFade`, cadence-controlled, primary): slope +0.013 mOhm/month, CI spans zero (values as of 2026-09; regenerate). `resistanceVreg` (cadence-uncontrolled) is sensitivity only. Cell-spread trend: cluster-robust OLS (authoritative), CI spans zero.
- TOST bounds locked at M108 (cell-spread 0.2315 mV/month, resistance 0.5439 mOhm/month): verdict "not established, window too short".
- Energy MC policy (M217): full recompute every ingestion.
- RPM histogram: the 1,400-1,600 rpm bin split into two setpoints (~1,500 and ~1,589) at M218.
- Enhancement plan M220-M228 and the independent audit (33 findings F01-F33) closed except F02 (needs an unavailable raw archive).
- M119-v2 (socHysteresisV2) fully recomputed at M264 on 410 drives; `recompute_m119v2` stays False for routine ingestion.

## Known artifacts
- `degradation_trends.json` is an orphaned stale snapshot (decision pending: regenerate, retire, or document).
- `corpus_manifest.py` `_classify()` misclassifies e4orce masters as auxiliary raw drives; use a clean `raw_only/` directory as `raw_dir`.

## Article audit (current)
Verdict: "scientifically promising, substantial revision required" (methodological backbone unusually strong). Remaining: three-way EFC disambiguation (FCE / standard EFC / Rainflow-EFC);
stationary-start ratio rests on 7 events (Wilson CI ~160x-760x); Wikner (Chalmers 2017) source cell is a large-format NMC/LMO pouch (different chemistry/duty class); corpus-size/date reconciliation across sections;
code<->dashboard<->article consistency pass once the manuscript is provided.
