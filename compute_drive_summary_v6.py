"""
compute_drive_summary_v6.py  —  SELF-CONTAINED (v5 merged in, 2026-07-10)

Single-file pipeline. Formerly a strict wrapper that did
`import compute_drive_summary_v5 as v5`; the v5 module body is now inlined
verbatim, with its two public entry points renamed to _v5_analyze_bytes /
_v5_postprocess_master (v6 shadows both names) and its orchestration block
(build_master_from_raw / run_pipeline / __main__) removed in favour of the
v6 orchestration below. NO numerics were altered: the merge is verified
byte-exact against the two-file v6 output on drive_master.csv (107 x 143).
The import-and-call architecture is retained logically — v6 post-processing
still begins by calling the untouched v5 post-process — so M13-M19 remain
attributable to v5 and M23-M25 to v6.

======================================================================
M53 (2026-07-24) — PURE-ELECTRIC TRACTION CENSUS. Adds the ev_* per-drive
block (_ev_metrics, called from analyze_bytes alongside _vsag_metrics, so
the v5 byte-compat guarantee on _v5_analyze_bytes is untouched). Reports
engine-off distance share and longest contiguous engine-off run, on a 1 Hz
grid validated against the odometer per drive. EV state uses the existing
eng_rpm>400 engine-on threshold, so ev_* and engine_on_pct are complementary
by construction, and the M46/M48 motored-unfuelled state counts as ENGINE ON
(conservative). Emits its own validity gate (ev_valid) because the failure
mode -- a silent engine-channel gap reading as engine-off -- is
one-directional. See _ev_metrics docstring.

======================================================================
PART 1 — v6 additions (M23, M24, M25).  Audit 2026-07-09, n=107.
======================================================================
called, not copied) + methodology-audit additions (audit 2026-07-09, n=107):

  M23. INTENSITY-NORMALIZED ANOMALY TAXONOMY. The v5 M18 statistical
       detectors (IF/LOF/MAD) ran on absolute-magnitude features
       (gross_throughput_kwh, efc, ...), so the four longest highway drives
       (169-284 km) were flagged as "outliers" purely for being long —
       excluding 31% of valid 80-120 band time, 27% of throughput and 29%
       of distance from group stats, i.e. exactly the under-sampled
       stressor tail. v6 re-runs the same three detectors on an
       INTENSITY feature block (per-100km energetics instead of totals)
       and splits the flag semantically:
         f_iso_i / f_lof_i / f_mad_i   detectors on intensity features
         ens_invalid   = f_domain_2p   (hard physical rules only —
                                        data that is WRONG)
         ens_extreme   = >=2 statistical votes, not invalid
                                       (data that is UNUSUAL but real)
         ens_outlier_v2 = ens_invalid | ens_extreme
       ens_outlier_v2 is the new canonical exclusion for group statistics
       and trends; because size is normalized away, ordinary long drives
       are no longer flagged while per-km-artifact micro-trips still are.
       All v5 columns (f_iso, f_lof, f_mad, f_domain, ens_outlier,
       iso_outlier) are retained byte-compatible for v5 comparability.

  M24. TWO-PASS SoC-ANCHORED OFFSET. The v5 M13 offset (-0.4159 A on
       n=107) was estimated over ALL current-carrying drives, including
       domain-invalid ones (sign-check ANOMALY, PID-starved logs) whose
       residuals are junk; excluding ensemble outliers moved the estimate
       ~6% (-0.392 A). v6 iterates: estimate offset excluding f_domain
       rows -> recompute corrected residuals -> re-evaluate the domain
       rules (whose |residual|>0.35 kWh rule depends on the offset) ->
       re-estimate, to convergence (<=5 passes; converges in 1-2).
       New columns (v5 *_corr columns untouched):
         I_offset_2p_A_applied, offset_2p_kwh_removed,
         net_draw_kwh_corr2p, energy_residual_kwh_corr2p,
         net_draw_per100km_corr2p, f_domain_2p
       ASSUMPTION (article-explicit): the estimator anchors on the SoC
       ledger and assumes it is unbiased; any systematic key-on SoC
       re-estimation after rest aliases into I_off. Corroborated in sign
       and order of magnitude by the READY-idle calibration log.

  M25. V-SAG POWER-FADE PROXY (per-drive). Power fade from rising DC
       internal resistance is the study's declared functionally
       meaningful degradation mode, but no master column measured it.
       v6 adds a coarse per-drive pack-resistance proxy from co-timed
       BMS V/I samples:
         rest curve: median pack V vs SoC (0.5%-bins) over |Id| < 5 A
         load set:   discharge samples Id > 100 A with SoC inside the
                     rest-curve support (+/- 2%)
         sag        = V_rest(SoC) - V_load;  R = sag / Id
         vsag_R_pack_mohm = median(R)*1000 over plausibility-windowed
                     samples (0 < R < 500 mOhm)
       Columns: vsag_R_pack_mohm, vsag_R_iqr_mohm, n_vsag_load,
       n_vsag_rest, vsag_I_mean_A, vsag_soc_mean.
       CAVEATS (carried into the article): in-drive "rest" samples are
       not relaxed OCV (surface-charge/hysteresis bias, same sign every
       drive -> differences trend, absolute level is proxy-only); BMS I/V
       are asynchronously logged within +/-1.5 s alignment tolerance; the
       proxy pools SoC/temperature within a drive, so trending MUST
       control for pack temperature (R is strongly T-dependent). The
       postprocess report emits a T-controlled temporal trend with a
       day-cluster bootstrap CI (same protocol as M19); it does NOT
       replace the matched-condition dV/dI binning planned for a future
       version — it makes the power-fade axis non-empty until then.

Column policy: every v5 column retained byte-compatible (verified by the
regression harness in this batch); v6 only adds columns.
pipeline_version = 6.

======================================================================
PART 2 — v5 provenance (M1-M19), inlined verbatim below.
======================================================================
Per-drive metric extraction + master-level post-processing for X-Trail
e-POWER OBD logs.

v4 = v3 core (M1-M12, unchanged numerics) + methodology-audit corrections
(audit 2026-07-05, n=105 drives):

  M13. CURRENT-SENSOR OFFSET CORRECTION (SoC-anchored, master-level).
       The M8 energy residual is systematic, not noise: corr(residual,
       duration) = -0.86, corr(residual, throughput) = -0.89, and dataset
       net draw sums to -12.4 kWh over 54.9 h (a physically impossible net
       accumulation of ~5.9x pack capacity). A constant charge-biased
       offset in the BMS current PID is the parsimonious explanation.
       Estimator (discharge-positive frame):
         I_off = sum(energy_residual_kwh) * 1000 / (sum(duration_h) * V_w)
       anchored on the SoC ledger (soc_delta_kwh), which is independent of
       the current integral. Applied analytically per drive:
         net_draw_kwh_corr      = net_draw_kwh - I_off * V * h / 1000
         net_draw_per100km_corr = net_draw_kwh_corr / km * 100
         energy_residual_corr   = residual - I_off * V * h / 1000  (diag,
                                  must re-center near 0)
       Gross discharge/charge are NOT re-split (offset shifts the sign
       boundary second-order for |I_off| << typical |I|); the residual
       bias on cumulative throughput is bounded at ~2.9 % and is carried
       as article caveat #4. A dedicated key-on / engine-off /
       accessories-off calibration log supersedes this estimator when
       available (set I_OFFSET_CAL_A).
  M14. DEFICIT VALIDITY GATE. deficit_80_120_pct is a ratio of integrated
       seconds; below ~120 s of 80-120 km/h band time it is a single-digit
       -sample percentage and statistically meaningless (3 such drives in
       the v3 master). v4 keeps the raw ratio (deficit_80_120_pct, compat)
       and adds deficit_80_120_valid = band_80_120_s >= 120; aggregates
       must filter on the flag.
  M15. LOADED CELL-SPREAD DECONFOUNDING. Raw temporal trend of
       cell_spread_loaded_p95_mv (+0.61 mV/month) inverts to -0.40 mV/month
       once pack temperature and peak current are controlled for; recent
       >18 mV values are load/temperature artifacts of summer urban
       driving, not divergence. v4 fits, across the master,
         spread_p95 ~ b0 + bT * T_pack_mean_avg + bI * peak_I_discharge
       and stores cell_spread_loaded_p95_adj_mv = prediction-at-reference
       (T_ref = 25 C, I_ref = master median peak discharge) + residual.
       The degradation indicator must be trended on the _adj_ column.
  M16. ML SAMPLING LAYER (master-level).
       a) KMeans (k=3, standardized time-weighted speed features): the
          natural cluster structure of the fleet-of-one is k=3
          (silhouette 0.555 > k=4 0.490); rule-based 4-class labels are
          retained as the operational taxonomy (drive_type) and the
          data-derived cluster is stored as drive_cluster_k3
          (urban_like / mixed_like / highway_like by ascending
          cluster-mean moving speed).
       b) IsolationForest (500 trees, contamination 0.06) over the energy/
          stress feature block -> iso_outlier (bool) + iso_score. Per-type
          means, per-km energetics and indicator trends must exclude
          iso_outlier rows (prevents 0.9-km trips, stationary diagnostic
          logs and single extreme highway runs from biasing group stats:
          false-negative / false-optimistic control).

Column policy: every v3 column is retained byte-compatible; v4 only adds
columns. pipeline_version = 4.

v5 = v4 (unchanged numerics on all shared columns) + methodology-audit
additions (audit 2026-07-06, n=105 drives):

  M17. RAINFLOW CYCLE COUNTING on the raw SoC time series (ASTM E1049
       four-point, `rainflow` package). Captures partial-cycle and
       depth-of-discharge structure invisible to gross-throughput EFC.
       Amplitude floor RF_FLOOR_PCT = 1.0 % SoC (2x the 0.5 % PID
       quantization step; a 0.5 % "cycle" is one LSB of chatter).
       Validation on the 95-drive HV-current subset: cumulative
       rainflow-EFC = 111.9 vs coulometric FCE = 102.6 (ratio 1.09 at
       1.0 % floor, 1.02 at 1.5 %), per-drive corr = 0.997 — the SoC
       ledger and the current integral independently agree, closing the
       loop on M13. New columns: rf_efc (floor 1.0 %), rf_efc_f05
       (floor 0.5 %, sensitivity), rf_n_cycles, rf_dod_wmean_pct,
       rf_dod_max_pct, rf_damage_k2 = sum(count * DoD^2), a
       Woehler-type damage proxy (exponent RF_DAMAGE_EXP = 2,
       NMC-generic). Dataset rf_damage_k2 = 10.1 full-DoD-equivalent
       cycles vs FCE = 102.6: under a DoD^2 damage law the observed
       shallow micro-cycling duty (63 % of counted cycles <= 2 % DoD)
       is ~10x less damaging than the same throughput at full DoD —
       quantitative support for the power-buffer framing.
  M18. ENSEMBLE ANOMALY DETECTION (master-level), replacing reliance on
       IsolationForest alone:
         f_iso    IsolationForest (global unusualness, as v4)
         f_lof    LocalOutlierFactor, n_neighbors=15 (local density)
         f_mad    robust z (0.6745*(x-med)/MAD) > 4 on any energy/stress
                  feature (univariate physical extremes)
         f_domain hard physical rules: moved >5 km with throughput
                  <0.3 kWh; <1 km but >300 s (stationary diagnostic
                  log); sign_check == ANOMALY; current-PID starvation
                  (<100 samples over >600 s); |energy_residual_corr| >
                  0.35 kWh (ledger disagreement > 1/6 pack)
       Decision: ens_outlier = f_domain OR (>=2 of {f_iso,f_lof,f_mad}).
       On n=95: iso=6, lof=6, mad=22, domain=2 -> ensemble=10; all 6 v4
       iso flags retained, 4 added (three sub-1-km micro-trips with
       +25..30 kWh/100 km per-km artifacts that IF missed). Urban
       net_draw_per100km_corr SD drops 6.22 -> 3.79 after filtering.
       Group statistics and indicator trends must filter on ens_outlier
       (iso_outlier retained for v4 compatibility).
  M19. ROBUST CELL-SPREAD TREND WITH UNCERTAINTY. The M15 OLS
       adjustment is retained (column-compatible) and augmented with:
       Huber-regression adjusted column cell_spread_loaded_p95_adj_hub_mv
       (epsilon=1.35, resistant to leverage from extreme drives), and a
       cluster-by-calendar-day bootstrap (4000 resamples) of the
       temporal slope of the adjusted spread, reported with 95 % CI in
       the postprocess report. Audit result (ensemble-clean n=85):
       OLS -0.35, Huber -0.36, weighted-OLS -0.47, QuantReg(0.5) -0.78,
       MixedLM(day RI) -0.42 mV/month; bootstrap 95 % CI
       [-1.79, +0.73], P(slope>0)=0.27, MixedLM p=0.56. The correct
       article statement is "no detectable divergence trend"; any
       reported slope MUST carry the CI. Note corr(T_pack, I_peak) =
       0.63 (seasonal collinearity): with I in the model bT ~ 0; the
       adjustment is dominated by the current covariate.

Column policy: every v4 column retained byte-compatible; v5 only adds
columns. pipeline_version = 5. Dependency: pip install rainflow.

v5 addenda (not a version bump -- additive columns only, all v5 numerics
unchanged):

  M91 (2026-08-06). SoC-LEVEL (mean) decomposition of rf_damage_k2, per the
       Chalmers/Wikner (2017) cross-check: rainflow.extract_cycles() already
       yields (range, mean, count, i_start, i_end); M17 read only range and
       count. New columns rf_damage_k2_socband_{lo,mid,hi} split the existing
       rf_damage_k2 by cycle mean SoC (breakpoints RF_SOCLVL_LO_PCT=30,
       RF_SOCLVL_HI_PCT=50 -- Wikner's approximate, unverified-for-this-pack
       boundaries) and rf_socmean_wtd_pct is the count-weighted mean cycle
       SoC level per drive. Identity: rf_damage_k2_socband_lo +
       _mid + _hi == rf_damage_k2 (checked in the acceptance harness). This
       is a diagnostic SPLIT of the existing damage total, not a new damage
       law; any SoC-level WEIGHTING is computed downstream in
       compute_summary_arrays._soc_level_sensitivity() as an explicit,
       labeled, unverified sensitivity.
"""

# ======================================================================
# v5 CORE (inlined verbatim; M1-M19). Do not edit without re-running the
# byte-exact regression harness against drive_master.csv.
# ======================================================================


import pandas as pd
import numpy as np
import io

CAP_KWH = 2.1
DT_CAP_S = 5.0          # cap on integration step across logging gaps
V_ALIGN_TOL = '1500ms'  # I<->V alignment tolerance
ENG_ALIGN_TOL = '3s'    # engine-state alignment tolerance
SPREAD_TOL = '300ms'    # Vmax<->Vmin pairing tolerance

DEFICIT_MIN_BAND_S = 120.0   # M14 validity gate

# M41 (2026-07-17): decomposition thresholds for the engine-on discharge
# share (formerly "generator-saturation deficit"). See M41 block below.
BLEND_ACC_THRESH = 0.5       # km/h/s -- transient (accel/decel) gate
BLEND_I_THRESH_A = 30.0      # A -- high-current power-blend gate
SATUR_LOAD_PCT = 85.0        # calc engine load, % -- near-capability gate
SATUR_MIN_RUN_S = 5.0        # s -- sustained-run requirement
SPREAD_T_REF = 25.0          # M15 reference temperature, deg C
I_OFFSET_CAL_A = None        # M13: set from calibration log when available

RF_FLOOR_PCT = 1.0           # M17 rainflow amplitude floor, % SoC (2 LSB)
RF_FLOOR_SENS_PCT = 0.5      # M17 sensitivity floor (1 LSB)
RF_DAMAGE_EXP = 2.0          # M17 Woehler DoD exponent (NMC-generic)
# M91 (2026-08-06): SoC-level band breakpoints for the rf_damage_k2_socband_*
# split, from Wikner (Chalmers, 2017) 10%-SOC-interval lifetime cycling data
# (see full provenance note at the computation site below). UNVERIFIED for
# this pack -- diagnostic split only, not a damage law.
RF_SOCLVL_LO_PCT = 30.0      # M91: below this, Wikner's data show minimal aging
RF_SOCLVL_HI_PCT = 50.0      # M91: at/above this, aging accelerates in her data
MAD_Z_THRESH = 4.0           # M18 robust-z threshold
LOF_NEIGHBORS = 15           # M18
RESIDUAL_MAX_KWH = 0.35      # M18 ledger-disagreement rule (>1/6 pack)
N_BOOT = 4000                # M19 cluster bootstrap resamples
# M88 (2026-08-05): micro-move distance floor. Supersedes the old
# "distance<1.0km AND duration>300s" domain rule -- that rule let real
# short trips under a few minutes slip through uncaught while also
# catching nothing between 0.2 and 1.0km regardless of how long they took.
# A drive under this floor is treated as noise-floor (parking-lot
# maneuvering, GPS/odometer jitter at standstill), independent of duration.
MIN_DIST_KM = 0.2

# P0-12 (2026-07-30): rainflow was previously imported optionally and the
# per-drive rf_* columns were silently skipped when the package was absent.
# But category_A() in compute_summary_arrays.py accesses dm['rf_efc']
# unconditionally, so a missing package produced a partial (rf-less) master
# and then crashed the summary build AFTER the expensive raw extraction pass.
# rainflow is therefore a MANDATORY dependency. We import it eagerly and, if it
# is unavailable, fail loud at import time (before any processing) with an
# actionable message and the pinned version. Its resolved version is recorded
# in the build manifest by run_pipeline (see RAINFLOW_VERSION).
RAINFLOW_REQUIRED = "3.2.0"   # pinned; matches shipped rawManifest environment
try:
    import rainflow as _rainflow           # M17; pip install rainflow==3.2.0
    RAINFLOW_VERSION = getattr(_rainflow, "__version__", "unknown")
except ImportError as _rf_err:             # pragma: no cover
    raise ImportError(
        "The 'rainflow' package is a MANDATORY dependency of the X-Trail "
        "e-POWER pipeline (M17 cycle-counting; rf_* master columns are "
        "required by category_A of the summary generator). Install the pinned "
        f"version before running: pip install rainflow=={RAINFLOW_REQUIRED}. "
        "The pipeline refuses to emit a master that violates the summary "
        "schema."
    ) from _rf_err


def _assert_rainflow_ready():
    """Preflight gate: call BEFORE the raw extraction pass so a missing or
    mismatched rainflow build fails fast instead of after ~9 min of work."""
    if _rainflow is None:                  # pragma: no cover (import guards)
        raise RuntimeError("rainflow import guard failed unexpectedly.")
    if not hasattr(_rainflow, "extract_cycles"):
        raise RuntimeError(
            "Installed 'rainflow' lacks extract_cycles(); incompatible build."
        )
    if RAINFLOW_VERSION != RAINFLOW_REQUIRED:
        # Non-fatal but recorded: numbers can shift between rainflow releases.
        import warnings
        warnings.warn(
            f"rainflow {RAINFLOW_VERSION} != pinned {RAINFLOW_REQUIRED}; "
            "rf_* values may differ from the shipped basis.",
            RuntimeWarning,
        )

COL_MAP = {
    '[BMS] HV Battery Current (A)': 'I',
    '[BMS] HV Battery voltage (V)': 'V',
    '[BMS] HV State of charge (%)': 'soc',
    '[BMS] HV Battery Temperature Sensor 1 (℃)': 'T1',
    '[BMS] HV Battery Temperature Sensor 2 (℃)': 'T2',
    '[BMS] HV Battery Temperature Sensor 3 (℃)': 'T3',
    '[BMS] HV Battery Temperature Sensor 4 (℃)': 'T4',
    '[BMS] HV Battery Intake Air Temperature (℃)': 'T_intake',
    '[BMS] Max Cell Voltage (V)': 'Vcell_max',
    '[BMS] Min Cell Voltage (V)': 'Vcell_min',
    '[VCM] Vehicle Speed (km/h)': 'speed',
    # '[VCM] Motor RPM (rpm)' -> REJECTED in M102, see _REJECTED_CHANNELS below.
    '[VCM] Motor Torque (N⋅m)': 'motor_torque',      # measured; ~1/256 of true N·m (M102): valid but mis-scaled and currently unused -- multiply by ~256 to recover measured N·m; cf. target_torque
    '[VCM] Target Motor Torque (N⋅m)': 'target_torque',
    '[VCM] HV Coolant Temperature (℃)': 'T_coolant',
    '[VCM] Traction motor temperature (℃)': 'T_motor',
    '[VCM] HV Battery Available Charge Display (%)': 'soc_vcm',
    'Оберти двигуна (rpm)': 'eng_rpm',
    'Розрахунковий наддув (bar)': 'boost',
    'Температура охолодної рідини (℃)': 'T_eng_coolant',
    'Температура олії у двигуні (℃)': 'T_oil',
    'Пройдений шлях(загальний) (km)': 'odo',
    'Пройдений шлях (km)': 'dist_trip',
    'Швидкість автомобіля (km/h)': 'speed_obd',
    'Абсолютне значення навантаження на двигун (%)': 'eng_load_abs',
    'Розрахункове значення навантаження на двигун (%)': 'eng_load_calc',
    'Прискорення (g)': 'accel_g',
    'Середня швидкість (km/h)': 'speed_avg_trip',
    'Тиск у впускному колекторі (абсолютний) (kPa)': 'map_kpa',
}


# ---------------------------------------------------------------------
# M102 (2026-08-08) -- rejected raw channels.
# PIDs present in the logs that must NOT enter the working namespace
# because they do not carry the physical quantity their label claims.
# Held here (deliberately out of COL_MAP) so the rejection is explicit at
# the ingestion boundary and the channel can never be silently
# re-consumed. Full evidence and provenance: CHANGELOG.md M102.
# ---------------------------------------------------------------------
_REJECTED_CHANNELS = {
    # '[VCM] Motor RPM' is NOT traction-motor mechanical speed. On the
    # 209/214 FWD drives that carry it, it is a linear image of the torque
    # register: median corr with target_torque = 0.9975 (min 0.951; >0.99
    # on 91% of drives), while median corr with vehicle speed = 0.017
    # (p95|r| = 0.23). Numerically rpm ~ 64 x target_torque; it reads 0 at
    # standstill yet fluctuates with torque at constant cruise speed, and
    # runs ~5x too low in magnitude for real motor speed. The e-4ORCE rail
    # shows the identical artifact (r_ttq=0.987, r_spd=-0.11) -> systematic
    # logger/PID-definition fault, not drive- or vehicle-specific. No
    # shaft-power (tau*omega), reduction-ratio, or torque-RPM operating-map
    # metric is derivable from this PID.
    '[VCM] Motor RPM (rpm)': 'motor_rpm__REJECTED_M102',
}


def _series(df, t, col, lo=None, hi=None):
    """Extract one PID as a clean (t, value) frame on its native timestamps."""
    if col not in df.columns:
        return None
    m = df[col].notna()
    if not m.any():
        return None
    s = pd.DataFrame({'t': t[m].values, 'v': df.loc[m, col].astype(float).values})
    if lo is not None:
        s = s[s['v'] >= lo]
    if hi is not None:
        s = s[s['v'] <= hi]
    s = s.sort_values('t').reset_index(drop=True)
    return s if len(s) else None


def _asof(base, other, name, tol):
    """Align 'other' series onto base timestamps (nearest, within tolerance)."""
    if other is None:
        base[name] = np.nan
        return base
    return pd.merge_asof(base, other.rename(columns={'v': name}),
                         on='t', direction='nearest', tolerance=pd.Timedelta(tol))


def _tw_stats(s, dt_cap=DT_CAP_S):
    """Duration weights for a (t, v) series."""
    dt = s['t'].diff().dt.total_seconds().clip(upper=dt_cap).fillna(0)
    return dt


def classify_drive_type_tw(spd, w):
    """Time-weighted classification; percentages over moving time (v>=3).
    M115 (2026-08-10, Andrii's methodology decision): highway threshold
    lowered from >=100 to >=90 km/h. The prior >=100 km/h cutoff was a
    holdover from the original distance-based DIST_BINS taxonomy (see the
    CLASS_ORDER comment in compute_summary_arrays.py) and was never itself
    independently re-justified when that taxonomy was replaced by this
    time-weighted speed classifier. 90 km/h is Ukraine's default open-road
    (non-motorway) statutory limit, making it a more representative
    "highway-speed driving" cutoff for this corpus than the round 100 km/h
    figure. This is a raw-level definitional change: it alters drive_type,
    pct_highway, pct_urban for ALL 219 corpus drives (not just newly
    appended ones) and, through those, the KMeans drive_cluster_k3 features
    (M16a) -- see CHANGELOG M115 for the full re-derivation and validation
    procedure (full analyze_bytes reprocess of all 219 raw files, not an
    incremental append; corpus-total invariants -- distance/GTC/FCE sums --
    confirmed unchanged; only the class-conditioned breakdown shifts)."""
    moving = spd['v'] >= 3
    w_mov = w[moving]
    if w_mov.sum() <= 0:
        return 'unknown', None, None, None
    pct_hw = float((w_mov[spd['v'][moving] >= 90]).sum() / w_mov.sum())
    pct_ur = float((w_mov[spd['v'][moving] < 60]).sum() / w_mov.sum())
    avg_mov = float((spd['v'][moving] * w_mov).sum() / w_mov.sum())
    if pct_hw > 0.4:
        typ = 'highway'
    elif pct_ur > 0.6:
        typ = 'urban'
    elif avg_mov > 60:
        typ = 'mixed_highway'
    else:
        typ = 'mixed'
    return typ, round(pct_hw * 100, 1), round(pct_ur * 100, 1), round(avg_mov, 1)


def _m41_decompose(e, dts, band, eng_on, spd, load_s):
    """M41 (2026-07-17): decompose the engine-on discharge share in the
    80-120 km/h band. Sample-level re-analysis (Jun19 D1, Jun27 D3,
    Jul16 D4) showed the metric formerly framed as "generator-saturation
    deficit" is dominated by (a) SoC steering around the ~62% setpoint
    (discharge probability rises monotonically with SoC above ~63%,
    reaching 0.85-0.90 at SoC 70-80%) and (b) generator load-point
    quantization at steady cruise (median 9-17 A at ~38% calc engine
    load, p95 ~43% -- ample headroom), with a minority genuine
    power-blend component during transients. Returns dict of:
      engon_dis_share_80_120 -- semantic rename of deficit_80_120_pct
      blend_s_80_120         -- transient/high-current subset, s
      blend_share_80_120     -- blend_s / engine-on-discharge s, %
      steer_s_80_120         -- steady low-current remainder, s
      satur_80_120_s         -- true-saturation gate: calc load >
                                SATUR_LOAD_PCT AND Id > BLEND_I_THRESH_A,
                                in contiguous runs >= SATUR_MIN_RUN_S
    `spd` is the native-timestamp speed series (for dv/dt), `load_s` the
    native eng_load_calc series (may be None on early logs).
    """
    out = {}
    dis = band & eng_on & (e['Id'] > 0)
    dis_s = float(dts[dis].sum())

    # acceleration on the native speed base, asof-aligned onto e
    acc = None
    if spd is not None and len(spd) > 3:
        a = spd.copy()
        dt_a = a['t'].diff().dt.total_seconds()
        a['v'] = a['v'].diff() / dt_a
        a = a[dt_a.between(0.05, DT_CAP_S)]
        a = a[a['v'].abs() < 15]                    # physical bound
        if len(a):
            acc = _asof(e[['t']].copy(), a, 'acc', ENG_ALIGN_TOL)['acc']
            acc.index = e.index
    if acc is None:
        acc = pd.Series(np.nan, index=e.index)

    # engine load asof-aligned onto e
    if load_s is not None and len(load_s):
        load = _asof(e[['t']].copy(), load_s, 'ld', ENG_ALIGN_TOL)['ld']
        load.index = e.index
    else:
        load = pd.Series(np.nan, index=e.index)

    blend = dis & ((acc.abs() >= BLEND_ACC_THRESH) |
                   (e['Id'] > BLEND_I_THRESH_A))
    blend_s = float(dts[blend].sum())
    out['blend_s_80_120'] = round(blend_s, 1)
    out['steer_s_80_120'] = round(max(dis_s - blend_s, 0.0), 1)
    out['blend_share_80_120'] = round(blend_s / dis_s * 100, 1) \
        if dis_s > 0 else None

    # true-saturation gate: sustained near-capability generation with the
    # battery still discharging hard. Runs broken by condition dropout or
    # a logging gap > DT_CAP_S.
    sat_cond = (dis & (load > SATUR_LOAD_PCT) &
                (e['Id'] > BLEND_I_THRESH_A)).to_numpy()
    step_s = dts.to_numpy()
    gap = e['t'].diff().dt.total_seconds().fillna(0).to_numpy()
    sat_total = 0.0
    run = 0.0
    for i in range(len(sat_cond)):
        if sat_cond[i] and gap[i] <= DT_CAP_S:
            run += step_s[i]
        else:
            if run >= SATUR_MIN_RUN_S:
                sat_total += run
            run = step_s[i] if sat_cond[i] else 0.0
    if run >= SATUR_MIN_RUN_S:
        sat_total += run
    out['satur_80_120_s'] = round(sat_total, 1)
    return out


def _v5_analyze_bytes(csv_bytes, filename):
    """Per-drive extraction. Numerically identical to v3 for all shared
    columns; adds deficit_80_120_valid (M14) and rf_* (M17). pipeline_version = 5."""
    df = pd.read_csv(io.BytesIO(csv_bytes), low_memory=False)
    df = df.rename(columns={k: v for k, v in COL_MAP.items() if k in df.columns})
    t = pd.to_datetime(df['time'], format='mixed', errors='coerce')

    r = {'file': filename, 'pipeline_version': 5}
    r['n_raw_rows'] = len(df)
    r['time_start'] = str(df['time'].iloc[0]) if 'time' in df.columns else None
    r['time_end'] = str(df['time'].iloc[-1]) if 'time' in df.columns else None
    r['duration_s'] = round((t.max() - t.min()).total_seconds(), 1)

    # ---------- per-PID series (native timestamps) ----------
    I = _series(df, t, 'I')
    if I is not None:
        I = I[I['v'].abs() < 900]                     # artifact samples only
    V = _series(df, t, 'V', lo=200, hi=450)
    soc = _series(df, t, 'soc')
    spd = _series(df, t, 'speed', lo=0, hi=260)
    eng = _series(df, t, 'eng_rpm', lo=0)
    odo = _series(df, t, 'odo')
    vmax = _series(df, t, 'Vcell_max', lo=2.0, hi=5.0)
    vmin = _series(df, t, 'Vcell_min', lo=2.0, hi=5.0)

    r['n_I_samples'] = len(I) if I is not None else 0
    if I is not None and len(I) > 2:
        r['I_sample_period_s'] = round(
            I['t'].diff().dt.total_seconds().median(), 3)

    # ---------- M138: I<->V alignment-gap diagnostic ----------
    # Median I<->V nearest-neighbor timestamp gap, computed UNCONSTRAINED
    # by V_ALIGN_TOL (1500ms). Distinguishes a genuine I/V co-timing gap
    # (every candidate pair sits just outside tolerance -> _asof(...).
    # dropna() returns 0 rows -> the energy integral correctly sums to 0.0)
    # from ordinary current-PID starvation (too few I samples, full stop).
    # Purely additive/diagnostic: does not feed any energy/throughput/
    # domain-gating computation. See CHANGELOG M138.
    if I is not None and V is not None and len(I) > 0 and len(V) > 0:
        _iv = pd.merge_asof(
            I[['t']].sort_values('t').reset_index(drop=True),
            V[['t', 'v']].rename(columns={'t': 't_v'})
                .sort_values('t_v').reset_index(drop=True),
            left_on='t', right_on='t_v', direction='nearest')
        _gap = (_iv['t'] - _iv['t_v']).abs().dt.total_seconds()
        r['iv_alignment_gap_s'] = round(float(_gap.median()), 3)
    else:
        r['iv_alignment_gap_s'] = np.nan

    # ---------- distance ----------
    if odo is not None and len(odo) > 1:
        r['odo_start'] = round(odo['v'].iloc[0], 1)
        r['odo_end'] = round(odo['v'].iloc[-1], 1)
        r['distance_km'] = round(r['odo_end'] - r['odo_start'], 2)

    # ---------- speed (time-weighted) ----------
    speed_source = 'vcm'
    if spd is None or len(spd) < 20:
        spd_obd = _series(df, t, 'speed_obd', lo=0, hi=260)
        if spd_obd is not None:
            spd = spd_obd
            speed_source = 'obd_fallback'
    r['speed_source'] = speed_source
    if spd is not None and len(spd) > 2:
        w = _tw_stats(spd)
        r['speed_mean'] = round(float((spd['v'] * w).sum() / w.sum()), 1)
        r['speed_max'] = round(spd['v'].max(), 1)
        r['speed_p95'] = round(spd['v'].quantile(0.95), 1)
        r['stationary_pct'] = round(float(w[spd['v'] < 3].sum() / w.sum()) * 100, 1)
        typ, pct_hw, pct_ur, avg_mov = classify_drive_type_tw(spd, w)
        r['drive_type'] = typ
        r['pct_highway'] = pct_hw
        r['pct_urban'] = pct_ur
        r['speed_mean_moving'] = avg_mov

    if 'speed_avg_trip' in df.columns:
        a = df['speed_avg_trip'].dropna()
        r['speed_avg_trip_final'] = round(a.iloc[-1], 1) if len(a) else None

    # ---------- energy: trapezoidal on I time base, V aligned ----------
    if I is not None and V is not None and len(I) > 2:
        e = _asof(I.copy(), V, 'V', V_ALIGN_TOL).dropna(subset=['V'])
        e = _asof(e, eng, 'eng_rpm', ENG_ALIGN_TOL)
        e = _asof(e, spd, 'speed', ENG_ALIGN_TOL)

        # M11: BMS current is charge-positive; convert to discharge-positive.
        e['Id'] = -e['v']
        # Per-file verification: engine-off propulsion must be discharge.
        tq_s = _series(df, t, 'target_torque')
        r['sign_check'] = 'not_testable'
        if tq_s is not None:
            ev = _asof(e[['t', 'Id', 'eng_rpm']].copy(), tq_s, 'tq', '1500ms')
            m_ev = (ev['tq'] > 50) & (ev['eng_rpm'].fillna(0) < 400)
            if m_ev.sum() >= 5:
                med = float(ev.loc[m_ev, 'Id'].median())
                r['sign_check'] = 'ok' if med > 0 else 'ANOMALY'
        e['P'] = e['Id'] * e['V'] / 1000.0           # kW, +discharge
        # M229 (2026-09-06): F01 zero-crossing-aware directional integration.
        # PRIOR DEFECT: mid-power P_mid = (p0+p1)/2 was formed BEFORE the sign
        # split, so a within-interval discharge<->charge crossing cancelled in
        # gross throughput (the released method reported ZERO gross energy for a
        # +10->-10 kW second, which has 0.00138889 kWh of real gross activity).
        # FIX: under piecewise-linear power, integrate the positive (discharge)
        # and negative (charge) portions of each interval separately. For a
        # crossing interval with endpoint powers p0,p1 and duration d(h):
        #   gross = d*(p0^2+p1^2)/(2*(|p0|+|p1|)); the positive endpoint's
        #   square feeds discharge, the negative endpoint's square feeds charge.
        # Non-crossing intervals are byte-identical to the released trapezoid,
        # so the change is isolated to the defect; NET (disc-charge) is provably
        # preserved. Corpus effect: +32.2063 kWh (+2.5486%), 69,954 crossings,
        # +16.1032 kWh each side. Verified against independent audit recompute.
        dt_h = e['t'].diff().dt.total_seconds().clip(lower=0, upper=DT_CAP_S) \
                     .fillna(0) / 3600.0     # pandas Series (used downstream)
        _dt = dt_h.to_numpy()
        _P = e['P'].to_numpy()
        if len(e) < 2:
            # F10: I and V samples exist but no integrable I/V pairs remained
            # after alignment -> UNOBSERVED, not zero battery activity. Return
            # null with a reason rather than a spurious 0.0 kWh.
            for _k in ('gross_discharge_kwh', 'gross_charge_kwh',
                       'gross_throughput_kwh', 'net_draw_kwh', 'gtc', 'fce',
                       'net_draw_per100km', 'peak_discharge_kw',
                       'peak_charge_kw', 'peak_I_discharge', 'peak_I_charge'):
                r[_k] = None
            r['energy_null_reason'] = 'no_integrable_iv_pairs'
            r['n_sign_crossings'] = 0
        else:
            _p0 = np.nan_to_num(np.concatenate([[np.nan], _P[:-1]]), nan=0.0)
            _cross = (_p0 * _P) < 0
            _absum = np.abs(_p0) + np.abs(_P)
            _den = np.where(_absum > 0, 2.0 * _absum, 1.0)
            _disc_c = _dt * ((_p0 > 0) * _p0**2 + (_P > 0) * _P**2) / _den
            _chg_c = _dt * ((_p0 < 0) * _p0**2 + (_P < 0) * _P**2) / _den
            _signed = _dt * (_p0 + _P) / 2.0
            _disc = np.where(_cross, _disc_c, np.where(_signed > 0, _signed, 0.0))
            _chg = np.where(_cross, _chg_c, np.where(_signed < 0, -_signed, 0.0))
            r['gross_discharge_kwh'] = round(float(_disc.sum()), 4)
            r['gross_charge_kwh'] = round(float(_chg.sum()), 4)
            r['n_sign_crossings'] = int(_cross.sum())
            thr = r['gross_discharge_kwh'] + r['gross_charge_kwh']
            r['gross_throughput_kwh'] = round(thr, 4)
            r['net_draw_kwh'] = round(
                r['gross_discharge_kwh'] - r['gross_charge_kwh'], 4)
            # M56 (2026-07-26) / M95 (2026-08-07): 'gtc' (gross capacity
            # turnover) = throughput / ONE nominal pack energy. NOT the standard
            # full-equivalent-cycle count; 'fce' = throughput / (2 x nominal) is.
            # The legacy byte-identical alias r['efc'] was REMOVED in M95
            # (semantic trap for external readers); all consumers read 'gtc'.
            r['gtc'] = round(thr / CAP_KWH, 4)           # canonical
            r['fce'] = round(thr / (2 * CAP_KWH), 4)     # standard convention
            if r.get('distance_km') and r['distance_km'] > 0:
                r['net_draw_per100km'] = round(
                    r['net_draw_kwh'] / r['distance_km'] * 100, 2)

            r['peak_discharge_kw'] = round(e['P'].max(), 1)
            r['peak_charge_kw'] = round(e['P'].min(), 1)
            r['peak_I_discharge'] = round(e['Id'].max(), 1)
            r['peak_I_charge'] = round(e['Id'].min(), 1)

            # pack capacity in Ah from measured voltage (M3)
            v_nom = float(V['v'].median())
            cap_ah = CAP_KWH * 1000.0 / v_nom
            r['V_pack_median'] = round(v_nom, 1)
            r['cap_ah_est'] = round(cap_ah, 2)

            # integration-time base for the M13 analytic offset correction
            r['integr_time_h'] = round(float(dt_h.sum()), 4)

            # charge split by engine state (M5, legacy 2-way — retained for compat)
            # M229 (F22): the charge-SOURCE buckets now use the F01 per-interval
            # directional charge magnitude (_chg) instead of the released signed
            # step energy, so charge_eng_on + charge_eng_off == corrected
            # gross_charge and the energyPath partition residual returns to ~0.
            # Crossing intervals now contribute their charge PORTION to the
            # bucket for the engine/torque state at that interval, even when the
            # net step was discharge. Peak / C-rate rows below keep the per-row
            # masks unchanged (they are current thresholds, not energy sums).
            eng_on = e['eng_rpm'].fillna(0) > 400
            _eng_on = eng_on.to_numpy()
            r['charge_eng_on_kwh'] = round(float(_chg[_eng_on].sum()), 4)
            r['charge_eng_off_kwh'] = round(float(_chg[~_eng_on].sum()), 4)
            r['charge_fraction'] = round(r['gross_charge_kwh'] / thr * 100, 1) \
                if thr > 0 else None
            r['regen_share_of_charge'] = round(
                r['charge_eng_off_kwh'] / r['gross_charge_kwh'] * 100, 1) \
                if r['gross_charge_kwh'] > 0 else None

            # M12: 4-way torque-verified charge split (dual-channel resolution)
            if tq_s is not None:
                e2 = _asof(e.copy(), tq_s, 'tq', '1500ms')
                tq_regen = e2['tq'].fillna(0) < -15   # motor actively braking
                _tqr = tq_regen.to_numpy()
                m_dual = eng_on & tq_regen           # pandas Series (reused below)

                r['charge_eng_only_kwh']    = round(max(float(_chg[_eng_on & ~_tqr].sum()),  0), 4)
                r['charge_dual_kwh']        = round(max(float(_chg[_eng_on &  _tqr].sum()),  0), 4)
                r['charge_pure_regen_kwh']  = round(max(float(_chg[~_eng_on &  _tqr].sum()), 0), 4)
                r['charge_lowtq_engoff_kwh']= round(max(float(_chg[~_eng_on & ~_tqr].sum()), 0), 4)

                gc = r['gross_charge_kwh']
                if gc > 0:
                    r['motor_regen_lower_pct'] = round(
                        r['charge_pure_regen_kwh'] / gc * 100, 1)
                    r['motor_regen_upper_pct'] = round(
                        (r['charge_pure_regen_kwh'] + r['charge_dual_kwh']) / gc * 100, 1)

                dual_chg = e2[m_dual & (e2['Id'] < -10)]
                if len(dual_chg):
                    r['dual_peak_A']     = round(dual_chg['Id'].min(), 1)
                    r['dual_peak_Crate'] = round(abs(dual_chg['Id'].min()) / cap_ah, 1)

            # C-rate peaks on correct capacity (M3)
            reg = e[(~eng_on) & (e['Id'] < -30)]
            if len(reg):
                r['regen_peak_A'] = round(reg['Id'].min(), 1)
                r['regen_peak_Crate'] = round(abs(reg['Id'].min()) / cap_ah, 1)
            egc = e[eng_on & (e['Id'] < -50)]
            if len(egc):
                r['eng_charge_peak_A'] = round(egc['Id'].min(), 1)
                r['eng_charge_peak_Crate'] = round(abs(egc['Id'].min()) / cap_ah, 1)

            # P0-3 (audit F-03, 2026-09-11): T1_at_peak_Crate + isFallback.
            # PREVIOUSLY generated only by the out-of-band probe
            # c1_joint_temp_crate.py, so a clean one-command rebuild produced a
            # 184-col master while the shipped/dashboard master carried 186 and
            # compute_summary_arrays.cRatePoints consumed `T1_at_peak_Crate`.
            # Ported into versioned code here so the core builder generates its
            # own published schema. Semantics reproduce the probe exactly: T1
            # asof-aligned (nearest, ENG_ALIGN_TOL=3s) to the SAME sample that
            # produced this drive's overall peak charge C-rate, across whichever
            # of the three charge channels (eng_charge / dual / regen) is
            # available. isFallback=True marks the minority of drives with no
            # simultaneous T1 probe at that sample, where cRatePoints falls back
            # to the (non-simultaneous) drive-max T1_peak.
            # Column convention (matches the shipped 186-col master exactly):
            #   * a charge C-rate exists AND a T1 sample sits within 3s of the
            #     peak-C-rate sample -> value = that co-timed T1, isFallback=False
            #   * a charge C-rate exists but NO co-timed T1 -> value = the
            #     drive-max T1 (== T1_peak), isFallback=True
            #   * no charge C-rate at all -> both keys left absent (NaN), which
            #     cRatePoints then fills from T1_peak itself.
            _t1_series = _series(df, t, 'T1', lo=-40, hi=90)
            if _t1_series is not None:
                _cands = []
                if len(reg):
                    _cands.append((reg, reg['Id'].idxmin()))
                if len(egc):
                    _cands.append((egc, egc['Id'].idxmin()))
                # dual_chg exists only inside the tq_s branch above; guard it.
                _dc = dual_chg if (tq_s is not None and 'dual_chg' in dir()) else None
                if _dc is not None and len(_dc):
                    _cands.append((_dc, _dc['Id'].idxmin()))
                if _cands:
                    _t1_drive_max = round(float(_t1_series['v'].max()), 1)
                    # pick the channel whose peak has the largest magnitude
                    # (most negative Id) -- the drive's peak C-rate, matching
                    # cRatePoints' max-across-channels selection.
                    _frame, _idx = min(_cands, key=lambda fi: fi[0].loc[fi[1], 'Id'])
                    _t_peak = _frame.loc[_idx, 't']
                    _b = pd.DataFrame({'t': [_t_peak]})
                    _m = _asof(_b, _t1_series.sort_values('t'), 'T1', ENG_ALIGN_TOL)
                    _t1_now = _m['T1'].iloc[0]
                    if pd.notna(_t1_now):
                        r['T1_at_peak_Crate'] = round(float(_t1_now), 1)
                        r['T1_at_peak_Crate_isFallback'] = False
                    else:
                        r['T1_at_peak_Crate'] = _t1_drive_max
                        r['T1_at_peak_Crate_isFallback'] = True

            # generator-saturation deficit, 80-120 km/h band (M6 + M14 gate)
            band = e['speed'].between(80, 120)
            dts = dt_h * 3600.0
            r['band_80_120_s'] = round(float(dts[band].sum()), 1)
            r['deficit_80_120_s'] = round(
                float(dts[band & eng_on & (e['Id'] > 0)].sum()), 1)
            r['deficit_80_120_pct'] = round(
                r['deficit_80_120_s'] / r['band_80_120_s'] * 100, 1) \
                if r['band_80_120_s'] > 0 else None
            r['deficit_80_120_valid'] = bool(
                r['band_80_120_s'] >= DEFICIT_MIN_BAND_S)          # M14

            # M41 (2026-07-17): "deficit" reframed. deficit_80_120_* retained
            # byte-compatible for continuity, but the quantity is an
            # engine-on discharge share (control-strategy observable: SoC
            # steering + load-point quantization + transient blending), not
            # evidence of generator saturation. New decomposition columns:
            r['engon_dis_share_80_120'] = r['deficit_80_120_pct']
            load_s = _series(df, t, 'eng_load_calc', lo=0, hi=110)
            r.update(_m41_decompose(e, dts, band, eng_on, spd, load_s))
            r['highspeed_discharge_s_130p'] = round(
                float(dts[(e['speed'] >= 130) & eng_on & (e['Id'] > 0)].sum()), 1)
            # M271 (audit Sec 10): the field above is a CUMULATIVE sum of all
            # qualifying-sample dt, not a contiguous run. Add the true gap-aware
            # LONGEST CONTIGUOUS RUN on the same per-sample frame: the maximal
            # block of consecutive samples all satisfying (speed>=130 & engine-on
            # & discharging), duration = summed dt within the block (dt already
            # capped at DT_CAP, so timeline gaps do not inflate the run).
            _q130 = ((e['speed'] >= 130) & eng_on & (e['Id'] > 0)).to_numpy()
            _dtv = (dts).to_numpy()
            _best = 0.0
            _cur = 0.0
            for _i in range(len(_q130)):
                if _q130[_i]:
                    _cur += float(_dtv[_i])
                    if _cur > _best:
                        _best = _cur
                else:
                    _cur = 0.0
            r['highspeed_discharge_longest_run_s_130p'] = round(_best, 1)

            # standstill accessory draw (A/C + DC-DC), engine off
            still = (e['speed'].fillna(99) < 1) & (~eng_on)
            if still.sum() >= 10:
                r['standstill_draw_kw'] = round(
                    float(e.loc[still, 'P'].median()), 2)
                r['n_standstill_samples'] = int(still.sum())

    # ---------- SoC + energy-balance residual (M8) ----------
    if soc is not None and len(soc) > 1:
        r['soc_start'] = round(soc['v'].iloc[0], 1)
        r['soc_end'] = round(soc['v'].iloc[-1], 1)
        r['soc_min'] = round(soc['v'].min(), 1)
        r['soc_max'] = round(soc['v'].max(), 1)
        r['soc_band'] = round(r['soc_max'] - r['soc_min'], 1)
        if r.get('net_draw_kwh') is not None:   # None on F10 no-pair drives
            soc_kwh = (r['soc_start'] - r['soc_end']) / 100.0 * CAP_KWH
            r['soc_delta_kwh'] = round(soc_kwh, 4)
            r['energy_residual_kwh'] = round(r['net_draw_kwh'] - soc_kwh, 4)

        # ---------- M17: rainflow cycle counting on raw SoC ----------
        # P0-13 (2026-07-30): the six rf_* keys are ALWAYS initialized so the
        # master schema is never partial. They stay NaN only when SoC is too
        # short to count cycles (an eligible-but-empty state distinct from the
        # earlier bug where 24 SoC-valid drives silently carried nulls). The
        # summary generator gates on rf coverage over SoC-eligible drives.
        for _rfk in ('rf_efc', 'rf_efc_f05', 'rf_n_cycles',
                     'rf_dod_wmean_pct', 'rf_dod_max_pct', 'rf_damage_k2',
                     'rf_damage_k2_socband_lo', 'rf_damage_k2_socband_mid',
                     'rf_damage_k2_socband_hi', 'rf_socmean_wtd_pct'):
            r.setdefault(_rfk, float('nan'))
        if len(soc) >= 10:                     # rainflow is mandatory (P0-12)
            cyc = list(_rainflow.extract_cycles(soc['v'].values))
            keep = [c for c in cyc if c[0] >= RF_FLOOR_PCT]
            rng = np.array([c[0] for c in keep])
            cnt = np.array([c[2] for c in keep])
            r['rf_efc'] = round(float((rng / 100.0 * cnt).sum()), 4) \
                if len(rng) else 0.0
            r['rf_efc_f05'] = round(float(sum(
                c[0] / 100.0 * c[2] for c in cyc
                if c[0] >= RF_FLOOR_SENS_PCT)), 4)
            if len(rng):
                r['rf_n_cycles'] = round(float(cnt.sum()), 1)
                r['rf_dod_wmean_pct'] = round(
                    float(np.average(rng, weights=cnt)), 2)
                r['rf_dod_max_pct'] = round(float(rng.max()), 1)
                r['rf_damage_k2'] = round(float(
                    ((rng / 100.0) ** RF_DAMAGE_EXP * cnt).sum()), 5)
                # M91 (2026-08-06): SoC-LEVEL band decomposition of rf_damage_k2.
                # rainflow.extract_cycles() already returns (range, MEAN, count,
                # i_start, i_end) -- c[1] was extracted but never read by M17.
                # Wikner (Chalmers, 2017, licentiate thesis, NMC/LMO pouch cell
                # lifetime tests) finds SoC WINDOW LEVEL a comparably strong (at
                # some SOC/DOD combinations dominant) aging axis independent of
                # DOD: <~30% SoC shows minimal cycling aging in her data, >~50%
                # shows clearly accelerated aging with little further
                # differentiation above ~60%. RF_DAMAGE_EXP=2 depth-weighting
                # alone is blind to this: it treats a cycle at 15-20% SoC and an
                # equal-depth cycle at 60-65% SoC identically. These three
                # columns decompose the SAME rf_damage_k2 total (identity:
                # lo+mid+hi == rf_damage_k2, to rounding) by the cycle's mean
                # SoC, using breakpoints RF_SOCLVL_LO_PCT/RF_SOCLVL_HI_PCT below
                # -- so no new damage law is introduced here, only a diagnostic
                # split of the existing one. Any SoC-level DAMAGE WEIGHTING
                # (i.e. an actual multiplier, not just this split) is a
                # separate, explicitly labeled, unverified sensitivity computed
                # downstream in compute_summary_arrays._soc_level_sensitivity(),
                # never folded into rf_damage_k2 itself. Wikner's breakpoints
                # are approximate, qualitative, and measured on a different
                # (though chemically comparable, NMC/LMO-blend graphite) cell
                # under fixed 10%-window symmetric cycling, not this pack's
                # continuously-varying shallow buffering -- treat as directional
                # only.
                mn = np.array([c[1] for c in keep])
                d2 = (rng / 100.0) ** RF_DAMAGE_EXP * cnt
                lo = mn < RF_SOCLVL_LO_PCT
                hi = mn >= RF_SOCLVL_HI_PCT
                mid = ~lo & ~hi
                r['rf_damage_k2_socband_lo'] = round(float(d2[lo].sum()), 5)
                r['rf_damage_k2_socband_mid'] = round(float(d2[mid].sum()), 5)
                r['rf_damage_k2_socband_hi'] = round(float(d2[hi].sum()), 5)
                r['rf_socmean_wtd_pct'] = round(
                    float(np.average(mn, weights=cnt)), 2)
            else:
                r['rf_n_cycles'] = 0.0
                r['rf_damage_k2'] = 0.0
                r['rf_damage_k2_socband_lo'] = 0.0
                r['rf_damage_k2_socband_mid'] = 0.0
                r['rf_damage_k2_socband_hi'] = 0.0

    # ---------- cell spread, paired timestamps (M10) ----------
    if vmax is not None and vmin is not None:
        p = pd.merge_asof(vmax.rename(columns={'v': 'vmax'}),
                          vmin.rename(columns={'v': 'vmin'}),
                          on='t', direction='nearest',
                          tolerance=pd.Timedelta(SPREAD_TOL)).dropna()
        if len(p):
            p = p.reset_index(drop=True)
            p['spread_mv'] = (p['vmax'] - p['vmin']) * 1000.0
            sp = p['spread_mv']
            r['cell_spread_mean_mv'] = round(sp.mean(), 1)
            r['cell_spread_max_mv'] = round(sp.max(), 1)
            r['cell_spread_p95_mv'] = round(sp.quantile(0.95), 1)
            if I is not None:
                p2 = _asof(p, I, 'I', V_ALIGN_TOL)
                loaded = p2.loc[p2['I'].abs() > 50, 'spread_mv']
                if len(loaded):
                    r['cell_spread_loaded_mean_mv'] = round(loaded.mean(), 1)
                    r['cell_spread_loaded_max_mv'] = round(loaded.max(), 1)
                    r['cell_spread_loaded_p95_mv'] = round(
                        loaded.quantile(0.95), 1)
                    r['n_loaded_spread_samples'] = int(len(loaded))

    # ---------- temperatures ----------
    t_series = {c: _series(df, t, c, lo=-40, hi=90) for c in
                ['T1', 'T2', 'T3', 'T4']}
    have = {k: v for k, v in t_series.items() if v is not None}
    if have:
        merged = None
        for k, v in have.items():
            merged = v.rename(columns={'v': k}) if merged is None else \
                _asof(merged, v, k, '3s')
        pack_mean = merged[list(have.keys())].mean(axis=1)
        r['T_pack_mean_max'] = round(pack_mean.max(), 1)
        r['T_pack_mean_avg'] = round(pack_mean.mean(), 1)
        if 'T1' in merged:
            r['T1_peak'] = round(merged['T1'].max(), 1)
            r['T1_minus_pack_max'] = round(
                (merged['T1'] - pack_mean).max(), 2)
        # M32 (2026-07-12): per-sensor peaks for T2-T4, mirroring the
        # existing T1_peak convention. Previously only Sensor 1 was
        # captured per-drive, so the "Battery temp (Sensor 1)" dataset
        # extreme silently ignored hotter readings from Sensors 2-4 on
        # drives where T1 wasn't the hottest probe. These feed the
        # true-max-across-sensors record in compute_summary_arrays.py.
        for k in ('T2', 'T3', 'T4'):
            if k in merged:
                r[f'{k}_peak'] = round(merged[k].max(), 1)
    ti = _series(df, t, 'T_intake', lo=-40, hi=90)
    if ti is not None:
        r['T_intake'] = round(ti['v'].mean(), 1)

    for col, key in [('T_coolant', 'T_coolant_max'),
                     ('T_motor', 'T_motor_max'),
                     ('T_eng_coolant', 'T_eng_coolant_max'),
                     ('T_oil', 'T_oil_max')]:
        s = _series(df, t, col, lo=-40, hi=200)
        if s is not None:
            r[key] = round(s['v'].max(), 1)

    # ---------- torque, engine, boost, loads, accel, MAP ----------
    tt = _series(df, t, 'target_torque')
    if tt is not None:
        r['target_torque_max'] = round(tt['v'].max(), 1)
        r['target_torque_min'] = round(tt['v'].min(), 1)

    if eng is not None and len(eng) > 2:
        w = _tw_stats(eng)
        r['engine_on_pct'] = round(
            float(w[eng['v'] > 400].sum() / w.sum()) * 100, 1)
        r['eng_rpm_max'] = round(eng['v'].max(), 0)

    for col, keys in [('boost', [('max', 'boost_max')]),
                      ('eng_load_abs', [('mean', 'eng_load_abs_mean'),
                                        ('max', 'eng_load_abs_max'),
                                        ('p95', 'eng_load_abs_p95')]),
                      ('eng_load_calc', [('mean', 'eng_load_calc_mean'),
                                         ('max', 'eng_load_calc_max')]),
                      ('map_kpa', [('max', 'map_kpa_max'),
                                   ('mean', 'map_kpa_mean')])]:
        s = _series(df, t, col)
        if s is not None:
            for stat, key in keys:
                if stat == 'mean':
                    r[key] = round(s['v'].mean(), 1)
                elif stat == 'max':
                    r[key] = round(s['v'].max(), 3 if col == 'boost' else 1)
                elif stat == 'p95':
                    r[key] = round(s['v'].quantile(0.95), 1)

    acc = _series(df, t, 'accel_g')
    if acc is not None:
        r['accel_max_g'] = round(acc['v'].max(), 3)
        r['accel_min_g'] = round(acc['v'].min(), 3)
        r['accel_p95_g'] = round(acc['v'].quantile(0.95), 3)
        r['accel_p05_g'] = round(acc['v'].quantile(0.05), 3)

    mp = _series(df, t, 'map_kpa')
    if mp is not None and eng is not None:
        m2 = _asof(mp.copy(), eng, 'eng_rpm', ENG_ALIGN_TOL)
        on = m2[m2['eng_rpm'].fillna(0) > 400]
        if len(on):
            r['map_kpa_max_eng_on'] = round(on['v'].max(), 1)

    return r


# ======================================================================
# Master-level post-processing (M13, M15, M16). Idempotent: re-running on
# an already-processed master recomputes all derived columns from scratch.
# ======================================================================

def _v5_postprocess_master(dm, verbose=True):
    dm = dm.copy()
    report = {}

    # ---------- M13: SoC-anchored current-offset correction ----------
    m = dm['energy_residual_kwh'].notna() & dm['duration_s'].notna() \
        & dm['V_pack_median'].notna()
    h = dm.loc[m, 'integr_time_h'] if 'integr_time_h' in dm.columns and \
        dm.loc[m, 'integr_time_h'].notna().all() else dm.loc[m, 'duration_s'] / 3600.0
    Vw = float((dm.loc[m, 'V_pack_median'] * h).sum() / h.sum())
    if I_OFFSET_CAL_A is not None:
        i_off = float(I_OFFSET_CAL_A)
        report['offset_source'] = 'calibration_log'
    else:
        i_off = float(dm.loc[m, 'energy_residual_kwh'].sum() * 1000.0
                      / (h.sum() * Vw))
        report['offset_source'] = 'soc_anchored_global'
    report['I_offset_A'] = round(i_off, 4)
    report['V_weighted'] = round(Vw, 1)

    dm['I_offset_A_applied'] = np.where(m, round(i_off, 4), np.nan)
    h_all = dm['integr_time_h'].fillna(dm['duration_s'] / 3600.0) \
        if 'integr_time_h' in dm.columns else dm['duration_s'] / 3600.0
    off_kwh = i_off * dm['V_pack_median'] * h_all / 1000.0
    dm['offset_kwh_removed'] = off_kwh.round(4)
    dm['net_draw_kwh_corr'] = (dm['net_draw_kwh'] - off_kwh).round(4)
    dm['energy_residual_kwh_corr'] = (dm['energy_residual_kwh'] - off_kwh).round(4)
    dist_ok = dm['distance_km'].fillna(0) > 0
    dm['net_draw_per100km_corr'] = np.where(
        dist_ok & dm['net_draw_kwh_corr'].notna(),
        (dm['net_draw_kwh_corr'] / dm['distance_km'] * 100).round(2), np.nan)
    dm['implied_offset_A_drive'] = np.where(
        m & (h_all > 0.05),
        (dm['energy_residual_kwh'] * 1000.0
         / (h_all * dm['V_pack_median'])).round(3), np.nan)
    report['residual_corr_mean_kwh'] = round(
        float(dm['energy_residual_kwh_corr'].mean()), 4)
    report['net_corr_sum_kwh'] = round(
        float(dm['net_draw_kwh_corr'].sum()), 3)

    # ---------- M14: deficit gate (recompute for v3-era rows) ----------
    dm['deficit_80_120_valid'] = dm['band_80_120_s'].fillna(0) >= DEFICIT_MIN_BAND_S
    report['n_deficit_valid'] = int(
        (dm['deficit_80_120_valid'] & dm['deficit_80_120_pct'].notna()).sum())

    # ---------- M15: loaded cell-spread deconfounding ----------
    sc = dm.dropna(subset=['cell_spread_loaded_p95_mv',
                           'T_pack_mean_avg', 'peak_I_discharge'])
    if len(sc) >= 20:
        X = np.column_stack([np.ones(len(sc)),
                             sc['T_pack_mean_avg'].values,
                             sc['peak_I_discharge'].values])
        y = sc['cell_spread_loaded_p95_mv'].values
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        I_ref = float(sc['peak_I_discharge'].median())
        pred = X @ beta
        ref_level = beta[0] + beta[1] * SPREAD_T_REF + beta[2] * I_ref
        adj = ref_level + (y - pred)
        dm.loc[sc.index, 'cell_spread_loaded_p95_adj_mv'] = np.round(adj, 1)
        report['spread_model'] = {
            'b0': round(float(beta[0]), 3),
            'bT_mv_per_degC': round(float(beta[1]), 4),
            'bI_mv_per_A': round(float(beta[2]), 5),
            'T_ref_C': SPREAD_T_REF, 'I_ref_A': round(I_ref, 1),
            'n': int(len(sc))}

    # ---------- M16a: KMeans k=3 data-derived cluster ----------
    from sklearn.preprocessing import StandardScaler
    from sklearn.cluster import KMeans
    from sklearn.ensemble import IsolationForest
    feat = ['speed_mean_moving', 'pct_highway', 'pct_urban',
            'stationary_pct', 'speed_p95']
    cl = dm.dropna(subset=feat)
    if len(cl) >= 20:
        Xc = StandardScaler().fit_transform(cl[feat])
        km = KMeans(n_clusters=3, n_init=20, random_state=42).fit(Xc)
        lbl = pd.Series(km.labels_, index=cl.index)
        order = cl.groupby(lbl)['speed_mean_moving'].mean().sort_values().index
        name_map = {order[0]: 'urban_like', order[1]: 'mixed_like',
                    order[2]: 'highway_like'}
        dm.loc[cl.index, 'drive_cluster_k3'] = lbl.map(name_map)
        report['cluster_sizes'] = dm['drive_cluster_k3'].value_counts().to_dict()

    # ---------- M16b + M18: ensemble anomaly detection ----------
    from sklearn.neighbors import LocalOutlierFactor
    en_cols = ['gross_throughput_kwh', 'net_draw_per100km', 'gtc',
               'peak_discharge_kw', 'peak_I_charge', 'deficit_80_120_pct',
               'T_pack_mean_max', 'cell_spread_loaded_p95_mv']
    io_sub = dm.dropna(subset=['gross_throughput_kwh'])
    if len(io_sub) >= 20:
        Z = io_sub[en_cols].copy()
        for c in en_cols:
            Z[c] = Z[c].fillna(Z[c].median())
        Zs = StandardScaler().fit_transform(Z)
        # (a) IsolationForest — v4-compatible columns
        iso = IsolationForest(n_estimators=500, contamination=0.06,
                              random_state=42).fit(Zs)
        f_iso = iso.predict(Zs) == -1
        dm.loc[io_sub.index, 'iso_outlier'] = f_iso
        dm.loc[io_sub.index, 'iso_score'] = np.round(
            iso.decision_function(Zs), 4)
        report['n_iso_outliers'] = int(dm['iso_outlier'].fillna(False).sum())
        # M18 detectors run on the M13/M15-corrected feature block (the
        # raw block above is retained only so iso_outlier stays v4-
        # byte-compatible).
        en_corr = ['gross_throughput_kwh', 'net_draw_per100km_corr', 'gtc',
                   'peak_discharge_kw', 'peak_I_charge',
                   'deficit_80_120_pct', 'T_pack_mean_max',
                   'cell_spread_loaded_p95_adj_mv']
        en_corr = [c for c in en_corr if c in io_sub.columns]
        Zc = io_sub[en_corr].copy()
        for c in en_corr:
            Zc[c] = Zc[c].fillna(Zc[c].median())
        Zcs = StandardScaler().fit_transform(Zc)
        f_iso = IsolationForest(n_estimators=500, contamination=0.06,
                                random_state=42).fit_predict(Zcs) == -1
        # (b) LocalOutlierFactor — local-density unusualness
        lof = LocalOutlierFactor(n_neighbors=min(LOF_NEIGHBORS,
                                                 len(io_sub) - 1),
                                 contamination=0.06)
        f_lof = lof.fit_predict(Zcs) == -1
        dm.loc[io_sub.index, 'lof_score'] = np.round(
            -lof.negative_outlier_factor_, 4)
        # (c) robust MAD z on any feature
        f_mad = np.zeros(len(Zc), dtype=bool)
        for c in en_corr:
            med = Zc[c].median()
            mad = (Zc[c] - med).abs().median()
            if mad == 0:
                continue
            f_mad |= (0.6745 * (Zc[c] - med) / mad).abs().values > MAD_Z_THRESH
        # (d) domain rules — physically implausible / non-drive logs
        s = io_sub
        f_dom = (
            ((s['distance_km'].fillna(0) > 5)
             & (s['gross_throughput_kwh'] < 0.3))
            | ((s['distance_km'].fillna(0) < 1.0) & (s['duration_s'] > 300))
            | s['sign_check'].eq('ANOMALY')
            | ((s['n_I_samples'] < 100) & (s['duration_s'] > 600))
            | (s['energy_residual_kwh_corr'].abs() > RESIDUAL_MAX_KWH)
        ).values
        votes = f_iso.astype(int) + f_lof.astype(int) + f_mad.astype(int)
        ens = f_dom | (votes >= 2)
        dm.loc[io_sub.index, 'f_iso'] = f_iso
        dm.loc[io_sub.index, 'f_lof'] = f_lof
        dm.loc[io_sub.index, 'f_mad'] = f_mad
        dm.loc[io_sub.index, 'f_domain'] = f_dom
        dm.loc[io_sub.index, 'ens_outlier'] = ens
        report['ensemble'] = {'iso': int(f_iso.sum()), 'lof': int(f_lof.sum()),
                              'mad': int(f_mad.sum()),
                              'domain': int(f_dom.sum()),
                              'ens_outlier': int(ens.sum())}

    # ---------- M19: robust spread adjustment + bootstrap trend CI ----
    if len(sc) >= 20 and 'date' in dm.columns:
        try:
            from sklearn.linear_model import HuberRegressor
            clean = dm.loc[sc.index]
            keep = ~clean['ens_outlier'].fillna(False).astype(bool).values \
                if 'ens_outlier' in clean.columns else np.ones(len(clean), bool)
            cc = clean[keep].dropna(subset=['date'])
            Xh = cc[['T_pack_mean_avg', 'peak_I_discharge']].values
            yh = cc['cell_spread_loaded_p95_mv'].values
            hub = HuberRegressor(epsilon=1.35, max_iter=500).fit(Xh, yh)
            I_ref = float(cc['peak_I_discharge'].median())
            ref = hub.predict([[SPREAD_T_REF, I_ref]])[0]
            adj_h = ref + (yh - hub.predict(Xh))
            dm.loc[cc.index, 'cell_spread_loaded_p95_adj_hub_mv'] = \
                np.round(adj_h, 1)
            dt = pd.to_datetime(cc['date'])
            t_mo = ((dt - dt.min()).dt.days / 30.44).values
            slope = float(np.polyfit(t_mo, adj_h, 1)[0])
            # cluster-by-day bootstrap of the OLS-adjusted slope
            days = dt.dt.date.values
            uniq = np.unique(days)
            rng_ = np.random.default_rng(42)
            boot = []
            for _ in range(N_BOOT):
                pick = rng_.choice(uniq, size=len(uniq), replace=True)
                idx = np.concatenate(
                    [np.where(days == d)[0] for d in pick])
                if len(np.unique(t_mo[idx])) < 3:
                    continue
                b1 = np.linalg.lstsq(
                    np.column_stack([np.ones(len(idx)), Xh[idx]]),
                    yh[idx], rcond=None)[0]
                a1 = (b1[0] + b1[1] * SPREAD_T_REF + b1[2] * I_ref) \
                    + (yh[idx] - np.column_stack(
                        [np.ones(len(idx)), Xh[idx]]) @ b1)
                boot.append(float(np.polyfit(t_mo[idx], a1, 1)[0]))
            boot = np.asarray(boot)
            lo, hi = np.percentile(boot, [2.5, 97.5])
            report['spread_trend'] = {
                'slope_hub_mv_per_month': round(slope, 3),
                'boot_ci95_mv_per_month': [round(float(lo), 3),
                                           round(float(hi), 3)],
                'p_slope_gt0': round(float((boot > 0).mean()), 3),
                'n_clean': int(len(cc)), 'n_boot': int(len(boot))}
        except Exception as ex:
            report['spread_trend_error'] = str(ex)

    if verbose:
        print('postprocess_master:', report)
    return dm, report


# ======================================================================
# Orchestration (v5). One entry point that takes the pipeline end-to-end:
#   raw CSVs  ->  per-drive rows (analyze_bytes)
#             ->  drive_master.csv (postprocess_master: M13-M19)
#             ->  summary_arrays.json (compute_summary_arrays)
# so a new batch of drives needs a SINGLE command and leaves NO hand-edited
# dashboard literals. Idempotent: reprocesses every raw CSV from scratch on
# each run (per the "full historical reprocessing on every upgrade" rule) and
# verifies nothing is silently column-patched.
# ======================================================================

import os
import glob
import json


import re as _re_date

# P0-11 (2026-07-30): the source archive names files as
# "2026-07-05 12-20-16.csv" while the working corpus uses the canonical
# "20260705_122016.csv". The original parser split on '_' only and returned
# (None, None) for every archive-named file, silently nulling all dates and
# aborting at the M49 guard. This parser accepts BOTH forms so the documented
# one-command build ingests the archive as supplied, with no undocumented
# rename step. All 14 digits (YYYYMMDDHHMMSS) are extracted regardless of the
# separators used between/among them.
_DATE_DIGITS_RE = _re_date.compile(r'(\d{4})\D?(\d{2})\D?(\d{2})\D+(\d{2})\D?(\d{2})\D?(\d{2})')


def _date_from_name(fn):
    """Parse a drive timestamp from the filename.

    Accepts canonical  '20260705_122016.csv' -> ('2026-07-05', '12:20:16')
    and archive-native  '2026-07-05 12-20-16.csv' -> ('2026-07-05', '12:20:16').
    Returns (None, None) only when no 14-digit timestamp can be recovered.
    """
    base = os.path.basename(fn)
    m = _DATE_DIGITS_RE.search(base)
    if not m:
        return None, None
    y, mo, d, hh, mm, ss = m.groups()
    return f"{y}-{mo}-{d}", f"{hh}:{mm}:{ss}"


def _canonical_file_name(fn):
    """Return the canonical 'YYYYMMDD_HHMMSS.csv' form for any accepted name.

    Lets the pipeline store both raw_file (as supplied) and file (canonical)
    so downstream loaders and joins are separator-agnostic.
    """
    base = os.path.basename(fn)
    m = _DATE_DIGITS_RE.search(base)
    if not m:
        return base
    y, mo, d, hh, mm, ss = m.groups()
    return f"{y}{mo}{d}_{hh}{mm}{ss}.csv"


# ======================================================================
# v6 LAYER (M23, M24, M25) + orchestration.
# ======================================================================
# ---- M23/M24/M25 constants ----
VSAG_REST_A = 5.0        # |Id| below this = rest reference sample
VSAG_LOAD_A = 50.0       # Id above this = load sample (100 A left <15
                         # samples on most drives: high-current transients
                         # are brief vs the ~2-4 s I-PID period)
VSAG_MIN_REST = 30       # min rest samples for a usable rest curve
VSAG_MIN_LOAD = 15       # min load samples for a per-drive estimate
VREG_MIN_N = 300         # M25b regression estimator: min discharge samples
VREG_MIN_I_P95 = 40.0    # ... and min p95 of discharge current, A
VSAG_SOC_BIN = 0.5       # rest-curve SoC bin width, % (PID quantization)
VSAG_R_LO, VSAG_R_HI = 0.0, 0.5   # plausibility window, Ohm (0..500 mOhm)
OFFSET_MAX_PASSES = 5    # M24 iteration cap


# ======================================================================
# M25 per-drive V-sag extraction (raw bytes -> proxy columns)
# ======================================================================
def _vsag_metrics(csv_bytes):
    df = pd.read_csv(io.BytesIO(csv_bytes), low_memory=False)
    df = df.rename(columns={k: v for k, v in COL_MAP.items()
                            if k in df.columns})
    t = pd.to_datetime(df['time'], format='mixed', errors='coerce')
    I = _series(df, t, 'I')
    if I is not None:
        I = I[I['v'].abs() < 900]
    V = _series(df, t, 'V', lo=200, hi=450)
    soc = _series(df, t, 'soc')
    if I is None or V is None or soc is None or len(I) < 100:
        return {}
    e = _asof(I.copy(), V, 'V', V_ALIGN_TOL)
    e = _asof(e, soc, 'soc', V_ALIGN_TOL)
    e = e.dropna(subset=['V', 'soc'])
    if len(e) < 100:
        return {}
    e['Id'] = -e['v']                               # discharge-positive (M11)
    r = {}

    # ---- M25b: Huber regression V ~ b0 + b1*soc + b2*Id on rest +
    # discharge samples (charge excluded: different polarization path and
    # generator-side voltage rise). R = -b2. Uses every discharge sample,
    # so coverage is ~an order of magnitude better than the sag estimator;
    # the sag estimator (below) is retained as an independent cross-check.
    reg = e[e['Id'] > -VSAG_REST_A]
    if len(reg) >= VREG_MIN_N:
        i_p95 = float(reg['Id'].quantile(0.95))
        if i_p95 >= VREG_MIN_I_P95:
            try:
                from sklearn.linear_model import HuberRegressor
                Xr = reg[['soc', 'Id']].values
                hub = HuberRegressor(epsilon=1.35, max_iter=500) \
                    .fit(Xr, reg['V'].values)
                R = -float(hub.coef_[1])            # Ohm
                if VSAG_R_LO < R < VSAG_R_HI:
                    r['vreg_R_pack_mohm'] = round(R * 1000, 2)
                    r['n_vreg_samples'] = int(len(reg))
                    r['vreg_I_p95_A'] = round(i_p95, 1)
            except Exception:
                pass

    rest = e[e['Id'].abs() < VSAG_REST_A]
    load = e[e['Id'] > VSAG_LOAD_A]
    r['n_vsag_rest'] = int(len(rest))
    r['n_vsag_load'] = int(len(load))
    if len(rest) < VSAG_MIN_REST or len(load) < VSAG_MIN_LOAD:
        return r

    # rest curve: median V per 0.5% SoC bin
    rb = (rest['soc'] / VSAG_SOC_BIN).round() * VSAG_SOC_BIN
    curve = rest.groupby(rb)['V'].median()
    if len(curve) < 3:
        return r
    soc_lo, soc_hi = curve.index.min() - 2.0, curve.index.max() + 2.0

    ld = load[(load['soc'] >= soc_lo) & (load['soc'] <= soc_hi)]
    if len(ld) < VSAG_MIN_LOAD:
        r['n_vsag_load'] = int(len(ld))
        return r
    v_rest = np.interp(ld['soc'].values, curve.index.values, curve.values)
    R = (v_rest - ld['V'].values) / ld['Id'].values          # Ohm
    ok = (R > VSAG_R_LO) & (R < VSAG_R_HI)
    if ok.sum() < VSAG_MIN_LOAD:
        r['n_vsag_load'] = int(ok.sum())
        return r
    Rk = R[ok]
    r['n_vsag_load'] = int(ok.sum())
    r['vsag_R_pack_mohm'] = round(float(np.median(Rk)) * 1000, 2)
    r['vsag_R_iqr_mohm'] = round(
        float(np.percentile(Rk, 75) - np.percentile(Rk, 25)) * 1000, 2)
    r['vsag_I_mean_A'] = round(float(ld['Id'].values[ok].mean()), 1)
    r['vsag_soc_mean'] = round(float(ld['soc'].values[ok].mean()), 1)
    return r


# M49 (2026-07-22): batch-ingestion defect. analyze_bytes did NOT emit a
# 'date' key at all -- the filename-derived date was applied only by
# build_master_from_raw (r.setdefault('date', d) at its call site). The
# standing batch-ingestion workflow calls analyze_bytes directly and appends
# to the existing master, so every drive ingested that way landed with
# date=NaN. This is not cosmetic: 'date' is the regressor in _spread_trend
# and _powerfade_trend, both of which dropna(subset=['date']), so the new
# rows were silently excluded from the degradation and power-fade fits while
# the corpus counts elsewhere reported them as included. It also froze
# meta.dateRange / meta.loggedDates / meta.daysSpan in summary_arrays.json
# at the last correctly-dated batch. Observed on the Jul22 batch (n=167->173):
# spread-trend n_clean 150 vs 155, power-fade n_clean 87 vs 88, dateRange
# stuck at "Jul 21" on a corpus running to Jul 22. Caught only by an
# incidental null-count diff on summary_arrays.json, not by any assertion.
# Fix has two halves, deliberately redundant:
#   (a) derive date/time_start HERE, so all ingestion paths are covered
#       identically rather than the correctness depending on which entry
#       point the operator happened to use;
#   (b) a fail-loud guard in postprocess_master (see _assert_dates below),
#       because (a) still cannot cover a hand-assembled master and the
#       failure mode is silent-and-plausible, which is the worst kind.
# build_master_from_raw keeps its setdefault calls: they become no-ops, and
# leaving them preserves that path's behaviour if this function is ever
# refactored again.
# ---- M53 constants (pure-electric traction census) ----
EV_MOVING_KMH = 1.0      # speed at/above which the vehicle counts as moving
EV_DEBOUNCE_S = 3        # min sustained duration for an engine state change
EV_MIN_RUN_KM = 0.05     # runs shorter than this are not resolvable
EV_COV_MIN = 0.95        # min grid coverage of the rpm AND speed channels
EV_POLL_MAX_S = 2.0      # max median engine-rpm poll period, s
EV_MIN_DIST_KM = 1.0     # below this, odometer quantisation dominates
EV_SCALE_LO, EV_SCALE_HI = 0.90, 1.10   # integrated/odometer sanity window
EV_REGEN_POOR = 0.20     # max regen share of throughput for an "unassisted" run
EV_NR_MIN_KM = 0.3       # min run length entering the unassisted subset


def _ev_debounce(state, n):
    """Suppress state runs shorter than n samples on a 1 Hz grid."""
    s = state.astype(np.int8).values.copy()
    if len(s) == 0:
        return pd.Series(s.astype(bool), index=state.index)
    chg = np.flatnonzero(np.diff(s)) + 1
    for a, b in zip(np.r_[0, chg], np.r_[chg, len(s)]):
        if (b - a) < n and a > 0:
            s[a:b] = s[a - 1]
    return pd.Series(s.astype(bool), index=state.index)


# ======================================================================
# M53 per-drive pure-electric traction census (raw bytes -> ev_* columns)
# ======================================================================
def _ev_metrics(csv_bytes):
    """M53 (2026-07-24): pure-electric (engine-off) traction census.

    Question. The corpus quantified WHERE the battery is stressed but never
    HOW MUCH of the road is covered without the ICE turning, which is the
    metric a reader of an e-POWER study asks first. Two quantities are
    emitted per drive: the engine-off distance share, and the longest single
    engine-off run.

    Definition. EV state := ICE not rotating (eng_rpm <= 400, the SAME
    threshold engine_on_pct already uses, so the two are complementary by
    construction) with the vehicle in motion. A RUN is a maximally contiguous
    engine-off interval; standstill inside a run does NOT terminate it
    (engine-off idling at a light belongs to the same electric run), an engine
    start does. This is deliberately the CONSERVATIVE reading of "electric":
    it excludes the M46/M48 motored-unfuelled state (~3400 rpm, deep vacuum),
    which burns no fuel but is not engine-off. A zero-fuel variant would be
    strictly larger and is not what is reported here.

    Distance. Integrated on a 1 Hz grid. Per-row .diff() is INVALID on this
    logger -- the PID update rate is sparse relative to the row rate, so
    consecutive rows share a speed sample and the differential is identically
    zero. Integrated distance is validated against the odometer delta per
    drive (ev_dist_scale_k); across the corpus the ratio is 1.013 +/- 0.040,
    the residual being odometer 0.1 km quantisation plus speedometer bias.
    ev_dist_km is reported on the ODOMETER scale (integrated x k) so it sums
    consistently with distance_km.

    Guards against false-optimistic EV attribution. The failure mode here is
    silent and one-directional -- any gap in the engine channel reads as
    "engine off" -- so three gates are emitted rather than assumed:
      * ev_cov_rpm / ev_cov_speed: fraction of grid seconds with a sample
        inside tolerance. Grid points with no engine sample are UNKNOWN and
        are never counted as engine-off.
      * ev_rpm_dt_med_s: a coarse engine poll cannot exclude short engine
        bursts inside an apparent run.
      * ev_dist_scale_k outside [0.90, 1.10] means the speed channel did not
        reconstruct the trip and no distance claim is defensible.
    ev_valid ANDs these with a minimum trip length. Note the +/-3 s asof
    tolerance and the debounce both bias engine-off UPWARD, so every ev_*
    distance/time figure is an upper bound -- consistent with the standing
    merge_asof caveat on engine-off fraction.

    Run-length histogram. ev_runs_* are exact counts per distance bin, so
    summing them across drives yields an exact POOLED histogram. Pooling
    per-drive percentiles would not be valid; the per-drive percentiles
    (ev_run_p50_km / ev_run_p90_km) are emitted for per-drive use only.
    """
    df = pd.read_csv(io.BytesIO(csv_bytes), low_memory=False)
    df = df.rename(columns={k: v for k, v in COL_MAP.items()
                            if k in df.columns})
    t = pd.to_datetime(df['time'], format='mixed', errors='coerce')
    eng = _series(df, t, 'eng_rpm', lo=0)
    spd = _series(df, t, 'speed', lo=0, hi=260)
    if spd is None or len(spd) < 20:
        spd = _series(df, t, 'speed_obd', lo=0, hi=260)
    if eng is None or spd is None or len(eng) < 20:
        return {}

    tv = t.dropna()
    if len(tv) < 10:
        return {}
    grid = pd.DataFrame({'t': pd.date_range(tv.min(), tv.max(), freq='1s')})
    if len(grid) < 10:
        return {}
    tol = pd.Timedelta(ENG_ALIGN_TOL)
    g = pd.merge_asof(grid, spd.rename(columns={'v': 'speed'}), on='t',
                      direction='nearest', tolerance=tol)
    g = pd.merge_asof(g, eng.rename(columns={'v': 'rpm'}), on='t',
                      direction='nearest', tolerance=tol)

    r = {'ev_cov_rpm': round(float(g['rpm'].notna().mean()), 4),
         'ev_cov_speed': round(float(g['speed'].notna().mean()), 4),
         'ev_rpm_dt_med_s': round(float(eng['t'].diff().dt.total_seconds()
                                        .median()), 2)}

    v = g['speed'].fillna(0.0)
    g['dkm'] = v / 3600.0
    dist_int = float(g['dkm'].sum())

    odo = _series(df, t, 'odo')
    dist_odo = (float(odo['v'].max() - odo['v'].min())
                if odo is not None and len(odo) else np.nan)
    k = (dist_odo / dist_int) if (dist_int > 0 and np.isfinite(dist_odo)
                                  and dist_odo > 0) else np.nan
    r['ev_dist_scale_k'] = round(float(k), 4) if np.isfinite(k) else None
    kk = k if np.isfinite(k) else 1.0

    known = g['rpm'].notna()
    off = _ev_debounce(known & (g['rpm'] <= 400), EV_DEBOUNCE_S) & known
    moving = v >= EV_MOVING_KMH

    r['ev_dist_km'] = round(float(g.loc[off, 'dkm'].sum()) * kk, 3)
    r['ev_time_s'] = int(off.sum())
    r['ev_moving_time_s'] = int((off & moving).sum())
    if np.isfinite(dist_odo) and dist_odo > 0:
        r['ev_dist_pct'] = round(r['ev_dist_km'] / dist_odo * 100, 2)

    # battery-side energy while electrically propelled (raw current basis,
    # matching the gross_* convention; the M13/M24 offset is a net-draw
    # correction and is deliberately not applied to a gross quantity)
    I = _series(df, t, 'I')
    if I is not None:
        I = I[I['v'].abs() < 900]
    V = _series(df, t, 'V', lo=200, hi=450)
    if I is not None and V is not None and len(I) > 50:
        e = _asof(I.copy(), V, 'V', V_ALIGN_TOL).dropna(subset=['V'])
        e['P'] = -e['v'] * e['V'] / 1000.0          # kW, discharge-positive
        gp = pd.merge_asof(g[['t']], e[['t', 'P']].sort_values('t'), on='t',
                           direction='nearest', tolerance=tol)
        g['P'] = gp['P'].values
        sel = (off & moving & g['P'].notna()).values
        if sel.sum() > 30:
            kwh = float(g.loc[sel, 'P'].sum()) / 3600.0
            r['ev_batt_kwh'] = round(kwh, 4)
            evkm = float(g.loc[off, 'dkm'].sum()) * kk
            if evkm > 0.5:
                r['ev_kwh_per100km'] = round(kwh / evkm * 100, 2)

    # ---- runs ----
    lab = (off != off.shift()).cumsum()
    gg = g.assign(_off=off.values, _lab=lab.values, _mov=moving.values)
    runs = []
    nr_km = nr_kwh = nr_max = 0.0        # regen-poor ("unassisted") subset
    has_P = 'P' in gg.columns
    for _, b in gg.groupby('_lab'):
        if not bool(b['_off'].iloc[0]):
            continue
        d = float(b['dkm'].sum()) * kk
        if d < EV_MIN_RUN_KM:
            continue
        runs.append((d, int(len(b)), float(b['speed'].max())))
        # M53: the buffer-limit cross-check needs runs the pack actually
        # PAID for. Long runs recover 30-50% of throughput as regen mid-run
        # (descent / decel / light load) and so overstate how far the buffer
        # alone can propel the car. Runs whose regen share of throughput is
        # below EV_REGEN_POOR are aggregated separately; summing the two
        # accumulators across the corpus yields an exact pooled specific
        # consumption for genuinely buffer-drained electric running.
        if has_P and b['P'].notna().sum() > 20 and d >= EV_NR_MIN_KM:
            p = b['P'].dropna()
            kd, kc = float(p[p > 0].sum()), float(-p[p < 0].sum())
            if (kd + kc) > 0 and kc / (kd + kc) < EV_REGEN_POOR:
                nr_km += d
                nr_kwh += float(p.sum()) / 3600.0
                nr_max = max(nr_max, d)
    if nr_km > 0:
        r['ev_nr_km'] = round(nr_km, 3)
        r['ev_nr_kwh'] = round(nr_kwh, 4)
        r['ev_nr_run_max_km'] = round(nr_max, 3)
    r['ev_n_runs'] = len(runs)
    if runs:
        ds = np.array([x[0] for x in runs])
        top = max(runs, key=lambda x: x[0])
        r['ev_run_max_km'] = round(float(top[0]), 3)
        r['ev_run_max_s'] = int(top[1])
        r['ev_run_max_vmax_kmh'] = round(float(top[2]), 1)
        r['ev_run_p50_km'] = round(float(np.median(ds)), 3)
        r['ev_run_p90_km'] = round(float(np.quantile(ds, 0.90)), 3)
        edges = [EV_MIN_RUN_KM, 0.5, 1.0, 2.0, 3.0, np.inf]
        names = ['ev_runs_lt05', 'ev_runs_05_1', 'ev_runs_1_2',
                 'ev_runs_2_3', 'ev_runs_ge3']
        for nm, a, b_ in zip(names, edges[:-1], edges[1:]):
            r[nm] = int(((ds >= a) & (ds < b_)).sum())
    else:
        r['ev_run_max_km'] = 0.0
        for nm in ('ev_runs_lt05', 'ev_runs_05_1', 'ev_runs_1_2',
                   'ev_runs_2_3', 'ev_runs_ge3'):
            r[nm] = 0

    r['ev_valid'] = bool(
        r['ev_cov_rpm'] >= EV_COV_MIN and r['ev_cov_speed'] >= EV_COV_MIN
        and r['ev_rpm_dt_med_s'] <= EV_POLL_MAX_S
        and np.isfinite(dist_odo) and dist_odo >= EV_MIN_DIST_KM
        and np.isfinite(k) and EV_SCALE_LO <= k <= EV_SCALE_HI)
    return r


def analyze_bytes(csv_bytes, filename):
    """v5 per-drive extraction (byte-identical shared columns) + M25."""
    r = _v5_analyze_bytes(csv_bytes, filename)
    r['pipeline_version'] = 6
    try:
        r.update(_vsag_metrics(csv_bytes))
    except Exception:
        pass                                   # proxy columns simply absent
    try:
        r.update(_ev_metrics(csv_bytes))       # M53 pure-electric census
    except Exception:
        pass                                   # ev_* columns simply absent
    # M49: filename-derived date/time_start. Populate only when missing or
    # null so a real parsed value from the log always wins.
    d, tm = _date_from_name(filename)
    if r.get('date') is None or (isinstance(r.get('date'), float)
                                 and pd.isna(r.get('date'))):
        r['date'] = d
    if not r.get('time_start'):
        r['time_start'] = tm
    return r


def _assert_dates(dm):
    """M49 guard: 'date' must be fully populated before any date-regressed
    statistic is fitted. Raises rather than warns -- a partially dated master
    yields trend fits on a silent subset of the corpus, which is
    indistinguishable from a correct result in the emitted report."""
    if 'date' not in dm.columns:
        raise ValueError("M49: master has no 'date' column; date-regressed "
                         "trends (_spread_trend/_powerfade_trend) cannot be "
                         "fitted. Ingest via analyze_bytes (>=M49) or "
                         "build_master_from_raw.")
    bad = dm['date'].isna()
    if bad.any():
        files = dm.loc[bad, 'file'].tolist() if 'file' in dm.columns else []
        raise ValueError(
            "M49: %d of %d master rows have date=NaN; these would be silently "
            "dropped from _spread_trend/_powerfade_trend and would freeze "
            "meta.dateRange. Offending files: %s"
            % (int(bad.sum()), len(dm), files[:10]))


# ======================================================================
# Master-level post-processing: v5 (M13-M19, unchanged) then M24, M23,
# M25-trend. Idempotent.
# ======================================================================
# M47 (2026-07-21): batch-ingestion audit finding. The surgical ML-column
# restore-from-archive procedure (applied to pre-existing drives after each
# corpus expansion, per the standing workflow) previously assumed the four
# "hard domain rule" columns (f_mad, f_domain, f_domain_2p, ens_invalid)
# would show 0 diff on restore, since they are deterministic (non-sklearn)
# threshold logic rather than stochastic fits. On the Jul20-21 batch
# (n=155->167, +12 drives incl. one 159.5km high-throughput leg), a
# same-corpus repeat-run test showed f_domain/f_mad/ens_invalid CAN flip a
# small number of rows (~10 of 155) between identical runs on unchanged
# input -- isolated to early corpus drives lacking HV-current-sensor
# coverage (NaN residual_corr; e.g. 20260513_224232.csv-era files). Root
# cause not yet isolated to a specific line (candidates: PYTHONHASHSEED-
# dependent iteration order feeding tiny float-summation differences in an
# upstream aggregation, surfaced only for these NaN-adjacent boundary
# rows). f_domain_2p was unaffected (0 diff) in this test. Restore
# continues to be applied to all 16 ML/domain columns as before (the
# archived values are retained in preference to the fresh recompute for
# pre-existing rows); this note revises "should flip zero rows" to "flips
# zero rows in typical/small batches, but a handful of NaN-residual edge
# rows can jitter in larger batches" and flags the mechanism as
# unresolved rather than closed.
def _domain_rules(s, residual_corr):
    """The five hard rules, parameterized on which corrected residual
    column/array to use (M24 re-evaluates them per pass).
    M88 (2026-08-05): R2 changed from "distance<1.0km AND duration>300s"
    to a standalone "distance<MIN_DIST_KM (0.2km)" floor -- see MIN_DIST_KM
    docstring. R1/R3/R4/R5 unchanged from v5/M18."""
    return (
        ((s['distance_km'].fillna(0) > 5)
         & (s['gross_throughput_kwh'] < 0.3))
        | (s['distance_km'].fillna(0) < MIN_DIST_KM)
        | s['sign_check'].eq('ANOMALY')
        | ((s['n_I_samples'] < 100) & (s['duration_s'] > 600))
        | (pd.Series(residual_corr, index=s.index).abs()
           > RESIDUAL_MAX_KWH)
    ).values


def postprocess_master(dm, verbose=True):
    _assert_dates(dm)                      # M49: fail loud, not silent
    dm, report = _v5_postprocess_master(dm, verbose=False)   # M13-M19 intact

    # ---------- M24: two-pass offset ----------
    m = dm['energy_residual_kwh'].notna() & dm['duration_s'].notna() \
        & dm['V_pack_median'].notna()
    h_all = dm['integr_time_h'].fillna(dm['duration_s'] / 3600.0)
    Vw = float((dm.loc[m, 'V_pack_median'] * dm.loc[m, 'integr_time_h']).sum()
               / dm.loc[m, 'integr_time_h'].sum())
    io_sub = dm[dm['gross_throughput_kwh'].notna()]
    excl = dm['f_domain'].fillna(False).astype(bool)         # pass-0 seed (v5)
    i2, passes = None, 0
    for passes in range(1, OFFSET_MAX_PASSES + 1):
        mm = m & ~excl
        i2 = float(dm.loc[mm, 'energy_residual_kwh'].sum() * 1000.0
                   / (dm.loc[mm, 'integr_time_h'].sum() * Vw))
        off2 = i2 * dm['V_pack_median'] * h_all / 1000.0
        res2 = dm['energy_residual_kwh'] - off2
        f_dom2 = pd.Series(False, index=dm.index)
        f_dom2.loc[io_sub.index] = _domain_rules(
            io_sub, res2.loc[io_sub.index].values)
        if f_dom2.equals(excl):
            break
        excl = f_dom2
    dm['f_domain_2p'] = excl.values
    dm['I_offset_2p_A_applied'] = np.where(m, round(i2, 4), np.nan)
    off2 = i2 * dm['V_pack_median'] * h_all / 1000.0
    dm['offset_2p_kwh_removed'] = off2.round(4)
    dm['net_draw_kwh_corr2p'] = (dm['net_draw_kwh'] - off2).round(4)
    dm['energy_residual_kwh_corr2p'] = \
        (dm['energy_residual_kwh'] - off2).round(4)
    dist_ok = dm['distance_km'].fillna(0) > 0
    dm['net_draw_per100km_corr2p'] = np.where(
        dist_ok & dm['net_draw_kwh_corr2p'].notna(),
        (dm['net_draw_kwh_corr2p'] / dm['distance_km'] * 100).round(2),
        np.nan)
    report['M24'] = {
        'I_offset_2p_A': round(i2, 4),
        'I_offset_v5_A': report.get('I_offset_A'),
        'passes': passes,
        'n_excluded_domain': int(excl.sum()),
        'residual_corr2p_mean_kwh_clean': round(float(
            dm.loc[m & ~excl, 'energy_residual_kwh_corr2p'].mean()), 4)}

    # ---------- M23: intensity-normalized taxonomy ----------
    from sklearn.preprocessing import StandardScaler
    from sklearn.ensemble import IsolationForest
    from sklearn.neighbors import LocalOutlierFactor
    s = io_sub
    feats = pd.DataFrame(index=s.index)
    d = s['distance_km'].where(s['distance_km'] > 0)
    feats['thr_per100km'] = s['gross_throughput_kwh'] / d * 100
    feats['net_per100km'] = dm.loc[s.index, 'net_draw_per100km_corr2p']
    feats['efc_per100km'] = s['gtc'] / d * 100
    feats['peak_discharge_kw'] = s['peak_discharge_kw']
    feats['peak_I_charge'] = s['peak_I_charge']
    dv = dm.loc[s.index, 'deficit_80_120_valid'].fillna(False).astype(bool)
    feats['deficit_80_120_pct'] = s['deficit_80_120_pct'].where(dv)
    feats['T_pack_mean_max'] = s['T_pack_mean_max']
    feats['spread_adj'] = s['cell_spread_loaded_p95_adj_mv'] \
        if 'cell_spread_loaded_p95_adj_mv' in s else np.nan
    if len(s) >= 20:
        Z = feats.copy()
        for c in Z.columns:
            Z[c] = Z[c].fillna(Z[c].median())
        Zs = StandardScaler().fit_transform(Z)
        f_iso_i = IsolationForest(n_estimators=500, contamination=0.06,
                                  random_state=42).fit_predict(Zs) == -1
        lof = LocalOutlierFactor(
            n_neighbors=min(LOF_NEIGHBORS, len(s) - 1),
            contamination=0.06)
        f_lof_i = lof.fit_predict(Zs) == -1
        f_mad_i = np.zeros(len(Z), dtype=bool)
        for c in Z.columns:
            med = Z[c].median()
            mad = (Z[c] - med).abs().median()
            if mad == 0:
                continue
            f_mad_i |= (0.6745 * (Z[c] - med) / mad).abs().values \
                > MAD_Z_THRESH
        votes = f_iso_i.astype(int) + f_lof_i.astype(int) + f_mad_i.astype(int)
        inv = dm.loc[s.index, 'f_domain_2p'].fillna(False).astype(bool).values
        ext = (votes >= 2) & ~inv
        dm.loc[s.index, 'f_iso_i'] = f_iso_i
        dm.loc[s.index, 'f_lof_i'] = f_lof_i
        dm.loc[s.index, 'f_mad_i'] = f_mad_i
        dm.loc[s.index, 'ens_invalid'] = inv
        dm.loc[s.index, 'ens_extreme'] = ext
        # M88 (2026-08-05): canonical exclusion narrows to ens_invalid alone.
        # ens_extreme (>=2 statistical votes, no domain rule fired) no longer
        # drives exclusion -- a real, physically-valid drive isn't dropped
        # from group stats just for being an intensity-normalized outlier.
        # ens_extreme remains a stored diagnostic column.
        dm.loc[s.index, 'ens_outlier_v2'] = inv
        v5f = dm['ens_outlier'].fillna(False).astype(bool)
        v2f = dm['ens_outlier_v2'].fillna(False).astype(bool)
        report['M23'] = {
            'iso_i': int(f_iso_i.sum()), 'lof_i': int(f_lof_i.sum()),
            'mad_i': int(f_mad_i.sum()),
            'ens_invalid': int(inv.sum()), 'ens_extreme': int(ext.sum()),
            # M207 (F-04): ens_outlier_v2 stores ens_invalid ALONE (see M88), so
            # the report must count inv, not (inv|ext) -- the latter is the wider
            # statistical-diagnostic union that does NOT drive canonical
            # exclusion. Conflating them overstated the exclusion count.
            'ens_outlier_v2': int(inv.sum()),
            'diagnosticUnion_invOrExt': int((inv | ext).sum()),
            'unflagged_vs_v5': sorted(dm.loc[v5f & ~v2f, 'file'].tolist()),
            'newly_flagged_vs_v5': sorted(dm.loc[v2f & ~v5f, 'file'].tolist())}

    # ---------- M19 trend re-report on the v2-clean set (report only,
    # M19 columns untouched for v5 byte-compat) ----------
    try:
        report['spread_trend_v2'] = _spread_trend(
            dm, ~dm['ens_outlier_v2'].fillna(False).astype(bool))
    except Exception as ex:
        report['spread_trend_v2_error'] = str(ex)

    # ---------- M25: T-controlled power-fade trend (report only) ----------
    try:
        report['power_fade_trend'] = _powerfade_trend(dm)
    except Exception as ex:
        report['power_fade_trend_error'] = str(ex)

    if verbose:
        print('postprocess_master(v6):', json.dumps(report, default=str)[:2000])
    return dm, report


def _spread_trend(dm, keep_mask):
    cc = dm[keep_mask].dropna(subset=[
        'cell_spread_loaded_p95_mv', 'T_pack_mean_avg',
        'peak_I_discharge', 'date'])
    Xh = cc[['T_pack_mean_avg', 'peak_I_discharge']].values
    yh = cc['cell_spread_loaded_p95_mv'].values
    dt = pd.to_datetime(cc['date'])
    t_mo = ((dt - dt.min()).dt.days / 30.44).values
    days = dt.dt.date.values
    uniq = np.unique(days)
    Iref = float(cc['peak_I_discharge'].median())
    rng = np.random.default_rng(42)
    boot = []
    for _ in range(N_BOOT):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([np.where(days == d)[0] for d in pick])
        if len(np.unique(t_mo[idx])) < 3:
            continue
        X1 = np.column_stack([np.ones(len(idx)), Xh[idx]])
        b1 = np.linalg.lstsq(X1, yh[idx], rcond=None)[0]
        a1 = (b1[0] + b1[1] * SPREAD_T_REF + b1[2] * Iref) \
            + (yh[idx] - X1 @ b1)
        boot.append(float(np.polyfit(t_mo[idx], a1, 1)[0]))
    boot = np.asarray(boot)
    X0 = np.column_stack([np.ones(len(cc)), Xh])
    b0 = np.linalg.lstsq(X0, yh, rcond=None)[0]
    a0 = (b0[0] + b0[1] * SPREAD_T_REF + b0[2] * Iref) + (yh - X0 @ b0)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return {'slope_ols_mv_per_month': round(float(np.polyfit(t_mo, a0, 1)[0]), 3),
            'boot_ci95_mv_per_month': [round(float(lo), 3), round(float(hi), 3)],
            'p_slope_gt0': round(float((boot > 0).mean()), 3),
            'n_clean': int(len(cc)), 'n_boot': int(len(boot))}


def _i_channel_sampling_density(files, raw_loader):
    """M170: per-drive sampling density of the HV-current channel that excites
    the vreg resistance proxy.

    WHY THIS EXISTS. The `vreg_R_pack_mohm` proxy is a load-excited in-drive
    ratio of the voltage response to current, with I<->V matched within
    V_ALIGN_TOL (1500 ms). When the current/voltage channels are logged
    sparsely, (a) the alignment skew approaches the tolerance, diluting the
    ratio (regression attenuation -> R biased LOW), and (b) fewer samples land
    on the true instantaneous sag (peak sag under-captured -> R biased LOW).
    Denser logging removes both biases, so R is biased UPWARD purely by
    sampling density -- with no change in the pack. The raw-logging PID
    configuration changed mid-corpus (CHANGELOG M126, fifth configuration;
    M102 corrupt-PID rejection), roughly doubling HV-current coverage in the
    most recent batch, so this instrumentation variable is confounded with
    calendar time and MUST be controlled in the temporal trend (M170).

    Returns dict: file -> (eff_dt_s, coverage_frac), where eff_dt_s is the
    median inter-sample interval of the current channel and coverage_frac is
    the fraction of logged rows carrying a current sample.
    """
    import io
    ICOL = '[BMS] HV Battery Current (A)'
    out = {}
    for fn in files:
        try:
            b = raw_loader(fn)
            df = pd.read_csv(io.BytesIO(b),
                             usecols=lambda c: c in ('time', ICOL),
                             low_memory=False)
        except Exception:
            out[fn] = (np.nan, np.nan)
            continue
        if 'time' not in df.columns or ICOL not in df.columns:
            out[fn] = (np.nan, np.nan)
            continue
        ts = df['time']
        td = pd.to_timedelta(ts, errors='coerce')
        if td.notna().mean() > 0.5:
            t = td.dt.total_seconds().values
        else:
            t = pd.to_numeric(ts, errors='coerce').values
        t = np.asarray(t, float)
        m = df[ICOL].notna().values
        cov = float(m.mean())
        if m.sum() < 3:
            out[fn] = (np.nan, cov)
            continue
        d = np.diff(t[m])
        d = d[(d > 0) & (d < 20)]
        out[fn] = (float(np.median(d)) if len(d) else np.nan, cov)
    return out


def _powerfade_trend(dm, raw_loader=None):
    """M25/M170: temporal trend of the vreg (else vsag) pack-resistance proxy
    controlling for pack temperature and mean load current, v2-clean,
    day-cluster bootstrap.

    M170: when a `raw_loader` is supplied, the HV-current channel sampling
    density (median inter-sample interval + coverage) is added as covariates,
    so the reported time slope holds *logging cadence* constant. This removes
    the mid-corpus PID-configuration confound (see `_i_channel_sampling_density`)
    that otherwise levers the slope positive from the recent, more-densely-
    logged batch. With `raw_loader=None` the design is unchanged (byte-compat
    with the pre-M170 report path in postprocess_master)."""
    keep = ~dm['ens_outlier_v2'].fillna(False).astype(bool) \
        if 'ens_outlier_v2' in dm.columns else pd.Series(True, index=dm.index)
    rcol = 'vreg_R_pack_mohm' if 'vreg_R_pack_mohm' in dm.columns \
        else 'vsag_R_pack_mohm'
    icol = 'vreg_I_p95_A' if rcol == 'vreg_R_pack_mohm' else 'vsag_I_mean_A'
    cc = dm[keep].dropna(subset=[rcol, 'T_pack_mean_avg', icol, 'date'])
    if len(cc) < 20:
        return {'n': int(len(cc)), 'note': 'insufficient drives for trend'}
    # ---- M170 cadence covariate (optional; requires raw access) ----
    dens_cols = None
    cadence_controlled = False
    if raw_loader is not None and 'file' in cc.columns:
        dens = _i_channel_sampling_density(cc['file'].tolist(), raw_loader)
        eff = np.array([dens.get(f, (np.nan, np.nan))[0]
                        for f in cc['file']], float)
        cov = np.array([dens.get(f, (np.nan, np.nan))[1]
                        for f in cc['file']], float)
        ok = np.isfinite(eff) & np.isfinite(cov)
        # only engage the correction if density is resolvable on essentially
        # the whole clean set, so nClean is not silently eroded
        if ok.sum() >= 20 and ok.sum() >= int(0.8 * len(cc)):
            cc = cc.iloc[np.where(ok)[0]]
            dens_cols = (eff[ok], cov[ok])
            cadence_controlled = True
    dt = pd.to_datetime(cc['date'])
    t_mo = ((dt - dt.min()).dt.days / 30.44).values
    base = [np.ones(len(cc)), t_mo, cc['T_pack_mean_avg'].values,
            cc[icol].values]
    if dens_cols is not None:
        base += [dens_cols[0], dens_cols[1]]
    X = np.column_stack(base)
    y = cc[rcol].values
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    days = dt.dt.date.values
    uniq = np.unique(days)
    rng = np.random.default_rng(42)
    boot = []
    for _ in range(N_BOOT):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([np.where(days == d)[0] for d in pick])
        if len(np.unique(t_mo[idx])) < 3:
            continue
        bi, *_ = np.linalg.lstsq(X[idx], y[idx], rcond=None)
        boot.append(float(bi[1]))
    boot = np.asarray(boot)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return {'R_basis': rcol,
            'R_median_mohm': round(float(np.median(y)), 1),
            'slope_mohm_per_month_Tctrl': round(float(b[1]), 3),
            'bT_mohm_per_degC': round(float(b[2]), 3),
            'boot_ci95_mohm_per_month': [round(float(lo), 3),
                                         round(float(hi), 3)],
            'p_slope_gt0': round(float((boot > 0).mean()), 3),
            'n_clean': int(len(cc)), 'n_boot': int(len(boot)),
            'cadence_controlled': bool(cadence_controlled)}


# ======================================================================
# Orchestration (mirrors v5, using v6 analyze/postprocess)
# ======================================================================
# ======================================================================
# P0-01 (audit 2026-08-27): manifest-driven cohort selection + guard.
#
# The default 2026*.csv glob silently admits the two discontinued *_comparison
# captures, so the documented one-command path selects 291 files while the
# shipped master has 289 -- i.e. the correct exclusion happened OUT OF BAND and
# a future release could re-contaminate every statistic without any code change.
# These helpers make cohort selection driven by the typed raw manifest and fail
# loud on contamination or on a missing canonical file. They do not change the
# resulting master when the on-disk set already matches the manifest; they make
# that match a checked invariant instead of an accident.
# ======================================================================

# Defence-in-depth ONLY (used when no manifest is available). Manifest role
# records are the authoritative classifier; these markers are a last resort.
_NONCANONICAL_NAME_MARKERS = ('_comparison', 'e4orce', 'e-4orce', 'e_4orce')


def _is_noncanonical_by_name(basename):
    b = basename.lower()
    return any(m in b for m in _NONCANONICAL_NAME_MARKERS)


def _load_cohort_manifest(manifest_path, raw_dir):
    """Return (canonical, comparison, auxiliary) sets of raw basenames from a
    typed raw manifest, or None if no usable manifest is found. Tries the given
    path, then the same basename inside raw_dir."""
    candidates = []
    if manifest_path:
        candidates.append(manifest_path)
        candidates.append(os.path.join(raw_dir, os.path.basename(manifest_path)))
    path = next((p for p in candidates if p and os.path.exists(p)), None)
    if path is None:
        return None
    try:
        man = json.load(open(path))
        recs = man.get('files', []) if isinstance(man, dict) else []
    except Exception:
        return None
    canon, comp, aux = set(), set(), set()
    for r in recs:
        name = r.get('raw_name') or r.get('record_id')
        if not name:
            continue
        role = r.get('role')
        if role == 'canonical':
            canon.add(name)
        elif role == 'comparison_only':
            comp.add(name)
        elif role == 'auxiliary':
            aux.add(name)
    return (canon, comp, aux) if canon else None


def _select_canonical_cohort(files, raw_dir, manifest_path='raw_manifest.json',
                             strict=False, verbose=True):
    """Filter a globbed file list down to the canonical FWD cohort.

    strict=True (release gate): exact-set equality -- any on-disk file not typed
      canonical in the manifest, and any manifest-canonical file missing on disk,
      is a hard error.
    strict=False (ingest): typed/marked exclusions are dropped; genuinely-new
      canonical-looking files not yet in the manifest are ADMITTED append-only
      with a prominent notice (so ingestion still works); a missing canonical
      file is always a hard error.
    """
    coh = _load_cohort_manifest(manifest_path, raw_dir)
    by_name = {os.path.basename(f): f for f in files}
    on_disk = set(by_name)

    if coh is None:
        kept = sorted(f for b, f in by_name.items()
                      if not _is_noncanonical_by_name(b))
        dropped = sorted(b for b in on_disk if _is_noncanonical_by_name(b))
        if verbose:
            print(f"  [cohort] WARNING: no usable manifest ({manifest_path!r}); "
                  f"falling back to fragile filename-marker exclusion. "
                  f"Excluded {len(dropped)} by name: {dropped}")
        if strict:
            raise ValueError(
                "[cohort] strict/release gate requires a typed raw manifest; "
                f"none found at {manifest_path!r} or in {raw_dir!r}.")
        return kept

    # M207 (F-01/C-01): match on the canonical drive ID, not the raw basename.
    # Archive-native exports (e.g. '2026-07-30 22-06-51.csv') differ byte-for-
    # byte from the manifest's canonical names, so basename equality reported
    # every canonical file 'missing' (307 phantom-missing) and the non-strict
    # fallback then re-admitted the typed exclusions. _canonical_file_name
    # normalizes both sides to 'YYYYMMDD_HHMMSS.csv' before the role decision.
    canon, comp, aux = coh
    canon_ids = {_canonical_file_name(b) for b in canon}
    typed_excluded_ids = {_canonical_file_name(b) for b in (comp | aux)}
    kept, excluded, new_candidates = [], [], []
    on_disk_ids = set()
    for b, f in by_name.items():
        cid = _canonical_file_name(b)
        on_disk_ids.add(cid)
        if cid in canon_ids:
            kept.append(f)
        elif cid in typed_excluded_ids or _is_noncanonical_by_name(b):
            excluded.append(b)
        else:
            new_candidates.append(b)
    missing = sorted(canon_ids - on_disk_ids)

    if verbose:
        print(f"  [cohort] manifest: {len(canon)} canonical / {len(comp)} "
              f"comparison / {len(aux)} auxiliary; on disk kept={len(kept)} "
              f"excluded={len(excluded)} new={len(new_candidates)} "
              f"missing={len(missing)}")
        if excluded:
            print(f"  [cohort] typed/marked exclusions (skipped): {sorted(excluded)}")

    if missing:
        raise ValueError(
            f"[cohort] {len(missing)} manifest-canonical file(s) missing on "
            f"disk: {missing}. Refusing to build a master that silently drops "
            f"canonical drives. Restore the files or regenerate the manifest.")

    if strict:
        if new_candidates:
            raise ValueError(
                f"[cohort] strict/release gate: {len(new_candidates)} on-disk "
                f"file(s) are not typed in the manifest: {sorted(new_candidates)}."
                f" Exact-set equality requires every selected file to be a typed "
                f"canonical record. Regenerate raw_manifest.json first.")
        assert {_canonical_file_name(os.path.basename(f)) for f in kept} == canon_ids, \
            "[cohort] internal invariant: kept set != manifest canonical set"
        return sorted(kept)

    if new_candidates:
        if verbose:
            print(f"  [cohort] NOTE: admitting {len(new_candidates)} new "
                  f"canonical file(s) not yet typed in the manifest "
                  f"(append-only): {sorted(new_candidates)}. Regenerate "
                  f"raw_manifest.json so they become typed records before the "
                  f"release gate is run with --strict-cohort.")
        kept.extend(by_name[b] for b in new_candidates)
    return sorted(kept)


def build_master_from_raw(raw_dir, pattern='2026*.csv', verbose=True,
                          manifest_path='raw_manifest.json',
                          strict_cohort=False):
    files = sorted(glob.glob(os.path.join(raw_dir, pattern)))
    # P0-01: never trust the raw glob directly -- type it against the manifest.
    files = _select_canonical_cohort(files, raw_dir, manifest_path=manifest_path,
                                     strict=strict_cohort, verbose=verbose)
    rows = []
    for fn in files:
        with open(fn, 'rb') as f:
            r = analyze_bytes(f.read(), os.path.basename(fn))
        d, tm = _date_from_name(fn)
        r.setdefault('date', d)
        r.setdefault('time_start', r.get('time_start') or tm)
        rows.append(r)
        if verbose:
            print(f"  processed {os.path.basename(fn)}: "
                  f"{r.get('distance_km', '?')} km")
    dm = pd.DataFrame(rows)
    if 'date' in dm.columns:
        dm = dm.sort_values(['date', 'time_start']).reset_index(drop=True)
    dm, report = postprocess_master(dm, verbose=verbose)
    return dm, report


def run_pipeline(raw_dir='.', out_dir='.', pattern='2026*.csv',
                 config_path='summary_config.json', verbose=True,
                 recompute_m119v2=False, manifest_path='raw_manifest.json',
                 strict_cohort=False):
    import compute_summary_arrays as csa
    dm, report = build_master_from_raw(raw_dir, pattern, verbose,
                                       manifest_path=manifest_path,
                                       strict_cohort=strict_cohort)
    master_path = os.path.join(out_dir, 'drive_master.csv')
    dm.to_csv(master_path, index=False)
    if verbose:
        print(f"wrote {master_path}: {dm.shape[0]} drives x {dm.shape[1]} cols")
    odometer_km = None
    seasonal_cfg = None
    ambient_by_drive = None
    session_cfg = None
    if config_path and os.path.exists(config_path):
        try:
            cfg = json.load(open(config_path))
            odometer_km = cfg.get('vehicle', {}).get('odometerKm')
            # F-12 (audit): run_pipeline previously read only odometerKm and
            # never forwarded seasonalAssumptions, so build_summary_arrays
            # silently skipped the seasonalLife block. The shipped JSON carried
            # seasonalLife only because it was produced by an out-of-band call,
            # i.e. the documented one-command pipeline could not reproduce the
            # artifact. Forward the config so seasonalLife is regenerated here.
            seasonal_cfg = cfg.get('seasonalAssumptions')
            ambient_by_drive = cfg.get('ambientByDrive')
            # P0-14 (2026-07-30): the same defect applied to sessionLedgerAudit.
            # run_pipeline read cfg but never passed session_cfg=cfg, so a
            # one-command build emitted sessionLedgerAudit:null while the shipped
            # dashboard used a populated reconciliation block (again produced
            # out-of-band). Forward the whole config; _session_ledger_audit reads
            # cfg['sessions'] / cfg['sessionGroups'] itself.
            session_cfg = cfg
        except Exception as ex:
            if verbose:
                print(f"  (config read failed: {ex})")
            ambient_by_drive = None

    def loader(fn):
        with open(os.path.join(raw_dir, fn), 'rb') as f:
            return f.read()

    # M148 (2026-08-21): load the prior summary_arrays.json (if present) so
    # build_summary_arrays can carry socHysteresisV2 forward instead of
    # refitting it -- see CHANGELOG M148 for why the M119-v2 hazard-model
    # fit is now recompute-on-demand rather than routine.
    prev_arrays = None
    arrays_path_existing = os.path.join(out_dir, 'summary_arrays.json')
    if os.path.exists(arrays_path_existing):
        try:
            prev_arrays = json.load(open(arrays_path_existing))
        except Exception:
            prev_arrays = None

    # P0-2 (audit F-02, 2026-09-11): forward raw_dir explicitly. The energy-MC
    # fresh-recompute gate in build_summary_arrays
    # (compute_summary_arrays.py ~17139) is `recompute_energy_mc and ... and
    # raw_dir` -- it hard-requires a truthy raw_dir and does NOT fall back to
    # the loader closure. Previously run_pipeline() passed only `loader`, so the
    # documented one-command CLI silently produced recomputeMode='carriedForward'
    # regardless of recompute_energy_mc=True, contradicting the M217 policy (and
    # the same gap disabled _audit_raw_manifest's oneToOneVerified check).
    # Passing raw_dir closes that. See CHANGELOG M247/M248 for the prior manual
    # workaround this replaces.
    arrays = csa.build_summary_arrays(dm, loader, with_raw=True,
                                      odometer_km=odometer_km,
                                      seasonal_cfg=seasonal_cfg,
                                      ambient_by_drive=ambient_by_drive,
                                      session_cfg=session_cfg,
                                      raw_dir=raw_dir,
                                      recompute_m119v2=recompute_m119v2,
                                      prev_arrays=prev_arrays)

    # P0-2 fail-closed release gate: with raw_dir now forwarded, a release build
    # MUST carry a freshly-recomputed energy-MC block. If it came back carried
    # forward, the recompute silently failed (e.g. a missing standalone module)
    # and the build must not be trusted as reproducible. strict_cohort marks a
    # release build; ingestion runs (strict_cohort=False) may legitimately carry
    # forward under the recompute_energy_mc escape hatch and are exempted.
    if strict_cohort:
        _mc_block = arrays.get('energyUncertaintyMC') or {}
        _mc_mode = _mc_block.get('recomputeMode')
        if _mc_mode != 'fresh':
            raise RuntimeError(
                "energyUncertaintyMC.recomputeMode == %r (expected 'fresh') on a "
                "release build. raw_dir forwarding or the standalone MC modules "
                "failed; refusing to ship a carried-forward uncertainty block "
                "(P0-2)." % (_mc_mode,))

    # P0-14 assertion: if the config declares sessions/sessionGroups, the audit
    # block MUST be non-null, or the one-command build has silently regressed.
    if session_cfg and (session_cfg.get('sessions')
                        or session_cfg.get('sessionGroups')):
        if not arrays.get('sessionLedgerAudit'):
            raise RuntimeError(
                "sessionLedgerAudit is null although the config declares "
                "sessions/sessionGroups; session_cfg was not forwarded "
                "correctly (P0-14).")
    arrays_path = os.path.join(out_dir, 'summary_arrays.json')
    json.dump(arrays, open(arrays_path, 'w'), ensure_ascii=False, indent=1)
    if verbose:
        print(f"wrote {arrays_path}")
    return dm, arrays, report


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(
        description='X-Trail e-POWER v6 pipeline: raw CSVs -> master + summary_arrays.json')
    ap.add_argument('--raw-dir', default='.')
    ap.add_argument('--out-dir', default='.')
    ap.add_argument('--pattern', default='2026*.csv')
    ap.add_argument('--config', default='summary_config.json')
    ap.add_argument('--manifest', default='raw_manifest.json',
                    help='P0-01: typed raw manifest used to select the canonical '
                         'cohort and reject comparison/auxiliary contamination.')
    ap.add_argument('--strict-cohort', action='store_true',
                    help='P0-01 release gate: require exact-set equality between '
                         'the on-disk files and the manifest canonical records '
                         '(fail on any untyped orphan or missing canonical). Use '
                         'for release builds; omit during ingestion.')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--recompute-m119v2', action='store_true',
                    help='M148: force a fresh M119-v2 hazard-model refit '
                         '(expensive, ~250k-row 4x5 GLM ladder; known to '
                         'OOM a <=4GB-RAM environment). Default: carry the '
                         'last-computed socHysteresisV2 block forward.')
    a = ap.parse_args()
    run_pipeline(a.raw_dir, a.out_dir, a.pattern, a.config,
                 verbose=not a.quiet,
                 recompute_m119v2=a.recompute_m119v2,
                 manifest_path=a.manifest,
                 strict_cohort=a.strict_cohort)

print("compute_drive_summary_v6.py loaded OK")
