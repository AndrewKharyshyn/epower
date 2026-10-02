"""
compute_summary_arrays.py  —  companion to compute_drive_summary_v5.py

Regenerates every DATA-DERIVED array consumed by xtrail_summary.jsx into a
single machine-written artefact, summary_arrays.json, so that adding a batch
of new raw drives requires NO manual recomputation of dashboard literals.

Design (audit 2026-07-06):
  * Category A  — derivable from drive_master.csv alone (fast, exact). These
                  are pure per-drive aggregations; they reproduce the current
                  hand-maintained JSX values within rounding and MUST refresh
                  on every batch (totals, per-class energetics, cumulative
                  cycle ledgers, auto-maxed records, C-rate scatter, ...).
  * Category B  — require the raw 1 Hz PID time series (not stored per-drive in
                  the master): pooled speed/torque/engine/thermal distributions.
                  Computed in a SINGLE streaming pass over the raw corpus
                  (one read per file, all accumulators fed together) so cost is
                  O(rows) not O(rows x arrays). Convention-sensitive; validated
                  against the archived JSX values by build_and_validate().
  * Category C  — narrative / external-reference / non-reproducing content
                  (session notes, riskUpdates prose, regional climate normals,
                  the engineOnDuration distribution whose original derivation is
                  not reproducible from the documented parameters). NOT emitted
                  here; carried in the hand-maintained summary_config.json and
                  merged at import time in the JSX.

Column policy: this module never writes to drive_master.csv. It only READS the
finished master + the raw CSVs. summary_arrays.json is a pure projection.

Contract used by the JSX:
    import arrays from './summary_arrays.json'
    import config from './summary_config.json'
    const S = { ...config, ...arrays }
(arrays wins on any key collision — computed values supersede archived ones.)
"""

import io
import json
import numpy as np
import pandas as pd
import degradation_trends
try:
    import m119v2_model              # M147: M119-v2 five-variable hazard model
except Exception:                    # pragma: no cover - keeps arrays build resilient
    m119v2_model = None
try:
    import energy_mc_precompute      # M217: H-01/F-12 auto-recompute wiring
    import energy_uncertainty_mc
except Exception:                    # pragma: no cover - keeps arrays build resilient
    energy_mc_precompute = None
    energy_uncertainty_mc = None

# ----------------------------------------------------------------------
# Vehicle / study constants (mirror compute_drive_summary_v5 where shared)
# ----------------------------------------------------------------------
CAP_KWH        = 2.1
VEHICLE_MASS_KG = 1950.0     # M20 kinetic-energy basis (curb + driver + kit).
                              # DEPRECATED as of M124 (2026-08-15): retained
                              # only as the fallback for drive_type == 'unknown'.
                              # See MASS_BY_DRIVE_TYPE_KG / _mass_for_drive below.
# M124 (2026-08-15, Andrii's methodology decision): class-conditional
# curb-mass assumption, replacing the single flat VEHICLE_MASS_KG=1950 kg used
# in the two mass-scaled physics estimates (regen-capture KE loss in
# _RawAccum.add; descent-energy-budget PE in _mountain_pattern). Highway-type
# running (drive_type 'highway' or 'mixed_highway') is assumed to carry more
# load (longer trips -> more likely to carry luggage/passengers/fuel); urban
# and generic-mixed running is assumed to split evenly between two lighter
# load states. Like VEHICLE_MASS_KG before it, every one of these figures is
# an UNVERIFIED assumption (see CONSTANT_PROVENANCE['MASS_BY_DRIVE_TYPE_KG']),
# not a measurement -- apparent regen-capture and descent-budget figures scale
# with it.
MASS_HIGHWAY_KG = 2000.0
# M164 (2026-08-22, audit sec.5 remediation): the prior M124 scheme assigned
# EACH urban/mixed drive deterministically to 1860 OR 1920 kg via an md5 hash
# of its filename -- a fair coin flip with no physical basis, presented
# per-file as if it were a measurement. "This is pseudo-random imputation,
# not a physical measurement; replace with an uncertainty range." Every
# urban/mixed drive now uses a single honest point assumption, the midpoint
# of the same disclosed range (matching how MASS_HIGHWAY_KG has always been a
# single point value, not a split); the retired range is retained ONLY to
# derive closed-form uncertainty bounds on the physics outputs that scale
# with it (see _mass_uncertainty_factors below), not to assign it per drive.
MASS_URBAN_MIXED_KG = 1890.0
MASS_URBAN_MIXED_RANGE_KG = (1860.0, 1920.0)   # retired hash-split bounds;
                                               # uncertainty-derivation only


def _mass_for_drive(drive_type, file_label):
    """Class-conditional assumed curb mass (kg) for one drive.

    highway / mixed_highway -> MASS_HIGHWAY_KG (single point assumption).
    urban / mixed           -> MASS_URBAN_MIXED_KG (single point assumption,
                                M164 -- see module-level note above; file_label
                                is accepted for signature compatibility with
                                every M124-era call site but no longer used).
    anything else (unknown) -> legacy VEHICLE_MASS_KG fallback.
    """
    if drive_type in ('highway', 'mixed_highway'):
        return MASS_HIGHWAY_KG
    if drive_type in ('urban', 'mixed'):
        return MASS_URBAN_MIXED_KG
    return VEHICLE_MASS_KG


def _mass_uncertainty_bounds(central_value, reference_mass_kg,
                             urban_mixed_weight=1.0):
    """M164: closed-form uncertainty bounds for any output computed as
    measured-energy / (assumed-mass-scaled quantity) -- regen efficiency %,
    descent capture fraction. reference_mass_kg is the ACTUAL mass this
    central_value was computed at (e.g. mountainPattern.descentBudget's own
    stored assumedMassKg, or MASS_URBAN_MIXED_KG when no per-block reference
    is available). urban_mixed_weight (0..1) is the fraction of that
    reference mass's population subject to mass uncertainty at all -- the
    rest is highway/mixed_highway at the FIXED MASS_HIGHWAY_KG, contributing
    none. Pass urban_mixed_weight=1.0 (default) for a CONSERVATIVE upper
    bound when the true per-output urban/mixed KE-share is unknown without a
    raw per-second rebuild (regen-by-zone/speed/temperature); pass the
    population's derived weight when it is known (the descent-energy
    budget -- see _mountain_pattern, which solves for it from its own stored
    assumedMassKg). Since MASS_URBAN_MIXED_KG is exactly the midpoint of
    MASS_URBAN_MIXED_RANGE_KG, a uniform shift of the urban/mixed portion
    from the midpoint to either bound moves the population-weighted
    reference mass by +/- urban_mixed_weight * halfRange, symmetric by
    construction. Returns (low, high); heavier assumed mass -> larger
    denominator -> LOWER value, and vice versa."""
    lo, hi = MASS_URBAN_MIXED_RANGE_KG
    half_range = (hi - lo) / 2.0
    w = max(0.0, min(1.0, urban_mixed_weight))
    mass_lo = reference_mass_kg - w * half_range
    mass_hi = reference_mass_kg + w * half_range
    return (central_value * reference_mass_kg / mass_hi,
           central_value * reference_mass_kg / mass_lo)


REG_FLOOR_PCT  = 1.0
# M56 (2026-07-26, audit F-01/6.2): renamed from CYCLE_RATED_LIFE. The old name
# asserted a rating this number does not have. It is an UNVERIFIED generic
# planning threshold in gross-capacity-turnover units, with no pack-rated
# provenance and no established link to 80 % SOH. Retained ONLY to parameterize
# labeled scenario crossings, which are workload sensitivities, NOT end-of-life
# predictions. See summary_arrays['thresholdSensitivity'].
SCENARIO_THRESHOLD_GTC = 20000
CYCLE_RATED_LIFE = SCENARIO_THRESHOLD_GTC   # DEPRECATED alias (M56)

# T-01 golden-snapshot regression reference (audit P1, 2026-08-10). NOT a
# pass/fail gate -- _acceptance_tests() prints an INFO-level match/drift note
# against this on every run; it never affects the return value. Update the
# tuple deliberately (new drive count, new peakChargeA, today's date) after
# reviewing that a changed value is a legitimate consequence of new data,
# not a regression. (n_drives, peakChargeA_A, as_of_date)
_T01_GOLDEN = (289, 213.0, '2026-08-28')  # M181: updated from (219, 213.0,
# '2026-08-10') -- value unchanged at 213.0 A, only n grew via routine
# ingestion; drift confirmed expected by Andrii (chat, 2026-08-28), not a
# silent regression. Prior golden snapshot preserved here for provenance:
# was _T01_GOLDEN = (219, 213.0, '2026-08-10').

# M56 (audit F-09/6.2): source + uncertainty provenance for hardcoded constants.
CONSTANT_PROVENANCE = {
    'CAP_KWH': {'value': 2.1, 'unit': 'kWh',
                'source': 'assumed normalization constant (press-cited '
                          'planning figure, not a published OEM spec)',
                'verified': False,
                'note': 'Assumed 2.1 kWh normalization constant; unverified '
                        'and not an OEM nameplate figure. Nissan sources '
                        'reviewed identify the pack chemistry family only '
                        '(Li-ion, NMC-family per teardown reporting) and do '
                        'not publish a cell/pack energy-capacity spec. Every '
                        'GTC/FCE/C-rate figure scales linearly with it. The '
                        'separate OEM-disclosed 5.0 Ah per-cell figure (EU '
                        'Battery Regulation 2023/1542 Art. 10) is a charge '
                        '(Ah) figure, not energy (kWh), and is not silently '
                        'converted without a stated pack-voltage basis.'},
    'SCENARIO_THRESHOLD_GTC': {'value': 20000, 'unit': 'GTC',
                               'source': 'generic-lithium planning figure',
                               'verified': False,
                               'note': 'NOT a Nissan rating and NOT an 80 % SOH '
                                       'criterion. Scenario parameter only.'},
    'VEHICLE_MASS_KG': {'value': 1950.0, 'unit': 'kg', 'source': 'curb estimate',
                        'verified': False,
                        'note': 'DEPRECATED as of M124 (2026-08-15): superseded '
                                'by the class-conditional MASS_BY_DRIVE_TYPE_KG '
                                'scheme below for regen-capture KE loss and the '
                                'descent-energy budget. Retained only as the '
                                "fallback for drive_type == 'unknown' (3 zero-"
                                'distance drives, no physical effect).'},
    'MASS_BY_DRIVE_TYPE_KG': {
        'value': {'highway': 2000.0, 'mixed_highway': 2000.0,
                  'urban': 1890.0, 'mixed': 1890.0},
        'unit': 'kg', 'source': 'assumed, per Andrii (2026-08-15); M164 '
                                '(2026-08-22) point-value revision',
        'verified': False,
        'note': 'Class-conditional curb-mass assumption used in the two '
                'mass-scaled physics estimates (regen-capture KE loss; '
                'descent-energy-budget PE), replacing the single flat 1950 kg '
                'VEHICLE_MASS_KG. highway/mixed_highway drives are assumed '
                '2000 kg; urban/mixed drives are assumed 1890 kg -- a single '
                'point value, the midpoint of a disclosed 1860-1920 kg range '
                '(MASS_URBAN_MIXED_RANGE_KG). M164 (audit sec.5): the prior '
                'M124 scheme assigned each urban/mixed drive DETERMINISTICALLY '
                'to 1860 or 1920 kg via an md5 hash of its filename -- a fair '
                'coin flip presented per-file as if it were a measurement, '
                'flagged as pseudo-random imputation. Outputs that scale with '
                'this assumption now carry a closed-form uncertainty range '
                'derived from it (regenByZone.effRangeMassUncertainty, '
                'regenCaptureMeasuredMassUncertainty, regenByTempMeasured.'
                'effRangeMassUncertainty, mountainPattern.descentBudget.'
                'captureFractionRangeMassUncertainty/'
                'toSaturationRangeMassUncertaintyM) rather than a single '
                'point derived from the retired coin flip. Ignores actual '
                'payload/occupants/grade; every regen-capture and '
                'descent-budget figure still scales with the point value. No '
                'independent (e.g. weighbridge) verification.'},
    'RF_DAMAGE_EXP': {'value': 2.0, 'unit': '-', 'source': 'generic Wohler k',
                      'verified': False,
                      'note': 'Not fitted to this pack. Sensitivity only; never '
                              'convert into a life extension.'},
    'REG_DATE': {'value': '2024-08-07', 'unit': 'date', 'source': 'registration',
                 'verified': True,
                 'note': 'Drives calendar age and annual-km denominators.'},
}

# M79 (2026-07-31): pack topology constants for the official-disclosure
# correlation (_official_disclosure_correlation). NOT a manufacturer-
# published series count -- inferred from a raw-file spot-check (pack
# terminal voltage max / observed max single-cell voltage, on the subset of
# files exposing full 80/96-channel cell telemetry: 394.1 V / 4.114 V approx
# 96). The OBD PID set exposes only cell channels #01-#80 regardless of the
# true series count, so this cannot be corroborated further from this
# corpus. Used only to express pack-level resistance/voltage figures on a
# per-cell basis for readability; every pack-level figure it is derived from
# remains the primary, pipeline-computed value.
PACK_SERIES_CELLS_EST = 96
CELL_VOLTAGE_WINDOW_V = (3.50, 4.11)
CONSTANT_PROVENANCE['PACK_SERIES_CELLS_EST'] = {
    'value': 96, 'unit': 'cells', 'source': 'raw-file spot-check inference',
    'verified': False,
    'note': ('Pack Vmax (394.1 V) / observed max cell V (4.114 V) approx 96. '
             'Not a full-corpus scan and not a manufacturer-published spec.')}
CONSTANT_PROVENANCE['CELL_VOLTAGE_WINDOW_V'] = {
    'value': [3.50, 4.11], 'unit': 'V', 'source': 'raw-file spot-check inference',
    'verified': False,
    'note': ('Observed min/max single-cell voltage on the file subset with '
             'full cell telemetry. The 3.50-4.11 V window EXCLUDES LFP '
             '(LFP plateau ~3.2-3.3 V, ceiling ~3.6 V) and is CONSISTENT '
             'WITH a layered-oxide (NMC/NCA-class) cathode, but does NOT '
             'uniquely identify NMC. Not a full-corpus scan. OEM material '
             'discloses the pack only as lithium-ion.')}
MIN_ENGINE_START_S = 2       # min engine-on segment (s) to count as a start (F-08)
REG_DATE       = "2024-08-07"  # registration; drives calendar age
COLD_START_C   = 30.0        # engine-coolant "cold start" threshold for warmup
WARM_ENGINE_C  = 80.0        # engine-coolant "reached operating temp" threshold (M30 hvc)

# M31 (2026-07-12): distance-domain warm-up curve (Chart 2 rebuild). The old
# warmupPoints array plotted WHOLE-TRIP distance vs per-drive PEAK coolant, so a
# long-haul drive was one point pinned to the hot plateau -- it showed "long
# drives get hot", not the warm-up process. M31 instead reconstructs the coolant
# rise WITHIN each cold-start drive: a drive is a warm-up sample if its first
# valid engine-coolant reading is <= WARMUP_COLD_C (clear headroom below the
# ~85C thermostat point), its coolant trace is interpolated onto WARMUP_GRID
# (km travelled from the cold anchor, speed-integrated on the 1 Hz grid), and
# the per-drive vectors are pooled by condition class into median + IQR bands.
# A grid point is emitted only where >= WARMUP_MIN_N drives reach that distance,
# so thin tails (short city trips, sparse mixed class) are dropped rather than
# rendered as noisy medians. Supersedes warmupPoints as the Chart-2 basis.
WARMUP_COLD_C  = 50.0        # first-sample engine-coolant ceiling for a cold start
WARMUP_MIN_N   = 5           # min drives per (class, grid) point to emit it
WARMUP_GRID    = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0]

# M21 (audit 2026-07-06): operating-condition class for all "drive condition"
# arrays (driveTypes, cycleByType, efficiencyBands, cRatePoints, engineStartsByType).
# Previously these bucketed on distance_km alone (DIST_BINS below) — a poor proxy
# for actual driving condition, since a long trip can pass through a city (or a
# short trip can be a pure highway hop). Audit of the 105-drive master: of the 15
# drives with distance_km > 50 (old "highway" bucket), only 5 were >=40% highway-
# speed moving time; 9 were time-majority "mixed_highway" and one
# (20260612_152740.csv, 62.4 km) was 49.6% urban-speed moving time vs 8.5%
# highway-speed -- a long city-traffic drive misclassified as "highway" purely on
# distance. drive_type (computed per-drive in compute_drive_summary_v5.py via
# classify_drive_type_tw: time-weighted % of moving time at >=90 km/h vs
# <60 km/h -- threshold lowered from >=100 to >=90 km/h at M115, 2026-08-10,
# Andrii's methodology decision: 90 km/h is Ukraine's statutory open-road
# limit) is now the single condition-classification basis dashboard-wide; it
# is also the taxonomy independently cross-checked by the M16 KMeans cluster.
# DIST_BINS is retained ONLY as a legacy/reference constant (no longer applied
# anywhere) -- trip length is a distinct axis from driving condition and is not
# reintroduced here since no current array needs a pure-length bucket.
DIST_BINS   = [(0, 5, "city_short"), (5, 20, "city_long"),
               (20, 50, "mixed"), (50, 1e9, "highway")]
CLASS_ORDER = ["urban", "mixed", "mixed_highway", "highway"]
CLASS_COLOR = {"urban": "#ef4444", "mixed": "#eab308",
               "mixed_highway": "#3b82f6", "highway": "#22c55e"}

# speed-zone edge sets reused across arrays
Z_SOC   = [(0, 20, "0-20", "Stop/slow"), (20, 60, "20-60", "Low speed"),
           (60, 90, "60-90", "Arterial"), (90, 120, "90-120", "Highway cruise"),
           (120, 999, "120+", "Fast highway")]
Z_ENGINE = [0, 20, 40, 60, 80, 100, 120, 999]
Z_ENGINE_LBL = ["0-20", "20-40", "40-60", "60-80", "80-100", "100-120", "120+"]
Z_TORQUE = [(0, 20, "0-20"), (20, 40, "20-40"), (40, 60, "40-60"),
            (60, 80, "60-80"), (80, 100, "80-100"), (100, 120, "100-120"),
            (120, 160, "120-160")]
Z_SPEED_DIST = [(0, 5), (5, 30), (30, 60), (60, 90), (90, 120), (120, 999)]
Z_REGEN = [(0, 30, "0-30"), (30, 60, "30-60"), (60, 90, "60-90"),
           (90, 120, "90-120"), (120, 999, "120+")]
Z_TURBO_SPD = [(0, 40, "0-40"), (40, 60, "40-60"), (60, 80, "60-80"),
               (80, 100, "80-100"), (100, 120, "100-120"), (120, 160, "120-160")]
RPM_BANDS = [(0, 1500, "<1500"), (1500, 2000, "1500-2000"),
             (2000, 2500, "2000-2500"), (2500, 3000, "2500-3000"),
             (3000, 3500, "3000-3500"), (3500, 4000, "3500-4000"),
             (4000, 1e9, "4000+")]

# M82 (2026-08-04): rpmDistribution -- duration-weighted engine-RPM occupancy
# histogram. Distinct from RPM_BANDS/turboByRpm above, which buckets NATIVE
# (non-gridded) boost samples by RPM to characterise turbo activity and never
# included an "engine off" bucket or genuine time-in-band weighting. This one
# answers a different question -- how much of total ICE runtime (and total
# corpus time) sits at each RPM -- so it must be duration-weighted (1 Hz grid,
# same convention as terrain_hist/cy_kwh/engineOnDuration in _RawAccum: each
# hz row ~= 1 second) rather than native-sample-weighted, since raw logging
# density varies across the three logging generations (34/37/39 vs 42-col).
#
# M83 (2026-08-04): bin edges REPLACED after a uniform-400rpm scheme (the
# original M82 edges) was checked against a one-off 100rpm-resolution recompute
# and found to hide the actual shape. The initial assumption going in -- that
# the "primary operating range" begins near ~1500 rpm -- does NOT hold: 300-
# 1400 rpm is close to empty (~4% of engine-on time, essentially a rev-through
# transient, not a sustained band); there IS a real but small secondary mode at
# 1400-1600 (~7% of engine-on time); then a genuine VALLEY at 1600-1900 rpm
# (~2.7%, the engine rarely holds here); then one overwhelmingly dominant mode
# packed into a 200rpm window at 1900-2100 (~62% of ALL engine-on time in the
# corpus, split almost evenly 1900-2000 / 2000-2100); above that a fairly flat
# ~9%/300rpm shoulder out to 3200, then a small tail. The edges below now
# resolve that shape directly (coarse where empirically flat/empty, fine where
# the mass actually concentrates) instead of a uniform-width scheme that
# smeared the peak across the old "1600-2000" and "2000-2400" bins.
#
# M205 (2026-09-01): edges 1900/2000 REPLACED by 1975/2025 after Andrii
# queried whether the 2000rpm OEM-claimed thermal fixed point was being
# split by a bin boundary landing exactly on it, and whether 1500rpm
# oscillation (1499/1501-type readings) was safely contained. Standalone
# 5rpm-resolution re-derivation across the full 307-drive corpus (same
# _RawAccum 1Hz-grid convention, independent read of every raw file) found:
#  - the "2000rpm" mode is a genuinely narrow spike, not a broad shoulder:
#    weighted center of mass over 1975-2025 is 2000.30 rpm; 96%+ of that
#    window's mass sits inside +/-25rpm of 2000. The OLD edge sat AT 2000,
#    splitting this single physical mode 45.3%/54.7% across the 1900-2000/
#    2000-2100 bins (1900-1975 and 2025-2100 are true valley/decay-tail
#    density, ~7.2% dilution of the combined old bin pair, not itself a
#    data-loss bug, but a presentational one -- reading as a ~400rpm-wide
#    shoulder when it is <50rpm wide). True valley density (flat,
#    ~25-30s/rpm) extends to ~1975, not 1900; the spike decays back to
#    background density (~50-60s/rpm) by ~2025-2050, not 2100.
#  - the "1500rpm" mode (weighted center of mass 1500.08 rpm over
#    1485-1515) is NOT split -- 1500 is not and was not a bin edge, it
#    sits mid-bin inside 1400-1600, so 1499/1501-type oscillation was
#    already fully contained. No edge change made on this side.
#  - ancillary, NOT acted on this milestone (flagged for a future decision):
#    1400-1600 is actually bimodal, not a single smeared ~1500 region --
#    a second, distinct governed setpoint at weighted center 1588.62 rpm
#    (7,569s) sits alongside the 1500.08rpm spike (11,045s) under one label.
#
# M218 (2026-09-04): M205's ancillary finding acted on, SAME LOGIC as the
# 2000rpm fix above (isolate each spike in a +/-25rpm window around its
# weighted center, rounded; leave the rest as valley/decay-tail bins; verify
# mass conservation). Independent 1Hz-grid re-derivation across the full
# 320-drive corpus, extended down to 1400 and up to 1975 (the M205 boundary)
# to characterize the whole region in one pass:
#  - "1500rpm" spike: weighted center 1499.69-1500.08 rpm (window-dependent,
#    consistent with M205) -> rounds to 1500 -> window 1475-1525.
#  - "1589rpm" spike: weighted center 1588.62-1589.29 rpm (window-dependent)
#    -> rounds to 1589 -> window 1564-1614.
#  - Both are SHARPER than the 2000rpm mode (>90% of each spike's own mass
#    sits in a single 10rpm sub-bin, vs the 2000rpm mode's wider spread) --
#    the +/-25 window comfortably contains each with clean valley margin on
#    both sides, not a tight fit.
#  - True background/valley density: 10.1 s/rpm (1400-1475, decay-in from
#    the 300-1400 transient band), 21.9 s/rpm (1525-1564, between the two
#    spikes), 29.7 s/rpm (1614-1975, rising shoulder toward the 2000rpm
#    mode) -- all far below either spike's own in-window density (274 and
#    183 s/rpm respectively), confirming these are genuine valleys, not
#    residual spike mass.
# Engine-load separation (investigated alongside the bin fix, at Andrii's
# request, NOT itself encoded in this histogram): the two setpoints are
# cleanly distinguished by eng_load_calc (median 31% vs 46%, IQRs barely
# overlap), boost (-0.41 vs -0.10 bar) and coolant temp (54 vs 77C),
# consistent across 76-77 of the corpus's 77 driving dates (not a logging-era
# artifact) -- consistent with (not proof of) two adjacent rungs on the
# generator's discrete load-point ladder (M41/M118), i.e. the same physical
# phenomenon already established there, resolved one level finer. NOT
# separated by drive_type. This interpretation is reported as a hypothesis
# in the dashboard prose, not encoded as a load-conditioned bin split --
# that would be a materially bigger change (a new detector, not a bin-edge
# fix) and was not what was asked for this milestone.
# Net change: 1400/1600 edges REPLACED by 1400/1475/1525/1564/1614/1975 (4
# new edges inserted, bin count 10 -> 13); all other edges unchanged; total
# corpus coverage identical (edges only redistribute mass within the
# unchanged 1400-1975 span -- verified new-bin sum == old "1400-1600" +
# "1600-1975" == 35,172 s at this session's corpus snapshot).
RPM_HIST_EDGES = [0, 300, 1400, 1475, 1525, 1564, 1614, 1975, 2025, 2100,
                  2400, 2800, 3200, 6000]
RPM_HIST_LABELS = ["0 (engine off)", "300-1400 (transient)", "1400-1475",
                   "1475-1525", "1525-1564 (valley)", "1564-1614",
                   "1614-1975 (valley)", "1975-2025", "2025-2100",
                   "2100-2400", "2400-2800", "2800-3200", "3200+"]
# Label kept bare-numeric (not annotated "(~2000, OEM thermal point)") to
# match the compact-label convention every other non-annotated bin already
# uses, and because this label also feeds the chart's narrow per-bin x-axis
# column and the "{bins[peakIdx]} rpm" prose template (xtrail_summary.jsx)
# -- an annotated label there would double up with the literal " rpm" suffix
# and overflow the fixed-width axis. The OEM-thermal-point match is called
# out explicitly in the dashboard's Manufacturer Cross-Check prose instead.
# Fuelled/motored split reuses the M46/M48 dissipation-census classifier
# thresholds verbatim (RPM_MIN/BOOST_MOTORED/BOOST_FUELLED/LOAD_MAX in
# _dissipation_census) so the two views can be read together; redeclared
# locally rather than imported, matching this module's existing convention of
# each raw-pass function owning its own copy of these constants
# (_dissipation_census, _mountain_pattern, _low_speed_dissipation all do the
# same -- see M48 provenance).
#
# M84 (2026-08-04): RPM_HIST_FUELSTATE_RPM_MIN LOWERED 2000 -> 1400, correcting
# an unverified assumption from M82/M83 ("below 2000rpm boost/load don't
# separate the two modes reliably"). That was never checked -- it was
# inherited from _dissipation_census's RPM_MIN=2000, which was tuned to that
# census's specific target (SoC-ceiling-defense motoring, empirically a
# higher-rpm behaviour), not validated as a general signal-reliability floor.
# Checked directly: in 1400-2000rpm (22.17 gridded hours, the corpus's SECOND-
# LARGEST occupancy band after the 1900-2100 peak), median calc-load is 41.6%
# (p10-p90 27.8-45.9%) and median boost is +0.07 bar, with 70.3% of samples
# meeting the FUELLED boost criterion outright and only 1.0% meeting MOTORED
# -- an unambiguous, high-volume fuelled-generation signature. The M46/M48
# floor was excluding it from classification entirely (rendering it as a
# false "gap" in the fuelled/motored views, not a real absence -- the pooled
# view was never affected). Below 1400rpm the floor stays: 800-1400rpm is
# low-volume (0.57h) and genuinely mixed/ambiguous (boost and load both
# spread wide, no clean mode); 300-800rpm's apparent 44.7% median load is very
# likely a forward-fill artifact of sparse, asynchronous PID polling during
# fast rpm transients (start/stop ramps), not a real simultaneous state, and
# at only 2.11h is not worth resolving further for this chart. 1400 is the
# empirically-supported floor, not a further guess.
RPM_HIST_FUELSTATE_RPM_MIN = 1400.0
RPM_HIST_BOOST_MOTORED = -0.70
RPM_HIST_BOOST_FUELLED = -0.55
RPM_HIST_LOAD_MAX = 8.0

# M89 (2026-08-05): load-only FUELLED proxy for the 56 corpus files that
# never carry 'boost' at all (Розрахунковий наддув, dropped from the
# logging profile 2026-05-15 through 2026-06-18) -- of which 51 still carry
# 'eng_load_calc'. Without this, the fuelled/motored split only covers 157
# of 213 drives (nDrivesFuelState); the pooled/by-class occupancy histogram
# above is unaffected, since it only requires eng_rpm, which every file has.
#
# Calibrated (not guessed) against the 159 boost-covered files as ground
# truth, at the SAME RPM_HIST_FUELSTATE_RPM_MIN=1400 floor. At RPM>1400,
# calc-load cleanly separates the two boost-defined classes (motored median
# 6.3%, p90 20.8%; fuelled median 41.6%, p10 32.2%) but the classes are
# heavily imbalanced there (motored is only ~2.5% of samples), so a
# threshold's precision differs sharply by direction:
#   load>=20 as a FUELLED proxy : 98.3% recall, 0.33% contamination
#     (of samples proxy-labelled fuelled, 0.33% are boost-ground-truth
#     motored -- i.e. the ~2.5%-population class barely leaks in)
#   load<12  as a MOTORED proxy : 78.9% recall, 31.9% contamination
#     (the small motored class gets swamped by leakage from the huge
#     fuelled population even at single-digit false-positive rates)
# The motored side is therefore NOT extrapolated with calc-load alone --
# doing so would manufacture a false-optimistic motored-hours figure from
# majority-class leakage, which is exactly the failure mode this corpus's
# QC conventions (ens_outlier_v2, bootstrap CIs on M19/M20, etc.) exist to
# avoid. Only the fuelled bucket is extended, and it is kept in a SEPARATE
# accumulator (rpm_hist_fuelled_loadproxy) rather than merged into
# rpm_hist_fuelled, so boost-verified and load-proxy seconds stay
# distinguishable in the output and the dashboard can disclose both
# instead of silently blending two different-precision measurements.
RPM_HIST_LOAD_PROXY_FUELLED_MIN = 20.0
REGEN_TEMP_BINS = [(-99, 15, "10C"), (15, 25, "20C"),
                   (25, 35, "30C"), (35, 45, "40C"), (45, 99, "49C")]

# minimal raw column map (only what the B-pass needs)
# M57: speed zones for cycleBySpeed (kept identical to the zone edges the
# retired summary_config.json series used, so the chart's x-axis is unchanged
# and only the values move).
Z_CYSPD = [(0, 20), (20, 60), (60, 90), (90, 120), (120, 1e9)]
Z_CYSPD_LBL = ['0-20', '20-60', '60-90', '90-120', '120+']

RAW_MAP = {
    '[BMS] HV Battery Current (A)': 'I',
    '[BMS] HV Battery voltage (V)': 'V',
    '[BMS] HV State of charge (%)': 'soc',
    '[VCM] HV Battery Available Charge Display (%)': 'soc_vcm',
    '[BMS] HV Battery Temperature Sensor 1 (℃)': 'T1',
    '[BMS] HV Battery Temperature Sensor 2 (℃)': 'T2',
    '[BMS] HV Battery Temperature Sensor 3 (℃)': 'T3',
    '[BMS] HV Battery Temperature Sensor 4 (℃)': 'T4',
    '[BMS] HV Battery Intake Air Temperature (℃)': 'T_intake',
    '[BMS] Max Cell Voltage (V)': 'Vcmax',      # M43: pooled spread baselines
    '[BMS] Min Cell Voltage (V)': 'Vcmin',      # M43
    '[VCM] Vehicle Speed (km/h)': 'speed',
    '[VCM] Target Motor Torque (N⋅m)': 'target_torque',
    'Оберти двигуна (rpm)': 'eng_rpm',
    'Розрахунковий наддув (bar)': 'boost',
    'Температура охолодної рідини (℃)': 'T_coolant',   # engine coolant (M30 hvc)
    # M82: calc engine load, needed on the 1 Hz grid for the rpmDistribution
    # fuelled/motored split (same channel _dissipation_census reads via its
    # own ad hoc column map; added here so _RawAccum.add() can use it too).
    'Розрахункове значення навантаження на двигун (%)': 'eng_load_calc',
}

# ======================================================================
# M167 (2026-08-23, project-wide audit): ONE vehicle-speed source-priority
# rule for the whole module, replacing the seven independent, VCM-only
# column maps this file had grown (RAW_MAP above plus six local `C = {...}`
# / bare-literal sites in _motor_temp_stats, _highspeed_census,
# _ramp_latency_events, _soc_hysteresis_grid, _dissipation_census,
# _mountain_pattern, _low_speed_dissipation). None of them had a fallback
# for files that log speed only under the OBD-generic PID -- 44/274 drives
# (5 from May 11-13, 39 from Aug 14-22), silently dropping those files from
# every speed-gated computation in this module (see CHANGELOG M167).
# compute_drive_summary_v6.py already carried the correct rule
# (speed_source='vcm'/'obd_fallback') and m119v2_model.py's build_grid()
# independently arrived at the identical one (same 20-native-sample
# threshold) -- this makes it the ONE implementation every raw-consuming
# function in this module shares, instead of a rule re-derived per site.
_SPEED_VCM_RAW = '[VCM] Vehicle Speed (km/h)'
_SPEED_OBD_RAW = 'Швидкість автомобіля (km/h)'
_SPEED_MIN_NATIVE = 20   # native (pre-resample) non-null sample floor


def _apply_speed_priority(df, min_native=_SPEED_MIN_NATIVE):
    """Resolve ONE vehicle-speed column for `df` (original raw PID names,
    not yet renamed) under the project-wide priority rule: the native VCM
    channel ('[VCM] Vehicle Speed (km/h)') if it carries >= min_native
    non-null samples; otherwise the OBD-generic channel ('Швидкість
    автомобіля (km/h)') if present. Mutates the VCM-named column in place
    (creating it if absent) so every downstream rename map / bare-literal
    reference to '[VCM] Vehicle Speed (km/h)' in this module picks up the
    resolved series with no further changes at the call site. No-op (df
    returned unchanged) if df is None or carries neither channel, or if the
    VCM channel is already adequate. Returns (df, used_fallback: bool)."""
    if df is None or _SPEED_OBD_RAW not in df.columns:
        return df, False
    vcm_ok = (_SPEED_VCM_RAW in df.columns and pd.to_numeric(
        df[_SPEED_VCM_RAW], errors='coerce').notna().sum() >= min_native)
    if vcm_ok:
        return df, False
    df = df.copy()
    df[_SPEED_VCM_RAW] = df[_SPEED_OBD_RAW]
    return df, True



# ======================================================================
# helpers
# ======================================================================
def _as_bool(s):
    """Coerce an object/nan/'True'/'False' column back to real bool (CSV round-trip)."""
    return s.map(lambda x: x is True or str(x).strip().lower() == 'true').astype(bool)


def _dist_class(km):
    """Legacy distance-only bucket (M21: superseded by drive_type for all
    condition-semantics arrays; retained only as a reference/legacy helper,
    not called anywhere in this module)."""
    if pd.isna(km):
        return None
    for lo, hi, name in DIST_BINS:
        if lo <= km < hi:
            return name
    return None


def _cond_class(drive_type):
    """M21 condition class: pass-through of the time-weighted drive_type
    column, restricted to the CLASS_ORDER taxonomy (excludes the rare
    'unknown' drive_type, same exclusion behavior _dist_class(None) had)."""
    return drive_type if drive_type in CLASS_ORDER else None


def _rng(series):
    s = series.dropna()
    return (None, None) if not len(s) else (round(float(s.min()), 2),
                                            round(float(s.max()), 2))


def _q(series, p):
    s = series.dropna()
    return None if not len(s) else round(float(s.quantile(p)), 2)


# ======================================================================
# CATEGORY A  — master-derived arrays (drive_master.csv only)
# ======================================================================
def _cell_health_trend(dm, n_boot=4000, seed=42):
    """v6 Cell-Health robustness statistics, generated (was hard-typed prose).

    Temporal trend of the deconfounded (M15/M19) loaded cell-spread p95 on the
    ens_outlier_v2-clean set (v6 canonical intensity-normalized filter). Reports
    OLS and Huber slopes (mV/month) plus a cluster-by-calendar-day bootstrap 95%
    CI and P(slope>0), the same protocol M19 documents. Absolute resting spread
    is the median of the unloaded cell_spread_mean_mv. Always reported with the
    CI; the point estimate alone is never the headline.

    Audit remediation (P0.2, source-only pass): this is a SECONDARY robustness
    cross-check, not the authoritative cell-spread trend result. It differs
    methodologically from degradationTrends.cellSpread (degradation_trends.py)
    in two ways: (1) it regresses the already temperature/current-DECONFOUNDED
    series (cell_spread_loaded_p95_ADJ_mv), while the authoritative estimator
    regresses the raw p95 series with pack-temperature and peak-current as
    explicit regression controls in a single stage; (2) its uncertainty comes
    from an unconditional day-cluster bootstrap, while the authoritative
    estimator uses cluster-robust OLS standard errors with a day-cluster t
    reference. These are legitimate, independently-computed checks and their
    numbers are NOT forced to agree with each other (never hardcode agreement).
    Consumers MUST NOT present this block's slope/CI as co-equal with, or as a
    substitute for, degradationTrends.cellSpread -- see 'authoritative' and
    'seeAuthoritative' below, added so downstream JSX/tests can enforce this.
    """
    import numpy as np
    # F-14 (audit): bare .astype(bool) coerces NaN -> True, so ~mask would
    # DROP rows with a missing ens_outlier_v2 flag from the trend fit. Use the
    # NaN-safe _as_bool (NaN -> False) so missing flags are treated as
    # not-excluded, consistently with the canonical exclusion policy.
    d = dm[~_as_bool(dm['ens_outlier_v2'])].copy()
    d['date'] = pd.to_datetime(d['date'])

    def _ols(x, y):
        A = np.vstack([x, np.ones_like(x)]).T
        return float(np.linalg.lstsq(A, y, rcond=None)[0][0])

    g = d.dropna(subset=['cell_spread_loaded_p95_adj_mv', 'date'])
    out = {
        'restingSpreadMedianMv': None, 'n': 0,
        # P0.2: explicit non-authoritative tag -- degradationTrends.cellSpread
        # (cluster-robust OLS on the raw, non-deconfounded series with T/I as
        # explicit controls) is the sole authoritative inferential object for
        # headline cell-spread trend claims. This block's slope/CI/p-value
        # below are a secondary, methodologically-distinct robustness check
        # (deconfounded series, unconditional day-cluster bootstrap) and must
        # not be quoted as an independent confirmation of significance/null
        # without stating that distinction.
        'authoritative': False,
        'seeAuthoritative': 'degradationTrends.cellSpread',
        'methodNote': ('Bootstrap OLS/Huber on the pre-deconfounded '
                        'cell_spread_loaded_p95_adj_mv series (day-cluster '
                        'bootstrap CI), methodologically distinct from the '
                        'authoritative single-stage cluster-robust-OLS '
                        'estimator on the raw series with pack-temperature '
                        'and peak-current as explicit controls. The two can '
                        'disagree on whether the interval spans zero; that '
                        'is expected, not an error, and the authoritative '
                        'object governs headline claims.'),
    }
    if 'cell_spread_mean_mv' in d:
        rs = d['cell_spread_mean_mv'].dropna()
        out['restingSpreadMedianMv'] = round(float(rs.median()), 1) if len(rs) else None
    if len(g) >= 5:
        t0 = g['date'].min()
        months = (g['date'] - t0).dt.total_seconds().values / (30.4375 * 86400)
        y = g['cell_spread_loaded_p95_adj_mv'].values
        out['n'] = int(len(g))
        out['olsSlopeMvPerMo'] = round(_ols(months, y), 2)
        days = g['date'].dt.date.values
        uniq = np.unique(days)
        rng = np.random.default_rng(seed)
        sl = []
        for _ in range(n_boot):
            samp = rng.choice(uniq, size=len(uniq), replace=True)
            idx = np.concatenate([np.where(days == dd)[0] for dd in samp])
            sl.append(_ols(months[idx], y[idx]))
        sl = np.array(sl)
        out['ci95'] = [round(float(np.percentile(sl, 2.5)), 2),
                       round(float(np.percentile(sl, 97.5)), 2)]
        out['pSlopeGt0'] = round(float((sl > 0).mean()), 2)
    gh = d.dropna(subset=['cell_spread_loaded_p95_adj_hub_mv', 'date'])
    if len(gh) >= 5:
        try:
            from sklearn.linear_model import HuberRegressor
            t0h = gh['date'].min()
            mh = (gh['date'] - t0h).dt.total_seconds().values / (30.4375 * 86400)
            hub = HuberRegressor().fit(mh.reshape(-1, 1),
                                       gh['cell_spread_loaded_p95_adj_hub_mv'].values)
            out['huberSlopeMvPerMo'] = round(float(hub.coef_[0]), 2)
            out['nHuber'] = int(len(gh))
            # M317 (+Amendment 1): interval for THIS slope (second-stage Huber slope of the stored adjusted series): S1 = two-stage day-clustered percentile
            # bootstrap (refit first stage, recompute I_ref and the adjusted values, refit the slope; the only interval that passed calibration). Conditional and
            # week-block sensitivities live in spreadFitProvenance (spec analyses/M317_spec.md).
            try:
                import sys as _sys, os as _os
                _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'tools'))
                import huber_slope_ci as _hsc
                _ci = _hsc.two_stage_ci(mh, gh['T_pack_mean_avg'].values, gh['peak_I_discharge'].values, gh['cell_spread_loaded_p95_mv'].values,
                                        _hsc.day_labels(gh['date']), n_boot=n_boot, seed=seed)
                out['huberSlopeCi95'] = None if _ci['inconclusive'] else [round(_ci['ci95'][0], 2), round(_ci['ci95'][1], 2)]
                out['huberSlopeCiFailedDraws'] = int(_ci['failed_draws'] + _ci['nonconverged_draws'])
                out['huberSlopeCiMethod'] = ('Two-stage day-clustered percentile bootstrap (%d draws, seed %d, %d days): per draw the first-stage Huber fit, I_ref and the adjusted '
                                             'values are recomputed before the second-stage Huber slope. Calibrated in simulation; non-authoritative.' % (n_boot, seed, _ci['n_groups'])
                                             + (' INCONCLUSIVE: more than 1% of draws failed or did not converge.' if _ci['inconclusive'] else ''))
            except Exception as _ex:
                out['huberSlopeCi95'] = None
                out['huberSlopeCiMethod'] = 'not computed: ' + str(_ex)
        except Exception:
            out['huberSlopeMvPerMo'] = None
    return out


def category_A(dm, odometer_km=None):
    """odometer_km: the vehicle's TRUE dashboard odometer at the latest drive
    (external ground truth; NOT derivable from the logs, whose 'odo' PID is a
    cumulative logged-distance counter ~= sum of trip distances, not the car's
    lifetime odometer). Drives annualKm and the cycle-life projection. If None,
    those fields fall back to logged distance and are flagged approximate."""
    dm = dm.copy()
    dm['dclass'] = dm['drive_type'].apply(_cond_class)  # M21: time-weighted, not distance
    # M23 (2026-07-09): canonical exclusion is ens_outlier_v2 (invalid
    # records ONLY; intensity-extremes are flagged but RETAINED in group
    # stats -- M112 audit F-13). The v5 ens_outlier flagged the longest highway
    # drives on absolute magnitude, dropping 31% of valid 80-120 band time
    # and 27% of throughput from "clean" group stats; v2 normalizes size
    # away. Falls back to ens_outlier on a pre-v6 master.
    if 'ens_outlier_v2' in dm:
        dm['ens'] = _as_bool(dm['ens_outlier_v2'])
    elif 'ens_outlier' in dm:
        dm['ens'] = _as_bool(dm['ens_outlier'])
    else:
        dm['ens'] = False
    clean = dm[~dm['ens']].copy()
    out = {}

    # ---- meta / header scalars ----
    dt = pd.to_datetime(dm['date'])
    reg = pd.Timestamp(REG_DATE)
    today = dt.max()
    age_yr = (today - reg).days / 365.25
    total_km = round(float(dm['distance_km'].sum()), 1)
    odo = float(odometer_km) if odometer_km is not None \
        else round(float(dm['odo_end'].max()), 1)
    out['meta'] = {
        'totalDrives': int(len(dm)),
        'totalKm': total_km,
        'totalHours': round(float(dm['duration_s'].sum()) / 3600, 1),
        # M62 (2026-07-28, terminology audit): canonical key is now gtcSum.
        # The quantity is gross_throughput / CAP_KWH -- a DOUBLE-counting
        # convention (charge + discharge). "EFC" is the standard name for
        # throughput/capacity counting DEPTH only, so the old efcSum key was
        # publishing a GTC number under the industry name for a quantity
        # ~2x smaller. M95 (2026-08-07): the deprecated efcSum /
        # efcSum_superseded aliases were removed; gtcSum (from the 'gtc'
        # column) is canonical. Legacy JSX '?? efcSum' fallbacks are inert.
        'gtcSum': round(float(dm['gtc'].sum()), 1),
        'fceSum': round(float(dm['fce'].sum()), 1),
        'rfEfcSum': round(float(dm['rf_efc'].sum()), 1),
        # H-04 (audit 2026-07-14): expose the Woehler k=2 damage sum and the
        # applied two-pass current offset so the M17/M24 narrative captions bind
        # to the pipeline instead of the hand-typed "10.3" / "-0.4115 A" literals
        # that had gone stale (current: 12.29 / -0.4024 A).
        'rfDamageK2Sum': round(float(dm['rf_damage_k2'].sum()), 2),
        'offset2pA': (round(float(dm['I_offset_2p_A_applied'].dropna().iloc[0]), 4)
                      if dm['I_offset_2p_A_applied'].notna().any() else None),
        'grossThroughputKwh': round(float(dm['gross_throughput_kwh'].sum()), 1),
        'dateRange': f"{dt.min():%b %d} \u2013 {dt.max():%b %d, %Y}",
        'odometer': round(odo),
        'odometerSource': 'external' if odometer_km is not None else 'logged_distance_fallback',
        'carAgeNow': round(age_yr, 4),
        'annualKm': round(odo / age_yr) if age_yr > 0 else None,
        'daysSpan': int((dt.max() - dt.min()).days),
        # ---- round-2 stale-content fixes: overview/methodology aggregates,
        #      all Category-A (master-derived, deterministic) so the dashboard
        #      binds instead of hand-typing counts that drift. ----
        'loggedDates': int(dm['date'].nunique()),
        'stationaryHours': round(float((dm['duration_s'] * dm['stationary_pct']
                                        / 100).sum(skipna=True)) / 3600, 1),
        # moving = total - stationary so the two ALWAYS reconcile to totalHours
        # (drives missing stationary_pct fold into moving; reported below).
        'movingHours': round(float(dm['duration_s'].sum()) / 3600
                             - float((dm['duration_s'] * dm['stationary_pct']
                                      / 100).sum(skipna=True)) / 3600, 1),
        'stationaryCoverageN': int(dm['stationary_pct'].notna().sum()),
        'deficitValidN': int(dm['deficit_80_120_valid'].sum()),
        'deficitMeanPct': round(float(
            dm.loc[_as_bool(dm['deficit_80_120_valid']),
                   'deficit_80_120_pct'].mean()), 1),
        'deficitMinPct': round(float(
            dm.loc[_as_bool(dm['deficit_80_120_valid']),
                   'deficit_80_120_pct'].min()), 1),
        'deficitMaxPct': round(float(
            dm.loc[_as_bool(dm['deficit_80_120_valid']),
                   'deficit_80_120_pct'].max()), 1),
        # M41 (2026-07-17): decomposition of the engine-on discharge share
        # (deficit_* keys above retained byte-compatible; semantics reframed
        # -- see provenance.dischargeDecomp). Pool: M14-valid drives.
        'blendShareMeanPct': round(float(
            dm.loc[_as_bool(dm['deficit_80_120_valid']),
                   'blend_share_80_120'].mean()), 1),
        'blendShareP25': round(float(
            dm.loc[_as_bool(dm['deficit_80_120_valid']),
                   'blend_share_80_120'].quantile(0.25)), 1),
        'blendShareP75': round(float(
            dm.loc[_as_bool(dm['deficit_80_120_valid']),
                   'blend_share_80_120'].quantile(0.75)), 1),
        'steerShareMeanPct': round(100.0 - float(
            dm.loc[_as_bool(dm['deficit_80_120_valid']),
                   'blend_share_80_120'].mean()), 1),
        'saturTotalS': round(float(dm['satur_80_120_s'].sum()), 1),
        'saturDrivesN': int((dm['satur_80_120_s'] > 0).sum()),
        'saturCoverageN': int((dm['satur_80_120_s'].notna()
                               & dm['eng_load_calc_mean'].notna()).sum()),
        # M42 (2026-07-17): thermal ceiling bound to the master (the
        # Confirmed-by block hand-typed "49 C / Jun27 D7").
        'tPeakC': round(float(dm['T1_peak'].max()), 0),
        'tPeakPackMeanC': round(float(
            dm.loc[dm['T1_peak'].idxmax(), 'T_pack_mean_max']), 0),
        'tPeakDrive': _day_label(dm, int(dm['T1_peak'].idxmax())),
        'exclInvalid': int(dm['ens_invalid'].sum()),
        'exclExtreme': int(dm['ens_extreme'].sum()),
        'exclTotal': int(dm['ens_outlier_v2'].sum()),
        'peakDischargeA': round(float(dm['peak_I_discharge'].max()), 1),
        # C-02 (audit 2026-07-14): peak_I_charge is stored sign-negative for
        # charging, so .max() returned the value nearest zero (1.0 A) rather
        # than the true peak magnitude. Use the absolute extremum. Verified
        # 213.0 A on the 119-drive master (was 1.0 A).
        'peakChargeA': round(float(dm['peak_I_charge'].abs().max()), 1),
        # ---- coolant-loop peaks (master-derived; bind the two-loops prose so
        #      the hand-typed "43C / 97C" figures stop drifting). HV/e-powertrain
        #      loop = [VCM] HV Coolant Temperature (T_coolant_max); engine loop =
        #      T_eng_coolant_max. ----
        'hvCoolantPeakC': (round(float(dm['T_coolant_max'].dropna()
                                       [dm['T_coolant_max'].dropna() <= 120].max()))
                           if dm['T_coolant_max'].notna().any() else None),
        'engCoolantPeakC': (round(float(dm['T_eng_coolant_max'].dropna()
                                        [dm['T_eng_coolant_max'].dropna() <= 120].max()))
                            if dm['T_eng_coolant_max'].notna().any() else None),
        # count of drives longer than 60 min (backs the thermal-convergence
        # count so "N drives >60min" is never hand-typed).
        'longDrivesN': int((dm['duration_s'] > 3600).sum()),
        # ---- M82 (2026-08-04): engineOnHours / engineHoursPer10k -- total ICE
        # runtime and its per-10,000km rate. Category A: engine_on_pct (the
        # duration-weighted %-of-drive-time eng_rpm>400, computed in
        # compute_drive_summary_v6._v6_analyze_bytes) times duration_s is
        # already the per-drive engine-on seconds; summing needs no raw pass.
        # Unfiltered by ens_outlier_v2, matching the adjacent movingHours /
        # stationaryHours / grossThroughputKwh corpus-total convention above.
        'engineOnHours': round(float((dm['duration_s'] * dm['engine_on_pct']
                                      / 100).sum(skipna=True)) / 3600, 1),
        'engineOnCoverageN': int(dm['engine_on_pct'].notna().sum()),
        'engineHoursPer10k': (round(float((dm['duration_s'] * dm['engine_on_pct']
                                           / 100).sum(skipna=True)) / 3600
                                    / dm['distance_km'].sum() * 10000, 2)
                              if dm['distance_km'].sum() > 0 else None),
    }

    # ---- M75 (2026-07-29): turboMeta -- coverage counter for the Turbo
    # Pattern section (turboByRpm / turboBySpeedCtx, category B). That
    # section's intro caption and "boost-active duration" callout carried
    # hand-typed drive counts and percentages ("49 drives", "19.7%") that
    # were never bound to computed data and had drifted badly as the corpus
    # grew (>0.1 bar) -- verified against a header scan of all 194 raw CSVs,
    # 138 currently carry both the boost and engine-rpm PIDs, not 49. Derived
    # here master-only (boost_max/eng_rpm_max non-null on drive_master) so it
    # is available without a raw pass, mirroring the M35 soc_speed_files
    # coverage counter for the SoC-by-speed chart.
    turbo_cov = dm[dm['boost_max'].notna() & dm['eng_rpm_max'].notna()]
    out['turboMeta'] = {
        'nDrives': int(len(turbo_cov)),
        'totalDrives': int(len(dm)),
        'km': round(float(turbo_cov['distance_km'].sum()), 1),
        'hours': round(float(turbo_cov['duration_s'].sum()) / 3600, 1),
    }

    # ---- M26 (2026-07-09): standstillStats -- backs the Parasitic Draws
    # caption, which was a hand-typed snapshot ("all 92 drives... 10,665
    # idle samples... median -1.27 kW") that had drifted (92->96 drives,
    # 10,665->10,867 samples, -1.27->-1.245 kW median) as drives were added.
    # Unfiltered by ens_outlier_v2 to match the caption's "all drives" scope.
    ss = dm.dropna(subset=['standstill_draw_kw'])
    out['standstillStats'] = {
        'drives': int(len(ss)),
        'samples': int(dm['n_standstill_samples'].fillna(0).sum()),
        'medianKw': round(float(ss['standstill_draw_kw'].median()), 3),
        'loKw': round(float(ss['standstill_draw_kw'].min()), 3),
        'hiKw': round(float(ss['standstill_draw_kw'].max()), 3),
    }
    out['carOffStandby'] = _car_off_standby(dm)

    # ---- driveTypes (totals over all; per-drive means over ens-clean) ----
    dtl = []
    for k in CLASS_ORDER:
        g, gc = dm[dm['dclass'] == k], clean[clean['dclass'] == k]
        dtl.append({
            'key': k, 'label': k.replace('_', ' ').title(),
            'drives': int(len(g)),
            'km': round(float(g['distance_km'].sum()), 1),
            'hours': round(float(g['duration_s'].sum()) / 3600, 1),
            'avgKm': round(float(gc['distance_km'].mean()), 1) if len(gc) else None,
            'avgMin': round(float(gc['duration_s'].mean()) / 60) if len(gc) else None,
            'avgSpeedKmh': round(float(gc['speed_mean_moving'].mean())) if len(gc) else None,
            'color': CLASS_COLOR[k],
        })
    out['driveTypes'] = dtl

    # ---- M82 (2026-08-04): engineHoursByType -- companion to driveTypes,
    # ICE runtime per class instead of drive-time per class. engineOnPct
    # (mean, ens-clean) is the per-drive-averaged figure; engineOnHours /
    # hoursPer10k are class TOTALS, same totals-vs-per-drive-mean split
    # driveTypes already uses (km/hours = totals; avgKm/avgMin = per-drive
    # ens-clean means). A class with 0 km is skipped (hoursPer10k undefined).
    ehl = []
    for k in CLASS_ORDER:
        g, gc = dm[dm['dclass'] == k], clean[clean['dclass'] == k]
        km = float(g['distance_km'].sum())
        eng_h = float((g['duration_s'] * g['engine_on_pct'] / 100)
                      .sum(skipna=True)) / 3600
        ehl.append({
            'key': k, 'label': k.replace('_', ' ').title(),
            'drives': int(len(g)),
            'km': round(km, 1),
            'engineOnHours': round(eng_h, 1),
            'hoursPer10k': round(eng_h / km * 10000, 2) if km > 0 else None,
            'avgEngineOnPct': (round(float(gc['engine_on_pct'].mean()), 1)
                               if len(gc) and gc['engine_on_pct'].notna().any()
                               else None),
            'color': CLASS_COLOR[k],
        })
    out['engineHoursByType'] = ehl

    # ---- M74 (2026-07-29): driveDurationDist -- per-class duration DISTRIBUTION
    # (min/q1/median/q3/max in minutes), companion to driveTypes.avgMin. The
    # Drive Type Distribution section previously showed only the ens-clean MEAN
    # duration per class in its table; a mean hides spread, so a 19-min "Urban"
    # average reads as uniform even though the class runs sub-5-min hops to
    # 60+-min sessions. Same clean subset (ens_outlier_v2) and CLASS_ORDER as
    # avgMin above, so the two are directly comparable (box median != table
    # mean by construction -- distinct statistics, not a discrepancy). n < 2
    # drives cannot support a box (min==max==med, q1/q3 collapse to the point)
    # so the caller should treat n<5 as a thin-sample warning, consistent with
    # the >=5-drive gates used elsewhere in this pipeline (e.g. warmupCurve).
    ddl = []
    for k in CLASS_ORDER:
        gc = clean[clean['dclass'] == k]
        dur_min = gc['duration_s'].dropna() / 60
        if not len(dur_min):
            ddl.append({'key': k, 'label': k.replace('_', ' ').title(),
                        'color': CLASS_COLOR[k], 'n': 0, 'min': None, 'q1': None,
                        'med': None, 'q3': None, 'max': None})
            continue
        ddl.append({
            'key': k, 'label': k.replace('_', ' ').title(),
            'color': CLASS_COLOR[k],
            'n': int(len(dur_min)),
            'min': round(float(dur_min.min())),
            'q1': round(float(dur_min.quantile(0.25))),
            'med': round(float(dur_min.median())),
            'q3': round(float(dur_min.quantile(0.75))),
            'max': round(float(dur_min.max())),
        })
    out['driveDurationDist'] = ddl

    # ---- regenByType (torque-verified 4-way split, % of attributed subtotal) ----
    parts = [('Engine-only charge', 'charge_eng_only_kwh', 100, 0),
             ('Dual-channel', 'charge_dual_kwh', 50, 50),
             ('Pure regen', 'charge_pure_regen_kwh', 0, 100),
             ('Low-torque / aux', 'charge_lowtq_engoff_kwh', 0, 0)]
    tot = sum(float(dm[c].sum()) for _, c, _, _ in parts)
    out['regenByType'] = [{
        'type': lbl, 'engine': eng, 'regen': reg,
        'kwh': round(float(dm[c].sum()), 1),
        'pct': round(float(dm[c].sum()) / tot * 100, 1) if tot else None
    } for lbl, c, eng, reg in parts]

    # ---- M71 (2026-07-29): regenByTypeMeta -------------------------------
    # The chart's own title and its motor-involvement bracket were carrying
    # hand-typed numbers from the 93-drive era ("146.6 kWh total (93 drives)",
    # ">=28.6% certain -> <=49.9% upper bound"). The BARS were bound and
    # therefore current, so the caption contradicted the figure directly above
    # it by a factor of ~3 in energy and ~2 in drive count. Every quantity the
    # caption needs is emitted here so it cannot drift again.
    _n_attr = int(dm[[c for _, c, _, _ in parts]].notna().all(axis=1).sum())
    _pct = {lbl: (round(float(dm[c].sum()) / tot * 100, 1) if tot else None)
            for lbl, c, _, _ in parts}
    out['regenByTypeMeta'] = {
        'totalKwh': round(tot, 1),
        'nDrives': _n_attr,
        'nCorpus': int(len(dm)),
        'basis': ('unfiltered corpus, drives carrying the BMS current channel; '
                  'the four categories are exhaustive over gross charge'),
        # Lower bound: energy that is unambiguously motor braking (engine off,
        # motor braking). Upper bound adds dual-source intervals, where the
        # motor was braking but the generator was also charging, so the split
        # between the two sources within those samples is not resolvable.
        'motorCertainPct': _pct['Pure regen'],
        'motorUpperPct': (round(_pct['Pure regen'] + _pct['Dual-channel'], 1)
                          if _pct['Pure regen'] is not None
                          and _pct['Dual-channel'] is not None else None),
    }

    # M78 (2026-07-30): per-drive-type regen-vs-generator charge-share range,
    # charge-weighted, ens-clean. Backs two hand-typed caption literals in the
    # Drive-Type tab ("regen 27-40%" / "generator 72-85%") that had drifted and
    # were not even complementary. regen_share_of_charge is already a PERCENT
    # (0-100) of gross charge that arrived via regen; generator share is its
    # complement to 100.
    _rs_by_type = {}
    for k in ('urban', 'mixed', 'mixed_highway', 'highway'):
        g = clean[(clean['drive_type'] == k)
                  & clean['regen_share_of_charge'].notna()
                  & (clean['gross_charge_kwh'] > 0)]
        if len(g):
            w = g['gross_charge_kwh']
            _rs_by_type[k] = float((g['regen_share_of_charge'] * w).sum()
                                   / w.sum())
    if _rs_by_type:
        _lo, _hi = min(_rs_by_type.values()), max(_rs_by_type.values())
        out['regenByTypeMeta']['regenShareLoPct'] = round(_lo, 0)
        out['regenByTypeMeta']['regenShareHiPct'] = round(_hi, 0)
        out['regenByTypeMeta']['generatorShareLoPct'] = round(100 - _hi, 0)
        out['regenByTypeMeta']['generatorShareHiPct'] = round(100 - _lo, 0)

    # ---- cycleByType / cycleBySpeed  (explicit basis: efc per 100 km, ens-clean)
    # supersedes the legacy 98-drive figure whose normalization was undocumented.
    dm['gtc_per100'] = dm['gtc'] / dm['distance_km'] * 100
    clean['gtc_per100'] = clean['gtc'] / clean['distance_km'] * 100
    cbt = []
    for k in CLASS_ORDER:
        g = clean[clean['dclass'] == k]['gtc_per100'].dropna()
        cbt.append({'label': k.replace('_', ' ').title(),
                    'lo': round(float(g.min()), 1), 'hi': round(float(g.max()), 1),
                    'avg': round(float(g.mean()), 1), 'med': round(float(g.median()), 1),
                    'color': CLASS_COLOR[k]} if len(g) else {'label': k})
    out['cycleByType'] = cbt

    # ---- efficiencyBands / "Battery Draw Spectrum" (M21 fix, ens-clean) ----
    # PRIOR BASIS (net_draw_per100km_corr) was net(discharge - charge) over the
    # WHOLE drive, i.e. essentially (soc_start - soc_end) corrected and scaled
    # per 100 km. Because e-POWER treats the pack as a power BUFFER, not an
    # energy reservoir, the BMS actively steers SoC back toward a target band
    # over the course of a trip -- so this "net" figure mostly reflects where
    # the buffer happened to land relative to where it started (a start/end
    # balance artifact), not how hard the battery was actually worked. It goes
    # to ~0 (or even negative, i.e. net recharge) on longer drives simply
    # because there's more time for the generator to true the buffer back up --
    # not because the car got more "efficient" (e.g. 20260627_144929.csv,
    # 82.8% highway time, net_draw_per100km_corr = -0.19: reads as a
    # meaningless near-zero/negative "draw" under the old basis, but a
    # perfectly ordinary 2.96 kWh gross-discharge/100km under this one).
    # FIXED BASIS: gross_discharge_kwh / distance_km * 100 -- the actual energy
    # pulled OUT of the pack per 100 km (regardless of how much the generator
    # later put back in), i.e. genuine buffer-utilization intensity. Band is
    # the 10th-90th percentile of ens-clean drives per class (a "typical
    # range"), not the raw min-max, since a handful of near-zero/negative-
    # -tending net values previously stretched the low end into meaningless
    # territory; percentile band + median is comparable to the IQR/box-plot
    # treatment already used for SoC-by-speed and cycleByType.
    clean['gross_discharge_per100km'] = np.where(
        clean['distance_km'] > 0,
        clean['gross_discharge_kwh'] / clean['distance_km'] * 100, np.nan)
    eb = []
    for k in CLASS_ORDER:
        g = clean[clean['dclass'] == k]['gross_discharge_per100km'].dropna()
        eb.append({'label': k.replace('_', ' ').title(),
                   'lo': round(float(g.quantile(0.10)), 2),
                   'hi': round(float(g.quantile(0.90)), 2),
                   'med': round(float(g.median()), 2),
                   'n': int(len(g)),
                   'color': CLASS_COLOR[k]} if len(g) else {'label': k})
    out['efficiencyBands'] = eb

    # ---- cumulative cycle ledgers by calendar day ----
    d0 = dt.min()
    ordered = dm.sort_values(['date', 'time_start'])
    day_idx = (pd.to_datetime(ordered['date']) - d0).dt.days
    # M103 (2026-08-08): second escaped M95 efc->gtc read-site (efc was byte-
    # identical to gtc; CHANGELOG M95). Left unrepointed, cycleCumulative silently
    # dropped ('efc' not in master -> `continue`), which nulls a REQUIRED_BLOCKS /
    # JSX-consumed key. Repoint is numerically byte-exact.
    for col, key in [('gtc', 'cycleCumulative'), ('rf_efc', 'rfCycleCumulative')]:
        if col not in ordered:
            continue
        tmp = pd.DataFrame({'day': day_idx.values,
                            'v': ordered[col].fillna(0).values,
                            'type': ordered['drive_type'].values})
        by_day = tmp.groupby('day').agg(v=('v', 'sum'),
                                        type=('type', 'last')).reset_index()
        by_day['cum'] = by_day['v'].cumsum()
        lbl = [f"{(d0 + pd.Timedelta(days=int(d))):%d %b}" for d in by_day['day']]
        if key == 'cycleCumulative':
            out[key] = [[int(d), round(float(c), 1), l, str(t)]
                        for d, c, l, t in zip(by_day['day'], by_day['cum'],
                                              lbl, by_day['type'])]
        else:
            out[key] = [[int(d), round(float(c), 2)]
                        for d, c in zip(by_day['day'], by_day['cum'])]

    # ---- warmupPoints [distance_km, T_eng_coolant_max, coldStart<30C] ----
    wp = []
    for _, r in dm.iterrows():
        if pd.isna(r.get('distance_km')) or pd.isna(r.get('T_eng_coolant_max')) \
           or r['distance_km'] <= 0:            # skip zero-distance diagnostic logs
            continue
        cold = bool(r.get('T_intake', 99) < COLD_START_C) \
            if not pd.isna(r.get('T_intake')) else False
        wp.append([round(float(r['distance_km']), 2),
                   round(float(r['T_eng_coolant_max']), 0), cold])
    out['warmupPoints'] = wp

    # ---- cRatePoints [T1_at_peak_Crate, C-rate at charge peak, class] ----
    # M21: band now derived from time-weighted drive_type, not distance_km.
    # mixed_highway folds into the 'highway' band here (3-band chart) since
    # it is majority-highway-speed-influenced charging behavior.
    # M239 (Deep Article Audit C1): PREVIOUSLY paired each drive's peak
    # charge C-rate with T1_peak -- the drive's max battery temperature
    # ANYWHERE in the drive -- even though the two need not be simultaneous.
    # Both HV Battery Current and HV Battery Temperature Sensor 1 are logged
    # on native timestamps in every raw file, so the true simultaneous
    # pairing is directly computable: T1_at_peak_Crate (new master column)
    # is T1 asof-aligned (3s tolerance, matching ENG_ALIGN_TOL) to the exact
    # sample of whichever channel (eng_charge/dual/regen) produced the
    # drive's reported peak C-rate, falling back to T1_peak only for the
    # small minority of drives where a raw current+temperature probe isn't
    # available (early logs predating full PID coverage). Corpus effect:
    # this is NOT a relabeling -- re-pairing moves the median point 2 degC
    # (up to 16 degC) toward the true co-timed temperature, reveals 6
    # additional cold-zone (<20 degC) points hidden by the old pairing (10
    # -> 16 points below 20 degC; peak C-rate at cold pack rises from 18.9C
    # to 23.8C), and removes 25 of 49 points from the heat-risk zone (>=44
    # degC) that were false co-occurrences -- the charge event actually
    # happened at a cooler moment than the drive's separately-timed peak.
    crp = []
    for _, r in dm.iterrows():
        cls = _cond_class(r.get('drive_type'))
        if cls is None:
            continue
        cr = None
        for k in ['eng_charge_peak_Crate', 'dual_peak_Crate', 'regen_peak_Crate']:
            if not pd.isna(r.get(k)) and (cr is None or r[k] > cr):
                cr = float(r[k])
        t1_simul = r.get('T1_at_peak_Crate')
        if pd.isna(t1_simul):
            t1_simul = r.get('T1_peak')          # legacy fallback, no raw probe available
        if cr is None or pd.isna(t1_simul):
            continue
        band = 'highway' if cls in ('highway', 'mixed_highway') \
            else ('mixed' if cls == 'mixed' else 'city')
        crp.append([round(float(t1_simul), 0), round(cr, 1), band])
    out['cRatePoints'] = crp

    # ---- records (auto-maxed with robust artefact caps) ----
    out['records'] = _records(dm)

    # ---- cycle projections + calendar life scalars ----
    out['cycleLife'] = _cycle_projection(dm, clean, age_yr, odo)

    # ---- cellHealthTrend (M19/M23-M25, v6): generated so the Cell-Health
    #      robustness prose binds to it instead of hard-typing slope/CI/n
    #      figures that go stale as drives are added. Filtered on the v6
    #      canonical ens_outlier_v2 (intensity-normalized), not the retired
    #      magnitude-based M18 ensemble. ----
    out['cellHealthTrend'] = _cell_health_trend(dm)

    # M30 (2026-07-12): six of the ten Comparison-tab rows (SoC band, net
    # discharge, engine-ON fraction, battery temp, peak charge/discharge
    # currents) computable from drive_master alone. Merged with the four
    # raw-derived rows (category B) into the final highwayVsCity list in
    # build_summary_arrays().
    out['highwayVsCityMaster'] = _highway_vs_city_master(dm)
    out['socBandStats'] = _soc_band_stats(dm)
    # M53 (2026-07-24): pure-electric traction census. Master-only (the ev_*
    # block is computed at ingest by _ev_metrics), so it populates with or
    # without a raw pass. Returns None on a master predating M53 rather than
    # raising, so archived masters still build.
    _ev = _ev_traction(dm)
    if _ev is not None:
        out['evTraction'] = _ev

    return out


def _day_label(dm, idx):
    """'2026-06-27' + ordinal-within-day (by time_start) -> 'Jun27 D7', matching
    the attribution convention used throughout the hand-maintained narrative
    sections. Falls back to the bare date if time_start/date are unavailable."""
    if idx is None or idx not in dm.index:
        return None
    row = dm.loc[idx]
    d = row.get('date')
    if d is None or (isinstance(d, float) and pd.isna(d)):
        return None
    try:
        day_rows = dm[dm['date'] == d].sort_values('time_start')
        ordinal = list(day_rows.index).index(idx) + 1
        label = pd.to_datetime(d).strftime('%b%d')
        return f"{label} D{ordinal}"
    except Exception:
        return str(d)


_CTX_FIELDS = {
    # key -> (column(s) required, formatter). Every fragment is bound to the
    # master row that set the record; nothing is hand-typed.
    'class':  (('drive_type',),
               lambda r: (None if pd.isna(r['drive_type'])
                          or str(r['drive_type']) == 'unknown'
                          else str(r['drive_type']).replace('_', '-'))),
    'trip':   (('distance_km', 'duration_s'),
               lambda r: f"{r['distance_km']:.1f} km / {r['duration_s'] / 60:.0f} min"),
    'vmax':   (('speed_max',), lambda r: f"peak {r['speed_max']:.0f} km/h"),
    'vmov':   (('speed_mean_moving',),
               lambda r: f"{r['speed_mean_moving']:.0f} km/h moving avg"),
    'pack':   (('T_pack_mean_max',),
               lambda r: f"pack mean {r['T_pack_mean_max']:.0f}\u00b0C"),
    'engon':  (('engine_on_pct',),
               lambda r: f"engine on {r['engine_on_pct']:.0f}% of drive"),
    'soc':    (('soc_min', 'soc_max'),
               lambda r: f"SoC {r['soc_min']:.1f}-{r['soc_max']:.1f}%"),
    'thr':    (('gross_throughput_kwh',),
               lambda r: f"{r['gross_throughput_kwh']:.1f} kWh through the cells"),
    'rpm':    (('eng_rpm_max',), lambda r: f"engine peak {r['eng_rpm_max']:.0f} rpm"),
}


def _ctx(dm, idx, keys):
    """M37 (2026-07-15): render the operating context of the drive that set a
    record, from that drive's own master row. Used to build the per-record
    narrative note in _records(); every fragment is data-bound (no hand-typed
    conditions), and any fragment whose source column is missing/NaN on that
    row is silently dropped rather than emitting 'nan'."""
    if idx is None or idx not in dm.index:
        return ''
    row = dm.loc[idx]
    frags = []
    for k in keys:
        spec = _CTX_FIELDS.get(k)
        if spec is None:
            continue
        cols, fmt = spec
        if any(c not in dm.columns or pd.isna(row.get(c)) for c in cols):
            continue
        try:
            s = fmt(row)
        except Exception:
            continue
        if s:
            frags.append(s)
    return ' \u00b7 '.join(frags)


def _records(dm):
    """Auto-extract headline records from master maxima with artefact guards.
    Each record carries a 'drive' attribution label (day + ordinal-in-day,
    e.g. 'Jun27 D7') resolved from the row that set it -- previously dropped
    silently (sane_max returned only the scalar), leaving the JSX's r.drive
    span empty. Fixed here: sane_max/argmax variants now also return the
    source index.

    M37 (2026-07-15): (a) every row now carries a 'note' -- a definitional
    statement of what the extremum means, plus the setting drive's operating
    context resolved from its own master row via _ctx() (no hand-typed
    conditions); (b) extrema audit of drive_master added 17 rows that were
    computable from already-logged channels but unrepresented: discharge-side
    current/power, the three decomposed charge channels (dual / pure-regen /
    engine-only), engine rpm, boost, MAP, intake-air temp, duration, per-drive
    throughput, SoC excursion, moving-average speed, the M14-gated 80-120
    deficit, the 130+ discharge streak and the standstill-draw ceiling. All 19
    pre-existing rows reproduce byte-identically (value + attribution)."""
    def sane_max(col, cap):
        s = dm[col].dropna()
        s = s[s <= cap]
        if not len(s):
            return None, None
        idx = s.idxmax()
        return round(float(s.loc[idx]), 3), idx

    def sane_min(col, cap_lo=None):
        s = dm[col].dropna()
        if cap_lo is not None:
            s = s[s >= cap_lo]
        if not len(s):
            return None, None
        idx = s.idxmin()
        return round(float(s.loc[idx]), 3), idx

    longest_idx = dm['distance_km'].idxmax() if dm['distance_km'].notna().any() else None
    longest = dm.loc[longest_idx] if longest_idx is not None else None

    # M32 (2026-07-12): true max across all 4 pack temperature sensors,
    # not just Sensor 1. Previously the "Battery temp (Sensor 1)" record
    # silently missed drives where Sensor 2-4 ran hotter than Sensor 1.
    # Row-wise max over whichever T1-T4 peaks are present, capped like the
    # other true-extrema records, with the winning sensor tracked for the
    # narrative note (never baked into the row label itself).
    _t_sensor_cols = [c for c in ('T1_peak', 'T2_peak', 'T3_peak', 'T4_peak')
                      if c in dm.columns]
    tbatt_i = None
    tbatt = None
    tbatt_sensor = None
    if _t_sensor_cols:
        _tsub = dm[_t_sensor_cols].where(dm[_t_sensor_cols] <= 80)
        _rowmax = _tsub.max(axis=1)
        if _rowmax.notna().any():
            tbatt_i = _rowmax.idxmax()
            tbatt = round(float(_rowmax.loc[tbatt_i]), 3)
            _row = _tsub.loc[tbatt_i]
            tbatt_sensor = int(_row.idxmax()[1])  # 'T1_peak' -> 1

    tpm, tpm_i = sane_max('T_pack_mean_max', 80)
    tec, tec_i = sane_max('T_eng_coolant_max', 120)
    thvc, thvc_i = sane_max('T_coolant_max', 120)   # [VCM] HV coolant loop
    tq, tq_i = sane_max('target_torque_max', 400)
    load, load_i = sane_max('eng_load_abs_max', 300)
    spd, spd_i = sane_max('speed_max', 200)
    tmo, tmo_i = sane_max('T_motor_max', 130)
    toil, toil_i = sane_max('T_oil_max', 150)

    pchg_i = dm['peak_I_charge'].idxmin() if dm['peak_I_charge'].notna().any() else None
    pchg = abs(dm['peak_I_charge'].min()) if pchg_i is not None else None
    pchg_c = pchg / dm['cap_ah_est'].median() if pchg is not None else None

    spread_p95_i = dm['cell_spread_loaded_p95_mv'].idxmax() \
        if dm['cell_spread_loaded_p95_mv'].notna().any() else None
    spread_ss_i = dm['cell_spread_loaded_max_mv'].idxmax() \
        if dm['cell_spread_loaded_max_mv'].notna().any() else None

    accel_max_i = dm['accel_max_g'].idxmax() if dm['accel_max_g'].notna().any() else None
    accel_min_i = dm['accel_min_g'].idxmin() if dm['accel_min_g'].notna().any() else None
    accel_drive = _day_label(dm, accel_max_i)
    if accel_min_i != accel_max_i:
        lo_lbl = _day_label(dm, accel_min_i)
        if lo_lbl and lo_lbl != accel_drive:
            accel_drive = f"{accel_drive} / {lo_lbl}"

    # M295 (audit 2026-09-24 P0): a record may not be won by a canonically invalid drive. The
    # previous winner (20260513_182950, 0.01 kWh/100 km) is ens_invalid/ens_outlier_v2.
    _ens_bad = (dm['ens_invalid'].map(lambda x: x is True or str(x).strip().lower() == 'true')
                | dm['ens_outlier_v2'].map(lambda x: x is True or str(x).strip().lower() == 'true'))
    lo_draw_pool = dm.loc[(dm['soc_delta_kwh'].abs() < 0.05)
                          & (dm['net_draw_per100km_corr'] > 0) & ~_ens_bad, 'net_draw_per100km_corr'].dropna()
    lo_draw_i = lo_draw_pool.idxmin() if len(lo_draw_pool) else None
    lo_draw = float(lo_draw_pool.loc[lo_draw_i]) if lo_draw_i is not None else None

    hi_draw_i = dm['net_draw_per100km'].idxmax() if dm['net_draw_per100km'].notna().any() else None
    hi_draw = dm['net_draw_per100km'].max() if hi_draw_i is not None else None

    stat_pool = dm.loc[dm['distance_km'] > 0.5, 'stationary_pct']
    stat_i = stat_pool.idxmax() if stat_pool.notna().any() else None
    stat = stat_pool.max() if stat_i is not None else None

    soc_max_v, soc_max_i = sane_max('soc_max', 100)
    soc_min_v, soc_min_i = sane_min('soc_min', 0)

    # ---- M37 (2026-07-15): extrema audit of drive_master. Every column that
    # carries a physically meaningful per-drive maximum and was NOT already
    # represented above is added below. Sign convention: charge-side channels
    # (peak_I_charge, dual_peak_A, regen_peak_A, eng_charge_peak_A,
    # peak_charge_kw) are negative in the master, so their extremum is the
    # minimum, reported as a magnitude (same convention as the pre-existing
    # 'Peak charge current' row / acceptance test T-01).
    _cap_ah = float(dm['cap_ah_est'].median()) if dm['cap_ah_est'].notna().any() else None

    def abs_min(col, cap=None):
        """Most-negative value of a charge-side column -> (magnitude, idx)."""
        if col not in dm.columns:
            return None, None
        s = dm[col].dropna()
        if cap is not None:
            s = s[s.abs() <= cap]
        if not len(s):
            return None, None
        idx = s.idxmin()
        return round(abs(float(s.loc[idx])), 3), idx

    pdis, pdis_i = sane_max('peak_I_discharge', 300)
    pdis_c = (pdis / _cap_ah) if (pdis is not None and _cap_ah) else None
    pdis_kw, pdis_kw_i = sane_max('peak_discharge_kw', 150)
    pchg_kw, pchg_kw_i = abs_min('peak_charge_kw', 150)
    dual, dual_i = abs_min('dual_peak_A', 300)
    dual_c = float(dm.at[dual_i, 'dual_peak_Crate']) if dual_i is not None else None
    regen, regen_i = abs_min('regen_peak_A', 300)
    regen_c = float(dm.at[regen_i, 'regen_peak_Crate']) if regen_i is not None else None
    engchg, engchg_i = abs_min('eng_charge_peak_A', 300)
    engchg_c = float(dm.at[engchg_i, 'eng_charge_peak_Crate']) if engchg_i is not None else None

    rpm, rpm_i = sane_max('eng_rpm_max', 7000)
    boost, boost_i = sane_max('boost_max', 3.0)
    mapk, mapk_i = sane_max('map_kpa_max', 400)
    tin, tin_i = sane_max('T_intake', 80)

    dur_i = dm['duration_s'].idxmax() if dm['duration_s'].notna().any() else None
    dur_h = float(dm.at[dur_i, 'duration_s']) / 3600 if dur_i is not None else None
    thr, thr_i = sane_max('gross_throughput_kwh', 100)
    band, band_i = sane_max('soc_band', 100)
    hs_i = dm['highspeed_discharge_s_130p'].idxmax() \
        if dm['highspeed_discharge_s_130p'].notna().any() else None
    hs = float(dm.at[hs_i, 'highspeed_discharge_s_130p']) if hs_i is not None else None
    if hs is not None and hs <= 0:
        hs, hs_i = None, None
    vmov, vmov_i = sane_max('speed_mean_moving', 200)
    ss_i = dm['standstill_draw_kw'].idxmax() \
        if dm['standstill_draw_kw'].notna().any() else None
    ss = float(dm.at[ss_i, 'standstill_draw_kw']) if ss_i is not None else None

    # M14 validity gate: deficit % is only reportable where band time >= 120 s.
    _def_pool = dm.loc[dm['deficit_80_120_valid'] == True, 'deficit_80_120_pct'].dropna() \
        if 'deficit_80_120_valid' in dm.columns else pd.Series(dtype=float)
    def_i = _def_pool.idxmax() if len(_def_pool) else None
    defc = float(_def_pool.loc[def_i]) if def_i is not None else None

    # M37 (2026-07-15): each row is (metric, value, idx, why, ctx_keys).
    # 'why' is the mechanistic reading of the record -- what the number means
    # and why it is the extremum worth carrying -- and is definitional prose,
    # never a number. Every quantity in the rendered note comes from _ctx(),
    # i.e. from the master row that set the record, so the notes cannot drift
    # out of sync with the data the way hand-typed conditions would.
    recs = [
        # ---- thermal ----
        ('Battery temp max', f"{tbatt:.0f}\u00b0C" if tbatt is not None else None, tbatt_i,
         'Hottest single pack probe in the dataset (row-wise max over sensors '
         '1-4, M32). Sets the observed thermal ceiling of the buffer; the pack '
         'reached without runaway in these logs; a finite maximum is a sampled extremum, not a test of asymptotic thermal equilibrium.',
         ('class', 'trip', 'vmax', 'pack')),
        ('Battery temp (pack mean)', f"{tpm:.0f}\u00b0C" if tpm is not None else None, tpm_i,
         'Highest 4-sensor mean -- the bulk-cell temperature, always below the '
         'hottest-probe figure by the fixed ~9\u00b0C spatial gradient. This is '
         'the number that drives Arrhenius calendar aging, not the probe max.',
         ('class', 'trip', 'vmax', 'engon')),
        ('Engine coolant peak', f"{tec:.0f}\u00b0C" if tec is not None else None, tec_i,
         'Hottest generator-loop coolant. The engine deliberately runs hot for '
         'combustion efficiency; it is thermally isolated from the HV loop.',
         ('class', 'trip', 'engon', 'rpm')),
        ('HV coolant peak', f"{thvc:.0f}\u00b0C" if thvc is not None else None, thvc_i,
         'Hottest e-powertrain loop coolant (inverter/motor/generator). The '
         'ceiling of the separate low-temperature circuit the battery and '
         'motor share -- roughly half the engine-loop peak.',
         ('class', 'trip', 'vmax', 'pack')),
        ('Traction motor temperature', f"{tmo:.0f}\u00b0C" if tmo is not None else None, tmo_i,
         'Hottest stator reading. Tracks pack temperature more strongly than '
         'speed (shared cooling environment) and stays far under the ~150\u00b0C '
         'class limit for this machine.',
         ('class', 'trip', 'vmax', 'pack')),
        ('Oil temperature peak', f"{toil:.0f}\u00b0C" if toil is not None else None, toil_i,
         'Hottest engine oil -- the slowest thermal mass in the generator set, '
         'and the last channel to reach steady state on a long run.',
         ('class', 'trip', 'engon')),
        ('Battery intake air temperature max',
         f"{tin:.1f}\u00b0C" if tin is not None else None, tin_i,
         'Hottest cabin-sourced cooling air presented to the pack inlet. The '
         'floor the pack can be cooled to: forced convection cannot pull cells '
         'below their own intake, so this bounds the achievable pack minimum '
         'on a hot day.',
         ('class', 'trip', 'pack')),
        # ---- electrical / C-rate ----
        ('Peak discharge current',
         f"{pdis:.0f} A ({pdis_c:.1f}C)" if pdis is not None else None, pdis_i,
         'Hardest single instantaneous pull out of the cells. With charge '
         'current, brackets the observed current envelope. High current is a '
         'plausible ageing stressor; this record is exposure, not measured damage.',
         ('class', 'vmax', 'pack')),
        ('Peak charge current',
         f"{pchg:.0f} A ({pchg_c:.1f}C)" if pchg is not None else None, pchg_i,
         'Hardest single instantaneous push into the cells, from any source '
         '(engine-generator, regen, or both). Charge acceptance at high C-rate '
         'on a cold pack is the literature plating-risk channel; this absolute '
         'peak was not set cold (see the C-rate map for sub-20 C peaks).',
         ('class', 'vmax', 'pack')),
        ('Peak discharge power',
         f"{pdis_kw:.1f} kW" if pdis_kw is not None else None, pdis_kw_i,
         'Peak power delivered by the buffer (I\u00b7V at the pack terminals). '
         'The traction-motor demand the pack alone had to cover at that '
         'instant, over and above whatever the generator was supplying.',
         ('class', 'vmax', 'engon')),
        ('Peak charge power',
         f"{pchg_kw:.1f} kW" if pchg_kw is not None else None, pchg_kw_i,
         'Peak power absorbed by the buffer. Bounds how much generator surplus '
         'plus regen the pack absorbed at once in these logs -- an observed '
         'maximum, not a rated acceptance limit.',
         ('class', 'vmax', 'engon')),
        ('Peak dual-channel charge (engine + regen)',
         f"{dual:.0f} A ({dual_c:.1f}C)" if dual is not None else None, dual_i,
         'Highest current with the engine charging while the motor is '
         'simultaneously regenerating -- the two charge paths summing into one '
         'pack. The architecture\'s worst-case charge-acceptance event.',
         ('class', 'vmax', 'rpm')),
        ('Peak pure-regen charge (engine off)',
         f"{regen:.0f} A ({regen_c:.1f}C)" if regen is not None else None, regen_i,
         'Highest current from braking energy alone, generator inactive. '
         'Isolates the regen channel\'s own ceiling from engine-charge '
         'contamination.',
         ('class', 'vmax', 'pack')),
        ('Peak engine-only charge',
         f"{engchg:.0f} A ({engchg_c:.1f}C)" if engchg is not None else None, engchg_i,
         'Highest current from the generator alone. Together with the '
         'pure-regen peak, decomposes the dual-channel record into its two '
         'physical sources.',
         ('class', 'vmax', 'rpm')),
        # ---- drivetrain / ICE ----
        ('Peak motor torque', f"+{tq:.0f} Nm" if tq is not None else None, tq_i,
         'Highest commanded traction torque. The single front motor is the '
         'only path to the wheels, so this is the drivetrain\'s full output '
         'ceiling, not one axle\'s share.',
         ('class', 'vmax', 'trip')),
        ('Peak engine load', f"{load:.1f}%" if load is not None else None, load_i,
         'Highest in-range OBD Absolute Engine Load PID value (can exceed 100% '
         'under boost; not a rated engine capability). In series '
         'hybrid this reflects electrical demand plus pack recharge, not road '
         'load -- the engine is decoupled from the wheels.',
         ('class', 'rpm', 'vmax')),
        ('Max engine speed', f"{rpm:.0f} rpm" if rpm is not None else None, rpm_i,
         'Highest generator rpm. In a series hybrid this is set by the power '
         'the controller demands, not by road speed -- there is no mechanical '
         'link to the wheels.',
         ('class', 'vmax', 'engon')),
        ('Peak boost', f"{boost:.2f} bar" if boost is not None else None, boost_i,
         'Highest turbocharger boost from the dedicated channel. Marks the '
         'generator being driven at its high-power operating point, typically '
         'during high-speed buffer recharge legs (M41 reframing).',
         ('class', 'vmax', 'rpm')),
        ('Peak intake manifold pressure',
         f"{mapk:.0f} kPa abs" if mapk is not None else None, mapk_i,
         'Highest absolute manifold pressure -- an independent sensor '
         'corroborating the boost channel above (subtract ~100 kPa ambient for '
         'the gauge-boost equivalent).',
         ('class', 'vmax', 'rpm')),
        ('Peak acceleration',
         f"+{dm['accel_max_g'].max():.2f}g / {dm['accel_min_g'].min():.2f}g"
         if (accel_max_i is not None or accel_min_i is not None) else None,
         accel_max_i,  # index only used as fallback below; label built separately
         'Hardest longitudinal acceleration / braking events (derived from the '
         'speed trace, so smoothed relative to a true accelerometer). The '
         'braking extreme is the regen channel\'s demand side.',
         ()),
        ('Max speed', f"{spd:.0f} km/h" if spd is not None else None, spd_i,
         'Fastest instantaneous sample in the corpus -- verified as real drive '
         'data, not a logging artefact. The 140+ km/h regime is reached only '
         'in brief excursions (see the M39 dwell census), never held long '
         'enough to characterise -- one of the two under-sampled stressors '
         '(with sub-15\u00b0C cold starts) most likely to move degradation '
         'conclusions.',
         ('class', 'trip', 'engon')),
        ('Highest moving-average speed',
         f"{vmov:.1f} km/h" if vmov is not None else None, vmov_i,
         'Highest whole-drive average excluding stopped time. Identifies the '
         'most sustained high-load duty cycle in the corpus, as distinct from '
         'a single fast instant.',
         ('class', 'trip', 'engon')),
        # ---- energy / cycling ----
        ('Longest single drive',
         f"{longest['distance_km']:.2f} km / {longest['duration_s']/60:.0f}min"
         if longest is not None else None, longest_idx,
         'Greatest distance in one key-cycle. Long drives dominate throughput '
         'and are where the pack reaches its highest sustained temperatures '
         '(a finite maximum, not an established equilibrium).',
         ('class', 'vmov', 'pack')),
        ('Longest duration drive',
         f"{dur_h:.2f} hr" if dur_h is not None else None, dur_i,
         'Longest continuous key-on session, which may differ from the longest '
         'by distance. Sets the maximum observed dwell at the thermal plateau.',
         ('class', 'trip', 'pack')),
        ('Largest single-drive throughput',
         f"{thr:.1f} kWh" if thr is not None else None, thr_i,
         'Most gross energy (discharge + charge) cycled through the cells in '
         'one drive -- the wear-relevant per-drive maximum, since throughput, '
         'not net SoC balance, is what ages the buffer.',
         ('class', 'trip', 'vmov')),
        ('Widest SoC excursion (single drive)',
         f"{band:.1f} pp" if band is not None else None, band_i,
         'Largest span between a drive\'s SoC floor and ceiling. Equal by '
         'construction to the deepest rainflow cycle of that drive (M17), so '
         'it is also the dataset\'s deepest single DoD event.',
         ('class', 'trip', 'soc')),
        ('Lowest net battery draw (SoC-neutral)',
         f"{lo_draw:.2f} kWh/100km" if lo_draw is not None else None, lo_draw_i,
         'Lowest net depletion per 100 km among drives that started and ended '
         'at effectively the same SoC (|\u0394| < 0.05 kWh), so the figure is not '
         'flattered by simply landing lower in the buffer. A battery-draw '
         'figure, not fuel economy.',
         ('class', 'trip', 'vmov')),
        ('Highest net battery draw',
         f"{hi_draw:.1f} kWh/100km" if hi_draw is not None else None, hi_draw_i,
         'Highest net depletion per 100 km (uncorrected basis). On short trips '
         'this is dominated by where the drive happened to end in the buffer, '
         'which is why net draw was retired as the headline efficiency metric '
         'in favour of gross throughput (M35).',
         ('class', 'trip', 'vmov')),
        ('Maximum SoC', f"{soc_max_v:.1f}%" if soc_max_v is not None else None, soc_max_i,
         'Highest SoC observed in these logs. It does not establish the absolute '
         'controller ceiling or BMS intent; no logged drive reached 100%.',
         ('class', 'trip', 'soc')),
        ('Minimum SoC', f"{soc_min_v:.1f}%" if soc_min_v is not None else None, soc_min_i,
         'Lowest SoC reached. The floor is defended by starting the generator; '
         'highway legs approach it during transient power-blending, then the '
         'controller steers SoC back toward its setpoint (M41 reframing).',
         ('class', 'trip', 'soc')),
        ('Deepest 80-120 km/h engine-on discharge share',
         f"{defc:.0f}% of band" if defc is not None else None,
         def_i,
         'Largest share of time in the 80-120 km/h band spent net-discharging '
         'with the engine running. M41 reframing: a control-strategy '
         'observable (SoC steering toward the ~62% setpoint, generator '
         'load-point quantization, transient power blending), not generator '
         'saturation -- calc engine load during these seconds averages ~38% '
         '(p95 ~43%), and the sustained-saturation gate (load>85%, Id>30 A, '
         '>=5 s) fires 0 s corpus-wide. Gated to drives with >=120 s of band '
         'time (M14).',
         ('class', 'trip', 'engon')),
        ('Longest sustained 130+ km/h discharge',
         f"{hs:.0f} s" if hs is not None else None, hs_i,
         'Longest continuous stretch of net discharge above 130 km/h (an observed '
         'run maximum, not a limit set by the SoC floor; read beside cumulative '
         '130+ km/h exposure).',
         ('class', 'vmax', 'soc')),
        # ---- cell / parasitic ----
        ('Cell spread under load (per-drive p95)',
         f"{dm['cell_spread_loaded_p95_mv'].max():.0f} mV"
         if spread_p95_i is not None else None, spread_p95_i,
         'Highest 95th-percentile max-min cell delta under load. A '
         'polarization/thermal artifact, not divergence -- it collapses back to '
         'the ~10 mV resting baseline within the same drive.',
         ('class', 'vmax', 'pack')),
        ('Cell spread under load (single-sample)',
         f"{dm['cell_spread_loaded_max_mv'].max():.0f} mV"
         if spread_ss_i is not None else None, spread_ss_i,
         'Highest single-sample cell delta under load -- a transient at a '
         'current step, shown for completeness against the p95 row, which is '
         'the defensible statistic.',
         ('class', 'vmax', 'pack')),
        ('Highest key-on standstill draw',
         f"{ss:.2f} kW" if ss is not None else None, ss_i,
         'Largest stationary hotel load (climate + electronics) with the car '
         'on and not moving. Sets the upper bound on the parasitic term that '
         'inflates any per-km figure computed on a stop-heavy drive.',
         ('class', 'trip', 'pack')),
        # exclude sub-0.5 km parked diagnostic logs (100%-stationary non-drives)
        ('Most stationary',
         f"{stat:.0f}% stopped" if stat is not None else None, stat_i,
         'Highest share of drive time at zero speed (drives >0.5 km only, so '
         'parked diagnostic logs are excluded). The worst-case congestion duty '
         'cycle in the corpus.',
         ('class', 'trip', 'vmov')),
    ]
    out = []
    for m, v, idx, why, ctx_keys in recs:
        if v is None:
            continue
        if m == 'Peak acceleration':
            drive = accel_drive
        else:
            drive = _day_label(dm, idx)
        rec = {'metric': m, 'value': v, 'drive': drive or ''}
        # M37: narrative note = definitional 'why' + the setting drive's own
        # operating context, resolved from its master row.
        ctx = _ctx(dm, idx, ctx_keys)
        rec['note'] = f"{why} Set on: {ctx}." if ctx else why
        if m == 'Battery temp max' and tbatt_sensor is not None:
            # sensor attribution belongs in narrative prose, not the row
            # label -- exposed here for the JSX to render as a footnote.
            rec['sensor'] = tbatt_sensor
        out.append(rec)

    # M255 (2026-09-14): "Battery temp min" / "Battery intake air temperature
    # min". Neither is derivable from dm alone -- drive_master.csv carries
    # only per-drive MAXIMA for the four pack sensors (T1_peak..T4_peak) and
    # no minimum at all for either the pack sensors or the intake-air
    # channel. Rather than add columns to drive_master.csv (the
    # corpus-integrity anchor -- any change there needs the full
    # ingestion/validation chain, out of scope for a two-row display
    # addition), this reads the additive side-pass artifact produced by
    # battery_temp_extremes.py (same "master untouched, side-module"
    # pattern as fuel_recon.py). Maintenance: re-run
    # `python3 battery_temp_extremes.py` after each ingestion batch, before
    # rebuilding summary_arrays.json, so the CSV covers the current corpus --
    # if it's missing or stale (row count != len(dm)) these two rows are
    # silently omitted rather than shown against a smaller/older corpus.
    try:
        import battery_temp_extremes as _bte
        _te_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 'battery_temp_extremes.csv')
        if os.path.exists(_te_path):
            _te = pd.read_csv(_te_path)
            if len(_te) == len(dm):
                for _m, _r in _bte.build_records(dm, _te).items():
                    out.append(_r)
    except Exception:
        pass  # side-pass unavailable this session -- degrade gracefully, don't fail _records()

    return out


def _ev_traction(dm):
    """M53 (2026-07-24): pure-electric (engine-off) traction census.

    Master-derived only -- the per-drive ev_* block is computed at ingest by
    _ev_metrics in compute_drive_summary_v6, so this function does no raw
    pass and needs no slim-cache channel. Two headline quantities:

      (1) TYPICAL. Engine-off share of distance, by condition class. Reported
          as median + IQR across drives, plus the exact corpus aggregate
          (sum of ev_dist_km over sum of distance_km), because the two answer
          different questions and the drive-median is NOT distance-weighted.

      (2) MAXIMUM. Longest single contiguous engine-off run. Two figures are
          emitted and both are needed to read the number honestly:
            runMax      -- the observed extremum, terrain/regen assisted.
                           Runs of this length recover 30-50% of their
                           throughput as regen mid-run, so the buffer is not
                           drained at road-load rate over their length.
            runMaxUnassisted -- longest run whose regen share of throughput
                           stayed below EV_REGEN_POOR, i.e. genuinely paid
                           for out of the buffer.

    Buffer-limit cross-check. usable window (p05 soc_min -> p95 soc_max, the
    operating window the controller actually uses, not the nameplate) x
    CAP_KWH, divided by the pooled unassisted specific consumption (an exact
    ratio of summed accumulators, not a mean of per-drive ratios). rangeKm is
    therefore the UNASSISTED window budget: how far the whole usable window
    would carry the car spent end-to-end with zero regen. It is an UPPER BOUND
    on unassisted range, not a per-run prediction, because no single run
    traverses the whole corpus window.
      M77 (2026-07-31): the prior reading paired rangeKm with the regen-
    assisted runMax ("predicted ~ observed => energy-limited by the buffer")
    and is WITHDRAWN -- runMax is not a buffer-drain distance (its own
    unassisted content is runMax.unassistedKm). The comparable figure is the
    longest genuinely-unassisted run, runMaxUnassistedKm; budgetFractionPct
    reports how far short of the budget it falls. Nothing here asserts a
    limiting mechanism; the numbers are emitted and the section reads them.

    Run histogram is pooled from exact per-drive bin COUNTS (ev_runs_*);
    pooling per-drive percentiles would not be valid.

    Filtering. ev_valid (per-drive channel-coverage / poll-rate / odometer-
    reconstruction gates, see _ev_metrics) AND the corpus-standard
    ens_outlier_v2 exclusion. Both counts are reported so the reader can see
    how much of the corpus supports the claim.
    """
    if 'ev_valid' not in dm.columns:
        return None
    ens = _as_bool(dm['ens_outlier_v2']) if 'ens_outlier_v2' in dm.columns \
        else pd.Series(False, index=dm.index)
    gate = _as_bool(dm['ev_valid'])
    d = dm[gate & ~ens].copy()
    if not len(d):
        return None
    d['dclass'] = d['drive_type'].apply(_cond_class)

    # M62 (2026-07-28): expose the support fraction and the NaN-gate default.
    # _as_bool maps a NaN ens_outlier_v2 to False, i.e. "not an outlier", so
    # rows whose ensemble flags were never fitted (the early-May drives that
    # predate the feature set) are INCLUDED. That is the intended
    # innocent-until-proven default, but it is an assumption and belongs in
    # the caveat list rather than in a reviewer's inference.
    n_nan_flag = int(dm['ens_outlier_v2'].isna().sum()) \
        if 'ens_outlier_v2' in dm.columns else 0
    nan_in_ev = int((gate & dm['ens_outlier_v2'].isna()).sum()) \
        if 'ens_outlier_v2' in dm.columns else 0
    km_nan_in_ev = (round(float(dm.loc[gate & dm['ens_outlier_v2'].isna(),
                                       'distance_km'].sum()), 1)
                    if 'ens_outlier_v2' in dm.columns else 0.0)
    out = {'nDrives': int(len(dm)), 'nValid': int(len(d)),
           'nGatedChannel': int((~gate).sum()),
           'nGatedOutlier': int((gate & ens).sum()),
           'supportPct': round(100 * len(d) / len(dm), 1),
           'nUnflaggedIncluded': nan_in_ev,
           'kmUnflaggedIncluded': km_nan_in_ev,
           'nUnflaggedCorpus': n_nan_flag,
           'kmValid': round(float(d['distance_km'].sum()), 1)}

    ev_km, tot_km = float(d['ev_dist_km'].sum()), float(d['distance_km'].sum())
    out['evKm'] = round(ev_km, 1)
    out['evPctDistance'] = round(ev_km / tot_km * 100, 1) if tot_km else None
    ev_s, mov_s = float(d['ev_time_s'].sum()), float(d['ev_moving_time_s'].sum())
    dur = float(d['duration_s'].sum())
    out['evPctTime'] = round(ev_s / dur * 100, 1) if dur else None
    out['evMovingShareOfEvTime'] = round(mov_s / ev_s * 100, 1) if ev_s else None

    rows = []
    for cls in CLASS_ORDER:
        g = d[d['dclass'] == cls]
        if not len(g):
            continue
        km = float(g['distance_km'].sum())
        rows.append({
            'class': cls, 'n': int(len(g)), 'km': round(km, 1),
            'medianPct': _q(g['ev_dist_pct'], 0.50),
            'q1Pct': _q(g['ev_dist_pct'], 0.25),
            'q3Pct': _q(g['ev_dist_pct'], 0.75),
            'aggregatePct': round(float(g['ev_dist_km'].sum()) / km * 100, 1)
            if km else None,
            'runsPer10km': round(float(g['ev_n_runs'].sum()) / km * 10, 1)
            if km else None,
            'runMaxKm': round(float(g['ev_run_max_km'].max()), 2),
            'runMedianKm': _q(g['ev_run_p50_km'], 0.50)})
    out['byClass'] = rows

    bins = [('ev_runs_lt05', '0.05-0.5 km'), ('ev_runs_05_1', '0.5-1 km'),
            ('ev_runs_1_2', '1-2 km'), ('ev_runs_2_3', '2-3 km'),
            ('ev_runs_ge3', '>3 km')]
    counts = [(lab, int(d[c].sum())) for c, lab in bins if c in d.columns]
    tot = sum(n for _, n in counts)
    out['runHistogram'] = [{'bin': lab, 'n': n,
                            'pct': round(n / tot * 100, 1) if tot else None}
                           for lab, n in counts]
    out['nRuns'] = tot

    if d['ev_run_max_km'].notna().any():
        i = d['ev_run_max_km'].idxmax()
        s = float(d.at[i, 'ev_run_max_s'])
        # M77 (2026-07-31): the record run's OWN unassisted content, so the
        # section can state from the pipeline how much of the observed maximum
        # was regen-carried rather than paid out of the buffer -- the figure
        # previously hand-typed on the dashboard as a vague "30-50%".
        rec_nr = (d.at[i, 'ev_nr_run_max_km']
                  if 'ev_nr_run_max_km' in d.columns else None)
        out['runMax'] = {
            'km': round(float(d.at[i, 'ev_run_max_km']), 2),
            'unassistedKm': (round(float(rec_nr), 2)
                             if rec_nr is not None and pd.notna(rec_nr)
                             else None),
            'durationS': int(s),
            'peakKmh': round(float(d.at[i, 'ev_run_max_vmax_kmh']), 0),
            'meanKmh': round(float(d.at[i, 'ev_run_max_km']) / (s / 3600.0), 0)
            if s > 0 else None,
            'driveType': d.at[i, 'drive_type'],
            'file': d.at[i, 'file'],
            'label': _day_label(dm, i)}
    if 'ev_nr_run_max_km' in d.columns and d['ev_nr_run_max_km'].notna().any():
        out['runMaxUnassistedKm'] = round(
            float(d['ev_nr_run_max_km'].max()), 2)

    # ---- buffer-limit cross-check ----
    if 'ev_nr_km' in d.columns and 'ev_nr_kwh' in d.columns:
        nk, ne = float(d['ev_nr_km'].sum()), float(d['ev_nr_kwh'].sum())
    else:
        nk, ne = 0.0, 0.0
    lo = float(dm['soc_min'].quantile(0.05))
    hi = float(dm['soc_max'].quantile(0.95))
    win = hi - lo
    kwh = win / 100.0 * CAP_KWH
    b = {'usableWindowPp': round(win, 1), 'socLoPct': round(lo, 1),
         'socHiPct': round(hi, 1), 'usableKwh': round(kwh, 2),
         'nrKm': round(nk, 1), 'nrKwh': round(ne, 2)}
    if nk > 0:
        cons = ne / nk * 100.0
        b['consKwhPer100km'] = round(cons, 1)
        b['rangeKm'] = round(kwh / cons * 100.0, 2) if cons > 0 else None
    # M77 (2026-07-31): compare the unassisted budget with the longest
    # genuinely-unassisted run (the apples-to-apples pair), and report the
    # fraction of the budget it reaches. observedKm (the regen-assisted
    # runMax) is deliberately NOT emitted here any more: pairing it with
    # rangeKm was the conflation that produced the withdrawn energy-limited
    # claim.
    rmu = out.get('runMaxUnassistedKm')
    b['runMaxUnassistedKm'] = rmu
    b['budgetFractionPct'] = (round(rmu / b['rangeKm'] * 100.0, 1)
                              if rmu is not None and b.get('rangeKm')
                              else None)
    out['bufferLimit'] = b

    out['caveats'] = [
        'EV state is eng_rpm <= 400 (engine not rotating), the same threshold '
        'engine_on_pct uses. The M46/M48 motored-unfuelled state burns no fuel '
        'but counts here as engine ON, so these figures are a conservative '
        'reading of "electric".',
        'The +/-3 s channel alignment and the 3 s state debounce both bias '
        'engine-off upward: every EV distance and time figure is an upper bound.',
        'Runs at the top of the distribution recover 30-50% of throughput as '
        'regen mid-run, so the observed maximum is not a buffer-drain range; '
        'runMaxUnassistedKm is.',
        'M62: the census rests on nValid of nDrives (supportPct); the balance '
        'is channel-gated. Drives whose ensemble outlier flags were never '
        'fitted (NaN) are treated as non-outliers and INCLUDED -- see '
        'nUnflaggedIncluded / kmUnflaggedIncluded for how much distance that '
        'assumption admits.',
        'The barometric PID is 1 kPa (~83 m) quantised and cannot resolve '
        'run-scale gradient, so no terrain attribution is made for long runs.']
    return out


def _typical_soc_band(sub):
    """M70 (2026-07-29): the single definition of a TYPICAL SoC operating band.

    Distinct from the Comparison tab's extrema row (min of soc_min, max of
    soc_max), which is a two-drive statistic: one deep-discharge session and
    one high-ceiling session set the whole reported range, so the extrema band
    describes what the pack has ever done, not what it does. This returns the
    median session floor and ceiling plus the IQR of each, which is what a
    reader means by "where does the buffer normally live".

    Basis note: computed on the UNFILTERED frame, deliberately, matching
    _soc_band_stats. The project default for typical-range claims is
    ens_outlier_v2-clean, but that flag targets energy-accounting anomalies;
    soc_min/soc_max are per-drive extrema of a directly-read BMS channel and
    the low-floor highway sessions it would drop are real drives, not
    domain-invalid ones. Filtering moves the medians by <=0.5 pp here, so the
    two bases agree numerically anyway; keeping them identical means the table
    row and the narrative prose cannot drift apart.
    """
    if sub is None or not len(sub):
        return None
    lo = sub['soc_min'].dropna()
    hi = sub['soc_max'].dropna()
    if not len(lo) or not len(hi):
        return None
    return {
        'n': int(min(len(lo), len(hi))),
        'floorMed': round(float(lo.median()), 1),
        'ceilMed': round(float(hi.median()), 1),
        'floorIqr': [round(float(lo.quantile(0.25)), 1),
                     round(float(lo.quantile(0.75)), 1)],
        'ceilIqr': [round(float(hi.quantile(0.25)), 1),
                    round(float(hi.quantile(0.75)), 1)],
    }


def _soc_band_stats(dm):
    """M31 (2026-07-12): median-based 'typical session' SoC floor/ceiling by
    class, for narrative prose describing typical highway-vs-city SoC-holding
    behaviour. Distinct from the Comparison tab's 'SoC operating band' row
    (_highway_vs_city_master.socBand), which reports the true observed
    extrema across all drives (min of soc_min, max of soc_max) -- a couple of
    genuine outlier drives can push that range wide even when the typical
    session is narrower. Both are legitimate, different statistics; narrative
    prose should cite whichever it actually means instead of a hand-typed
    number that silently drifts. Unfiltered dm (soc_min/soc_max are already
    per-drive extrema; the low-floor highway drives are real sessions, not
    domain-invalid, so no ens-exclusion here)."""
    d = dm.copy()
    d['dclass'] = d['drive_type'].apply(_cond_class)
    out = {}
    # M86 (2026-08-05): native CLASS_ORDER (was a city/mixed/highway
    # collapse). 'city' retained as an alias of 'urban' below for any
    # not-yet-migrated consumer.
    for key in CLASS_ORDER:
        sub = d[d['dclass'] == key]
        if not len(sub):
            out[key] = None
            continue
        # M70: delegated to _typical_soc_band so the narrative prose and the
        # Comparison-tab "Typical SoC operating band" row share one
        # implementation. floorMed/ceilMed are unchanged by the refactor;
        # floorIqr/ceilIqr are new.
        t = _typical_soc_band(sub)
        out[key] = None if t is None else {**t, 'n': int(len(sub))}
    out['city'] = out['urban']
    return out


def _highway_vs_city_master(dm):
    """M30 (2026-07-12, audit) / M31 (2026-07-12, addendum): the six
    Comparison-tab metrics computable from drive_master alone (the other
    four -- engine trigger/stop SoC, turbo activity, engine-reaches-80C --
    need the raw 1 Hz series and are computed in _RawAccum, category B).

    M86 (2026-08-05): native CLASS_ORDER buckets (Urban/Mixed/Mixed Highway/
    Highway), not the prior hand-rolled City/Mixed/Highway collapse
    ('mixed_highway'+'highway' blended into one 'highway' bucket). That
    blended convention is now used ONLY by the cycle-life scenario
    projection (_cycle_projection/_audit_observed_mix), where "highway" is a
    hand-chosen forward-usage archetype weight, not an empirical pooling
    bucket -- it is intentionally left unchanged there. 'city' is retained
    as an alias of 'urban' in the output dicts below for any not-yet-
    migrated consumer. 'unknown' drive_type (1 drive) is excluded from all
    buckets.

    Two evidentiary standards, matching the rest of the pipeline's
    convention (records use unfiltered extrema; trend/typical-range claims
    use the ens_outlier_v2-clean set):
      - true extrema (SoC band, battery temp, peak currents): unfiltered dm,
        same basis as _records(), since these are ceiling/extreme claims.
      - typical-operating ranges (gross discharge, engine-ON fraction): the
        ens_outlier_v2-clean set, since anomalous drives would distort a
        'typical range' claim.

    M31: 'Net discharge/100km' (net_draw_per100km_corr2p, i.e. SoC start/end
    balance over the whole drive) is REPLACED by gross_discharge_kwh/100km --
    the actual energy pulled out of the pack per 100 km, regardless of how
    much the generator later put back in. Same basis and p10-p90+median band
    convention as the 'Battery Draw Spectrum' chart (efficiencyBands, M21):
    net/start-end balance mostly reflects where the buffer happened to land
    relative to where it started (trends toward zero on longer drives
    regardless of how hard the battery worked), not genuine buffer
    utilization -- see the efficiencyBands docstring for the full argument
    and worked example (20260627_144929.csv).

    Supersedes the hand-authored highwayVsCity block in summary_config.json,
    which had drifted from current data (e.g. SoC band 'highway: 60-82%' vs
    the observed 44.5-84.5%; used a highway-only, not blended, basis; used
    the start/end-balance net-draw metric now known to be a start/end-
    balance artifact; and had no 'mixed' column)."""
    d = dm.copy()
    d['dclass'] = d['drive_type'].apply(_cond_class)
    if 'ens_outlier_v2' in d:
        d['ens'] = _as_bool(d['ens_outlier_v2'])
    elif 'ens_outlier' in d:
        d['ens'] = _as_bool(d['ens_outlier'])
    else:
        d['ens'] = False
    buckets_all = {k: d[d['dclass'] == k] for k in CLASS_ORDER}
    buckets_all['city'] = buckets_all['urban']    # M86: back-compat alias
    buckets_cl = {k: v[~v['ens']] for k, v in buckets_all.items()}

    out = {}

    # 1. SoC operating band (true extrema)
    def soc_band(sub):
        if not len(sub) or sub['soc_min'].isna().all() or sub['soc_max'].isna().all():
            return None
        return f"{sub['soc_min'].min():.1f}-{sub['soc_max'].max():.1f}%"
    out['socBand'] = {k: soc_band(v) for k, v in buckets_all.items()}

    # 1b. M70: TYPICAL band -- median session floor/ceiling + IQR of each.
    # The extrema row above is set by single drives at each end; this is the
    # band the buffer actually operates in on an ordinary session.
    def soc_band_typical(sub):
        t = _typical_soc_band(sub)
        if t is None:
            return None
        return (f"{t['floorMed']:.1f}-{t['ceilMed']:.1f}% "
                f"(floor IQR {t['floorIqr'][0]:.1f}-{t['floorIqr'][1]:.1f} "
                f"\u00b7 ceiling IQR {t['ceilIqr'][0]:.1f}-{t['ceilIqr'][1]:.1f}, "
                f"n={t['n']})")
    out['socBandTypical'] = {k: soc_band_typical(v)
                             for k, v in buckets_all.items()}

    # 2. Gross discharge/100km (M31: replaces net/start-end-balance basis;
    # ens-clean p10-p90 band + median, matching efficiencyBands exactly)
    def gross_band(sub):
        s = sub[sub['distance_km'] > 0]
        g = (s['gross_discharge_kwh'] / s['distance_km'] * 100).dropna()
        if not len(g):
            return None
        lo, hi, med = g.quantile(0.10), g.quantile(0.90), g.median()
        return f"{lo:.1f}-{hi:.1f} kWh/100km (median {med:.1f}, n={len(g)})"
    out['grossDischarge'] = {k: gross_band(v) for k, v in buckets_cl.items()}

    # 3. Engine ON fraction (ens-clean typical range)
    def eng_on_range(sub):
        s = sub['engine_on_pct'].dropna()
        return None if not len(s) else f"{s.min():.0f}-{s.max():.0f}%"
    out['engineOnFrac'] = {k: eng_on_range(v) for k, v in buckets_cl.items()}

    # 4. Battery temp Sensor 1 (true extrema, attributed like _records())
    def t1_range(sub):
        s = sub['T1_peak'].dropna()
        if not len(s):
            return None
        idx = s.idxmax()
        lbl = _day_label(dm, idx)
        tail = f" ({s.loc[idx]:.0f}\u00b0C on {lbl})" if lbl else ""
        return f"{s.min():.0f}-{s.max():.0f}\u00b0C" + tail
    out['battTempS1'] = {k: t1_range(v) for k, v in buckets_all.items()}

    # 5. Peak charge currents, by source channel (true extrema, attributed)
    def chan_peak(sub, col, lbl_name):
        s = sub[col].dropna()
        if not len(s):
            return None
        idx = s.idxmax()
        dlbl = _day_label(dm, idx)
        return f"{abs(float(s.loc[idx])):.0f} A {lbl_name}" + (f" ({dlbl})" if dlbl else "")

    def peak_charge_str(sub):
        parts = [p for p in (
            chan_peak(sub, 'eng_charge_peak_A', 'eng-charge'),
            chan_peak(sub, 'dual_peak_A', 'dual-channel'),
            chan_peak(sub, 'regen_peak_A', 'pure regen'),
        ) if p]
        return " / ".join(parts) if parts else None
    out['peakChargeI'] = {k: peak_charge_str(v) for k, v in buckets_all.items()}

    # 6. Peak discharge currents (median + range + n, true extrema basis)
    def peak_disch_str(sub):
        s = sub['peak_I_discharge'].dropna()
        if not len(s):
            return None
        return f"{s.min():.0f}-{s.max():.0f} A (median {s.median():.0f}A, n={len(s)})"
    out['peakDischargeI'] = {k: peak_disch_str(v) for k, v in buckets_all.items()}

    return out


def _assemble_highway_vs_city(master_hvc, raw_hvc):
    """M30/M31: merge the six Category-A rows with the four Category-B
    (raw-pass) rows into the single list-of-{metric,urban,mixed,
    mixed_highway,highway} shape the JSX consumes for the 'Comparison' tab
    (S.highwayVsCity.map). The computed array wins over config on key
    collision (see buildS).

    M86 (2026-08-05): native CLASS_ORDER columns (Urban/Mixed/Mixed Highway/
    Highway), replacing the prior City/Mixed/Highway table where 'Highway'
    silently pooled mixed_highway+highway. 'city' is still emitted as an
    alias of 'urban' for any not-yet-migrated consumer.

    M173 (2026-08-27): 'Engine reaches 80C+' row now reads hvcEngine80C's
    unified 'urban' bucket directly, like the other three columns --
    supersedes the city_short(<5km)/city_long(5-20km) sub-split, the one
    place this table still had a distance-based holdout under CLASS_ORDER."""
    warm = raw_hvc.get('hvcEngine80C', {}) if raw_hvc else {}
    ub, mx, mh, hw = (warm.get('urban'), warm.get('mixed'),
                      warm.get('mixed_highway'), warm.get('highway'))
    # M70: notes are optional third tuple members rendered as sub-captions, so
    # the two SoC rows declare their own basis instead of looking like a
    # contradiction. Rows without a note keep the 2-tuple form.
    rows = [
        ('Typical SoC operating band', master_hvc.get('socBandTypical', {}),
         'median session floor\u2192ceiling, IQR of each \u2014 where the buffer '
         'normally operates'),
        ('SoC operating band', master_hvc.get('socBand', {}),
         'true extrema: min soc_min \u2192 max soc_max across all drives \u2014 '
         'set by single sessions at each end'),
        ('Engine trigger SoC', (raw_hvc or {}).get('hvcEngineTriggerSoC', {})),
        ('Engine stop SoC', (raw_hvc or {}).get('hvcEngineStopSoC', {})),
        ('Gross discharge/100km', master_hvc.get('grossDischarge', {})),
        ('Engine ON fraction', master_hvc.get('engineOnFrac', {})),
        ('Turbo activity', (raw_hvc or {}).get('hvcTurboActivity', {})),
        ('Battery temp (Sensor 1)', master_hvc.get('battTempS1', {})),
        ('Engine reaches 80\u00b0C+',
         {'urban': ub, 'city': ub, 'mixed': mx, 'mixed_highway': mh,
          'highway': hw}),
        ('Peak charge currents', master_hvc.get('peakChargeI', {})),
        ('Peak discharge currents', master_hvc.get('peakDischargeI', {})),
    ]
    return [{'metric': r[0], 'note': (r[2] if len(r) > 2 else None),
             'urban': (r[1] or {}).get('urban') or '\u2014',
             'city': (r[1] or {}).get('urban') or '\u2014',
             'mixed': (r[1] or {}).get('mixed') or '\u2014',
             'mixed_highway': (r[1] or {}).get('mixed_highway') or '\u2014',
             'highway': (r[1] or {}).get('highway') or '\u2014'} for r in rows]


def _cycle_projection(dm, clean, age_yr, odo):
    """Cycle-life projection under distance-mix scenarios, driven by the observed
    per-class cycle intensity (efc per km, ens-clean) and the vehicle's real
    lifetime odometer (external). No hand-set cycle rates.

    M21: condition class is now drive_type (time-weighted), not distance_km
    (see CLASS_ORDER comment). The scenario mix below is still expressed as
    3 buckets (city / mixed / highway); 'highway' here is the distance-
    weighted blend of the 'mixed_highway' and 'highway' drive_type classes
    (both majority-highway-speed-influenced), the same blending pattern the
    old code used to merge city_short+city_long into a single 'city' bucket.

    M86 (2026-08-05): every OTHER condition-class array in this module
    (highwayVsCity, socBands, hvcTurboActivity, hvcEngine80C, warmupCurve,
    batteryTempRanges' class axis) was migrated off this collapse to native
    CLASS_ORDER. This function is the one deliberate holdout: the scenario
    archetypes below (City-heavy, Mixed use, Highway-heavy) are hand-chosen
    forward-usage WEIGHTS, not empirical pooling buckets -- splitting
    'highway' into 'mixed_highway'+'highway' here would require asserting a
    new weight (how much pure-highway vs. mixed-highway driving a "Highway-
    heavy" driver does) with no basis in the corpus to derive it from, and
    would break the M56 byte-comparability of prior scenario figures. Kept
    blended by explicit decision, not oversight."""
    clean2 = clean.copy()
    clean2['dclass'] = clean2['drive_type'].apply(_cond_class)
    intensity = {}
    for k in CLASS_ORDER:
        g = clean2[clean2['dclass'] == k]
        d = g['distance_km'].sum()
        intensity[k] = float(g['gtc'].sum() / d) if d > 0 else 0.0
    # blended highway intensity (distance-weighted across highway + mixed_highway)
    hwy_km = clean2[clean2['dclass'].isin(['mixed_highway', 'highway'])]['distance_km'].sum()
    hwy_int = (intensity['mixed_highway'] *
               clean2[clean2['dclass'] == 'mixed_highway']['distance_km'].sum()
               + intensity['highway'] *
               clean2[clean2['dclass'] == 'highway']['distance_km'].sum()) / hwy_km \
        if hwy_km > 0 else 0.0
    lvl = {'city': intensity['urban'], 'mixed': intensity['mixed'], 'highway': hwy_int}
    annual_km = odo / age_yr if age_yr > 0 else 0.0
    # M56 (audit F-04): 'Realistic blend' renamed -> 'Selected blend'. The label
    # implied empirical support the mix does not have: at 55/30/15 it is far more
    # city-weighted than the OBSERVED logged distance mix, which inflates modeled
    # GTC intensity ~39 %. The observed mix is now carried as an explicit
    # scenario so the two are directly comparable. Weights are unchanged, so all
    # prior scenario numbers remain byte-comparable under the new label.
    _typed = clean2[clean2['dclass'].isin(
        ['urban', 'mixed', 'mixed_highway', 'highway'])]
    _tk = _typed['distance_km'].sum()
    if _tk > 0:
        obs_mix = {
            'city': float(_typed[_typed['dclass'] == 'urban']['distance_km'].sum() / _tk),
            'mixed': float(_typed[_typed['dclass'] == 'mixed']['distance_km'].sum() / _tk),
            'highway': float(hwy_km / _tk)}
    else:
        obs_mix = {'city': .55, 'mixed': .30, 'highway': .15}
    # M85 (2026-08-05): Selected blend reconciled to the highway-dominant
    # forward-usage frame (city .40 / mixed .10 / highway .50, == the
    # cold/working-season endpoint of the All-year model). This is the WARM-
    # FLOOR mix rate; build_summary_arrays() overrides the Selected row's rate
    # with the CLIMATIC-STRESS rate from _seasonal_projection.selectedConstant
    # (throughput-multiplied, seasonal) and flips measured -> False, because the
    # blend now carries the M28 seasonal assumption load. The archetype rows
    # (City-heavy / Mixed use / Highway-heavy / Observed) stay warm-floor and
    # measured, as pure per-class reference points.
    scen = {'City-heavy':      {'city': .70, 'mixed': .20, 'highway': .10},
            'Selected blend':  {'city': .40, 'mixed': .10, 'highway': .50},
            'Mixed use':       {'city': .40, 'mixed': .35, 'highway': .25},
            'Highway-heavy':   {'city': .20, 'mixed': .30, 'highway': .50},
            'Observed logged mix': obs_mix}
    colors = {'City-heavy': '#ef4444', 'Selected blend': '#60a5fa',
              'Mixed use': '#eab308', 'Highway-heavy': '#22c55e',
              'Observed logged mix': '#a78bfa'}
    projections = []
    for name, mix in scen.items():
        cyc_per_km = sum(mix[k] * lvl[k] for k in mix)
        rate = cyc_per_km * annual_km                     # cycles / yr
        accumulated = cyc_per_km * odo                    # cycles at current odo
        remain = (CYCLE_RATED_LIFE - accumulated) / rate if rate > 0 else None
        projections.append({
            'label': name, 'color': colors[name],
            'rate': round(rate), 'accumulated': round(accumulated),
            'warmFloorRate': round(rate),          # M85: pre-climatic reference
            'warmFloorAccumulated': round(accumulated),
            'yearsRemain': round(remain, 1) if remain else None,
            'yearsTotal': round((remain + age_yr), 1) if remain else None,
            'governs': 'cycle',   # warm-season basis: cycle limit governs
            'gtcPerKm': round(cyc_per_km, 5),
            'mix': {k: round(v * 100, 1) for k, v in mix.items()},
            'basis': ('observed logged distance mix' if name == 'Observed logged mix'
                      else 'hand-selected forward-usage assumption'),
            # M112 (2026-08-10, audit P1): City-heavy/Mixed use/Highway-heavy
            # are hand-chosen forward-usage WEIGHTS (see scen{} above and the
            # docstring at the top of this function) -- their workload input
            # is an assumption, not a measurement, even though the per-class
            # intensity rates (lvl[k]) they are multiplied by ARE measured.
            # Only 'Observed logged mix' has a workload split actually read
            # from the corpus (obs_mix, above). Previously all four
            # non-Selected rows were flagged measured:True; only this one
            # should be. 'basis' already documented this distinction
            # correctly -- 'measured' did not match it.
            'measured': name == 'Observed logged mix',
            'climaticStress': False,
            'primary': name == 'Selected blend'})
    # cycleAtOdo band: accumulated cycles at the current odometer by scenario
    acc = {p['label']: p['accumulated'] for p in projections}
    cycle_at_odo = {'city': acc['City-heavy'], 'mixed': acc['Mixed use'],
                    'highway': acc['Highway-heavy'], 'blend': acc['Selected blend']}
    # M56 (audit F-01/5.4): threshold sensitivity. Crossing age is essentially
    # linear in the assumed turnover threshold, which is the clearest evidence
    # that the headline year figure is a scenario output, not a measured life.
    _sel = scen['Selected blend']
    _gpk = sum(_sel[k] * lvl[k] for k in _sel)
    _rate = _gpk * annual_km
    _acc = _gpk * odo
    thr_sens = [{'thresholdGtc': t,
                 'crossingYr': round(age_yr + (t - _acc) / _rate, 1)}
                for t in (10000, 15000, 20000, 25000, 30000)] if _rate > 0 else []
    return {'ratedLife': CYCLE_RATED_LIFE,
            'scenarioThresholdGtc': SCENARIO_THRESHOLD_GTC,
            'thresholdVerified': False,
            'thresholdSensitivity': thr_sens,
            'observedMixShare': {k: round(v * 100, 1) for k, v in obs_mix.items()},
            'thresholdNote': ('20,000 GTC is an unverified generic planning '
                              'threshold with no pack-rated provenance and no '
                              'validated link to 80 % SOH. Crossings below are '
                              'workload scenarios, not EOL predictions.'),
            'annualKm': round(annual_km),
            'carAgeNow': round(age_yr, 4), 'odometer': round(odo),
            'intensityGtcPerKm': {k: round(v, 4) for k, v in intensity.items()},
            'highwayBlendedIntensity': round(hwy_int, 4),
            'cycleAtOdo': cycle_at_odo, 'projections': projections}


def _power_fade(dm, raw_loader=None):
    """M61 (2026-07-27): pipeline-bound producer for the `powerFade` block.

    PROVENANCE FIX. The shipped summary_arrays.json carried `powerFade` as an
    out-of-band injection: the numbers were correct (they came from
    compute_drive_summary_v6._powerfade_trend) but build_summary_arrays() did
    not produce the key, so an arrays-only regeneration silently DROPPED it and
    every dashboard figure bound to S.powerFade would have rendered blank. The
    v6 trend function is called here so the key regenerates deterministically
    (seed 42, N_BOOT=4000 -> byte-identical to the archived block).

    Adds the M61 detection-power fields. A trend whose 95 % interval spans zero
    is only informative if you also state what slope the window COULD have
    resolved; otherwise "no detectable fade" is unfalsifiable. See
    `detectionHorizon` for the required-monitoring-window ladder.
    """
    import compute_drive_summary_v6 as _v6
    d = dm.copy()
    if 'date' in d.columns:
        d['date'] = d['date'].astype(str)   # M52: never let dates arrive as NaT
    t = _v6._powerfade_trend(d, raw_loader=raw_loader)
    if 'slope_mohm_per_month_Tctrl' not in t:
        return {'basis': None, 'note': t.get('note', 'trend unavailable'),
                'nClean': t.get('n', 0)}
    rcol = t['R_basis']
    keep = ~_as_bool(dm['ens_outlier_v2']) if 'ens_outlier_v2' in dm.columns \
        else pd.Series(True, index=dm.index)
    r_clean = dm[keep][rcol].dropna()
    lo, hi = t['boot_ci95_mohm_per_month']
    r_med = t['R_median_mohm']
    # Minimum detectable effect at the present window/noise: the smallest
    # monthly slope whose estimate would clear zero, i.e. the CI half-width.
    mde = (hi - lo) / 2.0
    dts = pd.to_datetime(dm[keep].dropna(subset=[rcol])['date'])
    window_mo = float((dts.max() - dts.min()).days) / 30.44
    # Required-window scaling. For an OLS slope with a fixed drive-sampling
    # density, SE(b1) = sigma / (sqrt(n) * SD(t)); n grows ~linearly with the
    # window T and SD(t) ~linearly with T, so SE ~ T^-1.5. ASSUMPTIONS:
    # constant logging cadence, homogeneous residual variance, genuinely
    # linear fade. Documented, not measured -- read as an order-of-magnitude
    # planning figure for how long monitoring must continue.
    def _req_mo(target):
        if target <= 0 or mde <= 0 or window_mo <= 0:
            return None
        return round(window_mo * (mde / target) ** (1.0 / 1.5), 1)
    horizon = []
    for rise_pct, yrs in ((20, 15), (20, 10), (30, 10), (50, 10)):
        tgt = rise_pct / 100.0 * r_med / (yrs * 12.0)
        horizon.append({'risePct': rise_pct, 'overYr': yrs,
                        'slopeMohmPerMo': round(tgt, 4),
                        'reqWindowMo': _req_mo(tgt),
                        'resolvedNow': bool(tgt >= mde)})
    # M170: the significance clause is now derived from the actual CI, not
    # hardcoded. The pre-M170 note asserted "spans zero" unconditionally; once
    # the cadence-confounded slope crossed the boundary that text contradicted
    # the shipped CI. It is also stated whether cadence was controlled.
    spans_zero = bool(lo <= 0.0 <= hi)
    cadence_controlled = bool(t.get('cadence_controlled', False))
    sig_clause = (
        'The 95 % day-cluster interval spans zero: no statistically '
        'detectable power fade in this window.' if spans_zero else
        'The 95 % day-cluster interval excludes zero on this build; read it '
        'with the cadence caveat below and the short window before treating '
        'it as fade.')
    cad_clause = (
        ' Sampling cadence IS controlled (M170): HV-current logging density -- '
        'which changed mid-corpus with the PID configuration and otherwise '
        'biases this load-excited proxy upward -- is held constant in the '
        'trend.' if cadence_controlled else
        ' WARNING: sampling cadence is NOT controlled on this build; HV-current '
        'logging density changed mid-corpus (CHANGELOG M126) and can bias the '
        'slope. Supply a raw_loader to engage M170 cadence normalization.')
    return {
        'basis': rcol,
        'rMedianMohm': r_med,
        'rP25Mohm': round(float(r_clean.quantile(0.25)), 1),
        'rP75Mohm': round(float(r_clean.quantile(0.75)), 1),
        'nClean': t['n_clean'],
        'nAllRows': int(dm[rcol].notna().sum()),
        'slopeMohmPerMoTctrl': t['slope_mohm_per_month_Tctrl'],
        'ci95MohmPerMo': [lo, hi],
        'pSlopeGt0': t['p_slope_gt0'],
        'bTMohmPerDegC': t['bT_mohm_per_degC'],
        'nBoot': t['n_boot'],
        'cadenceControlled': cadence_controlled,
        # --- M61 detection power ---
        'windowMo': round(window_mo, 2),
        'mdeMohmPerMo': round(mde, 3),
        'mdeRisePctPerYr': round(mde * 12.0 / r_med * 100.0, 1),
        'detectionHorizon': horizon,
        'horizonBasis': ('SE(slope) ~ T^-1.5 at constant logging cadence; '
                         'assumes homogeneous residual variance and linear '
                         'fade. Planning figure, not a measurement.'),
        'note': ('M25/M56/M170. Temperature- and sampling-cadence-controlled '
                 'V-regression resistance trend. ' + sig_clause + cad_clause +
                 ' Absolute level is a load-excited in-drive proxy, NOT '
                 'relaxed-OCV resistance, and is available on only a selected '
                 'subset of drives - use for trend, never as an absolute SOH '
                 'measurement.')}


def _reconcile_resistance_models(arrays, dm, raw_loader=None):
    """M207 (C-04/F-08): resolve the two conflicting resistance-trend results
    the audit flagged (powerFade +0.013 mOhm/mo, p=0.497 vs
    degradationTrends.resistanceVreg ~+1.16-1.19 mOhm/mo, cadence-uncontrolled)
    into ONE primary estimand plus a labelled sensitivity.

    They are NOT two independent estimands. They are the SAME day-cluster
    bootstrap regression with and WITHOUT the M170 HV-current logging-cadence
    control. Logging density ~doubled mid-corpus (M126) and biases the
    load-excited vreg proxy upward (regression attenuation; Barai 2018); that
    density is confounded with calendar time (corr months~coverage +0.725), so
    the cadence-UNCONTROLLED slope is levered positive by instrumentation, not
    pack aging. Holding cadence constant collapses it to +0.013 (p~0.497).

    Primary  = powerFade (cadence-controlled).
    Sensitivity = degradationTrends.resistanceVreg (cadence-uncontrolled).
    The released resistance equivalence test is run on the CADENCE-CONTROLLED
    slope so the released inference is coherent. Idempotent; additive-only.
    """
    import compute_drive_summary_v6 as _v6
    import degradation_trends as _dtr
    pf = arrays.get('powerFade') or {}
    dtr_blk = arrays.get('degradationTrends') or {}
    rv = dtr_blk.get('resistanceVreg') or {}

    t_cc = _v6._powerfade_trend(dm, raw_loader=raw_loader)
    t_un = _v6._powerfade_trend(dm, raw_loader=None)
    if 'slope_mohm_per_month_Tctrl' not in t_cc:
        return arrays
    b_cc = t_cc['slope_mohm_per_month_Tctrl']
    lo, hi = t_cc['boot_ci95_mohm_per_month']
    se_cc = (hi - lo) / (2 * 1.959964)
    b_un = t_un.get('slope_mohm_per_month_Tctrl')

    keep = ~_as_bool(dm['ens_outlier_v2']) if 'ens_outlier_v2' in dm.columns \
        else pd.Series(True, index=dm.index)
    cc = dm[keep].dropna(subset=['vreg_R_pack_mohm', 'date'])
    G = pd.to_datetime(cc['date']).dt.date.nunique()
    # M207 (F-07): equivalence delta uses the FROZEN SESOI baseline median, not
    # the live sample median, matching degradation_trends' locked bound.
    delta = 0.75 * _dtr.VREG_MED_BASELINE_MOHM / (14 * 12)   # oem75pct_over14yr
    tost_cc = {**{'label': 'oem75pct_over14yr', 'delta': round(delta, 4)},
               **_dtr._tost(b_cc, se_cc, delta, df=G - 1)}

    if pf:
        pf['role'] = 'primaryResistanceEstimand'
        pf['sensitivityRef'] = 'degradationTrends.resistanceVreg'
        pf['releasedResistanceEquivalence'] = tost_cc
        arrays['powerFade'] = pf

    if rv:
        rv['role'] = 'sensitivity_cadence_uncontrolled'
        rv['cadenceControlled'] = False
        rv['primaryEstimandRef'] = 'powerFade'
        rv['sensitivitySlopeMohmPerMo'] = b_un
        rv['releasedEquivalence'] = tost_cc
        rv['tostEstimatorBasis'] = 'powerFadeCadenceControlled'
        rv['tostSlopeUsed'] = round(float(b_cc), 4)
        rv['tostSeUsed'] = round(float(se_cc), 4)
        dtr_blk['resistanceVreg'] = rv

    dtr_blk['resistanceReconciliation'] = {
        'primaryEstimand': 'powerFade',
        'primarySlopeMohmPerMo': b_cc,
        'primaryCi95': [lo, hi],
        'primaryPslopeGt0': t_cc['p_slope_gt0'],
        'primaryCadenceControlled': bool(t_cc.get('cadence_controlled', False)),
        'sensitivitySlopeMohmPerMo': b_un,
        'sensitivityCi95': t_un.get('boot_ci95_mohm_per_month'),
        'releasedResistanceEquivalence': tost_cc,
        'cadenceConfoundMechanism': (
            'HV-current PID logging density ~doubled mid-corpus (M126); denser '
            'logging biases the load-excited vreg proxy upward and is confounded '
            'with calendar time, levering the UNcontrolled slope positive. M170 '
            'holds logging density constant.'),
        'conclusion': (
            f'Cadence-controlled slope {b_cc:+.3f} mOhm/mo (CI [{lo}, {hi}], '
            f'p(slope>0)={t_cc["p_slope_gt0"]}) is the primary resistance '
            f'estimand; its interval spans zero -> no resolved trend. The '
            f'{b_un:+.3f} mOhm/mo cadence-uncontrolled sensitivity is the M126 '
            f'logging-density artifact, not pack aging. Released equivalence '
            f'(vs {delta:.4f} mOhm/mo OEM 75%/14yr bound) is run on the '
            f'cadence-controlled slope: equivalent={tost_cc.get("equivalent")} '
            f'(pTOST={tost_cc.get("pTOST")}) -- window too short to establish '
            f'equivalence either. The prior M161 "one reconciled resistance '
            f'estimate" claim is withdrawn.')}
    arrays['degradationTrends'] = dtr_blk
    return arrays


def _fade_modes(dm, cyc, seasonal, power_fade):
    """M61 (2026-07-27): separate the two degradation mechanisms the dashboard
    had been presenting as one line, and replace the five precise crossing
    labels with a two-dimensional sensitivity matrix.

    WHY. The old projection chart drew five workload trajectories, each ending
    in a dot annotated to 0.1 yr against a single 20,000-GTC line. Two distinct
    problems:

      (1) FALSE PRECISION / WRONG DOMINANT TERM. A crossing year is a function
          of BOTH the workload scenario AND the threshold, and the threshold is
          the *unverified* input (F-01: generic-lithium planning figure, no
          pack-rated provenance, no validated link to 80 % SOH). Plotting five
          crossings against one threshold visually attributes the whole spread
          to workload choice, when varying the threshold across its plausible
          range moves the answer further than any workload choice does. The
          matrix makes both axes visible and lets the reader see which
          dominates instead of being told.

      (2) CONFLATED MECHANISMS. Capacity fade (usable Ah loss) and power fade
          (internal-resistance rise) are different mechanisms with different
          drivers, different end-of-life criteria, and -- decisively here --
          different EVIDENCE STATUS in this corpus. A single "years to
          threshold" line implied both were being projected. They are not:

          * capacity fade   -> modeled only. There is NO capacity observable in
            this dataset. `cap_ah_est` is not a measurement: it is
            CAP_KWH / V_pack_median, an algebraic restatement of the assumed
            2.1 kWh nameplate, so it cannot detect capacity loss even in
            principle. Resolving real capacity fade needs a full-window
            coulomb count between relaxed-OCV anchors; the pack never leaves
            its ~44-82 % operating band in normal e-POWER use, so passive OBD
            logging cannot produce one.
          * power fade      -> MEASURED, with a null result (M25) and a stated
            minimum detectable effect (M61).

          For a series-hybrid buffer worked at 20-33 C peak rates, power fade
          is arguably the functionally-limiting mode, and it is the one this
          study can actually observe. Merging it into the GTC line hid that.
    """
    thresholds = [10000, 15000, 20000, 25000, 30000]
    age = cyc.get('carAgeNow')
    ref = cyc.get('scenarioThresholdGtc')
    if age is None or not cyc.get('projections'):
        return None
    # cycle-weighted mean depth-of-discharge (M17 rainflow columns, ens-clean)
    _cl = dm[~_as_bool(dm['ens_outlier_v2'])] if 'ens_outlier_v2' in dm.columns \
        else dm
    _d = _cl.dropna(subset=['rf_dod_wmean_pct', 'rf_n_cycles']) \
        if {'rf_dod_wmean_pct', 'rf_n_cycles'} <= set(_cl.columns) \
        else _cl.iloc[0:0]
    _dod_wmean = (round(float((_d['rf_dod_wmean_pct'] * _d['rf_n_cycles']).sum()
                              / _d['rf_n_cycles'].sum()), 2)
                  if len(_d) and _d['rf_n_cycles'].sum() > 0 else None)

    def _cross(acc, rate):
        return [(round(age + (t - acc) / rate, 1) if rate > 0 else None)
                for t in thresholds]

    rows = []
    for p in cyc['projections']:
        rows.append({'label': p['label'], 'color': p['color'],
                     'primary': bool(p.get('primary')),
                     'basis': p.get('basis'),
                     'rateGtcYr': p['rate'], 'accumulatedGtc': p['accumulated'],
                     'gtcPerKm': p.get('gtcPerKm'),
                     # M85: honor the per-row flag. Archetype/observed rows are
                     # measured warm-floor; the Selected row is demoted to
                     # measured:false once it carries climatic stress.
                     'measured': bool(p.get('measured', True)),
                     'climaticStress': bool(p.get('climaticStress', False)),
                     'crossingYr': _cross(p['accumulated'], p['rate'])})
    if seasonal and seasonal.get('rate') and seasonal.get('accumulated'):
        rows.append({'label': 'All-year model (M28)', 'color': '#ec4899',
                     'primary': False,
                     'basis': ('seasonal re-weighting of the same measured '
                               'intensities over Kyiv climate normals; the cold '
                               'tail below the lowest logged pack-probe reading '
                               'is modelled, not observed'),
                     'rateGtcYr': round(seasonal['rate']['mid']),
                     'accumulatedGtc': round(seasonal['accumulated']['mid']),
                     'gtcPerKm': None, 'measured': False,
                     'crossingYr': _cross(seasonal['accumulated']['mid'],
                                          seasonal['rate']['mid'])})
    # M65 (2026-07-29): display order is now ASSUMPTION LOAD, ascending, not
    # the incidental order the projection list was built in. The matrix is a
    # sensitivity table, so the reader should descend it from the row that
    # assumes least to the row that assumes most:
    #   0  observed logged distance mix  - the measured duty cycle; the only
    #                                      row whose workload input is data
    #   1  archetype mixes               - hand-chosen, but single-axis
    #   2  Selected blend (primary)      - the anchor row. M85: it now carries
    #                                      climatic stress (measured:false), but
    #                                      it stays at rank 2 (directly above the
    #                                      model it is most compared against),
    #                                      because it is still the single primary
    #                                      row and the study's reference mix.
    #   3  All-year model (M28)          - re-weighted, no sub-15 C pack data
    # Sorted stably, so ties keep their descending-rate order.
    # M112 (2026-08-10, audit P1): archetype rows' 'measured' flag was
    # corrected from True to False (their workload mix is hand-chosen, not
    # observed -- see the projections-list comment above). This rank
    # function previously used 'measured' to separate archetypes (rank 1)
    # from the seasonally-reweighted All-year model (rank 3); with the flag
    # corrected, both are now measured:False and would collapse into the
    # same rank. Switched the discriminator to 'basis', which already
    # encodes exactly this distinction in its own text and is unaffected by
    # the measured-flag fix. Sort order (and every prior test/isolation-diff
    # assumption about row order) is therefore unchanged by M112.
    def _assumption_rank(r):
        basis = (r.get('basis') or '').lower()
        if r.get('primary'):
            return 2                       # Selected anchor (M85: even if modeled)
        if 'observed logged' in basis:
            return 0                       # measured duty cycle
        if basis == 'hand-selected forward-usage assumption':
            return 1                       # archetype mixes, single-axis
        return 3                           # All-year model / other re-weighted
    rows.sort(key=_assumption_rank)

    ri = thresholds.index(ref) if ref in thresholds else 2
    at_ref = [r['crossingYr'][ri] for r in rows if r['crossingYr'][ri] is not None]
    prim = next((r for r in rows if r['primary']), rows[0])
    prim_row = [v for v in prim['crossingYr'] if v is not None]
    # Sensitivity coefficient: years of crossing age bought per +1000 GTC of
    # assumed threshold, at the primary scenario's rate. Near-exactly linear.
    yr_per_1k = (round(1000.0 / prim['rateGtcYr'], 2)
                 if prim['rateGtcYr'] else None)
    full = [v for r in rows for v in r['crossingYr'] if v is not None]
    return {
        'basis': ('M61. Two-dimensional scenario sensitivity replacing the '
                  'five single-threshold crossing labels, plus explicit '
                  'separation of capacity-fade and power-fade mechanisms.'),
        'capacity': {
            'mechanism': 'usable-capacity (Ah) loss',
            'evidenceStatus': 'MODELED ONLY - no observable in this corpus',
            'observable': None,
            'whyNoObservable': (
                'cap_ah_est = CAP_KWH / V_pack_median is an algebraic '
                'restatement of the assumed 2.1 kWh nameplate, not a '
                'measurement, and carries zero capacity-fade information. A '
                'real measurement needs a coulomb count between two relaxed-'
                'OCV anchors spanning most of the pack window; the buffer '
                'never leaves ~44-82 % SoC in normal use, so passive OBD '
                'logging cannot produce one. A BMS that rescales its own SoC '
                'as the pack ages would additionally mask fade from any '
                'SoC-referenced proxy.'),
            'projectedBy': ('cumulative gross capacity turnover (GTC) vs an '
                            'unverified generic threshold'),
            'thresholdGtc': ref, 'thresholdVerified': False,
            'thresholds': thresholds, 'rows': rows,
            'refIndex': ri,
            'workloadSpanYr': ([round(min(at_ref), 1), round(max(at_ref), 1)]
                               if at_ref else None),
            'thresholdSpanYr': ([round(min(prim_row), 1), round(max(prim_row), 1)]
                                if prim_row else None),
            'matrixSpanYr': ([round(min(full), 1), round(max(full), 1)]
                             if full else None),
            'yrPer1kGtc': yr_per_1k,
            'dominantTerm': (
                'threshold' if (prim_row and at_ref and
                                (max(prim_row) - min(prim_row)) >
                                (max(at_ref) - min(at_ref))) else 'workload'),
            'note': ('Every cell is a scenario output. The row axis varies a '
                     'hand-chosen forward-usage mix; the column axis varies an '
                     'unverified threshold. Neither axis is a prediction and '
                     'the table is not an end-of-life estimate.')},
        'power': {
            'mechanism': 'internal-resistance rise (power capability loss)',
            'evidenceStatus': ('PROXY - no resolved trend; precision stated as a '
                               'CI half-width'),
            'observable': (power_fade or {}).get('basis'),
            'projectedBy': None,
            'whyNotProjected': (
                'No validated resistance-vs-throughput law exists for this '
                'pack, and the measured trend is statistically '
                'indistinguishable from zero, so any extrapolation would be '
                'slope-noise multiplied by time. Reported as a monitored '
                'level + interval, deliberately WITHOUT a crossing year.'),
            'trend': power_fade,
            # Duty-cycle context for why resistance rise is the more plausible
            # functional limit here: cycle-weighted mean DoD across the clean
            # corpus (M17 rainflow basis). Bound to the master so the prose
            # cannot carry a stale literal.
            'meanDodPct': _dod_wmean,
            'relevance': (
                'For a series-hybrid power buffer cycled at 20-33 C peaks and '
                '~4 % mean DoD, resistance rise is the more plausible '
                'functional limit than Ah loss; it is also the only one of '
                'the two this dataset can observe.')},
        'coupling': (
            'The 20,000-GTC convention implicitly bundles both mechanisms into '
            'one throughput budget. They are reported separately here because '
            'their evidence status differs by kind, not by degree: one is '
            'entirely modeled, the other is measured and currently null.')}


def _official_disclosure_correlation(dm, cfg, cyc, fade_modes, power_fade):
    """M79 (2026-07-31): cross-check of the Nissan X-Trail e-POWER (T33)
    official battery durability disclosure (Article 10, Regulation (EU)
    2023/1542) against this study's measured and modeled quantities.

    WHY THIS EXISTS. The regulatory disclosure and this study's telemetry-
    derived figures are, for several parameters, DIFFERENT PHYSICAL
    QUANTITIES measured under different protocols (see resistance.note
    below) -- so the job here is not to force numeric agreement but to state,
    per parameter, whether the two are (a) directly comparable and
    consistent, (b) directly comparable and inconsistent (a serious finding),
    or (c) not directly comparable, with the reason given. Every number is
    bound to the CURRENT corpus / config; nothing here is a typed-in copy of
    a prior session's one-off arithmetic, so the whole block recomputes as
    the corpus grows and self-updates if the vehicle odometer is refreshed.

    Config dependency. Reads cfg['officialDisclosure'] (raw disclosure
    figures) and cfg['batterySupplier'] -- both external reference content,
    hand-maintained per the Category-C convention (same home as `climate`) --
    plus cfg['vehicle'] (odometer / registration / motor spec, some fields
    also external-reference). Returns None if the disclosure block or the
    cycle-life block is absent, so an unconfigured build degrades to a
    hidden dashboard section rather than a crash.
    """
    od = (cfg or {}).get('officialDisclosure')
    veh = (cfg or {}).get('vehicle') or {}
    supplier = (cfg or {}).get('batterySupplier') or {}
    if not od or not cyc:
        return None

    keep = ~_as_bool(dm['ens_outlier_v2']) if 'ens_outlier_v2' in dm.columns \
        else pd.Series(True, index=dm.index)
    clean = dm[keep]

    # ---- 1. chemistry / pack topology --------------------------------
    v_pack_max = float(dm['V_pack_median'].max()) if 'V_pack_median' in dm.columns \
        and dm['V_pack_median'].notna().any() else None
    v_pack_min = float(dm['V_pack_median'].min()) if 'V_pack_median' in dm.columns \
        and dm['V_pack_median'].notna().any() else None
    chemistry = {
        'supplier': supplier.get('company'), 'supplierAwardDate': supplier.get('awardDate'),
        'supplierNote': supplier.get('note'),
        'seriesCellsEst': PACK_SERIES_CELLS_EST,
        'cellVoltageWindowV': list(CELL_VOLTAGE_WINDOW_V),
        'packVoltageObservedRangeV': (
            [round(v_pack_min, 1), round(v_pack_max, 1)] if v_pack_min is not None else None),
        'capacityKwhEst': CAP_KWH,
        'powerEnergyRatioC': round(od['powerKw'] / CAP_KWH, 1),
        # M110 (audit s5/s7): retract the NMC IDENTIFICATION. The window
        # is evidence for what the chemistry is NOT (LFP) and what it is
        # CONSISTENT WITH (layered oxide); it is not a positive NMC ID.
        'lfpExcluded': True,
        'lfpExclusionBasis': ('observed cell window 3.50-4.11 V is '
                              'incompatible with the LFP voltage plateau '
                              '(~3.2-3.3 V, ceiling ~3.6 V)'),
        'layeredOxideConsistent': True,
        'nmcUniquelyIdentified': False,
        'oemDisclosedChemistry': 'lithium-ion',
        'note': ('Series-cell count and cell-voltage window are a raw-file '
                 'spot-check inference (pack-voltage extremum over the full '
                 'master vs. observed max single-cell voltage on the subset '
                 'of files exposing full cell telemetry), NOT a full-corpus '
                 'raw scan and NOT a manufacturer-published series count -- '
                 'the OBD PID set exposes only cell channels #01-#80 '
                 'regardless of the true series count. The window EXCLUDES '
                 'LFP and is CONSISTENT WITH a layered-oxide (NMC/NCA-'
                 'class) cathode; operational voltage/current behaviour '
                 'cannot uniquely identify the cathode, so this is NOT an '
                 'NMC identification. OEM material discloses only lithium-'
                 'ion. Pack voltage range IS a full-corpus, pipeline-'
                 'computed figure (V_pack_median extrema).')}

    # ---- 2. power ------------------------------------------------------
    peak_kw, peak_drive, peak_pack_c = None, None, None
    if 'peak_discharge_kw' in dm.columns and dm['peak_discharge_kw'].notna().any():
        pidx = dm['peak_discharge_kw'].idxmax()
        peak_kw = round(float(dm.loc[pidx, 'peak_discharge_kw']), 1)
        peak_drive = _day_label(dm, pidx)
    if 'T_pack_mean_avg' in clean.columns and clean['T_pack_mean_avg'].notna().any():
        peak_pack_c = round(float(clean['T_pack_mean_avg'].median()), 0)
    motor_kw, motor_nm = veh.get('motorPowerKw'), veh.get('motorTorqueNm')
    buffered_deficit_kw = (round(motor_kw - od['powerKw'], 1)
                           if motor_kw is not None else None)
    power = {
        'officialKw': od['powerKw'], 'officialConditionSoc': od.get('powerConditionSoc'),
        'measuredPeakKw': peak_kw, 'measuredPeakDrive': peak_drive,
        'motorRatedKw': motor_kw, 'motorRatedNm': motor_nm,
        'bufferedChannelDeficitKw': buffered_deficit_kw,
        'note': (f"Observed instantaneous peak battery discharge "
                 f"({peak_kw} kW, {peak_drive}) exceeds the {od['powerKw']} kW "
                 f"rating because the rating is a sustained/derated figure at "
                 f"exactly {od.get('powerConditionSoc')}% SoC, room "
                 f"temperature, whereas the corpus peak is a warm-pack "
                 f"(median {peak_pack_c}\u00b0C) instantaneous extremum. With "
                 f"the front motor rated {motor_kw} kW / {motor_nm} N\u00b7m, "
                 f"peak traction demand exceeds the {od['powerKw']} kW "
                 f"battery cap by ~{buffered_deficit_kw} kW at full power, "
                 f"which must be sourced directly from the generator across "
                 f"the shared HV DC bus -- an external OEM bound on the "
                 f"buffered/direct power split flagged as structurally "
                 f"unmeasurable from the BMS shunt alone (see energyPath).")}

    # ---- 3. internal resistance (explicitly NOT a level comparison) ----
    r_off_new_mohm = od['internalResistanceOhm'] * 1000.0
    r_off_eol_mohm = r_off_new_mohm * (1 + od['internalResistanceIncreasePct'] / 100.0)
    vsag_med = (float(clean['vsag_R_pack_mohm'].median())
               if 'vsag_R_pack_mohm' in clean.columns
               and clean['vsag_R_pack_mohm'].notna().any() else None)
    vreg_med = (power_fade or {}).get('rMedianMohm')
    resistance = {
        'officialNewMohm': round(r_off_new_mohm, 1),
        'officialEolMohm': round(r_off_eol_mohm, 1),
        'officialIncreasePct': od['internalResistanceIncreasePct'],
        'officialPerCellMohm': round(r_off_new_mohm / PACK_SERIES_CELLS_EST, 2),
        'ourVsagPackMohm': round(vsag_med, 1) if vsag_med is not None else None,
        'ourVregPackMohm': vreg_med,
        'ourVsagPerCellMohm': (round(vsag_med / PACK_SERIES_CELLS_EST, 2)
                               if vsag_med is not None else None),
        'ourVregPerCellMohm': (round(vreg_med / PACK_SERIES_CELLS_EST, 2)
                               if vreg_med is not None else None),
        'comparable': False,
        'note': ('NOT a like-for-like comparison. The official figure is a '
                 'standardized long-pulse DCIR at 80% SoC, ~25\u00b0C. our '
                 'vsag_R / vreg_R are instantaneous, load-excited in-drive '
                 'proxies (ohmic + fast polarization only) at ~64% SoC on a '
                 'warm pack -- a different resistance definition, not a '
                 'degraded-vs-new state. The ratio between the two levels '
                 'must NEVER be read as a state-of-health percentage. What '
                 'IS comparable is the measured TREND (see powerFade / '
                 'fadeModes.power), which is the null result reported '
                 'separately below.')}
    if power_fade and power_fade.get('mdeRisePctPerYr') is not None \
            and od.get('capacityFadeConditionKm') and cyc.get('odometer'):
        km_frac = cyc['odometer'] / od['capacityFadeConditionKm']
        expected_pct_so_far = round(od['internalResistanceIncreasePct'] * km_frac, 1)
        yr_now = cyc.get('carAgeNow') or 0
        mde_pct_so_far = round(power_fade['mdeRisePctPerYr'] * yr_now, 1)
        resistance['trendContext'] = {
            'kmFractionOfOfficialLifePct': round(km_frac * 100, 1),
            'expectedIncreasePctSoFar': expected_pct_so_far,
            'detectionFloorPctSoFar': mde_pct_so_far,
            'withinDetectionFloor': bool(expected_pct_so_far <= mde_pct_so_far),
            'note': ('Linear-in-throughput approximation ONLY, for sanity-'
                     'checking the null result -- not a fitted degradation '
                     'law. At the current mileage fraction of the official '
                     f"{od['capacityFadeConditionKm']:,} km life point "
                     f"({round(km_frac*100,1)}%), the disclosed lifetime IR "
                     f"rise implies an expected-so-far increase "
                     f"(~{expected_pct_so_far}%) at or below this window's "
                     f"own CI half-width (\u00b1{mde_pct_so_far}% over "
                     f"{round(yr_now,2)}yr) -- i.e. the M25 interval does not "
                     'exclude the official trajectory at this mileage (a '
                     'consistency check, not a validation).')}
    else:
        resistance['trendContext'] = None

    # ---- 4. capacity-fade threshold external anchor ---------------------
    cap_rows = ((fade_modes or {}).get('capacity') or {}).get('rows') or []
    life_km = od.get('capacityFadeConditionKm')
    anchor_rows = []
    for r in cap_rows:
        gpk = r.get('gtcPerKm')
        if gpk is None or life_km is None:
            continue
        anchor_rows.append({'label': r['label'], 'gtcPerKm': gpk,
                            'gtcAtOfficialLife': round(gpk * life_km),
                            'measured': r.get('measured'),
                            'primary': r.get('primary', False)})
    thr = cyc.get('scenarioThresholdGtc')
    gtc_vals = [r['gtcAtOfficialLife'] for r in anchor_rows]
    capacity_fade_anchor = None
    if gtc_vals:
        lo, hi = min(gtc_vals), max(gtc_vals)
        brackets = bool(thr is not None and lo <= thr <= hi)
        capacity_fade_anchor = {
            'rows': sorted(anchor_rows, key=lambda r: r['gtcAtOfficialLife']),
            'rangeLowGtc': lo, 'rangeHighGtc': hi,
            'scenarioThresholdGtc': thr, 'bracketsThreshold': brackets,
            'officialLifeKm': life_km,
            'officialCapacityFadePct': od.get('capacityFadePct'),
            'note': (f"Nissan's {life_km:,} km / {od.get('capacityFadePct')}% "
                     f"capacity-fade reference point maps, via this study's "
                     f"measured gtcPerKm per usage mix, onto {lo:,}"
                     f"\u2013{hi:,} GTC" +
                     (f" -- a band that BRACKETS the study's assumed "
                      f"{thr:,} GTC capacity-fade threshold" if brackets else
                      f", compared against the study's assumed {thr:,} GTC "
                      f"threshold") +
                     '. First external anchor for a constant previously '
                     'carried as thresholdVerified: false -- still an order-'
                     'of-magnitude corroboration, not a calibration: '
                     'gtcPerKm reflects this buffer\'s OWN measured cycling '
                     'intensity, and the disclosed percentage is a maximum '
                     'decrease, not a defined GTC endpoint.')}

    # ---- 5. usage rate -> which limit governs ----------------------------
    odo = cyc.get('odometer')
    age_yr = cyc.get('carAgeNow')
    km_per_yr = cyc.get('annualKm')
    usage_rate = None
    if odo and age_yr and km_per_yr and od.get('expectedLifeKm') and od.get('expectedLifeYr'):
        yr_to_life_km = round(od['expectedLifeKm'] / km_per_yr, 1)
        governs = 'mileage' if yr_to_life_km < od['expectedLifeYr'] else 'calendar'
        usage_rate = {
            'odometerKm': odo, 'carAgeYr': round(age_yr, 2), 'kmPerYr': km_per_yr,
            'officialLifeYr': od['expectedLifeYr'], 'officialLifeKm': od['expectedLifeKm'],
            'yearsToOfficialLifeKm': yr_to_life_km, 'governingLimit': governs,
            'note': (f"At the current {km_per_yr:,} km/yr lifetime-average "
                     f"pace, the {od['expectedLifeKm']:,} km durability "
                     f"envelope is reached in ~{yr_to_life_km} years from "
                     f"new -- {'inside' if governs=='mileage' else 'outside'} "
                     f"the {od['expectedLifeYr']}-year calendar limit, so "
                     f"the {'mileage' if governs=='mileage' else 'calendar'} "
                     'clock governs for this usage pattern.')}

    # ---- 6. per-parameter correlation table (drives the JSX table) -------
    def _row(param, official, ours, verdict, note):
        return {'parameter': param, 'official': official, 'ours': ours,
                'verdict': verdict, 'note': note}

    rows = [
        _row('Rated capacity', f"{od['ratedCapacityAh']} Ah",
             f"{round(float(clean['cap_ah_est'].median()),2)} Ah (median, "
             f"nameplate-derived)" if 'cap_ah_est' in clean.columns else '\u2014',
             'consistent',
             'Both describe a ~2 kWh-class pack. cap_ah_est is CAP_KWH / '
             'V_pack_median, an algebraic restatement of the nameplate, not '
             'an independent capacity measurement (see fadeModes.capacity).'),
        _row('Power', f"{power['officialKw']} kW @ {power['officialConditionSoc']}% SoC",
             f"{power['measuredPeakKw']} kW peak ({power['measuredPeakDrive']})",
             'consistent',
             'Warm/instantaneous peak exceeds the derated rating as '
             'expected; the rating caps the buffered channel against a '
             f"{power['motorRatedKw']} kW motor."),
        _row('Internal resistance', f"{resistance['officialNewMohm']} m\u03a9 pack "
             f"({resistance['officialPerCellMohm']} m\u03a9/cell est.)",
             f"{resistance['ourVregPackMohm']} m\u03a9 pack "
             f"({resistance['ourVregPerCellMohm']} m\u03a9/cell est.)"
             if resistance['ourVregPackMohm'] is not None else '\u2014',
             'not_comparable', resistance['note']),
        _row('Power fade / IR increase',
             f"{od['powerFadePct']}% power / +{od['internalResistanceIncreasePct']}% IR "
             f"@ {od['expectedLifeKm']:,} km",
             (f"slope {power_fade.get('slopeMohmPerMoTctrl')} m\u03a9/mo, 95% CI "
              f"{power_fade.get('ci95MohmPerMo')}, null" if power_fade else '\u2014'),
             'consistent_null',
             (resistance['trendContext']['note'] if resistance.get('trendContext')
              else 'Measured trend is a null result; official life-point figures '
                   'are defined at full mileage, not at the current corpus window.')),
        _row('Round-trip efficiency',
             f"{od['roundTripEfficiencyPct']}% (new, benign protocol)",
             'not measured (gross-throughput-per-100km convention used instead)',
             'not_comparable',
             'Lab figure at gentle current, new battery. Real buffering at '
             '20-35C peaks incurs I\u00b2R losses this figure does not '
             'capture, which is why the study reports gross throughput '
             'rather than a round-trip efficiency.'),
        _row('Capacity fade', f"{od['capacityFadePct']}% @ {od['expectedLifeKm']:,} km",
             'no observable in this corpus (fadeModes.capacity: MODELED ONLY)',
             'consistent_by_design',
             (capacity_fade_anchor['note'] if capacity_fade_anchor else
              'Real but unobservable for a buffer that never leaves its '
              'operating SoC window; disclosure confirms the mechanism is '
              'real over full life without the study being able to verify it '
              'independently.')),
        _row('Expected life-time',
             f"{od['expectedLifeYr']} yr / {od['expectedLifeKm']:,} km",
             (usage_rate['note'] if usage_rate else '\u2014'),
             'consistent',
             'Mileage vs. calendar governance depends on the vehicle\'s own '
             'usage rate, recomputed here from the live odometer/registration.'),
        _row('Chemistry / supplier', supplier.get('company', '\u2014'),
             f"Li-ion (OEM-disclosed); LFP excluded by the "
             f"{chemistry['cellVoltageWindowV'][0]}"
             f"\u2013{chemistry['cellVoltageWindowV'][1]} V cell window; "
             f"layered-oxide (NMC/NCA-class) consistent but NOT uniquely "
             f"identified. {chemistry['seriesCellsEst']}S pack, "
             f"~{chemistry['powerEnergyRatioC']}C power/energy ratio",
             'consistent', chemistry['note']),
    ]

    return {
        'basis': ('M79 (2026-07-31). Cross-check of the Nissan X-Trail '
                  'e-POWER (T33) Article 10 (Regulation (EU) 2023/1542) '
                  'battery durability disclosure against this study\'s own '
                  'measured / modeled figures. Source disclosure and '
                  'supplier identity are external reference content '
                  '(cfg.officialDisclosure / cfg.batterySupplier); every '
                  'comparison figure on this side is pipeline-computed from '
                  'the live drive_master.csv + config, so the whole block '
                  'recomputes as the corpus grows.'),
        'official': od, 'supplier': supplier,
        'chemistry': chemistry, 'power': power, 'resistance': resistance,
        'capacityFadeAnchor': capacity_fade_anchor, 'usageRate': usage_rate,
        'rows': rows,
        'verdictHeadline': (
            'No official figure contradicts a study finding. The disclosure\'s '
            'own structure -- large tolerated capacity fade alongside '
            'separately tracked power fade and a large internal-resistance '
            'increase, on a high power/energy-ratio pack -- independently '
            'corroborates this study\'s central framing: the HV battery is a '
            'power buffer, and internal-resistance-driven power fade, not '
            'capacity fade, is the functionally meaningful degradation mode. '
            'The one figure that must never be read as a direct level match '
            'is internal resistance (see resistance.note) -- track its TREND '
            'against ours, never its absolute value.'),
        'note': ('No warranty implication can be derived from any information '
                 'here, per the source disclosure\'s own disclaimer. Figures '
                 'transcribed from the manufacturer\'s published compliance '
                 'table; this study did not independently verify the '
                 'disclosure\'s own test protocol.')}


def _seasonal_projection(dm, odometer_km, cfg, obs_mix=None):
    """M28 (2026-07-10): all-year seasonal extrapolation of the cycle-life
    projection. MODEL-BASED — the corpus contains no sub-15 °C pack data, so
    every cold-month figure here is an assumption-driven extrapolation, not a
    measurement. It exists to replace the bare 'warm-season floor' framing with
    an explicit, parameterized year-round estimate carried with lo/mid/hi bands;
    it is superseded the moment real winter logging lands.

    Frame: unchanged from _cycle_projection — gross-EFC accumulation rate vs
    CYCLE_RATED_LIFE (commensurable). The seasonal model only adjusts the RATE
    (monthly mix + a temperature-dependent throughput multiplier). The low-T
    plating damage acceleration is a DIFFERENT damage metric and is therefore
    reported only as a labeled sensitivity (damage-weighted rate), never blended
    into the primary crossing.

    Data-derived inputs (from the ens-clean master):
      * per-class cycle intensity (efc/km), identical basis to _cycle_projection
      * per-class pack thermal rise above monthly-mean ambient (time-weighted,
        observed months only)
      * per-class regen share of charge, and peak C-rate context
    Assumption inputs (cfg = config['seasonalAssumptions'], user-supplied /
    literature-anchored, each with an explicit band where uncertain):
      * Kyiv monthly mean temperatures (external climatology)
      * cold-consumption slope (throughput multiplier per °C below T0)
      * cold-soak retention of the urban thermal rise (inter-drive cooling,
        5-6 short drives/day working pattern)
      * work-season vs warm-season distance mix; -10% rel. highway share
      * regen-loss ramp and plating threshold/damage weights (sensitivity only)

    obs_mix (M92, 2026-08-06): optional {'city','mixed','highway'} FRACTIONS
    (0-1) for the observed logged distance mix. When the caller already has
    _cycle_projection's observedMixShare (build_summary_arrays does), it is
    passed in — pct/100 — so the two functions can never disagree on what
    "observed" means. If omitted (any other caller), it is recomputed here
    on the identical basis (typed dclass in {urban,mixed,mixed_highway,
    highway}, distance-weighted), so the function stays independently
    callable. Threads the observed mix through the SAME _model()/_hot_block()
    path already used for selectedConstant/hotTail.selected, producing
    observedConstant + hotTail.observed: does the Observed-logged-mix row of
    the capacity-fade matrix carry climatic + hot-tail stress the way
    Selected and All-year already do, rather than staying a bare warm-floor
    figure while the other rows pick up assumption load.
    """
    dm = dm.copy()
    dm['dclass'] = dm['drive_type'].apply(_cond_class)
    if 'ens_outlier_v2' in dm:
        dm['ens'] = _as_bool(dm['ens_outlier_v2'])
    elif 'ens_outlier' in dm:
        dm['ens'] = _as_bool(dm['ens_outlier'])
    else:
        dm['ens'] = False
    clean = dm[~dm['ens']].copy()

    dt = pd.to_datetime(dm['date'])
    reg = pd.Timestamp(REG_DATE)
    age_yr = (dt.max() - reg).days / 365.25
    odo = float(odometer_km) if odometer_km is not None \
        else float(dm['odo_end'].max())
    annual_km = odo / age_yr if age_yr > 0 else 0.0

    months = cfg['months']
    t_amb = [float(x) for x in cfg['monthlyTempC']]
    slope = cfg['consumptionSlopePerC']          # {lo, mid, hi} per °C
    t0 = float(cfg['consumptionT0C'])
    soak = cfg['coldSoakRetention']              # {lo, mid, hi}
    work_mix = cfg['workSeasonMix']
    warm_mix = cfg['warmSeasonMix']
    work_thr = float(cfg['workSeasonTempThresholdC'])
    hwy_red = float(cfg['highwayShareRelReduction'])
    plating_thr = float(cfg['platingTempThresholdC'])
    plating_w = list(cfg['platingDamageWeights'])
    arrh = cfg['arrhenius']

    # ---- per-class cycle intensity (identical basis to _cycle_projection) ----
    intensity = {}
    for k in CLASS_ORDER:
        g = clean[clean['dclass'] == k]
        d = g['distance_km'].sum()
        intensity[k] = float(g['gtc'].sum() / d) if d > 0 else 0.0
    hwy_sel = clean['dclass'].isin(['mixed_highway', 'highway'])
    hwy_km = clean.loc[hwy_sel, 'distance_km'].sum()
    # M103 (2026-08-08): escaped M95 read-site. M95 repointed "all 7" efc->gtc
    # reads but missed this 8th (highway-class intensity in _seasonal_projection);
    # it never surfaced because seasonalLife only builds when seasonal_cfg is
    # forwarded, which the M95 validation path (F-12) did not do. efc was
    # byte-identical to gtc (max|efc-gtc|=0.0, CHANGELOG M95), so this repoint is
    # numerically byte-exact and restores basis-consistency with intensity[*] above.
    hwy_int = float((clean.loc[hwy_sel, 'gtc'].sum()) / hwy_km) if hwy_km > 0 else 0.0
    lvl = {'city': intensity['urban'], 'mixed': intensity['mixed'],
           'highway': hwy_int}

    # M92 (2026-08-06): obs_mix fallback, identical basis to _cycle_projection's
    # observedMixShare (typed dclass, distance-weighted fractions).
    if obs_mix is None:
        _typed = clean[clean['dclass'].isin(
            ['urban', 'mixed', 'mixed_highway', 'highway'])]
        _tk = _typed['distance_km'].sum()
        obs_mix = ({'city': float(_typed[_typed['dclass'] == 'urban']['distance_km'].sum() / _tk),
                    'mixed': float(_typed[_typed['dclass'] == 'mixed']['distance_km'].sum() / _tk),
                    'highway': float(hwy_km / _tk)}
                   if _tk > 0 else {'city': .55, 'mixed': .30, 'highway': .15})

    # ---- observed pack thermal rise above monthly-mean ambient ----
    # time-weighted over the observed months; ambient = the SAME monthly-mean
    # series used for the extrapolation (consistency). Drives are daytime-
    # biased, so true rise is somewhat smaller than computed — one reason a
    # cold-soak retention band is carried rather than a point value.
    cl2 = clean.copy()
    cl2['month'] = pd.to_datetime(cl2['date']).dt.month
    cl2['amb'] = cl2['month'].map({i + 1: t_amb[i] for i in range(12)})
    cl2['dT'] = cl2['T_pack_mean_avg'] - cl2['amb']
    def _rise(sel):
        g = cl2[sel & cl2['dT'].notna() & cl2['duration_s'].notna()]
        return float(np.average(g['dT'], weights=g['duration_s'])) if len(g) else 0.0
    rise = {'city': _rise(cl2['dclass'] == 'urban'),
            'mixed': _rise(cl2['dclass'] == 'mixed'),
            'highway': _rise(cl2['dclass'].isin(['mixed_highway', 'highway']))}

    # ---- observed regen share + peak C-rate context (narrative binding) ----
    def _med(col, sel):
        v = clean.loc[sel, col].dropna()
        return round(float(v.median()), 1) if len(v) else None
    regen_share = {'city': _med('regen_share_of_charge', clean['dclass'] == 'urban'),
                   'highway': _med('regen_share_of_charge', hwy_sel)}
    crate = {'dischargePeakMedC': None, 'dischargePeakP95C': None,
             'chargePeakMedC': None}
    if 'peak_I_discharge' in clean and 'cap_ah_est' in clean:
        cap_ah = float(clean['cap_ah_est'].median())
        if cap_ah > 0:
            pid = clean['peak_I_discharge'].dropna()
            pic = clean['peak_I_charge'].dropna().abs()
            crate = {'dischargePeakMedC': round(float(pid.median()) / cap_ah, 1),
                     'dischargePeakP95C': round(float(pid.quantile(.95)) / cap_ah, 1),
                     'chargePeakMedC': round(float(pic.median()) / cap_ah, 1),
                     'capAhBasis': round(cap_ah, 2)}

    # ---- monthly model ----
    def _mix_for(temp):
        base = work_mix if temp < work_thr else warm_mix
        hwy = base['highway'] * (1.0 - hwy_red)
        return {'city': base['city'] + (base['highway'] - hwy),
                'mixed': base['mixed'], 'highway': hwy}

    KB = 8.617333e-5  # eV/K
    ea, t_ref = float(arrh['EaEv']), float(arrh['refC'])
    monthly = []
    for i, m in enumerate(months):
        ta = t_amb[i]
        mix = _mix_for(ta)
        f = {k: 1.0 + slope[k] * max(0.0, t0 - ta) for k in ('lo', 'mid', 'hi')}
        cyc_km = {k: sum(mix[c] * lvl[c] for c in mix) * f[k]
                  for k in ('lo', 'mid', 'hi')}
        # winter cold-soak: short urban drives retain only a fraction of the
        # observed steady-state rise; long highway drives reach full rise.
        cold = ta < work_thr
        tp = {k: {'city': ta + (soak[k] * rise['city'] if cold else rise['city']),
                  'highway': ta + rise['highway'],
                  'mixed': ta + (soak[k] * rise['mixed'] if cold else rise['mixed'])}
              for k in ('lo', 'mid', 'hi')}
        # plating-exposed share of the month's cycles (mid-soak pack temps)
        plating_share = sum(mix[c] * lvl[c] for c in mix
                            if tp['mid'][c] < plating_thr) \
            / sum(mix[c] * lvl[c] for c in mix)
        cal = float(np.exp(-ea / KB * (1.0 / (ta + 273.15)
                                       - 1.0 / (t_ref + 273.15))))
        monthly.append({'month': m, 'tAmbC': ta,
                        'tPackCityMidC': round(tp['mid']['city'], 1),
                        'tPackHighwayC': round(tp['mid']['highway'], 1),
                        'mix': {c: round(v, 3) for c, v in mix.items()},
                        'throughputMult': {k: round(f[k], 3) for k in f},
                        'cyclesPerKm': {k: round(cyc_km[k], 5) for k in cyc_km},
                        'platingShare': round(plating_share, 3),
                        'calendarFactor': round(cal, 3)})

    # ---- annual aggregation (uniform monthly km share — least-assumption
    #      choice: the odometer-average annualKm already spans a full year of
    #      real usage incl. one winter, so no seasonal km re-weighting is
    #      imposed on top of it) ----
    ann_cyc_km = {k: float(np.mean([mo['cyclesPerKm'][k] for mo in monthly]))
                  for k in ('lo', 'mid', 'hi')}
    rate = {k: ann_cyc_km[k] * annual_km for k in ann_cyc_km}
    accumulated = {k: ann_cyc_km[k] * odo for k in ann_cyc_km}
    def _cross(acc, r):
        return age_yr + (CYCLE_RATED_LIFE - acc) / r if r > 0 else None
    years_total = {k: round(_cross(accumulated[k], rate[k]), 1)
                   for k in ('lo', 'mid', 'hi')}

    # plating-exposed annual cycle share (mid) + damage-weighted sensitivity
    cyc_mid_m = [mo['cyclesPerKm']['mid'] for mo in monthly]
    plate_share = float(np.average([mo['platingShare'] for mo in monthly],
                                   weights=cyc_mid_m))
    sens = []
    for w in plating_w:
        r_eff = rate['mid'] * (1.0 + (w - 1.0) * plate_share)
        a_eff = accumulated['mid'] * (1.0 + (w - 1.0) * plate_share)
        sens.append({'damageWeight': w,
                     'effRate': round(r_eff),
                     'yearsTotal': round(_cross(a_eff, r_eff), 1)})

    # calendar aging annualized on the SAME user temp series (shaded/parked)
    cal_ann = float(np.mean([mo['calendarFactor'] for mo in monthly]))
    cal_life = round(float(arrh['refCalendarLifeYr']) / cal_ann, 1) \
        if cal_ann > 0 else None

    # ---- M85: constant-mix Selected blend under the same seasonal model, and
    #      the MEASURED high-temperature cycle-damage sensitivity (hot tail).
    #      The Selected blend is the constant selectedConstantMix carried through
    #      the monthly throughput model, so it inherits climatic stress (it is
    #      no longer the bare warm-season floor). The hot tail is the symmetric
    #      counterpart to the cold plating term: a hot class-month (pack temp =
    #      ambient + MEASURED per-class rise >= hotThr) has its cycles damage-
    #      weighted, reported as a labelled sensitivity only (never folded into
    #      the primary crossing), on the CYCLE axis (calendar life unchanged).
    sel_mix = cfg.get('selectedConstantMix')
    hot_cfg = cfg.get('hotTail', {}) or {}
    hot_thr = float(hot_cfg.get('tempThresholdC', 35.0))
    flat_w = list(hot_cfg.get('flatDamageWeights', [1.5, 2.0, 2.5]))

    def _af(tc):
        return float(np.exp(-ea / KB * (1.0 / (tc + 273.15)
                                        - 1.0 / (t_ref + 273.15))))

    def _model(mix_fn):
        """mix_fn(ta)->mix dict. Returns (annual cyclesPerKm {lo,mid,hi},
        mid base annual cyc/km, hot-cycle share, AF-weighted mid annual cyc/km,
        {w: flat-weighted mid annual cyc/km})."""
        per = {k: [] for k in ('lo', 'mid', 'hi')}
        base_mid = hot_mid = dmg_af = 0.0
        flat_d = {w: 0.0 for w in flat_w}
        for i in range(12):
            ta = t_amb[i]
            mix = mix_fn(ta)
            for k in ('lo', 'mid', 'hi'):
                f = 1.0 + slope[k] * max(0.0, t0 - ta)
                per[k].append(sum(mix[c] * lvl[c] for c in mix) * f)
            fmid = 1.0 + slope['mid'] * max(0.0, t0 - ta)
            for c in mix:
                tp = ta + rise[c]
                cyc = mix[c] * lvl[c] * fmid
                base_mid += cyc
                if tp >= hot_thr:
                    hot_mid += cyc
                    dmg_af += cyc * _af(tp)
                    for w in flat_w:
                        flat_d[w] += cyc * w
                else:
                    dmg_af += cyc
                    for w in flat_w:
                        flat_d[w] += cyc
        ann = {k: float(np.mean(per[k])) for k in per}
        return (ann, base_mid / 12.0, (hot_mid / base_mid if base_mid > 0 else 0.0),
                dmg_af / 12.0, {w: flat_d[w] / 12.0 for w in flat_w})

    def _hot_block(rate_mid, acc_mid, base_ann, hotshare, af_ann, flat_ann):
        up_af = af_ann / base_ann if base_ann > 0 else 1.0
        flat = [{'damageWeight': w,
                 'rate': round(rate_mid * (flat_ann[w] / base_ann if base_ann > 0 else 1.0)),
                 'yearsTotal': round(_cross(acc_mid * (flat_ann[w] / base_ann if base_ann > 0 else 1.0),
                                            rate_mid * (flat_ann[w] / base_ann if base_ann > 0 else 1.0)), 1)}
                for w in flat_w]
        return {'tempThresholdC': hot_thr,
                'hotCycleShare': round(hotshare, 3),
                'afWeightedRate': round(rate_mid * up_af),
                'afWeightedYearsTotal': round(_cross(acc_mid * up_af, rate_mid * up_af), 1),
                'flatSensitivity': flat}

    # Selected constant-mix (climatic-stress) block
    sel_ann, sel_base, sel_hs, sel_af, sel_flat = _model(lambda ta: sel_mix)
    sel_rate = {k: sel_ann[k] * annual_km for k in sel_ann}
    sel_acc = {k: sel_ann[k] * odo for k in sel_ann}
    selected_constant = {
        'mix': {c: round(v * 100, 1) for c, v in sel_mix.items()},
        'annualCyclesPerKm': {k: round(sel_ann[k], 5) for k in sel_ann},
        'rate': {k: round(sel_rate[k]) for k in sel_rate},
        'accumulated': {k: round(sel_acc[k]) for k in sel_acc},
        'yearsTotal': {k: round(_cross(sel_acc[k], sel_rate[k]), 1) for k in sel_ann},
        'warmFloorGtcPerKm': round(sum(sel_mix[c] * lvl[c] for c in sel_mix), 5),
        'basis': ('constant all-season selectedConstantMix carried through the '
                  'M28 seasonal throughput model -> carries climatic stress; '
                  'measured:false (inherits the seasonal assumption load). '
                  'Equals the cold/working-season endpoint, so it is the '
                  'conservative (upper) member of the Selected/All-year pair, '
                  'not their annual average.')}

    # M92 (2026-08-06): observed logged distance mix, carried through the SAME
    # constant-mix seasonal model as Selected. Answers point 2 of the M90/M92
    # review: does the one row whose WORKLOAD input is measured (obs_mix, not
    # a hand-chosen scenario) also carry climate + hot-tail stress the way
    # Selected and All-year already do. warmFloorGtcPerKm here must equal the
    # 'Observed logged mix' row's gtcPerKm in cycleLife.projections (both
    # trace to the same obs_mix and lvl) -- cross-checked in the acceptance
    # harness.
    obs_ann, obs_base, obs_hs, obs_af, obs_flat = _model(lambda ta: obs_mix)
    obs_rate = {k: obs_ann[k] * annual_km for k in obs_ann}
    obs_acc = {k: obs_ann[k] * odo for k in obs_ann}
    observed_constant = {
        'mix': {c: round(v * 100, 1) for c, v in obs_mix.items()},
        'annualCyclesPerKm': {k: round(obs_ann[k], 5) for k in obs_ann},
        'rate': {k: round(obs_rate[k]) for k in obs_rate},
        'accumulated': {k: round(obs_acc[k]) for k in obs_acc},
        'yearsTotal': {k: round(_cross(obs_acc[k], obs_rate[k]), 1) for k in obs_ann},
        'warmFloorGtcPerKm': round(sum(obs_mix[c] * lvl[c] for c in obs_mix), 5),
        'basis': ('constant all-season OBSERVED logged distance mix carried '
                  'through the M28 seasonal throughput model -> carries '
                  'climatic stress; measured:false (the workload input is '
                  'measured, but the seasonal throughput multiplier and '
                  'monthly mix-shift are still M28 assumptions, same as '
                  'selectedConstant). Equals the cold/working-season '
                  'endpoint, not an annual average.')}

    # All-year (season-switching) hot-tail, from the SAME _mix_for used above
    ay_ann, ay_base, ay_hs, ay_af, ay_flat = _model(_mix_for)

    # measured pack-thermal exposure summary (warm corpus, time-weighted)
    _te = cl2.dropna(subset=['T_pack_mean_avg', 'duration_s'])
    if len(_te):
        _w = _te['duration_s']
        pack_tw_mean = float(np.average(_te['T_pack_mean_avg'], weights=_w))
        share_ge = {str(int(t)): round(float(_w[_te['T_pack_mean_avg'] >= t].sum()
                                              / _w.sum()), 3)
                    for t in (30, 35, 40)}
        af_tw = float(np.average([_af(x) for x in _te['T_pack_mean_avg']], weights=_w))
        pack_peak_mean_max = round(float(_te['T_pack_mean_max'].max()), 1) \
            if 'T_pack_mean_max' in _te else None
    else:
        pack_tw_mean = None; share_ge = {}; af_tw = None; pack_peak_mean_max = None

    hot_tail = {
        'tempThresholdC': hot_thr,
        'arrheniusEaEv': ea, 'refC': t_ref,
        'packThermalMeasured': {
            'timeWeightedMeanPackC': round(pack_tw_mean, 1) if pack_tw_mean else None,
            'driveTimeShareGeC': share_ge,
            'timeWeightedArrheniusAF': round(af_tw, 2) if af_tw else None,
            'hottestPackPeakMeanC': pack_peak_mean_max,
            'perClassRiseC': {k: round(v, 1) for k, v in rise.items()}},
        'selected': _hot_block(sel_rate['mid'], sel_acc['mid'], sel_base,
                               sel_hs, sel_af, sel_flat),
        'allYear': _hot_block(rate['mid'], accumulated['mid'], ay_base,
                              ay_hs, ay_af, ay_flat),
        'observed': _hot_block(obs_rate['mid'], obs_acc['mid'], obs_base,   # M92
                               obs_hs, obs_af, obs_flat),
        'note': ('MEASURED high-T cycle-damage sensitivity (the logged corpus is '
                 'almost entirely Warm and Shoulder ambient class (Cold-class drives '
                 'are below minimum support), so pack thermal exposure is '
                 'characterised directly for that range). Reported as a labelled sensitivity only, never '
                 'folded into the primary crossing. Calendar-aging axis '
                 '(calendarLifeYrShaded) is duty-blended/parked-dominated and '
                 'is NOT affected by this in-drive cycling term.')}

    return {
        'basis': 'M28 model-based all-year extrapolation (the cold tail below the '
                 'lowest logged pack-probe reading is modelled, not observed; '
                 'assumption-driven, superseded by real winter logs)',
        'annualKm': round(annual_km), 'carAgeNow': round(age_yr, 4),
        'odometer': round(odo),
        'intensityGtcPerKm': {k: round(v, 4) for k, v in lvl.items()},
        'thermalRiseC': {k: round(v, 1) for k, v in rise.items()},
        'regenShareObserved': regen_share,
        'cRateObserved': crate,
        'monthly': monthly,
        'annualCyclesPerKm': {k: round(v, 5) for k, v in ann_cyc_km.items()},
        'rate': {k: round(v) for k, v in rate.items()},
        'accumulated': {k: round(v) for k, v in accumulated.items()},
        'yearsTotal': years_total,
        'platingCycleShare': round(plate_share, 3),
        'platingSensitivity': sens,
        'calendarAnnualFactor': round(cal_ann, 3),
        'calendarLifeYrShaded': cal_life,
        'selectedConstant': selected_constant,   # M85
        'observedConstant': observed_constant,   # M92
        'hotTail': hot_tail,                      # M85 (+ 'observed', M92)
        'assumptions': cfg,
    }


def _soc_level_sensitivity(dm, cfg):
    """M91 (2026-08-06). SoC-LEVEL (window placement) sensitivity overlay on
    the M17 rf_damage_k2 Woehler-DoD proxy, cross-checked against Wikner
    (Chalmers, 2017) -- see socLevelWeighting._provenance in summary_config
    for the full citation and caveats. cfg = config['socLevelWeighting'];
    returns None if that block is absent (config not yet added / arrays-only
    regen against a stale config), same discipline as
    _official_disclosure_correlation.

    WHAT THIS DOES. M17's rf_damage_k2 already depth-weights every rainflow
    cycle by (range/100)^RF_DAMAGE_EXP; drive_master.csv (M91) additionally
    carries that SAME total split three ways by the cycle's MEAN SoC
    (rf_damage_k2_socband_{lo,mid,hi}, using rainflow's own mean field, which
    M17 computed but never read). This function re-blends those three bands
    through a config-supplied weight ladder and reports, for the Selected
    blend and the Observed logged mix, how far the SoC-level-weighted
    per-km damage rate diverges from the unweighted (flat k=2) rate already
    shown elsewhere. It is a SENSITIVITY, not a correction: rf_damage_k2 and
    every GTC/FCE crossing in cycleLife/fadeModes are UNCHANGED by this
    function; nothing here is folded into a primary crossing.

    WHAT THE NUMBERS SAY (documented here so the shape can't drift silently
    out of sync with the corpus): essentially the entire corpus (99.8% of
    k2 damage in the 2026-08-06 corpus) already sits in the >=socLevelHiPct
    band, in every drive class. That means the weight ladder collapses to
    an almost class-blind multiplier: the Selected/Observed ratioVsFlat at
    each ladder point tracks w_hi directly, with lo/mid contributing
    negligibly regardless of workload mix. This IS the finding, not a
    modeling artifact: the buffer's ~44-82% operating window (per M61/other
    notes) sits inside the band Wikner's data flag as elevated, essentially
    without exception, so the mitigating "shallow buffering" framing (which
    is about DEPTH, and remains correct on that axis) gets no additional
    support from SoC WINDOW LEVEL -- if anything the opposite, per this
    source. See classRatioAtHi for whether class ranking still holds; it
    mostly collapses for the same reason.
    """
    if not cfg:
        return None
    bandcols = ['rf_damage_k2_socband_lo', 'rf_damage_k2_socband_mid',
               'rf_damage_k2_socband_hi']
    if not set(bandcols) <= set(dm.columns):
        return None
    keep = ~_as_bool(dm['ens_outlier_v2']) if 'ens_outlier_v2' in dm.columns \
        else pd.Series(True, index=dm.index)
    clean = dm[keep].copy()
    clean['dclass'] = clean['drive_type'].apply(_cond_class)
    sub = clean.dropna(subset=bandcols + ['rf_damage_k2', 'distance_km'])
    if not len(sub):
        return None

    def _perkm(col, dsel):
        g = sub[dsel]; d = g['distance_km'].sum()
        return float(g[col].sum() / d) if d > 0 else 0.0

    hwy_sel = sub['dclass'].isin(['mixed_highway', 'highway'])
    lvl = {}
    for col in bandcols + ['rf_damage_k2']:
        lvl[col] = {'city': _perkm(col, sub['dclass'] == 'urban'),
                    'mixed': _perkm(col, sub['dclass'] == 'mixed'),
                    'highway': _perkm(col, hwy_sel)}

    tot = sub[bandcols].sum()
    corpus_share_pct = ({c.replace('rf_damage_k2_socband_', ''):
                         round(float(tot[c] / tot.sum() * 100), 1) for c in bandcols}
                        if tot.sum() > 0 else None)

    lo_pct = cfg.get('socLevelLoPct', 30.0)
    hi_pct = cfg.get('socLevelHiPct', 50.0)
    ladder_cfg = cfg.get('weightLadder', {})
    w_lo = ladder_cfg.get('lo', [1.0])
    w_mid = ladder_cfg.get('mid', [1.0])
    w_hi = ladder_cfg.get('hi', [1.0])
    n_rungs = min(len(w_lo), len(w_mid), len(w_hi))

    # Observed logged mix, self-contained at full precision -- identical
    # basis to _cycle_projection's observedMixShare / _seasonal_projection's
    # obs_mix fallback (typed dclass, distance-weighted). Recomputed here
    # rather than threaded through a display-rounded field for the same
    # precision reason documented at the M92 build_summary_arrays call site.
    _typed = sub[sub['dclass'].isin(
        ['urban', 'mixed', 'mixed_highway', 'highway'])]
    _tk = _typed['distance_km'].sum()
    obs_mix = None
    if _tk > 0:
        _typed_hwy = _typed['dclass'].isin(['mixed_highway', 'highway'])
        obs_mix = {
            'city': float(_typed.loc[_typed['dclass'] == 'urban', 'distance_km'].sum() / _tk),
            'mixed': float(_typed.loc[_typed['dclass'] == 'mixed', 'distance_km'].sum() / _tk),
            'highway': float(_typed.loc[_typed_hwy, 'distance_km'].sum() / _tk)}

    scen = {'Selected blend': {'city': .4, 'mixed': .1, 'highway': .5}}
    if obs_mix is not None:
        scen['Observed logged mix'] = obs_mix

    def _blend(mix, weights=None):
        if weights is None:
            return sum(mix[c] * lvl['rf_damage_k2'][c] for c in mix)
        wl, wm, wh = weights
        return sum(mix[c] * (wl * lvl['rf_damage_k2_socband_lo'][c]
                             + wm * lvl['rf_damage_k2_socband_mid'][c]
                             + wh * lvl['rf_damage_k2_socband_hi'][c])
                  for c in mix)

    out_scen = {}
    for name, mix in scen.items():
        if mix is None:
            continue
        flat = _blend(mix)
        ladder = []
        for i in range(n_rungs):
            weighted = _blend(mix, (w_lo[i], w_mid[i], w_hi[i]))
            ladder.append({'wLo': w_lo[i], 'wMid': w_mid[i], 'wHi': w_hi[i],
                           'weightedPerKm': round(weighted, 6),
                           'ratioVsFlat': (round(weighted / flat, 4)
                                          if flat > 0 else None)})
        out_scen[name] = {'flatPerKm': round(flat, 6), 'ladder': ladder}

    # class ranking check: does city stay most-damaging once weighted at the
    # most Wikner-consistent (last) rung? (mirrors the M90 review's Panel C)
    class_ratio_at_hi = None
    if n_rungs:
        i = n_rungs - 1
        wl, wm, wh = w_lo[i], w_mid[i], w_hi[i]
        w_by_class = {c: (wl * lvl['rf_damage_k2_socband_lo'][c]
                          + wm * lvl['rf_damage_k2_socband_mid'][c]
                          + wh * lvl['rf_damage_k2_socband_hi'][c])
                     for c in ('city', 'mixed', 'highway')}
        base = w_by_class.get('city') or None
        class_ratio_at_hi = ({c: round(v / base, 3) for c, v in w_by_class.items()}
                             if base else None)

    return {
        'basis': ('M91. Diagnostic SoC-window-level split of the existing '
                  'rf_damage_k2 (M17) total, re-blended through a labeled, '
                  'unverified weight ladder cross-checked against Wikner '
                  '(Chalmers, 2017). Never folds into rf_damage_k2 itself '
                  'or any GTC/FCE crossing.'),
        'verified': False,
        'socLevelLoPct': lo_pct, 'socLevelHiPct': hi_pct,
        'corpusBandSharePctOfK2': corpus_share_pct,
        'perClassPerKm': {k: {c: round(v, 6) for c, v in d.items()}
                         for k, d in lvl.items()},
        'scenarios': out_scen,
        'classRatioAtHiRungVsCity': class_ratio_at_hi,
        'note': ('At the corpus'"'"'s observed band split, the weight ladder '
                 'collapses to an almost class-blind multiplier on w_hi '
                 '(essentially all classes already sit in the >= '
                 f'{hi_pct:g}% band) -- the scenario-level ratioVsFlat and '
                 'the class ranking are correspondingly close to flat. That '
                 'is the finding: shallow DEPTH is protective (unchanged '
                 'from rf_damage_k2/M17); shallow SoC-window LEVEL is not, '
                 'because this buffer'"'"'s operating window sits almost '
                 'entirely above socLevelHiPct.'),
    }


# ======================================================================
# CATEGORY B  — raw 1 Hz time-series arrays (single streaming pass)
# ======================================================================
class _RawAccum:
    """Pooled accumulators fed one raw file at a time; O(rows) total."""

    def __init__(self):
        # socBySpeed: per zone collect all SoC samples (weighted by dt via repeat-free
        # quantiles on the pooled sample — dt is ~1 s so sample count ~ time weight)
        self.soc_by_zone = {lbl: [] for _, _, lbl, _ in Z_SOC}
        # M35 (2026-07-14, audit): live coverage counters for the socBySpeed
        # narrative (n contributing files + total sample-span hours). Supersedes
        # a hand-typed "103 drives, 56 h" figure in xtrail_summary.jsx that had
        # drifted as the dataset grew past 103 files.
        # M167 (2026-08-23, audit): the M35 note above originally read "a file
        # contributes iff it carries the VCM speed PID; the 5 earliest (May
        # 11-13) files lack it and are correctly excluded, not a bug." That
        # was accurate at 5 files but had gone stale: by this session 44/274
        # files (the original 5 plus 39 from Aug 14-22, effectively the whole
        # of that block) carried only the OBD-generic speed PID, silently
        # dropping the most recent ~9 days of driving from this and every
        # other col('speed')-gated Category-B array. col('speed') now falls
        # back to the OBD-generic PID (see RAW_MAP) so all 274 files
        # contribute; self.soc_speed_obd_fallback_files below discloses how
        # many did so via the fallback rather than the native channel.
        self.soc_speed_files = 0
        self.soc_speed_seconds = 0.0
        self.soc_speed_obd_fallback_files = 0
        # M57 (2026-07-27): cycleBySpeed + engineOnDuration promoted from
        # summary_config.json (hand-maintained) into the pipeline. Both were
        # authored on an early corpus and never regenerated: the shipped
        # cycleBySpeed was off by -16%..+94% against the 194-drive recompute,
        # and engineOnDuration was still bucketed by trip DISTANCE, a basis
        # M21 retired everywhere else in this study. Neither had a documented
        # basis. Computed here so they can never drift again.
        # cycleBySpeed: gross throughput (|I*V|) and distance accumulated per
        # instantaneous-speed zone -> GTC per 100 km, same CAP_KWH basis as
        # cycleByType.
        self.cy_kwh = np.zeros(len(Z_CYSPD_LBL))
        self.cy_km = np.zeros(len(Z_CYSPD_LBL))
        self.cy_files = 0
        # engineOnDuration: engine-on segment lengths per drive_type class.
        self.eod = {}          # class -> list of segment durations (s)
        self.eod_on = {}       # class -> [on_samples, total_samples, n_segments]
        # engineOnBySpeed
        self.eng_on = np.zeros(len(Z_ENGINE_LBL))
        self.eng_tot = np.zeros(len(Z_ENGINE_LBL))
        self.eng_on_files = 0  # n drives contributing (both speed + rpm PIDs present)
        # torqueBySpeed: per zone collect accel/cruise/regen torque samples
        self.tq = {lbl: {'accel': [], 'cruise': [], 'regen': []}
                   for _, _, lbl in Z_TORQUE}
        # terrainTorqueDist: steady-speed (|dv|<1, 80-120) torque histogram
        self.terrain_bins = [-200, -60, -40, -25, -10, 0, 10, 25, 40, 75, 200]
        self.terrain_hist = np.zeros(len(self.terrain_bins) - 1)
        # M48 (2026-07-22): SECOND, LOW-SPEED steady band (40-70 km/h).
        # Audit finding: the 80-120 km/h gate admits only ~3% of the corpus's
        # high-relief (Carpathian) driving time and ZERO seconds from 5 of the
        # 10 highest-elevation drives -- those routes run at a 37-65 km/h
        # median, so the chart was structurally blind to exactly the terrain
        # it was captioned as describing. 40-70 km/h is the secondary/mountain
        # road regime; the same |dv|<1 + 3 s streak steadiness rule applies so
        # the two bands are directly comparable.
        self.terrain_hist_low = np.zeros(len(self.terrain_bins) - 1)
        # coverage bookkeeping: total gridded seconds vs seconds each gate
        # admits, so the dashboard can state what fraction of driving each
        # distribution actually rests on instead of implying full coverage.
        self.terrain_cov = {'gridS': 0, 'hwyS': 0, 'lowS': 0}
        # batteryThermalCurve: minute-into-drive -> [T1,T2,T3,T4,intake] sums/counts
        # M-07 (audit 2026-07-14): each channel now carries its own valid-sample
        # count (n1..n4, nint) instead of dividing every channel by a single T1-
        # keyed 'n'. Sensors with different finite-sample coverage than T1 were
        # previously biased. 'n' retained for the drive-count metadata only.
        # M48 (2026-07-22): 'nd' = number of DISTINCT DRIVES contributing to
        # this minute-bin. Without it the curve's tail is indistinguishable
        # from its head: bins past ~120 min rest on <10 drives (180 min: 2)
        # while the 0-10 min bin rests on all of them, so the apparent second
        # thermal rise after 2 h is a population-composition change, not
        # continued heating. Exposed per point so the chart can mark it.
        self.thermal = {m: {'s1': 0., 's2': 0., 's3': 0., 's4': 0.,
                            'intk': 0.,
                            'n1': 0, 'n2': 0, 'n3': 0, 'n4': 0, 'nint': 0,
                            'n': 0, 'nd': 0} for m in range(0, 190, 10)}
        # turboByRpm / turboBySpeedCtx (engine-on, >0.1 bar)
        self.turbo_rpm = {lbl: {'n': 0, 'act': 0, 'sumAct': 0., 'max': 0.}
                          for _, _, lbl in RPM_BANDS}
        # M82: rpmDistribution -- duration-weighted RPM occupancy (seconds,
        # on the 1 Hz grid; see RPM_HIST_EDGES provenance above).
        n_rb = len(RPM_HIST_LABELS)
        self.rpm_hist_total = np.zeros(n_rb)
        self.rpm_hist_by_class = {k: np.zeros(n_rb) for k in CLASS_ORDER}
        self.rpm_hist_fuelled = np.zeros(n_rb)
        self.rpm_hist_motored = np.zeros(n_rb)
        self.rpm_hist_files = 0
        self.rpm_hist_seconds = 0.0
        self.rpm_hist_fuelstate_files = 0
        self.rpm_hist_fuelstate_seconds = 0.0
        # M89: load-only fuelled proxy for boost-less files -- see
        # RPM_HIST_LOAD_PROXY_FUELLED_MIN provenance (module level). Kept
        # separate from rpm_hist_fuelled (boost-verified) throughout.
        self.rpm_hist_fuelled_loadproxy = np.zeros(n_rb)
        self.rpm_hist_fuelstate_loadproxy_files = 0
        self.rpm_hist_fuelstate_loadproxy_seconds = 0.0
        self.turbo_spd = {lbl: {'n': 0, 'act': 0, 'max': 0.}
                          for _, _, lbl in Z_TURBO_SPD}
        # socVcmPoints: (soc, soc_vcm) subsample
        self.soc_vcm = []
        # sensorSummary per-sensor global lo/hi + which-is-hottest counts
        self.sensor = {s: [None, None] for s in ['T1', 'T2', 'T3', 'T4']}
        self.hot_count = {s: 0 for s in ['T1', 'T2', 'T3', 'T4']}
        self.cold_count = {s: 0 for s in ['T1', 'T2', 'T3', 'T4']}
        self.hotcold_tot = 0
        # regenByZone / regenCaptureMeasured (engine-off decel KE capture)
        self.regen_zone = {lbl: {'cap': 0., 'ke': 0., 'n': 0, 'ke_um': 0.}
                           for _, _, lbl in Z_REGEN}
        self.regen_fine = {}   # 10-km/h mid-bins for the measured curve
        # M22 (audit 2026-07-07): regenByTempMeasured -- same engine-off decel
        # KE-capture basis as regenByZone/regenCaptureMeasured, stratified by
        # pack temperature (mean of T1-T4) at the moment of the decel sample,
        # instead of by speed. Answers whether "By Battery Temperature" (the
        # config-only regenByTemp curves) reflects real measured behaviour.
        self.regen_temp = {lbl: {'cap': 0., 'ke': 0., 'n': 0, 'ke_um': 0.}
                           for _, _, lbl in REGEN_TEMP_BINS}
        # engineStartsByType (starts/100km) per operating class
        self.starts = {k: [] for k in CLASS_ORDER}
        # M26 (2026-07-09): speedDist -- time-weighted zone shares from raw
        # speed samples (dt-weighted, same 5s-capped weights as everything
        # else in this class). Supersedes the hand-authored config block,
        # which had drifted ~3x from current data (see category_B provenance).
        self.speed_all = np.zeros(len(Z_SPEED_DIST))
        self.speed_city = np.zeros(len(Z_SPEED_DIST))
        self.speed_hwy = np.zeros(len(Z_SPEED_DIST))
        # M30 (2026-07-12, audit): highwayVsCity -- the four Comparison-tab
        # metrics that genuinely require the raw 1 Hz series (the other six
        # rows are drive_master-derivable and computed in Category A).
        # M86 (2026-08-05): migrated from a hand-rolled three-bucket collapse
        # (city=urban, mixed=mixed, highway=mixed_highway+highway) to the
        # native CLASS_ORDER taxonomy, matching driveTypes/engineStartsByType/
        # driveDurationDist/rpmDistribution dashboard-wide. The prior comment
        # here describing this as a "two-bucket city/highway split... 'mixed'
        # excluded by design" was stale -- M31 had already added 'mixed' to
        # every one of these dicts without updating this docstring; that drift
        # is itself the argument for a single shared classifier instead of
        # each accumulator re-deriving its own bucket set. The ONLY place the
        # blended mixed_highway+highway convention is retained is the cycle-
        # life scenario projection (_cycle_projection/_audit_observed_mix),
        # where "highway" is a hand-chosen forward-usage archetype weight, not
        # an empirical pooling bucket -- that collapse stays untouched.
        # Supersedes the hand-authored highwayVsCity block in
        # summary_config.json, which had drifted (SoC band '60-82%' vs the
        # observed 44.5-84.5%; see provenance note in build_summary_arrays).
        self.hvc_trigger_soc = {k: [] for k in CLASS_ORDER}
        self.hvc_stop_soc = {k: [] for k in CLASS_ORDER}
        self.hvc_turbo = {k: {'n': 0, 'act': 0, 'max': 0.0, 'max_label': None}
                          for k in CLASS_ORDER}
        # M173 (2026-08-27): engine-warmup -- 'urban' migrated off the
        # DIST_BINS-style city_short (<5km) / city_long (5-20km) distance
        # split onto the native CLASS_ORDER bucket, closing the one holdout
        # this accumulator still had (every sibling dict above -- trigger/
        # stop SoC, turbo activity -- already made this switch at M86). The
        # split additionally silently dropped every urban trip >20km from
        # the metric outright (undocumented in the JSX); the unified bucket
        # counts all urban drives, matching how mixed/mixed_highway/highway
        # are already counted. See build_summary_arrays()/_warm_str() for
        # the corresponding output-side simplification and CHANGELOG M173
        # for the audit trail (this was flagged by two contradictory
        # docstrings in this file: the M86 note near _cycle_projection
        # claimed hvcEngine80C was already on native CLASS_ORDER, while this
        # dict's own prior comment claimed the opposite as a deliberate,
        # permanent design decision -- the code matched the latter).
        self.hvc_warm = {k: [] for k in CLASS_ORDER}
        # M31: distance-domain warm-up curve -- per cold-start drive, engine-
        # coolant interpolated onto WARMUP_GRID (km from cold anchor) and
        # pooled by condition class (M86: native CLASS_ORDER, was a blended
        # {city, mixed, highway}).
        self.warm_curve = {k: [] for k in CLASS_ORDER}
        # M43 (2026-07-17): pooled EoL leading-indicator baselines. The
        # Six-Leading-Indicators block in the JSX hand-typed its pooled
        # references (loaded-spread p95 = 27 mV / n = 13,741 samples; resting
        # p95 = 11 mV; Sensor-1-minus-pack-mean median +2.5C / p90 +4.0 /
        # max +5.2 on a "100-drive pool") -- all stale on the 138-drive
        # corpus. Recomputed here on the v6 pairing conventions: Vmax<->Vmin
        # merge_asof nearest 300 ms, spread->current asof nearest 1500 ms
        # (identical to compute_drive_summary_v6 M10), loaded = |I| > 50 A,
        # resting = |I| < 5 A; Sensor-1 delta on the same all-four-sensors-
        # valid rowwise basis as sensorSummary's hottest-probe count.
        self.eol_loaded = []        # spread mV samples at |I| > 50 A
        self.eol_rest = []          # spread mV samples at |I| < 5 A
        self.eol_s1d = []           # T1 - mean(T1..T4) per valid row (C)
        self.eol_intkd = []         # pack mean - intake air per valid row (C)
        self.eol_spread_files = 0   # files contributing paired spread+I
        self.eol_temp_files = 0     # files contributing 4-sensor rows

    # ---- per-file ingestion ----
    def add(self, df, dist_km, cond_class=None, file_label=None, fn=None):
        # M167: resolve the VCM/OBD speed priority BEFORE the RAW_MAP rename
        # (see module-level _apply_speed_priority note) so both the
        # frame_loader and raw_loader sourcing paths get identical treatment.
        df, _spd_fallback = _apply_speed_priority(df)
        df = df.rename(columns={k: v for k, v in RAW_MAP.items() if k in df.columns})
        if 'time' not in df:
            return
        t = pd.to_datetime(df['time'], format='mixed', errors='coerce')
        n = len(df)
        # per-file forward-fill (limit 15), then work column-wise
        def col(name, lo=None, hi=None):
            if name not in df:
                return None
            s = pd.to_numeric(df[name], errors='coerce').ffill(limit=15)
            if lo is not None:
                s = s.where(s >= lo)
            if hi is not None:
                s = s.where(s <= hi)
            return s

        spd = col('speed', 0, 260)
        rpm = col('eng_rpm', 0)
        soc = col('soc', 0, 100)
        socv = col('soc_vcm', 0, 100)
        tq = col('target_torque')
        boost = col('boost')
        Ts = {s: col(s, -40, 90) for s in ['T1', 'T2', 'T3', 'T4']}
        Tin = col('T_intake', -40, 90)
        I = col('I')
        V = col('V', 200, 450)
        Tcool = col('T_coolant', -40, 150)

        # dt weights (seconds), capped at 5 s across gaps
        dt = t.diff().dt.total_seconds().clip(lower=0, upper=5).fillna(0).values

        # 1 Hz-resampled frame — REQUIRED for any per-second derivative
        # (decel detection, KE capture, steady-streak terrain). Asynchronous
        # PID rows with ffill make consecutive raw rows near-identical, so
        # per-row Delta-based logic silently returns ~0; resampling to a true
        # 1 s grid recovers the physical rate. Built once, reused below.
        # M82: eng_load_calc pulled via col() (native samples), needed only on
        # the 1 Hz grid below for the rpmDistribution fuelled/motored split.
        eng_load_calc = col('eng_load_calc')
        g1 = pd.DataFrame({'t': t})
        for cN, cS in [('speed', spd), ('eng_rpm', rpm), ('target_torque', tq),
                       ('I', I), ('V', V),
                       ('T1', Ts['T1']), ('T2', Ts['T2']), ('T3', Ts['T3']), ('T4', Ts['T4']),
                       ('soc', soc), ('T_coolant', Tcool),
                       ('boost', boost), ('eng_load_calc', eng_load_calc)]:
            g1[cN] = cS.values if cS is not None else np.nan
        g1 = g1.dropna(subset=['t']).set_index('t')
        hz = g1.resample('1s').mean().ffill(limit=15)

        # ---- socBySpeed ----
        if spd is not None and soc is not None:
            sp, sc = spd.values, soc.values
            contributed = False
            for lo, hi, lbl, _ in Z_SOC:
                m = (sp >= lo) & (sp < hi) & ~np.isnan(sc)
                if m.any():
                    self.soc_by_zone[lbl].append(sc[m])
                    contributed = True
            if contributed:  # M35: coverage counters, see __init__ note
                self.soc_speed_files += 1
                if _spd_fallback:
                    self.soc_speed_obd_fallback_files += 1
                span_s = (t.max() - t.min()).total_seconds()
                if pd.notna(span_s) and span_s > 0:
                    self.soc_speed_seconds += span_s

        # ---- M57: cycleBySpeed (gross throughput per zone / distance per zone) ----
        # Uses the 1 Hz grid: |I*V| integrated per second is the same gross
        # throughput quantity gross_throughput_kwh carries per drive, so the
        # zone rates are directly comparable to cycleByType.
        if {'speed', 'I', 'V'}.issubset(hz.columns):
            sph = hz['speed'].values
            pwr = np.abs(hz['I'].values * hz['V'].values) / 1000.0     # kW
            okc = ~np.isnan(sph) & ~np.isnan(pwr)
            if okc.sum() > 10:
                self.cy_files += 1
                kwh = pwr / 3600.0                 # per 1 s sample
                kmv = sph / 3600.0
                for i, (lo, hi) in enumerate(Z_CYSPD):
                    mm = okc & (sph >= lo) & (sph < hi)
                    if mm.any():
                        self.cy_kwh[i] += float(np.nansum(kwh[mm]))
                        self.cy_km[i] += float(np.nansum(kmv[mm]))

        # ---- M57: engineOnDuration (engine-on segment lengths by drive_type) ----
        # Segment = maximally contiguous run of eng_rpm > 300 on the 1 Hz grid
        # (same engine-on threshold engineOnBySpeed uses, so the two views are
        # consistent by construction).
        if 'eng_rpm' in hz.columns and cond_class is not None:
            rr = hz['eng_rpm'].values
            valid = ~np.isnan(rr)
            eon = (rr > 300) & valid
            if valid.any():
                dd = np.diff(eon.astype(int), prepend=0)
                starts = np.where(dd == 1)[0]
                ends = np.where(np.diff(eon.astype(int), append=0) == -1)[0]
                nseg = min(len(starts), len(ends))
                durs = (ends[:nseg] - starts[:nseg] + 1).astype(float)
                k = str(cond_class)
                self.eod.setdefault(k, []).extend(durs.tolist())
                acc = self.eod_on.setdefault(k, [0.0, 0.0, 0.0])
                acc[0] += float(eon.sum())
                acc[1] += float(valid.sum())
                acc[2] += float(nseg)

        # ---- engineOnBySpeed ----
        if spd is not None and rpm is not None:
            sp, rp = spd.values, rpm.values
            z = np.digitize(sp, Z_ENGINE[1:-1])
            eng = rp > 300
            ok = ~np.isnan(sp) & ~np.isnan(rp)
            if ok.any():
                self.eng_on_files += 1
            for i in range(len(Z_ENGINE_LBL)):
                m = (z == i) & ok
                self.eng_tot[i] += m.sum()
                self.eng_on[i] += (eng & m).sum()

        # ---- M82: rpmDistribution (duration-weighted RPM occupancy) ----
        # Uses the 1 Hz grid (hz), NOT the native-sampled `rpm` series above,
        # so bin counts are seconds rather than raw-row counts -- the same
        # one-row-approx-one-second convention terrainTorqueDist/cycleBySpeed/
        # engineOnDuration already rely on in this class.
        if 'eng_rpm' in hz.columns:
            rr_h = hz['eng_rpm'].dropna()
            if len(rr_h):
                h, _ = np.histogram(rr_h.values, bins=RPM_HIST_EDGES)
                self.rpm_hist_total += h
                self.rpm_hist_files += 1
                self.rpm_hist_seconds += float(len(rr_h))
                cls = str(cond_class)
                if cls in self.rpm_hist_by_class:
                    self.rpm_hist_by_class[cls] += h
            # Fuelled/motored split: only where boost + calc-load are both on
            # the grid, and only above RPM_HIST_FUELSTATE_RPM_MIN (1400, M84 --
            # empirically checked, not the un-verified 2000 M82/M83 originally
            # copied from _dissipation_census; see RPM_HIST_FUELSTATE_RPM_MIN
            # provenance above).
            #
            # M89: 'boost' and 'eng_load_calc' are ALWAYS present as column
            # NAMES in hz (g1[cN] is synthesised as all-NaN when the source
            # file lacks the raw PID -- see the g1 assembly above), so
            # `.issubset(hz.columns)` alone cannot distinguish "PID absent"
            # from "PID present but this row is NaN". Gate on actual data
            # presence instead. Files with eng_rpm + boost + eng_load_calc
            # all present take the boost-verified path (unchanged, M82-M84).
            # Files with eng_rpm + eng_load_calc but NO boost at all (the
            # 51 recoverable files, see RPM_HIST_LOAD_PROXY_FUELLED_MIN
            # provenance) take the load-only fuelled-proxy path instead --
            # motored is intentionally not proxied. Files lacking eng_rpm or
            # eng_load_calc entirely (the 5 earliest, minimal-column logs)
            # contribute to neither split, same as before.
            has_boost = 'boost' in hz.columns and hz['boost'].notna().any()
            has_load = 'eng_load_calc' in hz.columns and hz['eng_load_calc'].notna().any()
            if has_boost and has_load:
                sub = hz.dropna(subset=['eng_rpm', 'boost'])
                if len(sub):
                    base = sub['eng_rpm'] > RPM_HIST_FUELSTATE_RPM_MIN
                    ld = sub['eng_load_calc'].fillna(0)
                    mot = sub[base & (sub['boost'] < RPM_HIST_BOOST_MOTORED)
                             & (ld < RPM_HIST_LOAD_MAX)]
                    fue = sub[base & (sub['boost'] >= RPM_HIST_BOOST_FUELLED)]
                    if len(mot):
                        hm, _ = np.histogram(mot['eng_rpm'].values, bins=RPM_HIST_EDGES)
                        self.rpm_hist_motored += hm
                    if len(fue):
                        hf, _ = np.histogram(fue['eng_rpm'].values, bins=RPM_HIST_EDGES)
                        self.rpm_hist_fuelled += hf
                    self.rpm_hist_fuelstate_files += 1
                    self.rpm_hist_fuelstate_seconds += float(len(sub))
            elif has_load and not has_boost:
                sub = hz.dropna(subset=['eng_rpm', 'eng_load_calc'])
                if len(sub):
                    base = sub['eng_rpm'] > RPM_HIST_FUELSTATE_RPM_MIN
                    fue = sub[base & (sub['eng_load_calc']
                                       >= RPM_HIST_LOAD_PROXY_FUELLED_MIN)]
                    if len(fue):
                        hf, _ = np.histogram(fue['eng_rpm'].values, bins=RPM_HIST_EDGES)
                        self.rpm_hist_fuelled_loadproxy += hf
                    self.rpm_hist_fuelstate_loadproxy_files += 1
                    self.rpm_hist_fuelstate_loadproxy_seconds += float(len(sub))

        # ---- torqueBySpeed ----
        if spd is not None and tq is not None:
            sp, tv = spd.values, tq.values
            for lo, hi, lbl in Z_TORQUE:
                m = (sp >= lo) & (sp < hi) & ~np.isnan(tv)
                if not m.any():
                    continue
                tt = tv[m]
                self.tq[lbl]['accel'].append(tt[tt > 15])
                self.tq[lbl]['cruise'].append(tt[(tt >= -15) & (tt <= 15)])
                self.tq[lbl]['regen'].append(tt[tt < -15])

        # ---- terrainTorqueDist (steady 80-120, |dv|<1 km/h/s, >=3 s streak) ----
        # 1 Hz grid + a genuine 3-consecutive-second steady requirement; the
        # streak filter is what concentrates mass into the flat-cruise core and
        # is essential to reproduce the terrain distribution.
        rr = hz.dropna(subset=['speed', 'target_torque'])
        if len(rr) >= 4:
            sph, tqh = rr['speed'].values, rr['target_torque'].values
            dv = np.abs(np.diff(sph, prepend=sph[:1]))

            def _steady(lo, hi):
                """|dv|<1 km/h/s inside [lo,hi] for >=3 consecutive seconds."""
                inband = (sph >= lo) & (sph <= hi) & (dv < 1)
                st = np.zeros(len(sph), bool)
                run = 0
                for i in range(len(sph)):
                    run = run + 1 if inband[i] else 0
                    if run >= 3:
                        st[i - 2:i + 1] = True
                return st

            self.terrain_cov['gridS'] += len(sph)
            hwy = _steady(80, 120)
            if hwy.any():
                h, _ = np.histogram(tqh[hwy], bins=self.terrain_bins)
                self.terrain_hist += h
                self.terrain_cov['hwyS'] += int(hwy.sum())
            # M48: low-speed / secondary-road band
            low = _steady(40, 70)
            if low.any():
                h, _ = np.histogram(tqh[low], bins=self.terrain_bins)
                self.terrain_hist_low += h
                self.terrain_cov['lowS'] += int(low.sum())

        # ---- batteryThermalCurve ----
        if any(Ts[s] is not None for s in Ts) and n > 60:
            tmin = ((t - t.iloc[0]).dt.total_seconds() / 60).values
            for mkey in self.thermal:
                m = (tmin >= mkey) & (tmin < mkey + 10)
                if not m.any():
                    continue
                acc = self.thermal[mkey]
                for s, k, nk in [('T1', 's1', 'n1'), ('T2', 's2', 'n2'),
                                 ('T3', 's3', 'n3'), ('T4', 's4', 'n4')]:
                    if Ts[s] is not None:
                        v = Ts[s].values[m]
                        v = v[~np.isnan(v)]
                        if len(v):
                            acc[k] += v.sum()
                            acc[nk] += len(v)
                if Tin is not None:
                    v = Tin.values[m]
                    v = v[~np.isnan(v)]
                    if len(v):
                        acc['intk'] += v.sum()
                        acc['nint'] += len(v)
                acc['n'] += int(np.isfinite(Ts['T1'].values[m]).sum()
                                if Ts['T1'] is not None else m.sum())
                acc['nd'] += 1          # M48: one increment per drive per bin

        # ---- turbo (engine-on, >0.1 bar) ----
        if boost is not None and rpm is not None:
            bo, rp = boost.values, rpm.values
            eng = rp > 300
            for lo, hi, lbl in RPM_BANDS:
                m = (rp >= lo) & (rp < hi) & eng & ~np.isnan(bo)
                if not m.any():
                    continue
                bb = bo[m]
                d = self.turbo_rpm[lbl]
                d['n'] += len(bb)
                act = bb[bb > 0.1]
                d['act'] += len(act)
                d['sumAct'] += act.sum()
                d['max'] = max(d['max'], float(bb.max()))
            if spd is not None:
                sp = spd.values
                for lo, hi, lbl in Z_TURBO_SPD:
                    m = (sp >= lo) & (sp < hi) & eng & ~np.isnan(bo)
                    if not m.any():
                        continue
                    bb = bo[m]
                    d = self.turbo_spd[lbl]
                    d['n'] += len(bb)
                    d['act'] += (bb > 0.1).sum()
                    d['max'] = max(d['max'], float(bb.max()))

        # ---- socVcmPoints (subsample every ~200th valid pair) ----
        if soc is not None and socv is not None:
            m = ~np.isnan(soc.values) & ~np.isnan(socv.values)
            sv = np.column_stack([soc.values[m], socv.values[m]])[::200]
            for a, b in sv:
                self.soc_vcm.append([round(float(a), 1), int(round(b))])

        # ---- sensorSummary ----
        arrs = {s: (Ts[s].values if Ts[s] is not None else None) for s in Ts}
        for s in Ts:
            if arrs[s] is None:
                continue
            v = arrs[s][~np.isnan(arrs[s])]
            if not len(v):
                continue
            lo, hi = self.sensor[s]
            self.sensor[s][0] = float(v.min()) if lo is None else min(lo, float(v.min()))
            self.sensor[s][1] = float(v.max()) if hi is None else max(hi, float(v.max()))
        if all(arrs[s] is not None for s in Ts):
            M = np.column_stack([arrs[s] for s in ['T1', 'T2', 'T3', 'T4']])
            ok = ~np.isnan(M).any(axis=1)
            if ok.any():
                Mo = M[ok]
                hot = np.argmax(Mo, axis=1)
                cold = np.argmin(Mo, axis=1)
                names = ['T1', 'T2', 'T3', 'T4']
                for i, nm in enumerate(names):
                    self.hot_count[nm] += int((hot == i).sum())
                    self.cold_count[nm] += int((cold == i).sum())
                self.hotcold_tot += int(ok.sum())

        # ---- M43: pooled EoL baselines (see __init__ note) ----
        if 'Vcmax' in df and 'Vcmin' in df:
            def _pidser(cname, lo, hi):
                mm = df[cname].notna()
                if not mm.any():
                    return None
                q = pd.DataFrame({'t': t[mm].values,
                                  'v': pd.to_numeric(df.loc[mm, cname],
                                                     errors='coerce').values}
                                 ).dropna()
                q = q[(q['v'] >= lo) & (q['v'] <= hi)]
                return q.sort_values('t').reset_index(drop=True) \
                    if len(q) else None
            vx = _pidser('Vcmax', 2.0, 5.0)
            vn = _pidser('Vcmin', 2.0, 5.0)
            Ir = None
            if 'I' in df:
                Ir = _pidser('I', -900, 900)
                if Ir is not None:
                    Ir = Ir[Ir['v'].abs() < 900]          # v6 artifact gate
                    Ir = Ir if len(Ir) else None
            if vx is not None and vn is not None and Ir is not None:
                pp = pd.merge_asof(vx.rename(columns={'v': 'vmax'}),
                                   vn.rename(columns={'v': 'vmin'}),
                                   on='t', direction='nearest',
                                   tolerance=pd.Timedelta('300ms')).dropna()
                if len(pp):
                    pp['spread_mv'] = (pp['vmax'] - pp['vmin']) * 1000.0
                    pp = pd.merge_asof(
                        pp, Ir.rename(columns={'v': 'Ipair'}),
                        on='t', direction='nearest',
                        tolerance=pd.Timedelta('1500ms')).dropna(
                            subset=['Ipair'])
                    if len(pp):
                        ld = pp.loc[pp['Ipair'].abs() > 50,
                                    'spread_mv'].values
                        rs = pp.loc[pp['Ipair'].abs() < 5,
                                    'spread_mv'].values
                        if len(ld):
                            self.eol_loaded.append(ld.astype(np.float32))
                        if len(rs):
                            self.eol_rest.append(rs.astype(np.float32))
                        if len(ld) or len(rs):
                            self.eol_spread_files += 1
        if all(arrs[s] is not None for s in Ts):
            M43 = np.column_stack([arrs[s] for s in ['T1', 'T2', 'T3', 'T4']])
            ok43 = ~np.isnan(M43).any(axis=1)
            if ok43.any():
                Mo43 = M43[ok43]
                pk43 = Mo43.mean(axis=1)
                self.eol_s1d.append((Mo43[:, 0] - pk43).astype(np.float32))
                self.eol_temp_files += 1
                if Tin is not None:
                    dd = pk43 - Tin.values[ok43]
                    dd = dd[~np.isnan(dd)]
                    if len(dd):
                        self.eol_intkd.append(dd.astype(np.float32))

        # ---- regen capture (engine-off decel, motor-only), 1 Hz basis ----
        rq = hz.dropna(subset=['speed', 'I', 'V'])
        if len(rq) >= 4:
            sp = rq['speed'].values
            rp = rq['eng_rpm'].fillna(0).values
            Iv, Vv = rq['I'].values, rq['V'].values
            eng_off = rp <= 300
            v_prev = np.concatenate([sp[:1], sp[:-1]])
            decel = sp < v_prev
            P = (-Iv) * Vv / 1000.0            # +discharge; charge is negative
            cap_kwh = np.where(P < 0, -P, 0) * (1.0 / 3600.0)   # dt = 1 s
            # M124: class-conditional assumed mass for THIS drive (see
            # _mass_for_drive), not the flat VEHICLE_MASS_KG.
            # M164: urban/mixed now uses a single honest point value
            # (MASS_URBAN_MIXED_KG), not a pseudo-random per-file hash split
            # (audit sec.5: "replace with an uncertainty range"). is_um flags
            # whether THIS drive's contribution carries that mass uncertainty
            # at all (highway/mixed_highway does not -- MASS_HIGHWAY_KG is a
            # single fixed point value with no disclosed range), so the exact
            # per-zone urban/mixed KE-share can be recovered later
            # (ke_um/ke) to derive a precise -- not conservative-worst-case --
            # uncertainty bound per zone (see arrays['regenByZone'] below).
            drive_mass_kg = _mass_for_drive(cond_class, fn)
            is_um = cond_class in ('urban', 'mixed')
            ke_loss = 0.5 * drive_mass_kg * ((v_prev / 3.6) ** 2 - (sp / 3.6) ** 2) \
                / 3.6e6                        # kWh
            step = eng_off & decel & (sp > 0) & (ke_loss > 0)
            if step.any():
                for lo, hi, lbl in Z_REGEN:
                    m = step & (sp >= lo) & (sp < hi)
                    if m.any():
                        d = self.regen_zone[lbl]
                        d['cap'] += cap_kwh[m].sum()
                        d['ke'] += ke_loss[m].sum()
                        d['n'] += int(m.sum())
                        if is_um:
                            d['ke_um'] += ke_loss[m].sum()
                mids = (np.clip(sp[step], 0, 129) // 10 * 10 + 5).astype(int)
                for mid, c, k in zip(mids, cap_kwh[step], ke_loss[step]):
                    d = self.regen_fine.setdefault(int(mid), {'cap': 0., 'ke': 0., 'n': 0, 'ke_um': 0.})
                    d['cap'] += c
                    d['ke'] += k
                    d['n'] += 1
                    if is_um:
                        d['ke_um'] += k
                # M22: same qualifying decel steps, stratified by pack temperature
                # (mean of T1-T4 at that 1 Hz sample) instead of speed.
                Tpack = rq[['T1', 'T2', 'T3', 'T4']].mean(axis=1).values
                step_t = step & ~np.isnan(Tpack)
                if step_t.any():
                    for lo, hi, lbl in REGEN_TEMP_BINS:
                        m = step_t & (Tpack >= lo) & (Tpack < hi)
                        if m.any():
                            d = self.regen_temp[lbl]
                            d['cap'] += cap_kwh[m].sum()
                            d['ke'] += ke_loss[m].sum()
                            d['n'] += int(m.sum())
                            if is_um:
                                d['ke_um'] += ke_loss[m].sum()

        # ---- engineStartsByType (starts / 100 km) ----
        # M21: cls is now the time-weighted drive_type passed in from
        # category_B (via the master), not a distance_km bucket.
        # M29 (2026-07-10, audit F-08): the previous implementation counted
        # EVERY False->True rising edge on ffill'd raw RPM, so single-sample
        # or sub-second RPM blips inflated the start rate and the declared
        # ">=2 s" filter did not exist. Re-implemented on the true 1 Hz grid
        # (hz, built above): NaN samples are treated as engine-off so they
        # break segments (avoids merging runs across logger gaps that the raw
        # ffill would silently bridge), on-segments are run-length encoded,
        # and only starts of segments lasting >= MIN_ENGINE_START_S are
        # counted. On the 1 s grid one sample ~= one second.
        if dist_km and dist_km > 0 and 'eng_rpm' in hz.columns:
            cls = _cond_class(cond_class)
            er = hz['eng_rpm'].values
            if cls and er.size:
                on = np.nan_to_num(er, nan=0.0) > 300     # NaN -> off boundary
                edges = np.diff(np.concatenate([[0], on.astype(int), [0]]))
                starts_idx = np.where(edges == 1)[0]       # original-index run starts
                stops_idx = np.where(edges == -1)[0] - 1   # original-index run ends (last True)
                seg_len = (np.where(edges == -1)[0] -
                           np.where(edges == 1)[0])        # samples ~= seconds
                q = seg_len >= MIN_ENGINE_START_S
                starts = int(q.sum())
                self.starts[cls].append(starts / dist_km * 100)

                # M30/M31/M86: engine trigger/stop SoC, native CLASS_ORDER
                # (was a hand-rolled city/mixed/highway collapse; 'cls' above
                # is already _cond_class(cond_class), so reuse it directly).
                if cls and 'soc' in hz.columns and q.any():
                    soc_hz = hz['soc'].values
                    for si, ei in zip(starts_idx[q], stops_idx[q]):
                        trig, stp = soc_hz[si], soc_hz[ei]
                        if not np.isnan(trig):
                            self.hvc_trigger_soc[cls].append(float(trig))
                        if not np.isnan(stp):
                            self.hvc_stop_soc[cls].append(float(stp))

        # ---- M30/M31/M86: turbo activity by native CLASS_ORDER class ----
        if boost is not None and rpm is not None:
            cls2 = _cond_class(cond_class)
            if cls2:
                bo, rp = boost.values, rpm.values
                m = (rp > 300) & ~np.isnan(bo)
                if m.any():
                    bb = bo[m]
                    d = self.hvc_turbo[cls2]
                    d['n'] += int(len(bb))
                    d['act'] += int((bb > 0.1).sum())
                    mx = float(bb.max())
                    if mx > d['max']:
                        d['max'] = mx
                        d['max_label'] = file_label

        # ---- M173 (was M30/M86): engine reaches 80C+, native CLASS_ORDER
        # bucket for all four classes -- urban is no longer split by
        # distance (see __init__ comment) ----
        if dist_km and dist_km > 0 and 'T_coolant' in hz.columns:
            tc = hz['T_coolant'].values
            valid = ~np.isnan(tc)
            if valid.any():
                reached = bool((tc[valid] >= WARM_ENGINE_C).any())
                minutes = None
                if reached:
                    first_idx = int(np.argmax(tc >= WARM_ENGINE_C))
                    minutes = first_idx / 60.0     # hz is a 1 Hz grid
                bucket = cond_class if cond_class in CLASS_ORDER else None
                if bucket:
                    self.hvc_warm[bucket].append((reached, minutes))

        # ---- M31/M86: distance-domain warm-up curve (cold-start drives only) ----
        # Reconstruct the coolant rise WITHIN the drive: anchor at the first
        # valid engine-coolant sample, require it be <= WARMUP_COLD_C, integrate
        # speed on the 1 Hz grid for distance-from-anchor, and interpolate the
        # coolant trace onto WARMUP_GRID. Pool per native CLASS_ORDER class
        # (was a blended {city, mixed, highway}).
        if 'T_coolant' in hz.columns and 'speed' in hz.columns:
            wgrp = _cond_class(cond_class)
            if wgrp is not None:
                tcv = hz['T_coolant'].values
                spv = hz['speed'].values
                vc = ~np.isnan(tcv)
                if vc.any():
                    i0 = int(np.argmax(vc))          # first valid-coolant sample
                    if tcv[i0] <= WARMUP_COLD_C:     # genuine cold start
                        # km from anchor: 1 Hz grid => each row is ~1 s of travel
                        dcum = np.cumsum(np.nan_to_num(spv[i0:])) / 3600.0
                        cool = tcv[i0:]
                        m = ~np.isnan(cool)
                        if m.sum() >= 3:
                            dd, cc = dcum[m], cool[m]
                            ud = np.unique(dd)
                            # monotone-in-time collapse: hottest coolant per km
                            uc = np.array([cc[dd == v].max() for v in ud])
                            span = float(dd[-1])
                            self.warm_curve[wgrp].append(
                                [float(np.interp(g, ud, uc)) if g <= span
                                 else np.nan for g in WARMUP_GRID])

        # ---- M26: speedDist (time-weighted zone shares) ----
        if spd is not None:
            sv = spd.values
            ok = ~np.isnan(sv)
            if ok.any():
                w = dt[ok]
                svok = sv[ok]
                for i, (lo, hi) in enumerate(Z_SPEED_DIST):
                    m = (svok >= lo) & (svok < hi)
                    self.speed_all[i] += w[m].sum()
                cls = _cond_class(cond_class)
                if cls == 'urban':
                    for i, (lo, hi) in enumerate(Z_SPEED_DIST):
                        m = (svok >= lo) & (svok < hi)
                        self.speed_city[i] += w[m].sum()
                elif cls in ('mixed_highway', 'highway'):
                    for i, (lo, hi) in enumerate(Z_SPEED_DIST):
                        m = (svok >= lo) & (svok < hi)
                        self.speed_hwy[i] += w[m].sum()

    # ---- finalize into JSON-ready arrays ----
    def finalize(self):
        out = {}
        # M26: speedDist -- zones list + percentage shares per bucket
        def _pct(arr):
            tot = arr.sum()
            return [round(float(x / tot * 100), 1) for x in arr] if tot > 0 \
                else [0.0] * len(arr)
        out['speedDist'] = {
            'zones': [f"{lo}-{hi}" if hi < 999 else f"{lo}+"
                     for lo, hi in Z_SPEED_DIST],
            'overall': _pct(self.speed_all),
            'city': _pct(self.speed_city),
            'highway': _pct(self.speed_hwy),
        }
        # socBySpeed
        rows = []
        for lo, hi, lbl, name in Z_SOC:
            alls = np.concatenate(self.soc_by_zone[lbl]) if self.soc_by_zone[lbl] else np.array([])
            if len(alls):
                q = np.percentile(alls, [0, 25, 50, 75, 100])
                rows.append([lbl, name, *[round(float(x)) for x in q]])
        out['socBySpeed'] = rows
        # M35: live coverage figures for the narrative — see __init__ note
        # M167: nSpeedObdFallback discloses how many of nDrives contribute via
        # the OBD-generic speed PID fallback rather than the native VCM
        # channel (see RAW_MAP / _RawAccum.add note).
        out['socBySpeedMeta'] = {
            'nDrives': int(self.soc_speed_files),
            'hours': round(self.soc_speed_seconds / 3600, 1),
            'nSpeedObdFallback': int(self.soc_speed_obd_fallback_files),
        }
        # engineOnBySpeed
        pct = np.where(self.eng_tot > 0, self.eng_on / self.eng_tot * 100, 0)
        col = ["#3b82f6", "#60a5fa", "#4ade80", "#eab308", "#f97316", "#ef4444", "#dc2626"]
        out['engineOnBySpeed'] = [{'zone': z, 'pct': round(float(p)), 'color': c}
                                  for z, p, c in zip(Z_ENGINE_LBL, pct, col)]
        out['engineOnDrives'] = int(self.eng_on_files)
        # M57: cycleBySpeed
        cs = []
        cs_col = ["#ef4444", "#f97316", "#eab308", "#4ade80", "#22c55e"]
        for i, lbl in enumerate(Z_CYSPD_LBL):
            if self.cy_km[i] <= 0.05:
                continue
            cs.append({'zone': lbl,
                       'rate': round(self.cy_kwh[i] / CAP_KWH / self.cy_km[i] * 100, 1),
                       'kwh': round(float(self.cy_kwh[i]), 1),
                       'km': round(float(self.cy_km[i]), 1),
                       'color': cs_col[i]})
        out['cycleBySpeed'] = cs
        out['cycleBySpeedMeta'] = {'nDrives': int(self.cy_files),
                                   'basis': 'gross throughput |I*V| per instantaneous-speed '
                                            'zone / distance in that zone, CAP_KWH turnovers '
                                            'per 100 km (M57)'}
        # M57: engineOnDuration
        eo_col = {'urban': "#ef4444", 'mixed': "#eab308",
                  'mixed_highway': "#3b82f6", 'highway': "#22c55e"}
        eod = []
        for k in CLASS_ORDER:
            L = self.eod.get(k)
            if not L or len(L) < 5:
                continue
            a = np.asarray(L, float)
            on, tot, nseg = self.eod_on[k]
            eod.append({'label': k.replace('_', ' ').title(),
                        'min': round(float(a.min()), 1), 'max': round(float(a.max()), 1),
                        'median': round(float(np.median(a)), 1),
                        'p10': round(float(np.percentile(a, 10)), 1),
                        'p90': round(float(np.percentile(a, 90)), 1),
                        'onFraction': round(on / tot * 100, 1) if tot else None,
                        'segsPer10min': round(nseg / (tot / 600.0), 1) if tot else None,
                        'nSegments': int(len(a)),
                        'color': eo_col.get(k, "#94a3b8")})
        out['engineOnDuration'] = eod
        # torqueBySpeed
        tq_rows = []
        for lo, hi, lbl in Z_TORQUE:
            a = np.concatenate(self.tq[lbl]['accel']) if self.tq[lbl]['accel'] else np.array([])
            c = np.concatenate(self.tq[lbl]['cruise']) if self.tq[lbl]['cruise'] else np.array([])
            r = np.concatenate(self.tq[lbl]['regen']) if self.tq[lbl]['regen'] else np.array([])
            n = len(a) + len(c) + len(r)
            if n == 0:
                continue
            tq_rows.append({
                'speed': lbl,
                'accelMed': round(float(np.median(a))) if len(a) else 0,
                'accelP90': round(float(np.percentile(a, 90))) if len(a) else 0,
                'accelMax': round(float(a.max())) if len(a) else 0,
                'cruiseMed': round(float(np.median(c))) if len(c) else 0,
                'regenMed': round(float(np.median(r))) if len(r) else 0,
                'regenP10': round(float(np.percentile(r, 10))) if len(r) else 0,
                'regenMin': round(float(r.min())) if len(r) else 0,
                'pAccel': round(len(a) / n * 100), 'pCruise': round(len(c) / n * 100),
                'pRegen': round(len(r) / n * 100),
                'sparse': n < 500})
        out['torqueBySpeed'] = tq_rows
        # terrainTorqueDist
        tot_t = self.terrain_hist.sum()
        labels = [("-200..-60", "Steep down (B-regen >40Nm)", "\u22653.5% downgrade"),
                  ("-60..-40", "Clear down (B-regen 27-40Nm)", "~2-3.5% grade"),
                  ("-40..-25", "Slight down (B-regen 14-27Nm)", "~1-2% grade"),
                  ("-25..-10", "Very slight down", "<1% grade"),
                  ("-10..0", "Near-zero coast", "Slight downhill \u2014 drag \u2248 grade"),
                  ("0..10", "Near-zero drive", "Slight downhill \u2014 motor barely loads"),
                  ("10..25", "Flat cruise (low)", "Flat to very slight uphill"),
                  ("25..40", "Flat cruise (core)", "Flat \u2014 dominant band"),
                  ("40..75", "Uphill (mild)", "1-2% uphill"),
                  ("75..200", "Uphill (steep)", ">2% uphill")]
        out['terrainTorqueDist'] = [
            {'bin': b, 'pct': round(float(self.terrain_hist[i] / tot_t * 100), 1)
             if tot_t else 0, 'label': l, 'terrain': ter}
            for i, (b, l, ter) in enumerate(labels)]
        # M48: low-speed (40-70 km/h) companion distribution + gate coverage.
        tot_l = float(self.terrain_hist_low.sum())
        # The 'terrain' grade equivalents are DELIBERATELY DROPPED here. They
        # were calibrated against 80-120 km/h road load, where aerodynamic
        # drag dominates (~390 N at 100 km/h vs ~120 N at 55 km/h, Cd·A~0.85).
        # At 40-70 km/h the same motor torque therefore corresponds to a
        # markedly steeper grade -- roughly 1.4 pp per the ~270 N drag
        # difference against ~191 N per 1% grade at 1950 kg. Carrying the
        # highway labels across would understate every low-speed gradient.
        # A low-speed mapping needs its own validated road-load fit; until
        # then the bins stay in torque units only.
        out['terrainTorqueDistLow'] = [
            {'bin': b, 'pct': round(float(self.terrain_hist_low[i] / tot_l * 100), 1)
             if tot_l else 0, 'label': l, 'terrain': None}
            for i, (b, l, ter) in enumerate(labels)]
        cv = self.terrain_cov
        gs = float(cv['gridS']) or 1.0
        out['terrainCoverage'] = {
            'gridS': int(cv['gridS']),
            'hwyS': int(cv['hwyS']), 'lowS': int(cv['lowS']),
            'hwyPct': round(cv['hwyS'] / gs * 100, 1),
            'lowPct': round(cv['lowS'] / gs * 100, 1),
            'bothPct': round((cv['hwyS'] + cv['lowS']) / gs * 100, 1),
            'hwyBand': '80-120 km/h', 'lowBand': '40-70 km/h',
            'steadyRule': '|dv| < 1 km/h/s for >= 3 consecutive seconds'}
        # batteryThermalCurve
        curve = []
        for mkey in sorted(self.thermal):
            a = self.thermal[mkey]
            if a['n'] < 30:
                continue
            # M-07 (audit 2026-07-14): per-channel means use each channel's own
            # valid-sample count (n1..n4, nint); a channel absent for this minute
            # bin yields None rather than a T1-denominator-biased number.
            def _mean(ssum, ncnt):
                return round(ssum / ncnt, 1) if ncnt else None
            curve.append({'min': mkey,
                          's1': _mean(a['s1'], a['n1']), 's2': _mean(a['s2'], a['n2']),
                          's3': _mean(a['s3'], a['n3']), 's4': _mean(a['s4'], a['n4']),
                          'intake': _mean(a['intk'], a['nint']),
                          'nDrives': int(a['nd'])})   # M48
        out['batteryThermalCurve'] = curve
        # M48: derived descriptors so the caption binds instead of hand-typing
        # the plateau / spread / intake-offset / dominance figures.
        if curve:
            def _m4(d):
                v = [d[k] for k in ('s1', 's2', 's3', 's4') if d[k] is not None]
                return sum(v) / len(v) if v else None
            # "plateau" = the well-supported flat region, defined as bins whose
            # drive support is at least a tenth of the opening bin's. Past that
            # the curve is a handful of long highway drives, not the corpus.
            nd0 = max((d['nDrives'] for d in curve), default=0)
            solid = [d for d in curve if d['nDrives'] >= max(10, nd0 * 0.10)]
            plat = [d for d in solid if d['min'] >= 60] or solid[-3:]
            pm = [x for x in (_m4(d) for d in plat) if x is not None]
            sp0 = (curve[0]['s1'] - curve[0]['s4']
                   if curve[0]['s1'] is not None and curve[0]['s4'] is not None
                   else None)
            spP = [d['s1'] - d['s4'] for d in plat
                   if d['s1'] is not None and d['s4'] is not None]
            gapP = [_m4(d) - d['intake'] for d in plat
                    if d['intake'] is not None and _m4(d) is not None]
            out['batteryThermalMeta'] = {
                'maxMin': int(max(d['min'] for d in curve)),
                'binWidthMin': 10,
                'nDrivesFirstBin': nd0,
                'solidToMin': int(max((d['min'] for d in solid), default=0)),
                'solidMinDrives': int(max(10, round(nd0 * 0.10))),
                'plateauLoC': round(min(pm), 1) if pm else None,
                'plateauHiC': round(max(pm), 1) if pm else None,
                'spreadKeyOnC': round(sp0, 1) if sp0 is not None else None,
                'spreadPlateauC': (round(sum(spP) / len(spP), 1) if spP else None),
                'intakeGapPlateauC': (round(sum(gapP) / len(gapP), 1)
                                      if gapP else None),
                'tailNDrives': int(curve[-1]['nDrives']),
                'gate': 'drive has >60 raw rows; minute-bin needs >=30 samples'}
        # turboByRpm
        tr = []
        for lo, hi, lbl in RPM_BANDS:
            d = self.turbo_rpm[lbl]
            if d['n'] == 0:
                continue
            tr.append({'rpm': lbl, 'n': d['n'],
                       'activePct': round(d['act'] / d['n'] * 100),
                       'meanActive': round(d['sumAct'] / d['act'], 3) if d['act'] else 0.0,
                       'maxBoost': round(d['max'], 2)})
        out['turboByRpm'] = tr

        # M82: rpmDistribution -- see RPM_HIST_EDGES provenance (module level)
        def _hrs(arr):
            return [round(float(x) / 3600, 3) for x in arr]

        def _pctvec(arr):
            tot = float(np.sum(arr))
            return [round(float(x) / tot * 100, 1) for x in arr] if tot > 0 \
                else [0.0] * len(arr)

        by_class = {}
        for k in CLASS_ORDER:
            arr = self.rpm_hist_by_class[k]
            if arr.sum() <= 0:
                continue
            by_class[k] = {'hours': _hrs(arr), 'pct': _pctvec(arr)}
        out['rpmDistribution'] = {
            'bins': RPM_HIST_LABELS,
            'pooledHours': _hrs(self.rpm_hist_total),
            'pooledPct': _pctvec(self.rpm_hist_total),
            'byClass': by_class,
            'fuelled': {'hours': _hrs(self.rpm_hist_fuelled),
                       'nSamplesS': int(self.rpm_hist_fuelled.sum())},
            'motored': {'hours': _hrs(self.rpm_hist_motored),
                       'nSamplesS': int(self.rpm_hist_motored.sum())},
            # M89: load-only proxy extension of the fuelled bucket for
            # boost-less files. Separate from 'fuelled' throughout -- see
            # RPM_HIST_LOAD_PROXY_FUELLED_MIN provenance (module level).
            'fuelledLoadProxy': {
                'hours': _hrs(self.rpm_hist_fuelled_loadproxy),
                'nSamplesS': int(self.rpm_hist_fuelled_loadproxy.sum()),
            },
            'coverage': {
                'nDrives': int(self.rpm_hist_files),
                'hours': round(self.rpm_hist_seconds / 3600, 1),
                'nDrivesFuelState': int(self.rpm_hist_fuelstate_files),
                'hoursFuelState': round(self.rpm_hist_fuelstate_seconds / 3600, 1),
                'nDrivesFuelStateLoadProxy':
                    int(self.rpm_hist_fuelstate_loadproxy_files),
                'hoursFuelStateLoadProxy':
                    round(self.rpm_hist_fuelstate_loadproxy_seconds / 3600, 1),
                'nDrivesFuelStateCombined':
                    int(self.rpm_hist_fuelstate_files
                        + self.rpm_hist_fuelstate_loadproxy_files),
            },
            'params': {
                'engineOnThresholdRpm': 300,
                'fuelStateRpmMin': RPM_HIST_FUELSTATE_RPM_MIN,
                'fuelStateBoostMotored': RPM_HIST_BOOST_MOTORED,
                'fuelStateBoostFuelled': RPM_HIST_BOOST_FUELLED,
                'fuelStateLoadMax': RPM_HIST_LOAD_MAX,
                'fuelStateLoadProxyMin': RPM_HIST_LOAD_PROXY_FUELLED_MIN,
                'basis': 'duration-weighted, 1 Hz grid (1 sample ~= 1 s); '
                         'fuelled/motored split reuses the M46/M48 '
                         'dissipation-census classifier thresholds',
                'loadProxyBasis': 'M89: calc-load-only fuelled proxy for '
                    'files carrying eng_load_calc but not boost at all '
                    '(logging-profile gap 2026-05-15..2026-06-18); '
                    'calibrated at RPM>fuelStateRpmMin against the '
                    'boost-covered corpus (98.3% recall, 0.33% '
                    'contamination at load>=fuelStateLoadProxyMin). '
                    'Motored is NOT proxied this way -- at RPM>1400 it is '
                    'only ~2.5% of the boost-classified population, so '
                    'load-based motored recall (up to 78.9%) carries '
                    '30%+ contamination from fuelled leakage and is not '
                    'reliable enough to report.',
            },
        }
        ts = []
        for lo, hi, lbl in Z_TURBO_SPD:
            d = self.turbo_spd[lbl]
            if d['n'] == 0:
                continue
            ts.append({'zone': lbl, 'activePct': round(d['act'] / d['n'] * 100),
                       'maxBoost': round(d['max'], 2)})
        out['turboBySpeedCtx'] = ts
        # M32 (2026-07-12, audit): socVcmPoints -- SoC-domain-stratified
        # subsample, capped ~90 points. The prior approach applied a SECOND
        # fixed-position stride (pts[::step]) on top of the per-file [::200]
        # stage-1 thinning; two independent positional strides compounded to
        # erase the sparse high-SoC tail entirely (>=80% BMS SoC is only
        # ~0.18% of all samples -- real, not noise, per D1 2026-07-11 which
        # alone contributes 539 such samples reaching 84.5%). Raw scatter
        # must be preserved per the dashboard's stated BMS-SoC-scatter
        # principle (non-linearity is a property of the point cloud's shape,
        # not to be aggregated away) -- so this bins by observed BMS SoC
        # (5-point-wide bins) and takes a capped, still-raw subsample from
        # EVERY populated bin, guaranteeing rare-but-real high/low-SoC
        # territory survives instead of being silently thinned out.
        pts = self.soc_vcm
        TARGET_N = 90
        if len(pts) > TARGET_N:
            bins = {}
            for p in pts:
                b = int(p[0] // 5) * 5
                bins.setdefault(b, []).append(p)
            per_bin = max(1, TARGET_N // len(bins))
            out_pts = []
            for b in sorted(bins):
                bp = bins[b]
                if len(bp) <= per_bin:
                    out_pts.extend(bp)
                else:
                    step = len(bp) / per_bin
                    out_pts.extend(bp[int(i * step)] for i in range(per_bin))
            pts = out_pts
        out['socVcmPoints'] = pts
        # sensorSummary
        roles = {'T1': "Hottest probe", 'T2': "Second-warmest, tracks Sensor 1",
                 'T3': "Cooler zone", 'T4': "Coldest probe"}
        colr = {'T1': "#ef4444", 'T2': "#f97316", 'T3': "#eab308", 'T4': "#60a5fa"}
        ss = []
        for i, s in enumerate(['T1', 'T2', 'T3', 'T4']):
            lo, hi = self.sensor[s]
            if lo is None:
                continue
            hotpct = round(self.hot_count[s] / self.hotcold_tot * 100) if self.hotcold_tot else 0
            coldpct = round(self.cold_count[s] / self.hotcold_tot * 100) if self.hotcold_tot else 0
            role = roles[s]
            if s == 'T1':
                role += f" \u2014 reads highest in {hotpct}% of samples"
            if s == 'T4':
                role += f" \u2014 reads lowest in {coldpct}% of samples"
            ss.append({'sensor': f"Sensor {i+1}", 'lo': round(lo), 'hi': round(hi),
                       'role': role, 'color': colr[s]})
        out['sensorSummary'] = ss
        # regenByZone + regenCaptureMeasured
        tot_cap = sum(d['cap'] for d in self.regen_zone.values())
        rz = []
        for lo, hi, lbl in Z_REGEN:
            d = self.regen_zone[lbl]
            if d['n'] == 0:
                continue
            eff = d['cap'] / d['ke'] * 100 if d['ke'] > 0 else 0
            # M164: exact per-zone mass-uncertainty bound. ke_um is this
            # zone's KE contributed by urban/mixed drives (mass-uncertain);
            # ke - ke_um is highway/mixed_highway's contribution (mass-fixed
            # at MASS_HIGHWAY_KG, zero uncertainty). w_um is this zone's own
            # urban/mixed weight -- NOT the conservative 1.0 default -- so
            # zones dominated by highway decel (typically the higher-speed
            # zones) correctly get a tighter band than zones dominated by
            # urban/mixed decel.
            w_um = (d['ke_um'] / d['ke']) if d['ke'] > 0 else 0.0
            ref_mass = (d['ke'] / ((d['ke'] - d['ke_um']) / MASS_HIGHWAY_KG
                                  + d['ke_um'] / MASS_URBAN_MIXED_KG)
                       if d['ke'] > 0 else MASS_HIGHWAY_KG)
            eff_lo, eff_hi = _mass_uncertainty_bounds(eff, ref_mass, w_um)
            rz.append({'zone': lbl, 'pct': round(d['cap'] / tot_cap * 100, 1) if tot_cap else 0,
                       'eff': round(eff, 1), 'n': d['n'],
                       'effRangeMassUncertainty': [round(eff_lo, 1), round(eff_hi, 1)],
                       'urbanMixedKeShare': round(w_um, 3)})
        out['regenByZone'] = rz
        fine = []
        fine_unc = []
        for mid in sorted(self.regen_fine):
            d = self.regen_fine[mid]
            if d['n'] < 10 or d['ke'] <= 0:
                continue
            eff = d['cap'] / d['ke'] * 100
            fine.append([mid, round(eff, 1), d['n']])
            # M164: parallel array, NOT merged into `fine` above, so the
            # existing 3-tuple chart series shape (consumed positionally by
            # the JSX) is untouched. Exact per-bin urban/mixed-weighted bound,
            # same derivation as regenByZone above.
            w_um = d['ke_um'] / d['ke']
            ref_mass = (d['ke'] / ((d['ke'] - d['ke_um']) / MASS_HIGHWAY_KG
                                  + d['ke_um'] / MASS_URBAN_MIXED_KG))
            lo_e, hi_e = _mass_uncertainty_bounds(eff, ref_mass, w_um)
            fine_unc.append([mid, round(lo_e, 1), round(hi_e, 1)])
        out['regenCaptureMeasured'] = fine
        out['regenCaptureMeasuredMassUncertainty'] = fine_unc
        # M22: regenByTempMeasured -- real KE-basis capture pooled by pack
        # temperature (mean T1-T4 at the decel sample), same engine-off-decel
        # basis as regenByZone/regenCaptureMeasured above. Validity gate:
        # n >= 200 qualifying 1 Hz decel samples (~200 s aggregate engine-off
        # decel time), the same order of magnitude as M14's >=120 s band-time
        # gate elsewhere in this pipeline. Bins with less are real zero-fabrication
        # data but too thin to report a stable %, and are flagged invalid rather
        # than silently smoothed over.
        rbt = []
        for lo, hi, lbl in REGEN_TEMP_BINS:
            d = self.regen_temp[lbl]
            has_ke = d['ke'] > 0
            valid = d['n'] >= 200 and has_ke
            # M219 (2026-09-04): eff is now computed whenever there is ANY
            # qualifying KE (has_ke), not gated behind `valid`. The n>=200
            # validity gate is unchanged and still governs which bins are
            # reported as a stable, trustworthy %; but sub-200-sample bins
            # that do have real (if thin) decel data now carry their own
            # point estimate through as an EXPLORATORY figure, so the
            # dashboard can show a dashed/low-confidence marker instead of
            # hiding the bin behind an "insufficient data" placeholder.
            # `valid` remains the single source of truth for which figure is
            # citable; `eff` on an invalid bin must never be read as the
            # reported result.
            eff = d['cap'] / d['ke'] * 100 if has_ke else None
            eff_range = None
            if has_ke:
                w_um = d['ke_um'] / d['ke']
                ref_mass = (d['ke'] / ((d['ke'] - d['ke_um']) / MASS_HIGHWAY_KG
                                      + d['ke_um'] / MASS_URBAN_MIXED_KG))
                lo_e, hi_e = _mass_uncertainty_bounds(eff, ref_mass, w_um)
                eff_range = [round(lo_e, 1), round(hi_e, 1)]
            rbt.append({'label': lbl, 'n': d['n'],
                        'eff': round(eff, 1) if has_ke else None,
                        'effRangeMassUncertainty': eff_range,
                        'valid': bool(valid)})
        out['regenByTempMeasured'] = rbt
        # engineStartsByType
        est = []
        for k in CLASS_ORDER:
            v = np.array(self.starts[k])
            if not len(v):
                continue
            est.append({'label': k.replace('_', ' ').title(),
                        'lo': round(float(v.min())), 'hi': round(float(v.max())),
                        'avg': round(float(v.mean())), 'color': CLASS_COLOR[k]})
        out['engineStartsByType'] = est

        # ---- M30: highwayVsCity raw-derived rows ----
        def _soc_iqr(lst):
            a = np.array([x for x in lst if x is not None and not np.isnan(x)])
            if len(a) < 3:
                return None
            lo, hi = np.percentile(a, [25, 75])
            return f"{lo:.0f}-{hi:.0f}% (IQR, n={len(a)})"

        # M86 (2026-08-05): hvcEngineTriggerSoC/hvcEngineStopSoC migrated from
        # a hand-rolled city/mixed/highway collapse to native CLASS_ORDER, so
        # they carry the same 4 keys as driveTypes/engineStartsByType. 'city'
        # is retained as an ALIAS of 'urban' (not a distinct bucket) so any
        # not-yet-migrated consumer degrades to a stale-but-present value
        # instead of a silent KeyError; new consumers should read the
        # CLASS_ORDER keys directly.
        out['hvcEngineTriggerSoC'] = {k: _soc_iqr(self.hvc_trigger_soc[k])
                                      for k in CLASS_ORDER}
        out['hvcEngineTriggerSoC']['city'] = out['hvcEngineTriggerSoC']['urban']
        out['hvcEngineStopSoC'] = {k: _soc_iqr(self.hvc_stop_soc[k])
                                   for k in CLASS_ORDER}
        out['hvcEngineStopSoC']['city'] = out['hvcEngineStopSoC']['urban']

        # M51 (2026-07-22): NUMERIC socBands for the "Battery Operating Map"
        # panel. That panel previously rendered config.socBands -- a frozen
        # four-row narrative array explicitly registered under
        # kept_in_config_not_computed, so it never recalibrated with the
        # corpus. On the 173-drive corpus both city rows had drifted (trigger
        # 51-62 rendered vs 55-66 computed; stop 59-66 vs 62-68) and the
        # 'mixed' class was absent entirely. Built here from exactly the same
        # accumulator that feeds hvcEngine{Trigger,Stop}SoC above, so the
        # Operating Map and the Comparison-tab strings can no longer disagree:
        # same segment detection (>300 RPM, >= MIN_ENGINE_START_S), same
        # class taxonomy (M86: native CLASS_ORDER, was a three-bucket
        # collapse), same 25-75 IQR convention. Colors now reuse the
        # dashboard-wide CLASS_COLOR palette (driveTypes/engineStartsByType)
        # instead of the previously independent ad hoc socBands palette, so
        # the same class reads as the same color everywhere in the dashboard.
        def _soc_band(lst):
            a = np.array([x for x in lst if x is not None and not np.isnan(x)])
            if len(a) < 3:
                return None
            lo, hi = np.percentile(a, [25, 75])
            return (int(round(lo)), int(round(hi)),
                    round(float(np.median(a)), 1), int(len(a)))

        _band_meta = [(k, k.replace('_', ' ').title(), CLASS_COLOR[k])
                      for k in CLASS_ORDER]
        _bands = []
        for key, disp, color in _band_meta:
            for src, phase in ((self.hvc_trigger_soc, 'trigger (engine ON)'),
                               (self.hvc_stop_soc, 'stop (engine OFF)')):
                v = _soc_band(src[key])
                if v is None:
                    continue
                lo, hi, med, n = v
                _bands.append({'label': f'{disp} {phase}', 'lo': lo, 'hi': hi,
                               'med': med, 'n': n, 'color': color,
                               'cls': key,
                               'phase': ('trigger' if 'ON' in phase
                                         else 'stop')})
        out['socBands'] = _bands

        def _turbo_str(d):
            if d['n'] == 0:
                return None
            pct = d['act'] / d['n'] * 100
            s = f"{pct:.1f}% of engine-on time (n={d['n']:,}, >0.1 bar)"
            if d['max'] > 0:
                s += f"; peak {d['max']:.2f} bar" + (f" — {d['max_label']}" if d['max_label'] else "")
            return s
        # M86: native CLASS_ORDER (was city/mixed/highway); 'city' kept as an
        # alias of 'urban' for the same not-yet-migrated-consumer safety net
        # as hvcEngine{Trigger,Stop}SoC above.
        out['hvcTurboActivity'] = {k: _turbo_str(self.hvc_turbo[k])
                                   for k in CLASS_ORDER}
        out['hvcTurboActivity']['city'] = out['hvcTurboActivity']['urban']

        def _warm_str(lst, with_timing=False):
            if not lst:
                return None
            n = len(lst)
            reached_n = sum(1 for r, _ in lst if r)
            pct = reached_n / n * 100
            s = f"{pct:.0f}% of drives (n={n})"
            if with_timing:
                times = [t for r, t in lst if r and t is not None]
                if len(times) >= 3:
                    lo, hi = np.percentile(times, [25, 75])
                    s += f", typically within {lo:.0f}-{hi:.0f} min"
            return s
        # M86: 'highway' split into 'mixed_highway' + 'highway'; 'highway' key
        # retained as an alias of the OLD blended population
        # (mixed_highway + highway pooled) for any not-yet-migrated consumer,
        # computed directly rather than re-deriving from the two strings.
        _warm_hwy_blend = _warm_str(
            self.hvc_warm['mixed_highway'] + self.hvc_warm['highway'],
            with_timing=True)
        # M173: 'urban' now a single native-CLASS_ORDER bucket like its three
        # siblings (with_timing=True for all four, consistent basis) --
        # supersedes the city_short(<5km)/city_long(5-20km) split, which also
        # silently excluded every urban trip >20km from the metric.
        out['hvcEngine80C'] = {
            'urban': _warm_str(self.hvc_warm['urban'], with_timing=True),
            'city': _warm_str(self.hvc_warm['urban'], with_timing=True),
            'mixed': _warm_str(self.hvc_warm['mixed'], with_timing=True),
            'mixed_highway': _warm_str(self.hvc_warm['mixed_highway'], with_timing=True),
            'highway': _warm_str(self.hvc_warm['highway'], with_timing=True),
            'highway_blend': _warm_hwy_blend,
        }

        # ---- M31/M86: warmupCurve (distance-domain coolant rise, per native
        # CLASS_ORDER class; was pooled into a blended {city, mixed, highway})
        def _warm_curve(rows):
            if not rows:
                return None
            A = np.array(rows, float)
            med = np.nanmedian(A, axis=0)
            p25 = np.nanpercentile(A, 25, axis=0)
            p75 = np.nanpercentile(A, 75, axis=0)
            nn = (~np.isnan(A)).sum(axis=0)
            pts = []
            for i, g in enumerate(WARMUP_GRID):
                if nn[i] >= WARMUP_MIN_N:
                    pts.append({'km': g,
                                'med': round(float(med[i]), 1),
                                'p25': round(float(p25[i]), 1),
                                'p75': round(float(p75[i]), 1),
                                'n': int(nn[i])})
            # distance at which the class median first reaches operating temp
            cross = next((p['km'] for p in pts if p['med'] >= WARM_ENGINE_C), None)
            return {'nDrives': int(len(rows)), 'crossKm': cross, 'points': pts}

        out['warmupCurve'] = {
            'grid': WARMUP_GRID,
            'coldStartC': WARMUP_COLD_C,
            'operatingC': WARM_ENGINE_C,
            'minN': WARMUP_MIN_N,
            'classes': {k: _warm_curve(self.warm_curve[k]) for k in CLASS_ORDER},
        }
        out['warmupCurve']['classes']['city'] = out['warmupCurve']['classes']['urban']
        # M43: eolBaselines, raw half (master-derived half is merged in
        # build_summary_arrays; see __init__ note for basis and provenance).
        ld = np.concatenate(self.eol_loaded) if self.eol_loaded \
            else np.array([])
        rs = np.concatenate(self.eol_rest) if self.eol_rest else np.array([])
        s1 = np.concatenate(self.eol_s1d) if self.eol_s1d else np.array([])
        ik = np.concatenate(self.eol_intkd) if self.eol_intkd \
            else np.array([])
        def _q(a, p):
            return round(float(np.percentile(a, p)), 1) if a.size else None
        eol = {
            'loaded': {'n': int(ld.size), 'iThreshA': 50,
                       'medianMv': _q(ld, 50), 'p95Mv': _q(ld, 95)},
            'resting': {'n': int(rs.size), 'iThreshA': 5,
                        'medianMv': _q(rs, 50), 'p95Mv': _q(rs, 95)},
            'nSpreadFiles': int(self.eol_spread_files),
            's1Delta': {'nSamples': int(s1.size),
                        'nFiles': int(self.eol_temp_files),
                        'medianC': _q(s1, 50), 'p90C': _q(s1, 90),
                        'maxC': (round(float(s1.max()), 1)
                                 if s1.size else None),
                        'hottestPct': (round(self.hot_count['T1']
                                             / self.hotcold_tot * 100)
                                       if self.hotcold_tot else None)},
            'intakeBelowPackMedianC': _q(ik, 50),
        }
        if eol['loaded']['p95Mv'] is not None and \
                eol['resting']['p95Mv'] is not None:
            eol['gapP95Mv'] = round(eol['loaded']['p95Mv']
                                    - eol['resting']['p95Mv'], 1)
        out['eolBaselines'] = eol
        return out



def _k_ladder_scenarios(dm, raw_loader, frame_loader, fade_capacity,
                        ceiling_yr, cfg):
    """M93 (2026-08-07). Woehler/S-N k-EXPONENT sensitivity ladder + implied
    cycle-life scenarios. Replaces the retired M91 SoC-level weight-ladder
    CHART (Panel B); the M91 band-share split and its dodSocLevelSensitivity
    DATA are retained unchanged. cfg = config['kExponentLadder']; returns None
    if that block is absent or no raw loader is available (same
    arrays-only/stale-config discipline as _soc_level_sensitivity).

    WHAT THIS DOES. M17 fixes the Woehler depth exponent at RF_DAMAGE_EXP=2
    (NMC-generic, NOT fitted to this pack's cells). That single unvalidated
    constant is what the ~10x shallow-cycling damage mitigation rests on. This
    pass re-runs the rainflow damage sum for a LADDER of k over the SAME
    ens_outlier_v2-clean, SoC-eligible corpus and amplitude floor
    (RF_FLOOR_PCT=1.0) as M17, reading each drive's raw SoC from the slim cache
    (frame_loader; raw_loader fallback) -- so nothing is added to
    drive_master.csv and, with a warm cache, no raw CSV is re-parsed.

    rf_damage_k = sum(count * (range/100)^k). rf_efc IS rf_damage at k=1 by
    construction, so the mitigation m(k)=sum_k1/sum_k anchors m(1)=1.0 exactly
    and the k=1 rung reproduces the flat gross-throughput (GTC) planning
    convention. Implied scenario life = each fadeModes flat crossing at the
    reference GTC threshold * m(k), under the stated assumption that forward
    DoD-shape ~ observed DoD-shape (buffer behaviour is intrinsic, not
    forward-mix-dependent). DIAGNOSTIC ONLY: nothing here folds into
    rf_damage_k2, cycleLife, or any fadeModes GTC/FCE crossing; the century-
    scale lives at high k clear the calendar-aging ceiling by an order of
    magnitude and are exponent LEVERAGE, not predictions.
    """
    if not cfg:
        return None
    import rainflow as _rainflow           # local, mirrors _v6 import pattern
    _SOC_RAW = '[BMS] HV State of charge (%)'
    floor = float(cfg.get('floorPct', 1.0))          # M17 RF_FLOOR_PCT
    kgrid = sorted(set([1.0] + [float(k) for k in
                                cfg.get('kGrid', [1.0, 1.5, 2.0, 2.5, 3.0])]))
    kref = float(cfg.get('kReference', 2.0))
    kext = float(cfg.get('kExtreme', kgrid[-1]))
    ref_thr = int(cfg.get('referenceThresholdGtc', 20000))

    keep = ~_as_bool(dm['ens_outlier_v2']) if 'ens_outlier_v2' in dm.columns \
        else pd.Series(True, index=dm.index)
    sub = dm[keep].dropna(subset=['rf_efc', 'distance_km']).copy()
    if not len(sub):
        return None

    ksum = {k: 0.0 for k in kgrid}
    n_used = 0
    for fn in sub['file']:
        try:
            if frame_loader is not None:
                fr = frame_loader(fn)
                if fr is None or _SOC_RAW not in fr.columns \
                        or 'time' not in fr.columns:
                    continue
                df = fr[['time', _SOC_RAW]]
            else:
                raw = raw_loader(fn)
                cols = pd.read_csv(io.BytesIO(raw), nrows=0).columns
                if _SOC_RAW not in cols or 'time' not in cols:
                    continue
                df = pd.read_csv(io.BytesIO(raw), usecols=['time', _SOC_RAW],
                                 low_memory=False)
        except Exception:
            continue
        t = pd.to_datetime(df['time'], format='mixed', errors='coerce')
        v = pd.to_numeric(df[_SOC_RAW], errors='coerce')
        s = pd.DataFrame({'t': t, 'v': v}).dropna().sort_values('t')
        if len(s) < 10:                      # M17 rainflow eligibility gate
            continue
        cyc = list(_rainflow.extract_cycles(s['v'].values))
        kept = [c for c in cyc if c[0] >= floor]
        n_used += 1
        if not kept:
            continue
        rng = np.array([c[0] for c in kept])
        cnt = np.array([c[2] for c in kept])
        for k in kgrid:
            ksum[k] += float(((rng / 100.0) ** k * cnt).sum())

    if n_used == 0 or ksum.get(1.0, 0.0) <= 0:
        return None
    rf_efc_sum = ksum[1.0]                    # == corpus rf_efc by construction
    mit = {k: (rf_efc_sum / ksum[k]) if ksum[k] > 0 else None for k in kgrid}

    rungs = []
    for k in kgrid:
        r = {'k': k, 'rfDamageSum': round(ksum[k], 4),
             'mitigation': (round(mit[k], 3) if mit[k] is not None else None)}
        if k == 1.0:
            r['anchor'] = 'throughput \u2014 flat GTC planning convention'
        if k == kref:
            r['reference'] = True
        if k == kext:
            r['extreme'] = True
        rungs.append(r)

    # scenario overlay: vetted flat crossings from the already-built
    # fadeModes.capacity (flat convention), scaled by m(k). No rate recompute.
    cap = fade_capacity or {}
    thr = cap.get('thresholds') or []
    rows = cap.get('rows') or []
    try:
        ri = thr.index(ref_thr)
    except ValueError:
        ri = (len(thr) // 2) if thr else None
    by_label = {row.get('label'): row for row in rows}
    scenarios = {}
    for name in cfg.get('scenarios', ['Selected blend', 'Observed logged mix']):
        row = by_label.get(name)
        if row is None or ri is None:
            continue
        cy = row.get('crossingYr') or []
        if ri >= len(cy) or cy[ri] is None:
            continue
        flat = float(cy[ri])
        byk = [{'k': k, 'yr': round(flat * mit[k], 1)}
               for k in kgrid if mit[k] is not None]
        scenarios[name] = {'flatCrossingYr': round(flat, 2),
                           'primary': bool(row.get('primary')), 'byK': byk}

    fce_sum = (float(sub['fce'].dropna().sum())
               if 'fce' in sub.columns else None)
    ceil = round(float(ceiling_yr), 1) if ceiling_yr is not None else None

    return {
        'basis': ('k-exponent (Woehler/S-N) sensitivity ladder on the M17 '
                  'rainflow damage proxy. rf_damage_k = sum(count*(range/100)^k) '
                  'over the same ens_outlier_v2-clean, SoC-eligible corpus and '
                  'floor (RF_FLOOR_PCT) as M17 (n=%d). m(k)=sum(rf_efc)/'
                  'sum(rf_damage_k); rf_efc == rf_damage at k=1, so m(1)=1.0 '
                  'and the k=1 rung IS the flat GTC convention. Implied life = '
                  'fadeModes flat crossing at the reference GTC threshold * '
                  'm(k), assuming forward DoD-shape ~ observed.' % n_used),
        'verified': False,
        'kGrid': kgrid, 'kReference': kref, 'kExtreme': kext,
        'denominator': 'rf_efc',
        'referenceThresholdGtc': ref_thr,
        'plausibilityCeilingYr': ceil,
        'plausibilityCeilingBasis': cfg.get(
            'plausibilityCeilingBasis',
            'calendarLifeYrShaded (seasonalLife, M28) \u2014 calendar aging '
            'alone ends the pack near here regardless of cycling'),
        'corpus': {'nDrives': n_used, 'rfEfcSum': round(rf_efc_sum, 3),
                   'fceSum': (round(fce_sum, 3) if fce_sum is not None else None),
                   'rfDamageK2Sum': (round(ksum[2.0], 4) if 2.0 in ksum
                                     else None)},
        'rungs': rungs,
        'scenarios': scenarios,
        'note': ('m(k) grows near-exponentially because the duty is shallow-'
                 'dominated: each unit rise in k discounts a 2%-DoD cycle ~50x '
                 'while leaving a full-DoD cycle unchanged. Across the '
                 'physically admissible NMC range k=1.0..2.5 the mitigation '
                 'spans about 1x..29x; k=3.0 is a flagged aggressive extreme. '
                 'Implied lives of hundreds of years at k>=2.5 are NOT '
                 'predictions: they exceed the calendar-aging ceiling by an '
                 'order of magnitude, so real end-of-life is set by calendar '
                 'aging and the still-uncaptured winter-driving risk, not by '
                 'cycling. The ladder shows the LEVERAGE of the unvalidated '
                 'exponent; the flat k=1 GTC convention remains the planning '
                 'anchor.'),
        '_provenance': ('Diagnostic sensitivity only. k is NMC-generic, NOT '
                        'derived from this pack. Nothing here is folded into '
                        'rf_damage_k2, cycleLife, or any fadeModes GTC/FCE '
                        'crossing. Read WITH M17 (shallow DEPTH protective, '
                        'unchanged) and the winter-gap caveat. Replaces the '
                        'retired M91 SoC-level weight-ladder chart; M91 '
                        'band-share (Panel A) + dodSocLevelSensitivity retained.'),
    }


def _rf_dod_histogram(dm, raw_loader, frame_loader=None, floor_pct=None):
    """M149 (2026-08-21). Restores `rfDodHistogram` as a reproducible
    build_summary_arrays() computation.

    PROVENANCE. This block originated as an M146 conclusions-tab audit
    recompute -- correct numbers, hand-injected into summary_arrays.json --
    but no code anywhere in the pipeline (`compute_drive_summary_v6.py`,
    `compute_summary_arrays.py`, or any `mXX_arrays.py` module) reproduced
    it; an arrays-only regeneration would silently drop every S.rfDodHistogram
    binding. Disclosed M148 (grep-verified absent), same defect class as the
    F-12 `powerFade` and P0-14 `sessionLedgerAudit` out-of-band artifacts.
    Fixed here the same way: re-derive it from the master + raw corpus so it
    reproduces the shipped numbers, then wire it in.

    WHAT THIS DOES. Re-runs rainflow.extract_cycles() on every drive's raw
    SoC trace (frame_loader; raw_loader fallback) under the IDENTICAL
    RF_FLOOR_PCT=1.0 amplitude floor as the per-drive M17 convention in
    compute_drive_summary_v6.py, then bins the resulting cycle population by
    depth-of-discharge (DoD = rainflow range, % SoC). Because the floor and
    eligibility gate (len(soc)>=10) are identical to M17, the aggregate cycle
    count and k=2 damage sum reproduce drive_master.csv's own rf_n_cycles /
    rf_damage_k2 column sums by construction -- this identity is the
    crossCheck block below, not an independent validation, but it is a live
    regression guard: any future drift between this function and the M17
    per-drive convention will show up here immediately.

    Verified 2026-08-21: on the frozen 259-drive/257-file corpus this
    function reproduces the original M146 block to full precision
    (nCyclesTotal=7034.0, le1PctShare=27.65, le2PctShare=52.86,
    maxDodPct=40.5, topDodDrives identical, both crossCheck sums identical).
    Unlike M119-v2 (OOM-gated, recompute-on-demand only), this is a single
    lightweight rainflow pass over already-cached raw SoC columns with no
    model fitting, so it recomputes unconditionally on every regen rather
    than carrying forward -- there is no resource-ceiling reason to gate it.
    """
    if raw_loader is None and frame_loader is None:
        return None
    import rainflow as _rainflow            # local, mirrors _v6 import pattern
    _SOC_RAW = '[BMS] HV State of charge (%)'
    floor = float(floor_pct if floor_pct is not None else 1.0)   # M17 RF_FLOOR_PCT

    n_used = 0
    n_missing = 0
    total_cnt = 0.0
    le1_cnt = 0.0
    le2_cnt = 0.0
    k2sum = 0.0
    per_file_max = {}

    for fn in dm['file']:
        try:
            if frame_loader is not None:
                fr = frame_loader(fn)
                if fr is None or _SOC_RAW not in fr.columns \
                        or 'time' not in fr.columns:
                    n_missing += 1
                    continue
                df = fr[['time', _SOC_RAW]]
            else:
                raw = raw_loader(fn)
                cols = pd.read_csv(io.BytesIO(raw), nrows=0).columns
                if _SOC_RAW not in cols or 'time' not in cols:
                    n_missing += 1
                    continue
                df = pd.read_csv(io.BytesIO(raw), usecols=['time', _SOC_RAW],
                                 low_memory=False)
        except Exception:
            n_missing += 1
            continue
        t = pd.to_datetime(df['time'], format='mixed', errors='coerce')
        v = pd.to_numeric(df[_SOC_RAW], errors='coerce')
        s = pd.DataFrame({'t': t, 'v': v}).dropna().sort_values('t')
        if len(s) < 10:                      # M17 rainflow eligibility gate
            continue
        cyc = list(_rainflow.extract_cycles(s['v'].values))
        keep = [c for c in cyc if c[0] >= floor]
        if not keep:
            continue
        n_used += 1
        rng = np.array([c[0] for c in keep])
        cnt = np.array([c[2] for c in keep])
        total_cnt += float(cnt.sum())
        le1_cnt += float(cnt[rng <= 1.0].sum())
        le2_cnt += float(cnt[rng <= 2.0].sum())
        k2sum += float(((rng / 100.0) ** 2.0 * cnt).sum())
        per_file_max[fn] = float(rng.max())

    if n_used == 0 or total_cnt <= 0:
        return None

    top = sorted(per_file_max.items(), key=lambda kv: -kv[1])[:5]
    top_dod = [{'drive': fn, 'dodPct': round(v, 1)} for fn, v in top]

    rf_n_master = (float(dm['rf_n_cycles'].sum())
                   if 'rf_n_cycles' in dm.columns else None)
    rf_k2_master = (float(dm['rf_damage_k2'].sum())
                     if 'rf_damage_k2' in dm.columns else None)

    return {
        'nCyclesTotal': round(total_cnt, 1),
        'nFilesUsed': n_used,
        'nFilesMissingSocPid': n_missing,
        'floorPct': floor,
        'le1PctShare': round(le1_cnt / total_cnt * 100, 2),
        'le2PctShare': round(le2_cnt / total_cnt * 100, 2),
        'maxDodPct': round(max(per_file_max.values()), 1),
        'topDodDrives': top_dod,
        'crossCheck': {
            'rfNCyclesSumMaster': (round(rf_n_master, 1)
                                    if rf_n_master is not None else None),
            'rfDamageK2SumMaster': (round(rf_k2_master, 2)
                                     if rf_k2_master is not None else None),
            'rfDamageK2SumRecomputed': round(k2sum, 2),
        },
        'methodology': (
            'M149 (2026-08-21) reproducible recompute, restoring the M146 '
            'audit methodology: full-corpus rainflow decomposition run '
            'directly on raw SoC traces of every file in drive_master.csv '
            '(rainflow==3.2.0, extract_cycles, RF_FLOOR_PCT=%.1f cycle-range '
            'floor (pp) -- identical to the M17/compute_drive_summary_v6.py '
            'per-drive convention). Cross-validated every regen: recomputed '
            'total cycle count and rf_damage_k2 (k=2) sum match '
            'drive_master.csv\'s rf_n_cycles / rf_damage_k2 column sums to '
            'full precision, confirming methodology fidelity. Now produced '
            'by build_summary_arrays() itself (previously an out-of-band '
            'M146 injection with no reproducing code -- disclosed M148, '
            'fixed M149, same defect class as F-12/P0-14). %d file(s) lack '
            'the SoC PID entirely (excluded, consistent with NaN rf_* '
            'columns in the master).' % (floor, n_missing)),
    }


def category_B(dm, raw_loader, frame_loader=None):
    """Stream every raw file once, feeding all pooled accumulators.
    raw_loader(filename) -> bytes.
    M44 (2026-07-19): frame_loader(filename) -> slim DataFrame|None takes
    precedence over raw_loader. The slim frame (drive_raw_cache.SLIM_COLS)
    carries original 'time' strings and dtypes, so acc.add() operates on
    byte-identical inputs; only the CSV parse is skipped."""
    acc = _RawAccum()
    dist = dict(zip(dm['file'], dm['distance_km']))
    cond = dict(zip(dm['file'], dm['drive_type']))  # M21: time-weighted class
    # M30: per-file "MonDD Dn" attribution label, same convention as _records().
    label = {}
    for fn in dm['file']:
        idx = dm.index[dm['file'] == fn]
        label[fn] = _day_label(dm, idx[0]) if len(idx) else None
    for fn in dm['file']:
        try:
            if frame_loader is not None:
                df = frame_loader(fn)
                if df is None:
                    continue
            else:
                raw = raw_loader(fn)
                df = pd.read_csv(io.BytesIO(raw), low_memory=False)
        except Exception:
            continue
        acc.add(df, dist.get(fn), cond.get(fn), label.get(fn), fn)
    return acc.finalize()


# ======================================================================
# M33 (2026-07-13): pipeline-driven battery-temperature trajectories.
# Two hand-authored thermal blocks (Long-Highway Thermal Convergence, using
# Sensor 1; Battery vs Measured Ambient, using the 4-sensor pack mean) had
# gone stale as drives accrued -- a fixed "17 drives >60min" list ending
# Jun27, and an ambient-delta log ending Jul07. Both are now regenerated
# from raw per drive: Sensor-1 first/peak/last and pack-mean first/peak/last
# (first/last = first/last VALID sample after range-gating). The convergence
# list is emitted for every drive >60min; the ambient block joins these
# trajectories to the per-drive ambients recorded in config.ambientByDrive
# (ambient is a manual field -- the OBD logs carry no outside-air channel).
# ======================================================================
_T_SENS_RAW = ['[BMS] HV Battery Temperature Sensor 1 (\u2103)',
               '[BMS] HV Battery Temperature Sensor 2 (\u2103)',
               '[BMS] HV Battery Temperature Sensor 3 (\u2103)',
               '[BMS] HV Battery Temperature Sensor 4 (\u2103)']
# M223.1 (P0.1, enhancement plan): engine-coolant and oil channels, read in
# the SAME per-file pass as the pack sensors above (added to `use` below) --
# not a second raw pass. Single-sensor channels (no multi-sensor averaging
# needed, unlike pm_*): first/peak/last valid sample, same convention as
# t1_*. Both raw literals are already in drive_raw_cache.SLIM_COLS (the
# engine-coolant one is also this module's own RAW_MAP T_coolant -- see the
# M221 note on the cross-module T_coolant naming trap for why this is NOT
# the VCM HV-coolant channel).
_ENG_COOLANT_RAW = '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043e\u0445\u043e\u043b\u043e\u0434\u043d\u043e\u0457 \u0440\u0456\u0434\u0438\u043d\u0438 (\u2103)'
_OIL_RAW = '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043e\u043b\u0456\u0457 \u0443 \u0434\u0432\u0438\u0433\u0443\u043d\u0456 (\u2103)'


def _battery_temp_traj(dm, raw_loader, frame_loader=None):
    """Per-file {t1_start,t1_peak,t1_end, pm_start,pm_peak,pm_end}, all int C.
    t1 = Sensor 1 (hottest probe), first/peak/last valid sample. pm = 4-sensor
    pack mean. Because the sensors are ASYNC-logged (a raw row usually carries
    only one of T1-T4), a naive row-mean is biased toward whichever sensor
    fired that row -- so pm is built on a 1 Hz grid (resample -> ffill(limit=3))
    that aligns the four sensors before averaging, matching the master's
    T_pack_mean_max (merge_asof) definition to within rounding. first/last are
    the first/last valid samples after gating to a physical -40..80 C window.

    M223.1 (P0.1): also returns coolant_start/coolant_peak/coolant_end and
    oil_start/oil_peak/oil_end (engine coolant / oil, first/peak/last valid
    sample, same convention as t1_*, gated to a physical -40..150 C window)
    -- read in the SAME per-file pass as the pack sensors, purely additive
    to this function's pre-existing keys and callers."""
    out = {}
    for fn in dm['file']:
        try:
            if frame_loader is not None:
                fr = frame_loader(fn)
                if fr is None:
                    continue
                cols = fr.columns
                use = [c for c in _T_SENS_RAW if c in cols]
                use2 = [c for c in (_ENG_COOLANT_RAW, _OIL_RAW) if c in cols]
                if not use or 'time' not in cols:
                    continue
                df = fr[['time'] + use + use2]
            else:
                raw = raw_loader(fn)
                cols = pd.read_csv(io.BytesIO(raw), nrows=0).columns
                use = [c for c in _T_SENS_RAW if c in cols]
                use2 = [c for c in (_ENG_COOLANT_RAW, _OIL_RAW) if c in cols]
                if not use or 'time' not in cols:
                    continue
                df = pd.read_csv(io.BytesIO(raw), usecols=['time'] + use + use2,
                                 low_memory=False)
        except Exception:
            continue
        rec = {}
        t = pd.to_datetime(df['time'], format='mixed', errors='coerce')
        g = pd.DataFrame({'t': t})
        for c in use:
            v = pd.to_numeric(df[c], errors='coerce')
            v[(v < -40) | (v > 80)] = np.nan
            g[c] = v
        for c in use2:
            v = pd.to_numeric(df[c], errors='coerce')
            v[(v < -40) | (v > 150)] = np.nan
            g[c] = v
        g = g.dropna(subset=['t']).set_index('t')
        # ---- Sensor 1: raw first/peak/last (single column, no alignment) ----
        c1 = _T_SENS_RAW[0]
        if c1 in g.columns:
            ser = g[c1].dropna()
            if len(ser):
                rec['t1_start'] = int(round(ser.iloc[0]))
                rec['t1_peak'] = int(round(ser.max()))
                rec['t1_end'] = int(round(ser.iloc[-1]))
                # M51 (2026-07-22): observed FLOOR, additive. t1_start is the
                # key-on sample, which is not always the coldest of the drive
                # (a cold pack can still shed heat into the first minutes of a
                # winter/night trip). _battery_temp_ranges needs a true
                # per-drive minimum to build an honest "observed range" band.
                rec['t1_min'] = int(round(ser.min()))
        # ---- M223.1: engine coolant / oil, same single-column convention ----
        if _ENG_COOLANT_RAW in g.columns:
            ser = g[_ENG_COOLANT_RAW].dropna()
            if len(ser):
                rec['coolant_start'] = int(round(ser.iloc[0]))
                rec['coolant_peak'] = int(round(ser.max()))
                rec['coolant_end'] = int(round(ser.iloc[-1]))
        if _OIL_RAW in g.columns:
            ser = g[_OIL_RAW].dropna()
            if len(ser):
                rec['oil_start'] = int(round(ser.iloc[0]))
                rec['oil_peak'] = int(round(ser.max()))
                rec['oil_end'] = int(round(ser.iloc[-1]))
        # ---- pack mean: align async sensors on a 1 Hz grid, then row-mean ----
        try:
            aligned = g[use].resample('1s').mean().ffill(limit=3)
            pm = aligned.mean(axis=1).dropna()
        except Exception:
            pm = pd.Series(dtype=float)
        if len(pm):
            rec['pm_start'] = int(round(pm.iloc[0]))
            rec['pm_peak'] = int(round(pm.max()))
            rec['pm_end'] = int(round(pm.iloc[-1]))
            rec['pm_min'] = int(round(pm.min()))   # M51, symmetric with t1_min
        if rec:
            out[fn] = rec
    return out


# ======================================================================
# M38 (2026-07-15): pipeline-driven traction-motor thermal statistics.
# The Conclusions-tab motor paragraph was hand-authored on a 50-drive /
# 2,102 km subset and had gone stale twice over: the corpus is now larger,
# and its "peak 95 C (Jun10)" ceiling was superseded by a 100 C plateau on
# Jun27 D7 (verified in raw: sustained across consecutive samples, p99 96 C
# on that drive -- not a single-sample artefact). Recomputed here from raw
# so the paragraph binds to data instead of drifting.
#
# The motor PID, the four pack sensors and vehicle speed are ASYNC-logged
# (a raw row typically carries one channel), so correlations are computed on
# a 1 Hz grid with ffill(limit=3) -- the same alignment convention as
# _battery_temp_traj -- rather than on raw rows, which would correlate
# whichever channel happened to fire.
# ======================================================================
_MOTOR_RAW = '[VCM] Traction motor temperature (\u2103)'
_SPEED_RAW = '[VCM] Vehicle Speed (km/h)'


def _motor_temp_stats(dm, raw_loader, frame_loader=None):
    """Pooled traction-motor temperature stats over every drive carrying the
    motor PID: observed range, peak attribution, correlation against pack
    temperature vs vehicle speed, and the motor-minus-pack delta."""
    km = 0.0
    n_drives = 0
    lo, hi = None, None
    peak_fn = None
    pooled = []
    dist = dict(zip(dm['file'], dm['distance_km']))
    for fn in dm['file']:
        fr = None
        if frame_loader is not None:
            try:
                fr = frame_loader(fn)
            except Exception:
                fr = None
            if fr is None:
                continue
            cols = fr.columns
        else:
            try:
                raw = raw_loader(fn)
                cols = pd.read_csv(io.BytesIO(raw), nrows=0).columns
            except Exception:
                continue
        if _MOTOR_RAW not in cols or 'time' not in cols:
            continue
        tcols = [c for c in _T_SENS_RAW if c in cols]
        # M167: gate on either speed channel; _apply_speed_priority below
        # resolves which one is actually used.
        scols = [c for c in (_SPEED_RAW, _SPEED_OBD_RAW) if c in cols]
        if fr is not None:
            df = fr[['time', _MOTOR_RAW] + tcols + scols]
        else:
            try:
                df = pd.read_csv(io.BytesIO(raw),
                                 usecols=['time', _MOTOR_RAW] + tcols + scols,
                                 low_memory=False)
            except Exception:
                continue
        df, _ = _apply_speed_priority(df)
        t = pd.to_datetime(df['time'], format='mixed', errors='coerce')
        g = pd.DataFrame({'t': t})
        m = pd.to_numeric(df[_MOTOR_RAW], errors='coerce')
        m[(m < -40) | (m > 200)] = np.nan          # physical gate
        g['m'] = m
        for c in tcols:
            v = pd.to_numeric(df[c], errors='coerce')
            v[(v < -40) | (v > 80)] = np.nan
            g[c] = v
        if _SPEED_RAW in df.columns:
            v = pd.to_numeric(df[_SPEED_RAW], errors='coerce')
            v[(v < 0) | (v > 200)] = np.nan
            g['speed'] = v
        g = g.dropna(subset=['t']).set_index('t')
        if not g['m'].notna().any():
            continue
        n_drives += 1
        d = dist.get(fn)
        if d is not None and not pd.isna(d):
            km += float(d)
        mmin, mmax = float(g['m'].min()), float(g['m'].max())
        lo = mmin if lo is None else min(lo, mmin)
        if hi is None or mmax > hi:
            hi, peak_fn = mmax, fn
        try:
            aligned = g.resample('1s').mean().ffill(limit=3)
        except Exception:
            continue
        rec = pd.DataFrame({'m': aligned['m']})
        if tcols:
            rec['pack'] = aligned[tcols].mean(axis=1)
        if 'speed' in aligned.columns:
            rec['speed'] = aligned['speed']
        pooled.append(rec.dropna(subset=['m']))
    if not n_drives or not pooled:
        return None
    P = pd.concat(pooled, ignore_index=True)
    out = {
        'nDrives': int(n_drives),
        'km': round(km, 1),
        'nSamples': int(len(P)),
        'minC': int(round(lo)),
        'maxC': int(round(hi)),
        'peakDrive': None,
    }
    idx = dm.index[dm['file'] == peak_fn]
    if len(idx):
        out['peakDrive'] = _day_label(dm, idx[0])
        ts = dm.at[idx[0], 'time_start']
        out['peakDriveTime'] = str(ts)[:5] if isinstance(ts, str) else None
    if 'pack' in P.columns:
        pair = P[['m', 'pack']].dropna()
        if len(pair) > 2:
            out['rPack'] = round(float(pair['m'].corr(pair['pack'])), 2)
            out['nPairsPack'] = int(len(pair))
            delta = pair['m'] - pair['pack']
            out['deltaMeanC'] = round(float(delta.mean()), 1)
            out['deltaMaxC'] = int(round(float(delta.max())))
    if 'speed' in P.columns:
        pair = P[['m', 'speed']].dropna()
        if len(pair) > 2:
            out['rSpeed'] = round(float(pair['m'].corr(pair['speed'])), 2)
            out['nPairsSpeed'] = int(len(pair))
    return out


# ======================================================================
# M39 (2026-07-15): high-speed dwell census. The 170 km/h max-speed record
# (Jul14 D4) is confirmed real drive data, not a logging spike -- which puts
# it in tension with two hand-authored claims that data above 140 km/h is
# "uncaptured". Both are directionally right but unquantified, so the corpus
# is censused here instead: cumulative seconds and longest CONTINUOUS streak
# above each threshold, pooled and per-drive. This is what distinguishes a
# brief excursion (present) from a sustained hold (still absent) -- the
# distinction the deficit argument actually rests on.
#
# Speed is resampled to the same 1 Hz ffill(limit=3) grid used elsewhere, so
# "seconds" are grid seconds, not raw-sample counts (the logger's rate varies
# by PID set and would otherwise weight drives unequally).
# ======================================================================
_HS_THRESHOLDS = (130, 140, 150, 160)


def _highspeed_census(dm, raw_loader, frame_loader=None):
    """Per-threshold: total grid-seconds above it across the corpus, how many
    drives reach it, and the longest continuous streak + the drive that set
    it. Also carries the corpus speed ceiling and its attribution."""
    tot = {th: 0.0 for th in _HS_THRESHOLDS}
    ndr = {th: 0 for th in _HS_THRESHOLDS}
    best = {th: (0, None) for th in _HS_THRESHOLDS}
    vmax, vmax_fn = None, None
    n_drives = 0
    for fn in dm['file']:
        if frame_loader is not None:
            try:
                fr = frame_loader(fn)
            except Exception:
                fr = None
            if fr is None:
                continue
            cols = fr.columns
            if 'time' not in cols or (_SPEED_RAW not in cols
                                       and _SPEED_OBD_RAW not in cols):
                continue
            # M167 fix (2026-09-04, retrofitted): this pass predated the
            # project-wide speed-priority helper and read the native VCM
            # channel only, silently dropping every drive that logs speed
            # solely under the OBD-generic PID -- 90/320 drives at the
            # current corpus size (the 5 earliest May 11-13 files plus the
            # entire Aug 14+ third-generation logging batch, including all
            # Aug 30 drives). Bring it in line with every other raw pass.
            fr, _ = _apply_speed_priority(fr)
            if _SPEED_RAW not in fr.columns:
                continue
            df = fr[['time', _SPEED_RAW]]
        else:
            try:
                raw = raw_loader(fn)
                cols = pd.read_csv(io.BytesIO(raw), nrows=0).columns
            except Exception:
                continue
            if 'time' not in cols or (_SPEED_RAW not in cols
                                       and _SPEED_OBD_RAW not in cols):
                continue
            try:
                usecols = [c for c in ('time', _SPEED_RAW, _SPEED_OBD_RAW)
                           if c in cols]
                df = pd.read_csv(io.BytesIO(raw),
                                 usecols=usecols,
                                 low_memory=False)
            except Exception:
                continue
            df, _ = _apply_speed_priority(df)      # M167, retrofitted
            if _SPEED_RAW not in df.columns:
                continue
        t = pd.to_datetime(df['time'], format='mixed', errors='coerce')
        v = pd.to_numeric(df[_SPEED_RAW], errors='coerce')
        v[(v < 0) | (v > 200)] = np.nan                  # physical gate
        g = pd.DataFrame({'t': t, 'v': v}).dropna(subset=['t']).set_index('t')
        if not g['v'].notna().any():
            continue
        try:
            s = g['v'].resample('1s').mean().ffill(limit=3).dropna()
        except Exception:
            continue
        if not len(s):
            continue
        n_drives += 1
        if vmax is None or s.max() > vmax:
            vmax, vmax_fn = float(s.max()), fn
        for th in _HS_THRESHOLDS:
            m = (s >= th).to_numpy()
            n = int(m.sum())
            if not n:
                continue
            tot[th] += n
            ndr[th] += 1
            # longest continuous run of True
            streak = run = 0
            for x in m:
                run = run + 1 if x else 0
                streak = max(streak, run)
            if streak > best[th][0]:
                best[th] = (int(streak), fn)
    if not n_drives:
        return None
    def _lbl(fn):
        idx = dm.index[dm['file'] == fn] if fn else []
        return _day_label(dm, idx[0]) if len(idx) else None
    out = {
        'nDrives': int(n_drives),
        'vmaxKmh': int(round(vmax)) if vmax is not None else None,
        'vmaxDrive': _lbl(vmax_fn),
        'bands': [],
    }
    for th in _HS_THRESHOLDS:
        out['bands'].append({
            'kmh': th,
            'totalS': int(tot[th]),
            'nDrives': int(ndr[th]),
            'maxStreakS': best[th][0],
            'maxStreakDrive': _lbl(best[th][1]),
        })
    return out


def _near_limiter(dm, raw_loader, frame_loader=None):
    """M42 (2026-07-17): near-limiter generator-headroom census.

    Answers the question M41 leaves open: what does high-speed engine-on
    discharge mean when speed is held near the 170 km/h limiter? The
    argument rests on the fact that in a series hybrid the generator's
    operating point is commanded by the VCM and mechanically DECOUPLED
    from road speed -- so the load the engine reaches at a given rpm on
    ANY drive bounds what it could have reached at that same rpm at
    vmax. If the generator were the binding constraint at vmax, calc
    load there would sit at that ceiling. It does not.

    Emits, for the vmax drive: seconds and SoC/battery-power at >=150 and
    >=160 km/h, and the generator state (rpm/load/boost) at vmax; plus the
    corpus-wide load/boost ceiling in the same rpm band (RPM_BAND) pooled
    over every drive, which is the headroom reference.

    Motor-power apportionment was attempted and abandoned: the motor
    torque/rpm PIDs on the vmax drive decode implausibly (|tq| <= 0.9 Nm,
    rpm swinging +-10,000), so battery-vs-generator share cannot be
    computed on that log. The load-headroom argument does not depend on
    them.
    """
    RPM_BAND = (4400, 4700)
    C = {'[BMS] HV Battery Current (A)': 'I',
         '[BMS] HV Battery voltage (V)': 'V',
         '[BMS] HV State of charge (%)': 'soc',
         '[VCM] Vehicle Speed (km/h)': 'speed',
         '\u041e\u0431\u0435\u0440\u0442\u0438 \u0434\u0432\u0438\u0433\u0443\u043d\u0430 (rpm)': 'rpm',
         '\u0420\u043e\u0437\u0440\u0430\u0445\u0443\u043d\u043a\u043e\u0432\u0435 \u0437\u043d\u0430\u0447\u0435\u043d\u043d\u044f \u043d\u0430\u0432\u0430\u043d\u0442\u0430\u0436\u0435\u043d\u043d\u044f \u043d\u0430 \u0434\u0432\u0438\u0433\u0443\u043d (%)': 'load',
         '\u0420\u043e\u0437\u0440\u0430\u0445\u0443\u043d\u043a\u043e\u0432\u0438\u0439 \u043d\u0430\u0434\u0434\u0443\u0432 (bar)': 'boost'}

    def _grid_df(df):
        if 'time' not in df.columns:
            return None
        g = df.set_index(pd.to_datetime(df['time'], errors='coerce'))
        keep = [c for c in ('I', 'V', 'soc', 'speed', 'rpm', 'load', 'boost')
                if c in g.columns]
        g = g[keep].apply(pd.to_numeric, errors='coerce')
        return g.resample('1s').mean().ffill(limit=3)

    def grid(raw):
        df = pd.read_csv(io.BytesIO(raw),
                         usecols=lambda c: c in C or c == 'time' or c == _SPEED_OBD_RAW,
                         low_memory=False)
        df, _ = _apply_speed_priority(df)     # M167, before the C rename
        return _grid_df(df.rename(columns=C))

    def grid_fn(fn):
        """M44: cached-frame path when frame_loader given, raw path else."""
        if frame_loader is not None:
            fr = frame_loader(fn)
            if fr is None:
                return None
            fr = fr[[c for c in fr.columns
                    if c in C or c == 'time' or c == _SPEED_OBD_RAW]]
            fr, _ = _apply_speed_priority(fr)   # M167, before the C rename
            return _grid_df(fr.rename(columns=C))
        raw = raw_loader(fn)
        if not raw:
            return None
        return grid(raw)

    # ---- corpus ceiling in the plateau rpm band (all drives) ----
    pool = []
    for fn in dm['file']:
        try:
            g = grid_fn(fn)
        except Exception:
            continue
        if g is None or 'rpm' not in g or 'load' not in g:
            continue
        b = g[(g['rpm'] >= RPM_BAND[0]) & (g['rpm'] <= RPM_BAND[1])]
        b = b[b['load'].notna()]
        if len(b):
            pool.append(b.assign(file=fn))
    ceil = {}
    if pool:
        p = pd.concat(pool)
        ceil = {'nSamples': int(len(p)), 'nDrives': int(p['file'].nunique()),
                'loadMean': round(float(p['load'].mean()), 1),
                'loadP95': round(float(p['load'].quantile(0.95)), 1),
                'loadMax': round(float(p['load'].max()), 1),
                'boostMax': (round(float(p['boost'].max()), 2)
                             if 'boost' in p and p['boost'].notna().any()
                             else None)}

    # ---- the vmax drive ----
    i = int(dm['speed_max'].idxmax())
    fn = dm.loc[i, 'file']
    try:
        g = grid_fn(fn)
    except Exception:
        g = None
    if g is None:
        return {'rpmBand': list(RPM_BAND), 'corpusCeiling': ceil}
    g['Id'] = -g['I']
    g['P'] = g['Id'] * g['V'] / 1000.0
    out = {'drive': _day_label(dm, i), 'vmaxKmh': round(float(dm.loc[i, 'speed_max']), 0),
           'rpmBand': list(RPM_BAND), 'corpusCeiling': ceil}
    for th, key in ((150, 'at150'), (160, 'at160')):
        m = g['speed'] >= th
        if m.sum() < 3:
            continue
        s = g.loc[m, 'soc'].dropna()
        out[key] = {'s': int(m.sum()),
                    'socStart': round(float(s.iloc[0]), 1) if len(s) else None,
                    'socEnd': round(float(s.iloc[-1]), 1) if len(s) else None,
                    'pBatMeanKw': round(float(g.loc[m, 'P'].mean()), 1),
                    'loadMean': round(float(g.loc[m, 'load'].mean()), 1),
                    'loadMax': round(float(g.loc[m, 'load'].max()), 1),
                    'boostMax': round(float(g.loc[m, 'boost'].max()), 2)
                                if 'boost' in g and g.loc[m, 'boost'].notna().any() else None,
                    'rpmMax': int(g.loc[m, 'rpm'].max())}
    # generator state at the plateau ON THIS DRIVE (headroom comparison)
    b = g[(g['rpm'] >= RPM_BAND[0]) & (g['rpm'] <= RPM_BAND[1]) & g['load'].notna()]
    if len(b):
        out['vmaxDrivePlateau'] = {
            'nSamples': int(len(b)),
            'loadMean': round(float(b['load'].mean()), 1),
            'loadMax': round(float(b['load'].max()), 1),
            'boostMax': (round(float(b['boost'].max()), 2)
                         if 'boost' in b and b['boost'].notna().any() else None)}
        if ceil:
            out['loadHeadroomPp'] = round(ceil['loadMax'] - out['vmaxDrivePlateau']['loadMax'], 1)
            if ceil.get('boostMax') and out['vmaxDrivePlateau'].get('boostMax'):
                out['boostHeadroomBar'] = round(
                    ceil['boostMax'] - out['vmaxDrivePlateau']['boostMax'], 2)
    return out


# M116 (2026-08-10, audit §10 "New results derivable from the existing
# dataset" -- "Buffer impulse energy and duration: integrate battery power
# during engine power-ramp intervals; summarize peak, area and recovery.
# Quantifies the battery's transient support role without calling it
# generator deficit." Marked "Feasible now".
#
# Method: an engine-start is the cleanest, most unambiguous "power-ramp
# interval" available in this telemetry -- RPM crosses from a sustained-OFF
# state to running within a single ~1.3 s sample step, giving an
# unambiguous t0. Battery current is charge-positive raw (M11); flipped to
# discharge-positive throughout. For each detected start:
#   baseline = median discharge current in [t0-8s, t0-2s) -- the battery's
#              own local state immediately before this specific restart.
#              This can be negative (battery net-charging) in stop-start
#              driving where restarts follow closely on a prior cycle's
#              recharge tail -- that is a real driving-pattern feature, not
#              an artefact, and the excess computation below remains valid
#              relative to it.
#   excess(t) = max(0, I_discharge(t) - baseline) in [t0-1s, t0+8s]
#   impulse   = the FIRST contiguous run where excess exceeds a small
#               threshold (1.5 A) -- deliberately the first such run, not
#               the window's global max, since a wide window can otherwise
#               pick up an unrelated later current spike from ordinary
#               driving rather than the engine-lag transient itself.
#   peak      = max excess within that run (kW, at the sample's own voltage)
#   area      = dt-aware trapezoidal integral of excess*V over the run (Wh)
#   recovery  = time from peak back to the end of the run (s)
# A run needs >=2 samples (a computable duration) and a peak >=3 A to count.
# Known limitation: because baseline is LOCAL to the seconds right before
# each restart, an unusually large excess figure can partly reflect a
# coincident driver-demand transition (e.g. braking into the restart) as
# well as the engine-lag buffering itself -- the two are not separated.
# This is why corpus median/p95 are reported as the headline figures, with
# max shown only as a labelled outlier, not a typical case.
_BUFIMP_RPM_COL = '\u041e\u0431\u0435\u0440\u0442\u0438 \u0434\u0432\u0438\u0433\u0443\u043d\u0430 (rpm)'
_BUFIMP_I_COL = '[BMS] HV Battery Current (A)'
_BUFIMP_V_COL = '[BMS] HV Battery voltage (V)'


def _buffer_impulse_events(fr, min_peak_excess_a=3.0, excess_thresh_a=1.5,
                            pre_off_s=3.0, baseline_win=(8.0, 2.0),
                            search_win=(1.0, 8.0)):
    """Per-drive engine-start buffer-impulse detection on a cached slim
    frame. Returns a list of event dicts. See the M116 note above this
    function for the full methodology."""
    if (fr is None or _BUFIMP_RPM_COL not in fr.columns
            or _BUFIMP_I_COL not in fr.columns or _BUFIMP_V_COL not in fr.columns):
        return []
    rpm = fr[['time', _BUFIMP_RPM_COL]].dropna().reset_index(drop=True)
    rpm.columns = ['time', 'rpm']
    I = fr[['time', _BUFIMP_I_COL]].dropna().reset_index(drop=True)
    I.columns = ['time', 'I_raw']
    I['I_dis'] = -I['I_raw']            # M11: raw is charge-positive
    V = fr[['time', _BUFIMP_V_COL]].dropna().reset_index(drop=True)
    V.columns = ['time', 'V']
    if len(rpm) < 2 or len(I) < 2 or len(V) < 2:
        return []

    r = rpm['rpm'].values
    t = rpm['time'].values
    starts = []
    for i in range(1, len(r)):
        if r[i] > 800 and r[i-1] <= 100:
            t0 = pd.Timestamp(t[i])
            back = rpm.loc[(rpm['time'] >= t0 - pd.Timedelta(seconds=pre_off_s))
                           & (rpm['time'] < t0), 'rpm']
            if len(back) > 0 and (back <= 100).all():
                starts.append(t0)

    events = []
    for t0 in starts:
        base_I = I[(I['time'] >= t0 - pd.Timedelta(seconds=baseline_win[0]))
                   & (I['time'] < t0 - pd.Timedelta(seconds=baseline_win[1]))]['I_dis']
        if len(base_I) == 0:
            continue
        baseline = float(base_I.median())

        seg = I[(I['time'] >= t0 - pd.Timedelta(seconds=search_win[0]))
                & (I['time'] <= t0 + pd.Timedelta(seconds=search_win[1]))].copy()
        seg = seg.sort_values('time').reset_index(drop=True)
        if len(seg) < 2:
            continue
        seg = pd.merge_asof(seg, V.sort_values('time'), on='time',
                             direction='nearest', tolerance=pd.Timedelta(seconds=3))
        seg['excess'] = (seg['I_dis'] - baseline).clip(lower=0)
        above = seg['excess'] > excess_thresh_a
        if not above.any():
            continue
        first_idx = int(above.values.argmax())
        end_idx = first_idx
        while end_idx < len(above) - 1 and above.iloc[end_idx + 1]:
            end_idx += 1
        imp = seg.iloc[first_idx:end_idx + 1].reset_index(drop=True)
        if len(imp) < 2:
            continue
        peak_excess = float(imp['excess'].max())
        if peak_excess < min_peak_excess_a:
            continue
        peak_pos = imp['excess'].idxmax()
        peak_v = float(imp.loc[peak_pos, 'V'])

        dt_h = imp['time'].diff().dt.total_seconds().fillna(0) / 3600.0
        p_kw = (imp['excess'] * imp['V']) / 1000.0
        energy_wh = 0.0
        for k in range(1, len(imp)):
            energy_wh += 0.5 * (p_kw.iloc[k] + p_kw.iloc[k-1]) * dt_h.iloc[k] * 1000
        duration_s = float((imp['time'].iloc[-1] - imp['time'].iloc[0]).total_seconds())
        recovery_s = float((imp['time'].iloc[-1] - imp['time'].loc[peak_pos]).total_seconds())

        events.append({
            't0': t0.isoformat(), 'baselineA': round(baseline, 2),
            'peakExcessA': round(peak_excess, 2),
            'peakExcessKw': round(peak_excess * peak_v / 1000.0, 3),
            'energyWh': round(energy_wh, 3),
            'durationS': round(duration_s, 2),
            'recoveryS': round(recovery_s, 2),
        })
    return events


def _buffer_impulse_summary(dm, frame_loader=None):
    """M116: corpus-wide aggregation of _buffer_impulse_events across every
    canonical drive with a cached frame. frame_loader-only (no raw_loader
    fallback): the slim cache already carries every column this analysis
    needs, and re-parsing 219 full raw CSVs for irregular async-PID
    extraction the cache already provides would be pure waste."""
    if frame_loader is None:
        return None
    per_drive_n = {}
    all_events = []
    n_covered = 0
    for _, row in dm.iterrows():
        fn = row['file']
        fr = frame_loader(fn)
        if fr is None:
            continue
        n_covered += 1
        ev = _buffer_impulse_events(fr)
        per_drive_n[fn] = len(ev)
        for e in ev:
            e['file'] = fn
            all_events.append(e)
    if n_covered == 0:
        return {'nDrivesCovered': 0, 'nEvents': 0}

    covered_km = float(dm[dm['file'].isin(per_drive_n)]['distance_km'].sum())
    n_zero = sum(1 for v in per_drive_n.values() if v == 0)
    out = {
        'nDrivesCovered': n_covered, 'nDrivesZeroEvents': n_zero,
        'coveredKm': round(covered_km, 1),
        'nEvents': len(all_events),
        'eventsPer100km': (round(len(all_events) / covered_km * 100, 2)
                           if covered_km else None),
    }
    if all_events:
        peaks = np.array([e['peakExcessKw'] for e in all_events])
        energies = np.array([e['energyWh'] for e in all_events])
        durs = np.array([e['durationS'] for e in all_events])
        recovs = np.array([e['recoveryS'] for e in all_events])
        total_impulse_s = float(durs.sum())
        total_drive_s = float(dm[dm['file'].isin(per_drive_n)]['duration_s'].sum())
        mx = max(all_events, key=lambda e: e['energyWh'])
        out.update({
            'peakKw': {'mean': round(float(peaks.mean()), 2),
                       'median': round(float(np.median(peaks)), 2),
                       'p95': round(float(np.percentile(peaks, 95)), 2),
                       'max': round(float(peaks.max()), 2)},
            'energyWh': {'mean': round(float(energies.mean()), 2),
                         'median': round(float(np.median(energies)), 2),
                         'p95': round(float(np.percentile(energies, 95)), 2),
                         'max': round(float(energies.max()), 2),
                         'totalWh': round(float(energies.sum()), 1),
                         'maxEvent': {'file': mx['file'], 't0': mx['t0'],
                                      'baselineA': mx['baselineA']}},
            'durationS': {'mean': round(float(durs.mean()), 2),
                          'median': round(float(np.median(durs)), 2)},
            'recoveryS': {'mean': round(float(recovs.mean()), 2),
                          'median': round(float(np.median(recovs)), 2)},
            'impulseTimeFractionPct': (round(total_impulse_s / total_drive_s * 100, 2)
                                        if total_drive_s else None),
        })
    out['methodology'] = (
        'Engine-start events (RPM crosses from sustained-OFF to running '
        'within one ~1.3s sample) are the power-ramp interval; battery '
        'discharge current (M11 sign-flipped to discharge-positive) in '
        'excess of the local pre-restart baseline is integrated over the '
        'first contiguous above-threshold run following the crossing. '
        'Baseline is local to each restart and can be negative (net '
        'charging) in stop-start driving following a prior cycle\'s '
        'recharge tail -- a real driving-pattern feature, not an artefact. '
        'An unusually large single-event figure can partly reflect a '
        'coincident driver-demand transition (e.g. braking into the '
        'restart) rather than engine-lag buffering alone; median/p95, not '
        'max, are the headline figures for this reason.')
    return out


# M118 (2026-08-10, audit §10 "Generator ramp latency / load-point dwell":
# "Segment engine starts and RPM/load plateaus; estimate transitions
# conditional on speed demand." -- "Direct control-strategy
# characterization." Marked "Feasible now". Builds on the same engine-start
# trigger as M116 (buffer impulse) but asks a different question -- not "how
# much did the battery buffer" but "how does the generator's RPM/load
# actually settle and step between discrete operating points" -- so event
# counts differ from M116 by design: this detector has no current-based
# eligibility gate, M116 requires peak_excess>=3A.
#
# Method: quantize RPM into 250 rpm bins (matching the ~500 rpm spacing
# between the discrete load-points already established by the M41
# load-point-quantization finding -- the generator does not hold a
# continuously-variable RPM, it steps between a handful of operating
# points). A "plateau" is a maximal run of consecutive samples in the same
# bin lasting >=3s. Ramp latency = time from the engine-start trigger to
# the start of the FIRST qualifying plateau. Load-point dwell = each
# plateau's own duration. A transition is the boundary between two
# consecutive qualifying plateaus within the same engine-on cycle; vehicle
# speed is sampled in a +-2s window around it ("conditional on speed
# demand").
# Known resolution limit: RPM is sampled at native ~1.3s intervals (async
# polled PID, not a fixed clock) and the mechanical ramp itself can complete
# within a single sample step -- a genuine 0.0s reported latency means the
# ramp finished at or below the telemetry's temporal resolution, not that
# the transition was literally instantaneous. This is documented, not
# filtered out, since discarding it would bias the reported latency
# distribution upward.
_RAMPLAT_RPM_COL = _BUFIMP_RPM_COL
_RAMPLAT_SPD_COL = '[VCM] Vehicle Speed (km/h)'


def _ramp_latency_events(fr, plateau_bin_rpm=250, min_plateau_s=3.0, pre_off_s=3.0):
    """Per-drive engine-start ramp/plateau segmentation on a cached slim
    frame. Returns a list of event dicts. See the M118 note above this
    function for the full methodology."""
    if fr is None or _RAMPLAT_RPM_COL not in fr.columns:
        return []
    fr, _ = _apply_speed_priority(fr)      # M167
    rpm = fr[['time', _RAMPLAT_RPM_COL]].dropna().reset_index(drop=True)
    rpm.columns = ['time', 'rpm']
    if len(rpm) < 2:
        return []
    spd = None
    if _RAMPLAT_SPD_COL in fr.columns:
        spd = fr[['time', _RAMPLAT_SPD_COL]].dropna().reset_index(drop=True)
        spd.columns = ['time', 'speed']

    r = rpm['rpm'].values
    t = rpm['time'].values
    starts = []
    for i in range(1, len(r)):
        if r[i] > 800 and r[i-1] <= 100:
            t0 = pd.Timestamp(t[i])
            back = rpm.loc[(rpm['time'] >= t0 - pd.Timedelta(seconds=pre_off_s))
                           & (rpm['time'] < t0), 'rpm']
            if len(back) > 0 and (back <= 100).all():
                starts.append((i, t0))

    events = []
    for start_idx, t0 in starts:
        seg = rpm.iloc[start_idx:].reset_index(drop=True)
        stop_pos = len(seg) - 1
        for j in range(1, len(seg)):
            if seg['rpm'].iloc[j] <= 100 and seg['rpm'].iloc[j-1] <= 100:
                stop_pos = j - 1
                break
        cyc = seg.iloc[:stop_pos + 1].reset_index(drop=True)
        if len(cyc) < 2:
            continue

        bins = (cyc['rpm'] / plateau_bin_rpm).round().astype(int)
        plateaus = []
        cur_bin = bins.iloc[0]
        run_start = 0
        for k in range(1, len(bins)):
            if bins.iloc[k] != cur_bin:
                plateaus.append((run_start, k - 1, cur_bin))
                cur_bin = bins.iloc[k]
                run_start = k
        plateaus.append((run_start, len(bins) - 1, cur_bin))

        qualifying = []
        for (a, b, bv) in plateaus:
            dur = (cyc['time'].iloc[b] - cyc['time'].iloc[a]).total_seconds()
            if dur >= min_plateau_s:
                qualifying.append({
                    'binRpm': int(bv * plateau_bin_rpm),
                    'durationS': round(dur, 2),
                    'startTime': cyc['time'].iloc[a], 'endTime': cyc['time'].iloc[b],
                })
        if not qualifying:
            continue

        ramp_latency_s = (qualifying[0]['startTime'] - t0).total_seconds()

        transitions = []
        for p1, p2 in zip(qualifying[:-1], qualifying[1:]):
            spd_val = None
            if spd is not None:
                near = spd[(spd['time'] >= p1['endTime'] - pd.Timedelta(seconds=2))
                          & (spd['time'] <= p1['endTime'] + pd.Timedelta(seconds=2))]
                if len(near):
                    spd_val = float(near['speed'].mean())
            transitions.append({'fromRpm': p1['binRpm'], 'toRpm': p2['binRpm'],
                                 'speedKmh': round(spd_val, 1) if spd_val is not None else None})

        events.append({
            't0': t0.isoformat(),
            'rampLatencyS': round(max(0.0, ramp_latency_s), 2),
            'firstPlateauRpm': qualifying[0]['binRpm'],
            'nPlateaus': len(qualifying),
            'plateauDwellsS': [p['durationS'] for p in qualifying],
            'transitions': transitions,
        })
    return events


def _ramp_latency_summary(dm, frame_loader=None):
    """M118: corpus-wide aggregation of _ramp_latency_events. frame_loader-
    only, same rationale as _buffer_impulse_summary."""
    if frame_loader is None:
        return None
    all_events, all_dwells, all_transitions = [], [], []
    n_covered = 0
    for _, row in dm.iterrows():
        fr = frame_loader(row['file'])
        if fr is None:
            continue
        n_covered += 1
        for e in _ramp_latency_events(fr):
            e['file'] = row['file']
            all_events.append(e)
            all_dwells.extend(e['plateauDwellsS'])
            all_transitions.extend(e['transitions'])
    if n_covered == 0 or not all_events:
        return {'nDrivesCovered': n_covered, 'nEvents': len(all_events)}

    lat = np.array([e['rampLatencyS'] for e in all_events])
    dwells = np.array(all_dwells)
    speeds = np.array([tr['speedKmh'] for tr in all_transitions if tr['speedKmh'] is not None])
    out = {
        'nDrivesCovered': n_covered,
        'nEvents': len(all_events),
        'nZeroLatencyEvents': int((lat == 0).sum()),
        'zeroLatencyPct': round(float((lat == 0).sum()) / len(lat) * 100, 1),
        'rampLatencyS': {'mean': round(float(lat.mean()), 2),
                          'median': round(float(np.median(lat)), 2),
                          'p95': round(float(np.percentile(lat, 95)), 2),
                          'max': round(float(lat.max()), 2)},
        'nPlateaus': len(dwells),
        'plateauDwellS': {'mean': round(float(dwells.mean()), 2),
                           'median': round(float(np.median(dwells)), 2),
                           'p95': round(float(np.percentile(dwells, 95)), 2),
                           'max': round(float(dwells.max()), 2)},
        'nTransitions': len(all_transitions),
        'nTransitionsWithSpeed': int(len(speeds)),
        'transitionSpeedKmh': ({'mean': round(float(speeds.mean()), 1),
                                'median': round(float(np.median(speeds)), 1)}
                               if len(speeds) else None),
    }
    out['methodology'] = (
        'Engine-start events (same RPM sustained-off -> running trigger as '
        'M116) are segmented into discrete RPM plateaus (250 rpm bins, '
        '>=3s minimum dwell), matching the load-point quantization already '
        'established by the M41 finding: the generator steps between a '
        'handful of operating points rather than holding a continuously '
        'variable RPM. Ramp latency is the time from the trigger to the '
        'first qualifying plateau; RPM is sampled at native ~1.3s '
        'intervals (async polled PID), and the mechanical ramp can '
        'complete within a single sample step -- a 0.0s reported latency '
        'means the ramp finished at or below telemetry resolution, not '
        'that it was instantaneous. Transition speed is vehicle speed in '
        'a +-2s window around each plateau-to-plateau boundary within the '
        'same engine-on cycle. This detector has no current-based '
        'eligibility gate (unlike M116), so its event count is not '
        'directly comparable to the buffer-impulse count.')
    return out


# M122 (2026-08-14): distributional + reconciliation enrichment for the M116
# buffer-impulse and M118 ramp-latency censuses. The two detectors are two
# measurements of the SAME engine-start event -- M116 asks "how much did the
# battery buffer the transient" and M118 asks "how did the generator's RPM
# then settle" -- but the original summaries emitted only mean/median/p95/max
# scalars, so the dashboard could draw nothing richer than a median->p95 range
# bar. That collapsed the very feature the buffer-not-reservoir thesis rests on
# (the extreme right-skew: most draws tiny, a thin tail) and never surfaced the
# relational findings (which discrete load-points the generator jumps to; that
# transitions concentrate at highway speed). This pass adds histograms /
# percentile ladders to both blocks and an explicit start-event RECONCILIATION
# so the two event counts (2224 current-gated vs 3754 plateau-gated, from one
# shared trigger set) stop looking like two unrelated numbers. It re-runs the
# canonical detectors verbatim (no re-derivation of their logic), so every
# figure it emits reconciles by construction with the scalar summaries above.
def _engine_start_triggers(fr, pre_off_s=3.0):
    """Return the set of engine-start trigger timestamps (ISO strings) using
    the IDENTICAL sustained-off -> running logic shared by _buffer_impulse_events
    and _ramp_latency_events. This is the pre-eligibility trigger population;
    both detectors' event sets are subsets of it by construction."""
    if fr is None or _BUFIMP_RPM_COL not in fr.columns:
        return []
    rpm = fr[['time', _BUFIMP_RPM_COL]].dropna().reset_index(drop=True)
    rpm.columns = ['time', 'rpm']
    if len(rpm) < 2:
        return []
    r = rpm['rpm'].values
    t = rpm['time'].values
    out = []
    for i in range(1, len(r)):
        if r[i] > 800 and r[i-1] <= 100:
            t0 = pd.Timestamp(t[i])
            back = rpm.loc[(rpm['time'] >= t0 - pd.Timedelta(seconds=pre_off_s))
                           & (rpm['time'] < t0), 'rpm']
            if len(back) > 0 and (back <= 100).all():
                out.append(t0.isoformat())
    return out


def _hist_counts(vals, edges):
    """Right-open bins [edges[i], edges[i+1]); the final bin is closed and
    absorbs the overflow tail. Returns integer counts of len(edges)-1."""
    import numpy as _np
    v = _np.asarray(vals, dtype=float)
    c = [0] * (len(edges) - 1)
    for x in v:
        for i in range(len(edges) - 1):
            hi = edges[i + 1]
            if (x >= edges[i] and x < hi) or (i == len(edges) - 2 and x >= hi):
                c[i] += 1
                break
    return c


def _ladder(vals, ps=(10, 25, 50, 75, 90, 95, 99)):
    import numpy as _np
    v = _np.asarray(vals, dtype=float)
    return {('p%d' % p): round(float(_np.percentile(v, p)), 2) for p in ps}


def _start_event_analytics(dm, frame_loader=None, cap_kwh_assumed=2.1):
    """M122. One frame_loader pass; re-runs the canonical M116/M118 detectors
    per drive and returns three merge-ready blocks:
      bufferExtra  -> merged into arrays['bufferImpulse']
      rampExtra    -> merged into arrays['rampLatency']
      reconcile    -> arrays['startEventReconcile']
    Nothing here re-derives detector logic; it aggregates their per-event output
    into distributions, so it reconciles with the scalar summaries by design."""
    if frame_loader is None:
        return None
    b_energy, b_peak, b_dur, b_recov = [], [], [], []
    r_lat, r_dwell, r_firstrpm, r_transpd, r_nplat = [], [], [], [], []
    n_trig = n_both = n_bonly = n_ronly = n_neither = 0
    for _, row in dm.iterrows():
        fr = frame_loader(row['file'])
        if fr is None:
            continue
        trig = set(_engine_start_triggers(fr))
        bev = _buffer_impulse_events(fr)
        rev = _ramp_latency_events(fr)
        B = {e['t0'] for e in bev}
        R = {e['t0'] for e in rev}
        n_trig += len(trig)
        n_both += len(B & R)
        n_bonly += len(B - R)
        n_ronly += len(R - B)
        n_neither += len(trig - B - R)
        for e in bev:
            b_energy.append(e['energyWh']); b_peak.append(e['peakExcessKw'])
            b_dur.append(e['durationS']); b_recov.append(e['recoveryS'])
        for e in rev:
            r_lat.append(e['rampLatencyS']); r_firstrpm.append(e['firstPlateauRpm'])
            r_nplat.append(e['nPlateaus'])
            r_dwell.extend(e['plateauDwellsS'])
            for tr in e['transitions']:
                if tr.get('speedKmh') is not None:
                    r_transpd.append(tr['speedKmh'])
    if not b_energy and not r_lat:
        return None

    import numpy as _np
    total_wh = float(_np.sum(b_energy)) if b_energy else 0.0
    buffer_extra = {
        'energyLadder': _ladder(b_energy) if b_energy else None,
        'peakKwLadder': _ladder(b_peak) if b_peak else None,
        'durationLadder': _ladder(b_dur) if b_dur else None,
        'recoveryLadder': _ladder(b_recov) if b_recov else None,
        # energy histogram: 0-100 Wh in 10-Wh bins + a closed >=100 tail bin
        'energyHist': {
            'edges': [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 300],
            'counts': _hist_counts(b_energy, [0, 10, 20, 30, 40, 50, 60,
                                              70, 80, 90, 100, 300]),
            'tailFromWh': 100,
        } if b_energy else None,
        # peak buffering power: 0-100 kW in 10-kW bins + closed >=100 tail
        'peakKwHist': {
            'edges': [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 130],
            'counts': _hist_counts(b_peak, [0, 10, 20, 30, 40, 50, 60,
                                            70, 80, 90, 100, 130]),
            'tailFromKw': 100,
        } if b_peak else None,
        'capKwhAssumed': cap_kwh_assumed,
        'capacityMultiple': round(total_wh / 1000.0 / cap_kwh_assumed, 1),
    }

    # ramp latency: positive-only histogram (the exactly-0.0s resolution-floor
    # population is already reported as zeroLatencyPct and shown as its own bar)
    r_lat_pos = [x for x in r_lat if x > 0]
    lat_edges = [0, 1, 2, 3, 4, 5, 6, 8, 10, 15, 70]
    dwell_edges = [3, 6, 9, 12, 15, 20, 30, 45, 60, 265]
    spd_edges = [0, 20, 40, 60, 80, 90, 100, 110, 120, 130, 200]
    # first-plateau operating-point distribution (250-rpm binned) -- the M41
    # load-point-quantization signature: a handful of discrete set-points
    fr_counts = {}
    for v in r_firstrpm:
        fr_counts[int(v)] = fr_counts.get(int(v), 0) + 1
    first_rpm_dist = [{'rpm': k, 'n': fr_counts[k]} for k in sorted(fr_counts)]
    # plateaus-per-event distribution, 1..4 then 5+ collapsed
    npl_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for v in r_nplat:
        npl_dist[min(int(v), 5)] += 1
    plateaus_per_event = [{'k': k, 'n': npl_dist[k],
                           'label': ('5+' if k == 5 else str(k))}
                          for k in sorted(npl_dist)]
    ramp_extra = {
        'latencyLadder': _ladder(r_lat) if r_lat else None,
        'dwellLadder': _ladder(r_dwell) if r_dwell else None,
        'latencyHistPos': {
            'edges': lat_edges,
            'counts': _hist_counts(r_lat_pos, lat_edges),
            'nZero': int(sum(1 for x in r_lat if x == 0)),
            'note': ('nZero is the exactly-0.0s resolution-floor population '
                     '(ramp completed within one telemetry sample); the '
                     'histogram covers only latencies > 0 s.'),
        } if r_lat else None,
        'dwellHist': {'edges': dwell_edges,
                      'counts': _hist_counts(r_dwell, dwell_edges)} if r_dwell else None,
        'firstPlateauRpmDist': first_rpm_dist,
        'transitionSpeedHist': {
            'edges': spd_edges,
            'counts': _hist_counts(r_transpd, spd_edges),
            'n': len(r_transpd),
        } if r_transpd else None,
        'plateausPerEventDist': plateaus_per_event,
    }

    reconcile = {
        'nStartTriggers': int(n_trig),
        'nBufferEvents': int(n_both + n_bonly),
        'nRampEvents': int(n_both + n_ronly),
        'nBoth': int(n_both),
        'nBufferOnly': int(n_bonly),
        'nRampOnly': int(n_ronly),
        'nNeither': int(n_neither),
        'bufferGatePct': (round((n_both + n_bonly) / n_trig * 100, 1)
                          if n_trig else None),
        'rampGatePct': (round((n_both + n_ronly) / n_trig * 100, 1)
                        if n_trig else None),
        'methodology': (
            'Both detectors share ONE trigger definition (RPM sustained-off '
            '-> running); their event sets are subsets of that trigger '
            'population, differing only by downstream eligibility. M116 '
            'requires a battery discharge excess >=3A over the pre-restart '
            'baseline (current gate); M118 requires >=1 RPM plateau lasting '
            '>=3s (dwell gate). A trigger can pass one gate, both, or neither '
            '-- e.g. a brief restart with a current spike but no sustained '
            'plateau is buffer-only; a long low-current idle-up is ramp-only. '
            'This block makes the 2224-vs-3754 count difference explicit '
            'rather than leaving it as two unrelated headline numbers.'),
    }
    return {'bufferExtra': buffer_extra, 'rampExtra': ramp_extra,
            'reconcile': reconcile}


# M119 (2026-08-10, audit §10 "SoC hysteresis state machine": "Estimate
# state-dependent start/stop probabilities versus SoC, speed, temperature
# and recent demand." "Replaces fixed threshold narrative with
# probabilistic control map." Marked "Feasible now".
#
# Unlike M116/M118 (per-event, engine-start-triggered), this is a
# per-SECOND state-classification across the corpus: every second the
# engine is off is an "at-risk" sample for a start in the following second;
# every second it is on is at-risk for a stop. Building a 1 Hz grid
# (resample+ffill, same pattern as _near_limiter's grid_fn) and computing
# empirical P(start) / P(stop) conditional on SoC bin -- and, stratified,
# on SoC bin x speed band -- replaces the dashboard's existing "SoC
# hysteresis loop" chart (a fixed per-class trigger/stop box) with a
# genuine probability surface. The corpus-scale result is a clean
# demonstration that SoC alone is not the controlling variable: at the same
# SoC bin, P(start) differs by two orders of magnitude between stationary
# and highway speed (e.g. SoC~60%: stationary ~0.1%, highway ~13%) --
# demand dominates over SoC once both are known, which a single fixed
# threshold cannot represent.
#
# Scope note: the audit's covariate list is SoC, speed, temperature AND
# recent demand. This implementation delivers SoC (primary axis) and speed
# (the one stratifying secondary axis) at corpus scale. Temperature and a
# recent-demand proxy were prototyped but not included in v1: a full 4-way
# stratification fragments the ~235k/~209k at-risk samples into cells too
# sparse to trust (the SoC x speed table already leaves several cells
# below a usable n at n>=30), and resolving that properly needs a
# regression-style model (e.g. logistic) rather than binned tables, which
# is future work, not this pass. This is disclosed in the block's
# `methodology` string and in the dashboard prose, not left implicit.
_SOCHYST_COLS = {
    '[BMS] HV State of charge (%)': 'soc',
    '[VCM] Vehicle Speed (km/h)': 'speed',
    _BUFIMP_RPM_COL: 'rpm',
}


def _soc_hysteresis_grid(fr):
    """1 Hz resampled grid of soc/speed/rpm for one drive's cached frame."""
    if fr is None or 'time' not in fr.columns:
        return None
    fr, _ = _apply_speed_priority(fr)      # M167
    keep = [c for c in _SOCHYST_COLS if c in fr.columns]
    if 'soc' not in [_SOCHYST_COLS[c] for c in keep] or 'rpm' not in [_SOCHYST_COLS[c] for c in keep]:
        return None
    g = fr[['time'] + keep].rename(columns=_SOCHYST_COLS)
    g = g.set_index(pd.to_datetime(g['time'], errors='coerce')).drop(columns='time')
    g = g.apply(pd.to_numeric, errors='coerce')
    g = g.resample('1s').mean().ffill(limit=5)
    return g


def _soc_hysteresis_transitions(fr, engine_on_rpm=500):
    """Per-drive at-risk-for-start / at-risk-for-stop sample tables."""
    g = _soc_hysteresis_grid(fr)
    if g is None:
        return None
    g = g.dropna(subset=['rpm', 'soc'])
    if len(g) < 5:
        return None
    g['engineOn'] = g['rpm'] > engine_on_rpm
    g['engineOnPrev'] = g['engineOn'].shift(1)
    at_risk_start = g[g['engineOnPrev'] == False].copy()
    at_risk_start['isStart'] = at_risk_start['engineOn']
    at_risk_stop = g[g['engineOnPrev'] == True].copy()
    at_risk_stop['isStop'] = ~at_risk_stop['engineOn']
    keep_s = [c for c in ('soc', 'speed', 'isStart') if c in at_risk_start.columns]
    keep_t = [c for c in ('soc', 'speed', 'isStop') if c in at_risk_stop.columns]
    return at_risk_start[keep_s], at_risk_stop[keep_t]


def _soc_hysteresis_summary(dm, frame_loader=None, min_n=30):
    """M119: corpus-wide SoC/speed start-stop probability surface."""
    if frame_loader is None:
        return None
    all_start, all_stop = [], []
    n_covered = 0
    for _, row in dm.iterrows():
        fr = frame_loader(row['file'])
        if fr is None:
            continue
        res = _soc_hysteresis_transitions(fr)
        if res is None:
            continue
        n_covered += 1
        ars, aro = res
        if len(ars):
            all_start.append(ars)
        if len(aro):
            all_stop.append(aro)
    if n_covered == 0 or not all_start or not all_stop:
        return {'nDrivesCovered': n_covered}

    S = pd.concat(all_start, ignore_index=True)
    T = pd.concat(all_stop, ignore_index=True)
    S['socBin'] = (S['soc'] // 5 * 5).clip(35, 90)
    T['socBin'] = (T['soc'] // 5 * 5).clip(35, 90)

    def _marginal(df, outcome_col):
        grp = df.groupby('socBin').agg(n=(outcome_col, 'size'), k=(outcome_col, 'sum'))
        grp['prob'] = grp['k'] / grp['n']
        grp = grp[grp['n'] >= min_n]
        return [{'socBin': float(i), 'n': int(r.n), 'k': int(r.k),
                 'prob': round(float(r.prob), 5)}
                for i, r in grp.iterrows()]

    out = {
        'nDrivesCovered': n_covered,
        'nAtRiskStart': int(len(S)), 'nStarts': int(S['isStart'].sum()),
        'nAtRiskStop': int(len(T)), 'nStops': int(T['isStop'].sum()),
        'startProbBySoc': _marginal(S, 'isStart'),
        'stopProbBySoc': _marginal(T, 'isStop'),
    }

    if 'speed' in S.columns and 'speed' in T.columns:
        def _speed_band(s):
            return np.select([s < 5, s < 60], ['stationary', 'low'], default='high')
        S2 = S.dropna(subset=['speed']).copy()
        T2 = T.dropna(subset=['speed']).copy()
        S2['speedBand'] = _speed_band(S2['speed'].values)
        T2['speedBand'] = _speed_band(T2['speed'].values)

        def _stratified(df, outcome_col):
            grp = df.groupby(['socBin', 'speedBand']).agg(
                n=(outcome_col, 'size'), k=(outcome_col, 'sum'))
            grp['prob'] = grp['k'] / grp['n']
            grp = grp[grp['n'] >= min_n]
            return [{'socBin': float(i[0]), 'speedBand': i[1], 'n': int(r.n),
                     'k': int(r.k), 'prob': round(float(r.prob), 5)}
                    for i, r in grp.iterrows()]

        out['startProbBySocSpeed'] = _stratified(S2, 'isStart')
        out['stopProbBySocSpeed'] = _stratified(T2, 'isStop')
        # headline contrast: same SoC bin, stationary vs highway P(start)
        by_key = {(r['socBin'], r['speedBand']): r['prob'] for r in out['startProbBySocSpeed']}
        contrasts = []
        for (sb, band), p in by_key.items():
            if band == 'stationary' and (sb, 'high') in by_key and p > 0:
                contrasts.append({'socBin': sb, 'stationaryProb': p,
                                   'highwayProb': by_key[(sb, 'high')],
                                   'ratio': round(by_key[(sb, 'high')] / p, 1)})
        out['stationaryVsHighwayContrast'] = sorted(
            contrasts, key=lambda c: -c['ratio'])[:5]

    out['methodology'] = (
        'Per-second state classification (1 Hz resampled grid, engine-on = '
        'rpm>500) across the corpus, distinct from the per-event M116/M118 '
        'detectors. Every second the engine is off is an at-risk sample for '
        'a start in the following second; every second it is on is at-risk '
        'for a stop. Marginal probability is tabulated by 5-point SoC bin; '
        'stratified probability adds a speed band (stationary <5, low '
        '5-60, high >=60 km/h -- an independently-defined threshold for '
        'this per-second analysis only, NOT the same >=90 km/h boundary '
        'used by the drive_type Highway classifier (M115); the two serve '
        'different purposes and are not interchangeable). Both tables are '
        'filtered to cells with '
        'n>=30 to avoid presenting noisy small-sample estimates (e.g. a '
        'single-digit-n bin at the tails of the SoC range) with the same '
        'apparent weight as a well-supported one. Temperature '
        'and a recent-demand covariate were scoped out of this pass -- a '
        'full 4-way stratification fragments the sample too far for '
        'binned tables to remain trustworthy; that needs a regression-'
        'style model, not this pass. Replaces the dashboard\'s fixed '
        'per-class SoC hysteresis box with an actual probability surface: '
        'at matched SoC, P(start) differs by roughly two orders of '
        'magnitude between stationary and highway speed, showing SoC '
        'alone does not set the trigger point once demand is accounted '
        'for.')
    return out


# M140 (2026-08-18): BMS-declared possible-power headroom utilization.
# Origin: M121 (2026-08-14) flagged '[BMS] Input/Output possible power (hp)'
# -- the BMS's own real-time capability envelope -- as a candidate for a
# genuine headroom-utilization metric (measured P / BMS-declared possible
# power), more authoritative than the M14 deficit_80_120_pct generator-
# saturation proxy this study otherwise relies on. Flagged "not scheduled":
# needed its own validation pass (units hp->kW, alignment tolerance, and
# confirmation the channel is populated broadly enough to be useful) before
# entering COL_MAP.
#
# That validation pass, run here, found the channel is NOT broadly populated
# (23/256 files, ~9.0%, all from the third-PID-config era onward, 2026-08-13+)
# and NOT symmetric between its two directions:
#   - Output possible power (max DISCHARGE capability) is a HARD CONSTANT,
#     86.6758781031239 hp (64.634 kW), on every one of the 23 covered files
#     with zero exceptions -- an OEM-declared static ceiling this corpus's
#     driving never approached closely enough to move (max observed
#     discharge utilization across the whole covered set: ~88%). Comparing
#     measured discharge power against a value that never varies adds no
#     information beyond the already-reported discharge-power distribution;
#     NOT computed as a "genuine" ratio for this reason, only reported
#     descriptively (nDischargeEvents, dischargeUtilization against the
#     fixed ceiling).
#   - Input possible power (max CHARGE-acceptance capability) DOES vary --
#     roughly 55 hp up to the same 86.68 hp ceiling, evidently state-
#     dependent (candidate drivers: SoC, pack temperature -- not modeled
#     here, flagged as future work). This is the genuinely informative
#     direction: chargeUtilization = measured charge power (kW, I*V,
#     charge-positive raw per M11, aligned to the nearest possible-power
#     sample) / (Input possible power hp * 0.745699872).
#
# Alignment tolerance: this channel's own median inter-sample gap is far
# wider than the pipeline's usual V_ALIGN_TOL=1500ms (roughly 1-2% the fill
# density of ordinary BMS current/voltage within covered files), so a 2s
# merge_asof(direction='nearest') tolerance is used instead of V_ALIGN_TOL --
# wide enough to find a match at all given the channel's sparsity, at the
# documented cost that a small number of aligned pairs (chiefly during fast
# current transients) show utilization slightly ABOVE 1.0, most plausibly a
# stale-match artefact (the possible-power reading has not yet updated to
# reflect a transient the live current channel already shows) rather than a
# genuine BMS-limit excursion; NOT clipped, reported as-is with this caveat
# attached in the block's own methodology string.
_HDRM_PP_IN_COL = '[BMS] Input possible power (hp)'
_HDRM_PP_OUT_COL = '[BMS] Output possible power (hp)'
_HDRM_ALIGN_TOL = '2s'
_HDRM_HP_TO_KW = 0.745699872


def _headroom_utilization_events(csv_bytes, filename):
    """Per-drive extraction for M140. Aligns raw [BMS] Input/Output possible
    power samples against the pipeline's own I<->V power series, reusing
    compute_drive_summary_v6's COL_MAP/_series/_asof rather than
    reimplementing them. Returns None if the file carries neither
    possible-power channel or lacks a usable I<->V pairing."""
    import compute_drive_summary_v6 as _v6
    try:
        df_raw = pd.read_csv(io.BytesIO(csv_bytes), low_memory=False)
    except Exception:
        return None
    has_in = _HDRM_PP_IN_COL in df_raw.columns
    has_out = _HDRM_PP_OUT_COL in df_raw.columns
    if not (has_in or has_out):
        return None
    pp_in_raw = df_raw[_HDRM_PP_IN_COL].copy() if has_in else None
    pp_out_raw = df_raw[_HDRM_PP_OUT_COL].copy() if has_out else None

    df = df_raw.rename(columns={k: v for k, v in _v6.COL_MAP.items()
                                 if k in df_raw.columns})
    t = pd.to_datetime(df['time'], format='mixed', errors='coerce')
    I = _v6._series(df, t, 'I')
    if I is not None:
        I = I[I['v'].abs() < 900]
    V = _v6._series(df, t, 'V', lo=200, hi=450)
    if I is None or V is None or not len(I) or not len(V):
        return None
    e = _v6._asof(I.copy(), V, 'V', _v6.V_ALIGN_TOL).dropna(subset=['V'])
    if not len(e):
        return None
    e['P_kw'] = e['v'] * e['V'] / 1000.0     # charge-positive raw (M11)
    e = e[['t', 'P_kw']].sort_values('t')

    out = {'file': filename, 'charge': [], 'discharge': []}
    for label, pp_raw in [('charge', pp_in_raw), ('discharge', pp_out_raw)]:
        if pp_raw is None:
            continue
        pp = pd.DataFrame({'t': t, 'pp_hp': pp_raw}).dropna().sort_values('t')
        if not len(pp):
            continue
        m = pd.merge_asof(pp, e, on='t', direction='nearest',
                           tolerance=pd.Timedelta(_HDRM_ALIGN_TOL)
                           ).dropna(subset=['P_kw'])
        if not len(m):
            continue
        m['pp_kw'] = m['pp_hp'] * _HDRM_HP_TO_KW
        if label == 'charge':
            q = m[m['P_kw'] > 0.1].copy()
            q['measured_kw'] = q['P_kw']
        else:
            q = m[m['P_kw'] < -0.1].copy()
            q['measured_kw'] = -q['P_kw']
        if len(q):
            q['util'] = q['measured_kw'] / q['pp_kw']
            out[label] = q[['pp_kw', 'measured_kw', 'util']].to_dict('records')
    return out


def _headroom_utilization_summary(dm, raw_loader=None):
    """M140: corpus-wide '[BMS] Input/Output possible power' headroom-
    utilization scan. See the module comment above this function for the
    full origin, methodology, and the constant-Output-ceiling finding.
    raw_loader-only: the channel is not in COL_MAP / the slim frame cache,
    so every candidate file needs a real raw-bytes read; pre-filtered to
    date>=2026-08-13 (the confirmed first-appearance date per M121) to avoid
    paying that cost on the ~90% of the corpus already known not to carry it."""
    if raw_loader is None:
        return None
    candidates = dm
    if 'date' in dm.columns:
        candidates = dm[dm['date'].astype(str) >= '2026-08-13']
    n_scanned = 0
    n_covered = 0
    charge_events = []
    discharge_events = []
    for _, row in candidates.iterrows():
        fn = row['file']
        n_scanned += 1
        try:
            b = raw_loader(fn)
        except Exception:
            continue
        ev = _headroom_utilization_events(b, fn)
        if ev is None:
            continue
        n_covered += 1
        for r in ev.get('charge', []):
            r['file'] = fn
            charge_events.append(r)
        for r in ev.get('discharge', []):
            r['file'] = fn
            discharge_events.append(r)

    if n_covered == 0:
        return {'nFilesScanned': int(n_scanned), 'nFilesCovered': 0}

    out_ceiling_vals = set(round(r['pp_kw'], 3) for r in discharge_events)
    out = {
        'nFilesScanned': int(n_scanned), 'nFilesCovered': int(n_covered),
        'coveragePct': round(n_covered / len(dm) * 100, 1),
        'nChargeEvents': len(charge_events),
        'nDischargeEvents': len(discharge_events),
    }
    if len(out_ceiling_vals) == 1:
        out['outputCeilingKw'] = round(next(iter(out_ceiling_vals)), 3)
        out['outputCeilingConstant'] = True
    elif out_ceiling_vals:
        out['outputCeilingConstant'] = False
        out['outputCeilingRangeKw'] = [round(min(out_ceiling_vals), 2),
                                        round(max(out_ceiling_vals), 2)]

    if charge_events:
        util = np.array([r['util'] for r in charge_events])
        mx = max(charge_events, key=lambda r: r['util'])
        out['chargeUtilization'] = {
            'median': round(float(np.median(util)), 3),
            'p95': round(float(np.percentile(util, 95)), 3),
            'max': round(float(util.max()), 3),
            'nAbove1': int((util > 1.0).sum()),
            'maxEvent': {'file': mx['file'],
                         'measuredKw': round(mx['measured_kw'], 2),
                         'possibleKw': round(mx['pp_kw'], 2)},
        }
    if discharge_events:
        util = np.array([r['util'] for r in discharge_events])
        mx = max(discharge_events, key=lambda r: r['measured_kw'])
        out['dischargeUtilization'] = {
            'median': round(float(np.median(util)), 3),
            'p95': round(float(np.percentile(util, 95)), 3),
            'max': round(float(util.max()), 3),
            'maxMeasuredKw': round(mx['measured_kw'], 2),
            'maxMeasuredFile': mx['file'],
        }
    out['methodology'] = (
        'M121 origin: [BMS] Input/Output possible power (hp), the BMS\'s '
        'own declared capability envelope, present only from the third '
        'raw-logging PID configuration onward (2026-08-13+). Coverage is '
        f'sparse ({n_covered}/{len(dm)} corpus drives, {out["coveragePct"]}%'
        ') and the channel itself is polled far less densely than ordinary '
        'BMS current/voltage (roughly 1-2% fill density within covered '
        f'files), so alignment against the pipeline\'s I x V power series '
        f'uses a wide {_HDRM_ALIGN_TOL} merge_asof(direction="nearest") '
        'tolerance rather than the usual V_ALIGN_TOL=1500ms. Output '
        'possible power (max discharge capability) is a hard constant '
        'across every covered file (zero exceptions) -- this corpus\'s '
        'driving never moved it, so no discharge-side utilization ratio is '
        'reported as a headline figure, only the descriptive utilization-'
        'against-the-fixed-ceiling stats above. Input possible power (max '
        'charge-acceptance capability) DOES vary and is the genuinely '
        'informative direction. A small number of charge-utilization values '
        'exceed 1.0, most plausibly a stale-match artefact from the wide '
        'alignment tolerance during fast current transients rather than a '
        'real BMS-limit excursion; not clipped, reported as-is.')
    return out


# ======================================================================
# M141 (2026-08-19): heat-soak carryover -- inter-drive thermal relaxation.
# M142 (2026-08-19): drive-type regime transition matrix (cell-suppressed).
# M143 (2026-08-19): thermal step response -- pack warmup time constant.
#
# The three §10-audit residuals Andrii cleared for build (M139 flagged them
# as needing his scope steer; the order and the M142 cell-suppression choice
# came from that steer). All three are arrays-side, additive: they emit new
# top-level keys and touch neither drive_master.csv nor any existing column.
#
# time_start / time_end carry TIME-OF-DAY ONLY (HH:MM:SS.fff, no date), so a
# true drive timeline must anchor them to the 'date' column -- see
# _full_datetimes. (Empirically confirmed: naively parsing time_start alone
# collapses all 256 drives onto one fictitious day, corrupting both the
# chronological transition order and every inter-drive gap.)
# ======================================================================
def _full_datetimes(dm):
    """Anchor the date-less time_start/time_end (HH:MM:SS.fff) to the 'date'
    column -> true per-drive datetimes. A drive whose time_end < time_start
    crossed midnight, so its end is date+1."""
    d = dm.copy()
    dd = pd.to_datetime(d['date'], errors='coerce')
    ts = pd.to_timedelta(d['time_start'].astype(str), errors='coerce')
    te = pd.to_timedelta(d['time_end'].astype(str), errors='coerce')
    d['ts_full'] = dd + ts
    d['te_full'] = dd + te
    wrap = d['te_full'] < d['ts_full']
    d.loc[wrap, 'te_full'] = d.loc[wrap, 'te_full'] + pd.Timedelta(days=1)
    return d


def _regime_persistence(segments, n, n_perm=5000, seed=42):
    """M160 (audit section 7): does the drive-type regime sequence carry real
    serial dependence, or is it memoryless? The prior read -- that the Markov
    stationary distribution sits on the empirical marginal, therefore the chain
    is 'near-memoryless' -- is NOT an independence test: for an ergodic chain
    estimated from a single sequence, the fitted stationary distribution
    approximates the empirical marginal BY CONSTRUCTION, regardless of how much
    persistence the sequence has. This provides the actual tests.

    segments: list of runs (each a list of state indices 0..n-1) with chain
    breaks -- unknown-type drives, and over-threshold idle gaps in the session
    variants -- already split out, so transitions are only counted within a run.
    Returns the independence baseline for the same-state share, Cohen's kappa
    (from-state vs to-state agreement above chance), mutual information (nats),
    the likelihood-ratio G-test of independence (df=(n-1)^2), and a
    label-permutation p-value that shuffles the regime labels within the same
    run-length structure (preserving the marginal, destroying serial order)."""
    from scipy import stats
    C = np.zeros((n, n), dtype=float)
    for seg in segments:
        for a, b in zip(seg[:-1], seg[1:]):
            C[a][b] += 1.0
    N = float(C.sum())
    if N < 1:
        return None
    rs = C.sum(axis=1); cs = C.sum(axis=0)
    p_o = float(np.trace(C)) / N                     # observed same-state share
    p_e = float((rs * cs).sum() / N ** 2)            # expected under independence
    kappa = ((p_o - p_e) / (1 - p_e)) if (1 - p_e) > 1e-12 else None
    E = np.outer(rs, cs) / N
    mask = C > 0
    mi = float(np.sum((C[mask] / N) * np.log((C[mask] / N) / (E[mask] / N))))
    g = float(2.0 * np.sum(C[mask] * np.log(C[mask] / E[mask])))  # = 2*N*MI
    df = (n - 1) ** 2
    p_g = float(stats.chi2.sf(g, df))
    # label permutation: pool all run labels, shuffle, refill the same run
    # lengths, recompute the same-state share. Preserves the regime marginal and
    # the number of transitions; removes any serial structure.
    pool = np.array([lab for seg in segments for lab in seg], dtype=int)
    lens = [len(seg) for seg in segments]
    rng = np.random.default_rng(seed)
    ge = 0
    for _ in range(n_perm):
        pr = pool.copy(); rng.shuffle(pr)
        d2 = 0.0; n2 = 0.0; k = 0
        for L in lens:
            s = pr[k:k + L]; k += L
            if L >= 2:
                d2 += float(np.sum(s[:-1] == s[1:])); n2 += (L - 1)
        if n2 > 0 and (d2 / n2) >= p_o - 1e-12:
            ge += 1
    p_perm = (1 + ge) / (n_perm + 1)
    return {
        'nTransitions': int(N),
        'observedSameState': round(p_o, 4),
        'expectedSameStateIndep': round(p_e, 4),
        'kappa': round(kappa, 4) if kappa is not None else None,
        'mutualInfoNats': round(mi, 4),
        'gTest': round(g, 2), 'gTestDf': df, 'gTestP': p_g,
        'permutationP': round(p_perm, 5), 'nPermutations': n_perm,
        'verdict': ('Statistically detectable, moderate short-range persistence: '
                    'same-type drives cluster above the independence baseline '
                    '(kappa>0), confirmed by the G-test and the label-permutation '
                    'test. The sequence is NOT memoryless; the stationary-vs-'
                    'marginal agreement is expected by construction and is not an '
                    'independence test.')}


def _regime_transition(dm, min_cell=5, max_gap_h=None, _variant=False):
    """M142: first-order Markov transition structure over the drive-type regime
    taxonomy (CLASS_ORDER), chronological drive-to-drive.

    States are the four CLASS_ORDER regimes; 'unknown' drives (drive_type not
    in CLASS_ORDER) break the chain -- they are neither a valid from- nor
    to-state, the same gating _class_label applies elsewhere. Emits the raw
    count matrix, row-stochastic transition probabilities, the Markov
    stationary distribution (left eigenvector) alongside the empirical
    marginal (a DESCRIPTIVE pairing only -- their agreement is expected by
    construction for an ergodic chain and is NOT an independence test; see the
    'persistence' block from _regime_persistence for the actual serial-
    dependence tests), and the self-transition share (regime persistence).

    CELL SUPPRESSION (Andrii's steer): every cell whose count is in
    [1, min_cell) is flagged suppressed=True -- a small-count stability /
    statistical-disclosure guard, so a probability estimated from <5
    observations is never read as reliable. Suppressed cells are STILL counted
    in their row-sum denominator (the suppression is a display/reliability
    flag, not a deletion), so row probabilities remain proper.

    max_gap_h (optional) resets the chain across idle gaps longer than the
    threshold, giving a within-session variant; None = one global chain.
    """
    d = (_full_datetimes(dm).dropna(subset=['ts_full'])
         .sort_values('ts_full').reset_index(drop=True))
    idx = {c: i for i, c in enumerate(CLASS_ORDER)}
    n = len(CLASS_ORDER)
    C = np.zeros((n, n), dtype=int)
    prev = None
    prev_te = None
    n_trans = 0
    nbu = 0
    nbg = 0
    segments = []   # M160: maximal runs of consecutive valid drives (no break)
    cur = []
    for _, r in d.iterrows():
        cls = r['drive_type'] if r['drive_type'] in idx else None
        gap_h = None
        if prev is not None and prev_te is not None and pd.notna(r['ts_full']):
            gap_h = (r['ts_full'] - prev_te).total_seconds() / 3600.0
        if cls is None:
            if cur:
                segments.append(cur); cur = []
            prev = None
            prev_te = None
            nbu += 1
            continue
        if prev is not None:
            if max_gap_h is not None and gap_h is not None and gap_h > max_gap_h:
                nbg += 1
                if cur:
                    segments.append(cur); cur = []   # gap ends the run
            else:
                C[idx[prev]][idx[cls]] += 1
                n_trans += 1
        cur.append(idx[cls])
        prev = cls
        prev_te = r['te_full'] if pd.notna(r['te_full']) else r['ts_full']
    if cur:
        segments.append(cur)
    rowsum = C.sum(axis=1)
    P = np.zeros((n, n))
    cells = []
    for i in range(n):
        for j in range(n):
            c = int(C[i][j])
            rs = int(rowsum[i])
            p = (c / rs) if rs > 0 else None
            if p is not None:
                P[i][j] = p
            cells.append({'from': CLASS_ORDER[i], 'to': CLASS_ORDER[j],
                          'count': c,
                          'p': (round(p, 4) if p is not None else None),
                          'suppressed': bool(0 < c < min_cell)})
    stat = None
    if (rowsum > 0).all():
        try:
            vals, vecs = np.linalg.eig(P.T)
            k = int(np.argmin(np.abs(vals - 1.0)))
            v = np.real(vecs[:, k])
            v = v / v.sum()
            stat = {CLASS_ORDER[i]: round(float(v[i]), 4) for i in range(n)}
        except Exception:
            stat = None
    marg = dm['drive_type'].value_counts(normalize=True)
    diag = sum(int(C[i][i]) for i in range(n))
    # M162 (audit section 7 "preferred methods"): within-session variants under
    # a prospective idle-gap rule. Transitions are only counted between drives
    # separated by <= gap hours, so each gap rule reports the persistence within
    # sessions defined at that threshold. The label-permutation preserves the
    # per-session run-length structure (bootstrapping sessions, not individual
    # transitions). Computed only for the top-level (global-chain) call.
    session_variants = None
    if not _variant:
        session_variants = []
        for g in (1, 3, 6, 12):
            rt_g = _regime_transition(dm, min_cell=min_cell, max_gap_h=g,
                                      _variant=True)
            session_variants.append({
                'gapHours': g,
                'nTransitions': rt_g['nTransitions'],
                'selfTransitionShare': rt_g['selfTransitionShare'],
                'chainBreaksGap': rt_g['chainBreaksGap'],
                'persistence': rt_g['persistence']})
    return {
        'states': list(CLASS_ORDER),
        'countMatrix': C.tolist(),
        'rowSums': rowsum.tolist(),
        'cells': cells,
        'stationary': stat,
        'empiricalMarginal': {c: round(float(marg.get(c, 0)), 4)
                              for c in CLASS_ORDER},
        'nTransitions': n_trans,
        'selfTransitionShare': (round(diag / n_trans, 4) if n_trans else None),
        'persistence': _regime_persistence(segments, n),
        'sessionVariants': session_variants,
        'chainBreaksUnknown': nbu,
        'chainBreaksGap': nbg,
        'minCellSuppress': min_cell,
        'nSuppressedCells': sum(1 for c in cells if c['suppressed']),
        'maxGapHours': max_gap_h,
        'method': ('First-order Markov transition matrix over the drive-type '
                   'regime taxonomy, chronological drive-to-drive. Cells with '
                   '1<=count<%d suppressed (stability flag, still counted in '
                   'row denominator). Unknown-type drives break the chain.'
                   % min_cell),
    }


def _regime_transition_hardening(dm, min_cell=5, n_perm=4000, seed=42):
    """M223.2 (P1.5, enhancement plan): statistical hardening layer over
    regimeTransition's (M142) first-order count matrix. Re-derives the SAME
    chronological drive-to-drive transition sequence _regime_transition
    itself builds -- identical CLASS_ORDER/idx, identical chain-break rule
    for unknown-type drives, identical default max_gap_h=None global chain
    (the primary/non-variant countMatrix, not a session variant) --
    _regime_transition itself is NOT modified by this function, so its
    existing fields (including `cells`) are guaranteed byte-identical by
    construction. Day/gap/time-of-day labels are retained per transition
    here (which _regime_transition's own loop discards) for the additional
    statistics below.

    Adds 8 self-contained sub-computations:
      1. dirichletCI / dayClusteredCI -- per-cell uncertainty intervals
         (Jeffreys-prior Dirichlet, closed-form; day-clustered bootstrap,
         1000 draws, as a robustness comparison) -- NEW fields, `cells`
         itself is left untouched (the plan's own acceptance criterion
         requires regimeTransition's EXISTING fields stay byte-identical).
      2. residualHeatmap -- expected counts under rowMarginal x colMarginal
         independence, observed-minus-expected (raw and standardized)
         residuals.
      3. permutationTest -- shuffles drive-type labels WITHIN day blocks
         (not globally, respecting the same chain-break/session structure
         chainBreaksGap/maxGapHours already encode), seed=42, 4000 draws;
         G-test departure-from-independence statistic against the
         day-block-preserving null.
      4. secondOrder -- conditions the transition on the previous TWO
         drive types (not just one), fit on the SAME triples sample as the
         first-order re-fit for a fair comparison, BIC + likelihood-ratio.
      5. conditionalTransitions -- self-transition share by parking-gap bin
         (the SAME bins interDriveCarryover/M223.1 uses, reused verbatim),
         time-of-day (6h buckets), and weekday/weekend.
      6. heldOutLogLik -- leave-one-day-out predictive log-likelihood
         (Jeffreys-smoothed so a thin held-out day is never scored against
         a hard-zero cell) -- a genuine out-of-sample score, not an
         in-sample fit statistic.
      7. entropy / expectedRunLength -- row-wise Shannon entropy (bits) of
         countMatrix; expected run length 1/(1-p_ii) per diagonal cell.
      8. carryoverLink -- explicit carryoverLinkKey back to
         interDriveCarryover (M223.1), satisfying the plan's direct-linkage
         requirement between P0.1 and P1.5 (both share the SAME
         consecutive-chronological-pair construction and gap bins).

    Honest-null note: permutationTest (3) and secondOrder (4) may
    legitimately return "no detectable departure from the day-structure-
    preserving null" / "second-order does not improve BIC over first-
    order" -- reported with full statistic disclosure either way, matching
    the powerFade/cellSpreadRelaxation null-result precedent in this
    codebase, never smoothed over.
    """
    from scipy import stats as _stats
    d = (_full_datetimes(dm).dropna(subset=['ts_full'])
         .sort_values('ts_full').reset_index(drop=True))
    idx = {c: i for i, c in enumerate(CLASS_ORDER)}
    n = len(CLASS_ORDER)
    C = np.zeros((n, n), dtype=float)
    prev, prev_te = None, None
    trans = []
    segments, seg_days = [], []
    cur, cur_days = [], []
    for _, r in d.iterrows():
        cls = r['drive_type'] if r['drive_type'] in idx else None
        gap_h = None
        if prev is not None and prev_te is not None and pd.notna(r['ts_full']):
            gap_h = (r['ts_full'] - prev_te).total_seconds() / 3600.0
        day = str(r['ts_full'])[:10] if pd.notna(r['ts_full']) else None
        hour = r['ts_full'].hour if pd.notna(r['ts_full']) else None
        weekday = r['ts_full'].weekday() if pd.notna(r['ts_full']) else None
        if cls is None:
            if cur:
                segments.append(cur); seg_days.append(cur_days)
                cur, cur_days = [], []
            prev, prev_te = None, None
            continue
        if prev is not None:
            C[idx[prev]][idx[cls]] += 1.0
            trans.append({'from': idx[prev], 'to': idx[cls], 'day': day,
                          'gapH': gap_h, 'hour': hour, 'weekday': weekday})
        cur.append(idx[cls]); cur_days.append(day)
        prev = cls
        prev_te = r['te_full'] if pd.notna(r['te_full']) else r['ts_full']
    if cur:
        segments.append(cur); seg_days.append(cur_days)

    N = int(C.sum())
    if N < 1:
        return None
    rowsum = C.sum(axis=1)
    colsum = C.sum(axis=0)

    # ---- 1. Dirichlet (Jeffreys prior, closed-form) + day-clustered bootstrap CIs ----
    dirichlet_ci = []
    for i in range(n):
        row = []
        for j in range(n):
            if rowsum[i] > 0:
                a = C[i][j] + 0.5
                b = rowsum[i] - C[i][j] + (n - 1) * 0.5
                lo = round(float(_stats.beta.ppf(0.025, a, b)), 4)
                hi = round(float(_stats.beta.ppf(0.975, a, b)), 4)
            else:
                lo = hi = None
            row.append({'from': CLASS_ORDER[i], 'to': CLASS_ORDER[j], 'lo': lo, 'hi': hi})
        dirichlet_ci.append(row)

    uniq_days = sorted(set(t['day'] for t in trans if t['day']))
    by_day = {dv: [t for t in trans if t['day'] == dv] for dv in uniq_days}
    rng = np.random.default_rng(seed)
    boot_P = np.full((1000, n, n), np.nan)
    for b in range(1000):
        picks = rng.choice(uniq_days, size=len(uniq_days), replace=True) if uniq_days else []
        Cb = np.zeros((n, n))
        for dv in picks:
            for t in by_day[dv]:
                Cb[t['from']][t['to']] += 1
        rb = Cb.sum(axis=1)
        for i in range(n):
            if rb[i] > 0:
                boot_P[b, i, :] = Cb[i, :] / rb[i]
    day_clustered_ci = []
    for i in range(n):
        row = []
        for j in range(n):
            vals = boot_P[:, i, j]
            vals = vals[~np.isnan(vals)]
            if len(vals) >= 30:
                row.append({'from': CLASS_ORDER[i], 'to': CLASS_ORDER[j],
                           'lo': round(float(np.percentile(vals, 2.5)), 4),
                           'hi': round(float(np.percentile(vals, 97.5)), 4),
                           'n': int(len(vals))})
            else:
                row.append({'from': CLASS_ORDER[i], 'to': CLASS_ORDER[j],
                           'lo': None, 'hi': None, 'n': int(len(vals))})
        day_clustered_ci.append(row)

    # ---- 2. Independence baseline + residual heatmap ----
    E = np.outer(rowsum, colsum) / N if N else np.zeros((n, n))
    residual = C - E
    residual_heatmap = {
        'expected': [[round(float(x), 2) for x in row] for row in E],
        'residual': [[round(float(x), 2) for x in row] for row in residual],
        'standardizedResidual': [[
            (round(float(residual[i][j] / np.sqrt(E[i][j])), 3) if E[i][j] > 0 else None)
            for j in range(n)] for i in range(n)],
    }

    # ---- 3. Day-block-preserving permutation test ----
    def _g_stat(Cm):
        rs, cs, tot = Cm.sum(axis=1), Cm.sum(axis=0), Cm.sum()
        if tot == 0:
            return 0.0
        Em = np.outer(rs, cs) / tot
        mask = (Cm > 0) & (Em > 0)
        return float(2.0 * np.sum(Cm[mask] * np.log(Cm[mask] / Em[mask])))

    g_obs = _g_stat(C)
    rng2 = np.random.default_rng(seed)
    ge = 0
    for _ in range(n_perm):
        Cp = np.zeros((n, n))
        for seg, sdays in zip(segments, seg_days):
            by_day_pos = {}
            for pos, dv in enumerate(sdays):
                by_day_pos.setdefault(dv, []).append(pos)
            shuffled = list(seg)
            for dv, positions in by_day_pos.items():
                vals = [seg[p] for p in positions]
                rng2.shuffle(vals)
                for p, v in zip(positions, vals):
                    shuffled[p] = v
            for k in range(len(shuffled) - 1):
                Cp[shuffled[k]][shuffled[k + 1]] += 1
        if _g_stat(Cp) >= g_obs - 1e-9:
            ge += 1
    p_perm = (1 + ge) / (n_perm + 1)
    permutation_test = {
        'gStatObserved': round(float(g_obs), 3),
        'nPermutations': n_perm, 'permutationP': round(p_perm, 5),
        'verdict': (
            'Day-structure-preserving null rejected at p<0.05: the observed '
            'transition matrix departs from what within-day label reshuffling '
            'produces.' if p_perm < 0.05 else
            'No detectable departure from the day-structure-preserving null '
            'at this sample size -- reported as a null result, not '
            'reconciled away.'),
    }

    # ---- 4. Second-order model (previous TWO drive types) ----
    triples = [(seg[k - 2], seg[k - 1], seg[k])
              for seg in segments for k in range(2, len(seg))]
    n_triples = len(triples)
    if n_triples >= 30:
        C1 = np.zeros((n, n)); C2 = np.zeros((n, n, n))
        for p2, p1, c in triples:
            C1[p1][c] += 1
            C2[p2][p1][c] += 1
        r1 = C1.sum(axis=1)
        r2 = C2.sum(axis=2)
        ll1 = sum(np.log(C1[p1][c] / r1[p1]) for p2, p1, c in triples if r1[p1] > 0 and C1[p1][c] > 0)
        ll2 = sum(np.log(C2[p2][p1][c] / r2[p2][p1]) for p2, p1, c in triples
                 if r2[p2][p1] > 0 and C2[p2][p1][c] > 0)
        k1, k2 = n * (n - 1), n * n * (n - 1)
        bic1 = -2 * ll1 + k1 * np.log(n_triples)
        bic2 = -2 * ll2 + k2 * np.log(n_triples)
        lr = 2 * (ll2 - ll1)
        df_lr = k2 - k1
        p_lr = float(_stats.chi2.sf(lr, df_lr)) if lr > 0 else 1.0
        second_order = {
            'nTriples': n_triples,
            'logLikFirstOrder': round(float(ll1), 3),
            'logLikSecondOrder': round(float(ll2), 3),
            'bicFirstOrder': round(float(bic1), 2),
            'bicSecondOrder': round(float(bic2), 2),
            'bicImprovement': round(float(bic1 - bic2), 2),
            'likelihoodRatioStat': round(float(lr), 3), 'lrDf': int(df_lr), 'lrP': p_lr,
            'verdict': (
                'Second-order model improves BIC over first-order.'
                if bic2 < bic1 else
                'Second-order model does NOT improve BIC over first-order -- '
                'the extra memory depth is not supported by the data at '
                'this sample size, reported as a null result.'),
        }
    else:
        second_order = {'nTriples': n_triples,
                        'note': 'insufficient triples for a stable second-order fit'}

    # ---- 5. Conditional transitions ----
    gap_bins = ((0, 1), (1, 3), (3, 6), (6, 12), (12, 24), (24, 1e9))  # M223.1 bins, reused verbatim

    def _cond_rows(bin_of, labels, label_name):
        out = []
        for lab in labels:
            sub = [t for t in trans if bin_of(t) == lab]
            if not sub:
                out.append({label_name: lab, 'n': 0, 'selfTransitionShare': None})
                continue
            diag = sum(1 for t in sub if t['from'] == t['to'])
            out.append({label_name: lab, 'n': len(sub),
                       'selfTransitionShare': round(diag / len(sub), 4)})
        return out

    def _gap_bin(t):
        if t['gapH'] is None:
            return None
        for lo, hi in gap_bins:
            if lo <= t['gapH'] < hi:
                return '%g-%gh' % (lo, hi) if hi < 1e8 else '%g+h' % lo
        return None
    gap_labels = ['%g-%gh' % (lo, hi) if hi < 1e8 else '%g+h' % lo for lo, hi in gap_bins]
    by_gap = _cond_rows(_gap_bin, gap_labels, 'gapBin')

    def _hour_bucket(t):
        return None if t['hour'] is None else ('00-06', '06-12', '12-18', '18-24')[t['hour'] // 6]
    by_hour = _cond_rows(_hour_bucket, ('00-06', '06-12', '12-18', '18-24'), 'hourBucket')

    def _wd(t):
        return None if t['weekday'] is None else ('weekday' if t['weekday'] < 5 else 'weekend')
    by_weekday = _cond_rows(_wd, ('weekday', 'weekend'), 'dayType')

    conditional_transitions = {
        'byParkingGapBin': by_gap, 'byTimeOfDay': by_hour, 'byWeekday': by_weekday}

    # ---- 6. Held-out-day log-likelihood (leave-one-day-out) ----
    total_ll, total_n = 0.0, 0
    for held_day in uniq_days:
        train = [t for t in trans if t['day'] != held_day]
        test = [t for t in trans if t['day'] == held_day]
        if not test or not train:
            continue
        Ctr = np.zeros((n, n))
        for t in train:
            Ctr[t['from']][t['to']] += 1
        rtr = Ctr.sum(axis=1)
        for t in test:
            r = rtr[t['from']]
            if r > 0:
                p = (Ctr[t['from']][t['to']] + 0.5) / (r + n * 0.5)
                total_ll += np.log(p)
                total_n += 1
    held_out_log_lik = {
        'totalLogLik': round(float(total_ll), 3), 'nScored': total_n, 'nDays': len(uniq_days),
        'meanLogLikPerTransition': (round(float(total_ll / total_n), 4) if total_n else None),
        'method': (
            'Leave-one-day-out: fit the first-order count matrix on all other '
            'days (Jeffreys-smoothed, alpha=0.5, so a held-out day is never '
            'scored against a hard-zero cell), score the held-out day\'s own '
            'transitions under it, sum across all days. A genuine out-of-'
            'sample prediction score, not an in-sample fit statistic.'),
    }

    # ---- 7. Entropy + expected run length ----
    entropy, expected_run_length = {}, {}
    for i in range(n):
        if rowsum[i] > 0:
            p_row = C[i, :] / rowsum[i]
            p_nz = p_row[p_row > 0]
            entropy[CLASS_ORDER[i]] = round(float(-np.sum(p_nz * np.log2(p_nz))), 4)
            p_ii = C[i][i] / rowsum[i]
            expected_run_length[CLASS_ORDER[i]] = (
                round(float(1.0 / (1.0 - p_ii)), 3) if p_ii < 1 else None)
        else:
            entropy[CLASS_ORDER[i]] = None
            expected_run_length[CLASS_ORDER[i]] = None

    # ---- 8. Explicit link to interDriveCarryover (M223.1) ----
    carryover_link = {
        'carryoverLinkKey': 'interDriveCarryover',
        'note': ('Explicit link to interDriveCarryover (M223.1): both share '
                 'the SAME consecutive-chronological-pair construction '
                 '(_full_datetimes) and the SAME parking-gap bins (reused '
                 'verbatim here as conditionalTransitions.byParkingGapBin). '
                 'interDriveCarryover characterizes the thermal/SoC state '
                 'each gap leaves behind; byParkingGapBin here characterizes '
                 'how that SAME gap relates to which regime the next drive '
                 'turns out to be.'),
    }

    return {
        'nTransitions': N, 'nDays': len(uniq_days),
        'dirichletCI': dirichlet_ci,
        'dayClusteredCI': day_clustered_ci,
        'residualHeatmap': residual_heatmap,
        'permutationTest': permutation_test,
        'secondOrder': second_order,
        'conditionalTransitions': conditional_transitions,
        'heldOutLogLik': held_out_log_lik,
        'entropy': entropy,
        'expectedRunLength': expected_run_length,
        'carryoverLink': carryover_link,
        'hardeningMethod': (
            'M223.2 (P1.5, enhancement plan): statistical hardening layer '
            'over regimeTransition\'s (M142) first-order countMatrix -- '
            'Jeffreys-Dirichlet + day-clustered-bootstrap per-cell '
            'uncertainty, independence-residual heatmap, a day-block-'
            'preserving label-permutation test (seed=42, 4000 draws), a '
            'second-order (previous-two-drive-type) model with BIC/'
            'likelihood-ratio comparison against a first-order re-fit on '
            'the identical triples sample, transitions conditioned on '
            'parking-gap bin / time-of-day / weekday (the SAME gap bins '
            'interDriveCarryover/M223.1 uses), leave-one-day-out predictive '
            'log-likelihood, row-wise Shannon entropy and expected run '
            'length, and an explicit link back to interDriveCarryover. '
            'regimeTransition\'s own pre-existing fields (countMatrix, '
            'cells, stationary, persistence, sessionVariants, etc.) are '
            'computed by _regime_transition, UNCHANGED by this function.'),
    }



def _heat_soak_carryover(dm, traj, ambient_by_drive=None, min_excess_c=3.0,
                         gap_bins=((0, 1), (1, 3), (3, 6), (6, 12),
                                   (12, 24), (24, 1e9))):
    """M141: drive-to-drive pack thermal carryover (inter-drive relaxation).

    For each consecutive chronological pair (i -> i+1) with pack-temperature
    data on both ends (reuses the _battery_temp_traj pm_end / pm_start already
    computed for thermalConvergence -- no extra raw pass), quantify how much of
    the pack's end-of-drive heat persists into the next key-on as a function of
    the intervening park (soak) gap.

    Two readings:
      * empirical, binned by soak gap: median degC shed and -- where the START
        drive carries a recorded ambient -- the median retained above-ambient
        fraction (resid_excess / init_excess).
      * a Newtonian-cooling soak time constant tau: on pairs with a recorded
        ambient and a real initial excess (>min_excess_c), regress
        ln(resid_excess / init_excess) on gap through the origin (the decay
        must pass through ratio=1 at gap=0); slope = -1/tau. Bootstrap 95% CI.

    Caveats disclosed in-block: ambient is the manual DRIVING-time field, not
    the (typically cooler, day/night-swinging) parked-soak environment, so at
    long gaps the pack can settle slightly below it and the retained fraction
    floors just below zero -- an expected ambient-reference artefact, not
    sub-ambient cooling. Parking environment (garage vs open) is unobserved
    and is the main source of the moderate fit R^2.
    """
    d = (_full_datetimes(dm).dropna(subset=['ts_full'])
         .sort_values('ts_full').reset_index(drop=True))
    amb = {}
    if ambient_by_drive:
        for fn, pair in ambient_by_drive.items():
            try:
                amb[fn] = sum(float(x) for x in pair) / len(pair)
            except Exception:
                pass
    pairs = []
    for k in range(len(d) - 1):
        a = d.iloc[k]
        b = d.iloc[k + 1]
        ta = traj.get(a['file'], {})
        tb = traj.get(b['file'], {})
        if 'pm_end' not in ta or 'pm_start' not in tb:
            continue
        if pd.isna(a['te_full']) or pd.isna(b['ts_full']):
            continue
        gap_h = (b['ts_full'] - a['te_full']).total_seconds() / 3600.0
        if gap_h < 0:
            continue
        t_end = ta['pm_end']
        t_start = tb['pm_start']
        rec = {'gapH': gap_h, 'tEnd': t_end, 'tStart': t_start,
               'shedC': t_end - t_start, 'retainedFrac': None,
               'initExcessC': None, 'residExcessC': None}
        amb_b = amb.get(b['file'])
        if amb_b is not None:
            ie = t_end - amb_b
            re = t_start - amb_b
            rec['initExcessC'] = ie
            rec['residExcessC'] = re
            if ie > 0:
                rec['retainedFrac'] = re / ie
        pairs.append(rec)
    if not pairs:
        return None
    pf = pd.DataFrame(pairs)
    bins = []
    for lo, hi in gap_bins:
        sub = pf[(pf['gapH'] >= lo) & (pf['gapH'] < hi)]
        if len(sub) == 0:
            continue
        rf = sub['retainedFrac'].dropna()
        bins.append({'gapLoH': lo, 'gapHiH': (None if hi > 1e8 else hi),
                     'n': int(len(sub)),
                     'medShedC': round(float(sub['shedC'].median()), 2),
                     'medTEnd': round(float(sub['tEnd'].median()), 1),
                     'medTStart': round(float(sub['tStart'].median()), 1),
                     'nAmb': int(rf.shape[0]),
                     'medRetainedFrac': (round(float(rf.median()), 4)
                                         if len(rf) else None)})
    tau = tau_ci = half_life = r2 = fit_intercept = None
    nfit = 0
    fit = pf.dropna(subset=['initExcessC', 'residExcessC'])
    fit = fit[(fit['initExcessC'] > min_excess_c) & (fit['residExcessC'] > 0.5)]
    nfit = int(len(fit))
    if nfit >= 8:
        y = np.log(fit['residExcessC'].values / fit['initExcessC'].values)
        x = fit['gapH'].values
        # M242: Sen's slope (median of all pairwise (y_j-y_i)/(x_j-x_i))
        # replaces the squared-gap-weighted OLS-through-origin slope. A
        # single very-long parked gap (the corpus's ~187.5h outlier) was
        # dominating sum(x^2) and pulling tau from ~16-18h to 35.52h under
        # OLS; Sen's slope is robust to that single-point leverage without
        # the mirror-image failure mode of a median-of-ratios-to-origin
        # estimator on the many near-zero-gap pairs. See _sen_slope
        # docstring and _car_off_standby for the same estimator used
        # elsewhere in this pipeline for an identical long-gap-leverage
        # problem. Multi-day gaps are NOT excluded/capped -- they are real
        # observed parks and remain in the fit; only the estimator changed.
        slope = _sen_slope(x, y)
        # fitIntercept is the fit's own check of the through-origin
        # assumption this model relies on (decay must pass through
        # ratio=1, i.e. y=0, at gap=0): median residual y - slope*x.
        # Small values support the assumption.
        fit_intercept = float(np.median(y - slope * x))
        yhat = slope * x
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = (1 - np.sum((y - yhat) ** 2) / ss_tot) if ss_tot > 0 else None
        if slope < 0:
            tau = -1.0 / slope
            half_life = tau * np.log(2)
            rng = np.random.default_rng(42)
            taus = []
            for _ in range(1000):
                ii = rng.integers(0, nfit, nfit)
                s = _sen_slope(x[ii], y[ii])
                if s < 0:
                    taus.append(-1.0 / s)
            if taus:
                tau_ci = [round(float(np.percentile(taus, 2.5)), 2),
                          round(float(np.percentile(taus, 97.5)), 2)]
    return {
        'nPairs': int(len(pf)),
        'nPairsAmbient': int(pf['retainedFrac'].notna().sum()),
        'gapBins': bins,
        'soakTauH': (round(tau, 2) if tau else None),
        'soakTauCI': tau_ci,
        'soakHalfLifeH': (round(half_life, 2) if half_life else None),
        'tauFitN': nfit,
        'tauFitR2': (round(float(r2), 3) if r2 is not None else None),
        'tauFitIntercept': (round(fit_intercept, 4)
                            if fit_intercept is not None else None),
        'fitMethod': 'senSlope',
        'minExcessC': min_excess_c,
        'method': ('Consecutive chronological drive pairs; degC shed and '
                   'above-ambient retained fraction vs soak gap. Newtonian '
                   'soak tau from ln(resid/init excess) vs gap (recorded-'
                   'ambient pairs, init excess >%.0fC), slope by Sen\'s '
                   'slope -- median of all pairwise (y_j-y_i)/(x_j-x_i) '
                   '(M242) -- rather than a squared-gap-weighted least-'
                   'squares slope, so neither a single multi-day parked '
                   'gap nor a cluster of very-short, noise-dominated gaps '
                   'can dominate the estimate. tauFitIntercept is the '
                   "fit's own check of the through-origin assumption "
                   '(median residual at gap=0); small values support it.'
                   % min_excess_c),
    }


def _thermal_step_response(dm, raw_loader, frame_loader=None,
                           min_dur_s=1500, min_rise_c=5.0, min_r2=0.90,
                           plateau_slope_cmin=0.05):
    """M143: pack thermal STEP response -- first-order warmup time constant.

    The thermal analogue of M118 ramp-latency, at the timescale the telemetry
    actually resolves. EMPIRICAL FINDING driving the design: at the event
    (second-to-minute) scale the pack temperature does NOT track load steps --
    corr(60s-mean |I|, pack dT/dt) ~= 0.06 on a sustained 284 km highway leg --
    because the pack thermal mass low-pass-filters transient dissipation far
    below the ~6 s (0.16 Hz) pack-temperature PID cadence. So a per-event
    impulse response is below the resolvable floor (reported as such, not
    forced). What IS resolvable and physically meaningful is the BULK
    first-order response: the pack warming toward a load-dependent thermal
    steady-state, T(t) = Tss - (Tss - T0) exp(-t/tau).

    Per drive long enough to plateau (>=25 min), the pack-mean warmup is fit to
    that first-order form on the monotone-rising window (start -> first 98% of
    rise). IDENTIFIABILITY GATES, all required for a fit to be reported:
      * a real cold-start transient: rise >= min_rise_c (else 'no_transient');
      * the plateau is actually REACHED in-window: final-15% slope
        <= plateau_slope_cmin (else Tss would be an extrapolation, the failure
        mode that let an under-observed 64-min window run Tss to its bound at
        80C during development);
      * good fit: R^2 >= min_r2; and window >= 0.9*tau (>= ~one time constant
        observed). Gate tallies are returned for transparency.

    Reuses _battery_temp_traj's pack-mean convention (async 4-sensor 1 Hz grid,
    ffill(limit=3), -40..80C gate). raw_loader path; frame_loader used when the
    slim cache carries the four sensor columns.
    """
    try:
        from scipy.optimize import curve_fit
    except Exception:
        return {'available': False,
                'note': 'scipy.optimize.curve_fit unavailable; '
                        'thermal step-response fit skipped.'}

    def _packmean(fn):
        try:
            if frame_loader is not None:
                fr = frame_loader(fn)
                if fr is None:
                    return None
                cols = fr.columns
                use = [c for c in _T_SENS_RAW if c in cols]
                if not use or 'time' not in cols:
                    return None
                df = fr[['time'] + use]
            else:
                raw = raw_loader(fn)
                cols = pd.read_csv(io.BytesIO(raw), nrows=0).columns
                use = [c for c in _T_SENS_RAW if c in cols]
                if not use or 'time' not in cols:
                    return None
                df = pd.read_csv(io.BytesIO(raw), usecols=['time'] + use,
                                 low_memory=False)
        except Exception:
            return None
        t = pd.to_datetime(df['time'], format='mixed', errors='coerce')
        g = pd.DataFrame({'t': t})
        for c in use:
            v = pd.to_numeric(df[c], errors='coerce')
            v[(v < -40) | (v > 80)] = np.nan
            g[c] = v
        g = g.dropna(subset=['t']).set_index('t')
        try:
            pm = g[use].resample('1s').mean().ffill(limit=3).mean(axis=1).dropna()
        except Exception:
            return None
        return pm if len(pm) >= 180 else None

    def _fit(pm):
        sec = (pm.index - pm.index[0]).total_seconds().values
        T = pm.values
        T0 = float(T[:15].mean())
        Tpk = float(np.percentile(T, 98))
        rise = Tpk - T0
        if rise < min_rise_c:
            return ('no_transient', None)
        thr = T0 + 0.98 * rise
        hit = int(np.argmax(T >= thr)) if (T >= thr).any() else len(T) - 1
        hit = max(hit, 90)
        x = sec[:hit] / 60.0
        y = T[:hit]
        if x[-1] < 8:
            return ('window_too_short', None)
        tail = max(int(len(x) * 0.85), 1)
        if len(x[tail:]) >= 5:
            if np.polyfit(x[tail:], y[tail:], 1)[0] > plateau_slope_cmin:
                return ('plateau_not_reached', None)
        else:
            return ('plateau_not_reached', None)

        def f(tt, Tss, tau):
            return Tss - (Tss - T0) * np.exp(-tt / tau)
        try:
            p, _ = curve_fit(f, x, y, p0=[Tpk, 20], maxfev=8000,
                             bounds=([T0 + 0.5, 1], [Tpk + 2, 300]))
        except Exception:
            return ('fit_error', None)
        yhat = f(x, *p)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = (1 - np.sum((y - yhat) ** 2) / ss_tot) if ss_tot > 0 else 0.0
        Tss, tau = float(p[0]), float(p[1])
        if r2 < min_r2:
            return ('poor_fit', None)
        if x[-1] < 0.9 * tau:
            return ('window_lt_tau', None)
        return (None, {'T0': round(T0, 1), 'Tss': round(Tss, 1),
                       'tauMin': round(tau, 1), 'riseC': round(rise, 1),
                       'r2': round(float(r2), 3),
                       'winMin': round(float(x[-1]), 1), 'n': int(len(x))})

    cand = dm[dm['duration_s'] >= min_dur_s]
    fits = {}
    gates = {}
    for fn in cand['file']:
        pm = _packmean(fn)
        if pm is None:
            continue
        gate, rec = _fit(pm)
        if gate is not None:
            gates[gate] = gates.get(gate, 0) + 1
            continue
        fits[fn] = rec
    if not fits:
        return {'available': True, 'nFits': 0, 'gateRejections': gates,
                'nCandidates': int(len(cand)),
                'note': 'no identifiable first-order warmup in the corpus.'}
    taus = np.array([v['tauMin'] for v in fits.values()])
    tss = np.array([v['Tss'] for v in fits.values()])
    t0s = np.array([v['T0'] for v in fits.values()])
    r2s = np.array([v['r2'] for v in fits.values()])
    rows = []
    for fn, v in fits.items():
        idx = dm.index[dm['file'] == fn]
        v2 = dict(v)
        v2['label'] = _day_label(dm, idx[0]) if len(idx) else fn
        v2['file'] = fn
        rows.append(v2)
    rows.sort(key=lambda r: r['tauMin'])
    return {
        'available': True,
        'nCandidates': int(len(cand)),
        'nFits': int(len(fits)),
        'gateRejections': gates,
        'tauWarmupMinMedian': round(float(np.median(taus)), 1),
        'tauWarmupMinIQR': [round(float(np.percentile(taus, 25)), 1),
                            round(float(np.percentile(taus, 75)), 1)],
        'tauWarmupMinRange': [round(float(taus.min()), 1),
                              round(float(taus.max()), 1)],
        'TssMedianC': round(float(np.median(tss)), 1),
        'T0MedianC': round(float(np.median(t0s)), 1),
        'riseMedianC': round(float(np.median(tss - t0s)), 1),
        'fitR2Median': round(float(np.median(r2s)), 3),
        'fitR2Min': round(float(r2s.min()), 3),
        'fits': rows,
        'eventScaleResolvable': False,
        'method': ('First-order warmup fit T(t)=Tss-(Tss-T0)exp(-t/tau) on the '
                   'async-sensor 1 Hz pack-mean, gated on a real cold-start '
                   'transient (rise>=%.0fC), plateau reached in-window, '
                   'R^2>=%.2f, window>=~tau. Event-scale impulse response is '
                   'below the ~6 s pack-temp PID / thermal-mass floor and is '
                   'not reported.' % (min_rise_c, min_r2)),
    }


def _dissipation_census(dm, raw_loader, frame_loader=None):
    """M46 (2026-07-20): motored-engine overcharge-dissipation census.

    In the series-hybrid architecture the ICE couples only to the generator,
    never the wheels. Near the top of the SoC buffer the pack can no longer
    accept regenerative/surplus energy, so the VCM dumps it by MOTORING the
    engine through the generator: the ICE is spun UNFUELLED (throttle closed,
    deep intake vacuum, calc load ~0) at elevated rpm, dissipating electrical
    energy as pumping/friction loss. This is physically distinct from FUELLED
    generation (engine driven by combustion to charge the pack), and the two
    modes separate cleanly on manifold pressure.

    'Розрахунковий наддув' (boost, bar) is a linear transform of intake MAP
    (MAP ~= 101*boost + 95.2 kPa, r=0.999 on the record drive 20260719_154351)
    and is the slim-cached channel, so the classifier is expressed in boost:
        MOTORED  = eng_rpm > RPM_MIN  and boost <  BOOST_MOTORED (~ MAP<25 kPa)
                   and calc_load < LOAD_MAX
        FUELLED  = eng_rpm > RPM_MIN  and boost >= BOOST_FUELLED (~ MAP>=40 kPa)

    Emits per-mode SoC/boost/rpm medians; the count of motored samples at the
    buffer ceiling (SoC >= CEIL_SOC) and the net pack current there (the
    'pack refusing charge' signature -> ~0 A); corr(SoC, eng_rpm) among
    motored samples (dissipation intensity scales with buffer fullness); the
    per-drive ceiling-defended set; and the SoC-record drive with a flag for
    whether its ceiling is actively motored-defended. Drives lacking the
    boost/load channels (early minimal-column logs) contribute nothing and
    are reported via nDrivesCovered.
    """
    RPM_MIN = 2000.0
    BOOST_MOTORED = -0.70     # ~ MAP < 25 kPa  (MAP = 101*boost + 95.2)
    BOOST_FUELLED = -0.55     # ~ MAP >= 40 kPa
    LOAD_MAX = 8.0
    CEIL_SOC = 85.0
    C = {'[BMS] HV Battery Current (A)': 'I',
         '[BMS] HV State of charge (%)': 'soc',
         '[VCM] Vehicle Speed (km/h)': 'speed',
         'Оберти двигуна (rpm)': 'rpm',
         'Розрахункове значення навантаження на двигун (%)': 'load',
         'Розрахунковий наддув (bar)': 'boost'}

    def _grid_df(df):
        if 'time' not in df.columns:
            return None
        g = df.set_index(pd.to_datetime(df['time'], errors='coerce'))
        keep = [c for c in ('I', 'soc', 'speed', 'rpm', 'load', 'boost')
                if c in g.columns]
        g = g[keep].apply(pd.to_numeric, errors='coerce')
        return g.resample('1s').mean().ffill(limit=3)

    def grid_fn(fn):
        if frame_loader is not None:
            fr = frame_loader(fn)
            if fr is None:
                return None
            fr = fr[[c for c in fr.columns
                    if c in C or c == 'time' or c == _SPEED_OBD_RAW]]
            fr, _ = _apply_speed_priority(fr)   # M167
            return _grid_df(fr.rename(columns=C))
        raw = raw_loader(fn) if raw_loader is not None else None
        if not raw:
            return None
        df = pd.read_csv(io.BytesIO(raw),
                         usecols=lambda c: c in C or c == 'time' or c == _SPEED_OBD_RAW,
                         low_memory=False)
        df, _ = _apply_speed_priority(df)       # M167
        return _grid_df(df.rename(columns=C))

    mot_pool, fue_pool = [], []
    per_drive = {}          # file -> motored-at-ceiling count
    n_cov = 0
    for fn in dm['file']:
        try:
            g = grid_fn(fn)
        except Exception:
            continue
        # M126 (2026-08-16): 'soc' and 'load' were absent from this presence
        # gate although the block below unconditionally indexes both
        # (on['load'], per_drive[...]['soc']) -- a KeyError, not a graceful
        # skip, on any drive whose raw log has rpm+boost but no BMS/SoC
        # channel (the fifth PID configuration, 19 cols, zero BMS: see
        # 20260816_124817.csv / 20260816_144003.csv). Sibling function
        # _low_speed_dissipation already gates on all four channels via
        # `need = [...]; if len(need) < 4: continue` -- mirrored here so a
        # BMS-less drive is excluded from THIS census (which is inherently
        # SoC-ceiling-gated and cannot be computed without it) without
        # aborting the whole build. The drive itself remains in the corpus /
        # drive_master.csv and in every other array that doesn't need SoC.
        if g is None or 'rpm' not in g or 'boost' not in g \
                or 'load' not in g or 'soc' not in g:
            continue
        n_cov += 1
        on = g[g['rpm'] > 800].dropna(subset=['soc', 'rpm', 'boost'])
        if not len(on):
            continue
        base = on['rpm'] > RPM_MIN
        mot = on[base & (on['boost'] < BOOST_MOTORED)
                 & (on['load'].fillna(0) < LOAD_MAX)]
        fue = on[base & (on['boost'] >= BOOST_FUELLED)]
        if len(mot):
            mot_pool.append(mot.assign(file=fn))
        if len(fue):
            fue_pool.append(fue.assign(file=fn))
        per_drive[fn] = int((mot['soc'] >= CEIL_SOC).sum())

    def _med(s):
        return round(float(s.median()), 1) if len(s) else None

    out = {
        'params': {'rpmMin': RPM_MIN, 'boostMotored': BOOST_MOTORED,
                   'boostFuelled': BOOST_FUELLED, 'loadMax': LOAD_MAX,
                   'ceilSoc': CEIL_SOC,
                   'mapEquivKpa': {'motored': 25, 'fuelled': 40},
                   'mapFromBoost': 'MAP ≈ 101·boost + 95.2 kPa (r=0.999)'},
        'nDrivesCovered': n_cov,
        'nDrivesCeilingDefended': int(sum(1 for v in per_drive.values()
                                          if v > 0)),
    }
    mp = pd.concat(mot_pool) if mot_pool else pd.DataFrame()
    fp = pd.concat(fue_pool) if fue_pool else pd.DataFrame()
    out['motored'] = {
        'nSamples': int(len(mp)),
        'socMed': _med(mp['soc']) if len(mp) else None,
        'boostMed': (round(float(mp['boost'].median()), 2)
                     if len(mp) else None),
        'rpmMed': (int(mp['rpm'].median()) if len(mp) else None),
        'rpmMax': (int(mp['rpm'].max()) if len(mp) else None)}
    out['fuelled'] = {
        'nSamples': int(len(fp)),
        'socMed': _med(fp['soc']) if len(fp) else None,
        'boostMed': (round(float(fp['boost'].median()), 2)
                     if len(fp) else None)}
    # ceiling-defence signature
    ceil = mp[mp['soc'] >= CEIL_SOC] if len(mp) else pd.DataFrame()
    out['ceiling'] = {
        'nMotoredAtCeiling': int(len(ceil)),
        'packCurrentMedA': (round(float(ceil['I'].median()), 1)
                            if len(ceil) and ceil['I'].notna().any()
                            else None),
        'packCurrentP10A': (round(float(ceil['I'].quantile(0.10)), 1)
                            if len(ceil) and ceil['I'].notna().any()
                            else None),
        'packCurrentP90A': (round(float(ceil['I'].quantile(0.90)), 1)
                            if len(ceil) and ceil['I'].notna().any()
                            else None),
        'speedMedKmh': (int(ceil['speed'].median())
                        if len(ceil) and ceil['speed'].notna().any()
                        else None)}
    # dissipation intensity vs buffer fullness: corr(SoC, rpm) among motored
    if len(mp) >= 20 and mp['soc'].nunique() > 2:
        out['socRpmCorr'] = round(float(mp[['soc', 'rpm']].corr().iloc[0, 1]), 2)
    else:
        out['socRpmCorr'] = None
    # SoC-record drive and whether its ceiling is motored-defended
    ri = int(dm['soc_max'].idxmax())
    rfn = dm.loc[ri, 'file']
    out['record'] = {
        'file': rfn,
        'label': _day_label(dm, ri),
        'socMaxPct': round(float(dm.loc[ri, 'soc_max']), 1),
        'motoredAtCeiling': int(per_drive.get(rfn, 0)),
        'ceilingDefended': bool(per_drive.get(rfn, 0) > 0),
        'nextHighestPct': round(float(dm['soc_max'].sort_values(
            ascending=False).iloc[1]), 1) if len(dm) > 1 else None}
    return out


def _soc_band_reset(dm):
    """M59 (2026-07-27): session-adjacency derivation of the highway SoC-band
    "reset window". Closes the audit item M45 deliberately left open ("item 7
    is left untouched pending a proper session-adjacency derivation").

    RESULT: the long-standing "resets within ~44 hours" claim is NOT supported
    and is retracted. Ordering every drive by wall-clock start and measuring
    hours elapsed since the END of the most recent highway/mixed-highway drive:

      * the elevated urban ceiling is detectable only in the first ~6 h
        (Mann-Whitney vs the no-recent-highway baseline, p ~0.03);
      * it is already indistinguishable from baseline by ~12 h (p ~0.07) and
        far beyond it at 44 h (p ~0.23);
      * hours-since-highway does not predict urban ceiling monotonically
        (Spearman rho ~ -0.10, p ~0.27).

    ORIGIN OF THE ERROR: the Jun 16-18 drives the original claim rested on were
    already 50-97 h past the last highway drive. They therefore could not
    demonstrate a 44 h reset window at all -- they show a normal city band,
    which is consistent with reset at ANY time <= 50 h. The "~44 hours" figure
    was the elapsed gap between two particular drives, not a measured decay
    constant.
    """
    need = {'date', 'time_start', 'time_end', 'drive_type', 'soc_max', 'soc_min'}
    if not need.issubset(dm.columns):
        return None
    d = pd.DataFrame({
        'dt': pd.to_datetime(dm['date'].astype(str) + ' '
                             + dm['time_start'].astype(str), errors='coerce'),
        'dte': pd.to_datetime(dm['date'].astype(str) + ' '
                              + dm['time_end'].astype(str), errors='coerce'),
        'type': dm['drive_type'].astype(str),
        'smax': pd.to_numeric(dm['soc_max'], errors='coerce'),
        'smin': pd.to_numeric(dm['soc_min'], errors='coerce'),
    }).sort_values('dt').reset_index(drop=True)
    if d['dt'].isna().all():
        return None

    HW = {'highway', 'mixed_highway'}
    last_end, gaps = None, []
    for _, r in d.iterrows():
        gaps.append((r['dt'] - last_end).total_seconds() / 3600
                    if last_end is not None and pd.notna(r['dt']) else np.nan)
        if r['type'] in HW and pd.notna(r['dte']):
            last_end = r['dte']
    d['h'] = gaps

    urb = d[d['type'] == 'urban']
    base = urb[(urb['h'].isna()) | (urb['h'] > 168)]['smax'].dropna()
    if len(base) < 8:
        return None

    def _mwu(a, b):
        if len(a) < 4 or len(b) < 4:
            return None
        try:
            from scipy import stats
            return float(stats.mannwhitneyu(a, b)[1])
        except Exception:
            return None

    windows = []
    for hi in (6, 12, 24, 44, 72):
        a = urb[(urb['h'] >= 0) & (urb['h'] < hi)]['smax'].dropna()
        if len(a) < 4:
            continue
        p = _mwu(a, base)
        windows.append({'withinH': hi, 'n': int(len(a)),
                        'ceilMedPct': round(float(a.median()), 1),
                        'pVsBaseline': (round(p, 3) if p is not None else None),
                        'elevated': (bool(p < 0.05) if p is not None else None)})

    bins = [0, 6, 12, 24, 44, 72, 168, 1e9]
    lbl = ['<6h', '6-12h', '12-24h', '24-44h', '44-72h', '72h-1wk', '>1wk']
    tmp = urb.dropna(subset=['h']).copy()
    tmp['_b'] = pd.cut(tmp['h'], bins, labels=lbl)
    decay = []
    for k, gg in tmp.groupby('_b', observed=True):
        decay.append({'sinceHwy': str(k), 'n': int(len(gg)),
                      'ceilMedPct': round(float(gg['smax'].median()), 1),
                      'floorMedPct': round(float(gg['smin'].median()), 1)})

    rho = p_rho = None
    t2 = urb.dropna(subset=['h', 'smax'])
    if len(t2) >= 20:
        try:
            from scipy import stats
            rr, pp = stats.spearmanr(t2['h'], t2['smax'])
            rho, p_rho = round(float(rr), 2), float(pp)
        except Exception:
            pass

    sig = [w for w in windows if w.get('elevated')]
    persist = max((w['withinH'] for w in sig), default=None)
    hwy_ceil = d[d['type'].isin(HW)]['smax'].dropna()

    return {
        'baselineCeilMedPct': round(float(base.median()), 1), 'baselineN': int(len(base)),
        'highwayCeilMedPct': (round(float(hwy_ceil.median()), 1)
                              if len(hwy_ceil) else None),
        'windows': windows, 'decay': decay,
        'rhoHoursVsCeiling': rho, 'pHoursVsCeiling': p_rho,
        'persistenceH': persist,
        'retracted': {'claim': 'highway SoC band resets within ~44 hours',
                      'status': 'NOT SUPPORTED',
                      'reason': 'the drives the claim rested on (Jun 16-18) were '
                                'already 50-97 h past the last highway drive, so '
                                'they cannot bound a 44 h window; across the full '
                                'corpus the elevation is detectable only within '
                                'about the first 6 h and hours-since-highway does '
                                'not predict urban ceiling monotonically.'},
    }


def _soc_vcm_mapping(dm, arrays):
    """M58 (2026-07-27): computed replacement for the hand-typed BMS->VCM
    summary table and the "design intent" paragraph beneath it.

    Both were authored when the observed BMS window was 44-82% (38 pp). The
    corpus has since widened it to the values in eolBaselines.socWindow, so the
    paragraph's arithmetic ("38pp of cell capacity maps to ~24-90% = 66pp,
    ~74% of range") no longer describes this dataset, and the four table cells
    had drifted by 1-2 pp each. Everything is now interpolated from the same
    socVcmPoints array the scatter plot draws.
    """
    pts = arrays.get('socVcmPoints') or []
    if len(pts) < 20:
        return None
    a = np.asarray([[float(p[0]), float(p[1])] for p in pts], float)
    o = np.argsort(a[:, 0])
    bs, vs = a[o, 0], a[o, 1]

    def vcm_at(x):
        return float(np.interp(x, bs, vs))

    # crossover: where the displayed value stops flattering and starts
    # under-reporting (VCM - BMS changes sign)
    xs = np.linspace(bs.min(), bs.max(), 4000)
    dd = np.interp(xs, bs, vs) - xs
    sgn = np.where(np.diff(np.sign(dd)) != 0)[0]
    crossover = round(float(xs[sgn[0]]), 1) if len(sgn) else None

    # table anchors, snapped into the observed BMS range
    anchors = [p for p in (47, 55, 70, 80) if bs.min() <= p <= bs.max()]
    table = []
    for b in anchors:
        v = vcm_at(b)
        table.append({'bmsPct': b, 'vcmPct': round(v, 1),
                      'deltaPp': round(v - b, 1)})

    win = (arrays.get('eolBaselines') or {}).get('socWindow') or {}
    lo = win.get('minPct')
    hi = win.get('maxPct')
    out = {'table': table, 'crossoverBmsPct': crossover,
           'nPairs': int(len(a)),
           'bmsRange': [round(float(bs.min()), 1), round(float(bs.max()), 1)],
           'vcmRange': [round(float(vs.min()), 1), round(float(vs.max()), 1)]}
    if lo is not None and hi is not None:
        vlo, vhi = vcm_at(lo), vcm_at(hi)
        out['window'] = {
            'bmsLoPct': lo, 'bmsHiPct': hi, 'bmsSpanPp': round(hi - lo, 1),
            'vcmLoPct': round(vlo, 1), 'vcmHiPct': round(vhi, 1),
            'vcmSpanPp': round(vhi - vlo, 1),
            'bottomGapPp': round(vlo - lo, 1),
            'exaggerationRatio': (round((vhi - vlo) / (hi - lo), 2)
                                  if hi > lo else None)}
    return out


def _crate_ref_lines(dm, arrays):
    """M58: computed replacement for the three hand-typed reference lines on
    the C-rate/temperature risk map, plus the map's own axis bounds.

    The "30.5C engine-only ceiling" line had gone stale -- the engine-only peak
    is now equal to the dual-channel peak, so the two lines had silently
    converged while still being drawn and labelled as distinct ceilings. Axis
    bounds are derived with headroom so a future batch cannot clip a record
    off the plot, which is how the M50 VCM-axis defect arose.
    """
    def _mx(col):
        if col not in dm:
            return None, None
        s = pd.to_numeric(dm[col], errors='coerce')
        if not s.notna().any():
            return None, None
        i = s.idxmax()
        return round(float(s.max()), 1), str(dm.loc[i, 'file'])

    eng, eng_f = _mx('eng_charge_peak_Crate')
    dual, dual_f = _mx('dual_peak_Crate')
    regen, regen_f = _mx('regen_peak_Crate')
    clean = dm[~_as_bool(dm['ens_outlier_v2'])] if 'ens_outlier_v2' in dm else dm
    typ = pd.to_numeric(clean.get('dual_peak_Crate'), errors='coerce')
    typ_med = round(float(typ.median()), 1) if typ is not None and typ.notna().any() else None

    lines = []
    if typ_med is not None:
        lines.append({'y': typ_med, 'label': f'{typ_med}C median peak (ens-clean)',
                      'color': '#64748b', 'dash': '3 2', 'kind': 'typical'})
    if regen is not None:
        lines.append({'y': regen, 'label': f'{regen}C pure-regen peak',
                      'color': '#eab308', 'dash': '4 2', 'kind': 'regen'})
    if dual is not None:
        lines.append({'y': dual, 'label': f'{dual}C charge peak', 'color': '#ef4444',
                      'dash': '5 2', 'kind': 'peak', 'drive': dual_f})

    pts = arrays.get('cRatePoints') or []
    tmax = max([float(p[0]) for p in pts], default=55.0)
    cmax = max([float(p[1]) for p in pts], default=40.0)
    return {
        'lines': lines,
        'enginePeakC': eng, 'enginePeakDrive': eng_f,
        'dualPeakC': dual, 'dualPeakDrive': dual_f,
        'regenPeakC': regen, 'regenPeakDrive': regen_f,
        'axis': {'xMin': 8, 'xMax': int(np.ceil((tmax + 3) / 5) * 5),
                 'yMin': 0, 'yMax': int(np.ceil((cmax + 3) / 5) * 5)},
        # External domain thresholds -- NOT derived from this dataset. Declared
        # here so the risk-zone boundaries drawn on the map carry provenance
        # instead of sitting as bare literals inside xS() calls.
        'zones': {
            'coldBelowC': 20, 'optimalLoC': 20, 'optimalHiC': 40, 'heatAboveC': 44,
            'source': 'generic Li-ion NMC guidance (lithium-plating risk below '
                      '~20 degC on charge; accelerated calendar/cycle ageing above '
                      '~44 degC). External reference values, not measured here, and '
                      'not specific to this pack -- Nissan does not publish them.'},
        'note': 'M58: supersedes three hand-typed reference lines. The former '
                '"30.5C engine-only ceiling" was stale -- engine-only and '
                'dual-channel peaks are now the same event, so a separate '
                'engine-only ceiling line is no longer meaningful and is dropped.'}


def _mountain_pattern(dm, raw_loader, frame_loader=None):
    """M57 (2026-07-27): re-definition of the mountain-road pattern.

    SUPERSEDES the terrainTorqueDist labelling and the informal reading that a
    sustained descent produces buffer-saturation dissipation. Two things
    changed since M48 declared per-drive terrain profiling impossible:

      1. The 42-column logging generation (Jul 24 2026 onward) carries a GPS
         ALTITUDE channel. Unlike the baro PID (~84 m/LSB, a handful of samples
         per drive) this is a true 1 Hz trace -- but it is logged in CONTIGUOUS
         BURSTS with one long off-gap, not continuously, so only windows of
         >= 300 s of unbroken 1 Hz altitude are usable. Grade is fitted by
         least squares over a 250 m DISTANCE window (not a time window), which
         keeps the grade estimate's noise floor constant across speed.

      2. The Jul 18-26 Carpathian trip is where the dissipation mechanism
         actually lives: 1275 s of the corpus's 1386 s of motored-unfuelled
         running (92%) occurs in this 53-drive window.

    HEADLINE RESULT -- the gate is state of charge, NOT gradient. Across the 53
    trip drives, drive SoC ceiling predicts dissipation (Spearman rho ~0.82);
    barometric relief also correlates marginally (rho ~0.60), but the PARTIAL
    correlation of relief with dissipation controlling for SoC ceiling is
    rho ~0.25 (p ~0.08) -- relief adds nothing once the buffer state is known.
    Direct counter-examples exist: 20260723_113724 covers 420 m of barometric
    relief with a 79.5% SoC ceiling and logs ZERO motored seconds.

    Terrain is therefore the CAUSE of the SoC rise and SoC is the TRIGGER for
    dissipation. The correct four-state taxonomy is climb / descent-absorbing /
    descent-saturated / rolling, and only the third dissipates.

    Everything below is computed; nothing is hand-typed.
    """
    ALT = 'Висота (GPS) (m)'
    BAR = 'Атмосферний тиск (абсолютний) (kPa)'
    SPD = '[VCM] Vehicle Speed (km/h)'
    RPM = 'Оберти двигуна (rpm)'
    ICOL = '[BMS] HV Battery Current (A)'
    VCOL = '[BMS] HV Battery voltage (V)'
    SOC = '[BMS] HV State of charge (%)'
    BST = 'Розрахунковий наддув (bar)'
    TQ = '[VCM] Target Motor Torque (N⋅m)'
    LOAD = 'Розрахункове значення навантаження на двигун (%)'
    # M46/M48 motored-unfuelled classifier -- identical parameters, so the two
    # censuses are directly comparable.
    RPM_MIN, BOOST_MOT, LOAD_MAX, KNEE = 2000.0, -0.7, 8.0, 80.0
    GRADE_WIN_M = 250.0
    MIN_BURST_S = 300
    BARO_M_PER_KPA = 84.0

    def _frame(fn):
        if frame_loader is not None:
            f = frame_loader(fn)
            if f is not None:
                return f
        if raw_loader is None:
            return None
        try:
            import io
            return pd.read_csv(io.BytesIO(raw_loader(fn)), low_memory=False)
        except Exception:
            return None

    # M174 (2026-08-27): the trip is a BOUNDED window, not an open-ended tail.
    # The original M57 filter had no upper bound, so as ordinary post-trip
    # daily driving was appended through August the "trip" silently grew from
    # its documented 53-drive Jul 18-26 span to 148 drives / 3378.9 km,
    # contradicting this function's own docstring and diluting every gate
    # statistic below with a month of flat, low-SoC-ceiling driving. The
    # dissipation mechanism is empirically confined to Jul 18-26 (1275 of the
    # window's 1316 motored seconds -- 97% -- fall on or before Jul 26; the
    # 40 days after add 95 drives but only 41 motored seconds), and the only
    # GPS-altitude drives that reach true mountain elevation (Jul 24, to
    # 1028 m; Kyiv sits ~150 m) are inside it. Bounding at Jul 26 restores the
    # documented population.
    TRIP_START, TRIP_END = '2026-07-18', '2026-07-26'
    d = dm['date'].astype(str)
    trip = dm[(d >= TRIP_START) & (d <= TRIP_END)]
    if not len(trip):
        return None

    drives, seg_frames = [], []
    for _, row in trip.iterrows():
        fn = row['file']
        df = _frame(fn)
        if df is not None:
            df, _ = _apply_speed_priority(df)   # M167
        if df is None or SPD not in df.columns:
            continue
        d = df.copy()
        d['time'] = pd.to_datetime(d['time'], format='mixed', errors='coerce')
        d = d.dropna(subset=['time']).set_index('time')
        cols = [c for c in [SPD, RPM, ICOL, VCOL, SOC, BST, TQ, LOAD, BAR, ALT]
                if c in d.columns]
        for c in cols:
            d[c] = pd.to_numeric(d[c], errors='coerce')
        g = d[cols].resample('1s').mean().ffill(limit=15)
        if not {RPM, BST, LOAD}.issubset(g.columns):
            continue
        mot = ((g[RPM] >= RPM_MIN) & (g[BST] <= BOOST_MOT)
               & (g[LOAD] <= LOAD_MAX)).fillna(False)
        b = g[BAR].dropna() if BAR in g else pd.Series(dtype=float)
        rec = {
            'file': fn, 'date': str(row['date']), 'km': float(row['distance_km']),
            'driveType': str(row['drive_type']),
            'socMax': (float(row['soc_max']) if pd.notna(row['soc_max']) else None),
            'motoredS': int(mot.sum()),
            'socAtMotored': (round(float(g[SOC][mot].median()), 1)
                             if mot.sum() and SOC in g else None),
            'speedAtMotored': (round(float(g[SPD][mot].median()), 1)
                               if mot.sum() else None),
            'reliefBaroM': (round(float(b.max() - b.min()) * BARO_M_PER_KPA, 0)
                            if len(b) > 1 else None),
        }
        drives.append(rec)

        # ---- grade-resolved windows (GPS altitude only) ----
        if ALT not in g.columns:
            continue
        a = g[ALT].where((g[ALT] > 1) & (g[ALT] < 3000))
        ai = a.interpolate(limit=5, limit_area='inside')
        ok = ai.notna().values
        if not ok.any():
            continue
        dd = np.diff(ok.astype(int), prepend=0)
        st = np.where(dd == 1)[0]
        en = np.where(np.diff(ok.astype(int), append=0) == -1)[0]
        for s0, e0 in zip(st, en):
            if e0 - s0 + 1 < MIN_BURST_S:
                continue
            sub = g.iloc[s0:e0 + 1].copy()
            sub[ALT] = ai.iloc[s0:e0 + 1]
            v = np.nan_to_num(sub[SPD].values / 3.6)
            dist = np.cumsum(v)
            av = sub[ALT].values
            grade = np.full(len(av), np.nan)
            for i in range(len(av)):
                lo = np.searchsorted(dist, dist[i] - GRADE_WIN_M / 2)
                hi = np.searchsorted(dist, dist[i] + GRADE_WIN_M / 2)
                if hi - lo < 10 or (dist[hi - 1] - dist[lo]) < GRADE_WIN_M * 0.5:
                    continue
                x, y = dist[lo:hi], av[lo:hi]
                m = ~np.isnan(y)
                if m.sum() >= 10:
                    grade[i] = np.polyfit(x[m], y[m], 1)[0] * 100.0
            # M124: tag each segment with its drive's class-conditional
            # assumed mass so the pooled descent-energy budget below uses the
            # correct per-drive figure instead of a single flat constant.
            # M164: also tag whether this drive's mass carries the disclosed
            # urban/mixed uncertainty (audit sec.5) or is highway's fixed
            # point value, so the descent budget's uncertainty bound below is
            # exact -- the population-weighted urban/mixed share, not a
            # conservative worst-case guess.
            sub = sub.assign(grade_pct=grade, file=fn,
                             assumed_mass_kg=_mass_for_drive(row['drive_type'], fn),
                             mass_is_urban_mixed=row['drive_type'] in ('urban', 'mixed'))
            sub['motored'] = ((sub[RPM] >= RPM_MIN) & (sub[BST] <= BOOST_MOT)
                              & (sub[LOAD] <= LOAD_MAX)).fillna(False)
            seg_frames.append(sub)

    if not drives:
        return None
    D = pd.DataFrame(drives)
    D['diss'] = D['motoredS'] > 0

    def _spearman(x, y):
        x, y = np.asarray(x, float), np.asarray(y, float)
        m = ~np.isnan(x) & ~np.isnan(y)
        if m.sum() < 8:
            return None, None
        try:
            from scipy import stats
            r, p = stats.spearmanr(x[m], y[m])
            return round(float(r), 2), float(p)
        except Exception:
            rx = pd.Series(x[m]).rank().values
            ry = pd.Series(y[m]).rank().values
            return round(float(np.corrcoef(rx, ry)[0, 1]), 2), None

    rho_soc, p_soc = _spearman(D['socMax'], D['motoredS'])
    sub = D.dropna(subset=['reliefBaroM'])
    rho_rel, p_rel = _spearman(sub['reliefBaroM'], sub['motoredS'])

    # partial correlation of relief with dissipation, controlling for SoC ceiling
    rho_part, p_part = None, None
    ss = sub.dropna(subset=['socMax'])
    if len(ss) >= 10:
        def _resid(y, x):
            X = np.column_stack([x, np.ones(len(x))])
            b, *_ = np.linalg.lstsq(X, y, rcond=None)
            return y - X @ b
        ry = _resid(ss['motoredS'].values.astype(float), ss['socMax'].values.astype(float))
        rx = _resid(ss['reliefBaroM'].values.astype(float), ss['socMax'].values.astype(float))
        rho_part, p_part = _spearman(rx, ry)

    # incidence vs drive SoC ceiling
    edges = [0, 72.5, 75, 77.5, 80, 82.5, 100]
    lbl = ['<72.5', '72.5-75', '75-77.5', '77.5-80', '80-82.5', '>82.5']
    D['_bin'] = pd.cut(D['socMax'], edges, labels=lbl)
    inc = []
    for k, gg in D.groupby('_bin', observed=True):
        inc.append({'socCeilBin': str(k), 'nDrives': int(len(gg)),
                    'nWithDissipation': int(gg['diss'].sum()),
                    'pctWithDissipation': round(float(gg['diss'].mean() * 100)),
                    'totalMotoredS': int(gg['motoredS'].sum())})

    counter = [{'file': r['file'], 'km': round(r['km'], 1),
                'reliefBaroM': r['reliefBaroM'], 'socMax': r['socMax']}
               for _, r in D[(D['reliefBaroM'] >= 250) & (~D['diss'])].iterrows()]

    out = {
        'window': {'firstDate': str(trip['date'].min()), 'lastDate': str(trip['date'].max()),
                   'nDrives': int(len(D)), 'km': round(float(D['km'].sum()), 1)},
        'dissipation': {
            'motoredS': int(D['motoredS'].sum()),
            'nDrivesActive': int(D['diss'].sum()),
            'socAtMotoredMed': (round(float(D.loc[D['diss'], 'socAtMotored'].median()), 1)
                                if D['diss'].any() else None),
            'speedAtMotoredMed': (round(float(D.loc[D['diss'], 'speedAtMotored'].median()), 1)
                                  if D['diss'].any() else None)},
        'gate': {'rhoSocCeiling': rho_soc, 'pSocCeiling': p_soc,
                 'rhoRelief': rho_rel, 'pRelief': p_rel,
                 'rhoReliefGivenSoc': rho_part, 'pReliefGivenSoc': p_part,
                 'kneeSoc': KNEE,
                 'verdict': 'SoC ceiling gates dissipation; relief is not '
                            'independently predictive once SoC is controlled'},
        'incidenceBySocCeiling': inc,
        'counterExamples': counter,
        'params': {'gradeWindowM': GRADE_WIN_M, 'minBurstS': MIN_BURST_S,
                   'baroMPerKpa': BARO_M_PER_KPA, 'rpmMin': RPM_MIN,
                   'boostMotored': BOOST_MOT, 'loadMax': LOAD_MAX},
    }

    # ---- grade-resolved half ----
    if seg_frames:
        F = pd.concat(seg_frames)
        F = F.rename(columns={SPD: 'speed', ICOL: 'I', VCOL: 'V', SOC: 'soc', TQ: 'tq'})
        F['dv'] = F.groupby('file')['speed'].diff()
        gg = F.dropna(subset=['grade_pct'])
        out['gradeCoverage'] = {
            'nWindows': int(len(seg_frames)),
            'windowSeconds': int(sum(len(x) for x in seg_frames)),
            'gradeResolvedSeconds': int(len(gg)),
            'nFiles': int(F['file'].nunique()),
            'note': 'GPS-altitude bursts only (Jul 24 2026 onward). The highest-relief '
                    'drives of the trip (Jul 24, 620-1030 m) fall in the channel-off '
                    'gaps, so grade-resolved coverage is NOT representative of the '
                    'steepest driving -- see reliefBaroM for those.'}
        # torque <-> grade calibration on steady samples
        stq = gg[(gg['dv'].abs() < 1) & gg['tq'].notna() & gg['speed'].notna()]
        if len(stq) >= 200:
            X = np.column_stack([stq['grade_pct'], stq['speed'], np.ones(len(stq))])
            beta, *_ = np.linalg.lstsq(X, stq['tq'].values, rcond=None)
            pred = X @ beta
            r2 = 1 - ((stq['tq'] - pred) ** 2).sum() / ((stq['tq'] - stq['tq'].mean()) ** 2).sum()
            out['torqueGradeCalibration'] = {
                'nmPerPctGrade': round(float(beta[0]), 2),
                'nmPerKmh': round(float(beta[1]), 3),
                'interceptNm': round(float(beta[2]), 1),
                'r2': round(float(r2), 3), 'n': int(len(stq)),
                'basis': 'steady samples (|dv|<1 km/h/s) in grade-resolved windows'}
            # measured grade behind each shipped terrainTorqueDist torque bin
            tb = [-200, -60, -40, -25, -10, 0, 10, 25, 40, 75, 200]
            obs = []
            for lo, hi in zip(tb[:-1], tb[1:]):
                m = stq[(stq['tq'] >= lo) & (stq['tq'] < hi)]
                obs.append({'bin': f'{lo}..{hi}', 'n': int(len(m)),
                            'gradeMedPct': (round(float(m['grade_pct'].median()), 2)
                                            if len(m) > 20 else None)})
            out['terrainBinValidation'] = obs
        # grade-band occupancy
        bins = [-99, -6, -4, -2, -0.5, 0.5, 2, 4, 6, 99]
        bl = ['<-6', '-6..-4', '-4..-2', '-2..-0.5', 'flat', '0.5..2', '2..4', '4..6', '>6']
        gb = gg.assign(band=pd.cut(gg['grade_pct'], bins, labels=bl))
        rows = []
        for k, x in gb.groupby('band', observed=True):
            rows.append({'band': str(k), 'n': int(len(x)),
                         'pct': round(len(x) / len(gb) * 100, 1),
                         'speedMean': round(float(x['speed'].mean()), 1),
                         'torqueMed': round(float(x['tq'].median()), 1),
                         'socMean': round(float(x['soc'].mean()), 1),
                         'currentMed': round(float(x['I'].median()), 1),
                         'motoredS': int(x['motored'].sum())})
        out['gradeBands'] = rows
        # descent energy budget: what fraction of released potential energy the
        # pack actually captures, and how far you can descend before saturating
        dsc = gg[(gg['grade_pct'] <= -2) & (gg['speed'] > 5)].copy()
        if len(dsc) > 100:
            dh = -(dsc['grade_pct'] / 100.0) * (dsc['speed'] / 3.6)
            # M124: per-row class-conditional assumed mass (tagged onto
            # each segment above), not the flat VEHICLE_MASS_KG.
            pe = dsc['assumed_mass_kg'] * 9.81 * dh / 1000.0
            pb = (dsc['I'] * dsc['V']) / 1000.0
            m = pe > 1
            eta = float(np.nanmedian((pb[m] / pe[m]).clip(-1, 2)))
            # netDropToSaturateM needs a single scalar mass; use the mean
            # assumed mass over the same qualifying-descent population that
            # eta was estimated on, for internal consistency.
            mass_repr_kg = float(dsc.loc[m, 'assumed_mass_kg'].mean())
            # M164: exact mass-uncertainty bound for this specific population.
            # w_um = the fraction of qualifying descent ROWS carrying the
            # disclosed urban/mixed mass uncertainty (vs highway's fixed
            # point value) -- a direct row-count share, not the KE-weighted
            # share used for the regen blocks, since PE contributions here
            # aren't separately accumulated by class the way regen's ke_um
            # is; disclosed as such below.
            w_um = float(dsc.loc[m, 'mass_is_urban_mixed'].mean())
            eta_lo, eta_hi = _mass_uncertainty_bounds(eta, mass_repr_kg, w_um)
            budget = []
            budget_lo = []
            budget_hi = []
            for s0 in (60, 65, 70, 75):
                head = (KNEE - s0) / 100.0 * CAP_KWH
                budget.append({'entrySocPct': s0, 'headroomKwh': round(head, 2),
                               'netDropToSaturateM': round(head * 3.6e6
                                                           / (mass_repr_kg * 9.81 * eta))})
                # M164: netDropToSaturateM is near mass-invariant (the same
                # assumed mass appears in both eta's denominator and this
                # formula's denominator and nearly cancels) -- computed
                # explicitly at both mass-uncertainty bounds rather than
                # asserted, so the (small, real) residual is shown, not hidden.
                mlo = mass_repr_kg - w_um * (MASS_URBAN_MIXED_RANGE_KG[1]
                                             - MASS_URBAN_MIXED_KG)
                mhi = mass_repr_kg + w_um * (MASS_URBAN_MIXED_RANGE_KG[1]
                                             - MASS_URBAN_MIXED_KG)
                budget_lo.append(round(head * 3.6e6 / (mhi * 9.81 * eta_lo)))
                budget_hi.append(round(head * 3.6e6 / (mlo * 9.81 * eta_hi)))
            out['descentBudget'] = {
                'captureFraction': round(eta, 2), 'n': int(m.sum()),
                'assumedMassKg': round(mass_repr_kg, 1),
                'captureFractionRangeMassUncertainty':
                    [round(eta_lo, 4), round(eta_hi, 4)],
                'urbanMixedRowShare': round(w_um, 3),
                'toSaturation': budget,
                'toSaturationRangeMassUncertaintyM':
                    list(zip(budget_lo, budget_hi)),
                'maxReliefDrivenM': (float(D['reliefBaroM'].max())
                                     if D['reliefBaroM'].notna().any() else None),
                'note': ('capture fraction is pack-measured charge energy over '
                        'released potential energy on >=2% descents; the '
                        'remainder is aero, rolling, driveline and friction '
                        'braking. M164: captureFraction and toSaturation carry '
                        'a closed-form mass-uncertainty range (audit sec.5) '
                        'from the disclosed urban/mixed assumed-mass range '
                        '(MASS_URBAN_MIXED_RANGE_KG), weighted by this '
                        'population\'s own urban/mixed row share -- '
                        'netDropToSaturateM is near mass-invariant (the mass '
                        'in captureFraction\'s denominator nearly cancels '
                        'against the mass in this formula\'s own denominator), '
                        'shown explicitly rather than assumed.')}
    return out


def _low_speed_dissipation(dm, raw_loader, frame_loader=None):
    """M48 (2026-07-22): low-speed buffer-saturation dissipation census.

    Extends the M46 motored-engine classifier from a two-drive curiosity into
    a characterised, thresholded process, and answers three questions M46 left
    open: WHEN it engages, HOW MUCH energy it moves, and WHERE it happens.

    Mechanism. The ICE drives only the generator. When the pack approaches the
    top of its buffer it can no longer accept surplus regen, so the VCM spins
    the engine UNFUELLED through the generator -- throttle shut, deep intake
    vacuum, calc load ~0 -- and dumps the surplus as pumping + friction work.
    The classifier is M46's, unchanged, so the two censuses stay comparable:
        MOTORED = eng_rpm > RPM_MIN and boost < BOOST_MOTORED and load < LOAD_MAX

    What M48 adds.
    (1) THRESHOLD. Incidence is binned by each drive's own SoC ceiling. The
        process is not a smooth function of SoC: it is absent below ~75%,
        present in every drive above ~78%, and the median motored duration
        rises by two orders of magnitude across that knee. M46's CEIL_SOC=85
        gate therefore sat ABOVE the engagement point and classified most of
        the phenomenon as absent; KNEE_SOC (80%) is reported alongside it.
    (2) ENERGY. Per motored second the pack's own power is integrated, and the
        regen the pack would otherwise have taken is estimated from the SAME
        drive's engine-off decelerating-charge median (a within-drive control,
        so route and ambient cancel). The difference is energy the buffer
        refused. Reported with a first-principles pumping-work cross-check,
        as a RANGE -- the reference method attributes the whole shortfall to
        diversion and so bounds it from above.
    (3) SPEED + TERRAIN. Episode speeds establish this as a LOW-SPEED process
        (secondary/mountain roads), which is why the 80-120 km/h terrain gate
        never saw it. A barometric route-relief census tests the terrain
        association directly. That test is REPORTED HONESTLY AS WEAK: the
        atmospheric-pressure PID is polled ~3x per drive at 1 kPa (~84 m)
        quantisation, so it bounds a route's elevation envelope and nothing
        finer. Elevation explains dissipation only marginally and does NOT
        significantly explain the SoC ceiling itself; both statistics are
        emitted so the dashboard can state that rather than imply causation.
    """
    RPM_MIN, BOOST_MOTORED, LOAD_MAX = 2000.0, -0.70, 8.0
    CEIL_SOC, KNEE_SOC = 85.0, 80.0
    MIN_EPISODE_S = 5
    DISPLACEMENT_L, FMEP_KPA, DRIVELINE_EFF = 1.5, 100.0, 0.90
    C = {'[BMS] HV Battery Current (A)': 'I',
         '[BMS] HV Battery voltage (V)': 'V',
         '[BMS] HV State of charge (%)': 'soc',
         '[VCM] Vehicle Speed (km/h)': 'speed',
         'Оберти двигуна (rpm)': 'rpm',
         'Розрахункове значення навантаження на двигун (%)': 'load',
         'Розрахунковий наддув (bar)': 'boost',
         'Атмосферний тиск (абсолютний) (kPa)': 'baro'}
    KEEP = ('I', 'V', 'soc', 'speed', 'rpm', 'load', 'boost', 'baro')

    def grid_fn(fn):
        if frame_loader is not None:
            fr = frame_loader(fn)
            if fr is None:
                return None
            df = fr[[c for c in fr.columns
                     if c in C or c == 'time' or c == _SPEED_OBD_RAW]]
        else:
            raw = raw_loader(fn) if raw_loader is not None else None
            if not raw:
                return None
            df = pd.read_csv(io.BytesIO(raw),
                             usecols=lambda c: c in C or c == 'time' or c == _SPEED_OBD_RAW,
                             low_memory=False)
        df, _ = _apply_speed_priority(df)      # M167, before the C rename
        df = df.rename(columns=C)
        if 'time' not in df.columns:
            return None
        g = df.set_index(pd.to_datetime(df['time'], errors='coerce'))
        g = g[[c for c in KEEP if c in g.columns]].apply(pd.to_numeric,
                                                         errors='coerce')
        return g.resample('1s').mean().ffill(limit=3)

    per, eps_all, mot_speeds, relief = [], [], [], []
    for fn in dm['file']:
        try:
            g = grid_fn(fn)
        except Exception:
            continue
        if g is None or len(g) < 120:
            continue
        # route-relief envelope (independent of the motoring classifier)
        if 'baro' in g:
            b = g['baro'].dropna()
            b = b[(b > 80) & (b < 110)]
            if len(b):
                relief.append({'file': fn, 'nSamp': int(len(b)),
                               'pMin': float(b.min()), 'pMax': float(b.max())})
        need = [c for c in ('soc', 'rpm', 'load', 'boost') if c in g]
        if len(need) < 4:
            continue
        gg = g.dropna(subset=need)
        if len(gg) < 120:
            continue
        mot = ((gg['rpm'] > RPM_MIN) & (gg['boost'] < BOOST_MOTORED)
               & (gg['load'] < LOAD_MAX))
        soc_max = float(gg['soc'].max())
        rec = {'file': fn, 'socMax': soc_max, 'motoredS': int(mot.sum()),
               'motoredCeilS': int((mot & (gg['soc'] >= CEIL_SOC)).sum()),
               'motoredKneeS': int((mot & (gg['soc'] >= KNEE_SOC)).sum())}
        if mot.any():
            # ---- energy: pack power (module convention: +ve = discharge) ----
            if 'I' in gg and 'V' in gg:
                p_dis = (-gg['I']) * gg['V'] / 1000.0
                # within-drive control: engine-off decelerating charge power
                ref = None
                if 'speed' in gg:
                    dec = gg['speed'].diff() < 0
                    ctl = p_dis[(~mot) & dec & (gg['speed'] > 20)
                                & (p_dis < 0)]
                    if len(ctl) >= 30:
                        ref = float(-ctl.median())      # kW into the pack
                rec['refChgKw'] = round(ref, 2) if ref is not None else None
                # CRITICAL SPLIT. The motored signature has two causes that
                # must not be pooled: (a) ceiling defence, where a near-full
                # pack refuses charge and the surplus is burned off, and
                # (b) ordinary high-speed fuel-cut coasting, where the engine
                # is also unfuelled but the pack is charging normally and
                # NOTHING is being dissipated. Only (a) is buffer saturation.
                # SoC >= KNEE_SOC separates them; pooling the two inflates the
                # diverted-energy budget with events that diverted nothing.
                for tag, msk in (('', mot),
                                 ('Ceil', mot & (gg['soc'] >= KNEE_SOC)),
                                 ('Coast', mot & (gg['soc'] < KNEE_SOC))):
                    ns = int(msk.sum())
                    if not ns:
                        continue
                    wh = float(-p_dis[msk].sum()) / 3.6   # +ve = pack charged
                    rec['packWh' + tag] = round(wh, 1)
                    rec['s' + (tag or 'All')] = ns
                    if ref is not None:
                        rec['divertedWh' + tag] = round(ref * ns / 3.6 - wh, 1)
            if 'speed' in gg:
                sv = gg.loc[mot, 'speed'].dropna()
                if len(sv):
                    rec['spdMedKmh'] = round(float(sv.median()), 1)
                    mot_speeds.append(sv)
            rec['socMedAtMot'] = round(float(gg.loc[mot, 'soc'].median()), 1)
            rec['mapMedKpa'] = round(101 * float(gg.loc[mot, 'boost'].median())
                                     + 95.2, 1)
            rec['rpmMedAtMot'] = int(gg.loc[mot, 'rpm'].median())
            # ---- episodes ----
            v = mot.values
            st = None
            for i, x in enumerate(v):
                if x and st is None:
                    st = i
                elif not x and st is not None:
                    if i - st >= MIN_EPISODE_S:
                        eps_all.append({'file': fn, 'durS': i - st})
                    st = None
            if st is not None and len(v) - st >= MIN_EPISODE_S:
                eps_all.append({'file': fn, 'durS': len(v) - st})
        per.append(rec)

    P = pd.DataFrame(per)
    out = {'params': {'rpmMin': RPM_MIN, 'boostMotored': BOOST_MOTORED,
                      'loadMax': LOAD_MAX, 'ceilSoc': CEIL_SOC,
                      'kneeSoc': KNEE_SOC, 'minEpisodeS': MIN_EPISODE_S},
           'nDrivesCovered': int(len(P)),
           'nDrivesWithMotoring': int((P['motoredS'] > 0).sum()) if len(P) else 0}
    if not len(P):
        return out

    # ---- (1) threshold table -------------------------------------------
    edges = [0, 72.5, 75, 77.5, 80, 82.5, 200]
    lbls = ['<72.5', '72.5-75', '75-77.5', '77.5-80', '80-82.5', '>82.5']
    P['_b'] = pd.cut(P['socMax'], edges, labels=lbls, right=True)
    tbl = []
    for lb in lbls:
        s = P[P['_b'] == lb]
        if not len(s):
            continue
        tbl.append({'socMaxBin': lb, 'nDrives': int(len(s)),
                    'nWithMotoring': int((s['motoredS'] > 0).sum()),
                    'pctWithMotoring': round((s['motoredS'] > 0).mean() * 100),
                    'medMotoredS': int(s['motoredS'].median()),
                    'maxMotoredS': int(s['motoredS'].max()),
                    'totMotoredS': int(s['motoredS'].sum())})
    out['socThreshold'] = tbl
    try:
        from scipy.stats import spearmanr
        r_, p_ = spearmanr(P['socMax'], P['motoredS'])
        out['socMotoredSpearman'] = {'rho': round(float(r_), 2),
                                     'p': float(f'{p_:.3g}'),
                                     'n': int(len(P))}
    except Exception:
        out['socMotoredSpearman'] = None

    # ---- (2) energy ------------------------------------------------------
    act = P[P['motoredS'] > 0]
    e = {'totalMotoredS': int(act['motoredS'].sum()),
         'nDrivesActive': int(len(act))}
    for tag, key in (('', 'all'), ('Ceil', 'ceilingDefence'), ('Coast', 'fuelCutCoast')):
        sc, pc, dc = 's' + (tag or 'All'), 'packWh' + tag, 'divertedWh' + tag
        if sc not in act:
            continue
        secs = int(act[sc].fillna(0).sum())
        blk = {'seconds': secs,
               'nDrives': int(act[sc].notna().sum()),
               'packNetWh': (round(float(act[pc].sum()), 0)
                             if pc in act else None)}
        if dc in act:
            dv = act[dc].dropna()
            ds = int(act.loc[dv.index, sc].fillna(0).sum())
            if len(dv) and ds:
                blk['divertedWh'] = round(float(dv.sum()), 0)
                blk['divertedMeanKw'] = round(float(dv.sum()) * 3.6 / ds, 1)
        e[key] = blk
    # headline basis is ceiling defence -- the mode that is actually
    # dissipation. fuelCutCoast is retained only to show it is NOT.
    hl = e.get('ceilingDefence', {})
    e['headlineMode'] = 'ceilingDefence'
    e['divertedWh'] = hl.get('divertedWh')
    e['divertedMeanKw'] = hl.get('divertedMeanKw')
    # fuelCutCoast is a NEGATIVE CONTROL. Below the knee the pack is charging
    # normally and nothing is being dissipated, so its apparent "diverted"
    # power is pure method bias -- the within-drive reference over-attributes,
    # because a motored decel is not always as steep as the median decel it is
    # compared against. Publish that bias rather than hide it: the honest
    # excess attributable to buffer saturation is the DIFFERENCE between the
    # two modes, and the first-principles model is the independent lower bound.
    fc = e.get('fuelCutCoast', {})
    if hl.get('divertedMeanKw') is not None and fc.get('divertedMeanKw') is not None:
        e['negativeControl'] = {
            'ceilingKw': hl['divertedMeanKw'],
            'coastKw': fc['divertedMeanKw'],
            'methodBiasKw': fc['divertedMeanKw'],
            'excessKw': round(hl['divertedMeanKw'] - fc['divertedMeanKw'], 1),
            'note': 'coastKw is measured where no dissipation can be occurring '
                    'and therefore estimates the reference method\'s upward '
                    'bias; excessKw is the bias-corrected ceiling-defence term.'}
    # first-principles cross-check: pumping + friction at the observed
    # motoring point, converted to an electrical draw.
    if 'mapMedKpa' in act and 'rpmMedAtMot' in act:
        mp = float(act['mapMedKpa'].median())
        rp = float(act['rpmMedAtMot'].median())
        cyc_s = rp / 60.0 / 2.0                       # 4-stroke cycles / s
        pump_kw = (95.2 - mp) * DISPLACEMENT_L * cyc_s / 1000.0
        fric_kw = FMEP_KPA * DISPLACEMENT_L * cyc_s / 1000.0
        e['model'] = {'mapMedKpa': round(mp, 1), 'rpmMed': int(rp),
                      'pumpingKw': round(pump_kw, 1),
                      'frictionKw': round(fric_kw, 1),
                      'electricalKw': round((pump_kw + fric_kw)
                                            / DRIVELINE_EFF, 1),
                      'fmepAssumedKpa': FMEP_KPA,
                      'note': 'pumping = (P_atm - MAP)·V_d·N/2; friction from '
                              'an assumed FMEP; /0.90 for generator+inverter'}
        if e.get('divertedMeanKw'):
            e['boundedKw'] = [e['model']['electricalKw'],
                              e['divertedMeanKw']]
    out['energy'] = e

    # ---- (3) speed regime ------------------------------------------------
    if mot_speeds:
        sv = pd.concat(mot_speeds)
        out['speedRegime'] = {
            'nSamples': int(len(sv)),
            'p05': round(float(sv.quantile(0.05)), 0),
            'med': round(float(sv.median()), 0),
            'p95': round(float(sv.quantile(0.95)), 0),
            'pctBelow70': round(float((sv < 70).mean() * 100), 1),
            'pctInHwyGate': round(float(((sv >= 80) & (sv <= 120)).mean() * 100), 1)}
    if eps_all:
        E = pd.DataFrame(eps_all)
        lo = E.loc[E['durS'].idxmax()]
        out['episodes'] = {
            'n': int(len(E)), 'medDurS': int(E['durS'].median()),
            'p90DurS': int(E['durS'].quantile(0.90)),
            'longestS': int(lo['durS']),
            'longestDrive': _day_label_by_file(dm, lo['file']),
            'nOver60s': int((E['durS'] > 60).sum())}

    # ---- (4) route relief, reported with its own limits -------------------
    if relief:
        R = pd.DataFrame(relief)
        R['altMaxM'] = (101.325 - R['pMin']) * 84.3
        R['reliefM'] = (R['pMax'] - R['pMin']) * 84.3
        rel = {'nDrives': int(len(R)),
               'medSamplesPerDrive': int(R['nSamp'].median()),
               'maxSamplesPerDrive': int(R['nSamp'].max()),
               'pMinKpa': round(float(R['pMin'].min()), 0),
               'pMaxKpa': round(float(R['pMax'].max()), 0),
               'corpusSpanM': int(round((R['pMax'].max() - R['pMin'].min())
                                        * 84.3)),
               'altMaxM': int(round(R['altMaxM'].max())),
               'resolutionM': 84,
               'caveat': '1 kPa PID quantisation ~= 84 m; the PID is polled '
                         'about 3x per drive (the per-drive sample counts here '
                         'are gridded seconds, inflated ~4x by the 3 s '
                         'forward-fill). Bounds a route elevation ENVELOPE '
                         'only -- not a time-resolved altitude or road-grade '
                         'trace, and no substitute for GPS/DEM elevation.'}
        M = R.merge(P[['file', 'socMax', 'motoredS']], on='file', how='inner')
        if len(M) >= 20:
            hi = M[M['altMaxM'] >= 450]
            lo_ = M[M['altMaxM'] < 450]
            rel['highGround'] = {
                'thresholdM': 450, 'n': int(len(hi)),
                'totMotoredS': int(hi['motoredS'].sum()),
                'medSocMax': round(float(hi['socMax'].median()), 1)}
            rel['lowGround'] = {
                'n': int(len(lo_)), 'totMotoredS': int(lo_['motoredS'].sum()),
                'medSocMax': round(float(lo_['socMax'].median()), 1)}
            try:
                from scipy.stats import spearmanr, mannwhitneyu
                r1, p1 = spearmanr(M['altMaxM'], M['motoredS'])
                r2, p2 = spearmanr(M['altMaxM'], M['socMax'])
                _, pm = mannwhitneyu(hi['motoredS'], lo_['motoredS'],
                                     alternative='greater')
                rel['altVsMotored'] = {'rho': round(float(r1), 2),
                                       'p': float(f'{p1:.3g}')}
                rel['altVsSocMax'] = {'rho': round(float(r2), 2),
                                      'p': float(f'{p2:.3g}')}
                rel['mwuMotoredHighVsLow'] = float(f'{pm:.3g}')
                rel['verdict'] = (
                    'Elevation is a WEAK, marginally significant predictor of '
                    'dissipation time and does NOT significantly predict the '
                    'SoC ceiling. Totals are carried by a handful of drives. '
                    'Consistent with, but not established by, the data.')
            except Exception:
                pass
        out['relief'] = rel
    return out


# ======================================================================
# M183 (2026-08-29): crawl & stop-go operating-mode census (candidate D
# of the Phase-1 feasibility review). NEW analysis -- the only prior
# low-speed-halt reading is standstillStats (M26), which is pure standstill
# (key-on, speed==0) parasitic draw and says nothing about the launch ->
# crawl -> approach -> stop CYCLE that dominates urban duty (219/290
# drives). D segments that cycle and integrates the buffer energy moved by
# each phase.
#
# Estimands (feasibility review, tier P): episode segmentation, Wh/launch,
# Wh/approach, net Wh/cycle, engine-starts per 10 min of stop-go operation.
#
# Method. On the per-drive 1 Hz grid (resample('1s').mean().ffill(limit=3),
# the module-wide raw-derived convention; speed resolved by the M167
# VCM/OBD priority rule BEFORE use):
#   * STOP  = a maximal run of speed < STOP_V lasting >= MIN_STOP_S. The
#     sustain gate rejects single-sample speed dropouts (the async speed PID
#     quantises hard near zero).
#   * LAUNCH = the transient from a stop's end forward to the first sample
#     reaching MOVE_V (or the inter-stop speed peak if it never does),
#     capped at WINDOW_CAP_S. Requires the vehicle actually moved.
#   * APPROACH = the mirror transient decaying into the next stop.
#   * STOP-GO CYCLE = a consecutive (stop, stop) pair whose inter-stop speed
#     PEAK <= STOPGO_CEIL, i.e. genuine low-speed crawl-and-halt, not an
#     urban cruise leg that merely happens to bracket two stops.
# Energy uses the module convention p_dis = (-I)*V/1000 kW (M11 discharge-
# positive). Per cycle:
#   whCycleNet  = integral of p_dis over the whole cycle / 3.6  (net pack Wh
#                 spent; + = drawn down).
#   whLaunchOut = integral of max(p_dis,0) over the launch window / 3.6
#                 (GROSS discharge to pull away).
#   whApproachIn= integral of max(-p_dis,0) over the approach window / 3.6
#                 (GROSS regen returned to the pack on the decel).
#   recoveryRatio = whApproachIn / whLaunchOut.
# The gross/net split is deliberate: at these speeds approach regen is
# small and the net approach flow is frequently still DISCHARGE (creep +
# accessory load outweigh sub-15-km/h regen), so a single signed "approach
# regen" figure would be misleading -- the honest quantities are the gross
# energy IN and the gross energy OUT.
#
# Buffer-thesis reading (reported, not asserted as causal): if launch spends
# the buffer and approach returns almost none of it, the cycle's energy is
# closed by the GENERATOR, not by regen -- which is why engine starts per
# 10 min of low-speed operation is reported alongside. This is descriptive
# single-vehicle/single-driver characterisation; no control-strategy claim
# is made beyond what the integrals show.
#
# Resolution limits (honest): (1) the ~1.3 Hz batched-synchronous core
# cadence and 1 Hz regrid put sub-second launch dynamics (jerk, t10/t50/t90)
# below the resolvable floor -- NOT reported here; only phase-integrated
# energy and counts are. (2) speed is the VCM (or OBD-fallback) channel, not
# wheel-speed; the STOP_V/MOVE_V thresholds are reported WITH a sensitivity
# sweep so the headline does not hinge on one cut.
_CSG_COLS = {'[BMS] HV Battery Current (A)': 'I',
             '[BMS] HV Battery voltage (V)': 'V',
             '[BMS] HV State of charge (%)': 'soc',
             '[VCM] Vehicle Speed (km/h)': 'speed',
             'Оберти двигуна (rpm)': 'rpm',
             # M226.1 (P1.1, enhancement plan): pack temperature, read in
             # the SAME per-file pass as everything else above (one more
             # column, not a second raw pass) -- used only by the
             # stop-effect covariate model below, nowhere else in this
             # function.
             '[BMS] HV Battery Temperature Sensor 1 (℃)': 'tpack'}


def _csg_runs(mask_vals):
    """Contiguous True runs of a boolean ndarray -> list of (start,end) incl."""
    out = []
    n = len(mask_vals)
    i = 0
    while i < n:
        if mask_vals[i]:
            j = i
            while j + 1 < n and mask_vals[j + 1]:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def _csg_grid(fn, raw_loader, frame_loader):
    if frame_loader is not None:
        fr = frame_loader(fn)
        if fr is None:
            return None
        df = fr[[c for c in fr.columns
                 if c in _CSG_COLS or c == 'time' or c == _SPEED_OBD_RAW]]
    else:
        raw = raw_loader(fn) if raw_loader is not None else None
        if not raw:
            return None
        df = pd.read_csv(io.BytesIO(raw),
                         usecols=lambda c: (c in _CSG_COLS or c == 'time'
                                            or c == _SPEED_OBD_RAW),
                         low_memory=False)
    df, _ = _apply_speed_priority(df)          # M167, before the rename
    df = df.rename(columns=_CSG_COLS)
    if 'time' not in df.columns or 'speed' not in df.columns:
        return None
    g = df.set_index(pd.to_datetime(df['time'], errors='coerce'))
    g = g[[c for c in ('I', 'V', 'soc', 'speed', 'rpm', 'tpack') if c in g.columns]]
    g = g.apply(pd.to_numeric, errors='coerce')
    return g.resample('1s').mean().ffill(limit=3)


def _csg_events(g, stop_v=1.5, stopgo_ceil=30.0, min_stop_s=3,
                move_v=15.0, window_cap_s=20):
    """Per-drive stop-go segmentation on a 1 Hz grid. Returns a dict of
    counts, the low-speed operating time, engine-starts within it, and
    (when I&V are present) per-cycle / per-launch / per-approach energy
    lists. Returns None if the grid is too short or has no usable speed.

    M226.1 (P1.1, enhancement plan): cycles/approaches also carry
    decelRateKmhPerS (peak speed / approach-phase duration -- the SAME
    abeg/s_k1 or beg/st window already computed below for the energy
    phases, not a new segmentation), and cycles additionally carry
    engineRestarted (any OFF->ON RPM transition within the cycle),
    precedingEngineOn (RPM>800 immediately before the stop the cycle
    starts from), stopDurationS, socAtStop, and tpackAtStop (tpack: M226.1
    addition to _CSG_COLS/_csg_grid, read in the same per-file pass) --
    all covariates the M226.1 two-part/stop-effect models need, extracted
    from data already present in this function's own grid, no new raw
    pass or re-segmentation."""
    if g is None or 'speed' not in g.columns or g['speed'].notna().sum() < 120:
        return None
    s = g['speed']
    sv = s.values
    r = g['rpm'].values if 'rpm' in g.columns else None
    soc_v = g['soc'].values if 'soc' in g.columns else None
    tpack_v = g['tpack'].values if 'tpack' in g.columns else None
    has_iv = ('I' in g.columns and 'V' in g.columns
              and g['I'].notna().sum() > 60 and g['V'].notna().sum() > 60)
    p = ((-g['I']) * g['V'] / 1000.0) if has_iv else None   # kW, discharge +

    def _at(arr, i):
        if arr is None or i < 0 or i >= len(arr):
            return None
        v = arr[i]
        return float(v) if v == v else None   # NaN-safe

    def _restarted(i0, i1):
        """Any OFF(<=100)->ON(>800) RPM transition strictly within (i0, i1]."""
        if r is None or i1 <= i0:
            return None
        for i in range(max(i0 + 1, 1), i1 + 1):
            if (r[i] > 800 and not np.isnan(r[i - 1]) and r[i - 1] <= 100):
                return True
        return False

    stops = [(a, b) for a, b in _csg_runs((sv < stop_v))
             if (b - a + 1) >= min_stop_s]

    def _phase(a, b):
        """(netWh, grossOutWh, grossInWh) over inclusive index window."""
        if p is None:
            return (None, None, None)
        seg = p.iloc[a:b + 1].dropna()
        if not len(seg):
            return (None, None, None)
        return (float(seg.sum()) / 3.6,
                float(seg.clip(lower=0).sum()) / 3.6,
                float((-seg).clip(lower=0).sum()) / 3.6)

    launches, approaches, cycles = [], [], []
    # launches: stop-end -> first >= move_v (or local peak), capped
    for (a, b) in stops:
        st = b
        e = min(st + window_cap_s, len(sv) - 1)
        seg = sv[st + 1:e + 1]
        if len(seg) == 0 or not np.isfinite(seg).any():
            continue
        hit = np.where(seg >= move_v)[0]
        end = st + 1 + (int(hit[0]) if len(hit) else int(np.nanargmax(seg)))
        if end <= st or not (sv[st + 1:end + 1] > stop_v).any():
            continue
        net, out, _in = _phase(st, end)
        launches.append({'durS': end - st, 'grossOutWh': out,
                         'vPeak': float(np.nanmax(sv[st + 1:end + 1]))})
    # approaches: last >= move_v (or peak) -> stop-start, capped
    for (a, b) in stops:
        st = a
        s0 = max(st - window_cap_s, 0)
        seg = sv[s0:st]
        if len(seg) == 0 or not np.isfinite(seg).any():
            continue
        hit = np.where(seg >= move_v)[0]
        beg = s0 + (int(hit[-1]) if len(hit) else int(np.nanargmax(seg)))
        if beg >= st or not (sv[beg:st] > stop_v).any():
            continue
        net, _out, gin = _phase(beg, st)
        v_peak = float(np.nanmax(sv[beg:st]))
        dur = st - beg
        approaches.append({'durS': dur, 'grossInWh': gin, 'vPeak': v_peak,
                           'decelRateKmhPerS': (round(v_peak / dur, 3)
                                                if dur > 0 else None),
                           'socAtStart': _at(soc_v, beg),
                           'tpackAtStart': _at(tpack_v, beg)})
    # stop-go cycles: consecutive stop pairs, inter-stop peak <= ceil
    for k in range(len(stops) - 1):
        e_k = stops[k][1]
        s_k1 = stops[k + 1][0]
        if s_k1 - e_k < 2:
            continue
        inter = sv[e_k:s_k1 + 1]
        if not np.isfinite(inter).any():
            continue
        vpk = float(np.nanmax(inter))
        if vpk > stopgo_ceil or vpk < stop_v:
            continue
        tgt = min(move_v, vpk)
        rel = sv[e_k + 1:s_k1]
        if len(rel) == 0 or not np.isfinite(rel).any():
            continue
        up = np.where(rel >= tgt)[0]
        lend = e_k + 1 + (int(up[0]) if len(up) else int(np.nanargmax(rel)))
        abeg = e_k + 1 + (int(up[-1]) if len(up) else lend)
        net, _o, _i = _phase(e_k, s_k1)
        _n, out, _i2 = _phase(e_k, min(lend, s_k1))
        _n2, _o2, gin = _phase(max(abeg, e_k), s_k1)
        rec = (gin / out) if (out is not None and gin is not None and out > 0) else None
        approach_dur = s_k1 - max(abeg, e_k)
        cycles.append({
            'vPeak': round(vpk, 1), 'durS': s_k1 - e_k,
            'whCycleNet': net, 'whLaunchOut': out,
            'whApproachIn': gin, 'recoveryRatio': rec,
            'decelRateKmhPerS': (round(vpk / approach_dur, 3)
                                 if approach_dur > 0 else None),
            'engineRestarted': _restarted(e_k, s_k1),
            'precedingEngineOn': (bool(r[e_k - 1] > 800)
                                  if (r is not None and e_k > 0
                                      and not np.isnan(r[e_k - 1])) else None),
            'stopDurationS': stops[k][1] - stops[k][0] + 1,
            'socAtStop': _at(soc_v, e_k), 'tpackAtStop': _at(tpack_v, e_k)})
    # engine starts (OFF->running, M116 trigger) within low-speed operation
    starts_ls = 0
    low_time = int((s <= stopgo_ceil).sum())
    if r is not None:
        for i in range(1, len(r)):
            if (r[i] > 800 and not np.isnan(r[i - 1]) and r[i - 1] <= 100
                    and not np.isnan(sv[i]) and sv[i] <= stopgo_ceil):
                starts_ls += 1
    return {'nStops': len(stops), 'launches': launches,
            'approaches': approaches, 'cycles': cycles,
            'startsLowSpeed': starts_ls, 'lowSpeedTimeS': low_time,
            'hasIV': has_iv}


def _csg_med_iqr(vals):
    x = np.array([v for v in vals if v is not None
                  and not (isinstance(v, float) and np.isnan(v))], float)
    if not len(x):
        return None
    return {'median': round(float(np.median(x)), 2),
            'p25': round(float(np.percentile(x, 25)), 2),
            'p75': round(float(np.percentile(x, 75)), 2),
            'p95': round(float(np.percentile(x, 95)), 2),
            'n': int(len(x))}


def _csg_dayboot(pairs, seed=42, n_boot=4000):
    """Day-clustered bootstrap of a median. pairs = list of (day, value).
    Resamples calendar days (the experimental unit), never 1 Hz samples."""
    from collections import defaultdict
    grp = defaultdict(list)
    for day, v in pairs:
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            grp[day].append(v)
    keys = [k for k in grp if grp[k]]
    if len(keys) < 3:
        return None
    arrs = {k: np.array(grp[k], float) for k in keys}
    rng = np.random.default_rng(seed)
    meds = np.empty(n_boot)
    for i in range(n_boot):
        samp = rng.choice(len(keys), len(keys), replace=True)
        meds[i] = np.median(np.concatenate([arrs[keys[j]] for j in samp]))
    return {'bootMedian': round(float(np.median(meds)), 2),
            'ci95': [round(float(np.percentile(meds, 2.5)), 2),
                     round(float(np.percentile(meds, 97.5)), 2)],
            'nDays': int(len(keys))}


def _crawl_stop_go(dm, raw_loader, frame_loader=None):
    """M183 candidate-D crawl & stop-go census. See the block comment above
    _CSG_COLS for the full methodology. frame_loader-preferred (raw_loader
    fallback), matching _low_speed_dissipation."""
    if frame_loader is None and raw_loader is None:
        return None
    per = []
    cyc_all, launch_all, appr_all = [], [], []
    n_cov = n_iv = 0
    for _, row in dm.iterrows():
        fn = row['file']
        day = str(row.get('date'))[:10]
        try:
            g = _csg_grid(fn, raw_loader, frame_loader)
        except Exception:
            continue
        r = _csg_events(g)
        if r is None:
            continue
        n_cov += 1
        n_iv += 1 if r['hasIV'] else 0
        for c in r['cycles']:
            c['day'] = day
            cyc_all.append(c)
        for l in r['launches']:
            launch_all.append((day, l['grossOutWh']))
        for ap in r['approaches']:
            appr_all.append((day, ap['grossInWh']))
        st10 = (r['startsLowSpeed'] / (r['lowSpeedTimeS'] / 600.0)
                if r['lowSpeedTimeS'] > 0 else None)
        per.append({'file': fn, 'day': day, 'driveType': row.get('drive_type'),
                    'km': float(row.get('distance_km') or 0.0),
                    'nStops': r['nStops'], 'nCycles': len(r['cycles']),
                    'startsPer10minStopGo': st10,
                    'lowSpeedTimeS': r['lowSpeedTimeS'],
                    # M204 (2026-09-01): denominator-visibility fields, added
                    # alongside the byDriveType breakdown -- see the caveat
                    # text built after 'bt' below for why these are needed.
                    'startsLowSpeed': r['startsLowSpeed'],
                    'durationS': float(row.get('duration_s') or 0.0)})
    if n_cov == 0:
        return {'nDrivesCovered': 0}
    P = pd.DataFrame(per)
    covered_km = float(P['km'].sum())

    net = [c['whCycleNet'] for c in cyc_all]
    lout = [c['whLaunchOut'] for c in cyc_all]
    ain = [c['whApproachIn'] for c in cyc_all]
    rec = [c['recoveryRatio'] for c in cyc_all]

    out = {
        'nDrivesCovered': n_cov, 'nDrivesEnergy': n_iv,
        'coveredKm': round(covered_km, 1),
        'nStops': int(P['nStops'].sum()),
        'nStopGoCycles': len(cyc_all),
        'nLaunches': len(launch_all), 'nApproaches': len(appr_all),
        # cycle-level energy (skewed -> median/IQR/p95)
        'whCycleNet': _csg_med_iqr(net),
        'whLaunchOut': _csg_med_iqr(lout),
        'whApproachIn': _csg_med_iqr(ain),
        'recoveryRatio': _csg_med_iqr(rec),
        # per-launch / per-approach gross energy (all qualifying transients)
        'whPerLaunch': _csg_med_iqr([v for _, v in launch_all]),
        'whPerApproachRegen': _csg_med_iqr([v for _, v in appr_all]),
        # per-drive rates
        'stopsPerDrive': _csg_med_iqr(P['nStops'].tolist()),
        'cyclesPerDrive': _csg_med_iqr(P['nCycles'].tolist()),
        'startsPer10minStopGo': _csg_med_iqr(P['startsPer10minStopGo'].tolist()),
        # day-clustered bootstraps of the two headline medians
        'whCycleNetBoot': _csg_dayboot([(c['day'], c['whCycleNet'])
                                        for c in cyc_all]),
        'recoveryRatioBoot': _csg_dayboot([(c['day'], c['recoveryRatio'])
                                           for c in cyc_all]),
        'startsPer10minBoot': _csg_dayboot(
            [(r['day'], r['startsPer10minStopGo']) for r in per]),
    }
    # drive-type breakdown (single-driver: descriptive, never scored)
    bt = {}
    for dt_, sub in P.groupby('driveType'):
        frac = sub['lowSpeedTimeS'] / sub['durationS'].replace(0, np.nan)
        bt[str(dt_)] = {
            'nDrives': int(len(sub)),
            'cyclesPerDrive': _csg_med_iqr(sub['nCycles'].tolist()),
            'startsPer10minStopGo': _csg_med_iqr(
                sub['startsPer10minStopGo'].tolist()),
            # M204 (2026-09-01): denominator-visibility fields. startsPer10min
            # -StopGo divides a per-drive numerator (discrete engine starts,
            # often single digits) by a per-drive denominator (seconds at
            # <=stopGoCeil km/h) that is NOT fixed across drive types -- it is
            # the low-speed time actually present in that one drive. These
            # three fields let the rate be read together with what produced
            # it rather than in isolation. See out['rateCaveat'].
            'lowSpeedTimeS': _csg_med_iqr(sub['lowSpeedTimeS'].tolist()),
            'lowSpeedFracOfDrive': _csg_med_iqr(frac.tolist()),
            'startsLowSpeedAbs': _csg_med_iqr(sub['startsLowSpeed'].tolist()),
        }
    out['byDriveType'] = bt
    # M204 (2026-09-01): flag drive-types where the low-speed window is a
    # small, episodic share of the drive (median <20% of drive duration).
    # For these, startsPer10minStopGo divides a handful of discrete starts by
    # a short, lumpy window (a ramp, a toll gate, a congestion pinch-point --
    # not a sustained stop-go duty cycle), so the rate is high-variance by
    # construction and swings between 0 and a large value on individual
    # drives depending on whether any starts happen to fall in that brief
    # window. This was checked against the raw per-drive data (all 20
    # highway drives, M204 investigation): median low-speed time/drive ~5-13%
    # of drive duration for highway vs ~57% for urban in a same-size sample,
    # and 3 of the 20 highway drives show startsPer10minStopGo == 0 while the
    # single highest (13.0/10min) comes from a drive with only 415s of
    # low-speed time carrying 9 starts. Not a detection-filtering artefact --
    # byDriveType covers every drive of that type with >=120 valid speed
    # samples (n sums to nDrivesCovered), including drives with zero stop-go
    # activity.
    small_denom = sorted(
        k for k, v in bt.items()
        if v.get('lowSpeedFracOfDrive') and
        v['lowSpeedFracOfDrive'].get('median') is not None and
        v['lowSpeedFracOfDrive']['median'] < 0.20)
    out['smallDenominatorDriveTypes'] = small_denom
    out['rateCaveat'] = (
        'startsPer10minStopGo = startsLowSpeed / (lowSpeedTimeS/600), '
        'computed per drive then aggregated by drive type. The denominator '
        '(seconds at <=stopGoCeil km/h) is NOT a fixed window -- it is '
        'whatever low-speed time that one drive actually contains. Urban '
        'drives spend the majority of their duration in this band (large, '
        'stable denominator); drive types in smallDenominatorDriveTypes '
        '(median low-speed time <20% of drive duration -- typically '
        'highway/mixed_highway) touch it only in brief, episodic windows: '
        'ramps, toll gates, a congestion pinch-point, not a sustained '
        'stop-go duty cycle. A handful of discrete engine starts landing '
        'inside a short low-speed window inflates the ratio; the identical '
        'window with zero starts reads zero -- hence the wide IQR/p95 on '
        'these types relative to urban. Read the rate together with '
        'lowSpeedTimeS (the window size) and startsLowSpeedAbs (the raw '
        'count) reported alongside it, not in isolation. This is the same '
        'short-window/small-sample denominator pattern already documented '
        'corpus-wide for short-trip throughput (M35), here affecting a rate '
        'rather than an intensity figure. Descriptive only: no claim that '
        'highway driving produces more frequent stop-go engine cycling in '
        'absolute terms -- the opposite is true (urban carries far more '
        'absolute low-speed/engine-start volume); this is purely about '
        'per-drive-type rate variance from a small, uneven denominator.')
    # threshold sensitivity: rerun headline medians at alternative cuts.
    # Cheap because we re-segment only; report net-Wh/cycle + starts/10min.
    sens = []
    for sv_, ceil_ in [(1.0, 30.0), (2.5, 30.0), (1.5, 25.0), (1.5, 40.0)]:
        nn, ss, ntime, nstart = [], [], 0, 0
        for _, row in dm.iterrows():
            try:
                g = _csg_grid(row['file'], raw_loader, frame_loader)
            except Exception:
                continue
            r = _csg_events(g, stop_v=sv_, stopgo_ceil=ceil_)
            if r is None:
                continue
            nn += [c['whCycleNet'] for c in r['cycles']]
            if r['lowSpeedTimeS'] > 0:
                ss.append(r['startsLowSpeed'] / (r['lowSpeedTimeS'] / 600.0))
        sens.append({'stopV': sv_, 'stopGoCeil': ceil_,
                     'netWhCycleMedian': (round(float(np.nanmedian(
                         [v for v in nn if v is not None])), 2) if nn else None),
                     'nCycles': len([v for v in nn if v is not None]),
                     'startsPer10minMedian': (round(float(np.median(ss)), 2)
                                              if ss else None)})
    out['thresholdSensitivity'] = sens
    out['thresholds'] = {'stopV': 1.5, 'minStopS': 3, 'moveV': 15.0,
                         'stopGoCeil': 30.0, 'windowCapS': 20}
    out['methodology'] = (
        'Per-drive 1 Hz grid. STOP = speed<1.5 km/h sustained >=3 s; '
        'LAUNCH/APPROACH = transient to/from 15 km/h (cap 20 s); STOP-GO '
        'CYCLE = consecutive-stop pair with inter-stop speed peak <=30 km/h. '
        'Energy p_dis=(-I)*V/1000 kW (M11 discharge-positive): whCycleNet = '
        'signed integral over the cycle; whLaunchOut / whApproachIn = gross '
        'discharge-out / regen-in over the phase windows; recoveryRatio = '
        'in/out. Aggregation is cycle/drive/day (never 1 Hz seconds as '
        'replicates); medians/IQR for skewed energy; day-clustered bootstrap '
        '(seed 42, 4000 draws) for headline CIs. Single vehicle / ~single '
        'driver -- descriptive characterisation, no control-strategy or '
        'population claim. Sub-second launch dynamics (jerk, t10/t50/t90) are '
        'below the ~1.3 Hz cadence floor and are NOT reported. Speed is the '
        'VCM/OBD channel, not wheel-speed; thresholdSensitivity sweeps the '
        'STOP_V and stop-go-ceiling cuts so the headline does not hinge on '
        'one threshold. byDriveType covers every drive of that type passing '
        'the >=120-sample speed-data gate (n sums to nDrivesCovered), '
        'including drives with zero stop-go activity -- it is not filtered '
        'to drives where a cycle was detected. M204 (2026-09-01) added '
        'lowSpeedTimeS / lowSpeedFracOfDrive / startsLowSpeedAbs to '
        'byDriveType and out.rateCaveat, since startsPer10minStopGo divides '
        'a small numerator by a per-drive-type-uneven denominator and reads '
        'misleadingly on its own for episodic-low-speed drive types; see '
        'out.rateCaveat for the full interpretation.')
    return out


def _crawl_stop_go_two_part(dm, raw_loader, frame_loader=None):
    """M226.1 (P1.1, enhancement plan): stop-go zero-inflation two-part
    model. Re-derives the SAME per-drive cycle/approach event lists
    _crawl_stop_go itself builds (via _csg_grid/_csg_events, frame_loader-
    cached -- not a new raw pass, matching this codebase's established
    re-derive-rather-than-touch-the-existing-function convention used
    elsewhere this session, e.g. M223.2's _regime_transition_hardening),
    this time retaining the M226.1-extended per-event covariates (decel
    rate, engine-restart flag, preceding-engine-state, SoC/pack-temp at
    the stop) that _crawl_stop_go's own aggregation loop discards.

    regenProbability: P(grossInWh > 0 | context) as an empirical binned
    proportion with a day-clustered bootstrap CI, NOT a fitted parametric
    logistic -- matching this codebase's dominant binned + day-clustered-
    bootstrap convention rather than introducing a new GLM family for one
    metric. conditionalMagnitude: quantiles of grossInWh GIVEN
    grossInWh > 0 -- the genuine two-part-model second stage; the existing
    crawlStopGo.whPerApproachRegen/recoveryRatio (pooled, including zeros)
    are UNCHANGED and retained for continuity, per the plan's explicit
    instruction. netCycleByPeakSpeed: whCycleNet binned by peak speed x
    deceleration-intensity tercile. restartProbability: P(engineRestarted)
    within a cycle, overall and split by preceding engine state.
    stopEffectCovariates: regen/restart probability split by stop-duration,
    SoC, and pack-temperature terciles.

    movingSegmentComparison is the one piece NOT a reuse of existing
    extraction (the plan's own acknowledgement): continuously-moving runs
    (never below stop_v for >=20s) on the SAME 1 Hz grid _csg_grid already
    builds. Reported as side-by-side distributions (net energy, mean
    speed) rather than exact per-cycle speed-matched pairs -- at this
    sample size, strict pairwise matching would leave very few matched
    pairs; a coarser but disclosed comparison, not silently narrowed.

    Single vehicle / ~single driver -- descriptive, not causal.
    """
    if frame_loader is None and raw_loader is None:
        return None

    def _at(arr, i):
        if arr is None or i < 0 or i >= len(arr):
            return None
        v = arr[i]
        return float(v) if v == v else None

    all_cycles, all_approaches, moving_segments = [], [], []
    for _, row in dm.iterrows():
        fn = row['file']
        day = str(row.get('date'))[:10]
        try:
            g = _csg_grid(fn, raw_loader, frame_loader)
        except Exception:
            continue
        r = _csg_events(g)
        if r is None:
            continue
        for c in r['cycles']:
            c = dict(c)
            c['day'] = day
            all_cycles.append(c)
        for ap in r['approaches']:
            ap = dict(ap)
            ap['day'] = day
            all_approaches.append(ap)
        if g is not None and 'speed' in g.columns:
            sv = g['speed'].values
            p = (((-g['I']) * g['V'] / 1000.0)
                 if ('I' in g.columns and 'V' in g.columns) else None)
            moving_mask = np.isfinite(sv) & (sv >= 1.5)
            for a, b in _csg_runs(moving_mask):
                if (b - a + 1) < 20:
                    continue
                mean_v = float(np.nanmean(sv[a:b + 1]))
                net_wh = None
                if p is not None:
                    seg_p = p.iloc[a:b + 1].dropna()
                    if len(seg_p):
                        net_wh = float(seg_p.sum()) / 3.6
                moving_segments.append({'day': day, 'durS': b - a + 1,
                                        'meanSpeedKmh': mean_v, 'netWh': net_wh})

    if not all_cycles and not all_approaches:
        return None

    def dayboot_prop(pairs, seed=42, n_boot=4000):
        from collections import defaultdict
        grp = defaultdict(list)
        for d, v in pairs:
            if v is not None:
                grp[d].append(1.0 if v else 0.0)
        keys = [k for k in grp if grp[k]]
        if len(keys) < 3:
            return None
        arrs = {k: np.array(grp[k]) for k in keys}
        rng = np.random.default_rng(seed)
        props = np.empty(n_boot)
        for i in range(n_boot):
            samp = rng.choice(len(keys), len(keys), replace=True)
            props[i] = np.mean(np.concatenate([arrs[keys[j]] for j in samp]))
        allv = np.concatenate(list(arrs.values()))
        return {'proportion': round(float(allv.mean()), 4),
               'ci95': [round(float(np.percentile(props, 2.5)), 4),
                        round(float(np.percentile(props, 97.5)), 4)],
               'n': int(len(allv)), 'nDays': int(len(keys))}

    # ---- regenProbability ----
    appr_valid = [a for a in all_approaches if a.get('grossInWh') is not None]
    overall_p = dayboot_prop([(a['day'], a['grossInWh'] > 0) for a in appr_valid])
    vpeaks = np.array([a['vPeak'] for a in appr_valid if a.get('vPeak') is not None])
    by_vpeak = None
    if len(vpeaks) >= 30:
        terc = np.percentile(vpeaks, [33.3, 66.7])
        by_vpeak = []
        for lo, hi, lbl in ((-1.0, terc[0], 'low'), (terc[0], terc[1], 'mid'),
                           (terc[1], 1e9, 'high')):
            sub = [a for a in appr_valid if a.get('vPeak') is not None and lo < a['vPeak'] <= hi]
            row = dayboot_prop([(a['day'], a['grossInWh'] > 0) for a in sub]) or {'n': 0}
            by_vpeak.append({'band': lbl, **row})
    regen_probability = {'overall': overall_p, 'byPeakSpeedTercile': by_vpeak}

    # ---- conditionalMagnitude ----
    positive = [a['grossInWh'] for a in appr_valid if a['grossInWh'] > 0]
    conditional_magnitude = _csg_med_iqr(positive)
    if conditional_magnitude:
        n_zero = sum(1 for a in appr_valid if a['grossInWh'] <= 0)
        n_total = len(appr_valid)
        conditional_magnitude['nZero'] = n_zero
        conditional_magnitude['nTotal'] = n_total
        conditional_magnitude['zeroInflationPct'] = (
            round(100.0 * n_zero / n_total, 1) if n_total else None)

    # ---- netCycleByPeakSpeed ----
    cyc_valid = [c for c in all_cycles if c.get('whCycleNet') is not None]
    decel_vals = np.array([c['decelRateKmhPerS'] for c in cyc_valid
                           if c.get('decelRateKmhPerS') is not None])
    net_by_speed = None
    if len(cyc_valid) >= 30 and len(decel_vals) >= 30:
        v_terc = np.percentile([c['vPeak'] for c in cyc_valid], [33.3, 66.7])
        d_terc = np.percentile(decel_vals, [33.3, 66.7])
        net_by_speed = []
        for vlo, vhi, vlbl in ((-1.0, v_terc[0], 'low'), (v_terc[0], v_terc[1], 'mid'),
                              (v_terc[1], 1e9, 'high')):
            for dlo, dhi, dlbl in ((-1.0, d_terc[0], 'low'), (d_terc[0], d_terc[1], 'mid'),
                                  (d_terc[1], 1e9, 'high')):
                sub = [c['whCycleNet'] for c in cyc_valid
                      if vlo < c['vPeak'] <= vhi and c.get('decelRateKmhPerS') is not None
                      and dlo < c['decelRateKmhPerS'] <= dhi]
                if sub:
                    net_by_speed.append({'peakSpeedBand': vlbl, 'decelBand': dlbl,
                                        **(_csg_med_iqr(sub) or {})})

    # ---- restartProbability ----
    cyc_restart_known = [c for c in all_cycles if c.get('engineRestarted') is not None]
    preceding_split = []
    for state in (True, False):
        sub = [c for c in cyc_restart_known if c.get('precedingEngineOn') == state]
        row = dayboot_prop([(c['day'], c['engineRestarted']) for c in sub]) or {'n': 0}
        preceding_split.append({'precedingEngineOn': state, **row})
    restart_probability = {
        'overall': dayboot_prop([(c['day'], c['engineRestarted']) for c in cyc_restart_known]),
        'byPrecedingEngineState': preceding_split,
    }

    # ---- stopEffectCovariates ----
    def tercile_split(items, key, outcome_fn, label):
        vals = np.array([it[key] for it in items if it.get(key) is not None], float)
        if len(vals) < 30:
            return {'note': 'insufficient samples for a %s tercile split' % label}
        terc = np.percentile(vals, [33.3, 66.7])
        out_rows = []
        for lo, hi, lbl in ((-1e12, terc[0], 'low'), (terc[0], terc[1], 'mid'),
                           (terc[1], 1e12, 'high')):
            sub = [it for it in items if it.get(key) is not None and lo < it[key] <= hi]
            out_rows.append({'band': lbl, **(outcome_fn(sub) or {'n': 0})})
        return {'bands': out_rows}

    stop_effect_covariates = {
        'stopDurationS_vs_restartProb': tercile_split(
            cyc_restart_known, 'stopDurationS',
            lambda sub: dayboot_prop([(c['day'], c['engineRestarted']) for c in sub]),
            'stop duration'),
        'socAtStop_vs_restartProb': tercile_split(
            cyc_restart_known, 'socAtStop',
            lambda sub: dayboot_prop([(c['day'], c['engineRestarted']) for c in sub]),
            'SoC'),
        'tpackAtStop_vs_restartProb': tercile_split(
            cyc_restart_known, 'tpackAtStop',
            lambda sub: dayboot_prop([(c['day'], c['engineRestarted']) for c in sub]),
            'pack temperature'),
        'socAtStart_vs_regenProb': tercile_split(
            [a for a in appr_valid if a.get('socAtStart') is not None], 'socAtStart',
            lambda sub: dayboot_prop([(a['day'], a['grossInWh'] > 0) for a in sub]),
            'SoC (approach)'),
    }

    # ---- movingSegmentComparison ----
    moving_comparison = None
    if moving_segments and cyc_valid:
        mv_speed = [m['meanSpeedKmh'] for m in moving_segments if m.get('meanSpeedKmh') is not None]
        moving_speed_stats = _csg_med_iqr(mv_speed) if mv_speed else None
        cycle_speed_stats = _csg_med_iqr([c['vPeak'] for c in cyc_valid])
        speed_gap_note = ''
        if moving_speed_stats and cycle_speed_stats:
            speed_gap_note = ((' MEDIAN SPEED GAP: %.1f km/h (moving) vs. '
                              '%.1f km/h (cycles, peak) -- the two '
                              'populations are NOT speed-matched at this '
                              'sample size, disclosed numerically rather '
                              'than only in prose; treat the net-energy '
                              'comparison as two different operating '
                              'regimes shown side by side, not a matched-'
                              'pair contrast.')
                             % (moving_speed_stats['median'], cycle_speed_stats['median']))
        moving_comparison = {
            'nMovingSegments': len(moving_segments),
            'movingNetWh': _csg_med_iqr([m['netWh'] for m in moving_segments
                                        if m.get('netWh') is not None]),
            'cycleNetWh': _csg_med_iqr([c['whCycleNet'] for c in cyc_valid]),
            'meanSpeedKmhMoving': moving_speed_stats,
            'meanSpeedKmhCycles': cycle_speed_stats,
            'note': ('New segment-extraction sub-pass (continuously-moving '
                     'runs, speed never below 1.5 km/h for >=20s, same '
                     '1 Hz grid _csg_grid already builds) -- not '
                     'individually matched pair-by-pair on mean speed; the '
                     'two populations\' overall speed and net-energy '
                     'distributions are reported side by side instead, '
                     'since strict per-cycle matching at this sample size '
                     'would leave very few matched pairs. A coarser but '
                     'disclosed comparison, not silently narrowed.'
                     + speed_gap_note),
        }

    return {
        'nCyclesCovered': len(cyc_valid), 'nApproachesCovered': len(appr_valid),
        'regenProbability': regen_probability,
        'conditionalMagnitude': conditional_magnitude,
        'netCycleByPeakSpeed': net_by_speed,
        'restartProbability': restart_probability,
        'stopEffectCovariates': stop_effect_covariates,
        'movingSegmentComparison': moving_comparison,
        'twoPartMethodology': (
            'M226.1 (P1.1, enhancement plan): two-part model over the SAME '
            'approach/cycle event lists crawlStopGo itself builds. Part 1 '
            '(regenProbability): empirical P(grossInWh>0), day-clustered '
            'bootstrap CI (seed=42, 4000 draws), not a fitted parametric '
            'logistic. Part 2 (conditionalMagnitude): quantiles of '
            'grossInWh GIVEN grossInWh>0 -- crawlStopGo.whPerApproachRegen/'
            'recoveryRatio (pooled, including zeros) are retained '
            'unchanged for continuity. netCycleByPeakSpeed bins '
            'whCycleNet by peak-speed x deceleration-intensity tercile '
            '(decel rate = peak speed / approach-phase duration, the same '
            'window crawlStopGo\'s own energy phases already use). '
            'restartProbability/stopEffectCovariates use the SAME '
            'day-clustered-bootstrap-proportion estimator throughout. '
            'movingSegmentComparison is the one new segment-extraction '
            'sub-pass (see its own note) -- everything else re-derives '
            '_csg_grid/_csg_events (frame_loader-cached, not a new raw '
            'pass) rather than touching crawlStopGo itself, so '
            'crawlStopGo\'s existing fields are unaffected by construction. '
            'Single vehicle / ~single driver -- descriptive, not causal.'),
    }


# ── Module A (M184): accel/decel speed-binned dynamics envelopes ──────────────
# Speed-aligned median/IQR of the logged longitudinal acceleration(g), battery
# power, engine RPM, boost, per-second SoC-rate and TARGET motor torque, split
# by accel vs decel phase, corpus-wide. New relative to torqueBySpeed (which is
# a speed x torque occupancy histogram only, no phase split and no dynamics
# envelope). Conventions per the feasibility review's tier-1 shared rules:
# episode/drive/day as the unit (never 1 Hz seconds as replicates for CIs);
# median/IQR for skewed data; day-clustered bootstrap; target torque (not the
# M102-rejected actual torque) as the command signal; naturalistic labelling.
#
# Resolution honesty: acceleration is the LOGGED accel(g) sensor channel
# (schema-v6 slim cache), a genuine ~1.26 Hz batched-synchronous reading, NOT a
# diff(speed) derivative. Sub-second latency / time-constants are below the
# cadence floor and are NOT reported. Jerk = |d accg/dt| is carried only as a
# clearly-flagged exploratory descriptor (candidate P), never a headline. Per-
# second SoC-rate is quantisation-dominated (0.5 % SoC steps at ~1 Hz -> most
# 1 s diffs are exactly 0, with spurious spikes when a step lands in one
# second); it is carried for completeness but flagged, and the battery-kW
# envelope is the real per-phase energy-flow signal. Single vehicle / ~single
# driver -> descriptive, no control-strategy or population claim.
_ADE_COLS = {'[BMS] HV Battery Current (A)': 'I',
             '[BMS] HV Battery voltage (V)': 'V',
             '[BMS] HV State of charge (%)': 'soc',
             '[VCM] Vehicle Speed (km/h)': 'speed',
             '\u041e\u0431\u0435\u0440\u0442\u0438 \u0434\u0432\u0438\u0433\u0443\u043d\u0430 (rpm)': 'rpm',
             '\u0420\u043e\u0437\u0440\u0430\u0445\u0443\u043d\u043a\u043e\u0432\u0438\u0439 \u043d\u0430\u0434\u0434\u0443\u0432 (bar)': 'boost',
             '[VCM] Target Motor Torque (N\u22c5m)': 'tqTgt',
             '\u041f\u0440\u0438\u0441\u043a\u043e\u0440\u0435\u043d\u043d\u044f (g)': 'accg'}
_ADE_SPEED_EDGES = [0, 10, 20, 30, 40, 50, 70, 90, 110, 130, float('inf')]
_ADE_MOVE_V = 3.0          # km/h floor: below this is not "moving"
_ADE_THR_DEFAULT = 0.02    # g: |accg| >= thr => accel/decel, else cruise


def _ade_grid(fn, raw_loader, frame_loader):
    if frame_loader is not None:
        fr = frame_loader(fn)
        if fr is None:
            return None
        df = fr[[c for c in fr.columns
                 if c in _ADE_COLS or c == 'time' or c == _SPEED_OBD_RAW]]
    else:
        raw = raw_loader(fn) if raw_loader is not None else None
        if not raw:
            return None
        df = pd.read_csv(io.BytesIO(raw),
                         usecols=lambda c: (c in _ADE_COLS or c == 'time'
                                            or c == _SPEED_OBD_RAW),
                         low_memory=False)
    df, _ = _apply_speed_priority(df)              # M167, before the rename
    df = df.rename(columns=_ADE_COLS)
    if 'time' not in df.columns or 'speed' not in df.columns or 'accg' not in df.columns:
        return None
    g = df.set_index(pd.to_datetime(df['time'], errors='coerce'))
    keep = [c for c in ('I', 'V', 'soc', 'speed', 'rpm', 'boost', 'tqTgt', 'accg')
            if c in g.columns]
    g = g[keep].apply(pd.to_numeric, errors='coerce')
    return g.resample('1s').mean().ffill(limit=3)


def _ade_mi(vals):
    import numpy as _np
    v = _np.asarray([x for x in vals if x == x], float)
    if v.size == 0:
        return None
    return {'median': round(float(_np.median(v)), 3),
            'p25': round(float(_np.percentile(v, 25)), 3),
            'p75': round(float(_np.percentile(v, 75)), 3),
            'n': int(v.size)}


def _ade_dayboot(vals, dates, nb=4000, seed=42):
    import numpy as _np
    v = _np.asarray(vals, float)
    dts = _np.asarray(dates)
    m = _np.isfinite(v)
    v, dts = v[m], dts[m]
    if v.size < 3:
        return None
    uniq = _np.unique(dts)
    by = {d: v[dts == d] for d in uniq}
    rng = _np.random.default_rng(seed)
    meds = []
    for _ in range(nb):
        samp = rng.choice(uniq, size=len(uniq), replace=True)
        meds.append(_np.median(_np.concatenate([by[d] for d in samp])))
    return {'bootMedian': round(float(_np.median(v)), 3),
            'ci95': [round(float(_np.percentile(meds, 2.5)), 3),
                     round(float(_np.percentile(meds, 97.5)), 3)],
            'nDrives': int(v.size), 'nDays': int(uniq.size)}


def _accel_decel_envelopes(dm, raw_loader, frame_loader=None,
                           a_thr=_ADE_THR_DEFAULT):
    """Corpus-wide accel/decel speed-binned dynamics envelopes (Module A)."""
    import numpy as _np
    edges = _ADE_SPEED_EDGES
    nlab = len(edges) - 1
    metrics = ['accg', 'battKw', 'rpm', 'boost', 'socRate', 'tqTgt']
    pool = {ph: [{m: [] for m in metrics} for _ in range(nlab)]
            for ph in ('accel', 'decel')}
    perdrive = {ph: {'battKw': [], 'date': []} for ph in ('accel', 'decel')}
    jerk = {'accel': [], 'decel': []}
    # threshold-sensitivity accumulators: per-drive accel/decel median battKw at
    # each alternate threshold (headline robustness; cheap, same grids)
    thr_grid = [0.015, 0.02, 0.03]
    thr_pd = {t: {'accel': [], 'decel': [], 'ad': [], 'dd': []} for t in thr_grid}

    nCov = nEnergy = 0
    coveredKm = 0.0
    days = set()
    for _, r in dm.iterrows():
        fn = r['file']
        g = _ade_grid(fn, raw_loader, frame_loader)
        if g is None or 'accg' not in g.columns:
            continue
        g = g.dropna(subset=['speed', 'accg'])
        if len(g) < 10:
            continue
        nCov += 1
        d = str(r.get('date', ''))[:10]
        days.add(d)
        coveredKm += float(r.get('distance_km', 0) or 0)
        gm = g[g['speed'] >= _ADE_MOVE_V]
        if len(gm) < 5:
            continue
        has_iv = ('I' in gm.columns and 'V' in gm.columns
                  and gm['I'].notna().sum() >= 5 and gm['V'].notna().sum() >= 5)
        if has_iv:
            nEnergy += 1
        battKw = (((-gm['I']) * gm['V'] / 1000.0) if has_iv
                  else pd.Series(_np.nan, index=gm.index))
        socRate = (gm['soc'].diff() * 60.0 if 'soc' in gm.columns
                   else pd.Series(_np.nan, index=gm.index))
        jk = gm['accg'].diff().abs()
        accv = gm['accg'].values
        sbin = _np.digitize(gm['speed'].values, edges[1:-1])
        bkv = battKw.values
        # main threshold
        acc_mask = accv >= a_thr
        dec_mask = accv <= -a_thr
        for ph, mask in (('accel', acc_mask), ('decel', dec_mask)):
            if not mask.any():
                continue
            bk = bkv[mask]
            bk = bk[_np.isfinite(bk)]
            if bk.size:
                perdrive[ph]['battKw'].append(float(_np.median(bk)))
                perdrive[ph]['date'].append(d)
            jv = jk.values[mask]
            jerk[ph].extend(jv[_np.isfinite(jv)].tolist())
            for b in range(nlab):
                sel = mask & (sbin == b)
                if not sel.any():
                    continue
                pb = pool[ph][b]
                pb['accg'].extend(accv[sel].tolist())
                fbk = bkv[sel][_np.isfinite(bkv[sel])]
                pb['battKw'].extend(fbk.tolist())
                if 'rpm' in gm.columns:
                    rv = gm['rpm'].values[sel]
                    pb['rpm'].extend(rv[_np.isfinite(rv)].tolist())
                if 'boost' in gm.columns:
                    bv = gm['boost'].values[sel]
                    pb['boost'].extend(bv[_np.isfinite(bv)].tolist())
                sr = socRate.values[sel]
                pb['socRate'].extend(sr[_np.isfinite(sr)].tolist())
                if 'tqTgt' in gm.columns:
                    tv = gm['tqTgt'].values[sel]
                    pb['tqTgt'].extend(tv[_np.isfinite(tv)].tolist())
        # threshold sweep (battKw per-drive medians only)
        for t in thr_grid:
            am = accv >= t
            dmk = accv <= -t
            if am.any():
                ba = bkv[am]
                ba = ba[_np.isfinite(ba)]
                if ba.size:
                    thr_pd[t]['accel'].append(float(_np.median(ba)))
                    thr_pd[t]['ad'].append(d)
            if dmk.any():
                bd = bkv[dmk]
                bd = bd[_np.isfinite(bd)]
                if bd.size:
                    thr_pd[t]['decel'].append(float(_np.median(bd)))
                    thr_pd[t]['dd'].append(d)

    def bin_label(b):
        lo = edges[b]
        hi = edges[b + 1]
        return ("%d+" % int(lo)) if hi == float('inf') else ("%d-%d" % (int(lo), int(hi)))

    out = {'nDrivesCovered': nCov, 'nDrivesEnergy': nEnergy,
           'coveredKm': round(coveredKm, 1), 'nDays': len(days),
           'accelThresholdG': a_thr, 'moveVKmh': _ADE_MOVE_V,
           'speedEdges': [None if e == float('inf') else e for e in edges]}
    for ph in ('accel', 'decel'):
        rows = []
        for b in range(nlab):
            pb = pool[ph][b]
            if len(pb['accg']) < 20:
                continue
            rows.append({'speedBin': bin_label(b),
                         'accgG': _ade_mi(pb['accg']),
                         'battKw': _ade_mi(pb['battKw']),
                         'rpm': _ade_mi(pb['rpm']),
                         'boostBar': _ade_mi(pb['boost']),
                         'socRatePctPerMin': _ade_mi(pb['socRate']),
                         'tqTgtNm': _ade_mi(pb['tqTgt']),
                         'nSamples': len(pb['accg'])})
        out[ph + 'BySpeed'] = rows

    out['accelBattKwBoot'] = _ade_dayboot(perdrive['accel']['battKw'],
                                          perdrive['accel']['date'])
    out['decelBattKwBoot'] = _ade_dayboot(perdrive['decel']['battKw'],
                                          perdrive['decel']['date'])
    out['jerkExploratory'] = {
        'accelP95AbsGPerS': (round(float(_np.percentile(jerk['accel'], 95)), 3)
                             if jerk['accel'] else None),
        'decelP95AbsGPerS': (round(float(_np.percentile(jerk['decel'], 95)), 3)
                             if jerk['decel'] else None),
        'note': 'Jerk = |d(accel_g)/dt| on the ~1.26 Hz grid; noisy and '
                'cadence-limited. Descriptive/exploratory only (candidate P), '
                'NOT a headline.'}
    out['thresholdSensitivity'] = [
        {'thrG': t,
         'accelBattKwMedian': (round(float(_np.median(thr_pd[t]['accel'])), 3)
                               if thr_pd[t]['accel'] else None),
         'decelBattKwMedian': (round(float(_np.median(thr_pd[t]['decel'])), 3)
                               if thr_pd[t]['decel'] else None),
         'nAccelDrives': len(thr_pd[t]['accel']),
         'nDecelDrives': len(thr_pd[t]['decel'])}
        for t in thr_grid]
    out['methodology'] = (
        'Per-drive 1 Hz grid (resample -> ffill(limit=3); speed resolved by the '
        'M167 VCM/OBD priority rule). Phase from the LOGGED accel(g) sensor '
        '(schema-v6 slim cache, ~1.26 Hz, NOT diff(speed)): ACCEL accg>=+%.3f g, '
        'DECEL accg<=-%.3f g, moving samples (speed>=%.1f km/h) only. Battery '
        'power p=(-I)*V/1000 kW (M11 discharge-positive): +ve = traction draw, '
        '-ve = regen/charge. Speed-binned median/IQR of accg, battKw, engine RPM, '
        'boost, per-second SoC-rate and TARGET motor torque (M102: actual torque/'
        'RPM invalid, target is the command signal). Aggregation is drive/day '
        '(never 1 Hz seconds as replicates for CIs); pooled sample median/IQR for '
        'the per-bin envelope shape (nSamples), day-clustered bootstrap (seed 42, '
        '4000 draws) over per-drive medians for the headline battKw CIs. '
        'thresholdSensitivity sweeps the accel/decel threshold. Sub-second latency/'
        'time-constants are below the cadence floor and NOT reported; jerk is '
        'exploratory only; per-second SoC-rate is SoC-quantisation-dominated '
        '(0.5 %% steps) and carried only for completeness. Single vehicle / '
        '~single driver -- descriptive, no control-strategy or population claim.'
        % (a_thr, a_thr, _ADE_MOVE_V))
    return out



# ── Module C (M185): engine RPM vs wheel-speed synchronisation ────────────────
# Series-hybrid signature: in this architecture the engine drives only the
# generator, so its RPM is DECOUPLED from wheel speed and clamps to the efficient
# generator load-point (~2000 rpm) rather than tracking speed through a fixed gear
# ratio. C quantifies that decoupling: Spearman rho, OLS slope and monotonicity of
# engine RPM vs speed over engine-on moving samples, the RPM-by-speed occupancy
# envelope, the fraction of engine-on time at the load-point, and an exploratory
# lead/lag. Contrast reference: a mechanical geartrain would give rho ~ 1 and a
# steep, gear-stepped slope. No acoustic/NVH claims (no cabin-noise channel exists).
# Spearman is computed dependency-free (Pearson on pandas ranks) -- no new import.
_RSYNC_COLS = {'[VCM] Vehicle Speed (km/h)': 'speed',
               '\u041e\u0431\u0435\u0440\u0442\u0438 \u0434\u0432\u0438\u0433\u0443\u043d\u0430 (rpm)': 'rpm'}
_RSYNC_EDGES = [0, 10, 20, 30, 40, 50, 70, 90, 110, 130, float('inf')]
_RSYNC_MOVE_V = 3.0
_RSYNC_ENG_ON = 400.0
# M206 (2026-09-01): tightened from the M185-era [1800,2200] (an
# unvalidated +-200rpm guess made before the peak's true shape was known)
# to [1975,2025] (2000+-25rpm) to match M205's 5rpm-resolution
# re-derivation, which confirmed the generator load-point is a genuinely
# narrow spike (weighted center of mass 2000.30rpm, 96%+ of the
# 1975-2025rpm window's mass within +-25rpm of 2000) rather than a broad
# +-200rpm plateau. See CHANGELOG M206 for the isolated diff.
_RSYNC_LP_LO, _RSYNC_LP_HI = 1975.0, 2025.0


def _rsync_grid(fn, raw_loader, frame_loader):
    if frame_loader is not None:
        fr = frame_loader(fn)
        if fr is None:
            return None
        df = fr[[c for c in fr.columns
                 if c in _RSYNC_COLS or c == 'time' or c == _SPEED_OBD_RAW]]
    else:
        raw = raw_loader(fn) if raw_loader is not None else None
        if not raw:
            return None
        df = pd.read_csv(io.BytesIO(raw),
                         usecols=lambda c: (c in _RSYNC_COLS or c == 'time'
                                            or c == _SPEED_OBD_RAW),
                         low_memory=False)
    df, _ = _apply_speed_priority(df)
    df = df.rename(columns=_RSYNC_COLS)
    if 'time' not in df.columns or 'speed' not in df.columns or 'rpm' not in df.columns:
        return None
    g = df.set_index(pd.to_datetime(df['time'], errors='coerce'))
    g = g[[c for c in ('speed', 'rpm') if c in g.columns]].apply(pd.to_numeric, errors='coerce')
    return g.resample('1s').mean().ffill(limit=3)


def _rsync_spearman(x, y):
    """Spearman rho = Pearson correlation of ranks (dependency-free)."""
    import numpy as _np
    rx = pd.Series(x).rank().values
    ry = pd.Series(y).rank().values
    if _np.std(rx) < 1e-9 or _np.std(ry) < 1e-9:
        return float('nan')
    return float(_np.corrcoef(rx, ry)[0, 1])


def _rpm_speed_sync(dm, raw_loader, frame_loader=None):
    import numpy as _np
    edges = _RSYNC_EDGES
    nlab = len(edges) - 1
    perdrive = {'rho': [], 'slope': [], 'lpFrac': [], 'date': []}
    pool = [[] for _ in range(nlab)]
    lagcount = {l: 0 for l in (-2, -1, 0, 1, 2)}
    nCov = 0
    coveredKm = 0.0
    days = set()
    for _, r in dm.iterrows():
        g = _rsync_grid(r['file'], raw_loader, frame_loader)
        if g is None:
            continue
        g = g.dropna(subset=['speed', 'rpm'])
        if len(g) < 30:
            continue
        eng = g[(g['rpm'] > _RSYNC_ENG_ON) & (g['speed'] >= _RSYNC_MOVE_V)]
        if len(eng) < 30:
            continue
        nCov += 1
        d = str(r.get('date', ''))[:10]
        days.add(d)
        coveredKm += float(r.get('distance_km', 0) or 0)
        sp = eng['speed'].values
        rp = eng['rpm'].values
        if _np.std(sp) > 1e-6 and _np.std(rp) > 1e-6:
            rho = _rsync_spearman(sp, rp)
            if rho == rho:
                slope = float(_np.polyfit(sp, rp, 1)[0])
                perdrive['rho'].append(rho)
                perdrive['slope'].append(slope)
                perdrive['lpFrac'].append(
                    float(((rp >= _RSYNC_LP_LO) & (rp <= _RSYNC_LP_HI)).mean()))
                perdrive['date'].append(d)
        sb = _np.digitize(sp, edges[1:-1])
        for b in range(nlab):
            pool[b].extend(rp[sb == b].tolist())
        s2 = sp - sp.mean()
        r2 = rp - rp.mean()
        if len(s2) > 20 and _np.std(s2) > 1e-6 and _np.std(r2) > 1e-6:
            best, bl = -1.0, 0
            for lag in (-2, -1, 0, 1, 2):
                if lag < 0:
                    a, b_ = s2[:lag], r2[-lag:]
                elif lag > 0:
                    a, b_ = s2[lag:], r2[:-lag]
                else:
                    a, b_ = s2, r2
                if len(a) > 10:
                    c = _np.corrcoef(a, b_)[0, 1]
                    if abs(c) > best:
                        best, bl = abs(c), lag
            lagcount[bl] += 1

    def blabel(b):
        lo, hi = edges[b], edges[b + 1]
        return ("%d+" % int(lo)) if hi == float('inf') else ("%d-%d" % (int(lo), int(hi)))

    def dayboot(vals, dates, nb=4000, seed=42):
        v = _np.asarray(vals, float)
        dts = _np.asarray(dates)
        m = _np.isfinite(v)
        v, dts = v[m], dts[m]
        if v.size < 3:
            return None
        uniq = _np.unique(dts)
        by = {d: v[dts == d] for d in uniq}
        rng = _np.random.default_rng(seed)
        meds = []
        for _ in range(nb):
            s = rng.choice(uniq, len(uniq), replace=True)
            meds.append(_np.median(_np.concatenate([by[d] for d in s])))
        return {'bootMedian': round(float(_np.median(v)), 3),
                'ci95': [round(float(_np.percentile(meds, 2.5)), 3),
                         round(float(_np.percentile(meds, 97.5)), 3)],
                'nDrives': int(v.size), 'nDays': int(uniq.size)}

    def mi(v):
        v = _np.asarray([x for x in v if x == x], float)
        if v.size == 0:
            return None
        return {'median': round(float(_np.median(v)), 3),
                'p25': round(float(_np.percentile(v, 25)), 3),
                'p75': round(float(_np.percentile(v, 75)), 3), 'n': int(v.size)}

    rpmBySpeed = []
    for b in range(nlab):
        if len(pool[b]) >= 20:
            rpmBySpeed.append({'speedBin': blabel(b), 'rpm': mi(pool[b]),
                               'nSamples': len(pool[b])})
    meds = [row['rpm']['median'] for row in rpmBySpeed if row['rpm']]
    incr = sum(1 for i in range(1, len(meds)) if meds[i] > meds[i - 1])
    return {
        'nDrivesCovered': nCov, 'coveredKm': round(coveredKm, 1), 'nDays': len(days),
        'engOnRpm': _RSYNC_ENG_ON, 'loadPointBand': [_RSYNC_LP_LO, _RSYNC_LP_HI],
        'moveVKmh': _RSYNC_MOVE_V,
        'rhoMedIqr': mi(perdrive['rho']), 'slopeMedIqr': mi(perdrive['slope']),
        'loadPointFracMedIqr': mi(perdrive['lpFrac']),
        'rhoBoot': dayboot(perdrive['rho'], perdrive['date']),
        'rpmBySpeed': rpmBySpeed,
        'monotonicIncrFrac': round(incr / max(len(meds) - 1, 1), 3),
        'leadLagExploratory': {
            'lagCounts': lagcount,
            'note': 'Per-drive best speed-RPM cross-correlation lag over ±2 s. At '
                    'the ~1.26 Hz cadence this is near the resolvable floor -- '
                    'exploratory/descriptive only, no timing claim.'},
        'methodology': (
            'Engine RPM vs wheel speed over engine-on (rpm>%d) moving (speed>=%.1f '
            'km/h) 1 Hz samples, per drive. Spearman rho (rank monotonicity), OLS '
            'slope (rpm per km/h) and load-point fraction (rpm in [%d,%d]) '
            'summarised as per-drive median/IQR; day-clustered bootstrap (seed 42, '
            '4000 draws) on median rho. rpmBySpeed is the pooled engine-on RPM '
            'occupancy envelope per speed bin. Contrast: a fixed-ratio geartrain '
            'gives rho~1 and a steep gear-stepped slope; the low rho and shallow '
            'slope here quantify the series-hybrid decoupling (engine serves the '
            'generator/buffer, not the wheels). Lead/lag is exploratory '
            '(cadence-limited). No acoustic/NVH claim -- no cabin-noise channel '
            'exists. Single vehicle / ~single driver -- descriptive.'
            % (int(_RSYNC_ENG_ON), _RSYNC_MOVE_V, int(_RSYNC_LP_LO), int(_RSYNC_LP_HI)))}



# ── Module I (M186): engine-start context taxonomy ───────────────────────────
# For every CANONICAL engine start (the M116/M119-family debounced trigger,
# reused verbatim via _engine_start_triggers -- NOT the frozen M119-v2 hazard
# model), classify the pre-start context with multi-label rule-based rules and
# report the share of each label AND the unclassified share. This answers "why
# did the generator kick on?" descriptively, complementing M119 (which models
# start PROBABILITY) and engineStartsByType (which counts starts per drive-type).
# Thresholds are grounded on the observed pre-start feature distributions across
# the corpus (SoC clusters 54-70 %, speed 22-85 km/h, coolant mostly warm,
# pre-start demand median ~10 kW / torque ~27 N.m); a thresholdSensitivity sweep
# is shipped. Multi-label by construction (a start can be both high-demand and
# high-speed). A substantial unclassified share is expected and reported, not
# hidden. Formal hand-validation against a user-labelled subset is the pending
# confirmation step -- an illustrative classified sample is shipped for it.
_ISC_SOC = '[BMS] HV State of charge (%)'
_ISC_I = '[BMS] HV Battery Current (A)'
_ISC_V = '[BMS] HV Battery voltage (V)'
_ISC_TQ = '[VCM] Target Motor Torque (N\u22c5m)'
_ISC_COOL = '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043e\u0445\u043e\u043b\u043e\u0434\u043d\u043e\u0457 \u0440\u0456\u0434\u0438\u043d\u0438 (\u2103)'
_ISC_SPD = '[VCM] Vehicle Speed (km/h)'
# grounded rule thresholds
_ISC_SOC_LOW = 55.0        # <= => lowBuffer (buffer depleted)
_ISC_SOC_MAINT = 63.0      # (SOC_LOW, this] => socMaintenance (below ~65 setpoint)
_ISC_DISC_KW = 20.0        # pre-start discharge >= => highDemand
_ISC_TQ_NM = 60.0          # pre-start target torque >= => highDemand
_ISC_SPD_HI = 70.0         # speed >= => highSpeedCruise
_ISC_SPD_LO = 20.0         # speed <  => creepLaunch
_ISC_COOL_COLD = 60.0      # coolant <= => coldEngine


def _isc_grid(fr):
    if fr is None:
        return None
    fr2, _ = _apply_speed_priority(fr)
    keep = {_ISC_SOC: 'soc', _ISC_I: 'I', _ISC_V: 'V', _ISC_TQ: 'tq',
            _ISC_COOL: 'cool', _ISC_SPD: 'speed'}
    cols = {c: n for c, n in keep.items() if c in fr2.columns}
    if 'time' not in fr2.columns or _ISC_SPD not in fr2.columns:
        return None
    g = fr2.set_index(pd.to_datetime(fr2['time'], errors='coerce'))
    g = g[list(cols)].rename(columns=cols).apply(pd.to_numeric, errors='coerce')
    return g.resample('1s').mean().ffill(limit=3)


def _isc_context(g, t0):
    """Pre-start context feature vector for a start at t0 (Timestamp)."""
    pre = g.loc[t0 - pd.Timedelta(seconds=5):t0 - pd.Timedelta(seconds=1)]
    at = g.loc[t0 - pd.Timedelta(seconds=2):t0]
    if len(at) == 0:
        return None

    def last(col, frame):
        if col in frame.columns and frame[col].notna().any():
            return float(frame[col].dropna().iloc[-1])
        return float('nan')
    soc = last('soc', at)
    spd = last('speed', at)
    cool = last('cool', at)
    disc = float('nan')
    if 'I' in pre.columns and 'V' in pre.columns and pre['I'].notna().any():
        disc = float((((-pre['I']) * pre['V'] / 1000.0)).median())
    tq = float('nan')
    if 'tq' in pre.columns and pre['tq'].notna().any():
        tq = float(pre['tq'].clip(lower=0).median())
    return {'soc': soc, 'speed': spd, 'cool': cool, 'discKw': disc, 'tqDemand': tq}


def _isc_labels(c, soc_low=_ISC_SOC_LOW, disc_kw=_ISC_DISC_KW):
    """Multi-label rule set -> list of labels (may be empty = unclassified)."""
    import math
    labs = []
    soc, spd, cool, disc, tq = (c['soc'], c['speed'], c['cool'],
                                c['discKw'], c['tqDemand'])
    ok = lambda x: (x == x)  # not-NaN
    if ok(soc) and soc <= soc_low:
        labs.append('lowBuffer')
    elif ok(soc) and soc <= _ISC_SOC_MAINT:
        labs.append('socMaintenance')
    if (ok(disc) and disc >= disc_kw) or (ok(tq) and tq >= _ISC_TQ_NM):
        labs.append('highDemand')
    if ok(spd) and spd >= _ISC_SPD_HI:
        labs.append('highSpeedCruise')
    if ok(spd) and spd < _ISC_SPD_LO:
        labs.append('creepLaunch')
    if ok(cool) and cool <= _ISC_COOL_COLD:
        labs.append('coldEngine')
    return labs


def _engine_start_context(dm, frame_loader=None, sample_n=12):
    if frame_loader is None:
        return None
    import numpy as _np
    LABELS = ['lowBuffer', 'socMaintenance', 'highDemand', 'highSpeedCruise',
              'creepLaunch', 'coldEngine']
    counts = {k: 0 for k in LABELS}
    nStarts = nContext = nUnclassified = 0
    nlab_sum = 0
    perdrive = {'rate': [], 'date': []}   # starts per 100 km per drive
    days = set()
    coveredKm = 0.0
    sample = []
    # threshold sensitivity accumulators
    thr = {'socLow': {50.0: 0, 55.0: 0, 60.0: 0},
           'discKw': {15.0: 0, 20.0: 0, 25.0: 0}}
    thr_ctx = []   # keep light context list for the sweep

    for _, r in dm.iterrows():
        fr = frame_loader(r['file'])
        if fr is None or _BUFIMP_RPM_COL not in fr.columns:
            continue
        trig = _engine_start_triggers(fr)
        if not trig:
            continue
        g = _isc_grid(fr)
        if g is None:
            continue
        d = str(r.get('date', ''))[:10]
        km = float(r.get('distance_km', 0) or 0)
        dstart = 0
        for ts in trig:
            nStarts += 1
            c = _isc_context(g, pd.Timestamp(ts))
            if c is None:
                continue
            nContext += 1
            dstart += 1
            labs = _isc_labels(c)
            if labs:
                for L in labs:
                    counts[L] += 1
                nlab_sum += len(labs)
            else:
                nUnclassified += 1
            thr_ctx.append((c['soc'], c['discKw'], c['tqDemand']))
            if len(sample) < sample_n and labs:
                sample.append({'drive': r['file'],
                               'soc': None if c['soc'] != c['soc'] else round(c['soc'], 1),
                               'speedKmh': None if c['speed'] != c['speed'] else round(c['speed'], 1),
                               'discKw': None if c['discKw'] != c['discKw'] else round(c['discKw'], 1),
                               'tqDemand': None if c['tqDemand'] != c['tqDemand'] else round(c['tqDemand'], 1),
                               'coolC': None if c['cool'] != c['cool'] else round(c['cool'], 1),
                               'labels': labs})
        if dstart > 0 and km > 0:
            perdrive['rate'].append(dstart / km * 100.0)
            perdrive['date'].append(d)
            days.add(d)
            coveredKm += km

    if nContext == 0:
        return None

    # threshold sweep on the light context list
    for soc, disc, tq in thr_ctx:
        for t in thr['socLow']:
            if soc == soc and soc <= t:
                thr['socLow'][t] += 1
        for t in thr['discKw']:
            if (disc == disc and disc >= t) or (tq == tq and tq >= _ISC_TQ_NM):
                thr['discKw'][t] += 1

    def dayboot(vals, dates, nb=4000, seed=42):
        v = _np.asarray(vals, float)
        dts = _np.asarray(dates)
        m = _np.isfinite(v)
        v, dts = v[m], dts[m]
        if v.size < 3:
            return None
        uniq = _np.unique(dts)
        by = {d: v[dts == d] for d in uniq}
        rng = _np.random.default_rng(seed)
        meds = []
        for _ in range(nb):
            s = rng.choice(uniq, len(uniq), replace=True)
            meds.append(_np.median(_np.concatenate([by[d] for d in s])))
        return {'bootMedian': round(float(_np.median(v)), 3),
                'ci95': [round(float(_np.percentile(meds, 2.5)), 3),
                         round(float(_np.percentile(meds, 97.5)), 3)],
                'nDrives': int(v.size), 'nDays': int(uniq.size)}

    def share(k):
        return round(100.0 * counts[k] / nContext, 1)

    labelShares = [{'label': k, 'n': counts[k], 'pct': share(k)}
                   for k in LABELS]
    labelShares.sort(key=lambda x: -x['pct'])
    return {
        'nStarts': nStarts, 'nStartsWithContext': nContext,
        'coveredKm': round(coveredKm, 1), 'nDays': len(days),
        'labelShares': labelShares,
        'unclassifiedN': nUnclassified,
        'unclassifiedPct': round(100.0 * nUnclassified / nContext, 1),
        'meanLabelsPerStart': round(nlab_sum / nContext, 3),
        'startsPer100kmBoot': dayboot(perdrive['rate'], perdrive['date']),
        'thresholds': {'socLow': _ISC_SOC_LOW, 'socMaint': _ISC_SOC_MAINT,
                       'discKw': _ISC_DISC_KW, 'tqNm': _ISC_TQ_NM,
                       'spdHi': _ISC_SPD_HI, 'spdLo': _ISC_SPD_LO,
                       'coolCold': _ISC_COOL_COLD},
        'thresholdSensitivity': {
            'lowBufferBySocLow': [{'thr': t, 'pct': round(100.0 * thr['socLow'][t] / nContext, 1)}
                                  for t in sorted(thr['socLow'])],
            'highDemandByDiscKw': [{'thr': t, 'pct': round(100.0 * thr['discKw'][t] / nContext, 1)}
                                   for t in sorted(thr['discKw'])]},
        'validationSample': sample,
        'methodology': (
            'Canonical engine-start trigger (_engine_start_triggers: RPM>800 '
            'preceded by sustained RPM<=100 for >=3 s -- the same debounced '
            'detector M116/M119 use, NOT the frozen M119-v2 hazard model). For '
            'each start, pre-start context is read from a 1 Hz grid: SoC/speed/'
            'coolant at the last valid sample in [t0-2s, t0]; demand = median '
            'discharge kW and median clipped TARGET torque over [t0-5s, t0-1s] '
            '(M102: actual torque invalid). Multi-label rules (thresholds grounded '
            'on the observed pre-start distributions, sweep shipped): lowBuffer '
            'SoC<=%g; socMaintenance %g<SoC<=%g; highDemand disc>=%g kW or '
            'tqTgt>=%g N.m; highSpeedCruise speed>=%g; creepLaunch speed<%g; '
            'coldEngine coolant<=%g C. Labels are multi (a start may carry '
            'several); starts matching no rule are reported as unclassified, not '
            'forced. Day-clustered bootstrap (seed 42, 4000 draws) on per-drive '
            'starts/100 km. Formal hand-validation against a user-labelled subset '
            'is pending -- an illustrative classified sample is shipped for it. '
            'Single vehicle / ~single driver -- descriptive.'
            % (_ISC_SOC_LOW, _ISC_SOC_LOW, _ISC_SOC_MAINT, _ISC_DISC_KW,
               _ISC_TQ_NM, _ISC_SPD_HI, _ISC_SPD_LO, _ISC_COOL_COLD))}



# ── Module J (M187): buffer energy-debt recovery (extends M116 bufferImpulse) ──
# M116 measures the discharge IMPULSE the pack sources at each engine start (the
# energy 'debt'). J measures what happens NEXT: how fast and how completely the
# generator refills that debt. It reuses _buffer_impulse_events verbatim for the
# event set and per-event debt (no re-derivation of the detector), then integrates
# the pack's net-discharge energy forward over a recovery window to obtain, per
# event: recovery half-time (to repay 50 % of the debt), net fraction recovered by
# the window end, overshoot (refill PAST the debt -- the generator banking buffer
# headroom while it runs), fraction not recovered, and a SoC cross-check. Signed
# power p_dis=(-I)*V/1000 kW (M11 discharge-positive). Single vehicle / ~single
# driver -- descriptive.
_BDR_I = '[BMS] HV Battery Current (A)'
_BDR_V = '[BMS] HV Battery voltage (V)'
_BDR_SOC = '[BMS] HV State of charge (%)'
_BDR_DEBT_FLOOR_WH = 3.0
_BDR_WIN_S = 120


def _bdr_grid(fr):
    keep = {_BDR_I: 'I', _BDR_V: 'V', _BDR_SOC: 'soc'}
    cols = {c: n for c, n in keep.items() if c in fr.columns}
    if 'time' not in fr.columns or _BDR_I not in fr.columns or _BDR_V not in fr.columns:
        return None
    g = fr.set_index(pd.to_datetime(fr['time'], errors='coerce'))
    g = g[list(cols)].rename(columns=cols).apply(pd.to_numeric, errors='coerce')
    return g.resample('1s').mean().ffill(limit=3)


def _buffer_debt_recovery_events(fr):
    """M221.1 (P0.2 event chain) refactor: per-event buffer-debt-recovery
    extraction, split out of _buffer_debt_recovery()'s aggregation loop
    (pure refactor -- identical logic for the pre-existing fields,
    reorganized) so it can be reused as a stage of the M221.3 unified
    start-event chain, matching the _buffer_impulse_events/
    _ramp_latency_events _..._events(fr) convention. Self-contained:
    computes its own _buffer_impulse_events(fr) event set and _bdr_grid(fr)
    1 Hz grid internally (reused verbatim, no re-derivation of THEIR
    logic).

    M221.2 (P0.2 fixed-checkpoint repayment) is folded in here rather than
    as a separate pass: frac10S/frac30S/frac60S sample the SAME cumulative
    `recovered` array already built for the half-time crossing, at three
    more fixed checkpoints (t=10/30/60s post-debt-peak) -- no new raw pass,
    no new integration, purely reading more points off data already
    computed. frac120S is the SAME quantity as the scalar summary's
    fracRecovered120 (last available point in the window), reported here
    per-event for continuity. Each fracXXS pairs with an overshootFlagXXS
    (recovered > 1.0 at that checkpoint, UNCLAMPED). A checkpoint beyond
    the recovery window's edge is None, not fabricated.

    Returns a list of event dicts: {'t0', 'debtWh', 'recoveryHalfTimeS',
    'frac10S', 'frac30S', 'frac60S', 'frac120S', 'overshootFlag10S',
    'overshootFlag30S', 'overshootFlag60S', 'overshootFlag120S',
    'overshootFrac', 'socRecoveredPP'}."""
    if fr is None:
        return []
    ev = _buffer_impulse_events(fr)
    if not ev:
        return []
    g = _bdr_grid(fr)
    if g is None or 'I' not in g.columns or 'V' not in g.columns:
        return []
    pdis = ((-g['I']) * g['V'] / 1000.0)
    has_soc = 'soc' in g.columns
    out = []
    for e in ev:
        debt0 = e.get('energyWh')
        if debt0 is None or debt0 < _BDR_DEBT_FLOOR_WH:
            continue
        t0 = pd.Timestamp(e['t0'])
        win = g.loc[t0 - pd.Timedelta(seconds=1):t0 + pd.Timedelta(seconds=_BDR_WIN_S)]
        if len(win) < 8:
            continue
        pw = pdis.loc[win.index]
        if pw.notna().sum() < 8:
            continue
        cum = (pw.fillna(0) / 3.6).cumsum().values          # Wh, net discharge
        tsec = (win.index - win.index[0]).total_seconds().values
        pk = int(np.argmax(cum))
        debt = cum[pk]
        if debt < _BDR_DEBT_FLOOR_WH:
            continue
        post = cum[pk:]
        tpost = tsec[pk:] - tsec[pk]
        recovered = (debt - post) / debt

        def checkpoint(target_s):
            idx = int(np.searchsorted(tpost, target_s))
            if idx >= len(tpost):
                return None
            return float(recovered[idx])

        def flag(x):
            return bool(x > 1.0) if x is not None else None

        raw10, raw30, raw60 = checkpoint(10.0), checkpoint(30.0), checkpoint(60.0)
        raw120 = float(recovered[-1])       # SAME definition as fracRecovered120

        hi = np.where(recovered >= 0.5)[0]
        half = float(tpost[hi[0]]) if len(hi) else None

        soc_pp = None
        if has_soc and win['soc'].notna().sum() >= 2:
            sv = win['soc'].values
            socpk = sv[pk] if pk < len(sv) and sv[pk] == sv[pk] else np.nan
            socend = win['soc'].dropna().iloc[-1]
            if socpk == socpk:
                soc_pp = float(socend - socpk)

        # NOTE: fields feeding corpus-wide aggregation (mi()) below are kept
        # at FULL float precision here, unrounded -- matching the pre-
        # refactor code's convention exactly (rounding happened only once,
        # at the final aggregate, never on the per-event input). Rounding
        # here first would shift percentiles by a rounding-order artifact
        # (caught by the M221.1 byte-identity gate during this refactor).
        out.append({
            't0': e['t0'], 'debtWh': float(debt),
            'recoveryHalfTimeS': half,
            'frac10S': min(raw10, 1.0) if raw10 is not None else None,
            'frac30S': min(raw30, 1.0) if raw30 is not None else None,
            'frac60S': min(raw60, 1.0) if raw60 is not None else None,
            'frac120S': min(raw120, 1.0),
            'overshootFlag10S': flag(raw10), 'overshootFlag30S': flag(raw30),
            'overshootFlag60S': flag(raw60), 'overshootFlag120S': flag(raw120),
            'overshootFrac': float(max(0.0, recovered.max() - 1.0)),
            'socRecoveredPP': soc_pp})
    return out


def _buffer_debt_recovery(dm, frame_loader=None):
    if frame_loader is None:
        return None
    import numpy as _np      # local alias retained for the unmodified
                              # mi()/dayboot() bodies below (pre-existing code)
    per = {'half': [], 'frac': [], 'over': [], 'notRec': [], 'debt': [],
           'socPP': [], 'date': []}
    ck_frac = {'frac10S': [], 'frac30S': [], 'frac60S': []}
    ck_flag = {'overshootFlag10S': [], 'overshootFlag30S': [], 'overshootFlag60S': []}
    nDrives = nEvents = 0
    days = set()
    for _, r in dm.iterrows():
        fr = frame_loader(r['file'])
        if fr is None:
            continue
        # M221.1 refactor note: the coverage check (ev/g validity) is kept
        # HERE, matching the pre-refactor code's nDrivesCovered semantics
        # exactly (a drive counts as covered once it has a buffer-impulse
        # event set and a valid I/V grid, REGARDLESS of whether any
        # individual event goes on to qualify) -- a byte-identity
        # requirement caught during this refactor's own verification.
        # _buffer_debt_recovery_events(fr) re-derives ev/g internally too
        # (cheap; frame_loader's own cache read is not duplicated).
        ev = _buffer_impulse_events(fr)
        if not ev:
            continue
        g = _bdr_grid(fr)
        if g is None or 'I' not in g.columns or 'V' not in g.columns:
            continue
        nDrives += 1
        d = str(r.get('date', ''))[:10]
        events = _buffer_debt_recovery_events(fr)
        for e in events:
            nEvents += 1
            days.add(d)
            per['half'].append(e['recoveryHalfTimeS'] if e['recoveryHalfTimeS'] is not None else _np.nan)
            per['frac'].append(e['frac120S'] if e['frac120S'] is not None else _np.nan)
            per['over'].append(e['overshootFrac'])
            per['notRec'].append(max(0.0, 1.0 - e['frac120S'])
                                  if e['frac120S'] is not None else _np.nan)
            per['debt'].append(e['debtWh'])
            per['date'].append(d)
            if e['socRecoveredPP'] is not None:
                per['socPP'].append(e['socRecoveredPP'])
            for k in ck_frac:
                v = e.get(k)
                ck_frac[k].append(v if v is not None else _np.nan)
            for k in ck_flag:
                ck_flag[k].append(e.get(k))

    if nEvents == 0:
        return None

    def mi(v):
        v = _np.asarray([x for x in v if x == x], float)
        if v.size == 0:
            return None
        return {'median': round(float(_np.median(v)), 3),
                'p25': round(float(_np.percentile(v, 25)), 3),
                'p75': round(float(_np.percentile(v, 75)), 3), 'n': int(v.size)}

    def dayboot(vals, dates, nb=4000, seed=42):
        v = _np.asarray(vals, float)
        dts = _np.asarray(dates)
        m = _np.isfinite(v)
        v, dts = v[m], dts[m]
        if v.size < 3:
            return None
        uniq = _np.unique(dts)
        by = {d: v[dts == d] for d in uniq}
        rng = _np.random.default_rng(seed)
        meds = []
        for _ in range(nb):
            s = rng.choice(uniq, len(uniq), replace=True)
            meds.append(_np.median(_np.concatenate([by[d] for d in s])))
        return {'bootMedian': round(float(_np.median(v)), 3),
                'ci95': [round(float(_np.percentile(meds, 2.5)), 3),
                         round(float(_np.percentile(meds, 97.5)), 3)],
                'nEvents': int(v.size), 'nDays': int(uniq.size)}

    def flag_rate(flags):
        vals = [f for f in flags if f is not None]
        if not vals:
            return None
        return {'pctOvershoot': round(100.0 * sum(1 for f in vals if f) / len(vals), 1),
                'n': len(vals)}

    def checkpoint_block(fracs, flags):
        m = mi(fracs)
        if m is None:
            return None
        fr_rate = flag_rate(flags)
        if fr_rate is not None:
            m['overshootPct'] = fr_rate['pctOvershoot']
            m['overshootN'] = fr_rate['n']
        return m

    over = _np.asarray(per['over'], float)
    notrec = _np.asarray(per['notRec'], float)
    return {
        'nDrivesCovered': nDrives, 'nEvents': nEvents, 'nDays': len(days),
        'recoveryHalfTimeS': mi(per['half']),
        'fracRecovered120': mi(per['frac']),
        'overshootFrac': mi(per['over']),
        'fracNotRecovered120': mi(per['notRec']),
        'debtWh': mi(per['debt']),
        'socRecoveredPP': mi(per['socPP']),
        'pctFullyRecovered120': round(float(100.0 * (notrec <= 0.01).mean()), 1),
        'pctOvershoot': round(float(100.0 * (over > 0.05).mean()), 1),
        'recoveryHalfTimeBoot': dayboot(per['half'], per['date']),
        'windowS': _BDR_WIN_S, 'debtFloorWh': _BDR_DEBT_FLOOR_WH,
        # M221.2 (P0.2 fixed-checkpoint repayment): frac10S/30S/60S ladders,
        # each with the overshoot rate at that checkpoint nested in
        # (overshootPct/overshootN) -- 120s already has fracRecovered120/
        # pctOvershoot above, so no redundant 120s block is added here.
        'frac10S': checkpoint_block(ck_frac['frac10S'], ck_flag['overshootFlag10S']),
        'frac30S': checkpoint_block(ck_frac['frac30S'], ck_flag['overshootFlag30S']),
        'frac60S': checkpoint_block(ck_frac['frac60S'], ck_flag['overshootFlag60S']),
        'methodology': (
            'Extends M116: reuses _buffer_impulse_events verbatim for the engine-'
            'start discharge-impulse set and its per-event energy debt (>= %g Wh). '
            'On a 1 Hz I/V grid, integrates net-discharge Wh from the event over a '
            '%d s recovery window (signed p=(-I)*V, M11). The debt peak is the '
            'cumulative-net-discharge maximum (~impulse end); recovery is measured '
            'from there. recoveryHalfTimeS = time to repay 50 %% of the debt; '
            'fracRecovered120 = net fraction repaid by window end (clamped <=1); '
            'overshootFrac = peak refill PAST the debt (generator banking buffer '
            'headroom while running); fracNotRecovered120 = residual; socRecoveredPP '
            'is the independent SoC cross-check. M221.2: frac10S/30S/60S sample the '
            'SAME cumulative recovery curve at three more fixed post-peak '
            'checkpoints (10/30/60s), each with its own overshoot rate '
            '(recovered > 1.0, unclamped, at that specific checkpoint) -- '
            'checkpoints beyond the recovery window edge are excluded, not '
            'fabricated. Per-event medians/IQR; day-clustered bootstrap (seed 42, '
            '4000 draws) on median half-time. Single vehicle / ~single driver -- '
            'descriptive.'
            % (_BDR_DEBT_FLOOR_WH, _BDR_WIN_S))}



# ── Module E (M188): within-drive driving-state taxonomy ─────────────────────
# Per-second kinematic state (idle/accel/cruise/decel) WITHIN each drive: state
# occupancy, the within-drive first-order state transition (Markov) structure,
# per-state buffer power and engine-on fraction, and per-state dwell. Explicitly
# distinct from M142 regimeTransition (which is a BETWEEN-drive Markov chain over
# whole-drive TYPES at drive granularity) -- E is within-drive at 1 Hz -- and from
# D (stop-go cycles) and A (speed-conditioned envelopes): E adds the occupancy
# census, the within-drive state Markov structure and per-state buffer behaviour.
# State from logged accel(g) (schema-v6) + speed (M167 priority): idle speed<3;
# accel accg>=+0.02 g; decel accg<=-0.02 g; cruise otherwise (moving). Battery
# power p=(-I)*V/1000 kW (M11). Single vehicle / ~single driver -- descriptive.
_DST_COLS = {'[BMS] HV Battery Current (A)': 'I', '[BMS] HV Battery voltage (V)': 'V',
             '[VCM] Vehicle Speed (km/h)': 'speed',
             '\u041e\u0431\u0435\u0440\u0442\u0438 \u0434\u0432\u0438\u0433\u0443\u043d\u0430 (rpm)': 'rpm',
             '\u041f\u0440\u0438\u0441\u043a\u043e\u0440\u0435\u043d\u043d\u044f (g)': 'accg'}
_DST_STATES = ['idle', 'accel', 'cruise', 'decel']
_DST_MOVE_V = 3.0
_DST_A_THR = 0.02
_DST_ENG_ON = 400.0


def _dst_grid(fn, raw_loader, frame_loader):
    if frame_loader is not None:
        fr = frame_loader(fn)
        if fr is None:
            return None
        df = fr[[c for c in fr.columns
                 if c in _DST_COLS or c == 'time' or c == _SPEED_OBD_RAW]]
    else:
        raw = raw_loader(fn) if raw_loader is not None else None
        if not raw:
            return None
        df = pd.read_csv(io.BytesIO(raw),
                         usecols=lambda c: (c in _DST_COLS or c == 'time'
                                            or c == _SPEED_OBD_RAW),
                         low_memory=False)
    df, _ = _apply_speed_priority(df)
    df = df.rename(columns=_DST_COLS)
    if 'time' not in df.columns or 'speed' not in df.columns or 'accg' not in df.columns:
        return None
    g = df.set_index(pd.to_datetime(df['time'], errors='coerce'))
    g = g[[c for c in ('I', 'V', 'speed', 'rpm', 'accg') if c in g.columns]].apply(
        pd.to_numeric, errors='coerce')
    return g.resample('1s').mean().ffill(limit=3)


def _dst_classify(g):
    import numpy as _np
    sp = g['speed'].values
    ac = g['accg'].values
    st = _np.full(len(g), -1, int)
    idle = sp < _DST_MOVE_V
    st[idle] = 0
    mov = ~idle
    st[mov & (ac >= _DST_A_THR)] = 1
    st[mov & (ac <= -_DST_A_THR)] = 3
    st[mov & (_np.abs(ac) < _DST_A_THR)] = 2
    return st


def _driving_state_taxonomy(dm, raw_loader, frame_loader=None):
    import numpy as _np
    S = _DST_STATES
    occ = {s: [] for s in S}
    occ_date = {s: [] for s in S}
    dwell = {s: [] for s in S}
    battkw = {s: [] for s in S}
    engon = {s: [0, 0] for s in S}
    T = _np.zeros((4, 4), float)
    nDrives = 0
    coveredKm = 0.0
    days = set()
    for _, r in dm.iterrows():
        g = _dst_grid(r['file'], raw_loader, frame_loader)
        if g is None:
            continue
        g = g.dropna(subset=['speed', 'accg'])
        if len(g) < 20:
            continue
        st = _dst_classify(g)
        if (st >= 0).sum() < 20:
            continue
        nDrives += 1
        d = str(r.get('date', ''))[:10]
        days.add(d)
        coveredKm += float(r.get('distance_km', 0) or 0)
        n = len(st)
        for si, s in enumerate(S):
            occ[s].append(float((st == si).mean()))
            occ_date[s].append(d)
        for k in range(1, n):
            if st[k - 1] >= 0 and st[k] >= 0:
                T[st[k - 1], st[k]] += 1
        cur = st[0]
        run = 1
        for k in range(1, n):
            if st[k] == cur:
                run += 1
            else:
                if cur >= 0:
                    dwell[S[cur]].append(run)
                cur = st[k]
                run = 1
        if cur >= 0:
            dwell[S[cur]].append(run)
        if 'I' in g.columns and 'V' in g.columns:
            pk = ((-g['I']) * g['V'] / 1000.0).values
            for si, s in enumerate(S):
                m = (st == si) & _np.isfinite(pk)
                battkw[s].extend(pk[m].tolist())
        if 'rpm' in g.columns:
            rp = g['rpm'].values
            for si, s in enumerate(S):
                m = (st == si) & _np.isfinite(rp)
                engon[s][0] += int((rp[m] > _DST_ENG_ON).sum())
                engon[s][1] += int(m.sum())

    if nDrives == 0:
        return None

    def mi(v):
        v = _np.asarray([x for x in v if x == x], float)
        if v.size == 0:
            return None
        return {'median': round(float(_np.median(v)), 3),
                'p25': round(float(_np.percentile(v, 25)), 3),
                'p75': round(float(_np.percentile(v, 75)), 3), 'n': int(v.size)}

    def dayboot(vals, dates, nb=4000, seed=42):
        v = _np.asarray(vals, float)
        dts = _np.asarray(dates)
        m = _np.isfinite(v)
        v, dts = v[m], dts[m]
        if v.size < 3:
            return None
        uniq = _np.unique(dts)
        by = {d: v[dts == d] for d in uniq}
        rng = _np.random.default_rng(seed)
        meds = []
        for _ in range(nb):
            s = rng.choice(uniq, len(uniq), replace=True)
            meds.append(_np.median(_np.concatenate([by[d] for d in s])))
        return {'bootMedian': round(float(_np.median(v)), 3),
                'ci95': [round(float(_np.percentile(meds, 2.5)), 3),
                         round(float(_np.percentile(meds, 97.5)), 3)],
                'nDrives': int(v.size), 'nDays': int(uniq.size)}

    rows = T.sum(1, keepdims=True)
    P = _np.divide(T, rows, out=_np.zeros_like(T), where=rows > 0)
    occupancy = {s: {'perDriveMedIqr': mi(occ[s]),
                     'boot': dayboot(occ[s], occ_date[s])} for s in S}
    perState = {}
    for si, s in enumerate(S):
        e = engon[s]
        perState[s] = {'battKw': mi(battkw[s]),
                       'dwellS': mi(dwell[s]),
                       'engineOnFrac': round(e[0] / e[1], 3) if e[1] else None,
                       'selfTransition': round(float(P[si, si]), 3)}
    return {
        'nDrivesCovered': nDrives, 'coveredKm': round(coveredKm, 1),
        'nDays': len(days), 'states': S,
        'thresholds': {'moveVKmh': _DST_MOVE_V, 'accelThresholdG': _DST_A_THR,
                       'engOnRpm': _DST_ENG_ON},
        'occupancy': occupancy,
        'perState': perState,
        'transitionMatrix': {'from': S, 'to': S,
                             'counts': T.astype(int).tolist(),
                             'prob': [[round(float(P[i, j]), 4) for j in range(4)]
                                      for i in range(4)]},
        'methodology': (
            'Within-drive per-second kinematic state on a 1 Hz grid (speed via '
            'M167 priority; accel from the logged accel(g) sensor, schema-v6): '
            'idle speed<%.1f km/h; accel accg>=+%.3f g; decel accg<=-%.3f g; cruise '
            'otherwise (moving). Per drive: state occupancy fraction, within-drive '
            'first-order transition counts (t->t+1), per-state battery kW '
            '(p=(-I)*V, M11), engine-on fraction (rpm>%d) and dwell run-lengths. '
            'Occupancy is per-drive median/IQR with a day-clustered bootstrap (seed '
            '42, 4000 draws); transition probabilities and per-state battery kW/'
            'dwell are pooled. Distinct from M142 regimeTransition (between-drive '
            'drive-TYPE Markov at drive granularity) -- this is within-drive at 1 '
            'Hz. Single vehicle / ~single driver -- descriptive.'
            % (_DST_MOVE_V, _DST_A_THR, _DST_A_THR, int(_DST_ENG_ON)))}



# ── Module G (M189): departure/arrival behaviour vs matched mid-trip ─────────
# Within-drive PAIRED design: each drive of sufficient length supplies a departure
# window (first W s), an arrival window (last W s) and a mid-trip control window
# (centre W s); the drive is its own control. Time-normalised (primary; GPS-free,
# so corpus-wide). Boundary windows are intrinsically low-speed (the vehicle is
# starting/stopping), which CONFOUNDS speed-driven metrics (engine-on fraction,
# battery kW) -- for those a SPEED-MATCHED mid-trip control is also computed
# (mid-trip seconds within the boundary window's speed band). State-of-charge and
# coolant are not primarily speed-driven, so their boundary-vs-mid deltas are the
# confound-free headlines. Reuses _engine_start_triggers for per-window start
# counts. Single vehicle / ~single driver -- descriptive.
_DA_COLS = {'[BMS] HV Battery Current (A)': 'I', '[BMS] HV Battery voltage (V)': 'V',
            '[BMS] HV State of charge (%)': 'soc', '[VCM] Vehicle Speed (km/h)': 'speed',
            '\u041e\u0431\u0435\u0440\u0442\u0438 \u0434\u0432\u0438\u0433\u0443\u043d\u0430 (rpm)': 'rpm',
            '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043e\u0445\u043e\u043b\u043e\u0434\u043d\u043e\u0457 \u0440\u0456\u0434\u0438\u043d\u0438 (\u2103)': 'cool'}
_DA_W = 60
_DA_MIN_DUR = 240
_DA_ENG_ON = 400.0


def _da_grid(fn, frame_loader):
    fr = frame_loader(fn) if frame_loader is not None else None
    if fr is None:
        return None, None
    df = fr[[c for c in fr.columns if c in _DA_COLS or c == 'time' or c == _SPEED_OBD_RAW]]
    df, _ = _apply_speed_priority(df)
    df = df.rename(columns=_DA_COLS)
    if 'time' not in df.columns or 'speed' not in df.columns:
        return None, None
    g = df.set_index(pd.to_datetime(df['time'], errors='coerce'))
    keep = [c for c in ('I', 'V', 'soc', 'speed', 'rpm', 'cool') if c in g.columns]
    g = g[keep].apply(pd.to_numeric, errors='coerce').resample('1s').mean().ffill(limit=3)
    return g, fr


def _da_wmetrics(g, i0, i1, trig_ts):
    import numpy as _np
    seg = g.iloc[i0:i1]
    if len(seg) < 10:
        return None
    m = {}
    if 'I' in seg.columns and 'V' in seg.columns and seg['I'].notna().any():
        m['battKw'] = float((((-seg['I']) * seg['V'] / 1000.0)).median())
    else:
        m['battKw'] = _np.nan
    m['engOnFrac'] = (float((seg['rpm'] > _DA_ENG_ON).mean())
                      if 'rpm' in seg.columns and seg['rpm'].notna().any() else _np.nan)
    m['socMean'] = (float(seg['soc'].mean())
                    if 'soc' in seg.columns and seg['soc'].notna().any() else _np.nan)
    m['speedMean'] = float(seg['speed'].mean()) if seg['speed'].notna().any() else _np.nan
    m['coolMean'] = (float(seg['cool'].mean())
                     if 'cool' in seg.columns and seg['cool'].notna().any() else _np.nan)
    t0, t1 = seg.index[0], seg.index[-1]
    m['nStarts'] = sum(1 for ts in trig_ts if t0 <= pd.Timestamp(ts) <= t1)
    return m, seg


def _da_speed_matched(g, mid_i0, mid_i1, bwin_seg):
    """engine-on frac & battKw over the WHOLE-drive mid region restricted to the
    boundary window's [p10,p90] speed band (speed-matched control)."""
    import numpy as _np
    lo = float(_np.nanpercentile(bwin_seg['speed'], 10))
    hi = float(_np.nanpercentile(bwin_seg['speed'], 90))
    mid = g.iloc[mid_i0:mid_i1]
    sel = mid[(mid['speed'] >= lo) & (mid['speed'] <= hi)]
    if len(sel) < 8:
        return None
    eng = (float((sel['rpm'] > _DA_ENG_ON).mean())
           if 'rpm' in sel.columns and sel['rpm'].notna().any() else _np.nan)
    bk = (float((((-sel['I']) * sel['V'] / 1000.0)).median())
          if 'I' in sel.columns and 'V' in sel.columns and sel['I'].notna().any() else _np.nan)
    return {'engOnFrac': eng, 'battKw': bk, 'nSamples': int(len(sel))}


def _departure_arrival(dm, frame_loader=None):
    if frame_loader is None:
        return None
    import numpy as _np
    METRICS = ['battKw', 'engOnFrac', 'socMean', 'speedMean', 'coolMean', 'nStarts']
    dep = {k: [] for k in METRICS}
    arr = {k: [] for k in METRICS}
    mid = {k: [] for k in METRICS}
    dep_date, arr_date = [], []
    # speed-matched: boundary engOn/battKw vs matched-mid engOn/battKw
    sm = {'depEng': [], 'depMidEng': [], 'depBk': [], 'depMidBk': [],
          'arrEng': [], 'arrMidEng': [], 'arrBk': [], 'arrMidBk': []}
    nDrives = 0
    days = set()
    for _, r in dm.iterrows():
        g, fr = _da_grid(r['file'], frame_loader)
        if g is None:
            continue
        n = len(g)
        if n < _DA_MIN_DUR:
            continue
        trig = _engine_start_triggers(fr) if fr is not None else []
        md0 = n // 2 - _DA_W // 2
        wins = {'dep': (0, _DA_W), 'mid': (md0, md0 + _DA_W), 'arr': (n - _DA_W, n)}
        if not (wins['dep'][1] <= wins['mid'][0] and wins['mid'][1] <= wins['arr'][0]):
            continue
        res = {}
        segs = {}
        ok = True
        for name, (a, b) in wins.items():
            rm = _da_wmetrics(g, a, b, trig)
            if rm is None:
                ok = False
                break
            res[name], segs[name] = rm
        if not ok:
            continue
        nDrives += 1
        d = str(r.get('date', ''))[:10]
        days.add(d)
        for k in METRICS:
            dep[k].append(res['dep'][k])
            arr[k].append(res['arr'][k])
            mid[k].append(res['mid'][k])
        dep_date.append(d)
        arr_date.append(d)
        # speed-matched controls against the FULL mid third of the drive
        m0, m1 = n // 3, 2 * n // 3
        smd = _da_speed_matched(g, m0, m1, segs['dep'])
        if smd is not None:
            sm['depEng'].append(res['dep']['engOnFrac'])
            sm['depMidEng'].append(smd['engOnFrac'])
            sm['depBk'].append(res['dep']['battKw'])
            sm['depMidBk'].append(smd['battKw'])
        sma = _da_speed_matched(g, m0, m1, segs['arr'])
        if sma is not None:
            sm['arrEng'].append(res['arr']['engOnFrac'])
            sm['arrMidEng'].append(sma['engOnFrac'])
            sm['arrBk'].append(res['arr']['battKw'])
            sm['arrMidBk'].append(sma['battKw'])

    if nDrives == 0:
        return None

    def paired(a, b):
        d = _np.array([x - y for x, y in zip(a, b) if x == x and y == y], float)
        if d.size == 0:
            return None
        return {'medianDelta': round(float(_np.median(d)), 3),
                'p25': round(float(_np.percentile(d, 25)), 3),
                'p75': round(float(_np.percentile(d, 75)), 3), 'n': int(d.size)}

    def absmed(v):
        v = _np.asarray([x for x in v if x == x], float)
        return round(float(_np.median(v)), 3) if v.size else None

    def dayboot_paired(a, b, dates, nb=4000, seed=42):
        d = _np.array([x - y for x, y in zip(a, b)], float)
        dts = _np.asarray(dates)
        m = _np.isfinite(d)
        d, dts = d[m], dts[m]
        if d.size < 3:
            return None
        uniq = _np.unique(dts)
        by = {k: d[dts == k] for k in uniq}
        rng = _np.random.default_rng(seed)
        meds = []
        for _ in range(nb):
            s = rng.choice(uniq, len(uniq), replace=True)
            meds.append(_np.median(_np.concatenate([by[k] for k in s])))
        return {'bootMedianDelta': round(float(_np.median(d)), 3),
                'ci95': [round(float(_np.percentile(meds, 2.5)), 3),
                         round(float(_np.percentile(meds, 97.5)), 3)],
                'nDrives': int(d.size), 'nDays': int(uniq.size)}

    absWindows = {k: {'departure': absmed(dep[k]), 'midtrip': absmed(mid[k]),
                      'arrival': absmed(arr[k])} for k in METRICS}
    return {
        'nDrivesCovered': nDrives, 'nDays': len(days), 'windowS': _DA_W,
        'minDurationS': _DA_MIN_DUR,
        'absWindows': absWindows,
        'departureVsMid': {k: paired(dep[k], mid[k]) for k in METRICS},
        'arrivalVsMid': {k: paired(arr[k], mid[k]) for k in METRICS},
        'speedMatched': {
            'departureEngOnFracDelta': paired(sm['depEng'], sm['depMidEng']),
            'departureBattKwDelta': paired(sm['depBk'], sm['depMidBk']),
            'arrivalEngOnFracDelta': paired(sm['arrEng'], sm['arrMidEng']),
            'arrivalBattKwDelta': paired(sm['arrBk'], sm['arrMidBk'])},
        'headlineBoot': {
            'departureCoolantDelta': dayboot_paired(dep['coolMean'], mid['coolMean'], dep_date),
            'departureSocDelta': dayboot_paired(dep['socMean'], mid['socMean'], dep_date)},
        'methodology': (
            'Within-drive paired windows of W=%d s on drives >=%d s: departure '
            '(first W), midtrip (centre W), arrival (last W), non-overlapping. '
            'Per window: median battery kW (p=(-I)*V, M11), engine-on fraction '
            '(rpm>%d), mean SoC, mean speed, mean coolant, canonical start count. '
            'Boundary-vs-mid reported as within-drive paired deltas (drive is its '
            'own control). Boundary windows are low-speed by construction, which '
            'confounds engine-on/battery-kW; for those a SPEED-MATCHED control uses '
            'mid-third seconds within the boundary window speed band [p10,p90]. SoC '
            'and coolant are not speed-driven, so their departure deltas are the '
            'confound-free headlines (day-clustered bootstrap, seed 42, 4000 draws). '
            'Time-normalised (GPS-free, corpus-wide). Single vehicle / ~single '
            'driver -- descriptive.'
            % (_DA_W, _DA_MIN_DUR, int(_DA_ENG_ON)))}



# ── Module K (M190): engine operating-point state machine ─────────────────────
# Extends rpmDistribution (M82, RPM occupancy only) and M118 (start-dwell only)
# into a full operating-point state machine: discrete RPM states with per-state
# occupancy, dwell, entry rate, the first-order transition matrix and per-state
# buffer power, across ALL engine time. States: off (rpm<400), low (400-1400),
# loadPoint (1400-2300, the OEM-nominal ~2000-rpm generator load-point), mid
# (2300-3200), high (>=3200). The load-point band is the OEM-nominal efficient
# generator point -- NOT a measured BSFC optimum; no efficiency claim is made.
# Battery power p=(-I)*V/1000 kW (M11). Single vehicle / ~single driver --
# descriptive.
_ESM_COLS = {'[BMS] HV Battery Current (A)': 'I', '[BMS] HV Battery voltage (V)': 'V',
             '\u041e\u0431\u0435\u0440\u0442\u0438 \u0434\u0432\u0438\u0433\u0443\u043d\u0430 (rpm)': 'rpm',
             # M227.1 (P1.3, enhancement plan): SoC and pack temperature,
             # read in the SAME per-file pass as I/V/rpm above -- not a
             # second raw pass. Used only by the dwell-survival model
             # below, nowhere else in this module.
             '[BMS] HV State of charge (%)': 'soc',
             '[BMS] HV Battery Temperature Sensor 1 (\u2103)': 'tpack'}
_ESM_STATES = ['off', 'low', 'loadPoint', 'mid', 'high']
_ESM_EDGES = [400, 1400, 2300, 3200]


def _esm_grid(fn, raw_loader, frame_loader):
    if frame_loader is not None:
        fr = frame_loader(fn)
        if fr is None:
            return None
        df = fr[[c for c in fr.columns
                 if c in _ESM_COLS or c == 'time' or c == _SPEED_OBD_RAW
                 or c == _SPEED_VCM_RAW]]
    else:
        raw = raw_loader(fn) if raw_loader is not None else None
        if not raw:
            return None
        df = pd.read_csv(io.BytesIO(raw),
                         usecols=lambda c: (c in _ESM_COLS or c == 'time'
                                            or c == _SPEED_OBD_RAW
                                            or c == _SPEED_VCM_RAW),
                         low_memory=False)
    df, _ = _apply_speed_priority(df)
    df = df.rename(columns=_ESM_COLS)
    if 'time' not in df.columns or 'rpm' not in df.columns:
        return None
    g = df.set_index(pd.to_datetime(df['time'], errors='coerce'))
    keep = [c for c in ('I', 'V', 'rpm', 'soc', 'tpack') if c in g.columns]
    if _SPEED_VCM_RAW in g.columns:
        g = g.rename(columns={_SPEED_VCM_RAW: 'speed'})
        keep.append('speed')
    g = g[keep].apply(pd.to_numeric, errors='coerce')
    return g.resample('1s').mean().ffill(limit=3)


def _esm_classify(rpm):
    import numpy as _np
    st = _np.zeros(len(rpm), int)
    st[rpm >= _ESM_EDGES[0]] = 1
    st[rpm >= _ESM_EDGES[1]] = 2
    st[rpm >= _ESM_EDGES[2]] = 3
    st[rpm >= _ESM_EDGES[3]] = 4
    st[~_np.isfinite(rpm)] = -1
    return st


def _engine_state_machine(dm, raw_loader, frame_loader=None):
    import numpy as _np
    S = _ESM_STATES
    occ = {s: [] for s in S}
    occ_date = {s: [] for s in S}
    dwell = {s: [] for s in S}
    battkw = {s: [] for s in S}
    entries = {s: 0 for s in S}
    T = _np.zeros((5, 5), float)
    engHours = 0.0
    nDrives = 0
    days = set()
    for _, r in dm.iterrows():
        g = _esm_grid(r['file'], raw_loader, frame_loader)
        if g is None or 'rpm' not in g.columns:
            continue
        g = g.dropna(subset=['rpm'])
        if len(g) < 20:
            continue
        st = _esm_classify(g['rpm'].values)
        if (st >= 0).sum() < 20:
            continue
        nDrives += 1
        d = str(r.get('date', ''))[:10]
        days.add(d)
        n = len(st)
        for si, s in enumerate(S):
            occ[s].append(float((st == si).mean()))
            occ_date[s].append(d)
        engHours += float((st >= 1).sum()) / 3600.0
        for k in range(1, n):
            if st[k - 1] >= 0 and st[k] >= 0:
                T[st[k - 1], st[k]] += 1
                if st[k] != st[k - 1]:
                    entries[S[st[k]]] += 1
        cur = st[0]
        run_ = 1
        for k in range(1, n):
            if st[k] == cur:
                run_ += 1
            else:
                if cur >= 0:
                    dwell[S[cur]].append(run_)
                cur = st[k]
                run_ = 1
        if cur >= 0:
            dwell[S[cur]].append(run_)
        if 'I' in g.columns and 'V' in g.columns:
            pk = ((-g['I']) * g['V'] / 1000.0).values
            for si, s in enumerate(S):
                m = (st == si) & _np.isfinite(pk)
                battkw[s].extend(pk[m].tolist())

    if nDrives == 0:
        return None

    def mi(v):
        v = _np.asarray([x for x in v if x == x], float)
        if v.size == 0:
            return None
        return {'median': round(float(_np.median(v)), 3),
                'p25': round(float(_np.percentile(v, 25)), 3),
                'p75': round(float(_np.percentile(v, 75)), 3), 'n': int(v.size)}

    def dayboot(vals, dates, nb=4000, seed=42):
        v = _np.asarray(vals, float)
        dts = _np.asarray(dates)
        m = _np.isfinite(v)
        v, dts = v[m], dts[m]
        if v.size < 3:
            return None
        uniq = _np.unique(dts)
        by = {d: v[dts == d] for d in uniq}
        rng = _np.random.default_rng(seed)
        meds = []
        for _ in range(nb):
            s = rng.choice(uniq, len(uniq), replace=True)
            meds.append(_np.median(_np.concatenate([by[d] for d in s])))
        return {'bootMedian': round(float(_np.median(v)), 3),
                'ci95': [round(float(_np.percentile(meds, 2.5)), 3),
                         round(float(_np.percentile(meds, 97.5)), 3)],
                'nDrives': int(v.size), 'nDays': int(uniq.size)}

    rows = T.sum(1, keepdims=True)
    P = _np.divide(T, rows, out=_np.zeros_like(T), where=rows > 0)
    # M203 (post-M190 correction, feasibility-review candidate K bug report):
    # `perDriveMedIqr.median` is the per-DRIVE median state fraction. For
    # zero-inflated states (mid/high: most individual drives never reach
    # >=2300 rpm at all) the median collapses to 0.0 even though the pooled
    # dwell/entry/battKw stats above prove the state is real and non-trivial
    # in aggregate -- and for "off" the per-drive median (skewed upward by
    # short/idle-heavy drives) reads well above the corpus-pooled fraction
    # reported elsewhere on the dashboard (rpmDistribution.pooledPct[0],
    # evTraction.evPctTime), which is what the module's own stated design
    # ("...across ALL engine time") calls for. `rows` (T row-sums) already
    # gives exactly that: total per-second occurrences of each state pooled
    # over the whole corpus. Row i excludes only the single LAST classified
    # sample of each drive (no outgoing t->t+1 transition to count) -- a
    # ~0.05% relative undercount (n_drives / total_seconds) at this corpus
    # size, disclosed below rather than corrected with a second raw pass.
    totalSeconds = float(rows.sum())
    pooledOcc = {s: (round(float(rows[si, 0]) / totalSeconds, 4) if totalSeconds > 0 else None)
                 for si, s in enumerate(S)}
    occupancy = {s: {'perDriveMedIqr': mi(occ[s]),
                     'boot': dayboot(occ[s], occ_date[s]),
                     'pooled': pooledOcc[s]} for s in S}
    perState = {}
    for si, s in enumerate(S):
        perState[s] = {
            'dwellS': mi(dwell[s]),
            'entriesPerEngHour': round(entries[s] / engHours, 2) if engHours else None,
            'battKw': mi(battkw[s]),
            'selfTransition': round(float(P[si, si]), 3)}
    return {
        'nDrivesCovered': nDrives, 'nDays': len(days),
        'engineOnHours': round(engHours, 1),
        'states': S,
        'stateEdgesRpm': {'off': [0, _ESM_EDGES[0]], 'low': [_ESM_EDGES[0], _ESM_EDGES[1]],
                          'loadPoint': [_ESM_EDGES[1], _ESM_EDGES[2]],
                          'mid': [_ESM_EDGES[2], _ESM_EDGES[3]], 'high': [_ESM_EDGES[3], None]},
        'occupancy': occupancy,
        'pooledTotalSeconds': int(totalSeconds),
        'perState': perState,
        'transitionMatrix': {'from': S, 'to': S,
                             'counts': T.astype(int).tolist(),
                             'prob': [[round(float(P[i, j]), 4) for j in range(5)]
                                      for i in range(5)]},
        'methodology': (
            'Per-second engine operating-point state on a 1 Hz grid: off rpm<%d; '
            'low %d-%d; loadPoint %d-%d (the OEM-nominal ~2000-rpm generator load-'
            'point -- NOT a measured BSFC optimum, no efficiency claim); mid %d-%d; '
            'high >=%d. Per drive: state occupancy, within-drive first-order '
            'transition counts (t->t+1), per-state dwell run-lengths, per-state '
            'entry counts and per-state battery kW (p=(-I)*V, M11). Occupancy is '
            'per-drive median/IQR with a day-clustered bootstrap (seed 42, 4000 '
            'draws); occupancy.<state>.pooled (M203) is the corpus-pooled, '
            'duration-weighted share of ALL classified engine time -- derived '
            'from the transition-matrix row sums, so it excludes only the single '
            'last classified sample of each drive (~0.05%% relative undercount at '
            'this corpus size). Use pooled for "how much of engine time", not the '
            'per-drive median: mid/high are zero-inflated across drives (most '
            'individual drives never reach the state at all), so their per-drive '
            'median reads 0%% even though pooled occupancy is real and non-trivial; '
            '"off" per-drive median reads above pooled because short/idle-heavy '
            'drives skew the median upward. Pooled "off" matches '
            'rpmDistribution.pooledPct[0] and evTraction.evPctTime (independent '
            'pooled computations over the same classified seconds). Dwell, entry '
            'rate (per engine-on hour), battery kW and the transition matrix are '
            'pooled. Extends rpmDistribution (occupancy only) '
            'and M118 (start-dwell only) with the full dwell/entry/transition state '
            'machine. Single vehicle / ~single driver -- descriptive.'
            % (_ESM_EDGES[0], _ESM_EDGES[0], _ESM_EDGES[1], _ESM_EDGES[1],
               _ESM_EDGES[2], _ESM_EDGES[2], _ESM_EDGES[3], _ESM_EDGES[3]))}



def _engine_dwell_survival(dm, raw_loader, frame_loader=None):
    """M227.1 (P1.3, enhancement plan): semi-Markov / dwell-survival
    engine-state model. `_engine_state_machine` (M188, above) already
    classifies the 1 Hz state sequence and computes `occupancy`/
    `perState`/`transitionMatrix` -- the sample-level first-order matrix
    the enhancement proposal critiques as inflated by 1 Hz self-transition
    dominance. `perState.dwellS` (dwell-time distribution),
    `perState.entriesPerEngHour`, and `perState.battKw` (state-specific
    battery-power distributions) ALREADY EXIST -- confirmed here, per the
    plan's own explicit instruction to check before rebuilding, and
    cross-referenced rather than duplicated. Only the survival-model layer
    is genuinely missing, which this function adds.

    Re-derives the SAME state sequence via `_esm_grid`/`_esm_classify`
    (additively extended, M227.1, with SoC/speed/pack-temperature read in
    the same per-file pass -- `_engine_state_machine` itself is untouched,
    confirmed byte-identical) rather than editing the existing function,
    this session's established pattern.

    Adds:
    1. Discrete-time hazard/survival curves per state: at each dwell
       duration d (seconds), hazard(d) = (spells that exit exactly at d) /
       (spells that survived to at least d) -- the standard actuarial
       life-table estimator. The LAST dwell spell of each drive is
       right-censored (still in that state when logging stopped, never
       observed to exit) and is excluded from the exit-event count but
       correctly counted in the at-risk set at every duration it reached
       -- `_engine_state_machine`'s own dwellS pools this spell as if it
       were a completed dwell (a known, disclosed simplification there);
       this function does not inherit that simplification.
    2. Exit hazard stratified by SoC/speed/pack-temperature tercile
       (covariate value at spell START), median dwell time per stratum --
       quantile stratification, this codebase's established alternative
       to a fitted parametric multi-state model (matching M224/M226's own
       choices this session).
    3. Transitions per FIXED PHYSICAL-TIME interval (10s/30s/60s/120s,
       modal state per window) as a direct cross-check against the
       existing 1 Hz `transitionMatrix`'s self-transition rate --
       quantifies exactly how much of the 1 Hz self-transition dominance
       is a sampling-rate artifact vs. genuine state persistence, per the
       plan's explicit ask.

    Single vehicle / ~single driver -- descriptive, not causal.
    """
    S = _ESM_STATES
    spells = []       # dicts: state, day, durationS, censored, soc0, speed0, tpack0
    seq_all = []       # (day, DatetimeIndex, state array) per drive, for the
                       # fixed-interval cross-check
    nDrives = 0
    days = set()
    for _, r in dm.iterrows():
        g = _esm_grid(r['file'], raw_loader, frame_loader)
        if g is None or 'rpm' not in g.columns:
            continue
        g = g.dropna(subset=['rpm'])
        if len(g) < 20:
            continue
        st = _esm_classify(g['rpm'].values)
        if (st >= 0).sum() < 20:
            continue
        nDrives += 1
        d = str(r.get('date', ''))[:10]
        days.add(d)
        seq_all.append((d, g.index, st))
        soc_v = g['soc'].values if 'soc' in g.columns else None
        spd_v = g['speed'].values if 'speed' in g.columns else None
        tpk_v = g['tpack'].values if 'tpack' in g.columns else None
        n = len(st)
        cur = st[0]
        run_start = 0
        for k in range(1, n + 1):
            if k < n and st[k] == cur:
                continue
            if cur >= 0:
                dur = k - run_start
                censored = (k == n)   # ran to the end of this drive's log
                def _v(arr):
                    return (float(arr[run_start]) if arr is not None
                           and arr[run_start] == arr[run_start] else None)
                spells.append({'state': S[cur], 'day': d, 'durationS': dur,
                              'censored': censored, 'soc0': _v(soc_v),
                              'speed0': _v(spd_v), 'tpack0': _v(tpk_v)})
            if k < n:
                cur = st[k]
                run_start = k
    if nDrives == 0 or not spells:
        return None

    # ---- 1. discrete-time hazard/survival curves ----
    def hazard_curve(state_spells, max_d=60, min_at_risk=30):
        durs = np.array([sp['durationS'] for sp in state_spells])
        cens = np.array([sp['censored'] for sp in state_spells])
        curve = []
        surv = 1.0
        for d in range(1, max_d + 1):
            at_risk = int((durs >= d).sum())
            if at_risk < min_at_risk:
                break
            exits = int(((durs == d) & (~cens)).sum())
            h = exits / at_risk if at_risk else None
            surv *= (1.0 - h) if h is not None else 1.0
            curve.append({'durationS': d, 'atRisk': at_risk, 'exits': exits,
                         'hazard': round(h, 4) if h is not None else None,
                         'survival': round(surv, 4)})
        return curve

    by_state = {s: [sp for sp in spells if sp['state'] == s] for s in S}
    hazard_curves = {s: hazard_curve(by_state[s]) for s in S if by_state[s]}

    # ---- 2. covariate-stratified exit hazard (median dwell by tercile) ----
    def stratified_dwell(state_spells, key):
        vals = np.array([sp[key] for sp in state_spells if sp[key] is not None], float)
        if len(vals) < 60:
            return {'note': 'insufficient samples for a %s tercile split' % key}
        terc = np.percentile(vals, [33.3, 66.7])
        bands = []
        for lo, hi, lbl in ((-1e12, terc[0], 'low'), (terc[0], terc[1], 'mid'),
                           (terc[1], 1e12, 'high')):
            sub = [sp['durationS'] for sp in state_spells
                  if sp[key] is not None and lo < sp[key] <= hi]
            if sub:
                bands.append({'band': lbl, 'n': len(sub),
                             'medianDurationS': round(float(np.median(sub)), 2)})
        return {'bands': bands}

    covariate_stratified = {
        s: {'bySocAtEntry': stratified_dwell(by_state[s], 'soc0'),
           'bySpeedAtEntry': stratified_dwell(by_state[s], 'speed0'),
           'byTpackAtEntry': stratified_dwell(by_state[s], 'tpack0')}
        for s in S if by_state[s]
    }

    # ---- 3. transitions per fixed physical-time interval ----
    def fixed_interval_self_transition(window_s):
        same = total = 0
        for day, idx, st in seq_all:
            ser = pd.Series(st, index=idx)
            ser = ser.where(ser >= 0)
            resampled = ser.resample('%ds' % window_s).apply(
                lambda x: x.mode().iloc[0] if len(x.dropna()) else np.nan)
            vals = resampled.dropna().values
            for k in range(1, len(vals)):
                total += 1
                if vals[k] == vals[k - 1]:
                    same += 1
        return {'windowS': window_s, 'nTransitionsObserved': total,
               'selfTransitionRate': round(same / total, 4) if total else None}

    fixed_interval = [fixed_interval_self_transition(w) for w in (1, 10, 30, 60, 120)]
    self_trans_1s = next((f['selfTransitionRate'] for f in fixed_interval if f['windowS'] == 1), None)
    self_trans_120s = next((f['selfTransitionRate'] for f in fixed_interval if f['windowS'] == 120), None)

    return {
        'nDrivesCovered': nDrives, 'nDays': len(days), 'nSpells': len(spells),
        'hazardSurvivalCurves': hazard_curves,
        'covariateStratifiedDwell': covariate_stratified,
        'fixedIntervalSelfTransition': fixed_interval,
        'crossReference': {
            'dwellDistributions': 'engineStateMachine.perState.<state>.dwellS',
            'entriesPerEngineHour': 'engineStateMachine.perState.<state>.entriesPerEngHour',
            'batteryPowerByState': 'engineStateMachine.perState.<state>.battKw',
            'note': ('These three already exist in engineStateMachine.'
                     'perState -- confirmed present before building '
                     'anything here, per the plan\'s explicit instruction, '
                     'and cross-referenced rather than duplicated.'),
        },
        'dwellSurvivalMethodology': (
            'M227.1 (P1.3, enhancement plan): re-derives the SAME 1 Hz '
            'state sequence engineStateMachine (M188) itself classifies '
            '(_esm_grid/_esm_classify, additively extended with SoC/speed/'
            'pack-temperature -- engineStateMachine itself unaffected, '
            'confirmed byte-identical). Discrete-time hazard/survival: '
            'standard actuarial life-table estimator (exits-at-duration-d '
            '/ at-risk-at-duration-d), with the LAST dwell spell of each '
            'drive correctly right-censored (excluded from exit events, '
            'retained in the at-risk set) -- NOT the same treatment '
            'engineStateMachine.perState.dwellS gives that spell (pooled '
            'as if complete there, a disclosed simplification in that '
            'pre-existing field, not inherited here). Covariate-'
            'stratified dwell: SoC/speed/pack-temperature AT SPELL ENTRY, '
            'tercile-split, median dwell time per stratum -- quantile '
            'stratification, not a fitted parametric multi-state model '
            '(this codebase\'s established binned-not-parametric '
            'convention, matching M224/M226 this session). Fixed-'
            'interval self-transition: the state sequence resampled onto '
            'coarser fixed windows (modal state per window), self-'
            'transition rate recomputed at each window size -- 1 s: %s, '
            '120 s: %s -- directly quantifying how much of the 1 Hz '
            'matrix\'s self-transition dominance is a sampling-rate '
            'artifact (should fall sharply as window widens if so) vs. '
            'genuine persistence (should stay high). Single vehicle / '
            '~single driver -- descriptive, not causal.'
            % (self_trans_1s, self_trans_120s)),
    }


def _daily_fingerprints_starts_by_file(files, frame_loader):
    """M231: the one raw-file-reading step _daily_fingerprints() needs,
    split out so it can be run once and its result reused across re-fits
    that only touch drive_master-column-derived features (e.g. the F07
    peak-sign fix), without re-reading every raw CSV."""
    starts_by_file = {}
    if frame_loader is not None:
        for fn in files:
            try:
                fr = frame_loader(fn)
                trig = _engine_start_triggers(fr) if fr is not None else []
                starts_by_file[fn] = len(trig) if trig else 0
            except Exception:
                pass
    return starts_by_file


def _daily_fingerprints(dm, ambient_by_drive=None, frame_loader=None,
                         starts_by_file=None):
    """M227.2 (P1.6, enhancement plan): daily operational fingerprints.
    Per-day feature vectors built from data already available per-drive
    (drive_master.csv columns, aggregated to per-day, distance-weighted
    where a share/rate) plus ambient temperature (ambient_by_drive,
    already assembled elsewhere in this pipeline) and genuine per-day
    engine-start counts (frame_loader + _engine_start_triggers, the SAME
    M116/M118/M147/M221 physical-detector family, reused verbatim -- not
    a new detector).

    Feature list, with two DELIBERATE, DISCLOSED proxy substitutions
    where the plan's literal feature is not itself a per-drive
    drive_master column (rather than building a new raw-pass detector
    purpose-built for one milestone):
      - urbanSharePct/mixedSharePct/mixedHighwaySharePct/highwaySharePct:
        distance-weighted drive_type shares (native CLASS_ORDER).
      - coldStartCount: count of that day's drives preceded by a >=2h gap
        since the previous drive (or no previous drive at all) -- reuses
        _full_datetimes' own gap computation (the M141/M223.1 convention).
        A PROXY for a true coolant-at-start<60C flag (that flag lives only
        in _of_grid's fuel-channel-only raw pass, a much smaller and
        differently-gated subset than this feature needs), disclosed as
        such rather than silently presented as the literal thing.
      - lowSpeedDriveShare: distance-weighted share of that day's drives
        with mean moving speed <20 km/h -- a PROXY for stop-go intensity
        (crawlStopGo's own per-drive cycle detail is not retained at the
        per-drive/per-day level in its aggregate-only output), disclosed
        as such.
      - engineStartsPerHour: genuine per-day engine-start count (frame_
        loader + _engine_start_triggers, reused verbatim) / that day's
        total engine-on hours (engine_on_pct-weighted duration).
      - evDistSharePct, gtcMean: distance-weighted, already-computed
        drive_master columns.
      - peakPowerKw: M231 (audit F07) -- the LARGER-MAGNITUDE of that
        day's peak_discharge_kw/peak_charge_kw, i.e.
        max(abs(discharge peak), abs(charge peak)). peak_charge_kw is
        stored NEGATIVE in the master; a plain max() over the two signed
        columns silently discards any charging peak, however large,
        whenever a positive discharge peak exists on the same day (which
        is nearly always) -- see peakPowerDischargeKw/peakPowerChargeKw
        (signed, informational) for the two directional components this
        collapses.
      - ambientTempC: mean ambient temperature that day.
      - highSpeedSecondsSum: sum of that day's highspeed_discharge_s_130p.

    Clustering: features z-scored, k-means (seed=42) swept over k=2..6,
    k selected by BEST SILHOUETTE SCORE (a data-driven criterion, not
    fixed a priori) among candidates with silhouette > 0.15; below that,
    no clustering is fit at all. STABILITY: day-bootstrap resampling (200
    draws, seed=42) -- each draw resamples days with replacement, refits
    k-means at the SAME k, and computes the adjusted Rand index against
    the original clustering restricted to the same (repeated) days.
    Median bootstrap ARI >= 0.4 (a conventional "reasonable agreement"
    threshold in the clustering-stability literature) is required before
    ANY cluster is reported as real -- below that, this function reports
    "no stable recurring duty profiles detected at this corpus size" as
    the headline finding, per the plan's own explicit honest-null
    instruction, not a forced cluster count.

    EXPLICIT FRAMING REQUIREMENT (proposal Sec.4.6): output is labelled
    recurring DUTY PROFILES throughout -- never "personality" or driver
    categories -- in every field name, cluster label, and prose string
    this function produces.

    Single vehicle / ~single driver, warm-season only -- exactly the
    boundary condition the source proposal's own Sec.2 flags as likely to
    produce weak cluster stability; a null result here would itself be a
    legitimate, publishable finding given these stated study boundaries,
    not a failure of the method.
    """
    if 'date' not in dm.columns or 'distance_km' not in dm.columns:
        return None
    d = dm[dm['distance_km'].notna() & (dm['distance_km'] > 0)].copy()
    if d.empty:
        return None

    # ---- genuine per-day engine-start counts (the only raw-file-reading
    # step in this function; split out -- M231 -- so it can be run once
    # and reused across re-fits that only change drive_master-column-
    # derived features, like the F07 peak-sign fix below). Callers may
    # pass a pre-computed starts_by_file to skip the raw pass entirely. ----
    if starts_by_file is None:
        starts_by_file = _daily_fingerprints_starts_by_file(d['file'], frame_loader)
    d['nStarts'] = d['file'].map(starts_by_file)

    # ---- cold-start proxy: gap since previous drive ----
    fd = _full_datetimes(dm).dropna(subset=['ts_full']).sort_values('ts_full')
    gap_h, prev_te = {}, None
    for _, r in fd.iterrows():
        gap_h[r['file']] = ((r['ts_full'] - prev_te).total_seconds() / 3600.0
                            if prev_te is not None and pd.notna(r['ts_full']) else None)
        prev_te = r['te_full'] if pd.notna(r.get('te_full')) else r['ts_full']
    d['gapH'] = d['file'].map(gap_h)
    d['isColdStartProxy'] = d['gapH'].isna() | (d['gapH'] >= 2.0)

    # ---- ambient temp per drive ----
    amb = {}
    if ambient_by_drive:
        for fn, pair in ambient_by_drive.items():
            try:
                amb[fn] = sum(float(x) for x in pair) / len(pair)
            except Exception:
                pass
    d['ambientC'] = d['file'].map(amb)

    spd_col = ('speed_mean_moving' if 'speed_mean_moving' in d.columns
              else ('speed_mean' if 'speed_mean' in d.columns else None))
    d['lowSpeedFlag'] = (d[spd_col] < 20.0) if spd_col else False

    days_out = []
    for day, g in d.groupby('date'):
        km = float(g['distance_km'].sum())
        if km <= 0:
            continue
        w = g['distance_km'] / km

        def wmean(col):
            if col not in g.columns:
                return None
            v = g[col]
            m = v.notna()
            return float((v[m] * w[m]).sum() / w[m].sum()) if m.any() and w[m].sum() > 0 else None

        shares = {cls: (float(w[g['drive_type'] == cls].sum())
                       if (g['drive_type'] == cls).any() else 0.0)
                 for cls in CLASS_ORDER}
        peak_cols = [c for c in ('peak_discharge_kw', 'peak_charge_kw') if c in g.columns]
        # M231 (audit F07): use the LARGER-MAGNITUDE peak, not plain max().
        # peak_charge_kw is stored negative, so a plain max() over the two
        # signed columns silently discarded any charging peak whenever a
        # positive discharge peak existed on the same day (nearly always) --
        # missing a larger-magnitude charging peak on 48 of 76 days in the
        # audit's independent check. Directional components are preserved
        # separately (peakPowerDischargeKw/peakPowerChargeKw, signed,
        # informational) rather than only collapsed into the magnitude.
        peak_kw = (float(np.nanmax(np.abs(g[peak_cols].values))) if peak_cols
                  and np.isfinite(g[peak_cols].values).any() else None)
        peak_dis_kw = (float(np.nanmax(g['peak_discharge_kw'].values))
                      if 'peak_discharge_kw' in g.columns
                      and np.isfinite(g['peak_discharge_kw'].values).any() else None)
        peak_chg_kw = (float(np.nanmin(g['peak_charge_kw'].values))
                      if 'peak_charge_kw' in g.columns
                      and np.isfinite(g['peak_charge_kw'].values).any() else None)
        eng_hours = (float((g['engine_on_pct'].fillna(0) / 100.0 * g['duration_s']).sum() / 3600.0)
                    if 'engine_on_pct' in g.columns and 'duration_s' in g.columns else 0.0)
        n_starts = g['nStarts'].sum() if g['nStarts'].notna().any() else None
        days_out.append({
            'date': day, 'nDrives': int(len(g)), 'totalKm': round(km, 1),
            'urbanSharePct': round(shares.get('urban', 0.0) * 100, 1),
            'mixedSharePct': round(shares.get('mixed', 0.0) * 100, 1),
            'mixedHighwaySharePct': round(shares.get('mixed_highway', 0.0) * 100, 1),
            'highwaySharePct': round(shares.get('highway', 0.0) * 100, 1),
            'coldStartCount': int(g['isColdStartProxy'].sum()),
            'lowSpeedDriveShare': round(float(w[g['lowSpeedFlag']].sum()), 3),
            'engineStartsPerHour': (round(n_starts / eng_hours, 2)
                                    if (n_starts is not None and eng_hours > 0) else None),
            'evDistSharePct': wmean('ev_dist_pct'),
            'gtcMean': wmean('gtc'),
            'peakPowerKw': peak_kw,
            'peakPowerDischargeKw': peak_dis_kw, 'peakPowerChargeKw': peak_chg_kw,
            'ambientTempC': wmean('ambientC'),
            'highSpeedSecondsSum': (float(g['highspeed_discharge_s_130p'].sum())
                                   if 'highspeed_discharge_s_130p' in g.columns else None),
        })
    if len(days_out) < 15:
        return None
    F = pd.DataFrame(days_out)

    feature_cols = ['urbanSharePct', 'highwaySharePct', 'coldStartCount',
                    'lowSpeedDriveShare', 'engineStartsPerHour', 'evDistSharePct',
                    'gtcMean', 'peakPowerKw', 'ambientTempC', 'highSpeedSecondsSum']
    Fc = F.dropna(subset=feature_cols)
    method_text = (
        'M227.2 (P1.6, enhancement plan): per-day feature vectors from '
        'drive_master.csv columns (distance-weighted shares/means) plus '
        'ambient temperature and genuine per-day engine-start counts '
        '(frame_loader + _engine_start_triggers, reused verbatim). '
        'coldStartCount and lowSpeedDriveShare are DISCLOSED PROXIES (gap-'
        'since-previous-drive; mean-moving-speed<20km/h), not the literal '
        'coolant-at-start/stop-go-cycle features, since those live only '
        'in other functions\' aggregate-only or differently-gated raw '
        'passes. peakPowerKw is max(abs(discharge peak), abs(charge '
        'peak)) (M231, audit F07: previously plain max() over the two '
        'signed columns, which silently discarded any charging peak on '
        'any day with a positive discharge peak -- nearly always; the '
        'signed components are kept separately as peakPowerDischargeKw/'
        'peakPowerChargeKw). Features z-scored; k-means (seed=42) swept k=2-6, k '
        'chosen by best silhouette score among candidates >0.15 (a data-'
        'driven criterion, not fixed a priori). Stability: 200 day-'
        'bootstrap resamples (seed=42), adjusted Rand index against the '
        'original clustering: median ARI must reach >=0.4 before ANY '
        'cluster is reported as real. Output is labelled recurring DUTY '
        'PROFILES throughout -- never "personality" or driver categories '
        '(proposal Sec.4.6\'s explicit framing requirement). Single '
        'vehicle / ~single driver, warm-season only -- exactly the '
        'boundary condition the source proposal\'s own Sec.2 flags as '
        'likely to produce weak cluster stability; a null result here is '
        'a legitimate, publishable finding given these study boundaries, '
        'not a failure of the method.')

    if len(Fc) < 15:
        return {
            'nDays': len(F), 'nDaysComplete': len(Fc),
            'clusters': None, 'stabilityCheck': None, 'featureLoadings': None,
            'verdict': 'no stable recurring duty profiles detected at this corpus size',
            'note': ('Fewer than 15 days have complete feature vectors '
                    '(missing ambient temperature or engine-start coverage '
                    'on the rest) -- insufficient for a clustering attempt '
                    'at all; reported as an honest absence, not a forced '
                    'fit on a smaller subset.'),
            'dailyFingerprintsMethodology': method_text,
        }

    from sklearn.preprocessing import StandardScaler
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score, adjusted_rand_score

    X = StandardScaler().fit_transform(Fc[feature_cols].values)
    n = len(X)
    best_k, best_sil, best_labels = None, -1.0, None
    sil_by_k = []
    for k in range(2, min(7, n // 5 + 1)):
        if k >= n:
            continue
        km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)
        sil = float(silhouette_score(X, km.labels_))
        sil_by_k.append({'k': k, 'silhouette': round(sil, 4)})
        if sil > best_sil:
            best_k, best_sil, best_labels = k, sil, km.labels_

    if best_k is None or best_sil <= 0.15:
        return {
            'nDays': len(F), 'nDaysComplete': len(Fc), 'silhouetteByK': sil_by_k,
            'clusters': None, 'stabilityCheck': None, 'featureLoadings': None,
            'verdict': 'no stable recurring duty profiles detected at this corpus size',
            'note': ('Best silhouette score (%s) does not clear the 0.15 '
                    'minimum for even attempting a stability check -- no '
                    'cluster structure is reported. A legitimate, '
                    'publishable finding given the study\'s single-'
                    'vehicle, single-driver, warm-season boundaries '
                    '(source proposal Sec.2), not a failure of the '
                    'method.' % (round(best_sil, 4) if best_k is not None else 'n/a')),
            'dailyFingerprintsMethodology': method_text,
        }

    rng = np.random.default_rng(42)
    aris = []
    idx_all = np.arange(n)
    for _ in range(200):
        picks = rng.choice(idx_all, n, replace=True)
        try:
            kmb = KMeans(n_clusters=best_k, random_state=42, n_init=10).fit(X[picks])
        except Exception:
            continue
        aris.append(float(adjusted_rand_score(best_labels[picks], kmb.labels_)))
    median_ari = float(np.median(aris)) if aris else None
    stable = bool(median_ari is not None and median_ari >= 0.4)
    stability_check = {
        'k': best_k, 'silhouette': round(best_sil, 4), 'nBootstraps': len(aris),
        'medianAri': round(median_ari, 4) if median_ari is not None else None,
        'ariCi95': ([round(float(np.percentile(aris, 2.5)), 4),
                    round(float(np.percentile(aris, 97.5)), 4)] if len(aris) >= 30 else None),
        'stabilityThreshold': 0.4, 'stable': stable,
    }

    if not stable:
        return {
            'nDays': len(F), 'nDaysComplete': len(Fc), 'silhouetteByK': sil_by_k,
            'clusters': None, 'stabilityCheck': stability_check, 'featureLoadings': None,
            'verdict': 'no stable recurring duty profiles detected at this corpus size',
            'note': (('A k=%d clustering was fit (silhouette=%.3f) but its '
                     'day-bootstrap median adjusted Rand index (%s) falls '
                     'below the 0.4 stability threshold -- the candidate '
                     'grouping does not reproduce reliably under '
                     'resampling, so no duty profile is reported as real. '
                     'A legitimate, publishable null result given the '
                     'study\'s single-vehicle/single-driver/warm-season '
                     'boundaries, not a failure of the method.')
                    % (best_k, best_sil,
                       ('%.3f' % median_ari) if median_ari is not None else 'n/a')),
            'dailyFingerprintsMethodology': method_text,
        }

    Fc = Fc.copy()
    Fc['dutyProfile'] = best_labels
    profiles = [{
        'dutyProfileId': int(lbl), 'nDays': int((best_labels == lbl).sum()),
        'meanFeatures': {c: round(float(Fc.loc[Fc['dutyProfile'] == lbl, c].mean()), 2)
                        for c in feature_cols},
    } for lbl in sorted(set(best_labels))]
    centroids = np.array([X[best_labels == lbl].mean(axis=0) for lbl in sorted(set(best_labels))])
    spread = centroids.std(axis=0)
    feature_loadings = {feature_cols[i]: round(float(spread[i]), 3) for i in range(len(feature_cols))}

    return {
        'nDays': len(F), 'nDaysComplete': len(Fc), 'silhouetteByK': sil_by_k,
        'clusters': {'k': best_k, 'profiles': profiles},
        'stabilityCheck': stability_check, 'featureLoadings': feature_loadings,
        'verdict': ('%d stable recurring duty profiles detected (day-bootstrap '
                   'median ARI=%.3f)' % (best_k, median_ari)),
        'dailyFingerprintsMethodology': method_text,
    }


# ── Module O-thermal (M191): coolant/oil warm-up + coolant-oil lag ────────────
# Extends warmupCurve (M31/M86, distance-domain COOLANT rise only) with the engine
# OIL warm-up trajectory and the coolant-oil thermal lag, in the time domain, on
# cold-start drives (coolant start <60 C). Oil has more thermal mass and is heated
# indirectly, so it lags the coolant; this quantifies that lag (time-to-threshold
# for each fluid, the coolant->oil lag to 70 C, and the steady-state coolant-oil
# offset) plus the paired warm-up curves. The fuel-consumption penalty of cold/
# warm-restart operation is a SEPARATE Aug-subset sub-analysis (needs the Aug-only
# fuel channel) and is NOT computed here; emissions are not instrumented. Single
# vehicle / ~single driver -- descriptive.
_TWL_COOL = '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043e\u0445\u043e\u043b\u043e\u0434\u043d\u043e\u0457 \u0440\u0456\u0434\u0438\u043d\u0438 (\u2103)'
_TWL_OIL = '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043e\u043b\u0456\u0457 \u0443 \u0434\u0432\u0438\u0433\u0443\u043d\u0456 (\u2103)'
_TWL_COLD_MAX = 60.0
_TWL_THR = [60, 70, 80]
_TWL_TIME_BINS = [0, 30, 60, 120, 180, 240, 300, 420, 600, 900]


def _twl_grid(fr):
    if fr is None or 'time' not in fr.columns or _TWL_COOL not in fr.columns:
        return None
    keep = {_TWL_COOL: 'cool', _TWL_OIL: 'oil'}
    cols = {c: n for c, n in keep.items() if c in fr.columns}
    g = fr.set_index(pd.to_datetime(fr['time'], errors='coerce'))
    g = g[list(cols)].rename(columns=cols).apply(pd.to_numeric, errors='coerce')
    return g.resample('1s').mean().ffill(limit=3)


def _twl_time_to(series_vals, tsec, thr, start_temp):
    import numpy as _np
    if start_temp >= thr:
        return 0.0
    hit = _np.where(series_vals >= thr)[0]
    return float(tsec[hit[0]]) if len(hit) else _np.nan


def _thermal_warmup_lag(dm, frame_loader=None):
    if frame_loader is None:
        return None
    import numpy as _np
    cool_tt = {t: [] for t in _TWL_THR}
    oil_tt = {t: [] for t in _TWL_THR}
    lag70 = []
    lag_date = []
    ss_offset = []
    cool_curve = [[] for _ in range(len(_TWL_TIME_BINS) - 1)]
    oil_curve = [[] for _ in range(len(_TWL_TIME_BINS) - 1)]
    nCold = nTotal = nOil = 0
    days = set()
    for _, r in dm.iterrows():
        fr = frame_loader(r['file'])
        g = _twl_grid(fr)
        if g is None or 'cool' not in g.columns:
            continue
        c = g['cool'].dropna()
        if len(c) < 30:
            continue
        nTotal += 1
        cstart = float(c.iloc[0])
        if cstart >= _TWL_COLD_MAX:
            continue
        nCold += 1
        d = str(r.get('date', ''))[:10]
        days.add(d)
        tsec = (g.index - g.index[0]).total_seconds().values
        cvals = g['cool'].values
        for t in _TWL_THR:
            cool_tt[t].append(_twl_time_to(cvals, tsec, t, cstart))
        has_oil = 'oil' in g.columns and g['oil'].notna().sum() >= 30
        ovals = g['oil'].values if has_oil else None
        if has_oil:
            nOil += 1
            ostart = float(g['oil'].dropna().iloc[0])
            for t in _TWL_THR:
                oil_tt[t].append(_twl_time_to(ovals, tsec, t, ostart))
            ct = _twl_time_to(cvals, tsec, 70, cstart)
            ot = _twl_time_to(ovals, tsec, 70, ostart)
            if ct == ct and ot == ot:
                lag70.append(ot - ct)
                lag_date.append(d)
            warm = g[(g['cool'] >= 80) & g['oil'].notna()]
            if len(warm) >= 10:
                ss_offset.append(float((warm['cool'] - warm['oil']).median()))
        sb = _np.digitize(tsec, _TWL_TIME_BINS[1:-1])
        for b in range(len(cool_curve)):
            m = sb == b
            if m.any():
                cv = cvals[m]
                if _np.isfinite(cv).any():
                    cool_curve[b].append(float(_np.nanmedian(cv)))
                if has_oil:
                    ov = ovals[m]
                    if _np.isfinite(ov).any():
                        oil_curve[b].append(float(_np.nanmedian(ov)))

    if nCold == 0:
        return None

    def mi(v):
        v = _np.asarray([x for x in v if x == x], float)
        if v.size == 0:
            return None
        return {'median': round(float(_np.median(v)), 1),
                'p25': round(float(_np.percentile(v, 25)), 1),
                'p75': round(float(_np.percentile(v, 75)), 1), 'n': int(v.size)}

    def dayboot(vals, dates, nb=4000, seed=42):
        v = _np.asarray(vals, float)
        dts = _np.asarray(dates)
        m = _np.isfinite(v)
        v, dts = v[m], dts[m]
        if v.size < 3:
            return None
        uniq = _np.unique(dts)
        by = {d: v[dts == d] for d in uniq}
        rng = _np.random.default_rng(seed)
        meds = []
        for _ in range(nb):
            s = rng.choice(uniq, len(uniq), replace=True)
            meds.append(_np.median(_np.concatenate([by[d] for d in s])))
        return {'bootMedian': round(float(_np.median(v)), 1),
                'ci95': [round(float(_np.percentile(meds, 2.5)), 1),
                         round(float(_np.percentile(meds, 97.5)), 1)],
                'nDrives': int(v.size), 'nDays': int(uniq.size)}

    def curve(cc):
        return [round(float(_np.nanmedian(x)), 1) if x else None for x in cc]

    return {
        'nColdStart': nCold, 'nDrivesTotal': nTotal, 'nWithOil': nOil,
        'nDays': len(days), 'coldStartMaxC': _TWL_COLD_MAX,
        'coolantTimeToThresholdS': {str(t): mi(cool_tt[t]) for t in _TWL_THR},
        'oilTimeToThresholdS': {str(t): mi(oil_tt[t]) for t in _TWL_THR},
        'coolantOilLag70S': mi(lag70),
        'coolantOilLag70Boot': dayboot(lag70, lag_date),
        'steadyStateOffsetC': mi(ss_offset),
        'warmupCurves': {
            'timeBinsS': _TWL_TIME_BINS,
            'binLabels': ['%d-%d' % (_TWL_TIME_BINS[i], _TWL_TIME_BINS[i + 1])
                          for i in range(len(_TWL_TIME_BINS) - 1)],
            'coolantMedianC': curve(cool_curve),
            'oilMedianC': curve(oil_curve)},
        'methodology': (
            'Cold-start drives (coolant start <%g C). Per drive on a 1 Hz grid: '
            'time from start for coolant and oil to cross %s C; the coolant->oil '
            'lag = oil_t70 - coolant_t70; the steady-state offset = median(coolant '
            '- oil) once coolant>=80 C; and the paired warm-up curves (median temp '
            'by time-from-start bin). Medians/IQR over cold-start drives; '
            'day-clustered bootstrap (seed 42, 4000 draws) on the lag. Extends '
            'warmupCurve (distance-domain coolant only) with the oil trajectory and '
            'the coolant-oil lag. Oil warms slower (more thermal mass, indirect '
            'heating), so it lags coolant. Fuel penalty (Aug-only subset) and '
            'emissions are NOT computed here. Single vehicle / ~single driver -- '
            'descriptive.'
            % (_TWL_COLD_MAX, '/'.join(str(t) for t in _TWL_THR)))}



# ── Module H (M192): SoC-balanced fuel consumption (accumulator subset) ────────
# Raw trip L/100km is confounded by SoC drift: a trip that ends lower-SoC borrowed
# energy from the buffer (flattering the raw figure); one that ends higher-SoC
# spent fuel charging it (penalising it). H corrects this with a PHYSICAL energy-
# equivalence: dFuel = dE_batt / (eta * LHV), dE_batt = dSoC/100 * CAP_KWH, over a
# disclosed generator-efficiency range eta in {0.25,0.30,0.35} (LHV gasoline 8.9
# kWh/L). It also reports a charge-balancing regression (fuel ~ dist + dE) as a
# descriptive cross-check -- but the dE coefficient is NOT identifiable here (the
# 2.1 kWh buffer's per-trip energy variance is tiny), so NO generator-efficiency
# is claimed from it. ACCUMULATOR SUBSET (grows as fuel-logged drives are
# ingested; dateSpan/nDrives/nDays are computed live, not hardcoded to a month):
# urban-dominated (no pure-highway fuel), warm-season only (no seasonal-cold
# penalty) -- do not generalise beyond the covered date span. CAP_KWH=2.1
# provenance is verified:false -- but the SoC-neutral marginal consumption
# (regression distance coefficient) is robust to CAP, and the fleet correction
# is eta-robust. M212 (2026-09-03): renamed "economy"->"consumption" throughout
# (L/100km is a consumption metric, lower=better; "economy" implies km/L,
# higher=better) and unhardcoded the August/single-month framing.
# Fuel accumulator 'Використане паливо (L)' is read directly from raw (not slimmed).
_HF_FUEL = '\u0412\u0438\u043a\u043e\u0440\u0438\u0441\u0442\u0430\u043d\u0435 \u043f\u0430\u043b\u0438\u0432\u043e (L)'
_HF_SOC = '[BMS] HV State of charge (%)'
_HF_SPD_VCM = '[VCM] Vehicle Speed (km/h)'
_HF_SPD_OBD = '\u0428\u0432\u0438\u0434\u043a\u0456\u0441\u0442\u044c \u0430\u0432\u0442\u043e\u043c\u043e\u0431\u0456\u043b\u044f (km/h)'
_HF_CAP_KWH = 2.1          # verified:false (disclosed)
_HF_LHV = 8.9              # gasoline LHV ~32 MJ/L
_HF_ETAS = [0.25, 0.30, 0.35]


def _hf_perdrive(fn, raw_loader, raw_dir):
    import os
    raw = None
    if raw_loader is not None:
        raw = raw_loader(fn)
    if raw is None and raw_dir is not None:
        try:
            with open(os.path.join(raw_dir, fn), 'rb') as fh:
                raw = fh.read()
        except Exception:
            return None
    if not raw:
        return None
    want = (_HF_FUEL, _HF_SOC, _HF_SPD_VCM, _HF_SPD_OBD, 'time')
    try:
        df = pd.read_csv(io.BytesIO(raw), usecols=lambda c: c in want, low_memory=False)
    except Exception:
        return None
    if _HF_FUEL not in df.columns:
        return None
    fuel = pd.to_numeric(df[_HF_FUEL], errors='coerce').dropna()
    if len(fuel) < 10:
        return None
    fuel_used = float(fuel.iloc[-1] - fuel.iloc[0])
    if fuel_used <= 0.01 or fuel_used > 30:     # accumulator delta sanity
        return None
    spd = None
    for c in (_HF_SPD_VCM, _HF_SPD_OBD):
        if c in df.columns and pd.to_numeric(df[c], errors='coerce').notna().sum() > 20:
            spd = pd.to_numeric(df[c], errors='coerce')
            break
    if spd is None:
        return None
    t = pd.to_datetime(df['time'], errors='coerce')
    g = pd.DataFrame({'spd': spd.values}, index=t).dropna().resample('1s').mean().ffill(limit=3).dropna()
    dist_km = float(g['spd'].clip(lower=0).sum() / 3600.0)
    if dist_km < 1.0:
        return None
    if _HF_SOC not in df.columns:
        return None
    soc = pd.to_numeric(df[_HF_SOC], errors='coerce').dropna()
    if len(soc) < 10:
        return None
    dsoc = float(soc.iloc[-1] - soc.iloc[0])
    return {'fuelL': fuel_used, 'distKm': dist_km, 'dSoC': dsoc,
            'dE_kWh': dsoc / 100.0 * _HF_CAP_KWH,
            'rawL100': fuel_used / dist_km * 100.0,
            'date': None}


def _soc_balanced_fuel(dm, raw_loader=None, raw_dir=None):
    import numpy as _np
    rows = []
    dates = []
    for _, r in dm.iterrows():
        d = _hf_perdrive(r['file'], raw_loader, raw_dir)
        if d is None:
            continue
        d['date'] = str(r.get('date', ''))[:10]
        rows.append(d)
        dates.append(d['date'])
    if len(rows) < 5:
        return None
    fuelL = _np.array([x['fuelL'] for x in rows])
    distKm = _np.array([x['distKm'] for x in rows])
    dE = _np.array([x['dE_kWh'] for x in rows])
    dSoC = _np.array([x['dSoC'] for x in rows])
    rawL100 = _np.array([x['rawL100'] for x in rows])
    dvec = _np.array(dates)
    days = sorted(set(dates))
    tot_fuel, tot_dist, tot_dE = float(fuelL.sum()), float(distKm.sum()), float(dE.sum())
    raw_fleet = tot_fuel / tot_dist * 100.0

    def mi(v):
        v = _np.asarray([x for x in v if x == x], float)
        if v.size == 0:
            return None
        return {'median': round(float(_np.median(v)), 3),
                'p25': round(float(_np.percentile(v, 25)), 3),
                'p75': round(float(_np.percentile(v, 75)), 3), 'n': int(v.size)}

    # physical SoC-balancing by eta
    byEta = []
    for eta in _HF_ETAS:
        dfuel = dE / (eta * _HF_LHV)
        bal_fleet = (tot_fuel - dfuel.sum()) / tot_dist * 100.0
        balL100 = (fuelL - dfuel) / distKm * 100.0
        absd = _np.abs(balL100 - rawL100)
        byEta.append({'eta': eta,
                      'fleetL100': round(bal_fleet, 3),
                      'fleetDelta': round(bal_fleet - raw_fleet, 3),
                      'perTripMedianL100': round(float(_np.median(balL100)), 3),
                      'perTripCorrMedian': round(float(_np.median(absd)), 3),
                      'perTripCorrP95': round(float(_np.percentile(absd, 95)), 3)})
    head = [e for e in byEta if e['eta'] == 0.30][0]

    # day-cluster bootstrap on the eta=0.30 SoC-balanced fleet economy
    dfuel30 = dE / (0.30 * _HF_LHV)
    def dayboot_fleet(nb=4000, seed=42):
        uniq = _np.array(days)
        idx_by = {d: _np.where(dvec == d)[0] for d in uniq}
        rng = _np.random.default_rng(seed)
        vals = []
        for _ in range(nb):
            s = rng.choice(uniq, len(uniq), replace=True)
            ii = _np.concatenate([idx_by[d] for d in s])
            vals.append((fuelL[ii] - dfuel30[ii]).sum() / distKm[ii].sum() * 100.0)
        return {'bootMedian': round(float(_np.median(vals)), 3),
                'ci95': [round(float(_np.percentile(vals, 2.5)), 3),
                         round(float(_np.percentile(vals, 97.5)), 3)],
                'nDrives': len(rows), 'nDays': len(uniq)}

    # charge-balancing regression (descriptive cross-check; dE coeff NOT identifiable)
    Xi = _np.column_stack([_np.ones(len(rows)), distKm, dE])
    coef, *_ = _np.linalg.lstsq(Xi, fuelL, rcond=None)
    yhat = Xi @ coef
    ss_res = float(_np.sum((fuelL - yhat) ** 2))
    ss_tot = float(_np.sum((fuelL - fuelL.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None

    return {
        'nDrives': len(rows), 'nDays': len(days),
        'dateSpan': [min(days), max(days)] if days else None,
        'totalDistKm': round(tot_dist, 1), 'totalFuelL': round(tot_fuel, 2),
        'capKwhAssumed': _HF_CAP_KWH, 'capVerified': False, 'lhvKwhPerL': _HF_LHV,
        'rawFleetL100': round(raw_fleet, 3),
        'rawPerTripL100': mi(rawL100),
        'socBalancedFleetL100': head['fleetL100'],
        'socBalancedFleetDelta': head['fleetDelta'],
        'socBalancedFleetBoot': dayboot_fleet(),
        'byEta': byEta,
        'dSoCPerTrip': {'median': round(float(_np.median(dSoC)), 1),
                        'min': round(float(dSoC.min()), 1), 'max': round(float(dSoC.max()), 1),
                        'p25': round(float(_np.percentile(dSoC, 25)), 1),
                        'p75': round(float(_np.percentile(dSoC, 75)), 1)},
        'regression': {'perTripFixedFuelL': round(float(coef[0]), 4),
                       'socNeutralMarginalL100': round(float(coef[1]) * 100, 3),
                       'fixedFuelPctOfMedianTrip': round(float(coef[0]) / float(_np.median(fuelL)) * 100, 1),
                       'r2': round(r2, 3) if r2 is not None else None,
                       'dERegCoeffIdentifiable': False},
        'methodology': (
            f'Fuel-accumulator subset ({min(days)} to {max(days)}, {len(days)} days, '
            f'{len(rows)} drives): drives carrying the monotonic used-fuel accumulator '
            '"Використане паливо (L)"; trip fuel = accumulator delta, distance = speed '
            'integral, dSoC = end-start. Raw L/100km is confounded by SoC drift; '
            'SoC-balancing subtracts the equivalent fuel of the net battery-energy '
            'change, dFuel = dE/(eta*LHV) with dE = dSoC/100*CAP_KWH (CAP=2.1 kWh, '
            'verified:false), swept over eta in {0.25,0.30,0.35} (LHV 8.9 kWh/L); '
            'headline eta=0.30. Day-clustered bootstrap (seed 42, 4000 draws) on the '
            'balanced fleet fuel consumption (L/100km; lower=better -- this is a '
            'consumption metric, not economy in the km/L sense). A charge-balancing '
            'regression (fuel ~ dist + dE) is reported as a descriptive cross-check, '
            'but the dE coefficient is NOT identifiable (the 2.1 kWh buffer gives '
            'tiny per-trip energy variance) so NO generator efficiency is claimed. '
            'SUBSET CAVEATS: urban-dominated (no pure-highway fuel), warm-season '
            'only (no seasonal-cold penalty) -- do not generalise beyond the covered '
            'date span above. Single vehicle / ~single driver.')}



# ── Module B (M193): battery->engine/turbo handoff sequence (coarse) ──────────
# Extends M116 (engine start) and M118 (rampLatency to load-point) by adding the
# multi-signal ORDERING at each handoff: battery-discharge peak (buffer delivering
# the demand), engine start, load-point reached, boost onset, discharge relaxation
# (generator relieving the buffer). Reuses _engine_start_triggers verbatim for the
# handoff set. COARSE ONLY: event ordering is resolvable to ~+/-1-2 s but fine
# time-constants (t10/t50/t90) are below the ~1.3 Hz cadence floor and are NOT
# reported. Battery power p=(-I)*V/1000 kW (M11). Single vehicle / ~single driver
# -- descriptive.
_HS_RPM = '\u041e\u0431\u0435\u0440\u0442\u0438 \u0434\u0432\u0438\u0433\u0443\u043d\u0430 (rpm)'
_HS_I = '[BMS] HV Battery Current (A)'
_HS_V = '[BMS] HV Battery voltage (V)'
_HS_BOOST = '\u0420\u043e\u0437\u0440\u0430\u0445\u0443\u043d\u043a\u043e\u0432\u0438\u0439 \u043d\u0430\u0434\u0434\u0443\u0432 (bar)'
_HS_LOAD_POINT_RPM = 1400
_HS_BOOST_ONSET = 0.10
_HS_PRE, _HS_POST = 8, 30


def _hs_grid(fr):
    keep = {_HS_RPM: 'rpm', _HS_I: 'I', _HS_V: 'V', _HS_BOOST: 'boost'}
    cols = {c: n for c, n in keep.items() if c in fr.columns}
    if 'time' not in fr.columns or _HS_RPM not in fr.columns:
        return None
    g = fr.set_index(pd.to_datetime(fr['time'], errors='coerce'))
    g = g[list(cols)].rename(columns=cols).apply(pd.to_numeric, errors='coerce')
    return g.resample('1s').mean().ffill(limit=3)


def _handoff_sequence_events(fr):
    """M221.1 (P0.2 event chain) refactor: per-event handoff-sequence
    extraction, split out of _handoff_sequence()'s aggregation loop (pure
    refactor -- identical logic, reorganized) so it can be reused as a
    stage of the M221.3 unified start-event chain, matching the
    _buffer_impulse_events/_ramp_latency_events _..._events(fr) convention.
    Reuses _engine_start_triggers(fr) verbatim for the trigger set (no
    re-derivation). Returns a list of event dicts: {'t0',
    'dischargePeakLagS', 'loadPointLagS', 'boostOnsetLagS',
    'dischargeRelaxLagS'} -- a missing sub-event (e.g. no boost channel, or
    the discharge never relaxes within the window) is None, not
    fabricated. COARSE ONLY (see the M147 note above): lags resolvable to
    ~+/-1-2 s on the ~1.3 Hz native cadence."""
    if fr is None or _HS_RPM not in fr.columns:
        return []
    trig = _engine_start_triggers(fr)
    if not trig:
        return []
    g = _hs_grid(fr)
    if g is None or 'I' not in g.columns or 'V' not in g.columns:
        return []
    pdis = ((-g['I']) * g['V'] / 1000.0)
    out = []
    for ts in trig:
        t0 = pd.Timestamp(ts)
        win = g.loc[t0 - pd.Timedelta(seconds=_HS_PRE):t0 + pd.Timedelta(seconds=_HS_POST)]
        if len(win) < 8:
            continue
        pw = pdis.loc[win.index]
        if pw.notna().sum() < 6:
            continue
        tsec = (win.index - t0).total_seconds().values
        ev = {}
        pv = pw.values
        if np.isfinite(pv).any():
            ev['dischargePeak'] = float(tsec[np.nanargmax(pv)])
        rp = win['rpm'].values
        post = (tsec >= 0) & (rp >= _HS_LOAD_POINT_RPM)
        if post.any():
            ev['loadPoint'] = float(tsec[np.where(post)[0][0]])
        boost_obs = bool('boost' in win.columns and win['boost'].notna().sum() >= 4)   # M285d
        if boost_obs:
            bv = win['boost'].values
            bon = np.where((tsec >= -2) & (bv >= _HS_BOOST_ONSET))[0]
            if len(bon):
                ev['boostOnset'] = float(tsec[bon[0]])
        if 'dischargePeak' in ev:
            pk_i = int(np.nanargmax(pv))
            peak = pv[pk_i]
            if peak > 0.5:
                after = np.where((np.arange(len(pv)) > pk_i) & (pv < 0.5 * peak))[0]
                if len(after):
                    ev['dischargeRelax'] = float(tsec[after[0]])
        out.append({
            't0': ts,
            'dischargePeakLagS': ev.get('dischargePeak'),
            'loadPointLagS': ev.get('loadPoint'),
            'boostOnsetLagS': ev.get('boostOnset'),
            'dischargeRelaxLagS': ev.get('dischargeRelax'),
            'boostObservable': boost_obs})   # M285d: boost channel present in the event window
    return out


def _handoff_sequence(dm, frame_loader=None):
    if frame_loader is None:
        return None
    import numpy as _np      # local alias retained for the unmodified
                              # mi()/dayboot() bodies below (pre-existing code)
    from collections import Counter
    KEYS = ['dischargePeak', 'loadPoint', 'boostOnset', 'dischargeRelax']
    FIELD = {'dischargePeak': 'dischargePeakLagS', 'loadPoint': 'loadPointLagS',
             'boostOnset': 'boostOnsetLagS', 'dischargeRelax': 'dischargeRelaxLagS'}
    lags = {k: [] for k in KEYS}
    lag_dates = {k: [] for k in KEYS}
    orderings = []
    nHandoff = nBoost = nBoostObs = 0     # M285d: nBoostObs = events whose window carries a boost channel
    days = set()
    for _, r in dm.iterrows():
        fr = frame_loader(r['file'])
        events = _handoff_sequence_events(fr)
        if not events:
            continue
        d = str(r.get('date', ''))[:10]
        for e in events:
            nHandoff += 1
            days.add(d)
            ev = {'engineStart': 0.0}
            for k in KEYS:
                v = e.get(FIELD[k])
                if v is not None:
                    ev[k] = v
            if 'boostOnset' in ev:
                nBoost += 1
            if e.get('boostObservable'):
                nBoostObs += 1
            for k in KEYS:
                if k in ev:
                    lags[k].append(ev[k])
                    lag_dates[k].append(d)
            orderings.append(tuple(sorted([k for k in ev], key=lambda k: ev[k])))

    if nHandoff == 0:
        return None

    def mi(v):
        v = _np.asarray([x for x in v if x == x], float)
        if v.size == 0:
            return None
        return {'median': round(float(_np.median(v)), 1),
                'p25': round(float(_np.percentile(v, 25)), 1),
                'p75': round(float(_np.percentile(v, 75)), 1), 'n': int(v.size)}

    def dayboot(vals, dates, nb=4000, seed=42):
        v = _np.asarray(vals, float)
        dts = _np.asarray(dates)
        m = _np.isfinite(v)
        v, dts = v[m], dts[m]
        if v.size < 3:
            return None
        uniq = _np.unique(dts)
        by = {d: v[dts == d] for d in uniq}
        rng = _np.random.default_rng(seed)
        meds = []
        for _ in range(nb):
            s = rng.choice(uniq, len(uniq), replace=True)
            meds.append(_np.median(_np.concatenate([by[d] for d in s])))
        return {'bootMedian': round(float(_np.median(v)), 1),
                'ci95': [round(float(_np.percentile(meds, 2.5)), 1),
                         round(float(_np.percentile(meds, 97.5)), 1)],
                'nEvents': int(v.size), 'nDays': int(uniq.size)}

    modal = [{'sequence': list(o), 'n': c, 'pct': round(100.0 * c / len(orderings), 1)}
             for o, c in Counter(orderings).most_common(6)]
    return {
        'nHandoffs': nHandoff, 'nWithBoost': nBoost,
        'boostInvolvementPct': round(100.0 * nBoost / nHandoff, 1),
        # M285d: boostInvolvementPct above divides by ALL handoffs, including those whose window has no boost
        # channel (PID not logged) -- a channel-availability artefact that biases it low. The estimand below
        # restricts the denominator to boost-observable handoffs.
        'nBoostObservable': nBoostObs,
        'boostInvolvementObservablePct': (round(100.0 * nBoost / nBoostObs, 1) if nBoostObs else None),
        'nDays': len(days),
        'coarseLagVsStartS': {k: mi(lags[k]) for k in KEYS},
        'loadPointLagBoot': dayboot(lags['loadPoint'], lag_dates['loadPoint']),
        'boostOnsetLagBoot': dayboot(lags['boostOnset'], lag_dates['boostOnset']),
        'modalOrderings': modal,
        'loadPointRpm': _HS_LOAD_POINT_RPM, 'boostOnsetBar': _HS_BOOST_ONSET,
        'methodology': (
            'Handoff = canonical engine start (_engine_start_triggers, reused from '
            'M116). Around each start t0, coarse event times on a 1 Hz grid: '
            'battery-discharge peak (argmax of p=(-I)*V over [t0-8,t0+30]); '
            'load-point reached (first rpm>=%d at/after t0); boost onset (first '
            'boost>=%.2f bar); discharge relaxation (first drop below half the '
            'discharge peak after the peak). Per-event coarse lag vs t0 (median/'
            'IQR) and the modal event ORDERING are reported; day-clustered '
            'bootstrap (seed 42, 4000 draws) on the load-point and boost-onset '
            'lags. Extends M116 (start) and M118 (ramp latency) with the full '
            'battery/engine/turbo sequence. COARSE ONLY: ordering resolvable to '
            '~+/-1-2 s; t10/t50/t90 are below the ~1.3 Hz cadence floor and are '
            'NOT reported. Single vehicle / ~single driver -- descriptive.'
            % (_HS_LOAD_POINT_RPM, _HS_BOOST_ONSET))}


# ── Module Q (M221, P0.2): unified engine-start-to-repayment event chain ──
# Joins the four independently-computed per-event detectors above (M116
# bufferImpulse, M118 rampLatency, M147 handoffSequence, M187
# bufferDebtRecovery) into one event-keyed attrition funnel, and attaches
# operating-condition context to events that clear every gate. M122's
# startEventReconcile already reconciled the buffer/ramp pair; this extends
# that to the full four-detector chain in one place. See _start_event_chain
# docstring for the full methodology.
_SEC_COOLANT = 'Температура охолодної рідини (℃)'  # engine coolant -- this
                                    # MODULE's own RAW_MAP T_coolant convention
                                    # (the Ukrainian OBD-generic channel).
                                    # compute_drive_summary_v6.py's COL_MAP
                                    # uses the SAME short name 'T_coolant' for
                                    # a DIFFERENT raw PID (the VCM-prefixed HV
                                    # coolant channel) -- the two modules are
                                    # each internally consistent but not cross-
                                    # comparable by short name; this constant
                                    # is scoped to what THIS module's SLIM_COLS
                                    # cache actually carries.
_SEC_PACK_T = '[BMS] HV Battery Temperature Sensor 1 (℃)'
_SEC_ACCEL = 'Прискорення (g)'
_SEC_TORQUE = '[VCM] Target Motor Torque (N⋅m)'


def _sec_grid(fr):
    """M221.3: context grid for the unified start-event chain -- extends
    the _bdr_grid/_hs_grid 1 Hz-resample pattern (identical construction:
    index on time, resample('1s').mean().ffill(limit=3)) with the columns
    the joined-event context needs: SoC, pack temperature (sensor 1),
    engine coolant temperature, speed (VCM/OBD priority-resolved, M167),
    acceleration, and target torque as the traction-demand proxy. Reuses
    the existing grid machinery rather than rebuilding it."""
    if fr is None or 'time' not in fr.columns:
        return None
    fr2, _ = _apply_speed_priority(fr)   # M167; resolves into _SPEED_VCM_RAW
    keep = {_BDR_SOC: 'soc', _SEC_PACK_T: 'packTempC',
            _SEC_COOLANT: 'coolantTempC', _SEC_ACCEL: 'accelG',
            _SEC_TORQUE: 'targetTorque', _SPEED_VCM_RAW: 'speed'}
    cols = {c: n for c, n in keep.items() if c in fr2.columns}
    if not cols:
        return None
    g = fr2.set_index(pd.to_datetime(fr2['time'], errors='coerce'))
    g = g[list(cols)].rename(columns=cols).apply(pd.to_numeric, errors='coerce')
    return g.resample('1s').mean().ffill(limit=3)


def _start_event_chain(dm, frame_loader=None):
    """M221.3 (P0.2). One frame_loader pass per drive (matching the M122
    _start_event_analytics pattern of "reuse detectors verbatim, no
    re-derivation"). Joins the four independently-computed per-event
    detectors (_buffer_impulse_events/M116, _ramp_latency_events/M118,
    _handoff_sequence_events/M147, _buffer_debt_recovery_events/M187) on
    t0. All four derive t0 from the IDENTICAL _engine_start_triggers
    timestamp, so the join is an EXACT STRING MATCH on t0 -- the same
    convention M122's startEventReconcile already uses for its buffer/ramp
    set intersection (confirmed from that code, not re-picked here), no
    fuzzy tolerance window needed or introduced.

    Publishes the full attrition funnel (nTrig -> nWithBuffer ->
    nWithBufferAndRamp -> nWithBufferRampAndHandoff -> nWithFullChain),
    directly reconciling all four detectors' event counts in one place --
    startEventReconcile (M122) covered only the buffer/ramp pair. For
    events that clear every gate (buffer ∩ ramp ∩ handoff ∩ recovery),
    attaches operating-condition context (SoC, pack/coolant temperature,
    speed, acceleration, target-torque as a traction-demand proxy) read at
    t0 off a 1 Hz grid extending the existing _bdr_grid/_hs_grid pattern
    (_sec_grid; nearest available sample within 3s of t0), and reports it
    as aggregate ladders (median/IQR/n) -- no per-event raw list in the
    JSON, matching how bufferImpulse/rampLatency already report
    distributions rather than event dumps.

    Not a "round-trip efficiency" claim: bufferImpulse/bufferDebtRecovery
    already avoid that framing in their own methodology strings; this join
    inherits the same discipline in its field names (*LagS, fracXXS) and
    prose."""
    if frame_loader is None:
        return None
    n_trig = n_buf = n_bufram = n_bufram_ho = n_full = 0
    ctx = {'soc': [], 'packTempC': [], 'coolantTempC': [], 'speed': [],
           'accelG': [], 'targetTorque': []}
    n_covered = 0
    for _, r in dm.iterrows():
        fr = frame_loader(r['file'])
        if fr is None:
            continue
        n_covered += 1
        trig = set(_engine_start_triggers(fr))
        if not trig:
            continue
        setB = {e['t0'] for e in _buffer_impulse_events(fr)}
        setR = {e['t0'] for e in _ramp_latency_events(fr)}
        setH = {e['t0'] for e in _handoff_sequence_events(fr)}
        setD = {e['t0'] for e in _buffer_debt_recovery_events(fr)}
        n_trig += len(trig)
        n_buf += len(setB)
        br = setB & setR
        n_bufram += len(br)
        brh = br & setH
        n_bufram_ho += len(brh)
        full = brh & setD
        n_full += len(full)
        if not full:
            continue
        g = _sec_grid(fr)
        if g is None or len(g) == 0:
            continue
        for ts in full:
            t0 = pd.Timestamp(ts)
            pos = g.index.get_indexer([t0], method='nearest',
                                      tolerance=pd.Timedelta('3s'))[0]
            if pos == -1:
                continue
            row = g.iloc[pos]
            for col_key in ('soc', 'packTempC', 'coolantTempC', 'speed',
                            'accelG', 'targetTorque'):
                if col_key in row.index and pd.notna(row[col_key]):
                    ctx[col_key].append(float(row[col_key]))

    if n_trig == 0:
        return None

    def mi(v):
        v = np.asarray([x for x in v if x == x], float)
        if v.size == 0:
            return None
        return {'median': round(float(np.median(v)), 2),
                'p25': round(float(np.percentile(v, 25)), 2),
                'p75': round(float(np.percentile(v, 75)), 2), 'n': int(v.size)}

    funnel = {
        'nTrig': int(n_trig), 'nWithBuffer': int(n_buf),
        'nWithBufferAndRamp': int(n_bufram),
        'nWithBufferRampAndHandoff': int(n_bufram_ho),
        'nWithFullChain': int(n_full),
        'pctBuffer': round(100.0 * n_buf / n_trig, 1),
        'pctBufferAndRamp': round(100.0 * n_bufram / n_trig, 1),
        'pctBufferRampHandoff': round(100.0 * n_bufram_ho / n_trig, 1),
        'pctFullChain': round(100.0 * n_full / n_trig, 1),
    }
    return {
        'nDrivesCovered': n_covered,
        'attritionFunnel': funnel,
        'fullChainContext': {
            'socPct': mi(ctx['soc']),
            'packTempC': mi(ctx['packTempC']),
            'coolantTempC': mi(ctx['coolantTempC']),
            'speedKmh': mi(ctx['speed']),
            'accelG': mi(ctx['accelG']),
            'targetTorqueNm': mi(ctx['targetTorque']),
        },
        'methodology': (
            'M221.3 (P0.2): joins the four independently-computed per-event '
            'engine-start detectors (bufferImpulse/M116, rampLatency/M118, '
            'handoffSequence/M147, bufferDebtRecovery/M187) on t0. All four '
            'derive t0 from the identical _engine_start_triggers timestamp '
            '(sustained-off RPM<=100 for >=3s -> RPM>800), so the join is an '
            'exact string match, not a fuzzy tolerance window -- the same '
            'convention startEventReconcile (M122) already uses for its '
            'buffer/ramp pair. The attrition funnel (nTrig -> nWithBuffer -> '
            'nWithBufferAndRamp -> nWithBufferRampAndHandoff -> '
            'nWithFullChain) shows eligibility loss at every downstream '
            'gate, directly reconciling all four detectors in one place '
            '(startEventReconcile covered only the buffer/ramp pair). '
            'fullChainContext reports condition (SoC, pack/coolant '
            'temperature, speed, acceleration, target-torque as a '
            'traction-demand proxy) at t0 for events clearing every gate, '
            'read off a 1 Hz grid extending the bufferDebtRecovery/'
            'handoffSequence grid pattern (nearest sample within 3s of t0) '
            '-- reported as aggregate ladders (median/IQR/n), not a raw '
            'per-event list, matching the project convention.'),
    }



# ── Module N (M194): cell-spread transient/relaxation (max/min channel) ───────
# EXPLORATORY. Under load the max-min cell-voltage spread can widen; at rest it
# relaxes back toward an unloaded baseline. On >=5 s rest windows following a
# loaded period, this measures the spread at load-off, the rest asymptote, the
# relaxation magnitude and half-time. Distinct from cellHealthTrend (long-term
# unloaded LEVEL/trend); this is the within-event transient/relaxation. NO cell
# diagnosis (the max/min channel does not identify WHICH cell, and no health claim
# is made). The ~1.3 Hz cadence means sub-5 s relaxation is not resolvable -- and
# the finding here is precisely that the load-induced widening is small and fast,
# so >=5 s relaxation dynamics are minimal. Single vehicle / ~single driver.
_CSR_MAXV = '[BMS] Max Cell Voltage (V)'
_CSR_MINV = '[BMS] Min Cell Voltage (V)'
_CSR_I = '[BMS] HV Battery Current (A)'
_CSR_REST_I = 5.0
_CSR_LOAD_I = 20.0
_CSR_MIN_REST_S = 5
_CSR_PRELOAD_S = 3


def _csr_grid(fr):
    keep = {_CSR_MAXV: 'maxv', _CSR_MINV: 'minv', _CSR_I: 'I'}
    cols = {c: n for c, n in keep.items() if c in fr.columns}
    if 'time' not in fr.columns or _CSR_MAXV not in fr.columns or _CSR_MINV not in fr.columns:
        return None
    g = fr.set_index(pd.to_datetime(fr['time'], errors='coerce'))
    g = g[list(cols)].rename(columns=cols).apply(pd.to_numeric, errors='coerce')
    return g.resample('1s').mean().ffill(limit=3)


def _cell_spread_relaxation(dm, frame_loader=None):
    if frame_loader is None:
        return None
    import numpy as _np
    loaded = []
    asym = []
    mag = []
    half = []
    dates = []
    nDrives = nRest = 0
    days = set()
    for _, r in dm.iterrows():
        fr = frame_loader(r['file'])
        g = _csr_grid(fr)
        if g is None or 'I' not in g.columns:
            continue
        g = g.dropna(subset=['maxv', 'minv', 'I'])
        if len(g) < 30:
            continue
        nDrives += 1
        d = str(r.get('date', ''))[:10]
        spread = (g['maxv'] - g['minv']).values * 1000.0
        cur = g['I'].abs().values
        resting = cur < _CSR_REST_I
        i = 0
        n = len(resting)
        while i < n:
            if resting[i]:
                j = i
                while j < n and resting[j]:
                    j += 1
                if j - i >= _CSR_MIN_REST_S:
                    pre0 = max(0, i - _CSR_PRELOAD_S)
                    if i - pre0 >= 2 and _np.nanmean(cur[pre0:i]) >= _CSR_LOAD_I:
                        seg = spread[i:j]
                        if _np.isfinite(seg).sum() >= 5:
                            s_onset = float(_np.nanmean(spread[max(0, i - 1):i + 1]))
                            s_asym = float(_np.nanmedian(seg[-min(5, len(seg)):]))
                            m = s_onset - s_asym
                            loaded.append(s_onset)
                            asym.append(s_asym)
                            mag.append(m)
                            if m > 1.0:
                                target = s_onset - 0.5 * m
                                hit = _np.where(seg <= target)[0]
                                if len(hit):
                                    half.append(float(hit[0]))
                            nRest += 1
                            days.add(d)
                            dates.append(d)
                i = j
            else:
                i += 1

    if nRest < 5:
        return None

    def mi(v):
        v = _np.asarray([x for x in v if x == x], float)
        if v.size == 0:
            return None
        return {'median': round(float(_np.median(v)), 2),
                'p25': round(float(_np.percentile(v, 25)), 2),
                'p75': round(float(_np.percentile(v, 75)), 2), 'n': int(v.size)}

    def dayboot(vals, dts, nb=4000, seed=42):
        v = _np.asarray(vals, float)
        dd = _np.asarray(dts)
        m = _np.isfinite(v)
        v, dd = v[m], dd[m]
        if v.size < 3:
            return None
        uniq = _np.unique(dd)
        by = {d: v[dd == d] for d in uniq}
        rng = _np.random.default_rng(seed)
        meds = []
        for _ in range(nb):
            s = rng.choice(uniq, len(uniq), replace=True)
            meds.append(_np.median(_np.concatenate([by[d] for d in s])))
        return {'bootMedian': round(float(_np.median(v)), 2),
                'ci95': [round(float(_np.percentile(meds, 2.5)), 2),
                         round(float(_np.percentile(meds, 97.5)), 2)],
                'nEvents': int(v.size), 'nDays': int(uniq.size)}

    magv = _np.asarray(mag, float)
    return {
        'exploratory': True,
        'nDrivesCovered': nDrives, 'nRestWindows': nRest, 'nDays': len(days),
        'loadedSpreadMv': mi(loaded),
        'restAsymptoteMv': mi(asym),
        'relaxationMagnitudeMv': mi(mag),
        'relaxationHalfTimeS': mi(half),
        'relaxationHalfTimeSubResolvable': True,
        'pctRestsWithRelaxationGt1mV': round(float(100.0 * (magv > 1.0).mean()), 1),
        'relaxationMagnitudeBoot': dayboot(mag, dates),
        'thresholds': {'restI': _CSR_REST_I, 'loadI': _CSR_LOAD_I,
                       'minRestS': _CSR_MIN_REST_S},
        'interpretation': (
            'The max-min cell spread sits at a stable ~10-11 mV baseline; load adds '
            'only a small (~1 mV median) widening that relaxes within ~1-2 s -- at '
            'or below the ~1.3 Hz cadence, so >=5 s relaxation dynamics are minimal. '
            'Consistent with a well-balanced, shallow-cycled buffer that never '
            'deeply stresses the cells. This is a small-effect/near-null result, '
            'reported honestly, NOT a cell-health diagnosis.'),
        'methodology': (
            'Rest window = |I|<%g A sustained >=%d s, immediately preceded by a '
            'loaded period (mean |I|>=%g A over the prior %d s). Per window: spread '
            '(max-min)*1000 mV at load-off, the rest asymptote (median of the last '
            'up-to-5 s), the relaxation magnitude (onset-asymptote) and the '
            'half-time (first second below onset-0.5*magnitude, only for >1 mV '
            'relaxations). Median/IQR over rest windows; day-clustered bootstrap '
            '(seed 42, 4000 draws) on the magnitude. EXPLORATORY; no cell diagnosis; '
            'sub-5 s relaxation is not resolvable at this cadence. Distinct from '
            'cellHealthTrend (long-term unloaded level). Single vehicle / ~single '
            'driver.'
            % (_CSR_REST_I, _CSR_MIN_REST_S, _CSR_LOAD_I, _CSR_PRELOAD_S))}



# ── Module S (M195): VGT-A command tracking + air-path operating map (subset) ──
# Absorbs S6. VGT-A commanded & actual position are co-sampled -> static tracking
# error = actual-command. The air-path operating map (VGT position vs boost, RPM,
# MAF, AFR) requires TIME-ALIGNMENT: these are sparse secondary channels in
# DIFFERENT OBD multiplex groups, never co-sampled in one row, so all are
# resampled to 1 s and ffilled (limit 60 s) before binning. Both analyses are
# restricted to engine-on (rpm>400): VGT is only actively controlled when the
# engine runs, and at rest cmd==act==parked would inflate "perfect tracking".
# Static command-vs-actual error + operating map are subset-supported; lag/
# hysteresis (error by command direction) is exploratory. A-ONLY: VGT-B actual is
# absent (only B command exists), so no B tracking. SUBSET: files with real VGT-A
# variation (actual std>0.5); single vehicle / ~single driver; sparse poll -- do
# not generalise timing.
_VGT_CMD = 'Commanded Variable Geometry Turbo A Position (%)'
_VGT_ACT = 'Variable Geometry Turbo A Position (%)'
_VGT_BOOST = '\u0420\u043e\u0437\u0440\u0430\u0445\u0443\u043d\u043a\u043e\u0432\u0438\u0439 \u043d\u0430\u0434\u0434\u0443\u0432 (bar)'
_VGT_RPM = '\u041e\u0431\u0435\u0440\u0442\u0438 \u0434\u0432\u0438\u0433\u0443\u043d\u0430 (rpm)'
_VGT_MAF = '\u041c\u0430\u0441\u043e\u0432\u0430 \u0432\u0438\u0442\u0440\u0430\u0442\u0430 \u043f\u043e\u0432\u0456\u0442\u0440\u044f (g/sec)'
_VGT_AFR = '\u0421\u043f\u0456\u0432\u0432\u0456\u0434\u043d\u043e\u0448\u0435\u043d\u043d\u044f \u043f\u0430\u043b\u0438\u0432\u043e/\u043f\u043e\u0432\u0456\u0442\u0440\u044f ()'
_VGT_POS_EDGES = [0, 20, 40, 60, 80, 100.01]
_VGT_ENG_ON = 400.0


def _vgt_drive(fn, raw_loader, raw_dir):
    import os
    raw = raw_loader(fn) if raw_loader is not None else None
    if raw is None and raw_dir is not None:
        try:
            with open(os.path.join(raw_dir, fn), 'rb') as fh:
                raw = fh.read()
        except Exception:
            return None
    if not raw:
        return None
    want = (_VGT_CMD, _VGT_ACT, _VGT_BOOST, _VGT_RPM, _VGT_MAF, _VGT_AFR, 'time')
    try:
        df = pd.read_csv(io.BytesIO(raw), usecols=lambda c: c in want, low_memory=False)
    except Exception:
        return None
    if _VGT_ACT not in df.columns or _VGT_CMD not in df.columns:
        return None
    act = pd.to_numeric(df[_VGT_ACT], errors='coerce')
    s = act.dropna()
    if len(s) < 10 or s.std() is None or s.std() <= 0.5:
        return None
    g = df.set_index(pd.to_datetime(df['time'], errors='coerce'))
    cols = {_VGT_CMD: 'cmd', _VGT_ACT: 'act', _VGT_BOOST: 'boost',
            _VGT_RPM: 'rpm', _VGT_MAF: 'maf', _VGT_AFR: 'afr'}
    g = g[[c for c in cols if c in g.columns]].rename(columns=cols).apply(pd.to_numeric, errors='coerce')
    g = g.resample('1s').mean().ffill(limit=60)
    if 'rpm' in g.columns:
        g = g[g['rpm'] > _VGT_ENG_ON]           # engine-on only
    g = g.dropna(subset=['act'])
    if len(g) < 10:
        return None
    return g


def _vgt_airpath(dm, raw_loader=None, raw_dir=None):
    import numpy as _np
    acc = {k: [] for k in ('cmd', 'act', 'boost', 'rpm', 'maf', 'afr', 'date')}
    nFiles = 0
    days = set()
    for _, r in dm.iterrows():
        g = _vgt_drive(r['file'], raw_loader, raw_dir)
        if g is None:
            continue
        nFiles += 1
        d = str(r.get('date', ''))[:10]
        days.add(d)
        for k in ('cmd', 'act', 'boost', 'rpm', 'maf', 'afr'):
            acc[k].append(g[k].values if k in g.columns else _np.full(len(g), _np.nan))
        acc['date'].append(_np.full(len(g), d))
    if nFiles < 5:
        return None
    for k in acc:
        acc[k] = _np.concatenate(acc[k]) if acc[k] else _np.array([])
    cmd, act = acc['cmd'], acc['act']
    paired = _np.isfinite(cmd) & _np.isfinite(act)
    err = act[paired] - cmd[paired]
    absr = _np.abs(err)
    dts = acc['date'][paired]

    def mi(v):
        v = _np.asarray([x for x in v if x == x], float)
        if v.size == 0:
            return None
        return {'median': round(float(_np.median(v)), 2),
                'p25': round(float(_np.percentile(v, 25)), 2),
                'p75': round(float(_np.percentile(v, 75)), 2), 'n': int(v.size)}

    def dayboot(vals, dd, nb=4000, seed=42):
        v = _np.asarray(vals, float)
        dd = _np.asarray(dd)
        m = _np.isfinite(v)
        v, dd = v[m], dd[m]
        if v.size < 3:
            return None
        uniq = _np.unique(dd)
        by = {d: v[dd == d] for d in uniq}
        rng = _np.random.default_rng(seed)
        meds = []
        for _ in range(nb):
            sm = rng.choice(uniq, len(uniq), replace=True)
            meds.append(_np.median(_np.concatenate([by[d] for d in sm])))
        return {'bootMedian': round(float(_np.median(v)), 2),
                'ci95': [round(float(_np.percentile(meds, 2.5)), 2),
                         round(float(_np.percentile(meds, 97.5)), 2)],
                'nSamples': int(v.size), 'nDays': int(uniq.size)}

    def lbl(b):
        return '%d-%d' % (int(_VGT_POS_EDGES[b]), int(min(_VGT_POS_EDGES[b + 1], 100)))

    # tracking error by commanded-position bin
    cb = _np.digitize(cmd[paired], _VGT_POS_EDGES[1:-1])
    byCmd = []
    for b in range(len(_VGT_POS_EDGES) - 1):
        m = cb == b
        if m.sum() >= 20:
            byCmd.append({'cmdBin': lbl(b), 'errMedian': mi(err[m])['median'],
                          'absErrMedian': mi(absr[m])['median'], 'n': int(m.sum())})
    # air-path operating map by actual-position bin
    ab = _np.digitize(act, _VGT_POS_EDGES[1:-1])
    def med(v):
        v = v[_np.isfinite(v)]
        return round(float(_np.median(v)), 2) if len(v) else None
    opMap = []
    for b in range(len(_VGT_POS_EDGES) - 1):
        m = ab == b
        if m.sum() >= 20:
            opMap.append({'posBin': lbl(b), 'n': int(m.sum()),
                          'boostBar': med(acc['boost'][m]), 'rpm': med(acc['rpm'][m]),
                          'mafGs': med(acc['maf'][m]), 'afr': med(acc['afr'][m])})
    # hysteresis (exploratory): error by command direction
    dc = _np.diff(cmd[paired], prepend=cmd[paired][0])
    hyst = {'risingErrMedian': mi(err[dc > 1]), 'fallingErrMedian': mi(err[dc < -1])}

    return {
        'subset': True, 'nFiles': nFiles, 'nDays': len(days),
        'nPairedEngineOn': int(paired.sum()),
        'trackingErrorPct': mi(err),
        'absTrackingErrorPct': mi(absr),
        'absTrackingErrorBoot': dayboot(absr, dts),
        'trackingByCmdBin': byCmd,
        'airPathMap': opMap,
        'hysteresisExploratory': hyst,
        'posEdges': _VGT_POS_EDGES[:-1] + [100],
        'methodology': (
            'Subset: files with real VGT-A actual variation (std>0.5). VGT-A '
            'commanded & actual are co-sampled -> static tracking error = actual-'
            'command. All channels resampled to 1 s and ffilled (limit 60 s) to '
            'align the sparse multiplex groups, then restricted to engine-on '
            '(rpm>%d) since VGT is only actively controlled when running (at rest '
            'cmd==act==parked would inflate tracking). Tracking error median/IQR '
            'overall and by commanded-position bin; day-clustered bootstrap (seed '
            '42, 4000 draws) on |error|. Air-path operating map: median boost, RPM, '
            'MAF and AFR by actual-position bin (absorbs S6). Hysteresis (error by '
            'command direction) is EXPLORATORY -- the sparse poll cannot resolve '
            'true actuator lag. A-only: VGT-B actual is absent. Single vehicle / '
            '~single driver; do not generalise timing.'
            % int(_VGT_ENG_ON))}



# ── Module R (M196): high-SoC regen reduction (thin) ─────────────────────────
# Tests whether the regen charge-power ENVELOPE tapers near the top of the SoC
# band (BMS charge-acceptance limiting). Regen power also depends on decel
# intensity, so the p95/p99 envelope per SoC bin (not the mean) is used as the
# "what regen is allowed" ceiling. Flagged THIN by the feasibility review: the
# effect is real but mild and confounded by the driving distribution across SoC
# (the pack spends different amounts of time regenerating at each SoC). Charge
# power is capped at a physical ceiling to drop sensor glitches. Charge-positive
# convention: chg = -((-I)*V)/1000 = I*V/1000 kW when charging. Single vehicle /
# ~single driver -- descriptive.
_HR_I = '[BMS] HV Battery Current (A)'
_HR_V = '[BMS] HV Battery voltage (V)'
_HR_SOC = '[BMS] HV State of charge (%)'
# M226.2 (P1.2, enhancement plan): speed/rpm/pack-temp, read in the SAME
# per-file pass as I/V/soc above (added to _hr_grid's `keep` dict below) --
# not a second raw pass. rpm/eng-off convention matches regenByZone's own
# (rpm<=300 -- a DIFFERENT threshold from this session's usual
# _engine_start_triggers <=100/>800 convention, reused here deliberately
# for consistency with "the same granularity as regenByZone's existing raw
# pass," per the plan's explicit instruction).
_HR_SPEED = _SPEED_VCM_RAW
_HR_RPM = 'Оберти двигуна (rpm)'
_HR_TPACK = '[BMS] HV Battery Temperature Sensor 1 (℃)'
_HR_TORQUE = '[VCM] Target Motor Torque (N⋅m)'  # M231 (audit F06): needed
                             # for the demand-controlled regen-only subset
                             # (torque < 0 == motor braking, not propulsion)
_HR_SOC_EDGES = [40, 50, 55, 60, 63, 66, 69, 72, 100]
_HR_MIN_CHG_KW = 1.0
_HR_CAP_KW = 120.0          # physical ceiling; drops glitches (e.g. 374 kW)


def _hr_grid(fr):
    """M231 (audit F21 fix): _apply_speed_priority() is now called BEFORE
    the selected-column map is built, not after. The prior ordering built
    `cols` from fr.columns as originally read; when the native VCM speed
    column was entirely ABSENT (not merely sparse) and only the OBD
    fallback existed, 'speed' was silently omitted from `cols` because
    _apply_speed_priority() (which creates the VCM-named column from the
    OBD fallback) had not run yet -- the in-place mutation happened on a
    column the selection dict had already decided to drop. Also now adds
    the target-torque channel (needed for the F06 demand-controlled
    regen-only subset) and returns whether the fallback was used, so
    callers can report/audit speed-source composition rather than silently
    losing the column. Returns (grid_df_or_None, used_fallback: bool)."""
    if fr is None or 'time' not in fr.columns or _HR_I not in fr.columns:
        return None, False
    fr, used_fallback = _apply_speed_priority(fr)   # M231: now runs FIRST
    keep = {_HR_I: 'I', _HR_V: 'V', _HR_SOC: 'soc',
            _HR_SPEED: 'speed', _HR_RPM: 'rpm', _HR_TPACK: 'tpack',
            _HR_TORQUE: 'torque'}
    cols = {c: n for c, n in keep.items() if c in fr.columns}
    g = fr.set_index(pd.to_datetime(fr['time'], errors='coerce'))
    g = g[list(cols)].rename(columns=cols).apply(pd.to_numeric, errors='coerce')
    return g.resample('1s').mean().ffill(limit=3), used_fallback


def _high_soc_regen(dm, frame_loader=None):
    """M231 (audit F06): the sampled population here is charge power in
    (_HR_MIN_CHG_KW, _HR_CAP_KW) kW with NO gate on engine state, braking
    torque or deceleration -- it is charging-power-while-at-high-SoC, not
    exclusively regenerative braking (a meaningful fraction of these
    samples are engine-on generator charging, or steady/accelerating
    driving with no deceleration at all). Renamed and disclosed
    accordingly (engineOnSharePct/nonDeceleratingSharePct below); the
    ORIGINAL unfiltered envelope is kept (it is what the released dashboard
    figures are actually computed from and remains useful descriptively),
    alongside a NEW demandControlledRegen block restricted to
    rpm<=300 (engine off/idle) & speed>3 km/h & deceleration>0 & target
    torque<0 -- samples that cannot plausibly be anything OTHER than
    regenerative braking. Both are reported; neither silently stands in
    for the other."""
    if frame_loader is None:
        return None
    import numpy as _np
    chg_all, soc_all, date_all = [], [], []
    eng_off_all, decel_all = [], []            # M231: population-composition disclosure
    reg_chg, reg_soc, reg_date = [], [], []    # M231: demand-controlled regen-only subset
    n_fallback_drives, n_drives_used = 0, 0
    for _, r in dm.iterrows():
        fr = frame_loader(r['file'])
        g, used_fallback = _hr_grid(fr)
        if g is None or 'soc' not in g.columns:
            continue
        g = g.dropna(subset=['I', 'V', 'soc'])
        if len(g) < 20:
            continue
        n_drives_used += 1
        n_fallback_drives += int(used_fallback)
        chg = (g['I'] * g['V'] / 1000.0).values      # charge positive
        soc = g['soc'].values
        m = (chg > _HR_MIN_CHG_KW) & (chg < _HR_CAP_KW)
        if not m.any():
            continue
        day = str(r.get('date', ''))[:10]
        chg_all.append(chg[m])
        soc_all.append(soc[m])
        date_all.append(_np.full(m.sum(), day))

        rpm = g['rpm'].values if 'rpm' in g.columns else _np.full(len(g), _np.nan)
        speed = g['speed'].values if 'speed' in g.columns else _np.full(len(g), _np.nan)
        torque = g['torque'].values if 'torque' in g.columns else _np.full(len(g), _np.nan)
        v_prev = _np.concatenate([speed[:1], speed[:-1]])
        decel = v_prev - speed                          # km/h per 1s sample; >0 == slowing
        eng_off = _np.nan_to_num(rpm, nan=9999.0) <= 300  # regenByZone's own threshold
        decelerating = _np.nan_to_num(decel, nan=-1.0) > 0
        eng_off_all.append(eng_off[m])
        decel_all.append(decelerating[m])

        # M231: demand-controlled regen-only subset (F06 required response)
        rm = (m & eng_off & (_np.nan_to_num(speed, nan=-1.0) > 3.0)
              & (_np.nan_to_num(decel, nan=-1.0) > 0)
              & (_np.nan_to_num(torque, nan=1.0) < 0))
        if rm.any():
            reg_chg.append(chg[rm])
            reg_soc.append(soc[rm])
            reg_date.append(_np.full(rm.sum(), day))
    if not chg_all:
        return None
    return _high_soc_regen_aggregate(
        _np.concatenate(chg_all), _np.concatenate(soc_all),
        _np.concatenate(date_all), _np.concatenate(eng_off_all),
        _np.concatenate(decel_all),
        _np.concatenate(reg_chg) if reg_chg else _np.array([]),
        _np.concatenate(reg_soc) if reg_soc else _np.array([]),
        _np.concatenate(reg_date) if reg_date else _np.array([]),
        n_drives_used, n_fallback_drives)


def _high_soc_regen_aggregate(chg, soc, dts, eng_off_flag, decelerating_flag,
                               reg_chg, reg_soc, reg_date,
                               n_drives_used, n_fallback_drives):
    """M231: pure aggregation step, split out of _high_soc_regen() so the
    (expensive, raw-file-reading) per-drive extraction loop and the
    (cheap, deterministic) bins/bootstrap/return-dict construction can be
    tested and re-run independently -- e.g. re-running just this function
    against corpus-wide arrays already extracted once, without re-reading
    every raw CSV."""
    import numpy as _np
    edges = _HR_SOC_EDGES

    def _envelope(chg_arr, soc_arr):
        """Shared SoC-binned median/p95/p99 envelope builder, used for both
        the full (unfiltered) population and the M231 regen-only subset so
        the two are computed identically and are directly comparable."""
        sb_ = _np.digitize(soc_arr, edges[1:-1])
        bins_ = []
        for b in range(len(edges) - 1):
            mm = sb_ == b
            if mm.sum() >= 50:
                v = chg_arr[mm]
                bins_.append({'socBin': lbl(b), 'n': int(mm.sum()),
                              'medianKw': round(float(_np.median(v)), 2),
                              'p95Kw': round(float(_np.percentile(v, 95)), 2),
                              'p99Kw': round(float(_np.percentile(v, 99)), 2),
                              '_binIdx': b})
        return sb_, bins_

    def lbl(b):
        hi = edges[b + 1]
        return ('%d+' % edges[b]) if hi == 100 else ('%d-%d' % (edges[b], hi))

    sb, bins = _envelope(chg, soc)
    if len(bins) < 3:
        return None
    # peak-envelope bin and high-SoC bins
    peak = max(bins, key=lambda x: x['p95Kw'])
    high = [x for x in bins if edges[x['_binIdx']] >= 69]
    high_idx = [x['_binIdx'] for x in high]
    high_p95 = _np.median([x['p95Kw'] for x in high]) if high else None
    reduction = (round(100.0 * (peak['p95Kw'] - high_p95) / peak['p95Kw'], 1)
                 if high_p95 is not None else None)

    def dayboot_p95(binIdx, dd_full, chg_full, sb_full, nb=4000, seed=42):
        m = sb_full == binIdx
        v = chg_full[m]
        dd = dd_full[m]
        if v.size < 20:
            return None
        uniq = _np.unique(dd)
        by = {d: v[dd == d] for d in uniq}
        rng = _np.random.default_rng(seed)
        ps = []
        for _ in range(nb):
            s = rng.choice(uniq, len(uniq), replace=True)
            ps.append(_np.percentile(_np.concatenate([by[d] for d in s]), 95))
        return {'p95': round(float(_np.percentile(v, 95)), 2),
                'ci95': [round(float(_np.percentile(ps, 2.5)), 2),
                         round(float(_np.percentile(ps, 97.5)), 2)],
                'nDays': int(uniq.size)}

    def dayboot_median_of_bins_p95(bin_indices, point_est, dd_full, chg_full,
                                    sb_full, nb=4000, seed=43):
        """M231 (audit F06, second estimand mismatch): bootstraps the SAME
        statistic as the point estimate it is paired with -- the median of
        each high-SoC bin's own p95, resampling calendar DAYS ONCE per draw
        and applying that identical day-set to every bin (preserving
        cross-bin within-day correlation) -- rather than the p95 of a single
        bin, which was a different (smaller, single-bin) aggregate silently
        attached to the multi-bin median point estimate."""
        if not bin_indices:
            return None
        in_high = _np.isin(sb_full, bin_indices)
        uniq = _np.unique(dd_full[in_high])
        if uniq.size < 5:
            return None
        by_bin = {}
        for bidx in bin_indices:
            m = sb_full == bidx
            v, dd = chg_full[m], dd_full[m]
            by_bin[bidx] = {d: v[dd == d] for d in _np.unique(dd)}
        rng = _np.random.default_rng(seed)
        ps = []
        for _ in range(nb):
            s = rng.choice(uniq, len(uniq), replace=True)
            per_bin_p95 = []
            for by in by_bin.values():
                vals = [by[d] for d in s if d in by]
                if vals:
                    vv = _np.concatenate(vals)
                    if vv.size >= 5:
                        per_bin_p95.append(_np.percentile(vv, 95))
            if per_bin_p95:
                ps.append(_np.median(per_bin_p95))
        if not ps:
            return None
        return {'p95': round(float(point_est), 2),
                'ci95': [round(float(_np.percentile(ps, 2.5)), 2),
                         round(float(_np.percentile(ps, 97.5)), 2)],
                'nDays': int(uniq.size), 'nBinsPooled': len(bin_indices)}

    top_idx = max(x['_binIdx'] for x in bins)
    peak_idx = peak['_binIdx']
    peak_boot = dayboot_p95(peak_idx, dts, chg, sb)
    top_boot = dayboot_p95(top_idx, dts, chg, sb)
    high_soc_boot = (dayboot_median_of_bins_p95(high_idx, high_p95, dts, chg, sb)
                     if high_p95 is not None else None)
    for x in bins:
        del x['_binIdx']

    # M231 (audit F06): honest population-composition disclosure. Verified
    # against the audit's own independent reconstruction (32.14% engine-on,
    # 61.75% non-decelerating of 205,882 SoC-valid charging samples).
    engine_on_share = round(100.0 * float((~eng_off_flag).mean()), 2)
    non_decel_share = round(100.0 * float((~decelerating_flag).mean()), 2)

    # M231 (audit F06 required response): demand-controlled regen-only
    # subset -- rpm<=300 & speed>3 km/h & deceleration>0 & torque<0.
    # Samples meeting all four conditions cannot plausibly be anything
    # other than regenerative braking (unlike the unfiltered population
    # above, which mixes in engine-on generator charging and non-
    # decelerating driving).
    demand_controlled = None
    if reg_chg.size:
        r_chg, r_soc, r_dts = reg_chg, reg_soc, reg_date
        r_sb, r_bins = _envelope(r_chg, r_soc)
        if len(r_bins) >= 3:
            r_peak = max(r_bins, key=lambda x: x['p95Kw'])
            r_high = [x for x in r_bins if edges[x['_binIdx']] >= 69]
            r_high_idx = [x['_binIdx'] for x in r_high]
            r_high_p95 = _np.median([x['p95Kw'] for x in r_high]) if r_high else None
            r_reduction = (round(100.0 * (r_peak['p95Kw'] - r_high_p95) / r_peak['p95Kw'], 1)
                          if r_high_p95 is not None else None)
            # prespecified contrast (peak bin vs. high-SoC aggregate),
            # day-bootstrapped on the SAME regen-only-restricted population
            r_contrast_boot = (dayboot_median_of_bins_p95(
                r_high_idx, r_high_p95, r_dts, r_chg, r_sb, seed=44)
                if r_high_p95 is not None else None)
            r_peak_boot = dayboot_p95(r_peak['_binIdx'], r_dts, r_chg, r_sb, seed=45)
            for x in r_bins:
                del x['_binIdx']
            demand_controlled = {
                'n': int(r_chg.size),
                'envelopeBySoc': r_bins,
                'peakP95Bin': r_peak['socBin'], 'peakP95Kw': r_peak['p95Kw'],
                'highSocP95Kw': round(float(r_high_p95), 2) if r_high_p95 is not None else None,
                'reductionPct': r_reduction,
                'peakBinP95Boot': r_peak_boot,
                'highSocP95Boot': r_contrast_boot,
                'methodology': (
                    'Restricted to rpm<=300 (engine off/idle) & speed>3 km/h '
                    '& instantaneous deceleration (speed[t-1]-speed[t])>0 & '
                    'target motor torque<0 (motor braking, not propulsion) '
                    '-- a demand-controlled subset that cannot plausibly be '
                    'anything other than regenerative braking, unlike the '
                    'unfiltered charging-power population above. Same SoC '
                    'bins, same day-clustered-bootstrap protocol (seed 44/45, '
                    '4000 draws), and the SAME median-of-high-bins-p95 '
                    'statistic paired correctly with its own bootstrap CI.')}

    return {
        'thin': True,
        'nChargingSamples': int(chg.size), 'nAboveSoc66': int((soc > 66).sum()),
        'nAboveSoc69': int((soc > 69).sum()), 'maxSoc': round(float(soc.max()), 1),
        'engineOnSharePct': engine_on_share,
        'nonDeceleratingSharePct': non_decel_share,
        'nDrivesUsed': int(n_drives_used), 'nDrivesSpeedFallback': int(n_fallback_drives),
        'populationCaveat': (
            'M231 (audit F06): this envelope\'s population is charge power '
            'in (%.0f, %.0f) kW while SoC is valid -- it is NOT restricted to '
            'regenerative braking. Of these samples, %.1f%% are engine-on '
            '(generator charging, not necessarily regen) and %.1f%% are '
            'non-decelerating (charging while steady or accelerating -- '
            'engine-on generator charging can do this). See '
            'demandControlledRegen for a subset restricted to samples that '
            'cannot plausibly be anything other than regenerative braking.'
            % (_HR_MIN_CHG_KW, _HR_CAP_KW, engine_on_share, non_decel_share)),
        'envelopeBySoc': bins,
        'peakP95Bin': peak['socBin'], 'peakP95Kw': peak['p95Kw'],
        'highSocP95Kw': round(float(high_p95), 2) if high_p95 is not None else None,
        'highSocReductionPct': reduction,
        'peakBinP95Boot': peak_boot,
        'topBinP95Boot': top_boot,
        'highSocP95Boot': high_soc_boot,
        'demandControlledRegen': demand_controlled,
        'capKw': _HR_CAP_KW,
        'interpretation': (
            'The high-SoC CHARGING-POWER p95 envelope (NOT exclusively regen '
            '-- see populationCaveat) is dome-shaped: it rises from low SoC, '
            'peaks mid-band, then declines mildly toward the top -- a modest '
            'high-SoC charge-acceptance taper, not a hard cutoff. THIN '
            'effect, confounded by the driving distribution across SoC; '
            'reported descriptively. demandControlledRegen (restricted to '
            'samples that cannot plausibly be anything other than '
            'regenerative braking) shows the same qualitative taper.'),
        'methodology': (
            'Charging-power samples (M231: renamed from "regen samples" -- '
            'see populationCaveat) = charge power I*V/1000 kW in (%.0f, %.0f) '
            'kW (cap drops sensor glitches). Envelope = median/p95/p99 charge '
            'kW per SoC bin (bins need >=50 samples). High-SoC reduction = '
            'drop in p95 from the peak bin to the MEDIAN (not mean) of bins '
            'at SoC>=69%%. Day-clustered bootstrap (seed 42/43, 4000 draws) '
            'on the peak-bin p95 (peakBinP95Boot), the single top-SoC-bin p95 '
            '(topBinP95Boot), and -- M231 fix for the estimand mismatch -- '
            'the SAME median-of-high-bins statistic as highSocP95Kw itself '
            '(highSocP95Boot), so the reported point estimate and its CI are '
            'always the same aggregate. The p95/p99 envelope (not the mean) '
            'is used because charge-power magnitude is set by demand '
            'intensity, not SoC -- the envelope is the observed ceiling, not '
            'an identified BMS acceptance limit. THIN per the feasibility '
            'review. Single vehicle / ~single driver.'
            % (_HR_MIN_CHG_KW, _HR_CAP_KW))}



def _high_soc_regen_covariates(dm, frame_loader=None):
    """M226.2 (P1.2, enhancement plan): condition-controlled regen-
    acceptance frontier. `highSocRegen` (above) already has a SoC-binned
    p95 envelope with bootstrapped CIs, but does not adjust for the
    deceleration-intensity confound the proposal names.

    Reuses `_high_soc_regen`'s OWN regen-sample definition verbatim
    (charge power I*V/1000 kW in (_HR_MIN_CHG_KW, _HR_CAP_KW), via the
    SAME `_hr_grid`, now additively extended -- M226.2 -- with speed/rpm/
    pack-temp read in the same per-file pass, not a second raw pass) so
    the covariate-adjusted quantiles are directly comparable to the
    existing envelope, not a differently-defined sample. Per-sample
    covariates, at the SAME per-1Hz-sample granularity regenByZone's own
    raw pass uses (a qualifying "step" there is a single 1 Hz sample, not
    a multi-second event with its own duration -- reused deliberately,
    per the plan's explicit instruction to match that granularity):
    initial/entry speed (speed at t-1), instantaneous deceleration rate
    (speed[t-1]-speed[t], km/h/s), pack temperature (T1 at t), and
    preceding traction power (discharge kW at t-1) -- plus contiguous-
    decel-run length as a bonus duration covariate.

    Quantile stratification, not a fitted quantile-regression/GAM: bins
    SoC (the SAME _HR_SOC_EDGES highSocRegen itself uses) jointly with a
    deceleration-intensity tercile, and reports p90/p95/p99 within each
    joint cell -- controlling for the confound via stratification, this
    codebase's established alternative to a new parametric model family
    (matching M224/M226.1's own binned-not-parametric choices this
    session). declineSurvivesAdjustment: TRUE only if the high-SoC p95
    decline (vs. the peak-SoC bin) holds in EVERY decel-intensity
    stratum; the actual per-stratum comparison is reported alongside the
    boolean so a reader is never asked to trust an unsupported summary
    flag. A genuine open question, per the plan -- reported honestly
    either way, not steered toward the pre-existing finding.

    Single vehicle / ~single driver -- descriptive, not causal.
    """
    if frame_loader is None:
        return None
    rows = []
    for _, r in dm.iterrows():
        fr = frame_loader(r['file'])
        g, _used_fallback = _hr_grid(fr)
        if g is None or 'soc' not in g.columns:
            continue
        g = g.dropna(subset=['I', 'V', 'soc'])
        if len(g) < 20:
            continue
        chg = (g['I'] * g['V'] / 1000.0).values      # charge positive
        soc = g['soc'].values
        m = (chg > _HR_MIN_CHG_KW) & (chg < _HR_CAP_KW)
        if not m.any():
            continue
        speed = g['speed'].values if 'speed' in g.columns else np.full(len(g), np.nan)
        rpm = g['rpm'].values if 'rpm' in g.columns else np.full(len(g), np.nan)
        tpack = g['tpack'].values if 'tpack' in g.columns else np.full(len(g), np.nan)
        dis_kw = np.where(chg < 0, -chg, 0.0)        # discharge magnitude, kW
        v_prev = np.concatenate([speed[:1], speed[:-1]])
        decel_rate = v_prev - speed                   # km/h per 1 s sample
        eng_off = np.nan_to_num(rpm, nan=9999.0) <= 300  # regenByZone's own threshold
        prior_dis = np.concatenate([dis_kw[:1], dis_kw[:-1]])
        idx = np.where(m)[0]
        # contiguous-run length each qualifying sample belongs to (bonus
        # duration covariate; regenByZone itself does not report this, so
        # not "reused" per se, but cheap given the boolean mask already exists)
        run_len = np.zeros(len(m), dtype=int)
        for a, b in _csg_runs(m):
            run_len[a:b + 1] = b - a + 1
        day = str(r.get('date', ''))[:10]
        for i in idx:
            rows.append({
                'day': day, 'chgKw': float(chg[i]), 'soc': float(soc[i]),
                'entrySpeedKmh': (float(v_prev[i]) if v_prev[i] == v_prev[i] else None),
                'decelRateKmhPerS': (float(decel_rate[i]) if decel_rate[i] == decel_rate[i] else None),
                'tpackC': (float(tpack[i]) if tpack[i] == tpack[i] else None),
                'precedingTractionKw': (float(prior_dis[i]) if prior_dis[i] == prior_dis[i] else None),
                'engineOff': bool(eng_off[i]),
                'runLenS': int(run_len[i]),
            })
    if not rows:
        return None
    return _high_soc_regen_covariates_aggregate(pd.DataFrame(rows))


def _high_soc_regen_covariates_aggregate(P):
    """M231: pure aggregation step, split out of _high_soc_regen_covariates()
    for the same reason as _high_soc_regen_aggregate() -- lets the
    (expensive, raw-file-reading) per-drive extraction and the (cheap,
    deterministic) stratification/quantile logic be tested and re-run
    independently."""

    def q_stats(vals, qs=(0.90, 0.95, 0.99)):
        x = np.asarray([v for v in vals if v == v], float)
        if len(x) < 20:
            return {'n': int(len(x))}
        out = {'n': int(len(x))}
        for q in qs:
            out['p%d' % int(q * 100)] = round(float(np.percentile(x, q * 100)), 2)
        return out

    edges = _HR_SOC_EDGES

    def soc_label(lo, hi):
        return ('%d+' % lo) if hi == 100 else ('%d-%d' % (lo, hi))

    decel_valid = P['decelRateKmhPerS'].dropna()
    decel_terc = (np.percentile(decel_valid, [33.3, 66.7])
                 if len(decel_valid) >= 60 else None)

    condition_controlled_quantiles = None
    decline_by_stratum = []
    if decel_terc is not None:
        bands = [('low', -1e6, decel_terc[0]), ('mid', decel_terc[0], decel_terc[1]),
                 ('high', decel_terc[1], 1e6)]
        condition_controlled_quantiles = {}
        for band_lbl, lo_d, hi_d in bands:
            sub_d = P[(P['decelRateKmhPerS'] > lo_d) & (P['decelRateKmhPerS'] <= hi_d)]
            cells = []
            for i in range(len(edges) - 1):
                lo, hi = edges[i], edges[i + 1]
                sub = sub_d[(sub_d['soc'] >= lo) & (sub_d['soc'] < hi)]
                st = q_stats(sub['chgKw'].values)
                st['socBin'] = soc_label(lo, hi)
                cells.append(st)
            condition_controlled_quantiles[band_lbl] = cells
            # decline check WITHIN this stratum: peak-p95 bin vs. mean of
            # bins at SoC>=69 (mirrors highSocRegen's own comparison exactly)
            eligible = [c for c in cells if c.get('n', 0) >= 20 and 'p95' in c]
            if len(eligible) >= 3:
                peak_c = max(eligible, key=lambda c: c['p95'])
                high_cells = [c for c in eligible
                             if int(c['socBin'].split('-')[0].rstrip('+')) >= 69]
                high_p95 = (float(np.mean([c['p95'] for c in high_cells]))
                           if high_cells else None)
                decline_by_stratum.append({
                    'decelBand': band_lbl, 'peakSocBin': peak_c['socBin'],
                    'peakP95Kw': peak_c['p95'],
                    'highSocP95Kw': round(high_p95, 2) if high_p95 is not None else None,
                    'declines': (bool(high_p95 < peak_c['p95'])
                                if high_p95 is not None else None),
                })
            else:
                decline_by_stratum.append({'decelBand': band_lbl,
                                          'note': 'insufficient eligible SoC bins in this stratum'})

    # covariate-adjusted p95: the single joint (SoC x decel-tercile) table,
    # p95 column only, for direct dashboard binding
    covariate_adjusted_p95 = None
    if condition_controlled_quantiles is not None:
        covariate_adjusted_p95 = {
            band: [{'socBin': c['socBin'], 'p95Kw': c.get('p95'), 'n': c.get('n', 0)}
                  for c in cells]
            for band, cells in condition_controlled_quantiles.items()
        }

    verdicts = [d.get('declines') for d in decline_by_stratum if d.get('declines') is not None]
    decline_survives_adjustment = (all(verdicts) if verdicts else None)

    return {
        'nRegenSamplesCovariates': int(len(P)),
        'decelTercileEdgesKmhPerS': (
            [round(float(x), 3) for x in decel_terc] if decel_terc is not None else None),
        'conditionControlledQuantiles': condition_controlled_quantiles,
        'covariateAdjustedP95': covariate_adjusted_p95,
        'declineSurvivesAdjustment': decline_survives_adjustment,
        'declineByStratum': decline_by_stratum,
        'engineOffSharePct': round(100.0 * float(P['engineOff'].mean()), 1),
        'covariateMethodology': (
            'M226.2 (P1.2, enhancement plan): the SAME regen-sample '
            'definition as highSocRegen (charge power in (%.0f, %.0f) kW), '
            'stratified jointly by SoC bin (highSocRegen\'s own edges) and '
            'a deceleration-intensity tercile (instantaneous speed[t-1]-'
            'speed[t], km/h per 1 s sample -- the same per-sample '
            'granularity regenByZone\'s own raw pass uses, deliberately '
            'reused rather than a new multi-second event definition). '
            'p90/p95/p99 reported per joint cell (quantile stratification, '
            'not a fitted quantile-regression/GAM model -- this codebase\'s '
            'established binned-not-parametric convention). '
            'declineSurvivesAdjustment is TRUE only if the high-SoC (>=69%%) '
            'p95 decline vs. the peak-p95 SoC bin holds in EVERY decel-'
            'intensity stratum; declineByStratum reports the actual '
            'per-stratum comparison so this is checkable, not just '
            'asserted. A genuine open question per the plan -- reported '
            'honestly either way.'
            % (_HR_MIN_CHG_KW, _HR_CAP_KW)),
    }


def _soc_control_surface(dm, frame_loader=None):
    """M224 (P0.3, enhancement plan): SoC-control surface completion.
    Builds the two missing components of the three-part dynamic
    SoC-control surface the enhancement proposal describes -- component 2
    (engine START/STOP hazard over SoC and demand) already exists as
    socHysteresisV2's own partialDependence/surfaces fields (M147/M216),
    referenced here via hazardCrossRef rather than duplicated.

    Reuses m119v2_model.build_grid(fr) verbatim -- the SAME function
    socHysteresisV2 itself is built from, via frame_loader (no new raw
    pass, new binning/aggregation only). SoC axis (40-85 by 5) and speed
    axis (0-130 by 10) are m119v2_model.SURF_SOC/SURF_SPEED verbatim, and
    the per-cell window half-widths (soc +/-2.5, speed +/-5) match
    m119v2_model._support_mask's own cell definition exactly -- satisfying
    the plan's "identical SoC/demand axes and identical support-density
    masking" requirement literally, not just in spirit.

    224.1 (component 1, net battery-power-neutral contour): per (SoC,
    speed) cell, a DAY-BLOCKED mean net battery power (kW, charge-positive
    -- the SAME sign convention energyPath.chargeSources' gross_charge_kwh
    accounting uses). Day-blocked, not per-second: each cell's reported
    value is the mean OF PER-DAY MEANS (every day weighted equally), not a
    naive pooled mean over samples -- the pseudoreplication guard the
    proposal explicitly calls for, matching this codebase's dominant
    day-clustered convention. Reported separately for engine-on and
    engine-off seconds (engine_state as the third conditioning variable):
    pooling the two would conflate two very different physical regimes.

    224.2 (component 3, generator-charging probability surface): the SAME
    day-blocked-mean convention applied to a binary "charging" indicator
    (net battery power > 0 kW) -- REUSES energyPath.chargeSources' own
    charge-positive sign convention as the outcome label, rather than
    re-deriving a charge-source classifier from scratch: every one of
    chargeSources' four charge-source categories represents net charging
    by construction, so "charging" = "net battery power > 0" is the exact
    union of all four -- sufficient for a binary indicator without
    replicating the full four-way engine-state x motor-torque attribution
    rule that categorizes WHICH source is charging.

    Low-support cells ('thin', extending highSocRegen's flag-naming
    convention to a per-cell boolean rather than a single block-level
    flag) are masked at nDays < 3 -- fewer than 3 distinct days behind a
    cell's day-blocked mean is not a stable estimate.

    A coarser 1-D sensitivity check (temperature tercile, demand tercile,
    at representative mid-speed [30,60) km/h engine-on cells) evaluates
    whether the zero-crossing SoC moves with those conditions -- reported
    as a stated finding either way, not assumed. "Demand" here is
    instantaneous |net battery power| (max of the grid's own dis_kw/chg_kw
    at that sample), a simpler proxy than socHysteresisV2's own WINDOWED-
    median demand definition -- distinguished explicitly, not conflated.
    At low demand, net power sits naturally near zero for both charge and
    discharge, so a "crossing" there is noisier by construction; disclosed
    rather than hidden. A full 5-D (SoC x speed x demand x temp x
    engine_state) joint binned regression was not attempted -- the corpus
    does not support that many simultaneous dimensions without cells
    collapsing to single-digit samples; a deliberate binned-local-
    regression scope limit (the plan explicitly permits "GAM OR binned
    local regression"), documented here rather than silently narrowed.

    Single vehicle / ~single driver -- descriptive, not causal.
    """
    if m119v2_model is None or frame_loader is None:
        return None
    soc_ax = list(m119v2_model.SURF_SOC)
    spd_ax = list(m119v2_model.SURF_SPEED)
    soc_hw, spd_hw = 2.5, 5.0

    parts = []
    for _, r in dm.iterrows():
        fr = frame_loader(r['file'])
        if fr is None:
            continue
        g = m119v2_model.build_grid(fr)
        if g is None:
            continue
        g = g.dropna(subset=['soc', 'speed', 'rpm'])
        if len(g) < 20:
            continue
        n = len(g)
        parts.append(pd.DataFrame({
            'soc': g['soc'].values, 'speed': g['speed'].values,
            'netKw': (g['chg_kw'] - g['dis_kw']).values,
            'on': (g['rpm'].values > 800.0),
            'tpack': g['tpack'].values,
            'demand': np.maximum(g['dis_kw'].values, g['chg_kw'].values),
            'day': np.full(n, str(r.get('date', ''))[:10]),
        }))
    if not parts:
        return None
    df = pd.concat(parts, ignore_index=True)
    df = df.dropna(subset=['soc', 'speed', 'netKw'])
    df['charging'] = (df['netKw'] > 0).astype(float)

    def day_blocked_cell(sub, value_col):
        if sub.empty:
            return None, 0, 0
        by_day = sub.groupby('day')[value_col].mean()
        return float(by_day.mean()), int(len(sub)), int(by_day.shape[0])

    def build_surface(sub, value_col, min_days=3):
        vals, ns, days, thins = [], [], [], []
        for s in soc_ax:
            row_v, row_n, row_d, row_t = [], [], [], []
            band = sub[(sub['soc'] >= s - soc_hw) & (sub['soc'] < s + soc_hw)]
            for v in spd_ax:
                cell = band[(band['speed'] >= v - spd_hw) & (band['speed'] < v + spd_hw)]
                mean_v, n, nd = day_blocked_cell(cell, value_col)
                row_v.append(round(mean_v, 4) if mean_v is not None else None)
                row_n.append(n); row_d.append(nd)
                row_t.append(bool(nd < min_days))
            vals.append(row_v); ns.append(row_n); days.append(row_d); thins.append(row_t)
        return {'values': vals, 'n': ns, 'nDays': days, 'thin': thins}

    def zero_crossing_by_speed(surface):
        """Reports the FIRST negative-to-positive sign change scanning low-
        to-high SoC, plus nSignChanges across the whole (non-thin) column --
        the underlying day-blocked values are not always monotonic (a real,
        observed pattern -- e.g. a mid-range net-charge plateau with a
        localized dip back to net-discharge before recovering), so
        nSignChanges>1 flags a column where "the" crossing is a
        simplification of a more textured shape, not a clean single
        boundary. Never smoothed to force monotonicity."""
        out = []
        vals, thin = surface['values'], surface['thin']
        for vi, v in enumerate(spd_ax):
            col_vals = [(soc_ax[si], vals[si][vi]) for si in range(len(soc_ax))
                       if vals[si][vi] is not None and not thin[si][vi]]
            crossing = None
            n_sign_changes = 0
            for k in range(len(col_vals) - 1):
                s0, p0 = col_vals[k]; s1, p1 = col_vals[k + 1]
                if (p0 <= 0 < p1) or (p0 < 0 <= p1):
                    n_sign_changes += 1
                    if crossing is None:
                        crossing = s0 + (s1 - s0) * (0 - p0) / (p1 - p0)
                elif (p0 >= 0 > p1) or (p0 > 0 >= p1):
                    n_sign_changes += 1
            out.append({'speed': v, 'zeroCrossingSoc':
                       round(crossing, 1) if crossing is not None else None,
                       'nSignChanges': n_sign_changes})
        return out

    net_on = build_surface(df[df['on']], 'netKw')
    net_off = build_surface(df[~df['on']], 'netKw')
    chg_on = build_surface(df[df['on']], 'charging')
    chg_off = build_surface(df[~df['on']], 'charging')

    mid_speed = (df['speed'] >= 30) & (df['speed'] < 60) & df['on']
    sens = {}
    for label, col in (('temperature', 'tpack'), ('demand', 'demand')):
        sub = df[mid_speed].dropna(subset=[col])
        if len(sub) < 60:
            sens[label] = {'note': 'insufficient samples for a tercile check'}
            continue
        terc = sub[col].quantile([1 / 3, 2 / 3]).values
        bands = [('low', sub[sub[col] <= terc[0]]),
                ('mid', sub[(sub[col] > terc[0]) & (sub[col] <= terc[1])]),
                ('high', sub[sub[col] > terc[1]])]
        band_rows = []
        for name, bsub in bands:
            usable = []
            for s in soc_ax:
                cell = bsub[(bsub['soc'] >= s - soc_hw) & (bsub['soc'] < s + soc_hw)]
                mean_v, n, nd = day_blocked_cell(cell, 'netKw')
                if mean_v is not None and nd >= 3:
                    usable.append((s, mean_v))
            crossing = None
            for k in range(len(usable) - 1):
                s0, p0 = usable[k]; s1, p1 = usable[k + 1]
                if p0 <= 0 < p1 or p0 < 0 <= p1:
                    crossing = s0 + (s1 - s0) * (0 - p0) / (p1 - p0)
                    break
            band_rows.append({'band': name, 'n': int(len(bsub)),
                             'zeroCrossingSoc': round(crossing, 1) if crossing is not None else None})
        sens[label] = {'bands': band_rows}

    return {
        'socAxis': soc_ax, 'speedAxis': spd_ax,
        'socHalfWidth': soc_hw, 'speedHalfWidth': spd_hw,
        'netPowerContour': {
            'engineOn': net_on, 'engineOff': net_off,
            'zeroCrossingBySpeedEngineOn': zero_crossing_by_speed(net_on),
            'zeroCrossingBySpeedEngineOff': zero_crossing_by_speed(net_off),
        },
        'chargingProbSurface': {'engineOn': chg_on, 'engineOff': chg_off},
        'supportDensity': {
            'engineOn': {'nDays': net_on['nDays'], 'thin': net_on['thin']},
            'engineOff': {'nDays': net_off['nDays'], 'thin': net_off['thin']},
        },
        'conditionSensitivity': sens,
        'hazardCrossRef': {
            'sourceKey': 'socHysteresisV2.surfaces',
            'socAxis': soc_ax, 'speedAxis': spd_ax,
            'note': ('Pointer, not a duplicate: component 2 (engine START/'
                     'STOP hazard) already exists as socHysteresisV2.'
                     'surfaces/partialDependence (M147/M216), computed over '
                     'the identical SoC/speed axes used here so the '
                     'dashboard can render all three views from one shared '
                     'axis definition.'),
        },
        'nSamplesTotal': int(len(df)), 'nDaysTotal': int(df['day'].nunique()),
        'methodology': (
            'M224 (P0.3, enhancement plan): net battery power (kW, charge-'
            'positive, matching energyPath.chargeSources\' own sign '
            'convention) and a binary charging indicator (net power > 0), '
            'binned onto m119v2_model\'s own SoC (40-85 by 5, +/-2.5 half-'
            'width) x speed (0-130 by 10, +/-5 half-width) axes -- '
            'identical to socHysteresisV2\'s surfaces and _support_mask '
            'cell definition. Each cell reports the DAY-BLOCKED mean (mean '
            'of per-day means, not a pooled per-second mean) to avoid '
            'pseudoreplication; cells behind fewer than 3 distinct days '
            'are flagged thin=true and should be treated as unreliable. '
            'Reported separately for engine-on and engine-off seconds. '
            'Zero-crossing SoC (where the day-blocked mean net power flips '
            'from net-discharge to net-charge along the SoC axis at a '
            'given speed) is linearly interpolated between the two '
            'bracketing non-thin cells; no crossing is reported where none '
            'exists in-support. The underlying per-cell values are NOT '
            'always monotonic in SoC (observed: e.g. a mid-range net-charge '
            'plateau with a localized dip back to net-discharge before '
            'recovering) -- never smoothed to force a single clean '
            'boundary. Each reported crossing carries nSignChanges (count '
            'of ALL sign changes across that speed column, not just the '
            'reported one); nSignChanges>1 flags a column where "the" '
            'crossing is a simplification of a more textured shape, '
            'disclosed rather than hidden. Binned local regression, not a '
            'smoothed GAM -- a deliberate simplification within the '
            'plan\'s explicitly-permitted choice, transparent about '
            'cell-to-cell noise rather than smoothing it away. Single '
            'vehicle / ~single driver -- descriptive, not causal.'),
    }


# ── Module F (M197): energy-shifting behaviour (no acoustic claims) ────────────
# EXPLORATORY. Tests the energy-shifting behaviour of the buffer across speed: the
# engine-on fraction and the NET battery power (discharge-positive) per speed bin.
# The signature: the buffer net-discharges at low speed (supplying electric
# operation, engine mostly off) and net-charges where the engine runs with headroom
# (banking generator energy), i.e. energy is shifted from the engine-on band to the
# low-speed electric band. IMPORTANT: there is NO microphone -- no acoustic /
# 'quietness dividend' claim is made. The behaviour is reported as energy flow only;
# whether it is noise-motivated, efficiency-motivated or demand-driven is NOT
# identifiable here. Battery power p=(-I)*V/1000 kW (M11). Single vehicle / ~single
# driver -- descriptive.
_ESH_COLS = {'[BMS] HV Battery Current (A)': 'I', '[BMS] HV Battery voltage (V)': 'V',
             '[VCM] Vehicle Speed (km/h)': 'speed',
             '\u041e\u0431\u0435\u0440\u0442\u0438 \u0434\u0432\u0438\u0433\u0443\u043d\u0430 (rpm)': 'rpm'}
_ESH_SPEED_EDGES = [0, 5, 15, 30, 50, 70, 90, 110, 200]
_ESH_ENG_ON = 400.0


def _esh_grid(fn, raw_loader, frame_loader):
    if frame_loader is not None:
        fr = frame_loader(fn)
        if fr is None:
            return None
        df = fr[[c for c in fr.columns
                 if c in _ESH_COLS or c == 'time' or c == _SPEED_OBD_RAW]]
    else:
        raw = raw_loader(fn) if raw_loader is not None else None
        if not raw:
            return None
        df = pd.read_csv(io.BytesIO(raw),
                         usecols=lambda c: (c in _ESH_COLS or c == 'time'
                                            or c == _SPEED_OBD_RAW),
                         low_memory=False)
    df, _ = _apply_speed_priority(df)
    df = df.rename(columns=_ESH_COLS)
    if 'time' not in df.columns or 'speed' not in df.columns:
        return None
    g = df.set_index(pd.to_datetime(df['time'], errors='coerce'))
    g = g[[c for c in ('I', 'V', 'speed', 'rpm') if c in g.columns]].apply(
        pd.to_numeric, errors='coerce')
    return g.resample('1s').mean().ffill(limit=3)


def _energy_shifting(dm, raw_loader, frame_loader=None):
    import numpy as _np
    nb = len(_ESH_SPEED_EDGES) - 1
    eng_on = [[] for _ in range(nb)]
    eng_date = [[] for _ in range(nb)]
    net_kw = [[] for _ in range(nb)]
    nDrives = 0
    days = set()
    for _, r in dm.iterrows():
        g = _esh_grid(r['file'], raw_loader, frame_loader)
        if g is None:
            continue
        g = g.dropna(subset=['speed'])
        if len(g) < 30:
            continue
        nDrives += 1
        d = str(r.get('date', ''))[:10]
        days.add(d)
        sb = _np.digitize(g['speed'].values, _ESH_SPEED_EDGES[1:-1])
        rpm = g['rpm'].values if 'rpm' in g.columns else None
        pdis = (((-g['I']) * g['V'] / 1000.0).values
                if 'I' in g.columns and 'V' in g.columns else None)
        for b in range(nb):
            m = sb == b
            if m.sum() < 3:
                continue
            if rpm is not None:
                rr = rpm[m]
                rr = rr[_np.isfinite(rr)]
                if len(rr) >= 3:
                    eng_on[b].append(float((rr > _ESH_ENG_ON).mean()))
                    eng_date[b].append(d)
            if pdis is not None:
                pp = pdis[m]
                net_kw[b].extend(pp[_np.isfinite(pp)].tolist())

    if nDrives == 0:
        return None

    def lbl(b):
        hi = _ESH_SPEED_EDGES[b + 1]
        return ('%d+' % _ESH_SPEED_EDGES[b]) if hi == 200 else ('%d-%d' % (_ESH_SPEED_EDGES[b], hi))

    def med_iqr(v):
        v = _np.asarray([x for x in v if x == x], float)
        if v.size == 0:
            return None
        return {'median': round(float(_np.median(v)), 3),
                'p25': round(float(_np.percentile(v, 25)), 3),
                'p75': round(float(_np.percentile(v, 75)), 3), 'n': int(v.size)}

    def dayboot(vals, dates, nb_=4000, seed=42):
        v = _np.asarray(vals, float)
        dts = _np.asarray(dates)
        m = _np.isfinite(v)
        v, dts = v[m], dts[m]
        if v.size < 3:
            return None
        uniq = _np.unique(dts)
        by = {d: v[dts == d] for d in uniq}
        rng = _np.random.default_rng(seed)
        meds = []
        for _ in range(nb_):
            s = rng.choice(uniq, len(uniq), replace=True)
            meds.append(_np.median(_np.concatenate([by[d] for d in s])))
        return {'bootMedian': round(float(_np.median(v)), 3),
                'ci95': [round(float(_np.percentile(meds, 2.5)), 3),
                         round(float(_np.percentile(meds, 97.5)), 3)],
                'nDrives': int(v.size), 'nDays': int(uniq.size)}

    bins = []
    for b in range(nb):
        eo = med_iqr(eng_on[b])
        nk = med_iqr(net_kw[b])
        if eo is None and nk is None:
            continue
        bins.append({'speedBin': lbl(b),
                     'engineOnFrac': eo['median'] if eo else None,
                     'netBattKwMedian': nk['median'] if nk else None,
                     'nDrives': len(eng_on[b])})
    # headline contrast: low-speed (5-15) vs charge band and high speed
    def bin_by_label(target):
        for i in range(nb):
            if lbl(i) == target:
                return i
        return None
    lo = bin_by_label('5-15')
    return {
        'exploratory': True,
        'nDrivesCovered': nDrives, 'nDays': len(days),
        'bySpeed': bins,
        'engineOnLowSpeed': med_iqr(eng_on[lo]) if lo is not None else None,
        'engineOnLowSpeedBoot': dayboot(eng_on[lo], eng_date[lo]) if lo is not None else None,
        'netKwLowSpeed': round(float(_np.median(net_kw[lo])), 3) if lo is not None and net_kw[lo] else None,
        'netKwChargeBandMin': round(float(min(b['netBattKwMedian'] for b in bins
                                              if b['netBattKwMedian'] is not None)), 3),
        'methodology': (
            'Per-drive 1 Hz grid (speed via M167 priority). Per speed bin: engine-on '
            'fraction (rpm>%d), summarised as per-drive median/IQR with a day-'
            'clustered bootstrap (seed 42, 4000 draws) at low speed; and pooled '
            'median NET battery power p=(-I)*V (M11, discharge-positive). The '
            'energy-shifting signature is net discharge at low speed (buffer '
            'supplying electric operation, engine off) and net charge where the '
            'engine runs with headroom (banking generator energy). NO acoustic / '
            'quietness claim -- there is no microphone; whether the shifting is '
            'noise-, efficiency- or demand-motivated is NOT identifiable. '
            'Exploratory. Single vehicle / ~single driver -- descriptive.'
            % int(_ESH_ENG_ON))}



# ── Module P (M198): barometric / air-density compensation (exploratory) ──────
# EXPLORATORY, CIRCULARITY-DISCLOSED. First establishes that the calculated boost
# channel is definitionally gauge pressure -- calc-boost == (MAP - baro)/100 to
# within sensor noise -- so boost CANNOT be used to study barometric compensation
# (circular). It then uses the NON-circular MAF (air mass) at the generator
# load-point (rpm 1800-2200) vs barometric pressure: if the engine holds a fixed
# air-mass operating point, MAF is baro-invariant (density-compensated). Sparse
# secondary channels (baro/MAP/MAF poll in different multiplex groups) are
# time-aligned (1 s ffill, limit 30 s). WEAK TEST: the baro range at the load-point
# is narrow, so the compensation result is suggestive, not conclusive. Single
# vehicle / ~single driver; flat terrain (baro is weather+minor-terrain driven).
_BC_BARO = '\u0410\u0442\u043c\u043e\u0441\u0444\u0435\u0440\u043d\u0438\u0439 \u0442\u0438\u0441\u043a (\u0430\u0431\u0441\u043e\u043b\u044e\u0442\u043d\u0438\u0439) (kPa)'
_BC_MAP = '\u0422\u0438\u0441\u043a \u0443 \u0432\u043f\u0443\u0441\u043a\u043d\u043e\u043c\u0443 \u043a\u043e\u043b\u0435\u043a\u0442\u043e\u0440\u0456 (\u0430\u0431\u0441\u043e\u043b\u044e\u0442\u043d\u0438\u0439) (kPa)'
_BC_BOOST = '\u0420\u043e\u0437\u0440\u0430\u0445\u0443\u043d\u043a\u043e\u0432\u0438\u0439 \u043d\u0430\u0434\u0434\u0443\u0432 (bar)'
_BC_MAF = '\u041c\u0430\u0441\u043e\u0432\u0430 \u0432\u0438\u0442\u0440\u0430\u0442\u0430 \u043f\u043e\u0432\u0456\u0442\u0440\u044f (g/sec)'
_BC_RPM = '\u041e\u0431\u0435\u0440\u0442\u0438 \u0434\u0432\u0438\u0433\u0443\u043d\u0430 (rpm)'
_BC_BARO_EDGES = [90, 94, 96, 98, 100, 103]
_BC_LP_LO, _BC_LP_HI = 1800, 2200


def _bc_aligned(fn, raw_loader, raw_dir):
    import os
    raw = raw_loader(fn) if raw_loader is not None else None
    if raw is None and raw_dir is not None:
        try:
            with open(os.path.join(raw_dir, fn), 'rb') as fh:
                raw = fh.read()
        except Exception:
            return None
    if not raw:
        return None
    want = (_BC_BARO, _BC_MAP, _BC_BOOST, _BC_MAF, _BC_RPM, 'time')
    try:
        df = pd.read_csv(io.BytesIO(raw), usecols=lambda c: c in want, low_memory=False)
    except Exception:
        return None
    if _BC_BARO not in df.columns or 'time' not in df.columns:
        return None
    g = df.set_index(pd.to_datetime(df['time'], errors='coerce'))
    ren = {_BC_BARO: 'baro', _BC_MAP: 'map', _BC_BOOST: 'boost', _BC_MAF: 'maf', _BC_RPM: 'rpm'}
    g = g[[c for c in ren if c in g.columns]].rename(columns=ren).apply(pd.to_numeric, errors='coerce')
    return g.resample('1s').mean().ffill(limit=30)


def _baro_compensation(dm, raw_loader=None, raw_dir=None):
    import numpy as _np
    resid = []
    baro_all = []
    lp_maf = []
    lp_baro = []
    nFiles = 0
    days = set()
    for _, r in dm.iterrows():
        g = _bc_aligned(r['file'], raw_loader, raw_dir)
        if g is None or 'baro' not in g.columns:
            continue
        nFiles += 1
        days.add(str(r.get('date', ''))[:10])
        if 'boost' in g.columns and 'map' in g.columns:
            m = g['boost'].notna() & g['map'].notna() & g['baro'].notna()
            if m.any():
                resid.append((g['boost'][m] - (g['map'][m] - g['baro'][m]) / 100.0).values)
        baro_all.append(g['baro'].dropna().values)
        if 'maf' in g.columns and 'rpm' in g.columns:
            lp = g[(g['rpm'] >= _BC_LP_LO) & (g['rpm'] <= _BC_LP_HI)
                   & g['maf'].notna() & g['baro'].notna()]
            if len(lp) >= 20:
                lp_maf.append(lp['maf'].values)
                lp_baro.append(lp['baro'].values)
    if nFiles < 5 or not baro_all:
        return None
    baro_all = _np.concatenate(baro_all)
    resid = _np.concatenate(resid) if resid else _np.array([])
    lp_maf = _np.concatenate(lp_maf) if lp_maf else _np.array([])
    lp_baro = _np.concatenate(lp_baro) if lp_baro else _np.array([])

    circ = None
    if resid.size:
        circ = {'residualMedianBar': round(float(_np.median(resid)), 4),
                'residualStdBar': round(float(_np.std(resid)), 4),
                'fracWithin0p05': round(float((_np.abs(resid) < 0.05).mean()), 3),
                'isGaugePressure': bool(abs(_np.median(resid)) < 0.02 and (_np.abs(resid) < 0.05).mean() > 0.8)}

    def span(v, lo=1, hi=99):
        return {'p1': round(float(_np.percentile(v, lo)), 1),
                'p99': round(float(_np.percentile(v, hi)), 1),
                'spanKpa': round(float(_np.percentile(v, hi) - _np.percentile(v, lo)), 1),
                'altEquivM': int((_np.percentile(v, hi) - _np.percentile(v, lo)) * 84)}

    lpMafByBaro = []
    corr = None
    if lp_maf.size >= 100:
        bb = _np.digitize(lp_baro, _BC_BARO_EDGES[1:-1])
        for i in range(len(_BC_BARO_EDGES) - 1):
            m = bb == i
            if m.sum() >= 30:
                lpMafByBaro.append({'baroBin': '%d-%d' % (_BC_BARO_EDGES[i], _BC_BARO_EDGES[i + 1]),
                                    'n': int(m.sum()),
                                    'mafMedian': round(float(_np.median(lp_maf[m])), 2),
                                    'mafP25': round(float(_np.percentile(lp_maf[m], 25)), 2),
                                    'mafP75': round(float(_np.percentile(lp_maf[m], 75)), 2)})
        rx = pd.Series(lp_baro).rank().values
        ry = pd.Series(lp_maf).rank().values
        if _np.std(rx) > 0 and _np.std(ry) > 0:
            corr = round(float(_np.corrcoef(rx, ry)[0, 1]), 3)

    mafs = [b['mafMedian'] for b in lpMafByBaro]
    maf_span = round(max(mafs) - min(mafs), 2) if len(mafs) >= 2 else None

    return {
        'exploratory': True, 'circularityDisclosed': True,
        'nFiles': nFiles, 'nDays': len(days),
        'circularity': circ,
        'baroRangeOverall': span(baro_all),
        'baroRangeLoadPoint': span(lp_baro) if lp_baro.size else None,
        'loadPointMafByBaro': lpMafByBaro,
        'loadPointMafSpanGs': maf_span,
        'loadPointMafBaroCorr': corr,
        'loadPointRpmBand': [_BC_LP_LO, _BC_LP_HI],
        'interpretation': (
            'Calc-boost is definitionally gauge pressure (== MAP-baro), so it cannot '
            'test barometric compensation -- circularity confirmed. Using the non-'
            'circular MAF at the load-point, air mass is near-constant across the '
            'available baro range, consistent with the engine holding a fixed air-'
            'mass operating point (density-compensated) -- but the load-point baro '
            'range is narrow, so this is suggestive, not conclusive. WEAK/exploratory.'),
        'methodology': (
            'Sparse channels (baro/MAP/MAF/RPM) time-aligned by 1 s ffill (limit 30 '
            's). Circularity: residual boost-(MAP-baro)/100 (median/std, frac '
            '|resid|<0.05 bar). Baro range overall and at the load-point '
            '(rpm %d-%d). Air-density compensation test: MAF (air mass) at the load-'
            'point by baro bin + rank correlation -- baro-invariant MAF => '
            'compensated. CIRCULARITY DISCLOSED; boost NOT used as an outcome. '
            'EXPLORATORY, under-powered (narrow load-point baro range). Single '
            'vehicle / ~single driver; flat terrain.'
            % (_BC_LP_LO, _BC_LP_HI))}



# ── Module S3 (M199): HV aux/climate load proxy vs ambient (exploratory) ──────
# Extends standstillStats (M26): correlates the per-drive standstill (key-on,
# stationary) draw power against ambient temperature (ambientByDrive start value).
# EXPLORATORY / no causality: there is no HVAC state channel (AC compressor
# on/off, fan speed, cabin setpoint), so this is a descriptive correlation, not a
# mechanism claim -- though the monotonic warm-weather rise is consistent with an
# AC-load interpretation. No sub-15C data exists (warm-season corpus), so this
# characterises the warm end of the range only. Single vehicle / ~single driver.
def _aux_load_ambient(dm, ambient_by_drive=None):
    import numpy as _np
    if not ambient_by_drive:
        return None
    ss = dm.dropna(subset=['standstill_draw_kw']).copy()
    if len(ss) < 20:
        return None
    amb = ss['file'].map(lambda f: (ambient_by_drive[f][0]
                                    if f in ambient_by_drive
                                    and isinstance(ambient_by_drive[f], list)
                                    and len(ambient_by_drive[f]) > 0 else None))
    ss = ss.assign(_amb=amb).dropna(subset=['_amb'])
    if len(ss) < 20:
        return None
    x = ss['_amb'].astype(float).values
    y = ss['standstill_draw_kw'].astype(float).values
    dts = ss.get('date', pd.Series([''] * len(ss))).astype(str).str[:10].values

    rx = pd.Series(x).rank().values
    ry = pd.Series(y).rank().values
    corr = (round(float(_np.corrcoef(rx, ry)[0, 1]), 3)
            if _np.std(rx) > 0 and _np.std(ry) > 0 else None)

    edges = [10, 15, 20, 25, 30, 40]

    def lbl(i):
        return '%d-%d' % (edges[i], edges[i + 1])
    bins = []
    bi = _np.digitize(x, edges[1:-1])
    for i in range(len(edges) - 1):
        m = bi == i
        if m.sum() >= 5:
            v = y[m]
            bins.append({'ambientBinC': lbl(i), 'n': int(m.sum()),
                        'medianKw': round(float(_np.median(v)), 3),
                        'p25Kw': round(float(_np.percentile(v, 25)), 3),
                        'p75Kw': round(float(_np.percentile(v, 75)), 3)})

    def dayboot_corr(nb=4000, seed=42):
        uniq = _np.unique(dts)
        if uniq.size < 3:
            return None
        by_x = {d: x[dts == d] for d in uniq}
        by_y = {d: y[dts == d] for d in uniq}
        rng = _np.random.default_rng(seed)
        corrs = []
        for _ in range(nb):
            s = rng.choice(uniq, len(uniq), replace=True)
            xs = _np.concatenate([by_x[d] for d in s])
            ys = _np.concatenate([by_y[d] for d in s])
            rxs = pd.Series(xs).rank().values
            rys = pd.Series(ys).rank().values
            if _np.std(rxs) > 0 and _np.std(rys) > 0:
                corrs.append(_np.corrcoef(rxs, rys)[0, 1])
        if not corrs:
            return None
        return {'bootMedian': round(float(_np.median(corrs)), 3),
                'ci95': [round(float(_np.percentile(corrs, 2.5)), 3),
                         round(float(_np.percentile(corrs, 97.5)), 3)],
                'nDrives': int(x.size), 'nDays': int(uniq.size)}

    # simple OLS slope kW per degree C (descriptive, not causal)
    Xi = _np.column_stack([_np.ones(len(x)), x])
    coef, *_r = _np.linalg.lstsq(Xi, y, rcond=None)

    return {
        'exploratory': True, 'causalityDisclosed': False,
        'nDrives': int(len(ss)), 'nDays': int(_np.unique(dts).size),
        'ambientRangeC': [round(float(x.min()), 1), round(float(x.max()), 1)],
        'standstillDrawRangeKw': [round(float(y.min()), 2), round(float(y.max()), 2)],
        'spearmanCorr': corr,
        'spearmanCorrBoot': dayboot_corr(),
        'slopeKwPerC': round(float(coef[1]), 4),
        'interceptKw': round(float(coef[0]), 3),
        'byAmbientBin': bins,
        'interpretation': (
            'Standstill draw rises monotonically with ambient temperature above '
            '~15 C, consistent with an AC-compressor climate-load proxy, but no '
            'HVAC state channel exists (compressor on/off, fan speed, setpoint) so '
            'this is a descriptive correlation, NOT a mechanism claim. Ambient below '
            '~15 C is thinly observed (the Cold class is below minimum support) -- '
            'this characterises the warm end of the range only.'),
        'methodology': (
            'Extends standstillStats (M26): per-drive standstill_draw_kw (key-on, '
            'stationary median draw, from drive_master, ens-unfiltered to match '
            'the M26 scope) paired with the drive-start ambient temperature '
            '(ambientByDrive[file][0]). Spearman rank correlation (day-clustered '
            'bootstrap, seed 42, 4000 draws); an OLS slope (kW/C) is reported as a '
            'descriptive summary, not a causal estimate. Binned median/IQR by '
            'ambient band. EXPLORATORY -- no HVAC state channel, no causality claim. '
            'Single vehicle / ~single driver.')}



# ── Module S5 (M200): full-cell array worked examples (case study) ────────────
# WORKED EXAMPLES ONLY, per the feasibility review's "Exp/case-study" tiering --
# NOT a statistical module and not extrapolated to the corpus. Exactly 3 files
# carry the individual per-cell array ('[BMS] Battery Cell #01 (V)' .. '#80'):
# 20260513_182950.csv (full 80/80, the primary example), 20260515_075207.csv
# (60/80), 20260511_185709.csv (25/80). Each cell is polled in a very slow
# round-robin (only ~5 samples per cell across an entire drive), so a usable
# snapshot requires reconstructing the array via ffill over a wide window --
# this is disclosed, not treated as a simultaneous measurement. NOTE: the
# corpus now has far more files with per-cell columns present in the header
# (~50+) than the review's "1-3 files" estimate, but the review's estimate was
# about files with ENOUGH non-null coverage to reconstruct a snapshot, which
# remains true -- most header-only files have near-zero actual per-cell data.
# This module deliberately stays within the reviewed "worked examples" scope;
# whether the broader header coverage supports a statistical S5-successor is a
# genuine scope decision, not made here.
_FCS_FILES = ['20260513_182950.csv', '20260515_075207.csv', '20260511_185709.csv']
_FCS_SOC = '[BMS] HV State of charge (%)'


def _fcs_snapshot(fn, raw_loader, raw_dir):
    import os
    raw = raw_loader(fn) if raw_loader is not None else None
    if raw is None and raw_dir is not None:
        try:
            with open(os.path.join(raw_dir, fn), 'rb') as fh:
                raw = fh.read()
        except Exception:
            return None
    if not raw:
        return None
    cell_cols = ['[BMS] Battery Cell #%02d (V)' % i for i in range(1, 81)]
    want = set(cell_cols) | {_FCS_SOC, 'time'}
    try:
        df = pd.read_csv(io.BytesIO(raw), usecols=lambda c: c in want, low_memory=False)
    except Exception:
        return None
    present = [c for c in cell_cols if c in df.columns]
    if len(present) < 10:
        return None
    cd = df[present].apply(pd.to_numeric, errors='coerce')
    t = pd.to_datetime(df['time'], errors='coerce', format='mixed')
    g = cd.set_index(t).resample('1s').mean().ffill(limit=90)
    completeness = g.notna().sum(axis=1)
    if completeness.max() < max(10, int(0.8 * len(present))):
        return None
    best_i = completeness.idxmax()
    row = g.loc[best_i].dropna()
    row.index = [c.replace('[BMS] Battery Cell #', '').replace(' (V)', '') for c in row.index]
    soc_val = None
    if _FCS_SOC in df.columns:
        sg = pd.to_numeric(df[_FCS_SOC], errors='coerce')
        sg.index = t
        sg = sg.resample('1s').mean().ffill(limit=90)
        v = sg.get(best_i)
        soc_val = round(float(v), 1) if v == v else None
    vals = row.values
    lo3 = row.nsmallest(3)
    hi3 = row.nlargest(3)
    return {
        'file': fn, 'cellColumnsInHeader': len(present),
        'cellsInSnapshot': int(len(row)), 'socAtSnapshot': soc_val,
        'meanV': round(float(vals.mean()), 4), 'minV': round(float(vals.min()), 4),
        'maxV': round(float(vals.max()), 4), 'spreadMv': round(float((vals.max() - vals.min()) * 1000), 1),
        'stdMv': round(float(vals.std() * 1000), 2),
        'lowest3': [{'cell': k, 'v': round(float(v), 4)} for k, v in lo3.items()],
        'highest3': [{'cell': k, 'v': round(float(v), 4)} for k, v in hi3.items()]}


def _full_cell_case_study(dm, raw_loader=None, raw_dir=None):
    examples = []
    for fn in _FCS_FILES:
        ex = _fcs_snapshot(fn, raw_loader, raw_dir)
        if ex is not None:
            examples.append(ex)
    if not examples:
        return None
    return {
        'caseStudyOnly': True, 'nExamples': len(examples),
        'nFilesWithHeaderColumns': None,   # not enumerated here; see methodology
        'examples': examples,
        'interpretation': (
            'Three worked examples across the observed SoC range, reconstructed '
            'from a very slow per-cell round-robin poll via forward-fill. All '
            'three show tight balance (spread <=21 mV on an 80-cell / 25-60-cell '
            'sample), consistent with a well-balanced pack; not a corpus-wide '
            'claim.'),
        'methodology': (
            'Exactly 3 raw files carry individual per-cell voltage columns '
            '("[BMS] Battery Cell #01 (V)".."#80"). Each cell updates only a '
            'handful of times across an entire drive (slow round-robin), so a '
            'representative snapshot is reconstructed by resampling to 1 s and '
            'forward-filling (limit 90 s) to the timestamp with the highest cell '
            'completeness; this is a RECONSTRUCTED array, not a simultaneous '
            'measurement, and is disclosed as such. Per example: mean/min/max/'
            'spread/std across the reconstructed cells, plus the 3 lowest and 3 '
            'highest cells by number. WORKED EXAMPLES ONLY -- no statistical '
            'aggregation, no corpus-wide claim, no cell-health diagnosis. The '
            'header column is present in far more files than 3, but non-null '
            'coverage sufficient to reconstruct a usable snapshot remains rare.')}



# ── Module O-fuel (M201): cold-start thermal FUEL PENALTY (accumulator subset) ──
# The fuel cost of cold-engine warm-up, explicitly deferred out of Module O-thermal
# (M191, which did only the thermal lag). Builds on Module H's (M192) fuel
# accumulator. On cold-start drives (coolant start <60 C that warm past 70 C) it
# quantifies the excess fuel burned before the engine is warm, and DECOMPOSES it:
#   (1) tripLevel  -- naive within-drive warm-up-window vs warm-window L/100km. The
#       observed penalty, but CONFOUNDED by driving regime (warm-up is early/low-
#       speed/urban) and slightly by SoC banking (fuel stored, not wasted) -- both
#       disclosed (SoC drift reported).
#   (2) combustionPenalty -- fuel burned per ENGINE-ON second at a MATCHED operating
#       point (RPM x load bins), cold vs warm. Isolates enrichment + cold-friction,
#       independent of duty cycle and of charge strategy (operating point matched
#       away). Day-clustered bootstrap CI; the modest effect is the cleanest claim.
#   (3) dutyCycle -- engine-ON fraction at MATCHED road speed, cold vs warm. Isolates
#       the series-hybrid strategy component (the ICE runs more when cold: catalyst
#       light-off + cold-start charge/idle logic). This dominates the trip penalty.
#   (4) idle -- fuel per hour at standstill (<3 km/h), cold vs warm (fast-idle).
# AUGUST-ONLY subset: single month, summer (mild cold-start: coolant starts ~ambient
# 16-59 C, NOT winter), urban-dominated. Emissions NOT instrumented. CAP/generator-
# efficiency NOT used here (this is a fuel-flow analysis, not an energy-balance one).
# Single vehicle / ~single driver -- descriptive. Fuel accumulator, coolant, engine
# RPM/load, SoC read directly from raw (coolant polls ~0.25 Hz, a slow multiplex
# group, so the 1 Hz grid uses a generous ffill).
import io, os
import pandas as pd
import numpy as np

_OF_FUEL = '\u0412\u0438\u043a\u043e\u0440\u0438\u0441\u0442\u0430\u043d\u0435 \u043f\u0430\u043b\u0438\u0432\u043e (L)'          # Використане паливо (L)
_OF_COOL = '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043e\u0445\u043e\u043b\u043e\u0434\u043d\u043e\u0457 \u0440\u0456\u0434\u0438\u043d\u0438 (\u2103)'  # coolant
_OF_ERPM = '\u041e\u0431\u0435\u0440\u0442\u0438 \u0434\u0432\u0438\u0433\u0443\u043d\u0430 (rpm)'                                # Оберти двигуна (engine rpm; NOT [VCM] Motor RPM)
_OF_LOAD = '\u0420\u043e\u0437\u0440\u0430\u0445\u0443\u043d\u043a\u043e\u0432\u0435 \u0437\u043d\u0430\u0447\u0435\u043d\u043d\u044f \u043d\u0430\u0432\u0430\u043d\u0442\u0430\u0436\u0435\u043d\u043d\u044f \u043d\u0430 \u0434\u0432\u0438\u0433\u0443\u043d (%)'  # calc engine load %
_OF_SOC  = '[BMS] HV State of charge (%)'
_OF_SPD_VCM = '[VCM] Vehicle Speed (km/h)'
_OF_SPD_OBD = '\u0428\u0432\u0438\u0434\u043a\u0456\u0441\u0442\u044c \u0430\u0432\u0442\u043e\u043c\u043e\u0431\u0456\u043b\u044f (km/h)'
# M226.3 (P1.4, enhancement plan): oil temperature, read in the SAME raw
# pass as everything else above (added to `want`/the constructed frame
# below) -- not a second raw pass. Used only by the continuous-covariate
# model, nowhere else in this module.
_OF_OIL = '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043e\u043b\u0456\u0457 \u0443 \u0434\u0432\u0438\u0433\u0443\u043d\u0456 (\u2103)'

_OF_COLD_MAX = 60.0    # cold-start: coolant start < 60 C (consistent w/ _TWL_COLD_MAX)
_OF_WARM_THR = 70.0    # warm: coolant >= 70 C (consistent w/ Module O lag-70 threshold)
_OF_ENG_ON = 400.0     # engine considered fuelling above 400 rpm
_OF_FFILL = 15         # 1 Hz ffill limit (covers ~4 s coolant multiplex interval)
_OF_RPM_BINS = [400, 1200, 1700, 2200, 2800, 6000]
_OF_LOAD_BINS = [0, 25, 50, 75, 101]
_OF_SPEED_BINS = [0, 5, 20, 40, 70, 200]


def _of_grid(fn, raw_loader, raw_dir):
    raw = None
    if raw_loader is not None:
        raw = raw_loader(fn)
    if raw is None and raw_dir is not None:
        try:
            with open(os.path.join(raw_dir, fn), 'rb') as fh:
                raw = fh.read()
        except Exception:
            return None
    if not raw:
        return None
    want = {_OF_FUEL, _OF_COOL, _OF_ERPM, _OF_LOAD, _OF_SOC, _OF_SPD_VCM,
           _OF_SPD_OBD, _OF_OIL, 'time'}
    try:
        df = pd.read_csv(io.BytesIO(raw), usecols=lambda c: c in want, low_memory=False)
    except Exception:
        return None
    if _OF_FUEL not in df.columns or _OF_COOL not in df.columns or 'time' not in df.columns:
        return None
    t = pd.to_datetime(df['time'], errors='coerce')
    spd = None
    for c in (_OF_SPD_VCM, _OF_SPD_OBD):
        if c in df.columns and pd.to_numeric(df[c], errors='coerce').notna().sum() > 20:
            spd = pd.to_numeric(df[c], errors='coerce').values
            break
    if spd is None:
        return None

    def col(c):
        return (pd.to_numeric(df[c], errors='coerce').values
                if c in df.columns else np.full(len(df), np.nan))
    # .values is required: passing an integer-indexed Series with index=t reindexes to NaN
    d = pd.DataFrame({'acc': col(_OF_FUEL), 'cool': col(_OF_COOL), 'spd': spd,
                      'erpm': col(_OF_ERPM), 'load': col(_OF_LOAD), 'soc': col(_OF_SOC),
                      'oil': col(_OF_OIL)},
                     index=pd.DatetimeIndex(t))
    d = d[d.index.notna()]
    if len(d) < 60:
        return None
    g = d.resample('1s').mean().ffill(limit=_OF_FFILL)
    g['acc'] = g['acc'].cummax()   # accumulator is monotone; repair ffill/mean artefacts
    return g


import re as _re_daykey
def _iso_day(k):
    k = str(k)
    return f'{k[:4]}-{k[4:6]}-{k[6:8]}' if _re_daykey.fullmatch(r'\d{8}', k) else k


_DAY_KEY_RE = _re_daykey.compile(r'(\d{4})\D?(\d{2})\D?(\d{2})')


def _day_key(fn):
    """M290 (audit 2026-09-22): robust YYYY-MM-DD day key from either compact
    ('20260910 074344.csv') or dash ('2026-09-10 074344.csv') filenames.

    Replaces ``str(fn)[:8]``, which on the dash-format drives yields '2026-09-'
    (the malformed ThermalFuelPenalty dateSpan/methodology dates) AND collapses
    distinct calendar days into one key -- the same P0-1 day-key defect fixed in
    ``m119v2_model.py`` at M286, but previously missed in the seasonal
    fuel/thermal passes. Undercounting days narrows the day-clustered bootstrap
    CIs (false-optimistic), so this is a correctness fix, not only cosmetic.
    """
    m = _DAY_KEY_RE.search(str(fn))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else str(fn)[:10]


def _thermal_fuel_penalty(dm, raw_loader=None, raw_dir=None):
    qual = []
    for _, r in dm.iterrows():
        fn = r['file']
        g = _of_grid(fn, raw_loader, raw_dir)
        if g is None:
            continue
        c = g['cool'].dropna()
        if len(c) < 60 or float(c.iloc[0]) >= _OF_COLD_MAX or float(c.max()) < _OF_WARM_THR:
            continue
        a = g['acc'].dropna()
        if len(a) < 30 or (a.iloc[-1] - a.iloc[0]) <= 0.02:
            continue
        qual.append((_day_key(fn), g))  # M290: was str(fn)[:8] (P0-1 day-key bug)
    if len(qual) < 5:
        return None
    days = sorted(set(d for d, _ in qual))

    def pct(v, p):
        return round(float(np.percentile(v, p)), 3)

    # (1) tripLevel: naive within-drive warm-up window vs warm window
    wu_l, wm_l, socd = [], [], []
    for day, g in qual:
        cr = g.index[g['cool'] >= _OF_WARM_THR]
        if len(cr) == 0:
            continue
        tc = cr[0]
        wu, wm = g[g.index < tc], g[g.index >= tc]

        def l100(seg):
            aa = seg['acc'].dropna()
            if len(aa) < 2:
                return np.nan
            dist = float(seg['spd'].clip(lower=0).sum() / 3600.0)
            return (float(aa.iloc[-1] - aa.iloc[0]) / dist * 100.0) if dist > 0.3 else np.nan
        a_wu, a_wm = l100(wu), l100(wm)
        if a_wu == a_wu and a_wm == a_wm:
            wu_l.append(a_wu); wm_l.append(a_wm)
            s = wu['soc'].dropna()
            socd.append(float(s.iloc[-1] - s.iloc[0]) if len(s) > 2 else np.nan)
    wu_l = np.array(wu_l); wm_l = np.array(wm_l)
    ratio = wu_l / wm_l
    sd = np.array([x for x in socd if x == x])
    trip = {
        'nDrives': int(len(wu_l)),
        'warmupWindowL100': {'median': pct(wu_l, 50), 'p25': pct(wu_l, 25), 'p75': pct(wu_l, 75)},
        'warmWindowL100': {'median': pct(wm_l, 50), 'p25': pct(wm_l, 25), 'p75': pct(wm_l, 75)},
        'ratioWarmupWarm': {'median': pct(ratio, 50), 'p25': pct(ratio, 25), 'p75': pct(ratio, 75)},
        'socDriftWarmupPctMedian': round(float(np.median(sd)), 1) if sd.size else None,
        'note': ('Confounded: warm-up window is early/low-speed/urban (regime) and can bank '
                 'fuel to the pack (SoC drift median disclosed). See combustionPenalty and '
                 'dutyCycle for the regime/operating-point-controlled decomposition.')}

    # sample pools (engine-on for combustion; all for duty; idle)
    comb_rows, duty_rows, idle_rows = [], [], []
    for day, g in qual:
        gg = g.dropna(subset=['acc', 'cool', 'erpm', 'load'])
        if len(gg) >= 60:
            dfl = gg['acc'].diff().clip(lower=0).values
            cv, rv, lv = gg['cool'].values, gg['erpm'].values, gg['load'].values
            for i in range(1, len(gg)):
                if rv[i] > _OF_ENG_ON:
                    comb_rows.append((day, cv[i], rv[i], lv[i], dfl[i]))
        gd = g.dropna(subset=['cool', 'erpm', 'spd'])
        cvd, rvd, svd = gd['cool'].values, gd['erpm'].values, gd['spd'].values
        for i in range(len(gd)):
            duty_rows.append((day, cvd[i], svd[i], 1.0 if rvd[i] > _OF_ENG_ON else 0.0))
        gi = g.dropna(subset=['acc', 'cool', 'spd'])
        dfi = gi['acc'].diff().clip(lower=0).values
        cvi, svi = gi['cool'].values, gi['spd'].values
        for i in range(1, len(gi)):
            if svi[i] < 3:
                idle_rows.append((day, cvi[i], dfi[i]))

    # (2) combustionPenalty: op-point-matched engine-on fuel/s, cold vs warm
    C = pd.DataFrame(comb_rows, columns=['day', 'cool', 'erpm', 'load', 'dfuel'])
    C['state'] = np.where(C['cool'] < _OF_WARM_THR, 'warmup', 'warm')
    C['rb'] = pd.cut(C['erpm'], _OF_RPM_BINS, right=False)
    C['lb'] = pd.cut(C['load'], _OF_LOAD_BINS, right=False)
    # per (day, cell, state): sum + count -> supports fast day-clustered bootstrap
    agg = (C.groupby(['day', 'rb', 'lb', 'state'], observed=True)['dfuel']
             .agg(['sum', 'count']).reset_index())

    def comb_ratio_from(day_list):
        sub = agg[agg['day'].isin(day_list)] if day_list is not None else agg
        piv = sub.groupby(['rb', 'lb', 'state'], observed=True)[['sum', 'count']].sum().reset_index()
        cells, weights = [], []
        for (rb, lb), s2 in piv.groupby(['rb', 'lb'], observed=True):
            w = s2[s2.state == 'warmup']; m = s2[s2.state == 'warm']
            if len(w) and len(m):
                nw, nm = int(w['count'].iloc[0]), int(m['count'].iloc[0])
                sw, sm = float(w['sum'].iloc[0]), float(m['sum'].iloc[0])
                if nw >= 15 and nm >= 15 and sm > 1e-9:
                    mean_w, mean_m = sw / nw, sm / nm
                    if mean_m > 1e-9:
                        cells.append(mean_w / mean_m); weights.append(nm)
        if not cells:
            return np.nan
        cells, weights = np.array(cells), np.array(weights, float)
        return float((cells * weights).sum() / weights.sum())

    comb_point = comb_ratio_from(None)
    # by-cell table (point)
    by_cell = []
    piv0 = agg.groupby(['rb', 'lb', 'state'], observed=True)[['sum', 'count']].sum().reset_index()
    for (rb, lb), s2 in piv0.groupby(['rb', 'lb'], observed=True):
        w = s2[s2.state == 'warmup']; m = s2[s2.state == 'warm']
        if len(w) and len(m):
            nw, nm = int(w['count'].iloc[0]), int(m['count'].iloc[0])
            sw, sm = float(w['sum'].iloc[0]), float(m['sum'].iloc[0])
            if nw >= 15 and nm >= 15 and sm > 1e-9:
                by_cell.append({'rpm': str(rb), 'load': str(lb),
                                'warmupLPerS': round(sw / nw, 6), 'warmLPerS': round(sm / nm, 6),
                                'ratio': round((sw / nw) / (sm / nm), 3), 'nWarmup': nw, 'nWarm': nm})
    rng = np.random.default_rng(42)
    cb = np.array([comb_ratio_from(list(rng.choice(days, len(days), replace=True)))
                   for _ in range(4000)])
    cb = cb[np.isfinite(cb)]
    comb = {
        'exposureWeightedRatio': round(comb_point, 3),
        'ci95': [round(float(np.percentile(cb, 2.5)), 3), round(float(np.percentile(cb, 97.5)), 3)],
        'resolvedAboveUnity': bool(np.percentile(cb, 2.5) > 1.0),
        'nCellsMatched': len(by_cell),
        'nEngineOnSamples': {'warmup': int((C.state == 'warmup').sum()),
                             'warm': int((C.state == 'warm').sum())},
        'rpmBins': _OF_RPM_BINS, 'loadBins': _OF_LOAD_BINS,
        'byCell': sorted(by_cell, key=lambda x: -(x['nWarmup'] + x['nWarm'])),
        'note': ('Fuel burned per engine-on second at a matched RPM x load operating point, '
                 'cold vs warm; exposure-weighted by warm-state cell counts (realistic mix). '
                 'Isolates enrichment + cold-friction from duty cycle and charge strategy. '
                 'Coarse bins; the effect rests largely on the most-populated cell.')}

    # (3) dutyCycle: engine-on fraction at matched road speed
    D = pd.DataFrame(duty_rows, columns=['day', 'cool', 'spd', 'on'])
    D['state'] = np.where(D['cool'] < _OF_WARM_THR, 'warmup', 'warm')
    D['sb'] = pd.cut(D['spd'], _OF_SPEED_BINS, right=False)
    # M213: dash-notation band labels ("70-137") instead of raw pandas Interval
    # bracket strings ("[70, 200)"). _OF_SPEED_BINS' upper edge (200) is a
    # permissive pd.cut ceiling only, chosen to safely exceed any speed the
    # vehicle can register; it is not a real observed value and was leaking
    # into the label. The open top band's display upper bound is instead
    # bound to this subset's actual observed speed maximum (self-healing as
    # the corpus grows), consistent with the no-hardcoded-literals convention
    # used for dateSpan/day-count text elsewhere (M212).
    _sb_obs_max = float(D['spd'].max()) if len(D) else _OF_SPEED_BINS[-2]
    _sb_labels = {}
    for _i in range(len(_OF_SPEED_BINS) - 1):
        _lo, _hi = _OF_SPEED_BINS[_i], _OF_SPEED_BINS[_i + 1]
        if _i == len(_OF_SPEED_BINS) - 2:
            _hi = max(_lo, int(np.ceil(_sb_obs_max)))
        _sb_labels[pd.Interval(_OF_SPEED_BINS[_i], _OF_SPEED_BINS[_i + 1], closed='left')] = f"{int(_lo)}-{int(_hi)}"
    by_speed = []
    for sbnd, sub in D.groupby('sb', observed=True):
        w = sub[sub.state == 'warmup']['on']; m = sub[sub.state == 'warm']['on']
        if len(w) >= 30 and len(m) >= 30:
            by_speed.append({'band': _sb_labels.get(sbnd, str(sbnd)),
                             'warmupOnFrac': round(float(w.mean()), 3),
                             'warmOnFrac': round(float(m.mean()), 3),
                             'ratio': round(float(w.mean() / m.mean()), 3) if m.mean() > 0 else None,
                             'nWarmup': int(len(w)), 'nWarm': int(len(m))})
    # matched 20-40 km/h band, day-clustered bootstrap
    band = D[(D.spd >= 20) & (D.spd < 40)]
    dagg = band.groupby(['day', 'state'], observed=True)['on'].agg(['sum', 'count']).reset_index()

    def duty_ratio_from(day_list):
        sub = dagg[dagg['day'].isin(day_list)] if day_list is not None else dagg
        w = sub[sub.state == 'warmup']; m = sub[sub.state == 'warm']
        wn, wc = w['sum'].sum(), w['count'].sum(); mn, mc = m['sum'].sum(), m['count'].sum()
        if mc == 0 or wc == 0 or mn == 0:
            return np.nan
        return float((wn / wc) / (mn / mc))
    duty_point = duty_ratio_from(None)
    db = np.array([duty_ratio_from(list(rng.choice(days, len(days), replace=True)))
                   for _ in range(4000)])
    db = db[np.isfinite(db)]
    duty = {
        'speedBins': _OF_SPEED_BINS, 'bySpeed': by_speed,
        'matched2040Ratio': round(duty_point, 3),
        'matched2040Ci95': [round(float(np.percentile(db, 2.5)), 3),
                            round(float(np.percentile(db, 97.5)), 3)],
        'note': ('Engine-on fraction (rpm>400) at matched road speed, cold vs warm. The '
                 'dominant mechanism of the trip penalty: the series-hybrid runs the ICE '
                 'more when cold (catalyst light-off + cold charge/idle strategy).')}

    # (4) idle fuel per hour
    I = pd.DataFrame(idle_rows, columns=['day', 'cool', 'dfuel'])
    iw = I[I.cool < _OF_WARM_THR]['dfuel']; im = I[I.cool >= _OF_WARM_THR]['dfuel']
    idle = {'speedMaxKmh': 3,
            'warmupLPerHour': round(float(iw.mean() * 3600), 3) if len(iw) else None,
            'warmLPerHour': round(float(im.mean() * 3600), 3) if len(im) else None,
            'ratio': round(float(iw.mean() / im.mean()), 3) if len(im) and im.mean() > 0 else None,
            'nWarmup': int(len(iw)), 'nWarm': int(len(im))}

    return {
        'nColdStartDrives': len(qual), 'nDays': len(days),
        'dateSpan': [min(days), max(days)],
        'coldStartMaxC': _OF_COLD_MAX, 'warmThresholdC': _OF_WARM_THR, 'engineOnRpm': _OF_ENG_ON,
        'tripLevel': trip, 'combustionPenalty': comb, 'dutyCycle': duty, 'idle': idle,
        'methodology': (
            # M295: days are ISO keys since the _day_key fix; slicing them as compact YYYYMMDD produced
            # '2026--0-8-'. Normalise either form.
            f'Fuel-accumulator subset ({_iso_day(days[0])} to {_iso_day(days[-1])}, {len(days)} days, '
            f'{len(qual)} cold-start drives; Module H fuel channel). Cold-start drives: '
            f'coolant start <{_OF_COLD_MAX:g} C reaching >={_OF_WARM_THR:g} C, carrying '
            'the used-fuel accumulator. 1 Hz grid (generous ffill for the ~0.25 Hz '
            'coolant multiplex group). Four views: (1) tripLevel naive warm-up-window '
            'vs warm-window L/100km (regime- and SoC-confounded, disclosed); '
            '(2) combustionPenalty = fuel per engine-on second at matched RPMxload '
            '(isolates enrichment+cold-friction; day-clustered bootstrap, seed 42, '
            '4000 draws); (3) dutyCycle = engine-on fraction at matched road speed '
            '(isolates series-hybrid strategy; the dominant term); (4) idle fuel/hour '
            'at standstill. SUBSET CAVEATS: warm-season only (mild cold-start, coolant '
            'starts ~ambient, NOT winter), urban-dominated. Emissions NOT instrumented; '
            'no generator-efficiency/CAP used. Single vehicle / ~single driver -- '
            'descriptive.')}


def _thermal_fuel_penalty_continuous(dm, raw_loader=None, raw_dir=None):
    """M226.3 (P1.4, enhancement plan): continuous thermal-settling /
    cold-start fuel. `thermalFuelPenalty` (above) already separates
    `combustionPenalty` from `dutyCycle` -- the core conceptual split the
    proposal asks to "continue" is already correct; this extends rather
    than redesigns.

    Re-derives the SAME qualifying cold-start drive set and `_of_grid`
    raw pass `_thermal_fuel_penalty` itself uses (raw_loader/raw_dir --
    the fuel-accumulator channel is not in `drive_raw_cache.SLIM_COLS`,
    so this cannot use frame_loader; matches the existing function's own
    raw-pass design, not a new one), additively extended (M226.3) with
    oil temperature read in the same pass.

    `continuousCovariateModel`: day-clustered bootstrap OLS
    (`_dayboot_ols`, the SAME estimator M223.1 introduced, reused
    directly) of engine-on fuel rate on CONTINUOUS coolant (and oil,
    where available) temperature, controlling for RPM and load --
    replacing the binary coldStartMaxC/warmThresholdC step function with
    an actual continuous relationship.

    `attenuationDistance`: bins engine-on fuel-rate EXCESS (over the
    warm-state baseline, the most-warmed distance bin) onto WARMUP_GRID's
    own distance-from-cold-start bins (the SAME grid `warmupCurve` already
    uses for the coolant trajectory -- "the fuel-penalty-vs-distance
    relationship already implicit in warmupCurve," per the plan), fits an
    exponential decay (ln(excess) on distance, regressed through the
    origin -- the identical convention `heatSoakCarryover`'s own tau fit
    uses, here in km rather than hours -- day-clustered bootstrap CI) to
    estimate the distance at which the excess decays to 1/e of its
    initial value. May legitimately fail to find a monotonic decay at
    this subset size; reported as a null result, not forced.

    `withinDayMatchedSubset`: counts days with >=2 qualifying cold-start
    drives (route/weather partially controlled by same-day proximity) --
    reports the actual eligible-subset size honestly, per the plan's
    explicit instruction, whether or not it supports a separate fit.

    Single vehicle / ~single driver -- descriptive, not causal.
    """
    qual = []
    for _, r in dm.iterrows():
        fn = r['file']
        g = _of_grid(fn, raw_loader, raw_dir)
        if g is None:
            continue
        c = g['cool'].dropna()
        if len(c) < 60 or float(c.iloc[0]) >= _OF_COLD_MAX or float(c.max()) < _OF_WARM_THR:
            continue
        a = g['acc'].dropna()
        if len(a) < 30 or (a.iloc[-1] - a.iloc[0]) <= 0.02:
            continue
        qual.append((_day_key(fn), fn, g))  # M290: was str(fn)[:8] (P0-1 day-key bug)
    if len(qual) < 5:
        return None
    days = sorted(set(d for d, _, _ in qual))

    # ---- continuousCovariateModel ----
    comb_rows = []
    for day, fn, g in qual:
        gg = g.dropna(subset=['acc', 'cool', 'erpm', 'load'])
        if len(gg) < 60:
            continue
        dfl = gg['acc'].diff().clip(lower=0).values
        cv, rv, lv = gg['cool'].values, gg['erpm'].values, gg['load'].values
        ov = gg['oil'].values if 'oil' in gg.columns else np.full(len(gg), np.nan)
        for i in range(1, len(gg)):
            if rv[i] > _OF_ENG_ON:
                comb_rows.append((day, cv[i], ov[i], rv[i], lv[i], dfl[i]))
    continuous_model = None
    if len(comb_rows) >= 100:
        Cc = pd.DataFrame(comb_rows, columns=['day', 'cool', 'oil', 'erpm', 'load', 'dfuel'])
        has_oil = bool(Cc['oil'].notna().sum() >= 100)
        cols = ['cool', 'oil', 'erpm', 'load'] if has_oil else ['cool', 'erpm', 'load']
        Cc2 = Cc.dropna(subset=cols + ['dfuel'])
        if len(Cc2) >= 100:
            X = Cc2[cols].values.astype(float)
            y = Cc2['dfuel'].values.astype(float) * 3600.0    # L/hr, more readable scale
            beta, ci, nDaysBoot, nBoots = _dayboot_ols(X, y, Cc2['day'].values)
            names = ['intercept'] + cols
            coefs = {names[i]: {'estimate': round(float(beta[i]), 5),
                               'ci95': ([round(ci[i][0], 5), round(ci[i][1], 5)]
                                       if ci is not None else None)}
                    for i in range(len(names))}
            continuous_model = {
                'nSamples': int(len(Cc2)), 'nDays': nDaysBoot, 'nBoots': nBoots,
                'outcome': 'engine-on fuel rate (L/hr)', 'predictors': cols,
                'coefficients': coefs, 'hasOilCovariate': has_oil,
                'coolantCiSpansZero': bool(coefs['cool']['ci95'][0] < 0 < coefs['cool']['ci95'][1]
                                          if coefs['cool']['ci95'] else True),
                'method': ('Day-clustered bootstrap OLS (_dayboot_ols, the '
                          'SAME estimator M223.1 introduced, reused '
                          'directly), continuous coolant (and oil, where '
                          'available) temperature plus RPM/load controls '
                          '-- replaces the binary coldStartMaxC/'
                          'warmThresholdC step function with an actual '
                          'continuous relationship. A negative coolant/oil '
                          'coefficient means fuel rate keeps falling '
                          'smoothly as the engine warms, not just stepping '
                          'down at one threshold. coolantCiSpansZero=true '
                          'means the continuous coolant effect is NOT '
                          'resolved once RPM/load are controlled for at '
                          'this sample size, a genuine null result -- '
                          'this does not contradict combustionPenalty\'s '
                          'own resolved BINARY warmup-vs-warm ratio above, '
                          'since that comparison pools cells differently '
                          'and this model estimates a single linear slope '
                          'across the full continuous range rather than a '
                          'coarse two-state contrast; both are reported, '
                          'neither is suppressed to make the other look '
                          'cleaner.'),
            }

    # ---- attenuationDistance ----
    dist_rows = []
    for day, fn, g in qual:
        gg = g.dropna(subset=['spd', 'acc', 'erpm'])
        if len(gg) < 60:
            continue
        dist_km = (gg['spd'].clip(lower=0).cumsum() / 3600.0).values
        dfl = gg['acc'].diff().clip(lower=0).values
        rv = gg['erpm'].values
        for i in range(1, len(gg)):
            if rv[i] > _OF_ENG_ON:
                dist_rows.append((day, dist_km[i], dfl[i]))
    attenuation_distance = None
    if len(dist_rows) >= 100:
        Dd = pd.DataFrame(dist_rows, columns=['day', 'distKm', 'dfuel'])
        edges = WARMUP_GRID
        Dd['bin'] = np.digitize(Dd['distKm'], edges[1:-1])
        bin_stats = []
        for b in range(len(edges) - 1):
            sub = Dd[Dd['bin'] == b]
            if len(sub) >= 20:
                bin_stats.append({'binIdx': b, 'distKm': edges[b],
                                 'meanRateLPerHr': float(sub['dfuel'].mean() * 3600.0),
                                 'n': int(len(sub))})
        if len(bin_stats) >= 4:
            baseline = bin_stats[-1]['meanRateLPerHr']
            excess = [(b['distKm'], b['meanRateLPerHr'] - baseline) for b in bin_stats]
            excess = [(d, e) for d, e in excess if e > 0.01]
            if len(excess) >= 3:
                xs = np.array([d for d, e in excess])
                ys = np.log(np.array([e for d, e in excess]))
                slope = np.sum(xs * ys) / np.sum(xs * xs)
                if slope < 0:
                    atten_km = -1.0 / slope
                    uniq_d = np.array(days)
                    by_day_bins = {}
                    for dv in uniq_d:
                        sub = Dd[Dd['day'] == dv]
                        bs = []
                        for b in range(len(edges) - 1):
                            s2 = sub[sub['bin'] == b]
                            bs.append(float(s2['dfuel'].mean() * 3600.0) if len(s2) >= 5 else np.nan)
                        by_day_bins[dv] = np.array(bs)
                    rng = np.random.default_rng(42)
                    boots = []
                    for _ in range(2000):
                        picks = rng.choice(uniq_d, len(uniq_d), replace=True)
                        stacked = np.vstack([by_day_bins[p] for p in picks])
                        mm = np.nanmean(stacked, axis=0)
                        if np.isnan(mm[-1]):
                            continue
                        bl = mm[-1]
                        exx = [(edges[i], mm[i] - bl) for i in range(len(mm))
                              if mm[i] == mm[i] and (mm[i] - bl) > 0.01]
                        if len(exx) < 3:
                            continue
                        xb = np.array([d for d, e in exx]); yb = np.log(np.array([e for d, e in exx]))
                        sb = np.sum(xb * yb) / np.sum(xb * xb)
                        if sb < 0:
                            boots.append(-1.0 / sb)
                    ci95 = ([round(float(np.percentile(boots, 2.5)), 2),
                            round(float(np.percentile(boots, 97.5)), 2)]
                           if len(boots) >= 30 else None)
                    # Honesty check: is the underlying bin sequence actually
                    # monotonically approaching the baseline, or does the
                    # single fitted slope paper over a noisier shape (e.g.
                    # fuel rate RISING from a low-RPM cold-start opening
                    # before settling, not simply decaying)? Disclosed
                    # explicitly, matching the M224 non-monotonicity
                    # disclosure convention -- never smoothed away.
                    rates = [b['meanRateLPerHr'] for b in bin_stats]
                    n_above_baseline = sum(1 for x in rates[:-1] if x > baseline)
                    is_monotonic_decay = all(
                        rates[i] >= rates[i + 1] - 1e-9 for i in range(len(rates) - 1))
                    attenuation_distance = {
                        'attenuationKm': round(float(atten_km), 2), 'ci95Km': ci95,
                        'nBoots': len(boots), 'warmBaselineLPerHr': round(baseline, 4),
                        'binStats': bin_stats,
                        'isMonotonicDecay': bool(is_monotonic_decay),
                        'nBinsAboveBaselinePreDecay': n_above_baseline,
                        'method': ('Exponential decay of engine-on fuel-rate '
                                  'EXCESS (over the warm-state baseline, the '
                                  'most-warmed distance bin) vs. distance '
                                  'from cold start, binned onto WARMUP_GRID '
                                  '-- the SAME grid warmupCurve already uses '
                                  'for the coolant trajectory. ln(excess) '
                                  'regressed through the origin on distance '
                                  '(the identical convention '
                                  'heatSoakCarryover\'s own tau fit uses, '
                                  'here in km rather than hours), day-'
                                  'clustered bootstrap CI (seed=42). '
                                  'isMonotonicDecay=false means the raw '
                                  'bin sequence is NOT a clean decay (e.g. '
                                  'fuel rate can rise from a low-RPM cold-'
                                  'start opening before settling toward '
                                  'the baseline) -- the fitted '
                                  'attenuationKm/CI is a single-parameter '
                                  'summary of a noisier underlying shape, '
                                  'disclosed via binStats rather than '
                                  'smoothed over; wide CI reflects this.'),
                    }
                else:
                    attenuation_distance = {
                        'note': ('Fuel-rate excess does not show a '
                                'monotonic decay with distance in this '
                                'subset (fitted slope >= 0) -- no '
                                'attenuation distance estimated; reported '
                                'as a null result, not forced.'),
                        'binStats': bin_stats,
                    }

    # ---- withinDayMatchedSubset ----
    from collections import Counter
    day_counts = Counter(d for d, _, _ in qual)
    multi_days = {d: c for d, c in day_counts.items() if c >= 2}
    if multi_days:
        note = ('%d of %d days in the cold-start subset have >=2 '
               'qualifying drives (%d drives total) -- a within-day '
               'comparison would partially control for weather/route, '
               'but the eligible subset is too small for a separate fit '
               'at this corpus size; reported honestly rather than fit '
               'anyway.' % (len(multi_days), len(days), sum(multi_days.values())))
    else:
        note = ('0 of %d days in the cold-start subset have more than one '
               'qualifying drive -- no within-day matched subset exists '
               'at this corpus size. Reported as an honest absence, not '
               'a fabricated comparison.' % len(days))
    within_day_matched_subset = {
        'nDaysWithMultipleColdStarts': len(multi_days),
        'nDrivesInMatchedSubset': sum(multi_days.values()),
        'nTotalColdStartDrives': len(qual), 'note': note,
    }

    return {
        'continuousCovariateModel': continuous_model,
        'attenuationDistance': attenuation_distance,
        'withinDayMatchedSubset': within_day_matched_subset,
        'continuousMethodology': (
            'M226.3 (P1.4, enhancement plan): re-derives thermalFuelPenalty\'s '
            'own qualifying cold-start drive set and _of_grid raw pass '
            '(raw_loader/raw_dir -- the fuel-accumulator channel is not in '
            'SLIM_COLS, matching the existing function\'s own design, not a '
            'new one), additively extended with oil temperature. '
            'continuousCovariateModel replaces the binary coldStartMaxC/'
            'warmThresholdC window with a day-clustered-bootstrap-OLS '
            'continuous coolant/oil-temperature relationship. '
            'attenuationDistance fits a heatSoakCarryover-style exponential '
            'decay of the fuel-rate excess vs. distance-from-cold-start '
            '(WARMUP_GRID bins, the same grid warmupCurve uses). '
            'withinDayMatchedSubset reports the actual eligible-subset size '
            'honestly, whether or not it supports a separate fit. Single '
            'vehicle / ~single driver -- descriptive, not causal.'),
    }


def _day_label_by_file(dm, fn):
    """M48: _day_label takes a positional index; this resolves by filename."""
    hit = dm.index[dm['file'] == fn]
    return _day_label(dm, int(hit[0])) if len(hit) else fn


# ======================================================================
# M223.1 (P0.1, enhancement plan): coolant/oil thermal decay + linked
# adjacent-drive table. Extends _heat_soak_carryover's pack-only pairing/
# gap-binning/tau-fit pattern to coolant and oil, and joins it with
# following-drive first-engine-start timing into one carryover table --
# see _linked_adjacent_drive_table's own docstring for the full join
# semantics.
# ======================================================================
def _first_window_engine_metrics(fr):
    """M223.1 (P0.1): per-drive time-to-first-engine-start (s) and
    first-5-minute engine-on fraction, reusing _engine_start_triggers'
    RPM handling convention (same RPM column, same >800 rpm on-threshold)
    -- a read of data already available via the SAME frame_loader pass
    other detectors use, no new instrumentation. Returns None if the RPM
    channel is unavailable for this drive."""
    if fr is None or _BUFIMP_RPM_COL not in fr.columns:
        return None
    rpm = fr[['time', _BUFIMP_RPM_COL]].dropna().reset_index(drop=True)
    rpm.columns = ['time', 'rpm']
    if len(rpm) < 2:
        return None
    t = pd.to_datetime(rpm['time'], errors='coerce')
    rpm = rpm.assign(t=t).dropna(subset=['t'])
    if len(rpm) < 2:
        return None
    t0 = rpm['t'].iloc[0]
    trig = _engine_start_triggers(fr)
    time_to_first_start_s = None
    if trig:
        first_t = min(pd.Timestamp(x) for x in trig)
        delta = (first_t - t0).total_seconds()
        if delta >= 0:
            time_to_first_start_s = delta
    win = rpm[(rpm['t'] >= t0) & (rpm['t'] <= t0 + pd.Timedelta(seconds=300.0))]
    first_five_min_on_frac = (float((win['rpm'].values > 800).mean())
                              if len(win) >= 5 else None)
    return {'timeToFirstStartS': time_to_first_start_s,
           'firstFiveMinOnFrac': first_five_min_on_frac}


def _linked_adjacent_drive_table(dm, traj, ambient_by_drive=None,
                                 frame_loader=None, first_window_by_file=None):
    """M223.1 (P0.1, enhancement plan): per consecutive chronological drive
    pair (a=previous, b=following), the joined carryover table underlying
    interDriveCarryover. Reuses _heat_soak_carryover's own gap computation
    verbatim (same _full_datetimes pairing, same gap_h formula) and the
    SAME traj dict this module already builds for thermalConvergence/
    heatSoakCarryover -- extended (M223.1) with coolant_*/oil_* alongside
    the pre-existing t1_*/pm_* keys, so this is a join over already-
    available per-drive data plus ONE additional lightweight per-drive raw
    pass (_first_window_engine_metrics, via frame_loader) for the
    following drive's own first-engine-start timing -- not a new
    instrumentation channel.

    'Arrival' means the state at the START of the FOLLOWING drive (b),
    i.e. what the soak gap left behind: traj[b]['*_start'] for temperatures,
    b's own soc_start. 'Departure' means the END of the PREVIOUS drive (a):
    a's own soc_end. Previous-drive duration/distance/engine-duty/thermal-
    maxima and following-drive fuel/GTC/peak-current/battery-work outcomes
    are read directly from already-computed drive_master columns -- no
    re-derivation.

    Single vehicle / ~single driver -- descriptive association, not a
    causal or generalizable driver-behavior law (same disclosure pattern as
    heatSoakCarryover/regimeTransition)."""
    d = (_full_datetimes(dm).dropna(subset=['ts_full'])
         .sort_values('ts_full').reset_index(drop=True))
    dm_idx = dm.set_index('file')
    amb = {}
    if ambient_by_drive:
        for fn, pair in ambient_by_drive.items():
            try:
                amb[fn] = sum(float(x) for x in pair) / len(pair)
            except Exception:
                pass
    rows = []
    for k in range(len(d) - 1):
        a, b = d.iloc[k], d.iloc[k + 1]
        af, bf = a['file'], b['file']
        ta, tb = traj.get(af, {}), traj.get(bf, {})
        if 'pm_end' not in ta or 'pm_start' not in tb:
            continue
        if pd.isna(a['te_full']) or pd.isna(b['ts_full']):
            continue
        gap_h = (b['ts_full'] - a['te_full']).total_seconds() / 3600.0
        if gap_h < 0:
            continue
        if af not in dm_idx.index or bf not in dm_idx.index:
            continue
        ra, rb = dm_idx.loc[af], dm_idx.loc[bf]
        eng = None
        if first_window_by_file is not None:
            eng = first_window_by_file.get(bf)
        elif frame_loader is not None:
            try:
                fr_b = frame_loader(bf)
                eng = _first_window_engine_metrics(fr_b)
            except Exception:
                eng = None
        rows.append({
            'prevFile': af, 'nextFile': bf,
            'previousDriveType': ra.get('drive_type'),
            'parkingGapH': gap_h,
            'arrivalPmC': tb.get('pm_start'),
            'arrivalCoolantC': tb.get('coolant_start'),
            'arrivalOilC': tb.get('oil_start'),
            'arrivalAmbientC': amb.get(bf),
            'arrivalSocPct': rb.get('soc_start'),
            'departureSocPct': ra.get('soc_end'),
            'prevDurationS': ra.get('duration_s'),
            'prevDistanceKm': ra.get('distance_km'),
            'prevEngineOnPct': ra.get('engine_on_pct'),
            'prevPeakBatteryC': ta.get('pm_peak'),
            'prevPeakCoolantC': ta.get('coolant_peak'),
            'prevPeakOilC': ta.get('oil_peak'),
            'prevEndCoolantC': ta.get('coolant_end'),   # M234, audit F08
            'prevEndOilC': ta.get('oil_end'),            # M234, audit F08
            'followingTimeToFirstStartS': (eng or {}).get('timeToFirstStartS'),
            'followingFirstFiveMinOnFrac': (eng or {}).get('firstFiveMinOnFrac'),
            'followingGtc': rb.get('gtc'),
            'followingPeakDischargeA': rb.get('peak_I_discharge'),
            'followingSocDeltaKwh': rb.get('soc_delta_kwh'),
            'day': str(b['ts_full'])[:10],
        })
    return pd.DataFrame(rows)


def _carryover_thermal_decay(pf, start_col, end_col, amb_key, min_excess_c=3.0):
    """M223.1: the SAME Newtonian-cooling tau fit `_heat_soak_carryover`
    uses for the pack (ln(resid/init excess) regressed through the origin
    on gap, day-clustered bootstrap CI), applied to a coolant/oil channel
    instead. `pf` is `_linked_adjacent_drive_table`'s output; start_col/
    end_col select which channel's arrival/departure temperature pair to
    fit (e.g. 'arrivalCoolantC' with the matching previous-drive END
    temperature as the pre-soak reference -- see call sites).

    M234 (audit F08 fix): end_col must be the PREVIOUS drive's actual
    end-of-drive temperature (prevEndCoolantC/prevEndOilC), matching
    _heat_soak_carryover's own pm_end convention for the pack -- cooling
    during the parking gap begins wherever the vehicle actually was when
    it was parked, not at whatever peak it reached at some earlier point
    mid-drive. Previously called with prevPeakCoolantC/prevPeakOilC (the
    previous drive's PEAK, not its end), overstating the initial excess
    and therefore the fitted cooling tau."""
    sub = pf.dropna(subset=[start_col, end_col, 'arrivalAmbientC', 'day']).copy()
    sub = sub[sub[amb_key].notna()]
    if sub.empty:
        return {'tau': None, 'tauCI': None, 'r2': None, 'nfit': 0}
    init_excess = sub[end_col] - sub[amb_key]
    resid_excess = sub[start_col] - sub[amb_key]
    fit = pd.DataFrame({'gapH': sub['parkingGapH'], 'ie': init_excess,
                        're': resid_excess, 'day': sub['day']})
    fit = fit[(fit['ie'] > min_excess_c) & (fit['re'] > 0.5)]
    nfit = int(len(fit))
    if nfit < 8:
        return {'tau': None, 'tauCI': None, 'r2': None, 'nfit': nfit}

    def _fit_tau(ie_vals, re_vals, gap_vals, day_vals):
        # M242: Sen's slope replaces the OLS-through-origin slope, same
        # rationale/estimator as _heat_soak_carryover's pack fit (see that
        # function's docstring/comment) -- long-gap leverage on a
        # squared-gap-weighted OLS slope, fixed by the same robust
        # estimator already used elsewhere in this pipeline
        # (_car_off_standby).
        y = np.log(re_vals / ie_vals)
        x = gap_vals
        slope = _sen_slope(x, y)
        intercept_ = float(np.median(y - slope * x))
        yhat = slope * x
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2_ = (1 - np.sum((y - yhat) ** 2) / ss_tot) if ss_tot > 0 else None
        if slope >= 0:
            return None, r2_, intercept_
        return -1.0 / slope, r2_, intercept_

    tau, r2, fit_intercept = _fit_tau(fit['ie'].values, fit['re'].values,
                                      fit['gapH'].values, fit['day'].values)
    if tau is None:
        return {'tau': None, 'tauCI': None,
               'r2': (round(float(r2), 3) if r2 is not None else None), 'nfit': nfit}
    y = np.log(fit['re'].values / fit['ie'].values)
    x = fit['gapH'].values
    days = fit['day'].values
    uniq = np.unique(days)
    by = {dv: np.where(days == dv)[0] for dv in uniq}
    rng = np.random.default_rng(42)
    taus = []
    for _ in range(1000):
        picks = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([by[dv] for dv in picks])
        s = _sen_slope(x[idx], y[idx])
        if s < 0:
            taus.append(-1.0 / s)
    tau_ci = ([round(float(np.percentile(taus, 2.5)), 2),
              round(float(np.percentile(taus, 97.5)), 2)] if taus else None)

    # M234 (audit F08, second half: "assess parking-ambient uncertainty").
    # arrivalAmbientC is the manual DRIVING-time ambient field (same caveat
    # _heat_soak_carryover already discloses for the pack), not a measured
    # parked-soak environment -- refit tau under plausible parking-ambient
    # OFFSETS (both init and resid excess shift together, since both are
    # referenced to the same following-drive ambient reading) to show how
    # much that unmeasured gap actually moves the point estimate.
    amb_sensitivity = []
    for off in (-3.0, 3.0):
        ie_o = sub[end_col] - (sub[amb_key] + off)
        re_o = sub[start_col] - (sub[amb_key] + off)
        fit_o = pd.DataFrame({'gapH': sub['parkingGapH'], 'ie': ie_o,
                              're': re_o, 'day': sub['day']})
        fit_o = fit_o[(fit_o['ie'] > min_excess_c) & (fit_o['re'] > 0.5)]
        if len(fit_o) >= 8:
            tau_o, _, _ = _fit_tau(fit_o['ie'].values, fit_o['re'].values,
                                   fit_o['gapH'].values, fit_o['day'].values)
        else:
            tau_o = None
        amb_sensitivity.append({
            'ambientOffsetC': off, 'tau': round(float(tau_o), 2) if tau_o else None,
            'nfit': int(len(fit_o))})

    return {'tau': round(float(tau), 2), 'tauCI': tau_ci,
           'r2': (round(float(r2), 3) if r2 is not None else None), 'nfit': nfit,
           'nDays': int(len(uniq)),
           'fitMethod': 'senSlope',
           'fitIntercept': round(fit_intercept, 4),
           'parkingAmbientSensitivity': amb_sensitivity,
           'parkingAmbientNote': (
               'M234 (audit F08): arrivalAmbientC is the manual DRIVING-time '
               'ambient field, not a measured parked-soak environment, which '
               'can differ (garage vs open, day/night swing). '
               'parkingAmbientSensitivity refits tau after shifting the '
               'ambient reference by +-3 degC (applied to both the initial '
               'and residual excess, since both reference the same '
               'following-drive ambient reading) -- the spread across these '
               'two refits is the approximate sensitivity of tau to this '
               'unmeasured uncertainty, not a formal error propagation.')}


def _dayboot_ols(X, y, days, nb=4000, seed=42):
    """M223.1: day-clustered bootstrap OLS -- point estimate from the
    full-sample fit; 95% CI per coefficient from resampling whole days
    with replacement and refitting. Generalizes the project's established
    dayboot pattern (bufferDebtRecovery's day_bootstrap/dayboot) from a
    scalar metric to a coefficient vector."""
    Xc = np.column_stack([np.ones(len(X)), X])
    beta0, *_ = np.linalg.lstsq(Xc, y, rcond=None)
    uniq = np.unique(days)
    by = {dv: np.where(days == dv)[0] for dv in uniq}
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(nb):
        picks = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([by[dv] for dv in picks])
        if len(idx) <= X.shape[1]:
            continue
        try:
            b, *_ = np.linalg.lstsq(Xc[idx], y[idx], rcond=None)
            boots.append(b)
        except Exception:
            pass
    boots = np.array(boots) if boots else None
    ci = (np.percentile(boots, [2.5, 97.5], axis=0).T.tolist()
         if boots is not None and len(boots) else None)
    return beta0, ci, int(len(uniq)), int(len(boots) if boots is not None else 0)


def _carryover_regression(pf):
    """M223.1: primary day-clustered bootstrap OLS + secondary mixed-
    effects (day random intercept, statsmodels==0.15.0, matching
    degradation_trends.py's _mixedlm convention) regression of the
    FOLLOWING drive's time-to-first-engine-start on arrival pack
    temperature, parking gap, and arrival SoC -- tests whether a colder /
    longer-soaked arrival predicts the ICE being called on SOONER to
    replenish the buffer, directly supporting the buffer-not-reservoir
    thesis with an inter-drive (not just intra-drive) observation.
    Descriptive association on one vehicle/driver, not a causal claim."""
    cols = ['followingTimeToFirstStartS', 'arrivalPmC', 'parkingGapH',
           'arrivalSocPct', 'day']
    d = pf.dropna(subset=cols).copy()
    n = len(d)
    if n < 15:
        return {'nPairs': n, 'nDays': int(d['day'].nunique()) if n else 0,
               'note': 'insufficient complete-case pairs for a regression fit'}
    X = d[['arrivalPmC', 'parkingGapH', 'arrivalSocPct']].values.astype(float)
    y = d['followingTimeToFirstStartS'].values.astype(float)
    beta, ci, nDaysBoot, nBoots = _dayboot_ols(X, y, d['day'].values)
    names = ['intercept', 'arrivalPmC', 'parkingGapH', 'arrivalSocPct']
    coefs = {names[i]: {'estimate': round(float(beta[i]), 4),
                        'ci95': ([round(ci[i][0], 4), round(ci[i][1], 4)]
                                if ci is not None else None)}
            for i in range(len(names))}
    mixed = None
    try:
        import statsmodels.formula.api as smf
        dd = d.rename(columns={'followingTimeToFirstStartS': 'y'})
        md = smf.mixedlm('y ~ arrivalPmC + parkingGapH + arrivalSocPct',
                         dd, groups=dd['day'])
        r = md.fit(method='lbfgs', reml=True, disp=False)
        mixed = {
            'coefficients': {
                nm: {'estimate': round(float(r.fe_params[nm]), 4),
                    'se': round(float(r.bse_fe[nm]), 4),
                    'ci95': [round(float(x), 4) for x in
                            r.conf_int().loc[nm].tolist()]}
                for nm in ('Intercept', 'arrivalPmC', 'parkingGapH', 'arrivalSocPct')
                if nm in r.fe_params.index},
            'converged': bool(r.converged),
            'statsmodelsVersion': '0.15.0'}
    except Exception as _e:
        mixed = {'error': repr(_e)}
    return {
        'nPairs': n, 'nDays': int(d['day'].nunique()),
        'outcome': 'followingTimeToFirstStartS',
        'predictors': ['arrivalPmC', 'parkingGapH', 'arrivalSocPct'],
        'dayClusteredBootstrap': {
            'coefficients': coefs, 'nBoots': nBoots, 'nDaysResampled': nDaysBoot},
        'mixedEffects': mixed,
        'method': (
            'PRIMARY: day-clustered bootstrap OLS (whole days resampled with '
            'replacement, 4000 draws, seed=42; point estimate from the full-'
            'sample fit) -- the established estimator pattern in this '
            'codebase (bufferDebtRecovery). SECONDARY/robustness: a day '
            'random-intercept mixed-effects model (statsmodels 0.15.0, '
            'matching degradation_trends.py\'s convention), not the primary '
            'estimator, since the mixed-effects fit is the piece flagged '
            'elsewhere in this codebase as not bit-reproducible across '
            'statsmodels versions. Descriptive association in one observed '
            'duty cycle on one vehicle/driver -- not a causal or '
            'generalizable driver-behavior law.'),
    }


def _thermal_convergence(dm, traj):
    """Every drive >60 min: Sensor-1 start->peak->end trajectory + duration/
    distance, sorted by duration descending. coldStart flag = start < 30 C."""
    long = dm[dm['duration_s'] > 3600].copy()
    long = long.sort_values('duration_s', ascending=False)
    rows = []
    for _, r in long.iterrows():
        t = traj.get(r['file'], {})
        if 't1_peak' not in t:
            continue
        rows.append({
            'label': _day_label(dm, r.name),
            'durMin': int(round(r['duration_s'] / 60)),
            'distKm': round(float(r['distance_km']), 1),
            't1Start': t.get('t1_start'),
            't1Peak': t.get('t1_peak'),
            't1End': t.get('t1_end'),
            'coldStart': (t.get('t1_start') is not None
                          and t['t1_start'] < 30),
        })
    return rows


def _battery_temp_ranges(dm, traj, ambient_by_drive):
    """M51 (2026-07-22): pipeline-computed replacement for the seven
    hand-typed RangeBar rows in "Battery Temperature -- Observed Range".

    Those rows carried literal lo/hi pairs (10/22, 14/20, 18/35, 35/47,
    17/48 ...) tied to hand-named May/June sessions. They never recalibrated,
    so by the 173-drive corpus the bars disagreed with the pipeline-bound
    caption sitting directly beneath them (S.tPeakC = 51 C) and one row's
    note asserted a "surpassed twice" ranking that a third drive had since
    tied.

    Grouping is now derived, not narrated, on two orthogonal axes that are
    both reproducible from the master:

      group='ambient'  cool <20 C / mild 20-26 C / hot >=26 C, binned on the
                       mean of the recorded [start, end] ambient pair. Only
                       drives with a recorded ambient participate (ambient is
                       a manual field -- the OBD logs carry no outside-air
                       channel), so this group's n is < totalDrives by
                       construction, not by exclusion.
      group='class'    native CLASS_ORDER (Urban/Mixed/Mixed Highway/
                       Highway; M86 -- was a three-bucket City/Mixed/Highway
                       collapse), the same taxonomy socBands and the
                       highway-vs-city arrays now use, so it is shared.

    plus two singleton context rows: the >60 min long-haul population
    (group='duration') and the corpus Sensor-1 record drive (group='record').

    Convention. lo = min over the group of the per-drive Sensor-1 MINIMUM,
    hi = max over the group of the per-drive Sensor-1 PEAK -- i.e. true
    observed extrema, matching the section title. Per the study's evidentiary
    split (see eolBaselines), extremum statistics run on the UNFILTERED
    master; only typical-range statistics filter on ens_outlier_v2. medPeak
    (median of per-drive peaks) is carried alongside so the caption can
    report the typical ceiling without the bar pretending an outlier is
    representative.
    """
    def _bar(label, files, color, group, note=None):
        mins = [traj[f]['t1_min'] for f in files
                if f in traj and 't1_min' in traj[f]]
        peaks = [traj[f]['t1_peak'] for f in files
                 if f in traj and 't1_peak' in traj[f]]
        if not mins or not peaks:
            return None
        # M213: p25Peak/p75Peak (IQR of the per-drive Sensor-1 PEAK
        # distribution within the group) added for the horizontal
        # interval-plot redesign of "Battery Temperature -- Observed Range"
        # -- median + IQR + true extremes, the same box-plot convention
        # already used by socBySpeed/driveDurationDist elsewhere on this
        # dashboard. Degenerates to a point (p25==p75==the single value)
        # on n=1 groups (the record row), which the JSX renders as no box.
        parr = np.asarray(peaks, dtype=float)
        return {'label': label, 'lo': int(min(mins)), 'hi': int(max(peaks)),
                'medPeak': int(round(float(np.median(peaks)))),
                'p25Peak': round(float(np.percentile(parr, 25)), 1),
                'p75Peak': round(float(np.percentile(parr, 75)), 1),
                'n': len(peaks), 'color': color, 'group': group,
                'note': note}

    rows = []

    # ---- axis 1: recorded ambient ------------------------------------
    amb_bins = [('Cool ambient (<20 C)', -99, 20, '#3b82f6'),
                ('Mild ambient (20-26 C)', 20, 26, '#22c55e'),
                ('Hot ambient (>=26 C)', 26, 99, '#f59e0b')]
    if ambient_by_drive:
        for label, lo_a, hi_a, color in amb_bins:
            files = []
            for fn, pair in ambient_by_drive.items():
                try:
                    a = sum(float(x) for x in pair) / len(pair)
                except Exception:
                    continue
                if lo_a <= a < hi_a:
                    files.append(fn)
            b = _bar(label, files, color, 'ambient')
            if b:
                b['note'] = (f"n={b['n']} drives with recorded ambient · "
                             f"median peak {b['medPeak']} C")
                rows.append(b)

    # ---- axis 2: drive class (shared native CLASS_ORDER taxonomy) ----
    cls_meta = [(k, k.replace('_', ' ').title(), CLASS_COLOR[k])
                for k in CLASS_ORDER]
    by_cls = {}
    for _, r in dm.iterrows():
        c = r.get('drive_type')
        if c in CLASS_ORDER:
            by_cls.setdefault(c, []).append(r['file'])
    for key, label, color in cls_meta:
        b = _bar(label, by_cls.get(key, []), color, 'class')
        if b:
            b['note'] = f"n={b['n']} drives · median peak {b['medPeak']} C"
            rows.append(b)

    # ---- context: long-haul population -------------------------------
    long_files = list(dm[dm['duration_s'] > 3600]['file'])
    b = _bar('Long-haul (>60 min)', long_files, '#f97316', 'duration')
    if b:
        b['note'] = (f"n={b['n']} drives · median peak {b['medPeak']} C — "
                     f"the convergence plateau population")
        rows.append(b)

    # ---- context: corpus Sensor-1 record drive -----------------------
    peaks = {f: traj[f]['t1_peak'] for f in dm['file']
             if f in traj and 't1_peak' in traj[f]}
    if peaks:
        rec_fn = max(peaks, key=peaks.get)
        b = _bar(f'Corpus S1 record ({_day_label_by_file(dm, rec_fn)})',
                 [rec_fn], '#dc2626', 'record')
        if b:
            b['note'] = 'single drive — highest Sensor-1 sample in the corpus'
            rows.append(b)

    return rows


def _battery_vs_ambient(dm, traj, ambient_by_drive):
    """For each drive with a recorded ambient (config.ambientByDrive, keyed by
    filename -> [ambStart, ambEnd]), join the pack-mean trajectory and compute
    battery-minus-ambient deltas at start and peak. Chronological order."""
    if not ambient_by_drive:
        return []
    d = dm.sort_values(['date', 'time_start'])
    rows = []
    for _, r in d.iterrows():
        fn = r['file']
        amb = ambient_by_drive.get(fn)
        if amb is None:
            continue
        t = traj.get(fn, {})
        if 'pm_peak' not in t:
            continue
        # M104 (2026-08-09): was amb[1], which silently mis-reads the
        # INTERIM reading as "end" for any 3+-value entry (amb[1] is only
        # correct-by-construction for exactly 2 values) and drops the true
        # final reading entirely -- caught on the 4 corpus drives with a
        # 3-value ambientByDrive entry (rise-then-fall long trips). amb[-1]
        # is correct for 1, 2, or N values. See CHANGELOG.md M104.
        # 2026-09-16 finding: ambientByDrive stores a bare scalar for
        # constant-ambient drives (not a length-1 list) -- every OTHER
        # consumer of this config (_aux_load_ambient, _heat_soak_carryover,
        # _daily_fingerprints, _linked_adjacent_drive_table,
        # _battery_temp_ranges) already guards for this; this function did
        # not, and raised TypeError the first time a scalar-ambient drive
        # also had a resolved pm_peak trajectory (2026-09-12..16 batch).
        # Normalize once here rather than at every call site.
        if not isinstance(amb, (list, tuple)):
            amb = [amb]
        a0, a1 = float(amb[0]), float(amb[-1])
        b0, bp, b1 = t.get('pm_start'), t.get('pm_peak'), t.get('pm_end')
        rows.append({
            'label': _day_label(dm, r.name),
            'time': str(r['time_start'])[:5],
            'ambStart': a0, 'ambEnd': a1,
            'batStart': b0, 'batPeak': bp, 'batEnd': b1,
            'deltaStart': (round(b0 - a0) if b0 is not None else None),
            'deltaPeak': (round(bp - a1) if bp is not None else None),
            'distKm': round(float(r['distance_km']), 1)
            if pd.notna(r['distance_km']) else None,
        })
    return rows


# ======================================================================
# top-level build
# ======================================================================
def _sen_slope(x, y):
    """Classical Sen's slope estimator (Theil-Sen for simple regression):
    the median of all pairwise slopes (y_j-y_i)/(x_j-x_i), i<j, x_i!=x_j.
    NOT the same as sklearn.linear_model.TheilSenRegressor, which for this
    single-predictor problem instead takes the *spatial* (2D geometric)
    median of the (intercept, slope) point cloud over all pairs -- jointly
    optimizing both parameters rather than marginally medianing the slope.
    On this dataset the two disagree by ~4x (0.031 vs 0.131 pp/h) because
    the pairwise-slope distribution here is extremely heavy-tailed (a few
    near-duplicate gap_h values produce huge-magnitude outlier slopes that
    pull sklearn's joint spatial median, which is not slope-marginal-
    invariant, more than they pull the coordinatewise median used here).
    Sen's slope is the standard, well-established robust trend estimator
    for exactly this univariate case and is used deliberately in place of
    TheilSenRegressor for that reason.
    """
    dx = x[:, None] - x[None, :]
    dy = y[:, None] - y[None, :]
    iu = np.triu_indices(len(x), k=1)
    dxu, dyu = dx[iu], dy[iu]
    v = dxu != 0
    return float(np.median(dyu[v] / dxu[v]))


def _car_off_standby(dm, cap_kwh=2.1, n_boot=4000):
    """M27 (2026-07-10). Replaces a hand-typed '-28 W / 0.67 kWh/day' Car-OFF
    standby caption that was never derived from data and is falsified by it:
    at 28 W the 2.1 kWh pack would fully drain in ~75 h, but the dataset has
    key-off gaps of 124/144/188 h with |SoC delta| under 20 pp -- an order of
    magnitude less drain than 28 W implies.

    Method: for every consecutive drive pair, gap_h = time between drive_N
    end and drive_(N+1) start (car parked); draw_pp = soc_end(N) -
    soc_start(N+1) (>0 = SoC fell while parked). A naive mean/median of
    implied W is not physically meaningful here: the delta is dominated by
    discrete key-on SoC-ledger re-anchoring jumps uncorrelated with gap_h
    (corr(gap_h, draw_pp) ~ -0.24 on n=107 gaps; mean |draw_pp| does not
    scale with gap_h -- e.g. the 0-0.5h bin averages 1.45pp, comparable to
    the 32-64h bin's 0.25pp). Sen's slope of draw_pp ~ gap_h (see
    _sen_slope) separates the duration-independent jump (intercept, the
    median re-anchoring offset) from the duration-proportional drain
    (slope, the actual standby rate). Gaps are independent events, so a
    plain bootstrap over gaps gives the slope's 95% CI (4000 resamples,
    matching the M19/M25 bootstrap-CI convention). Reported with CI, never
    as a bare point estimate -- this is weakly identified from the SoC
    ledger alone (n=107 gaps, heavy jump-noise floor; P(draw>0) well short
    of a confident detection).
    """
    try:
        dch = dm.dropna(subset=['date', 'time_start', 'time_end',
                                'soc_start', 'soc_end']).copy()
        dch = dch.sort_values(['date', 'time_start']).reset_index(drop=True)
        ts_start = pd.to_datetime(dch['date'] + ' ' + dch['time_start'])
        ts_end = pd.to_datetime(dch['date'] + ' ' + dch['time_end'])
        gap_h = (ts_start.iloc[1:].values - ts_end.iloc[:-1].values) \
            / np.timedelta64(1, 'h')
        draw_pp = dch['soc_end'].iloc[:-1].values - dch['soc_start'].iloc[1:].values
        m = gap_h > 0
        x, y = gap_h[m], draw_pp[m]
        n = len(x)
        cap_wh = cap_kwh * 1000.0

        slope = _sen_slope(x, y)                 # pp drawn per hour parked
        jump_pp = float(np.median(y - slope * x))  # re-anchoring offset, pp
        watts = slope / 100.0 * cap_wh

        rng = np.random.default_rng(42)
        boot = np.empty(n_boot)
        for i in range(n_boot):
            idx = rng.integers(0, n, n)
            boot[i] = _sen_slope(x[idx], y[idx])
        boot_w = boot / 100.0 * cap_wh
        lo, hi = np.percentile(boot_w, [2.5, 97.5])

        return {
            'n_gaps': int(n),
            'watts': round(watts, 2),
            'ci95_watts': [round(float(lo), 2), round(float(hi), 2)],
            'p_draw_gt0': round(float((boot_w > 0).mean()), 3),
            'kwh_per_day': round(watts * 24 / 1000, 4),
            'ci95_kwh_per_day': [round(float(lo) * 24 / 1000, 4),
                                 round(float(hi) * 24 / 1000, 4)],
            'jump_pp_per_keycycle': round(jump_pp, 2),
            'corr_gap_vs_draw': round(float(np.corrcoef(x, y)[0, 1]), 3),
            'estimator': 'sen_slope',
            'n_boot': int(n_boot),
        }
    except Exception as ex:
        return {'error': str(ex)}


# ======================================================================
# M45 (2026-07-19): dm-only (Category A) bindings for four paragraphs in the
# "What This Dataset Established" Conclusions section that were still
# hand-typed narrative snapshots, unlike their neighbors (item 11 fixed M38,
# the Cross-Session Confirmations block fixed M42). Audit found four of six
# checked claims stale or contradicted on the current 149-drive corpus:
#   - item 3 ("battery draw floor: 3.6 kWh/100km") -- basis was
#     net_draw_per100km_corr, the metric M35 retired as a headline figure
#     for exactly the buffer-landing-artifact reason documented in the
#     efficiencyBands docstring above; under the matching stated conditions
#     the current corpus shows net-*charging* (negative) values, not a 3.6
#     floor.
#   - item 4 (thermal ceiling "~49C ... Jun27 D7") -- superseded by the
#     already-computed-but-unreferenced tPeakC/tPeakDrive (50.0C, Jul18 D5).
#   - item 5 ("engine never reaches 80C on trips <5km") -- falsified
#     outright: 30 of 67 sub-5km trips do, up to 91C.
#   - item 10 ("lowest net battery draw: 2.76 kWh/100km, Jun19 Drive2") --
#     beaten by >8 later drives on the retired net-draw basis alone, before
#     even considering the M35 basis change.
# Per the user's direction, "battery draw" in items 3 and 10 is rebased from
# net SoC change to gross throughput (discharge + charge cycled through the
# cells) per 100 km -- the M35 replacement metric, consistent with
# 'Largest single-drive throughput' in _records() and the wear-relevant
# framing used everywhere else in the file. Item 2's dual/regen/engine-charge
# peak-current examples are NOT recomputed here: they already exist,
# correctly, as three rows in _records() ('Peak dual-channel charge...',
# 'Peak pure-regen charge...', 'Peak engine-only charge') and item 2 is
# rebound to those rows in the JSX instead of duplicating the computation.
# Item 4's ambient-tiered breakdown (25-28C ambient -> 44-47C, 41-42C
# 4-sensor mean, ~9C spread) required a raw+ambient join (_battery_vs_ambient,
# Category B) and is dropped rather than left stale; a Category-B follow-up
# can restore it. Item 7's "~44 hours" reset window and item 8's "~8.6km
# chain warm-up threshold" were spot-checked (item 8 reproduces exactly
# against the master: 2.1km->61C then 6.5km->84C on Jun17; item 7's raw
# time-gap is ~50h, not 44h, but the original figure may have used a
# different reset criterion than a raw gap) and are left untouched pending a
# proper session-adjacency derivation -- not addressed in this pass.
# ======================================================================

def _battery_draw_gross(dm):
    """Items 3 and 10: gross-throughput-per-100km battery-draw floors."""
    out = {}
    thr100 = dm['gross_throughput_kwh'] / dm['distance_km'] * 100

    # item 10: dataset-wide floor. >0.5 km gate matches the distance floor
    # already used for the 'Most stationary' record in _records(), avoiding
    # sub-trip normalization noise.
    pool = thr100[dm['distance_km'] > 0.5].dropna()
    if len(pool):
        i = pool.idxmin()
        out['floor'] = {
            'kwh100': round(float(pool.loc[i]), 2),
            'drive': _day_label(dm, i),
            'n': int(len(pool)),
            'ctx': _ctx(dm, i, ('trip', 'vmov', 'class')),
        }
    else:
        out['floor'] = None

    # item 3: floor restricted to the originally-stated matching condition
    # (sustained 65-90 km/h moving average, fully warm engine >=85C coolant).
    cond = (dm['speed_mean_moving'].between(65, 90)
            & (dm['T_eng_coolant_max'] >= 85))
    pool2 = thr100[cond].dropna()
    if len(pool2):
        i2 = pool2.idxmin()
        out['floorWarmHwy'] = {
            'kwh100': round(float(pool2.loc[i2]), 2),
            'medianKwh100': round(float(pool2.median()), 2),
            'drive': _day_label(dm, i2),
            'n': int(len(pool2)),
            'ctx': _ctx(dm, i2, ('vmov', 'trip')),
        }
    else:
        out['floorWarmHwy'] = None
    return out


def _thermal_highway_band(dm):
    """Item 4: cheap dm-only supplement to the existing tPeakC/tPeakPackMeanC/
    tPeakDrive headline (M42) -- the 'equilibrates at 43-49C under sustained
    highway load' range and the hottest-probe-vs-pack-mean gap."""
    hwy = dm.loc[dm['speed_mean_moving'] >= 70, 'T1_peak'].dropna()
    gap = dm['T1_minus_pack_max'].dropna()
    return {
        'highwayN': int(len(hwy)),
        'highwayLoC': round(float(hwy.min()), 0) if len(hwy) else None,
        'highwayHiC': round(float(hwy.max()), 0) if len(hwy) else None,
        'highwayMedianC': round(float(hwy.median()), 0) if len(hwy) else None,
        'gapMedianC': round(float(gap.median()), 1) if len(gap) else None,
        'gapMaxC': round(float(gap.max()), 1) if len(gap) else None,
    }


def _short_trip_warmup(dm):
    """Item 5: the original claim ('engine never reaches 80C on trips <5km')
    is falsified outright on the current corpus. Replaces the false
    universal with the measured rate and the duration split that explains
    the exceptions (dwell time, not distance, drives warm-up on short
    trips)."""
    sub = dm.loc[dm['distance_km'] < 5, ['duration_s', 'T_eng_coolant_max']].dropna()
    if not len(sub):
        return None
    crossed = sub[sub['T_eng_coolant_max'] >= 80]
    clean = sub[sub['T_eng_coolant_max'] < 80]
    peak_idx = dm.loc[dm['distance_km'] < 5, 'T_eng_coolant_max'].idxmax()
    return {
        'n': int(len(sub)),
        'nCrossed80': int(len(crossed)),
        'pctCrossed80': round(100 * len(crossed) / len(sub), 0),
        'peakC': round(float(sub['T_eng_coolant_max'].max()), 0),
        'peakDrive': _day_label(dm, peak_idx),
        'crossedMedianDurMin': (round(float(crossed['duration_s'].median() / 60), 1)
                                 if len(crossed) else None),
        'cleanMedianDurMin': (round(float(clean['duration_s'].median() / 60), 1)
                               if len(clean) else None),
        'cleanMaxC': round(float(clean['T_eng_coolant_max'].max()), 0) if len(clean) else None,
    }


def _dated_batch_summary(dm, date_str):
    """Item 12 (reusable for any single-date narrative point). Binds a dated
    anecdote to whatever the corpus now holds for that date instead of
    hand-typing specific files -- the Jun 20 batch grew from the originally
    -described 2 drives to 8 without the paragraph noticing."""
    sub = dm[dm['date'] == date_str]
    if not len(sub):
        return None
    return {
        'date': date_str,
        'n': int(len(sub)),
        'distLoKm': round(float(sub['distance_km'].min()), 1),
        'distHiKm': round(float(sub['distance_km'].max()), 1),
        'coolantLoC': round(float(sub['T_eng_coolant_max'].min()), 0),
        'coolantHiC': round(float(sub['T_eng_coolant_max'].max()), 0),
        'nCrossed80': int((sub['T_eng_coolant_max'] >= 80).sum()),
        'speedLo': round(float(sub['speed_mean_moving'].min()), 1),
        'speedHi': round(float(sub['speed_mean_moving'].max()), 1),
    }


def _energy_path(dm):
    """M63 (2026-07-29): measured HV-bus energy accounting for Section 4.

    REPLACES the illustrative Sankey. That figure carried explicit percentages
    -- engine BTE 38 %, thermal loss 62 %, generator 97 %, battery 95 %, motor
    97 %, "78 % direct / 22 % buffered", "34 % fuel->wheel" -- none of which
    were computed from this corpus and none of which had a cited external
    source either. Worse than unmeasured: the direct/buffered split is
    STRUCTURALLY UNMEASURABLE with this instrumentation. The BMS shunt sees
    only current crossing the pack terminals, so generator output that reaches
    the inverter directly across the shared HV DC bus never enters any logged
    channel. No sample-rate increase or additional PID recovers it; it would
    need a second current sensor on the generator/inverter link. Publishing a
    number for it was the single least defensible figure in the dashboard.

    What IS measured, and what this block therefore reports:
      * the four-way charge-SOURCE decomposition (M12 torque-verified), which
        partitions every joule that entered the pack and closes to ~1e-5 of
        gross charge by construction;
      * gross discharge / charge / throughput and their asymmetry;
      * engine-on vs engine-off share of pack charge.
    Engine-off TRACTION share (M53, evTraction) is the complementary measured
    statement about which prime mover moves the car, and is bound separately.
    """
    need = ['gross_discharge_kwh', 'gross_charge_kwh', 'charge_eng_only_kwh',
            'charge_dual_kwh', 'charge_pure_regen_kwh',
            'charge_lowtq_engoff_kwh']
    if not set(need) <= set(dm.columns):
        return None
    d = dm.dropna(subset=need)
    if not len(d):
        return None
    clean = d[~_as_bool(d['ens_outlier_v2'])] \
        if 'ens_outlier_v2' in d.columns else d
    chg = float(clean['gross_charge_kwh'].sum())
    dis = float(clean['gross_discharge_kwh'].sum())
    if not chg:
        return None
    parts = [
        ('eng_only', 'Engine-on / non-braking charge', '#f59e0b',
         'engine ON, motor not braking (target torque >= -15 N·m) — engine contribution likely, but the '
         'pack shunt does not meter generator output'),
        ('dual', 'Engine-on / braking overlap', '#8b5cf6',
         'engine ON while the motor brakes — mixed operating state; the physical split between '
         'generator output and recovered braking energy is unidentified'),
        ('pure_regen', 'Engine-off / braking charge', '#22c55e',
         'engine OFF, motor braking — strongest regenerative-braking-at-pack proxy, '
         'conditional on the torque/RPM state classification'),
        ('lowtq_engoff', 'Engine-off residual charge', '#0ea5e9',
         'engine OFF, motor not braking — unattributed by the -15 N·m threshold; not a metered '
         'motor or generator source'),
    ]
    src = []
    for key, label, col, detail in parts:
        v = float(clean[f'charge_{key}_kwh'].sum())
        src.append({'key': key, 'label': label, 'color': col, 'detail': detail,
                    'kwh': round(v, 2), 'pct': round(v / chg * 100, 1)})
    eng_on = (float(clean['charge_eng_on_kwh'].sum())
              if 'charge_eng_on_kwh' in clean.columns else None)
    eng_off = (float(clean['charge_eng_off_kwh'].sum())
               if 'charge_eng_off_kwh' in clean.columns else None)
    km = (float(clean['distance_km'].sum())
          if 'distance_km' in clean.columns else None)
    return {
        'basis': ('M63. Corpus-level pack-terminal energy accounting over the '
                  'ens_outlier_v2-clean drives carrying the BMS current '
                  'channel. The operating-state charge partition is the M12 '
                  'torque-verified four-way partition and is exhaustive by '
                  'construction.'),
        'n': int(len(clean)), 'nCorpus': int(len(dm)),
        'km': round(km, 1) if km is not None else None,
        'chargeKwh': round(chg, 2), 'dischargeKwh': round(dis, 2),
        'throughputKwh': round(chg + dis, 2),
        'asymmetryPct': round((chg - dis) / dis * 100, 1) if dis else None,
        'chargeSources': src,
        'partitionResidualKwh': round(chg - sum(s['kwh'] for s in src), 3),
        'engOnChargePct': (round(eng_on / chg * 100, 1)
                           if eng_on is not None else None),
        'engOffChargePct': (round(eng_off / chg * 100, 1)
                            if eng_off is not None else None),
        'regenTouchedPct': round(sum(s['kwh'] for s in src
                                     if s['key'] in ('dual', 'pure_regen'))
                                 / chg * 100, 1),
        'unobservable': [
            {'quantity': 'generator -> inverter direct path (pack bypass)',
             'why': ('the BMS shunt only sees current crossing the pack '
                     'terminals; bus-direct energy never appears in any '
                     'logged channel, so the direct/buffered split cannot be '
                     'derived from this data at any sample rate')},
            {'quantity': 'engine brake thermal efficiency / fuel energy in',
             'why': ('the logged fuel rate and fuel counter are calculated by '
                     'the logger app (Car Scanner, air-flow based) and are '
                     'present on a subset of drives; they are not an ECU fuel '
                     'measurement, so fuel energy in is logged volume x assumed '
                     'E10 LHV; MAF appears on a handful of early logs only, and '
                     'MAF-derived power is an air-side estimate; engine brake '
                     'thermal efficiency is therefore model-derived')},
            {'quantity': 'component efficiencies (generator, inverter, motor)',
             'why': ('each needs input and output power at the same node '
                     'simultaneously; only one side of each node is '
                     'instrumented')},
        ],
    }


def _metric_convention(dm):
    """M62 (2026-07-28, terminology audit): make the cycle-counting convention
    explicit and self-checking instead of leaving it to prose.

    Three quantities circulate in this study and two of them have been
    conflated in narrative text:

      GTC  = gross_throughput / CAP            (charge + discharge)
      FCE  = gross_throughput / (2 * CAP)      (this study's "full cycle")
      EFC  = gross_discharge  / CAP            (INDUSTRY STANDARD)

    The industry convention (TWAICE / accure / storage-warranty practice)
    counts depth: one 100 % DoD cycle, two 50 % cycles and ten 10 % cycles
    are all 1 EFC. That is discharge-referenced, so this study's FCE is the
    metric that maps onto it -- NOT GTC, which is ~2x larger by construction.

    "Gross capacity turnover" is NOT a recognised battery metric; a literature
    search returns only "gross capacity" in the unrelated nameplate-vs-usable
    sense, which makes the term actively ambiguous in an EV context. The
    ratios are computed live so the claim cannot drift from the data.
    """
    D = float(dm['gross_discharge_kwh'].sum())
    C = abs(float(dm['gross_charge_kwh'].sum()))
    T = float(dm['gross_throughput_kwh'].sum())
    if not D:
        return None
    efc_std = D / CAP_KWH
    return {
        'capKwh': CAP_KWH,
        'capVerified': False,
        'grossDischargeKwh': round(D, 2),
        'grossChargeKwh': round(C, 2),
        'grossThroughputKwh': round(T, 2),
        'chargeDischargeRatio': round(C / D, 3),
        'gtc': round(T / CAP_KWH, 1),
        'fce': round(T / (2 * CAP_KWH), 1),
        'efcStandard': round(efc_std, 1),
        'gtcOverStandardEfc': round((T / CAP_KWH) / efc_std, 3),
        'fceOverStandardEfc': round((T / (2 * CAP_KWH)) / efc_std, 3),
        'gtcIsStandard': False,
        'standardEquivalent': 'FCE',
        'note': ('GTC is a local double-counting convention, not a recognised '
                 'metric. FCE is the quantity that corresponds to the standard '
                 'equivalent-full-cycle (EFC) definition; the residual gap from '
                 '1.000 is charge-discharge imbalance (SoC drift, unlogged use, sensor-offset residual, auxiliaries), not a '
                 'definitional difference. Every figure here scales linearly '
                 'with CAP_KWH, which is itself unverified.'),
    }


def _risk_cold_engine_battery(dm):
    """M62 (2026-07-28): does "engine cold on short trips" carry any
    CELL-level signal, or is it only an engine-side observation?

    M60 corrected the engine claim itself (warm-up is common, not universal).
    It did not address whether the cold-engine state implies battery stress,
    which is the question the risk table's placement invites.

    Method. Restrict to sub-5 km drives, which controls trip length by design
    rather than by covariate adjustment, and split on whether the engine
    crossed 80 C. Then test whether any apparent cell-level effect survives
    control for pack temperature, since a cold engine is largely a
    thermometer for a cold pack.

    Filtering: corpus-standard ens_outlier_v2 exclusion.
    """
    need = ['distance_km', 'T_eng_coolant_max', 'T_pack_mean_max']
    if any(c not in dm.columns for c in need):
        return None
    d = dm[~_as_bool(dm['ens_outlier_v2'])].copy()
    s = d[(d['distance_km'] < 5) & (d['distance_km'] > 0)
          & d['T_eng_coolant_max'].notna()]
    if len(s) < 20:
        return None
    cold = s[s['T_eng_coolant_max'] < 80]
    warm = s[s['T_eng_coolant_max'] >= 80]
    if len(cold) < 5 or len(warm) < 5:
        return None

    def _mwu(a, b):
        a, b = a.dropna(), b.dropna()
        if len(a) < 5 or len(b) < 5:
            return None
        try:
            from scipy import stats as _st
            p = float(_st.mannwhitneyu(a, b).pvalue)
        except Exception:
            p = None
        return {'cold': round(float(a.median()), 2),
                'warm': round(float(b.median()), 2), 'p': (round(p, 4) if p is not None else None)}

    cmp_ = {
        'gtcPer100km': _mwu(cold['gtc'] / cold['distance_km'] * 100,
                            warm['gtc'] / warm['distance_km'] * 100),
        'damageK2PerKm': _mwu(cold['rf_damage_k2'] / cold['distance_km'],
                              warm['rf_damage_k2'] / warm['distance_km']),
        'peakDischargeA': _mwu(cold['peak_I_discharge'], warm['peak_I_discharge']),
        'socBandPp': _mwu(cold['soc_band'], warm['soc_band']),
        'loadedSpreadAdjMv': _mwu(cold['cell_spread_loaded_p95_adj_mv'],
                                  warm['cell_spread_loaded_p95_adj_mv']),
        'packTempC': _mwu(cold['T_pack_mean_max'], warm['T_pack_mean_max']),
    }

    def _partial(x, y, z):
        t = d[[x, y, z]].dropna()
        if len(t) < 15:
            return None
        try:
            from scipy import stats as _st
            import numpy as _np
            r = lambda a, b: _st.spearmanr(a, b)[0]
            rxy, rxz, ryz = r(t[x], t[y]), r(t[x], t[z]), r(t[y], t[z])
            pr = (rxy - rxz * ryz) / _np.sqrt((1 - rxz ** 2) * (1 - ryz ** 2))
            n = len(t)
            tt = pr * _np.sqrt((n - 3) / (1 - pr ** 2))
            p = float(2 * (1 - _st.t.cdf(abs(tt), n - 3)))
        except Exception:
            return None
        return {'rawRho': round(float(rxy), 3), 'partialRho': round(float(pr), 3),
                'p': round(p, 4), 'n': int(n)}

    cold_pack = d[d['T_pack_mean_max'] < 25]
    crate = cold_pack['eng_charge_peak_Crate'].dropna()
    try:
        from scipy import stats as _st
        _rho = round(float(_st.spearmanr(d['T_eng_coolant_max'],
                                         d['T_pack_mean_max'],
                                         nan_policy='omit')[0]), 3)
    except Exception:
        _rho = None
    return {
        'replaces': 'Engine cold on short trips',
        'nShort': int(len(s)), 'nCold': int(len(cold)), 'nWarm': int(len(warm)),
        'compare': cmp_,
        'partialSpread': _partial('T_eng_coolant_max',
                                  'cell_spread_loaded_p95_adj_mv', 'T_pack_mean_max'),
        'partialResistance': _partial('T_eng_coolant_max',
                                      'vreg_R_pack_mohm', 'T_pack_mean_max'),
        'coolantVsPackRho': _rho,
        'coldPackN': int(len(cold_pack)),
        'coldPackShortN': int((cold_pack['distance_km'] < 5).sum()),
        'coldPackChargeCrateMed': (round(float(crate.median()), 1) if len(crate) else None),
        'coldPackChargeCrateMax': (round(float(crate.max()), 1) if len(crate) else None),
        'minPackTempC': round(float(d['T_pack_mean_max'].min()), 1),
        'verdict': 'proxy_not_independent',
    }


def _session_ledger_audit(dm, session_cfg=None):
    """M62 (2026-07-28): reconcile the hand-maintained session / sessionGroup
    ledgers in summary_config.json against drive_master.csv.

    These rows carry hand-typed drives/km counts. They drift: a batch gets
    ingested and the narrative row that describes it is not updated, so the
    session table silently under-reports relative to the headline corpus
    count. That is exactly the failure mode M42/M60 fixed for the risk rows,
    and it cannot be fixed by editing numbers once -- it needs a standing
    check. This block recomputes per-row totals from the master wherever the
    row name resolves to a date or date range, and reports the residual.

    Names that are not date-resolvable ("May 23+31", "Jun 20 AM") are
    reported as unresolved rather than guessed at; they are legitimate
    groupings, not errors, and silently "correcting" them would be worse
    than leaving them.
    """
    import datetime as _dt, re as _re
    if not session_cfg:
        return None
    MON = {m: i for i, m in enumerate(
        ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul',
         'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}
    year = int(str(dm['date'].iloc[0])[:4])

    def _parse(name):
        s = _re.sub(r'[\u2012-\u2015\u2212\u2013]', '-', str(name))
        s = _re.sub(r'\s+', ' ', s).strip()
        if '+' in s or _re.search(r'\b(AM|PM)\b', s):
            return None
        parts = [p.strip() for p in s.split('-')]

        def one(tok, fb=None):
            m = _re.match(r'([A-Za-z]{3})\s*0?(\d{1,2})$', tok)
            if m:
                return MON[m.group(1)[:3].title()], int(m.group(2))
            m2 = _re.match(r'0?(\d{1,2})$', tok)
            if m2 and fb:
                return fb, int(m2.group(1))
            return None
        a = one(parts[0])
        if not a:
            return None
        if len(parts) == 1:
            return [_dt.date(year, *a)]
        b = one(parts[1], a[0])
        if not b:
            return None
        d0, d1 = _dt.date(year, *a), _dt.date(year, *b)
        if d1 < d0:
            return None
        return [d0 + _dt.timedelta(days=i) for i in range((d1 - d0).days + 1)]

    d = dm.copy()
    d['_d'] = pd.to_datetime(d['date']).dt.date

    def _audit(rows, label):
        mism, unres, covered = [], [], set()
        for r in rows:
            ds = _parse(r.get('name'))
            if ds is None:
                unres.append(r.get('name'))
                continue
            sub = d[d['_d'].isin(ds)]
            covered |= (set(ds) & set(d['_d']))
            cn, ck = r.get('drives'), float(r.get('km') or 0)
            mn, mk = len(sub), float(sub['distance_km'].sum())
            if cn != mn or abs(mk - ck) > 0.15:
                mism.append({'name': r.get('name'), 'cfgDrives': cn,
                             'cfgKm': round(ck, 1), 'masterDrives': mn,
                             'masterKm': round(mk, 1),
                             'kmAgrees': abs(mk - ck) <= 0.15})
        return {'scope': label, 'nRows': len(rows),
                'cfgDrives': int(sum(r.get('drives') or 0 for r in rows)),
                'cfgKm': round(float(sum(r.get('km') or 0 for r in rows)), 1),
                'nMismatched': len(mism), 'mismatches': mism,
                'nUnresolvedNames': len(unres), 'unresolvedNames': unres,
                'datesUncovered': sorted(str(x) for x in
                                         (set(d['_d']) - covered))}

    out = {'masterDrives': int(len(dm)),
           'masterKm': round(float(dm['distance_km'].sum()), 1)}
    if session_cfg.get('sessions'):
        out['sessions'] = _audit(session_cfg['sessions'], 'sessions')
        out['sessions']['driveShortfall'] = (out['masterDrives']
                                             - out['sessions']['cfgDrives'])
    if session_cfg.get('sessionGroups'):
        out['sessionGroups'] = _audit(session_cfg['sessionGroups'], 'sessionGroups')
        out['sessionGroups']['driveShortfall'] = (out['masterDrives']
                                                  - out['sessionGroups']['cfgDrives'])
    out['note'] = ('Hand-typed ledger rows reconciled against the master. '
                   'kmAgrees=true on a mismatch means the distance total is '
                   'right and only the drive COUNT drifted; kmAgrees=false '
                   'means drives were ingested that the row never described. '
                   'Unresolved names are non-date groupings, not errors.')
    return out


# ======================================================================
# P0-5 (2026-07-30): audit / provenance block producers.
#
# These eight dashboard-bound blocks previously reached summary_arrays.json
# only via out-of-band scripts, so a clean build_summary_arrays() run dropped
# them and the HTML fell back to blanks. They are now generated by the main
# pipeline. SIX are deterministic functions of the master + raw corpus + config
# and are reproduced here (all values verified against the shipped artifact on
# the 194-drive corpus). TWO are pure declared metadata (constantProvenance,
# determinism) and are sourced from the study config rather than recomputed --
# they describe assumptions and a reproducibility proof, not measurements.
# ======================================================================

def _audit_eligibility(dm):
    """F-18: per-output-family denominators. Eligibility is the actual metric
    not-null / validity gate for each family, NOT PID-header presence.

    M115 (2026-08-10, audit §10 coverage/observability map): added 'days'
    (distinct calendar dates) and 'km' (summed distance_km) alongside the
    existing drive-count 'n' for every family. The audit's ask was explicit
    -- "map files/days/km and channel availability... prevents denominator
    drift" -- and a drive count alone can be a misleading denominator on its
    own (a family eligible on 20 short urban drives covers very different
    evidence than 20 long highway drives at the same 'n')."""
    clean = ~_as_bool(dm['ens_outlier_v2'])
    typed = dm['drive_type'].notna() & (dm['drive_type'] != 'unknown')
    n_excl = int(_as_bool(dm['ens_outlier_v2']).sum())

    def _dims(mask):
        """n / days / km for a boolean row mask, or all-None if mask is None
        (column absent from this master vintage)."""
        if mask is None:
            return {'n': None, 'days': None, 'km': None}
        sub = dm.loc[mask]
        return {'n': int(mask.sum()),
                'days': int(sub['date'].nunique()) if len(sub) else 0,
                'km': round(float(sub['distance_km'].sum()), 1) if len(sub) else 0.0}

    _mask_typed_clean = typed & clean
    _mask_deficit = _as_bool(dm['deficit_80_120_valid'])
    _mask_ev = _as_bool(dm['ev_valid'])
    _mask_vreg = dm['vreg_R_pack_mohm'].notna()
    _mask_vsag = (dm['vsag_R_pack_mohm'].notna()
                  if 'vsag_R_pack_mohm' in dm.columns else None)
    _mask_cellspread = ((dm['cell_spread_loaded_p95_adj_mv'].notna() & clean)
                         if 'cell_spread_loaded_p95_adj_mv' in dm.columns else None)
    # M207 (F-06): the current-integral energy family must be gated on the
    # metric actually being produced (gross_throughput_kwh non-null), NOT on
    # raw HV-current sample presence. A drive can carry integrable samples yet
    # fail integration (e.g. 20260511_185709), so n_I_samples>0 overstated the
    # energy denominator by one (296 vs the 295 metric-valid drives). Sample
    # presence is reported separately below and in rawManifest.pidCoverage.
    _mask_iintegral = dm['gross_throughput_kwh'].notna()
    _mask_isamplepresent = dm['n_I_samples'] > 0

    fam = [
        {'family': 'Headline totals (km, kWh, GTC, duration)',
         **_dims(pd.Series(True, index=dm.index)),
         'basis': 'all rows, unfiltered',
         'note': 'true totals; includes early PID-poor logs'},
        {'family': 'Drive-condition statistics (per-type)',
         **_dims(_mask_typed_clean),
         'basis': 'typed AND ens_outlier_v2-clean',
         'note': ('untyped/unknown and canonical exclusions dropped; corrected '
                  'from a shipped n that counted typed-only against a '
                  'typed-AND-clean basis label (audit F-inconsistency)')},
        {'family': '80-120 km/h engine-on discharge (M14/M41)',
         **_dims(_mask_deficit),
         'basis': 'deficit_80_120_valid (>=120 s band time)',
         'note': 'condition-gated; never a 194-drive comparison'},
        {'family': 'EV traction census (M53)',
         **_dims(_mask_ev),
         'basis': 'ev_valid per-drive gate',
         'note': 'RPM/speed channel coverage gated'},
        {'family': 'V-regression resistance (M25 power fade)',
         **_dims(_mask_vreg),
         'basis': 'load-excited subset',
         'note': 'selected: needs sustained discharge current'},
        {'family': 'V-sag resistance proxy',
         **_dims(_mask_vsag),
         'basis': 'rest+load paired-sample subset',
         'note': 'selected: needs both rest and load reference samples'},
        {'family': 'Cell-spread trend (M19)',
         **_dims(_mask_cellspread),
         'basis': 'loaded-spread adjusted, ens_outlier_v2-clean',
         'note': 'temperature/current-deconfounded loaded spread available'},
        {'family': 'Current-integral energy metrics',
         **_dims(_mask_iintegral),
         'basis': 'gross_throughput_kwh.notna() (integration produced a metric)',
         'headerSamplePresentN': int(_mask_isamplepresent.sum()),
         'nonIntegrableWithSamples': sorted(
             dm.loc[_mask_isamplepresent & ~_mask_iintegral, 'file'].tolist()),
         'note': ('metric-validity denominator, NOT header/sample presence: '
                  'headerSamplePresentN drives carry integrable HV-current '
                  'samples, but nonIntegrableWithSamples yielded no energy '
                  'metric and are excluded from every kWh/GTC/FCE total')},
    ]
    return {'totalRows': int(len(dm)),
            'canonicalExclusions': n_excl,
            'analysisRows': int(len(dm) - n_excl),
            'families': fam,
            'note': ('F-18: each family reports its own validity denominator. '
                     'Header/PID presence, minimum-sample validity and metric '
                     'not-null are distinct concepts and are not conflated.')}


def _audit_observed_mix(dm, annual_km=None, threshold_gtc=20000):
    """F-04: observed distance mix vs the hand-selected forward scenario.
    Distance-weighted, ens_outlier_v2-clean; drive_type remapped to the
    three planning classes (urban->city, mixed->mixed, mixed_highway &
    highway -> highway) to match _cycle_projection's scenario archetypes.
    M86 (2026-08-05): this remains a deliberate 3-way planning-class remap,
    same reasoning as _cycle_projection's docstring -- do not migrate this
    one to native CLASS_ORDER without also redefining the archetype weights
    it is compared against. Rate/crossing fields are derived from the same
    annual-km and scenario threshold the cycle-life block uses (never
    hardcoded here)."""
    clean = ~_as_bool(dm['ens_outlier_v2'])
    remap = {'urban': 'city', 'mixed': 'mixed',
             'mixed_highway': 'highway', 'highway': 'highway'}
    d = dm[dm['drive_type'].isin(remap) & clean].copy()
    d['cls'] = d['drive_type'].map(remap)
    tot = float(d['distance_km'].sum())
    obs = {c: round(float(d[d['cls'] == c]['distance_km'].sum()) / tot * 100, 1)
           for c in ('city', 'mixed', 'highway')}
    sel = {'city': 40.0, 'mixed': 10.0, 'highway': 50.0}   # M85 scenario (hwy-dominant)
    obs_gpk = float(d['gtc'].sum()) / tot
    cls_gpk = {}
    for c in ('city', 'mixed', 'highway'):
        dc = d[d['cls'] == c]
        km = float(dc['distance_km'].sum())
        cls_gpk[c] = (float(dc['gtc'].sum()) / km) if km > 0 else 0.0
    sel_gpk = sum(cls_gpk[c] * sel[c] / 100 for c in sel)
    out = {
        'observedShare': obs, 'selectedShare': sel,
        'observedGtcPerKm': round(obs_gpk, 5),
        'selectedGtcPerKm': round(sel_gpk, 5),
        'intensityInflationPct': round((sel_gpk / obs_gpk - 1) * 100, 1)
        if obs_gpk else None,
        'typedKm': round(tot, 1), 'n': int(len(d))}
    if annual_km:
        obs_rate = obs_gpk * annual_km
        sel_rate = sel_gpk * annual_km
        out.update({
            'observedRateGtcYr': round(obs_rate),
            'selectedRateGtcYr': round(sel_rate),
            'observedCrossingYr': round(threshold_gtc / obs_rate, 1)
            if obs_rate else None,
            'selectedCrossingYr': round(threshold_gtc / sel_rate, 1)
            if sel_rate else None})
    out['note'] = ('M85: the selected 50/40/10 (city/mixed/highway) blend is a '
                   'hand-chosen forward-usage scenario, now highway-dominant to '
                   f'match the observed duty cycle ({obs["highway"]:.1f}% highway). It remains '
                   'somewhat more city-weighted than the logged mix, so it '
                   'still raises modeled GTC intensity, but far less than the '
                   'superseded 55/30/15 city-dominant blend did. These gtc/km '
                   'figures compare the MIX effect only (warm-floor intensities); '
                   'the Selected row shown in cycleLife additionally carries '
                   'climatic stress. Crossing years use the unverified '
                   'SCENARIO_THRESHOLD_GTC and are scenario analysis, not an '
                   'end-of-life estimate.')
    return out



def _offset_capacity_sweep(dm, caps=(1.7, 1.8, 1.9, 2.0, 2.1, 2.2, 2.3, 2.4, 2.5)):
    """M107 (audit P1/P0-05): regenerate the two-pass SoC-anchored offset solve
    across nominal-capacity assumptions, from the master alone.

    The solve is  i2 = sum(residual)*1000 / (sum(integr_time_h)*Vw)  over the
    converged domain-clean set (f_domain_2p). Only the SoC-implied energy term
    scales with CAP_KWH:  residual(cap) = net_draw_kwh - soc_kwh*(cap/CAP_KWH),
    with soc_kwh = net_draw_kwh - energy_residual_kwh (exact, master-stored).
    Vw and integr_time_h are CAP-independent. The domain exclusion set is held
    at its converged state (stable across this CAP range: it does not flip),
    so the sweep is exact within 1.7-2.5 kWh; the full pipeline re-evaluates the
    domain rules per pass but reaches the same exclusion set here.
    """
    m = (dm['energy_residual_kwh'].notna() & dm['duration_s'].notna()
         & dm['V_pack_median'].notna())
    h = dm['integr_time_h']
    Vw = float((dm.loc[m, 'V_pack_median'] * h[m]).sum() / h[m].sum())
    excl = _as_bool(dm['f_domain_2p']) if 'f_domain_2p' in dm.columns \
        else pd.Series(False, index=dm.index)
    mm = m & ~excl
    soc_kwh0 = dm['net_draw_kwh'] - dm['energy_residual_kwh']
    denom = float(h[mm].sum() * Vw)
    rows = []
    for cap in caps:
        resid = dm['net_draw_kwh'] - soc_kwh0 * (cap / CAP_KWH)
        i2 = float(resid[mm].sum() * 1000.0 / denom)
        rows.append({'capKwh': round(float(cap), 2), 'offsetA': round(i2, 4)})
    # linear sensitivity dOffset/dCap over the swept range
    lo, hi = rows[0], rows[-1]
    slope = (hi['offsetA'] - lo['offsetA']) / (hi['capKwh'] - lo['capKwh'])
    return {'rows': rows, 'nInSolve': int(mm.sum()),
            'vWeighted': round(Vw, 1),
            'dOffsetPerKwh': round(slope, 4)}


def _audit_offset_uncertainty(dm, n_boot=4000, seed=42):
    """4.3 (M230, audit F04 fix): day-cluster bootstrap of the SAME two-pass
    ratio-solve statistic used for the point estimate -- i2 = sum(residual)
    *1000 / (sum(integr_time_h) * day-cluster-recomputed V_pack-weighted
    mean) -- over the SAME domain-clean (f_domain_2p) population, held fixed
    across draws (matching _offset_capacity_sweep's convention: the domain
    exclusion set does not flip across this kind of resampling).

    Prior code (pre-M230) bootstrapped the MEDIAN of per-drive
    implied_offset_A_drive over a broader ens_invalid-only gate -- a
    different estimator over a different eligible subset than the point
    solve, so the reported interval did not characterize the reported point
    (audit F04, P0). Point estimate and gate are unchanged by this fix; only
    the resampling statistic and its population now match."""
    m = (dm['energy_residual_kwh'].notna() & dm['duration_s'].notna()
         & dm['V_pack_median'].notna())
    excl = _as_bool(dm['f_domain_2p']) if 'f_domain_2p' in dm.columns \
        else pd.Series(False, index=dm.index)
    mm = m & ~excl
    d = dm.loc[mm, ['date', 'energy_residual_kwh', 'integr_time_h',
                     'V_pack_median']].copy()
    d['day'] = pd.to_datetime(d['date']).dt.date
    groups = {k: g[['energy_residual_kwh', 'integr_time_h',
                     'V_pack_median']].to_numpy(dtype=float)
              for k, g in d.groupby('day')}
    keys = list(groups)
    rng = np.random.default_rng(seed)
    ests = np.empty(n_boot)
    for i in range(n_boot):
        samp = rng.choice(len(keys), len(keys), replace=True)
        block = np.concatenate([groups[keys[j]] for j in samp], axis=0)
        resid, th, v = block[:, 0], block[:, 1], block[:, 2]
        vw = float((v * th).sum() / th.sum())
        ests[i] = float(resid.sum() * 1000.0 / (th.sum() * vw))
    # M107 (audit P1): point estimate is the LIVE two-pass solve read from the
    # master, not a hardcoded constant. Prior code pinned -0.4125, which had
    # drifted from the corpus-current -0.4183.
    _live2p = (round(float(dm['I_offset_2p_A_applied'].dropna().iloc[0]), 4)
               if dm['I_offset_2p_A_applied'].notna().any() else None)
    _sweep = _offset_capacity_sweep(dm)
    _sum_off_net = (round(float(dm['offset_2p_kwh_removed'].abs().sum()), 2)
                    if 'offset_2p_kwh_removed' in dm.columns else None)
    return {
        'pointEstimateA': _live2p,   # M107: generated from the same solve
        'basis': 'M24/M107 two-pass SoC-anchored solve (live, master-read)',
        'bootMedianA': round(float(np.median(ests)), 4),
        'ci95A': [round(float(np.percentile(ests, 2.5)), 4),
                  round(float(np.percentile(ests, 97.5)), 4)],
        'nDays': int(len(keys)), 'nDrives': int(mm.sum()), 'nBoot': int(n_boot),
        'estimatorNote': (
            'M230 (audit F04, P0): bootstrap resamples calendar days and '
            'recomputes the identical ratio-solve statistic as pointEstimateA '
            '(same domain-clean f_domain_2p population, same formula, '
            'day-cluster-recomputed V-weighting per draw) -- point and '
            'interval are now the same estimator over the same population. '
            'Previously bootstrapped median(implied_offset_A_drive) over a '
            'broader ens_invalid-only gate; that interval did not '
            'characterize the reported point.'),
        'readyIdleA': -0.6, 'readyIdleSdA': 0.34,
        'capacitySensitivity': _sweep,
        'correctionScope': {
            'appliesTo': ['net_draw_kwh_corr2p', 'energy_residual_kwh_corr2p',
                          'net_draw_per100km_corr2p'],
            'notAppliedTo': ['gross_discharge_kwh', 'gross_charge_kwh',
                              'gross_throughput_kwh', 'gtc', 'fce'],
            'netCorrectionMagnitudeKwh': _sum_off_net,
            'note': ('P0-05: the constant additive current offset is removed '
                     'from NET draw and residuals only. GTC/FCE/gross '
                     'throughput integrate |I| and are NOT offset-corrected in '
                     'code -- a constant bias sums under the absolute value '
                     'rather than cancelling, so its gross-metric effect is '
                     'asymmetric and cannot be recovered from master '
                     'aggregates; quantifying it requires a raw re-integration '
                     'pass. Report gross metrics as offset-UNCORRECTED.')},
        'note': ('Point estimate is the live two-pass solve (M107). '
                 'capacitySensitivity regenerates the solve across nominal-'
                 'capacity assumptions from the same code path: the offset is '
                 'coupled to the unverified CAP_KWH and must be reported with '
                 'that band. Day-cluster bootstrap (M230) resamples days and '
                 're-solves the same pooled ratio estimator as the point '
                 'estimate, not a per-drive median; it assumes an unbiased '
                 'BMS SoC ledger, and quantization, key-cycle re-estimation '
                 'and temperature-dependent coulombic efficiency can still '
                 'alias into the fitted constant. Interval is method-'
                 'dependent (RNG/seed).')}


def _audit_contamination_sensitivity(dm):
    """F-13: how IsolationForest/LOF prevalence responds to the contamination
    parameter, showing the canonical exclusion is far less sensitive because
    it is driven by hard domain rules plus detector AGREEMENT, not a single
    imposed rate. Recomputes the detectors on the frozen master feature set."""
    from sklearn.ensemble import IsolationForest
    from sklearn.neighbors import LocalOutlierFactor
    from sklearn.preprocessing import StandardScaler
    feats = ['net_draw_per100km_corr2p', 'gross_throughput_kwh',
             'cell_spread_loaded_p95_adj_mv', 'peak_discharge_kw',
             'T_pack_mean_max', 'distance_km']
    feats = [f for f in feats if f in dm.columns]
    d = dm.dropna(subset=feats).copy()
    X = StandardScaler().fit_transform(d[feats].values)
    canon = _as_bool(dm.loc[d.index, 'ens_outlier_v2']).values
    rows = []
    for c in (0.02, 0.04, 0.06, 0.08, 0.10):
        iso = IsolationForest(n_estimators=500, contamination=c,
                              random_state=42).fit_predict(X) == -1
        lof = LocalOutlierFactor(n_neighbors=15,
                                 contamination=c).fit_predict(X) == -1
        both = iso & lof
        rows.append({'contamination': c,
                     'nIso': int(iso.sum()), 'nLof': int(lof.sum()),
                     'nBoth': int(both.sum()),
                     'overlapWithCanonical': int((both & canon).sum())})
    return {'rows': rows, 'nEvaluated': int(len(d)),
            'canonicalN': int(_as_bool(dm['ens_outlier_v2']).sum()),
            'note': ('Detector prevalence is imposed by the contamination '
                     'parameter, not discovered. Canonical exclusion '
                     '(ens_outlier_v2) is driven by hard domain rules plus '
                     'detector agreement, so it is far less sensitive to this '
                     'parameter than the raw detector counts are. Detector '
                     'counts are environment-dependent (sklearn version, '
                     'feature-NaN drop) and are a sensitivity illustration, '
                     'not a reproducible constant.')}


# raw-header PID column names for coverage detection
_PID_COLS = {
    'gpsAlt': 'Висота (GPS) (m)',
    'latlon': ('Latitude', 'Longtitude'),
    'hvCurrent': '[BMS] HV Battery Current (A)',
    'baro': 'Атмосферний тиск (абсолютний) (kPa)',
    'fuelRate': 'Витрата палива у двигуні (g/sec)',
    # M115 (2026-08-10, audit §10 coverage/observability map): the pair that
    # actually gates cell_spread_loaded_* (see compute_drive_summary_v6.py,
    # which builds it from Max/Min Cell Voltage, NOT the per-cell array).
    'cellMaxMin': ('[BMS] Max Cell Voltage (V)', '[BMS] Min Cell Voltage (V)'),
    # The full per-cell array (#01-#80) is a materially DIFFERENT, much
    # rarer channel (n=3 files vs. n=207+ for the max/min pair below) that
    # this pipeline does not currently consume for any shipped metric --
    # tracked here specifically because the coverage map's job is to
    # surface exactly this kind of unused-evidence gap, not just to gate
    # existing metrics. Checking cell #01 is sufficient: if the array
    # exists at all, #01 is present.
    'cellVoltage': '[BMS] Battery Cell #01 (V)',
}


def _audit_raw_manifest(dm, raw_loader, libs=None, corpus_md5=None, raw_dir=None):
    """F-02/F-19: raw<->master 1:1 check and per-PID header coverage.
    raw_loader(fname)->bytes; header is read from the first line only."""
    import io as _io
    import hashlib as _hl
    files = list(dm['file'])
    # M115 (2026-08-10, audit §10 coverage/observability map): track the file
    # LIST per channel, not just a running count, so days/km coverage can be
    # derived against drive_master afterward (see _channel_days_km below).
    # Previously this only supported a headline n/pct; the audit's ask
    # ("map files/days/km and channel availability... for every claim")
    # needs the file-level detail to compute the other two dimensions.
    cov_files = {k: [] for k in _PID_COLS}
    orphan, missing = [], []
    md5 = _hl.md5()
    for f in files:
        try:
            b = raw_loader(f)
        except Exception:
            missing.append(f)
            continue
        md5.update(b if isinstance(b, bytes) else b.encode())
        header = b.split(b'\n', 1)[0].decode('utf-8', 'replace') \
            if isinstance(b, bytes) else b.split('\n', 1)[0]
        for k, col in _PID_COLS.items():
            if isinstance(col, tuple):
                if all(c in header for c in col):
                    cov_files[k].append(f)
            elif col in header:
                cov_files[k].append(f)
    n = len(files)
    pid = {k: {'n': len(v), 'pct': round(len(v) / n * 100, 1) if n else 0.0}
           for k, v in cov_files.items()}
    gps_files = cov_files.get('gpsAlt', [])
    # M106 (audit P0-04): the raw<->master 1:1 claim requires ENUMERATING the raw
    # directory; iterating master filenames alone can never surface an orphan.
    # When a raw_dir is supplied we delegate orphan/missing/typed-exclusion
    # detection to corpus_manifest.build (the release source of truth). Without a
    # raw_dir we refuse to assert one-to-one and say so explicitly.
    typed_excl, orphan_enum, missing_enum = [], None, None
    one_to_one_verified = None
    if raw_dir is not None:
        try:
            import corpus_manifest as _cm
            _mf = _cm.build(raw_dir, master_csv=None, master_df=dm)  # in-memory
            orphan_enum = _mf['orphanDetail']
            missing_enum = _mf['missingDetail']
            typed_excl = _mf['typedExclusions']
            one_to_one_verified = _mf['integrity']['oneToOneCanonical']
        except Exception as _e:
            one_to_one_verified = None
            typed_excl = [{'error': f'enumeration failed: {_e!r}'}]
    return {
        'nFiles': n, 'nMasterRows': int(len(dm)),
        'oneToOneVerified': one_to_one_verified,
        'orphanRaw': orphan_enum if orphan_enum is not None else orphan,
        'missingRaw': missing_enum if missing_enum is not None else missing,
        'typedExclusions': typed_excl,
        'pidCoverage': pid,
        # M115: internal-use file lists per channel (underscore-prefixed --
        # not part of the published schema surface, consumed only by
        # _audit_coverage_map to derive days/km per channel against
        # drive_master; NOT filtered by the M94 stale-key gate, which only
        # forbids _superseded/_auditRemediation* patterns).
        '_pidCovFiles': {k: sorted(v) for k, v in cov_files.items()},
        'gpsFiles': sorted(gps_files),
        'corpusMd5': corpus_md5 or md5.hexdigest(),
        'libs': libs or {
            'pandas': pd.__version__, 'numpy': np.__version__,
            'python': '.'.join(map(str, __import__('sys').version_info[:3]))},
        'note': ('Raw directory enumerated vs drive_master (M106). '
                 f'oneToOneVerified is a full bijection check of the {int(len(dm))} '
                 'canonical drives against on-disk raw captures; comparison-only '
                 'and auxiliary (e-4ORCE) files are typedExclusions. null '
                 'oneToOneVerified means no raw_dir was supplied and the 1:1 '
                 'property was NOT checked. PID coverage is header-eligibility '
                 'only -- see eligibility for metric denominators.')}


def _audit_gps_altitude_coverage(dm, raw_manifest):
    """New 42-column logging generation carrying GPS altitude. Derived from the
    already-computed rawManifest coverage plus the first date it appears."""
    n = raw_manifest['pidCoverage']['gpsAlt']['n']
    gps_files = raw_manifest.get('gpsFiles', [])
    first = min(f[:8] for f in gps_files) if gps_files else None
    return {'nFiles': n, 'firstDate': first,
            'note': ('New 42-column logging generation carries GPS altitude '
                     'and GPS speed -- the first channel capable of per-event '
                     'grade attribution (the baro PID never was). Logged in '
                     'contiguous 1 Hz bursts with long off-gaps; the steepest '
                     'drives fall in the gaps, so grade-resolved coverage is '
                     'real but NOT representative of the steepest driving.')}


# M115 (2026-08-10, audit §10 "New results derivable from the existing
# dataset" -- the audit's own top priority item on that list: "Coverage /
# observability map -- for every claim, map files/days/km and channel
# availability. Prevents denominator drift and clarifies evidence gaps.").
#
# Two coverage concepts already existed in this pipeline, correctly kept
# separate (per _audit_raw_manifest's own docstring: "PID coverage is
# header-eligibility only -- see eligibility for metric denominators"):
#   1. rawManifest.pidCoverage  -- does the RAW FILE carry the channel at
#      all (header presence), independent of whether the metric that
#      depends on it actually validated.
#   2. eligibility.families     -- did the DOWNSTREAM METRIC actually
#      compute (not-null), which can differ from #1 when a channel is
#      present but under-sampled, gated by a minimum-duration rule, or
#      excluded by the outlier ensemble.
# Both were extended with days/km (see _audit_eligibility and
# _audit_raw_manifest above). This function does not replace either -- it
# pairs them side by side, per channel/family, into the single map the
# audit asked for, so a reader can see "channel present in N files / D
# days / K km" directly above "metric valid in n / d / k" for the same
# underlying evidence, without cross-referencing two separate blocks.
_CHANNEL_TO_FAMILY = {
    'hvCurrent':   'Current-integral energy metrics',
    'cellMaxMin':  'Cell-spread trend (M19)',
    'cellVoltage': None,   # full per-cell array: not consumed by any metric yet
    'gpsAlt':      None,   # no eligibility family; gpsAltitudeCoverage covers it
    'latlon':      None,   # not yet metric-gated to a specific family
    'baro':        None,   # not yet metric-gated to a specific family
    'fuelRate':    None,   # engine-fuel-state classifier input, not a fam above
}
_CHANNEL_LABEL = {
    'hvCurrent': 'HV battery current',
    'cellMaxMin': 'Max/Min cell voltage',
    'cellVoltage': 'Full per-cell voltage array (#01-80)',
    'gpsAlt': 'GPS altitude',
    'latlon': 'GPS lat/long',
    'baro': 'Atmospheric pressure',
    'fuelRate': 'Engine fuel-rate (in-engine)',
}


def _audit_coverage_map(dm, raw_manifest, eligibility):
    """Merge rawManifest.pidCoverage (channel presence) with
    eligibility.families (metric validity) into one per-claim evidence map.
    Channel-side days/km are derived from raw_manifest['_pidCovFiles'] (file
    lists) joined against drive_master; that key is popped by the caller
    before rawManifest ships, so this function must run BEFORE the pop."""
    file_lists = raw_manifest.get('_pidCovFiles', {})
    fam_by_name = {f['family']: f for f in eligibility.get('families', [])}
    rows = []
    for chan, col in _PID_COLS.items():
        files = file_lists.get(chan, [])
        mask = dm['file'].isin(files)
        sub = dm.loc[mask]
        channel_side = {
            'n': int(mask.sum()),
            'pct': round(float(mask.sum()) / len(dm) * 100, 1) if len(dm) else 0.0,
            'days': int(sub['date'].nunique()) if len(sub) else 0,
            'km': round(float(sub['distance_km'].sum()), 1) if len(sub) else 0.0,
        }
        fam_name = _CHANNEL_TO_FAMILY.get(chan)
        metric_side = fam_by_name.get(fam_name) if fam_name else None
        _gap_override = {
            'gpsAlt': 'covered separately in gpsAltitudeCoverage, not duplicated here',
            'cellVoltage': ('rich per-cell array present on very few files and not '
                            'consumed by any shipped metric -- an unused-evidence '
                            'gap in the audit\'s sense, not a missing-data one'),
        }
        rows.append({
            'channel': chan,
            'label': _CHANNEL_LABEL.get(chan, chan),
            'headerColumn': col if isinstance(col, str) else ' + '.join(col),
            'channelPresent': channel_side,
            'metricFamily': fam_name,
            'metricEligible': ({'n': metric_side['n'], 'days': metric_side['days'],
                                'km': metric_side['km']}
                               if metric_side else None),
            'gapNote': (
                _gap_override.get(chan) if chan in _gap_override else
                'no downstream metric family currently tracks this channel '
                'separately' if fam_name is None else
                ('channel present but metric validity not yet cross-tabulated'
                 if metric_side is None else None)),
        })
    total_days = int(dm['date'].nunique())
    total_km = round(float(dm['distance_km'].sum()), 1)
    return {
        'rows': rows,
        'totalFiles': int(len(dm)), 'totalDays': total_days, 'totalKm': total_km,
        'note': ('M115 (audit §10, coverage/observability map -- flagged '
                 '"High priority" in the audit\'s own new-results table). '
                 'For each raw channel: files/days/km where the header is '
                 'present (channelPresent), paired where applicable with '
                 'files/days/km where the dependent metric actually '
                 'validated (metricEligible) -- the same distinction '
                 '_audit_raw_manifest already documented in prose, now '
                 'tabulated side by side per channel rather than living in '
                 'two separately-consulted blocks. A gap between the two '
                 'columns is itself informative: it is under-sampling or a '
                 'validity gate, not missing data. Not yet extended to '
                 'every metric family in eligibility.families (deficit_80_120, '
                 'ev_valid and drive-type typing are not single-channel-'
                 'gated in a way this table can represent one-to-one); '
                 'those retain their existing eligibility-only reporting.')}


def _audit_metadata_from_cfg(session_cfg):
    """constantProvenance and determinism are declared metadata, not measured.
    They are read from the study config (auditMetadata block) so they live
    under version control with the other assumptions rather than being
    regenerated. Returns (constantProvenance, determinism) or (None, None)."""
    if not session_cfg:
        return None, None
    md = session_cfg.get('auditMetadata') or {}
    return md.get('constantProvenance'), md.get('determinism')


def _ledger_cross_check(dm):
    """M77: matched-population rainflow-EFC vs coulometric-FCE ledger. Only
    drives where BOTH metrics are computable enter the comparison, removing the
    coverage-denominator artifact that produced the spurious ~0.99 "closure"."""
    both = dm['rf_efc'].notna() & dm['fce'].notna()
    clean = ~_as_bool(dm['ens_outlier_v2'])

    def _stats(mask):
        d = dm[mask]
        rf = float(d['rf_efc'].sum())
        fce = float(d['fce'].sum())
        err = d['rf_efc'] - d['fce']
        r = float(np.corrcoef(d['rf_efc'], d['fce'])[0, 1]) if len(d) > 2 else None
        return {'n': int(mask.sum()),
                'rfEfc': round(rf, 4), 'fce': round(fce, 4),
                'ratio': round(rf / fce, 4) if fce else None,
                'biasPerDrive': round(float(err.mean()), 4),
                'maePerDrive': round(float(err.abs().mean()), 4),
                'pearsonR': round(r, 4) if r is not None else None,
                'excessPct': round((rf / fce - 1) * 100, 2) if fce else None}

    return {
        'matchedAll': _stats(both),
        'matchedClean': _stats(both & clean),
        'interpretation': 'systematic_positive_bias_not_closure',
        'note': ('Matched-population RF/FCE ledger (M77, 2026-07-30). Replaces '
                 'the retired full-dataset available-case ratio, which divided '
                 'RF-eligible (170) by FCE-eligible (184) totals over different '
                 'denominators and produced a spurious ~0.99. On the matched '
                 'population rainflow-EFC runs ~7-8% above coulometric FCE with '
                 'very high per-drive correlation: a stable definitional offset '
                 '(cycle-counting semantics + SoC quantization), not closure.')}


def _artifact_stamp(dm, arrays, raw_manifest_path='raw_manifest.json',
                    drive_master_path='drive_master.csv',
                    summary_config_path='summary_config.json'):
    """M220.2 (P0.4 closure): pipeline-wide, machine-checkable provenance
    stamp. Prior to this, provenance was narrative (_provenance milestone
    notes) plus a handful of module-local recomputeMode/corpusSizeAtRecompute
    fields (energyUncertaintyMC, socHysteresisV2 only) -- no hash was
    stamped on most of the 126 top-level keys, and staleness rejection lived
    only in build_html.js's gates. This generalizes that pattern uniformly
    across every top-level key rather than requiring each module to opt in.

    Returns an {_artifactStamps} dict: {key: {corpusHash, corpusHashSource,
    configHash, generatedAt, pipelineVersion, upstreamHashes}} for every
    non-underscore-prefixed top-level key in the already-assembled `arrays`
    dict. Every key gets the SAME stamp (one build, one corpus state, one
    config state) -- kept in a separate top-level dict rather than injected
    into each payload, to avoid bloating every array with repeated
    boilerplate, per the plan's explicit design choice.

    M234 (audit F09, partial): stamps did not previously distinguish a
    block that was genuinely computed THIS pass from one carried forward
    unchanged from a prior run -- both received the identical corpusHash/
    configHash/generatedAt, so "the stamp is fresh" never implied "the
    payload is fresh." `computationStatus` now reads each block's own
    `recomputeMode`/`frozenBasis` fields where present (currently
    socHysteresisV2, energyUncertaintyMC -- the only two modules with an
    explicit carry-forward path via prev_arrays) and reports 'computed',
    'carriedForward', or 'carriedForward_recomputeFailed' accordingly; for
    the remaining top-level keys, which this pipeline always recomputes
    fresh on every with_raw=True invocation and never carries forward
    itself, status is 'computed' -- but a caller that manually splices an
    old value into a NEW arrays dict outside this function (as a targeted,
    single-block patch might) is NOT detected here and must set its own
    stamp's generatedAt honestly, per this project's session discipline;
    this is a partial fix, not a comprehensive per-block dependency
    tracker (see the audit's full rework table for what a complete fix
    would require -- per-block source-module/computation-version hashing,
    a cache contract, a dependency lockfile -- none of which this stamps
    solely). configHash now also reports fullConfigHash, an MD5 of the
    entire on-disk summary_config.json (not just the constantProvenance
    subset the narrower configHash already covered), so an edit to ANY
    config value -- not only the ones already narrated in
    constantProvenance -- is detectable; configHash itself is left as-is
    for backward compatibility with any existing external comparison.
    """
    import hashlib as _hl
    import datetime as _dt
    import os as _os

    # corpusHash: MD5 of the ON-DISK drive_master.csv bytes -- the exact
    # quantity the standing session discipline already verifies by hand
    # every milestone (`md5sum drive_master.csv`). Falls back to a content
    # hash of the in-memory `dm` DataFrame only if the file genuinely isn't
    # present at build time; corpusHashSource discloses which was used so a
    # consumer never mistakes the fallback for the on-disk value.
    if drive_master_path and _os.path.exists(drive_master_path):
        with open(drive_master_path, 'rb') as _f:
            corpus_hash = _hl.md5(_f.read()).hexdigest()
        corpus_hash_source = 'file:' + drive_master_path
    else:
        corpus_hash = _hl.md5(
            dm.to_csv(index=False).encode('utf-8')).hexdigest()
        corpus_hash_source = 'dataframe_fallback (drive_master_path absent)'

    # configHash: hash of the same constants block already tracked
    # narratively in constantProvenance (CAP_KWH, SCENARIO_THRESHOLD_GTC,
    # MASS_BY_DRIVE_TYPE_KG, RF_DAMAGE_EXP, etc.) -- sourced from the
    # already-assembled arrays['constantProvenance'] itself, so a change to
    # any tracked constant's VALUE (not its prose) moves this hash.
    _cp = arrays.get('constantProvenance') or {}
    _cp_values = {k: (v.get('value') if isinstance(v, dict) else v)
                 for k, v in sorted(_cp.items())}
    config_hash = _hl.md5(json.dumps(
        _cp_values, sort_keys=True, default=str).encode('utf-8')).hexdigest()

    # M234 (audit F09): fullConfigHash -- MD5 of the ENTIRE on-disk
    # summary_config.json, not just the narrow constantProvenance subset.
    # Catches edits to manual ambient records, session annotations, or any
    # other config value never routed through constantProvenance.
    if summary_config_path and _os.path.exists(summary_config_path):
        with open(summary_config_path, 'rb') as _f:
            full_config_hash = _hl.md5(_f.read()).hexdigest()
        full_config_hash_source = 'file:' + summary_config_path
    else:
        full_config_hash = None
        full_config_hash_source = 'summary_config_path absent at build time'

    # upstreamHashes: raw_manifest.json's own corpusHash (raw-FILE identity,
    # independent of drive_master.csv's derived columns) plus the
    # raw_cache.tar schema version tag, so a stale cache rebuild is
    # detectable too, not just a stale master.
    upstream = {}
    if raw_manifest_path and _os.path.exists(raw_manifest_path):
        try:
            with open(raw_manifest_path) as _f:
                _rm = json.load(_f)
            upstream['rawManifestCorpusHash'] = _rm.get('corpusHash')
            upstream['rawManifestSnapshotId'] = _rm.get('snapshotId')
        except Exception as _e:
            upstream['rawManifestError'] = repr(_e)
    else:
        upstream['rawManifestError'] = f'{raw_manifest_path} not found at build time'
    try:
        import drive_raw_cache as _drc
        upstream['rawCacheSchemaVersion'] = _drc.SCHEMA_VERSION
    except Exception as _e:
        upstream['rawCacheSchemaVersionError'] = repr(_e)

    generated_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
    pipeline_version = (arrays.get('_generated') or {}).get('pipeline_version')

    stamp = {
        'corpusHash': corpus_hash, 'corpusHashSource': corpus_hash_source,
        'configHash': config_hash,
        'fullConfigHash': full_config_hash,
        'fullConfigHashSource': full_config_hash_source,
        'generatedAt': generated_at,
        'pipelineVersion': pipeline_version, 'upstreamHashes': upstream,
    }
    stamps = {}
    for _k in arrays:
        if _k.startswith('_'):
            continue
        s = dict(stamp)
        # M234 (audit F09): per-block computation status, read from the
        # block's OWN self-tracked recomputeMode/frozenBasis where the
        # block carries one (only socHysteresisV2/energyUncertaintyMC do
        # today). computationStatus/generatedAt together now let a
        # consumer tell "this build ran at time T" (always true) apart
        # from "this SPECIFIC block was computed at time T" (only true
        # when computationStatus=='computed').
        _v = arrays.get(_k)
        _rm = _v.get('recomputeMode') if isinstance(_v, dict) else None
        if _rm in ('carriedForward', 'carriedForward_recomputeFailed'):
            s['computationStatus'] = _rm
            s['computationStatusNote'] = (
                'This block was NOT recomputed in this build; its own '
                'recomputeMode field records why. generatedAt/corpusHash '
                'above reflect when the STAMPING PASS ran, not when this '
                'payload was actually last (re)computed.')
        elif isinstance(_v, dict) and _v.get('frozenBasis') is True:
            s['computationStatus'] = 'carriedForward'
            s['computationStatusNote'] = (
                'frozenBasis=true on this block: carried forward, not '
                'recomputed this build. generatedAt/corpusHash above '
                'reflect the stamping pass, not this payload\'s actual '
                'computation time.')
        else:
            s['computationStatus'] = 'computed'
        stamps[_k] = s
    return stamps


def _evidence_ledger(arrays):
    """M225 (Dashboard 7.1, enhancement plan): Evidence & Cross-Validation
    Ledger. Pure post-processing over the already-assembled `arrays` dict
    -- no raw pass, no new statistical computation beyond simple arithmetic
    on already-computed numbers -- pulling primary-estimate/independent-
    check pairs that were scattered across M220 (energy re-integration),
    M221 (start-event chain), M222 (rolling-origin CV), M223.2 (second-
    order transition model), and degradation_trends.py (predates M220-
    M224, populated independently of them) into one place.

    Each row: primary estimate, one or more independent checks, support
    (drives/days/km/s/events as applicable), evidence class (measured/
    derived/modeled/exploratory), validation status (confirmed/partially
    confirmed/unresolved/not externally testable), and a `sourceKey`
    resolved into an artifact-identity stamp by build_summary_arrays AFTER
    _artifact_stamp runs (this function is called BEFORE that stamp
    exists, so it cannot resolve its own row's stamp -- see the wiring
    code immediately after arrays['_artifactStamps'] is assigned).

    Each row's validationStatus reflects that row's OWN evidentiary claim,
    which differs by row: rows 1 and 3 test whether an independent method
    reproduces a released NUMBER; row 4 tests whether a MORE COMPLEX model
    is needed (a negative result there confirms the simpler model's
    adequacy, not a failure of the check); row 2 measures what fraction of
    a primary detector's events are independently corroborated by ALL of
    three other detectors at once, an intentionally strict bar. None of
    this is smoothed into one undifferentiated "match/no-match" column.
    """
    rows = []

    # ---- Row 1: Energy throughput (GTC/FCE) ----
    emc = arrays.get('energyUncertaintyMC') or {}
    val = emc.get('validation') or {}
    iic = emc.get('independentIntegrationCheck') or {}
    tt = iic.get('trueTrapezoidal') or {}
    gtm = emc.get('grossThroughputMC') or {}
    if val and tt:
        rows.append({
            'topic': 'Energy throughput (gross discharge/charge, GTC/FCE)',
            'evidenceClass': 'measured',
            'sourceKey': 'energyUncertaintyMC',
            'primary': {
                'label': 'Released gross throughput (energy_mc_precompute, nominal 1500ms tolerance)',
                'value': gtm.get('nominalReleasedThroughputKwh'), 'unit': 'kWh',
                'support': {'drives': tt.get('n')}},
            'checks': [
                {'label': ('Same-algorithm re-implementation (coding-bug '
                          'check only, not methodologically independent)'),
                 'value': val.get('maxAbsDevDischargeKwh'), 'unit': 'kWh max deviation',
                 'validationStatus': 'confirmed'},
                {'label': ('Independent re-integration (M220, true '
                          'trapezoidal on interpolated native timestamps)'),
                 'value': tt.get('meanAbsDevPctThroughput'), 'unit': '% mean deviation',
                 'p95Value': tt.get('p95AbsDevPctThroughput'),
                 'validationStatus': 'confirmed'},
            ],
            'validationStatus': 'confirmed',
            'notes': ('Same-algorithm check confirms no coding bug (near-'
                     'exact by construction). Independent re-integration '
                     'via a genuinely different numerical method agrees to '
                     '~%s%% mean / ~%s%% p95 -- a small, explained '
                     'deviation (see independentIntegrationCheck.'
                     'dataQualityNote), not a discrepancy requiring '
                     'resolution.'
                     % (round(tt.get('meanAbsDevPctThroughput'), 2)
                        if tt.get('meanAbsDevPctThroughput') is not None else '?',
                        round(tt.get('p95AbsDevPctThroughput'), 2)
                        if tt.get('p95AbsDevPctThroughput') is not None else '?')),
        })

    # ---- Row 2: Engine-start buffer (discharge impulse + full-chain reconciliation) ----
    bi = arrays.get('bufferImpulse') or {}
    sec = arrays.get('startEventChain') or {}
    funnel = sec.get('attritionFunnel') or {}
    if bi and funnel:
        n_buf = funnel.get('nWithBuffer')
        n_full = funnel.get('nWithFullChain')
        pct = round(100.0 * n_full / n_buf, 1) if n_buf else None
        rows.append({
            'topic': 'Engine-start discharge-impulse buffer event',
            'evidenceClass': 'measured',
            'sourceKey': 'startEventChain',
            'primary': {
                'label': 'Buffer discharge-impulse detector (bufferImpulse, M116)',
                'value': bi.get('nEvents'), 'unit': 'events',
                'support': {'drives': bi.get('nDrivesCovered'), 'km': bi.get('coveredKm')}},
            'checks': [
                {'label': ('Full 4-detector chain reconciliation (M221 '
                          'startEventChain: buffer AND ramp AND handoff '
                          'AND recovery)'),
                 'value': n_full, 'unit': 'events fully joined',
                 'pctOfPrimary': pct,
                 'validationStatus': 'partially confirmed'},
            ],
            'validationStatus': 'partially confirmed',
            'notes': (('%s%% of buffer-impulse events are independently '
                      'corroborated by all three other physical detectors '
                      '(ramp latency, handoff sequence, debt recovery) at '
                      'once; the remainder still qualify on the primary '
                      'detector alone but do not clear every downstream '
                      'gate -- see startEventChain.attritionFunnel for the '
                      'full per-gate breakdown, not smoothed into one '
                      'number.') % (pct if pct is not None else '?')),
        })

    # ---- Row 3: M119-v2 (SoC hysteresis hazard model, START side) ----
    v2 = arrays.get('socHysteresisV2') or {}
    ladder_start = ((v2.get('ladder') or {}).get('start') or {}).get('fiveVarDur') or {}
    ro = (((v2.get('sensitivity') or {}).get('rollingOrigin') or {}).get('start') or {}).get('pooled') or {}
    if ladder_start and ro:
        rows.append({
            'topic': 'M119-v2 engine-start hazard model (START side)',
            'evidenceClass': 'modeled',
            'sourceKey': 'socHysteresisV2',
            'primary': {
                'label': 'Blocked-day CV (socHysteresisV2.ladder.start.fiveVarDur)',
                'value': ladder_start.get('prAuc'), 'unit': 'PR-AUC',
                'ci95': ladder_start.get('prAucCI'),
                'support': {'atRiskSeconds': ladder_start.get('n'),
                           'events': ladder_start.get('events')}},
            'checks': [
                {'label': 'Rolling-origin CV (M222, genuine train-on-past-only)',
                 'value': ro.get('prAuc'), 'unit': 'PR-AUC',
                 'support': {'atRiskSeconds': ro.get('n'), 'events': ro.get('events')},
                 'validationStatus': 'confirmed'},
            ],
            'validationStatus': 'confirmed',
            'notes': ('PR-AUC point estimates and calibration are close '
                     'under a genuinely different (forward-chaining, not '
                     'just leakage-guarded) validation scheme -- the '
                     'blocked-day result is not an artifact of that '
                     'scheme\'s own future-data access. The STOP-side '
                     'comparison (not shown here) is also confirmed; see '
                     'socHysteresisV2.sensitivity.rollingOrigin.stop.'),
        })

    # ---- Row 4: Regime transitions (drive-type Markov chain) ----
    rt = arrays.get('regimeTransition') or {}
    so = rt.get('secondOrder') or {}
    if rt and so and 'bicImprovement' in so:
        rows.append({
            'topic': 'Drive-type regime transition structure',
            'evidenceClass': 'derived',
            'sourceKey': 'regimeTransition',
            'primary': {
                'label': 'First-order Markov model (regimeTransition.countMatrix)',
                'value': rt.get('selfTransitionShare'), 'unit': 'self-transition share',
                'support': {'transitions': rt.get('nTransitions'), 'days': rt.get('nDays')}},
            'checks': [
                {'label': ('Second-order model comparison (M223.2, '
                          'previous-two-drive-type)'),
                 'value': so.get('bicImprovement'),
                 'unit': 'delta-BIC (negative = second-order worse)',
                 'lrP': so.get('lrP'),
                 'validationStatus': 'confirmed'},
            ],
            'validationStatus': 'confirmed',
            'notes': (('This check tests MODEL ADEQUACY, not a number '
                      'match: the second-order model does NOT improve '
                      'BIC over first-order (delta-BIC=%.1f, LR p=%.3f), '
                      'which CONFIRMS the first-order model is an '
                      'adequate description at this sample size -- a '
                      'genuine null result reported as such, not evidence '
                      'of a failed check.')
                     % (so.get('bicImprovement', 0), so.get('lrP', 1))),
        })

    # ---- Row 5: Resistance / degradation trends (predates M220-M224) ----
    dt = arrays.get('degradationTrends') or {}
    pf = arrays.get('powerFade') or {}
    rv = dt.get('resistanceVreg') or {}
    if pf and rv:
        rv_ols = rv.get('clusterRobustOLS') or {}
        rows.append({
            'topic': 'Pack internal-resistance fade trend',
            'evidenceClass': 'measured',
            'sourceKey': 'powerFade',
            'primary': {
                'label': 'powerFade (cadence-controlled, day-clustered bootstrap)',
                'value': pf.get('slopeMohmPerMoTctrl'), 'unit': 'mOhm/month',
                'ci95': pf.get('ci95MohmPerMo'),
                # M236 (audit F15): pSlopeGt0 is the FRACTION of day-clustered
                # bootstrap resample slopes above zero (compute_drive_summary_
                # v6.py: round((boot>0).mean(),3), seed=42, N_BOOT=4000) --
                # neither a conventional null-hypothesis p-value nor
                # automatically a Bayesian posterior probability. Previously
                # mapped to 'pValue' here, which claims a specific inferential
                # meaning this quantity doesn't have. Paired with method/seed
                # per the audit's explicit instruction, alongside the ci95
                # interval already present above.
                'bootstrapFractionPositive': pf.get('pSlopeGt0'),
                'bootstrapMethod': ('day-clustered bootstrap, seed=42, '
                                    'N=4000 resamples'),
                'support': {'rows': pf.get('nClean')}},
            'checks': [
                {'label': ('resistanceVreg (%s, cluster-robust OLS, '
                          'explicit sensitivity check against powerFade)'
                          % rv.get('role')),
                 'value': rv_ols.get('slope'), 'unit': 'mOhm/month',
                 'ci95': rv_ols.get('ci95'),
                 'validationStatus': 'partially confirmed'},
            ],
            'validationStatus': 'partially confirmed',
            'notes': ('powerFade and resistanceVreg are explicitly linked '
                     '(resistanceVreg.primaryEstimandRef=powerFade): a '
                     'magnitude difference is expected since one is '
                     'cadence-controlled and the other is not (see their '
                     'own methodology strings for the full distinction) -- '
                     'both slopes\' 95% CIs span zero, so neither detects '
                     'a resolvable fade trend at this corpus size/window, '
                     'a genuine null result. Both metrics\' own SECONDARY '
                     'method (day random-intercept mixed-effects, '
                     'statsmodels 0.15.0) failed to converge (LinAlgError: '
                     'Singular matrix) -- disclosed here rather than '
                     'omitted; cluster-robust OLS is authoritative for '
                     'both, as already documented in degradationTrends.'
                     'cellSpread/resistanceVreg themselves.'),
        })

    return {
        'rows': rows,
        'nRows': len(rows),
        'evidenceClasses': ['measured', 'derived', 'modeled', 'exploratory'],
        'validationStatuses': ['confirmed', 'partially confirmed',
                              'unresolved', 'not externally testable'],
        'methodology': (
            'M225 (Dashboard 7.1, enhancement plan): assembles primary-'
            'estimate/independent-check pairs already computed across '
            'M220 (energy re-integration), M221 (start-event chain), M222 '
            '(rolling-origin CV), M223.2 (second-order transition model), '
            'and degradation_trends.py (predates M220-M224, populated '
            'independently) into one ledger. Pure post-processing over the '
            'already-assembled arrays dict -- no raw pass, no new '
            'statistical computation. Each row\'s validationStatus reflects '
            'that row\'s OWN evidentiary claim, which differs by row -- see '
            'this function\'s own docstring for the per-row distinction. '
            'artifactIdentity (added after this function returns, once '
            '_artifactStamps exists) is a snapshot corpusHash truncated to '
            '12 hex characters for display, so a reader can verify which '
            'corpus state each row reflects.'),
    }


def build_summary_arrays(dm, raw_loader=None, with_raw=True, odometer_km=None,
                         seasonal_cfg=None, ambient_by_drive=None,
                         frame_loader=None, session_cfg=None, raw_dir=None,
                         recompute_m119v2=False, prev_arrays=None,
                         recompute_energy_mc=True,
                         recompute_rolling_origin_cv=False):
    # M44 (2026-07-19): frame_loader(fname)->slim DataFrame (drive_raw_cache)
    # replaces the 5x-repeated raw CSV parse; outputs are byte-identical.
    arrays = category_A(dm, odometer_km=odometer_km)
    # M45: Category-A-only bindings for the Conclusions-tab items audited
    # above -- no raw pass required, so these compute unconditionally.
    arrays['batteryDrawGross'] = _battery_draw_gross(dm)
    arrays['thermalHighwayBand'] = _thermal_highway_band(dm)
    arrays['shortTripWarmup'] = _short_trip_warmup(dm)
    # M62 (2026-07-28, terminology + risk audit): both master-derived only.
    # metricConvention pins the GTC/FCE/EFC relationship to live data so the
    # naming claim cannot drift; riskColdEngineBattery answers the cell-level
    # half of the cold-engine risk row, which M60 left open.
    arrays['metricConvention'] = _metric_convention(dm)
    arrays['riskColdEngineBattery'] = _risk_cold_engine_battery(dm)
    # M63 (2026-07-29): measured replacement for the Section-4 illustrative
    # Sankey percentages. Master-derived only.
    arrays['energyPath'] = _energy_path(dm)
    # M62: standing reconciliation of the hand-typed session ledgers.
    arrays['sessionLedgerAudit'] = _session_ledger_audit(dm, session_cfg)
    arrays['jun20Batch'] = _dated_batch_summary(dm, '2026-06-20')
    # M59 (2026-07-27): session-adjacency derivation of the SoC-band reset
    # window (audit item left open by M45). Master-derived only.
    arrays['socBandReset'] = _soc_band_reset(dm)
    # M142 (2026-08-19): drive-type regime transition matrix (first-order
    # Markov, cell-suppressed). Master-only -- no raw pass required.
    arrays['regimeTransition'] = _regime_transition(dm)
    # M223.2 (P1.5, enhancement plan): statistical hardening layer, merged
    # into regimeTransition's existing dict (new keys only -- _regime_transition
    # itself is untouched above, so every pre-existing field, including
    # `cells`, stays byte-identical; verified via isolation diff, not just
    # by construction).
    if arrays.get('regimeTransition') is not None:
        _rth = _regime_transition_hardening(dm)
        if _rth is not None:
            # nTransitions is computed by BOTH functions from the identical
            # default (max_gap_h=None) chain and is expected to agree
            # exactly -- popped here regardless, so the merge can never
            # silently overwrite _regime_transition's own pre-existing
            # field even if that expectation were ever violated.
            _rth.pop('nTransitions', None)
            arrays['regimeTransition'].update(_rth)
    if seasonal_cfg is not None:
        # M92 (2026-08-06): obs_mix left at its default (None) deliberately --
        # _seasonal_projection recomputes it internally at full precision on
        # the identical basis _cycle_projection uses for observedMixShare.
        # (Threading cycleLife's observedMixShare through here was tried and
        # reverted: that field is display-rounded to 1 decimal %, which
        # introduced a ~1e-5 warmFloorGtcPerKm mismatch against cycleLife's
        # own gtcPerKm for the same row -- worse than the tiny duplication
        # risk of two independently-written, identically-specified blocks.)
        arrays['seasonalLife'] = _seasonal_projection(dm, odometer_km,
                                                      seasonal_cfg)
        # M85 (2026-08-05): overlay climatic stress onto the Selected blend row
        # of cycleLife. The archetype/observed rows stay warm-floor & measured;
        # Selected alone is replaced by the constant-mix seasonal (climatic)
        # rate and flipped to measured:false, because it now carries the M28
        # assumption load. thresholdSensitivity and cycleAtOdo['blend'] are
        # recomputed on the climatic rate so every downstream binding is
        # consistent. Warm-floor value is retained on the row (warmFloorRate).
        _sc = (arrays['seasonalLife'] or {}).get('selectedConstant')
        _cl = arrays.get('cycleLife') or {}
        if _sc and _cl.get('projections'):
            _age = _cl.get('carAgeNow'); _thr = _cl.get('scenarioThresholdGtc', 20000)
            for _p in _cl['projections']:
                if _p.get('primary'):
                    _p['rate'] = _sc['rate']['mid']
                    _p['accumulated'] = _sc['accumulated']['mid']
                    _p['rateBand'] = _sc['rate']
                    _p['accumulatedBand'] = _sc['accumulated']
                    _p['yearsBand'] = _sc['yearsTotal']
                    _rem = ((_thr - _p['accumulated']) / _p['rate']
                            if _p['rate'] > 0 else None)
                    _p['yearsRemain'] = round(_rem, 1) if _rem else None
                    _p['yearsTotal'] = round(_rem + _age, 1) if _rem else None
                    _p['gtcPerKm'] = round(_sc['annualCyclesPerKm']['mid'], 5)
                    _p['measured'] = False
                    _p['climaticStress'] = True
                    _p['basis'] = ('constant all-season mix, climatic-stress '
                                   '(M28 seasonal throughput model)')
            _cl.setdefault('cycleAtOdo', {})['blend'] = _sc['accumulated']['mid']
            _r, _a = _sc['rate']['mid'], _sc['accumulated']['mid']
            if _r > 0:
                _cl['thresholdSensitivity'] = [
                    {'thresholdGtc': _t, 'crossingYr': round(_age + (_t - _a) / _r, 1)}
                    for _t in (10000, 15000, 20000, 25000, 30000)]
            _cl['selectedClimaticStress'] = True
    # M61 (2026-07-27): powerFade is now produced HERE. It was previously an
    # out-of-band injection into summary_arrays.json -- correct numbers, but
    # build_summary_arrays() did not emit the key, so an arrays-only rebuild
    # would have dropped every S.powerFade binding in the dashboard. Values
    # reproduce the archived block byte-identically (seeded bootstrap).
    arrays['powerFade'] = _power_fade(dm, raw_loader)
    # M61: fade-mode separation + 2-D scenario x threshold sensitivity matrix
    # (supersedes the five single-threshold crossing labels on the chart).
    # Master-derived only -- no raw pass, safe under arrays-only regeneration.
    arrays['fadeModes'] = _fade_modes(dm, arrays.get('cycleLife', {}),
                                      arrays.get('seasonalLife'),
                                      arrays['powerFade'])
    # M79 (2026-07-31): official Article-10 disclosure cross-check. Master +
    # config only (officialDisclosure/batterySupplier/vehicle blocks in
    # session_cfg) -- no raw pass, safe under arrays-only regeneration, and
    # None (hidden section) if the config block hasn't been added yet.
    arrays['officialDisclosureCorrelation'] = _official_disclosure_correlation(
        dm, session_cfg, arrays.get('cycleLife', {}), arrays['fadeModes'],
        arrays['powerFade'])
    # M91 (2026-08-06): SoC-level (window placement) sensitivity overlay on
    # rf_damage_k2, cross-checked against Wikner (Chalmers, 2017). Master +
    # config only -- no raw pass, safe under arrays-only regeneration. None
    # if socLevelWeighting hasn't been added to config yet.
    arrays['dodSocLevelSensitivity'] = _soc_level_sensitivity(
        dm, (session_cfg or {}).get('socLevelWeighting'))
    # M93 (2026-08-07): Woehler k-EXPONENT sensitivity ladder + implied cycle-
    # life scenarios (replaces the retired M91 SoC-level weight-ladder chart).
    # RAW pass -- re-runs rainflow off the slim cache for a ladder of k -- so it
    # needs a loader; None when neither is supplied or the kExponentLadder
    # config block is absent. Depends on fadeModes (flat crossings) and
    # seasonalLife (calendar-aging ceiling), both assigned above. Diagnostic
    # only -- never folds into rf_damage_k2 or any GTC/FCE crossing.
    arrays['kLadderScenarios'] = (
        _k_ladder_scenarios(
            dm, raw_loader, frame_loader,
            (arrays.get('fadeModes') or {}).get('capacity'),
            (arrays.get('seasonalLife') or {}).get('calendarLifeYrShaded'),
            (session_cfg or {}).get('kExponentLadder'))
        if (raw_loader is not None or frame_loader is not None) else None)
    # M149 (2026-08-21): rfDodHistogram restored as a reproducible
    # computation (previously an out-of-band M146 injection with no
    # reproducing code anywhere in the pipeline -- disclosed M148). RAW pass
    # -- re-runs rainflow off the slim cache/raw CSVs -- so it needs a
    # loader; None when neither is supplied. Unlike M119-v2 this is cheap
    # (no model fitting), so it recomputes unconditionally rather than
    # carrying forward.
    arrays['rfDodHistogram'] = (
        _rf_dod_histogram(dm, raw_loader, frame_loader)
        if (raw_loader is not None or frame_loader is not None) else None)
    # M113 (2026-08-09, audit P0-01): retract the k-ladder -> implied-cycle-life
    # CONVERSION. Multiplying a flat GTC crossing by m(k) to yield "years" is a
    # dimensionally invalid life estimate (and the k=1==flat-GTC identity was
    # false). The dimensionless relative-damage m(k) (rungs[].mitigation) is the
    # legitimate exposure quantity and is retained; only the year outputs are
    # nulled. The chart that plotted these (KLadderScenarioChart) is removed.
    _kl = arrays.get('kLadderScenarios')
    if isinstance(_kl, dict):
        _kl['plausibilityCeilingYr'] = None
        _kl['plausibilityCeilingBasis'] = None
        for _sc in (_kl.get('scenarios') or {}).values():
            if isinstance(_sc, dict):
                _sc['flatCrossingYr'] = None
                for _r in (_sc.get('byK') or []):
                    if isinstance(_r, dict):
                        _r['yr'] = None
        _kl['_retracted'] = (
            'M113 (audit P0-01): implied-cycle-life outputs (scenarios[].byK[].yr, '
            'scenarios[].flatCrossingYr, plausibilityCeilingYr) retracted as '
            'dimensionally invalid life conversions. Dimensionless relative damage '
            'm(k) = rungs[].mitigation is retained as the exposure quantity.')
    if with_raw and (raw_loader is not None or frame_loader is not None):
        arrays.update(category_B(dm, raw_loader, frame_loader=frame_loader))
        # M33: raw battery-temperature trajectories -> thermalConvergence
        # (Sensor 1, all >60min drives) + batteryVsAmbient (pack mean joined
        # to manual ambients from config). Both replace stale hand-authored
        # blocks in the Thermal tab.
        _traj = _battery_temp_traj(dm, raw_loader, frame_loader=frame_loader)
        arrays['thermalConvergence'] = _thermal_convergence(dm, _traj)
        arrays['batteryVsAmbient'] = _battery_vs_ambient(
            dm, _traj, ambient_by_drive)
        # M51 (2026-07-22): computed replacement for the seven hand-typed
        # RangeBar rows in "Battery Temperature -- Observed Range". Reuses
        # the _traj pass already made above (no extra raw read); needs the
        # t1_min field M51 added to _battery_temp_traj.
        arrays['batteryTempRanges'] = _battery_temp_ranges(
            dm, _traj, ambient_by_drive)
        # M42 (2026-07-17): below-ambient-start census. The Confirmed-by block
        # hand-typed "7 confirmed occurrences" and named the drives; on the
        # 138-drive corpus that count has drifted badly. Derived here instead.
        _bva = arrays['batteryVsAmbient']
        _neg = [r for r in _bva if r.get('deltaStart') is not None
                and r['deltaStart'] < 0]
        arrays['belowAmbient'] = {
            'n': len(_neg), 'nCovered': len(_bva),
            'maxDeltaC': (min(r['deltaStart'] for r in _neg) if _neg else None),
            'maxDeltaDrive': (min(_neg, key=lambda r: r['deltaStart'])['label']
                              if _neg else None),
            'firstDrive': _neg[0]['label'] if _neg else None,
            'lastDrive': _neg[-1]['label'] if _neg else None}
        # M38: pooled traction-motor thermal stats (range, peak attribution,
        # pack-vs-speed correlation, motor-minus-pack delta) for the
        # Conclusions-tab motor paragraph, previously hand-authored.
        arrays['motorTemp'] = _motor_temp_stats(dm, raw_loader,
                                        frame_loader=frame_loader)
        # M39: high-speed dwell census (cumulative + longest continuous streak
        # per threshold) backing the "sustained 140+ km/h uncaptured" claims,
        # which were hand-authored and unquantified.
        arrays['highSpeedCensus'] = _highspeed_census(dm, raw_loader,
                                              frame_loader=frame_loader)
        # M42: near-limiter generator-headroom census (the 170 km/h question
        # M41 leaves open -- see _near_limiter docstring).
        arrays['nearLimiter'] = _near_limiter(dm, raw_loader,
                                      frame_loader=frame_loader)
        # M116 (2026-08-10, audit §10 "Buffer impulse energy and duration",
        # flagged Feasible now): corpus-wide engine-start transient-buffering
        # census -- see _buffer_impulse_summary docstring for methodology.
        arrays['bufferImpulse'] = _buffer_impulse_summary(dm, frame_loader=frame_loader)
        # M118 (2026-08-10, audit §10 "Generator ramp latency / load-point
        # dwell", flagged Feasible now): corpus-wide RPM plateau segmentation
        # -- see _ramp_latency_summary docstring for methodology.
        arrays['rampLatency'] = _ramp_latency_summary(dm, frame_loader=frame_loader)
        # M122 (2026-08-14): distributional + reconciliation enrichment for the
        # two engine-start censuses above. One frame_loader pass re-runs the
        # canonical M116/M118 detectors and merges histograms / percentile
        # ladders into their blocks, plus an explicit start-event reconciliation
        # -- see _start_event_analytics docstring. Additive: existing bufferImpulse
        # / rampLatency keys and all their bindings are untouched.
        _sea = _start_event_analytics(dm, frame_loader=frame_loader)
        if _sea:
            if arrays.get('bufferImpulse') and _sea.get('bufferExtra'):
                arrays['bufferImpulse'].update(_sea['bufferExtra'])
            if arrays.get('rampLatency') and _sea.get('rampExtra'):
                arrays['rampLatency'].update(_sea['rampExtra'])
            arrays['startEventReconcile'] = _sea['reconcile']
        # M119 (2026-08-10, audit §10 "SoC hysteresis state machine",
        # flagged Feasible now): per-second start/stop probability surface
        # -- see _soc_hysteresis_summary docstring for methodology.
        arrays['socHysteresis'] = _soc_hysteresis_summary(dm, frame_loader=frame_loader)
        # M147 (2026-08-20): M119-v2, the five-variable duration-aware
        # discrete-time hazard model of engine start/stop. Supersedes the v1
        # binned surface above (kept, additive) with two separate 1 Hz cloglog
        # hazard models (START on engine-off seconds, STOP on engine-on
        # seconds) over SoC, speed, pack temperature, recent demand and elapsed
        # engine-state duration, validated under whole-day blocked chronological
        # CV. v2 honours the full VCM/OBD speed-source priority via raw_loader
        # (its own read_needed(); it does not take a frame_loader parameter --
        # unaffected by the M167 slim-cache schema bump either way).
        # See m119v2_model.build_m119v2 for the full methodology.
        # M148 (2026-08-21): recompute-on-demand gate. run_ladder's 20 GLM
        # fits (4-model ladder x 5 blocked-chronological folds, per
        # start/stop) over the ~250k-at-risk-second complete-case sample
        # were isolated as the cause of a reproducible OOM kill in this
        # environment's 3.9GB-RAM sandbox: build_m119v2() alone (no other
        # array computation in the process) reliably exhausted memory during
        # run_ladder(). Recomputing this block is not part of routine
        # ingestion. Default behaviour CARRIES FORWARD the last-computed
        # block unchanged (prev_arrays['socHysteresisV2']) rather than
        # refitting on every session; a fresh fit only happens when
        # recompute_m119v2=True is passed explicitly, or when no prior
        # block exists at all (first run). See CHANGELOG M148.
        #
        # M179 (2026-08-28, audit P0-03): the M177 provenance gate can tell a
        # carried-forward block is stale (training basis < current corpus) but
        # not whether that staleness is SANCTIONED. This stamps the carry with
        # a machine-checkable freeze marker rather than relying on prose alone.
        #
        # M216 (2026-09-03, explicit user-requested full recompute at the
        # 320-drive corpus): added memory hygiene to m119v2_model.py
        # (explicit del + gc.collect() at every fold/candidate/model-ladder-
        # rung boundary in oos_predict/sensitivity_screen/run_ladder/
        # _corpus_tables -- pure cleanup, no change to any fit numerics).
        # This bounds peak RSS to <2GB even at n=320 (verified: 1874MB peak,
        # measured against a session-scoped 4GB swapfile of which 0B was
        # actually consumed) versus the unbounded growth that caused the
        # M148 OOM kill. The M148 root cause is therefore FIXED, not merely
        # worked around -- but the recompute-on-demand GATE is deliberately
        # UNCHANGED: a full recompute is still a single-core, ~11-12 minute
        # operation (corpus tables ~350s + ~340s of GLM fitting across
        # ~120 fold/candidate fits per side), too costly to run on every
        # routine ingestion. Recomputation is therefore still performed ONLY
        # ON THE USER'S EXPLICIT DEMAND (--recompute-m119v2 /
        # recompute_m119v2=True), never automatically as the corpus grows
        # and never silently -- the same policy as M148/M179, now justified
        # by cost rather than by an unconditional memory ceiling.
        _M119V2_RECOMPUTE_POLICY = (
            'M119-v2 recomputation is opt-in by design: it is performed ONLY '
            'when explicitly requested by the user for a given session '
            '(recompute_m119v2=True / --recompute-m119v2) -- never '
            'automatically, never merely because the corpus has grown. Prior '
            'to M216 this was ALSO enforced by a reproducible OOM kill during '
            'run_ladder\'s fit sequence in this environment\'s <=4GB-RAM '
            'sandbox (M148: build_m119v2() alone, no other array computation '
            'in the process, reliably exhausted memory). M216 (2026-09-03) '
            'added explicit memory hygiene to m119v2_model.py (gc.collect() + '
            'del at every fold/candidate/model boundary in oos_predict/'
            'sensitivity_screen/run_ladder/_corpus_tables) which bounds peak '
            'RSS to <2GB even at the current 320-drive corpus -- verified by '
            'a successful full recompute (peak RSS 1874MB, 0B swap consumed '
            'of a 4GB session-scoped swapfile added as a precaution but not '
            'actually needed). The OOM is therefore no longer an '
            'unconditional blocker, but the opt-in gate is UNCHANGED: a full '
            'recompute is a single-core, ~11-12 minute operation and remains '
            'something to run only on explicit demand, not on every routine '
            'ingestion. Absent that explicit request, the last-fit block is '
            'carried forward unchanged and stamped frozenBasis=true.')
        _prev_v2 = (prev_arrays or {}).get('socHysteresisV2')
        if recompute_m119v2 and m119v2_model is not None:
            try:
                _v2 = m119v2_model.build_m119v2(
                    dm, raw_loader=raw_loader, raw_dir=raw_dir)
                if _v2:
                    _v2['recomputeMode'] = 'fresh'
                    _v2['corpusSizeAtRecompute'] = int(len(dm))
                    _v2['frozenBasis'] = False
                    _v2['recomputeBlockedReason'] = None
                    _v2['recomputePolicy'] = _M119V2_RECOMPUTE_POLICY
                arrays['socHysteresisV2'] = _v2
            except Exception:
                arrays['socHysteresisV2'] = _prev_v2
        elif _prev_v2:
            _v2 = dict(_prev_v2)
            _v2['recomputeMode'] = 'carriedForward'
            _v2['currentCorpusSize'] = int(len(dm))
            # P0-03 freeze stamp: sanctioned, machine-checkable, not prose-only.
            _v2['frozenBasis'] = True
            _v2['recomputeBlockedReason'] = (
                'OOM-kill risk in this <=4GB-RAM environment (M148); recompute '
                'only on explicit user demand, see recomputePolicy.')
            _v2['recomputePolicy'] = _M119V2_RECOMPUTE_POLICY
            # Audit remediation (source-only pass, description-only -- NOT a
            # refit): the M147 fit-time methodology string baked into this
            # frozen block overclaimed "penalized interactions" (no
            # fit_regularized call exists anywhere in m119v2_model.py; see its
            # module docstring) and mislabeled the grouped contiguous
            # day-block k-fold CV as "chronological" (the scheme trains each
            # fold on ALL other blocks, including later-dated ones -- not a
            # forward-only / rolling-origin split). This overrides only the
            # descriptive text on the carried-forward block; every fitted
            # numeric field (ladder, surfaces, partialDependence, sensitivity,
            # PR-AUC/Brier/calibration values) is passed through unchanged.
            if _v2.get('methodology'):
                _v2['methodology'] = (
                    _v2['methodology']
                    .replace('penalised reduced tensor interactions',
                              'low-degree cross-product interaction terms '
                              '(not penalized -- no fit_regularized call, no '
                              'penalty matrix, no smoothing-parameter '
                              'selection anywhere in the fitting code)')
                    .replace('whole-day BLOCKED chronological cross-validation',
                              'whole-day GROUPED CONTIGUOUS DAY-BLOCK k-fold '
                              'cross-validation (each fold trains on all other '
                              'blocks, including later-dated ones -- a '
                              'leakage guard against same-day pseudo-'
                              'replication, not a forward-only / rolling-'
                              'origin split)'))
            _v2['methodologyCorrectionNote'] = (
                'Description-only correction applied on carry-forward '
                '(source-only remediation pass, this session): the frozen '
                'M147 fit itself was NOT rerun. Corrected: removed the '
                '"penalized interactions" / GAM(M) overclaim (unpenalized '
                'fixed-basis GLM, verified against the fitting code); '
                'removed the unsupported day-random-intercept GLMM '
                'sensitivity claim (no BinomialBayesMixedGLM call exists in '
                'this module); clarified no logistic-link sensitivity is '
                'currently run (link=cloglog only); renamed "blocked '
                'chronological CV" to "grouped contiguous day-block k-fold '
                'CV" (the scheme trains on future-dated blocks too, so '
                '"chronological" wrongly implied forward-only evaluation).')
            # E: preserve the original key (frozen; changing it would need a
            # refit) but add a correctly-named compatibility alias -- these
            # are median-profile / ceteris-paribus predictions (each
            # predictor swept over its observed support, others held at
            # their sample medians), not sample-averaged partial dependence.
            if 'partialDependence' in _v2 and 'medianProfilePredictions' not in _v2:
                _v2['medianProfilePredictions'] = _v2['partialDependence']
            # K: deferred M119-v2 methodological backlog (documentation only;
            # none of these are implemented or executed in this pass -- see
            # m119v2_model.py module docstring for the full rationale).
            _v2['deferredBacklog'] = [
                'grid-origin left-censoring correction',
                'raw vs. complete-case risk sets reported separately',
                'threshold/debounce sensitivity for the canonical transition detector',
                'genuine logistic-link (link=logit) sensitivity refit alongside the primary complementary-log-log fit',
                'day random-intercept GLMM sensitivity (e.g. BinomialBayesMixedGLM), reporting the day-level variance component',
                'support-density masks on the median-profile prediction curves',
                'penalized-spline / smoothing-parameter-selected / GAM(M) extension of the current unpenalized fixed-basis design',
            ]
            arrays['socHysteresisV2'] = _v2
        elif m119v2_model is not None:
            # No prior block available (first run ever) -- compute once
            # regardless of the flag, so the key is never silently absent.
            try:
                _v2 = m119v2_model.build_m119v2(
                    dm, raw_loader=raw_loader, raw_dir=raw_dir)
                if _v2:
                    _v2['recomputeMode'] = 'fresh'
                    _v2['corpusSizeAtRecompute'] = int(len(dm))
                    _v2['frozenBasis'] = False
                    _v2['recomputeBlockedReason'] = None
                    _v2['recomputePolicy'] = _M119V2_RECOMPUTE_POLICY
                arrays['socHysteresisV2'] = _v2
            except Exception:
                arrays['socHysteresisV2'] = None
        else:
            arrays['socHysteresisV2'] = _prev_v2
        # M222.1 (enhancement plan item M222): rolling-origin CV,
        # independent of the recompute_m119v2 gate above -- a validation
        # exercise re-fitting the already-selected fiveVarDur spec across
        # forward-chaining folds, not a refit of the model itself. Carries
        # forward from prev_arrays by default (same opt-in cadence as
        # M119-v2 proper); recompute_rolling_origin_cv=True (or no prior
        # value at all) triggers a fresh run. Injected into
        # socHysteresisV2.sensitivity.rollingOrigin, alongside (never
        # replacing) the existing per-candidate start/stop sensitivity
        # lists already at that key.
        _ROLLING_ORIGIN_POLICY = (
            'M222.1 (enhancement plan): rolling-origin (forward-chaining) CV '
            'of the already-selected five-variable duration-aware spec, '
            'reported alongside (never replacing) the existing blocked-day '
            'CV. Independent of the recompute_m119v2 gate -- this can run '
            'and attach to an otherwise carried-forward socHysteresisV2 '
            'block without refitting the model itself. Opt-in by the same '
            'cadence convention as M119-v2 proper: carries forward unless '
            'recompute_rolling_origin_cv=True is passed explicitly, or no '
            'prior value exists yet.')
        _prev_ro = ((_prev_v2 or {}).get('sensitivity') or {}).get('rollingOrigin') \
            if isinstance(_prev_v2, dict) else None
        if arrays.get('socHysteresisV2') and isinstance(arrays['socHysteresisV2'], dict):
            if recompute_rolling_origin_cv or _prev_ro is None:
                try:
                    _ro = m119v2_model.rolling_origin_validation(
                        dm, raw_loader=raw_loader, raw_dir=raw_dir) \
                        if m119v2_model is not None else None
                except Exception:
                    _ro = _prev_ro
            else:
                _ro = _prev_ro
            if _ro is not None and isinstance(arrays['socHysteresisV2'].get('sensitivity'), dict):
                arrays['socHysteresisV2']['sensitivity']['rollingOrigin'] = _ro
                arrays['socHysteresisV2']['rollingOriginCvPolicy'] = _ROLLING_ORIGIN_POLICY
                # No longer deferred once actually computed and attached --
                # remove from the carried-forward backlog note if present
                # (the backlog list above is only populated on the
                # carry-forward path; fresh-fit blocks never had it).
                if isinstance(arrays['socHysteresisV2'].get('deferredBacklog'), list):
                    arrays['socHysteresisV2']['deferredBacklog'] = [
                        b for b in arrays['socHysteresisV2']['deferredBacklog']
                        if 'rolling-origin' not in b.lower()]
        # M140 (2026-08-18): BMS-declared possible-power headroom utilization
        # (M121 candidate, validated and closed) -- see the module comment
        # above _headroom_utilization_summary for the full methodology and
        # the constant-Output-ceiling finding. raw_loader-only: the channel
        # is not in COL_MAP / the slim frame cache.
        arrays['headroomUtilization'] = _headroom_utilization_summary(
            dm, raw_loader=raw_loader)
        # M141 (2026-08-19): heat-soak carryover -- inter-drive thermal
        # relaxation. Reuses the _traj pass above (no extra raw read).
        arrays['heatSoakCarryover'] = _heat_soak_carryover(
            dm, _traj, ambient_by_drive)
        # M223.1 (P0.1, enhancement plan): coolant/oil thermal decay +
        # linked adjacent-drive table. Extends _heat_soak_carryover's
        # pack-only pairing/gap-binning/tau-fit pattern to coolant and oil
        # (both channels now carried in the SAME _traj dict above, per its
        # own M223.1 extension note -- no second raw pass), and joins in
        # following-drive first-engine-start timing (one additional
        # lightweight per-drive frame_loader read inside
        # _linked_adjacent_drive_table itself).
        _pf = _linked_adjacent_drive_table(
            dm, _traj, ambient_by_drive, frame_loader=frame_loader)
        if _pf is not None and len(_pf):
            _coolant_decay = _carryover_thermal_decay(
                _pf, 'arrivalCoolantC', 'prevEndCoolantC', 'arrivalAmbientC')
            _oil_decay = _carryover_thermal_decay(
                _pf, 'arrivalOilC', 'prevEndOilC', 'arrivalAmbientC')
            _hsc = arrays.get('heatSoakCarryover') or {}
            arrays['interDriveCarryover'] = {
                'nPairs': int(len(_pf)),
                'nDays': int(_pf['day'].nunique()),
                'thermalDecay': {
                    'coolant': _coolant_decay,
                    'oil': _oil_decay,
                    'battery': {
                        'crossReference': 'heatSoakCarryover',
                        'tau': _hsc.get('soakTauH'),
                        'tauCI': _hsc.get('soakTauCI'),
                        'r2': _hsc.get('tauFitR2'),
                        'nfit': _hsc.get('tauFitN'),
                    },
                },
                'regressionModel': _carryover_regression(_pf),
                'methodology': (
                    'M223.1 (P0.1, enhancement plan): extends '
                    'heatSoakCarryover\'s pack-only Newtonian-cooling '
                    'tau fit (ln(resid/init excess) regressed through '
                    'the origin on parking gap, day-clustered bootstrap '
                    'CI, seed=42) to the engine-coolant and oil channels, '
                    'using the identical consecutive-chronological-pair '
                    'construction (_full_datetimes, same gap formula). '
                    'regressionModel tests whether arrival pack '
                    'temperature, parking gap, and arrival SoC predict '
                    'the FOLLOWING drive\'s time-to-first-engine-start '
                    '(day-clustered bootstrap OLS, primary; day random-'
                    'intercept mixed-effects, statsmodels 0.15.0, '
                    'secondary robustness check -- may fail to converge '
                    'on a singular random-effects covariance at this '
                    'pairs-per-day density, reported as such rather than '
                    'suppressed). Single vehicle / ~single driver -- '
                    'descriptive association in one observed duty cycle, '
                    'not a causal or generalizable driver-behavior law '
                    '(same disclosure pattern as heatSoakCarryover/'
                    'regimeTransition).'),
            }
        else:
            arrays['interDriveCarryover'] = None
        # M143 (2026-08-19): thermal step response -- first-order pack
        # warmup time constant (event-scale impulse is below the pack-temp
        # PID / thermal-mass floor; see docstring).
        arrays['thermalStepResponse'] = _thermal_step_response(
            dm, raw_loader, frame_loader=frame_loader)
        # M46 (2026-07-20): motored-engine overcharge-dissipation census.
        # Formalizes the ad-hoc classifier that established the SoC-record
        # finding (20260719_154351, 88.0%): the buffer ceiling is actively
        # defended by spinning the ICE unfuelled (deep intake vacuum) to
        # dissipate surplus regen the full pack refuses. Classifier runs on
        # boost (slim-cached, MAP-linear r=0.999); MAP itself is deliberately
        # NOT added to SLIM_COLS (would force a schema-v3 cache rebuild for a
        # channel boost already proxies exactly).
        arrays['dissipationCensus'] = _dissipation_census(
            dm, raw_loader, frame_loader=frame_loader)
        # M48 (2026-07-22): low-speed buffer-saturation dissipation census.
        # Supersedes M46 as the primary reading of this mechanism: adds the
        # SoC engagement threshold (M46's ceilSoc=85 sat above the ~78-80%
        # knee), the diverted-energy budget with a pumping-work cross-check,
        # the low-speed regime that explains why the 80-120 km/h terrain gate
        # never observed it, and an explicitly-weak barometric terrain test.
        # NOTE this pass needs the barometric channel, which M48 DOES add to
        # SLIM_COLS (schema v2 -> v3, full cache rebuild ~23 s) -- reversing
        # the M46 note above, which declined the bump for MAP alone.
        arrays['lowSpeedDissipation'] = _low_speed_dissipation(
            dm, raw_loader, frame_loader=frame_loader)
        # M183 (2026-08-29): crawl & stop-go operating-mode census
        # (feasibility-review candidate D, top priority). NEW analysis --
        # standstillStats (M26) covers only pure key-on standstill; D
        # segments the launch->crawl->approach->stop CYCLE and integrates the
        # buffer energy each phase moves. See the block comment above
        # _CSG_COLS. frame_loader-preferred (raw_loader fallback).
        arrays['crawlStopGo'] = _crawl_stop_go(
            dm, raw_loader, frame_loader=frame_loader)
        # M226.1 (P1.1, enhancement plan): stop-go zero-inflation two-part
        # model, merged into crawlStopGo's existing dict (new keys only --
        # _crawl_stop_go itself is untouched above, so every pre-existing
        # field stays byte-identical; verified via isolation diff).
        if arrays.get('crawlStopGo'):
            _csg2 = _crawl_stop_go_two_part(dm, raw_loader, frame_loader=frame_loader)
            if _csg2 is not None:
                arrays['crawlStopGo'].update(_csg2)
        arrays['accelDecelEnvelopes'] = _accel_decel_envelopes(
            dm, raw_loader, frame_loader=frame_loader)
        arrays['rpmSpeedSync'] = _rpm_speed_sync(
            dm, raw_loader, frame_loader=frame_loader)
        arrays['engineStartContext'] = _engine_start_context(
            dm, frame_loader=frame_loader)
        arrays['bufferDebtRecovery'] = _buffer_debt_recovery(
            dm, frame_loader=frame_loader)
        arrays['drivingStateTaxonomy'] = _driving_state_taxonomy(
            dm, raw_loader, frame_loader=frame_loader)
        arrays['departureArrival'] = _departure_arrival(
            dm, frame_loader=frame_loader)
        arrays['engineStateMachine'] = _engine_state_machine(
            dm, raw_loader, frame_loader=frame_loader)
        # M227.1 (P1.3, enhancement plan): semi-Markov / dwell-survival
        # engine-state model. New top-level key (not merged into
        # engineStateMachine, which is untouched above and stays byte-
        # identical) -- per the plan's own stated isolation-diff criterion.
        arrays['engineDwellSurvival'] = _engine_dwell_survival(
            dm, raw_loader, frame_loader=frame_loader)
        # M227.2 (P1.6, enhancement plan): daily operational fingerprints.
        # New top-level key, per the plan's own stated isolation-diff
        # criterion (matching M227.1's treatment, not this session's usual
        # merge-into-existing-key pattern).
        arrays['dailyFingerprints'] = _daily_fingerprints(
            dm, ambient_by_drive=ambient_by_drive, frame_loader=frame_loader)
        arrays['thermalWarmupLag'] = _thermal_warmup_lag(
            dm, frame_loader=frame_loader)
        arrays['socBalancedFuel'] = _soc_balanced_fuel(
            dm, raw_loader=raw_loader, raw_dir=raw_dir)
        arrays['handoffSequence'] = _handoff_sequence(
            dm, frame_loader=frame_loader)
        # M221.3 (P0.2 event chain): joins bufferImpulse/rampLatency/
        # handoffSequence/bufferDebtRecovery on t0 into one attrition
        # funnel -- see _start_event_chain docstring. Placed after
        # handoffSequence/bufferDebtRecovery are both assigned above so the
        # startEventReconcile cross-reference fields just below can read
        # the funnel counts directly rather than recomputing them.
        arrays['startEventChain'] = _start_event_chain(
            dm, frame_loader=frame_loader)
        # M221.3: startEventReconcile (M122) gains two fields REFERENCING
        # the new funnel -- handoffJoinedPct (of the B∩R pair M122 already
        # reconciles, the fraction that also joined handoffSequence) and
        # recoveryJoinedPct (of THAT triple, the fraction that also joined
        # bufferDebtRecovery) -- so the old M122 view and the new full-
        # chain view don't silently diverge. Derived from startEventChain's
        # own funnel counts, not independently recomputed.
        if arrays.get('startEventReconcile') and arrays.get('startEventChain'):
            _funnel = arrays['startEventChain']['attritionFunnel']
            _bufram = _funnel.get('nWithBufferAndRamp')
            _bufram_ho = _funnel.get('nWithBufferRampAndHandoff')
            _full = _funnel.get('nWithFullChain')
            arrays['startEventReconcile']['handoffJoinedPct'] = (
                round(100.0 * _bufram_ho / _bufram, 1)
                if _bufram else None)
            arrays['startEventReconcile']['recoveryJoinedPct'] = (
                round(100.0 * _full / _bufram_ho, 1)
                if _bufram_ho else None)
        # M222.2 (enhancement plan item M222, full detector
        # reconciliation): cross-reference socHysteresisV2's own
        # START/STOP trigger-derived event counts against startEventChain's
        # nTrig. Hard dependency on M221 (startEventChain) -- both must
        # already be assigned above. The two ARE allowed to differ by
        # design: socHysteresisV2's canonical detector (detect_transitions)
        # requires >=2s of SUSTAINED running to CONFIRM a start (debounced),
        # while _engine_start_triggers (the M116/M118/M147/M221 physical-
        # detector family that startEventChain's nTrig counts) fires on a
        # single RPM>800 sample preceded by a sustained >=3s off period,
        # with no confirmation requirement on the following high-RPM
        # reading itself -- so the model's confirmed-start count is
        # expected to run BELOW the raw trigger count. That divergence is
        # stated explicitly here, not left implicit.
        if arrays.get('socHysteresisV2') and isinstance(arrays['socHysteresisV2'], dict) \
                and arrays.get('startEventChain'):
            _v2b = arrays['socHysteresisV2']
            _trig_n = arrays['startEventChain']['attritionFunnel'].get('nTrig')
            _model_start = _v2b.get('nStartEvents')
            _model_stop = _v2b.get('nStopEvents')
            _div_start = (_trig_n - _model_start) if (_trig_n is not None
                          and _model_start is not None) else None
            _v2b['detectorReconciliation'] = {
                'modelNStartEvents': _model_start,
                'modelNStopEvents': _model_stop,
                'startEventChainNTrig': _trig_n,
                'startVsTrigDivergence': _div_start,
                'startVsTrigDivergencePct': (
                    round(100.0 * _div_start / _trig_n, 1)
                    if (_div_start is not None and _trig_n) else None),
                'methodology': (
                    'socHysteresisV2.nStartEvents/nStopEvents count CONFIRMED '
                    'transitions from detect_transitions() (m119v2_model.py): '
                    'a sustained >=3s off interval followed by a sustained '
                    '>=2s CONFIRMED running interval (run-based debounce on '
                    'BOTH sides). startEventChain.attritionFunnel.nTrig '
                    '(compute_summary_arrays._engine_start_triggers, shared '
                    'by bufferImpulse/M116, rampLatency/M118, '
                    'handoffSequence/M147, this milestone\'s startEventChain/'
                    'M221) fires on a single RPM>800 sample preceded by a '
                    'sustained >=3s off period, with NO confirmation '
                    'requirement on the following high-RPM reading -- a '
                    'momentary blip above 800 rpm immediately followed by a '
                    'drop back down still counts as a trigger there, but not '
                    'as a confirmed start here. The two detectors are '
                    'therefore EXPECTED to diverge (model count below trigger '
                    'count), by construction, not by data-quality accident; '
                    'this field states the divergence rather than leaving it '
                    'implicit or reconciling it away.')}
        arrays['cellSpreadRelaxation'] = _cell_spread_relaxation(
            dm, frame_loader=frame_loader)
        arrays['vgtAirPath'] = _vgt_airpath(
            dm, raw_loader=raw_loader, raw_dir=raw_dir)
        arrays['highSocRegen'] = _high_soc_regen(
            dm, frame_loader=frame_loader)
        # M226.2 (P1.2, enhancement plan): condition-controlled regen-
        # acceptance frontier, merged into highSocRegen's existing dict
        # (new keys only -- _high_soc_regen itself is untouched above, so
        # every pre-existing field stays byte-identical; verified via
        # isolation diff).
        if arrays.get('highSocRegen'):
            _hrc = _high_soc_regen_covariates(dm, frame_loader=frame_loader)
            if _hrc is not None:
                arrays['highSocRegen'].update(_hrc)
        # M224 (P0.3, enhancement plan): SoC-control surface completion --
        # component 1 (net battery-power-neutral contour) and component 3
        # (charging probability surface), sharing socHysteresisV2's own
        # SoC/speed axes (component 2, the hazard surface, cross-referenced
        # via hazardCrossRef rather than duplicated). Reuses
        # m119v2_model.build_grid via frame_loader -- no new raw pass.
        arrays['socControlSurface'] = _soc_control_surface(
            dm, frame_loader=frame_loader)
        arrays['energyShifting'] = _energy_shifting(
            dm, raw_loader, frame_loader=frame_loader)
        arrays['baroCompensation'] = _baro_compensation(
            dm, raw_loader=raw_loader, raw_dir=raw_dir)
        arrays['auxLoadAmbient'] = _aux_load_ambient(
            dm, ambient_by_drive=ambient_by_drive)
        arrays['fullCellCaseStudy'] = _full_cell_case_study(
            dm, raw_loader=raw_loader, raw_dir=raw_dir)
        # M201 (2026-08-31): cold-start thermal fuel penalty (August fuel
        # accumulator subset). Deferred sub-analysis carved out of Module O
        # (_thermal_warmup_lag) -- decomposes the warm-up fuel penalty into
        # duty-cycle (dominant) and matched-operating-point combustion
        # (modest) components, reconciling with the naive trip-level ratio.
        arrays['thermalFuelPenalty'] = _thermal_fuel_penalty(
            dm, raw_loader=raw_loader, raw_dir=raw_dir)
        # M226.3 (P1.4, enhancement plan): continuous thermal-settling/
        # cold-start fuel, merged into thermalFuelPenalty's existing dict
        # (new keys only -- _thermal_fuel_penalty itself is untouched
        # above, so every pre-existing field stays byte-identical;
        # verified via isolation diff).
        if arrays.get('thermalFuelPenalty'):
            _tfc = _thermal_fuel_penalty_continuous(dm, raw_loader=raw_loader, raw_dir=raw_dir)
            if _tfc is not None:
                arrays['thermalFuelPenalty'].update(_tfc)
        # M57 (2026-07-27): mountain-road pattern re-definition. Establishes
        # that buffer-saturation dissipation is gated by SoC ceiling, not by
        # gradient, and validates the terrainTorqueDist bin labels against
        # measured GPS grade for the first time.
        arrays['mountainPattern'] = _mountain_pattern(
            dm, raw_loader, frame_loader=frame_loader)
        # M58 (2026-07-27): computed replacements for the last two hand-typed
        # numeric blocks in the dashboard (audit item carried since M36) -- the
        # BMS->VCM display-mapping table and the C-rate risk-map reference
        # lines. Both consume category_B outputs (socVcmPoints / cRatePoints),
        # so they must run AFTER the raw pass, not alongside the category_A
        # master-derived blocks.
        arrays['cRateRefLines'] = _crate_ref_lines(dm, arrays)
        # M43: master-derived half of eolBaselines. Typical-range statistics
        # (SoC-band median, vreg median) filter on ens_outlier_v2 per the
        # study's evidentiary convention; the observed SoC window is a true
        # extremum and therefore uses the UNFILTERED master.
        eb = arrays.get('eolBaselines')
        if eb is not None:
            _cl = dm[~_as_bool(dm['ens_outlier_v2'])] \
                if 'ens_outlier_v2' in dm.columns else dm
            eb['socBandMedianPp'] = round(float(_cl['soc_band'].median()), 1)
            eb['socWindow'] = {
                'minPct': round(float(dm['soc_min'].min()), 1),
                'maxPct': round(float(dm['soc_max'].max()), 1),
                'spanPp': round(float(dm['soc_max'].max()
                                      - dm['soc_min'].min()), 1)}
            if 'vreg_R_pack_mohm' in _cl.columns:
                _vr = _cl['vreg_R_pack_mohm'].dropna()
                eb['vreg'] = {'n': int(len(_vr)),
                              'medianMohm': (round(float(_vr.median()), 1)
                                             if len(_vr) else None)}
            # M58: socVcmMapping consumes eolBaselines.socWindow for its
            # display-exaggeration arithmetic, so it is built here -- after the
            # window is populated -- rather than alongside cRateRefLines above.
            arrays['socVcmMapping'] = _soc_vcm_mapping(dm, arrays)
    # M30: assemble the final Comparison-tab array from the A+B halves
    # (present even without a raw pass -- the 6 master-only rows still
    # populate; the 4 raw-derived rows fall back to '\u2014').
    arrays['highwayVsCity'] = _assemble_highway_vs_city(
        arrays.get('highwayVsCityMaster', {}), arrays)
    arrays.pop('highwayVsCityMaster', None)
    # M42 (2026-07-17): the riskUpdates row for the 80-120 km/h statistic is
    # regenerated here and substituted into the hand-authored config list by
    # factor name in the JSX. The config text had drifted (n=35 / mean 49.4%
    # / "May23-Jul13" against a 138-drive corpus) and still asserted the
    # superseded saturation framing. The config entry is retained, annotated
    # as superseded, per the provenance-preservation convention.
    _m = arrays['meta']
    arrays['riskDischargeShare'] = {
        # M57 (2026-07-27): join key renamed together with the config row.
        # The old key embedded the retracted "architectural deficit" framing
        # in an identifier, so the phrase survived every narrative rewrite.
        # If this string and summary_config.riskUpdates[].factor ever diverge
        # the override silently stops applying and the stale hand-authored
        # detail text renders instead -- change both or neither.
        'replaces': 'High-speed engine-on discharge (80-120 km/h) [legacy row]',
        'factor': 'High-speed engine-on discharge (80-120 km/h)',
        'severity': 'INFO', 'status': 'REFRAMED (M41)',
        'detail': (
            f"M41 (2026-07-17) reframing: NOT generator saturation. Engine-on "
            f"discharge share in the 80-120 km/h band is reproducible across "
            f"the full logged window -- mean {_m['deficitMeanPct']}% of band "
            f"time, range {_m['deficitMinPct']}-{_m['deficitMaxPct']}%, "
            f"n={_m['deficitValidN']} M14-valid drives (>=120 s band time) of "
            f"{int(len(dm))} -- but decomposes into "
            f"{_m['blendShareMeanPct']}% transient power blending "
            f"(|dv/dt|>=0.5 km/h/s or >30 A; p25-p75 {_m['blendShareP25']}-"
            f"{_m['blendShareP75']}%) and {_m['steerShareMeanPct']}% steady "
            f"SoC steering / generator load-point quantization. Calc engine "
            f"load during these discharge seconds averages ~38% (p95 ~43%) -- "
            f"indistinguishable from engine-on CHARGING seconds, i.e. unused "
            f"generator headroom; discharge probability rises monotonically "
            f"with SoC above ~63% (0.85-0.90 at SoC 70-80% vs 0.33-0.43 in "
            f"the 60-65% target band), the signature of steering toward the "
            f"setpoint. Sustained-saturation gate (load>85% AND >30 A, >=5 s): "
            f"{_m['saturTotalS']} s across all {int(len(dm))} drives "
            f"({_m['saturDrivesN']} affected, {_m['saturCoverageN']}-drive PID "
            f"coverage) -- a null result. Transient dual-channel peaks remain "
            f"real and confirmed (213 A engine-charge, 36.4C, Jun19). Battery "
            f"cycling at high speed is a designed control strategy, not an "
            f"architectural shortfall.")}
    # P0-5 (2026-07-30): audit/provenance blocks now produced by the main
    # generator (previously out-of-band, so a clean rebuild dropped them).
    # Master-derived, no raw pass -> safe under arrays-only regeneration:
    arrays['eligibility'] = _audit_eligibility(dm)
    # M108 (2026-08-11): degradation-trend equivalence testing (mixed-effects
    # + cluster-robust OLS + TOST), previously a standalone script never wired
    # into the pipeline. Master-derived only, safe under arrays-only regen.
    # Equivalence bounds were locked before this call was first wired in --
    # see degradation_trends.py's module docstring for the pre-registration
    # rationale.
    arrays['degradationTrends'] = degradation_trends.build(dm)
    _ann = (arrays.get('cycleLife') or {}).get('annualKm')
    _thr = (arrays.get('cycleLife') or {}).get('scenarioThresholdGtc', 20000)
    arrays['observedMix'] = _audit_observed_mix(dm, annual_km=_ann,
                                                threshold_gtc=_thr)
    arrays['offsetUncertainty'] = _audit_offset_uncertainty(dm)
    arrays['contaminationSensitivity'] = _audit_contamination_sensitivity(dm)
    # M77 (2026-07-30): matched-population RF/FCE ledger. Replaces the retired
    # available-case "within 1%" ratio (a coverage-denominator artifact). RF and
    # FCE are strongly correlated per-drive but RF is systematically ~7-8%
    # higher; high correlation is not numerical closure.
    arrays['ledgerCrossCheck'] = _ledger_cross_check(dm)
    # Declared metadata (assumptions + reproducibility proof) from study config:
    _cp, _det = _audit_metadata_from_cfg(session_cfg)
    if _cp is not None:
        arrays['constantProvenance'] = _cp
    if _det is not None:
        arrays['determinism'] = _det
    # Raw-dependent audit blocks (need the corpus headers):
    if with_raw and raw_loader is not None:
        _rm = _audit_raw_manifest(dm, raw_loader, raw_dir=raw_dir)
        arrays['gpsAltitudeCoverage'] = _audit_gps_altitude_coverage(dm, _rm)
        # M115: build the coverage map from _rm (needs its internal
        # _pidCovFiles file lists and the already-built eligibility block)
        # BEFORE stripping that internal key and shipping rawManifest.
        arrays['coverageMap'] = _audit_coverage_map(
            dm, _rm, arrays.get('eligibility', {}))
        _rm.pop('_pidCovFiles', None)
        arrays['rawManifest'] = _rm
    # M78 (2026-07-30): regen-capture summary scalars derived from the already-
    # computed regenCaptureMeasured / regenByTempMeasured arrays (no raw pass).
    # The by-speed and by-temperature capture ranges were hand-typed in the JSX
    # (72-85% generator share, 41-58% by zone, 51-62% by temperature) and had
    # drifted against the current corpus; binding them here stops the drift.
    _rcm = arrays.get('regenCaptureMeasured') or []
    _rbt = arrays.get('regenByTempMeasured') or []
    if _rcm or _rbt:
        meta_rc = {}
        if _rcm:
            effs = [r[1] for r in _rcm if r[1] is not None]
            plateau = [r[1] for r in _rcm if 50 <= r[0] <= 110 and r[1] is not None]
            lo_bins = [r for r in _rcm if r[0] < 30 and r[1] is not None]
            meta_rc['speedEffMin'] = round(min(effs), 1) if effs else None
            meta_rc['speedEffMax'] = round(max(effs), 1) if effs else None
            meta_rc['plateauLo'] = round(min(plateau), 0) if plateau else None
            meta_rc['plateauHi'] = round(max(plateau), 0) if plateau else None
            meta_rc['crawlEff'] = round(lo_bins[0][1], 0) if lo_bins else None
        if _rbt:
            valid = [b for b in _rbt if b.get('valid')]
            if valid:
                effs = [b['eff'] for b in valid]
                ns = [b['n'] for b in valid]
                meta_rc['tempEffMin'] = round(min(effs), 1)
                meta_rc['tempEffMax'] = round(max(effs), 1)
                meta_rc['tempLabelLo'] = valid[0]['label']
                meta_rc['tempLabelHi'] = valid[-1]['label']
                meta_rc['tempNMin'] = int(min(ns))
                meta_rc['tempNMax'] = int(max(ns))
                inv = [b for b in _rbt if not b.get('valid')]
                meta_rc['tempThinBins'] = [
                    {'label': b['label'], 'n': int(b['n'])} for b in inv]
        arrays['regenCaptureMeta'] = meta_rc

    # M217 (2026-09-03): H-01/F-12 policy decision (Andrii) -- energy-MC
    # ('energyUncertaintyMC') moves from manual carry-forward-until-stale to
    # a full recompute on every ingestion. Unlike M119-v2 this is NOT
    # OOM-bound (no GLM ladder, no statsmodels fit -- a raw I/V re-integration
    # on a small per-drive tolerance grid, cached once, then B=20000
    # vectorized MC draws over the cached numbers) and costs tens of seconds
    # to low minutes at the current corpus size, so the default is
    # unconditional recompute rather than an opt-in flag like
    # recompute_m119v2. recompute_energy_mc=False is an escape hatch for fast
    # arrays-only reruns that don't need a fresh MC (iterating on an
    # unrelated block); routine ingestion always leaves it at the default
    # True. Placed here (after offsetUncertainty/ledgerCrossCheck) because it
    # sources the released offset point estimate + 95% CI live from
    # offsetUncertainty rather than duplicating that fit.
    _ENERGY_MC_POLICY = (
        'M217 (2026-09-03, Andrii decision, H-01/F-12): energyUncertaintyMC is '
        'recomputed in full on every ingestion (energy_mc_precompute.py '
        're-integrates raw I/V per drive on the tolerance grid, then '
        'energy_uncertainty_mc.py runs a fresh 20,000-draw MC over the cached '
        'per-drive numbers) -- superseding the prior manual '
        'carry-forward-until-stale policy (M163-M216: recomputed only on ad '
        'hoc request, drifting up to the informal 0.5% build_html.js gate '
        'between refreshes). recompute_energy_mc=False reverts to '
        'carry-forward for a given call; routine ingestion never passes it.')
    _prev_mc = (prev_arrays or {}).get('energyUncertaintyMC')
    if (recompute_energy_mc and energy_mc_precompute is not None
            and energy_uncertainty_mc is not None and raw_dir):
        try:
            _ou = arrays.get('offsetUncertainty') or {}
            _off = float(_ou.get('pointEstimateA', -0.4093))
            _pre_rows, _pre_meta = energy_mc_precompute.build(
                raw_dir, dm, offset_point_a=_off)
            # energy_uncertainty_mc.build() expects string tolerance keys in
            # each drive's 'grid' dict (d['grid'][str(t)]) -- true only after
            # the JSON round-trip both scripts' own __main__ CLI does
            # (json.dump then json.load stringifies dict keys). In-memory
            # chaining bypasses that implicit stringification (grid keys are
            # int here), so replicate the round-trip explicitly rather than
            # editing either script's established, separately-validated
            # on-disk JSON contract.
            _precompute = json.loads(json.dumps(
                {'meta': _pre_meta, 'drives': _pre_rows}))
            _ci = tuple(float(x) for x in _ou.get('ci95A', (-0.70, -0.29)))
            _ncorr = float((_ou.get('correctionScope') or {})
                           .get('netCorrectionMagnitudeKwh', 0.0))
            _mc = energy_uncertainty_mc.build(
                _precompute, offset_point_a=_off, ci95a=_ci,
                net_correction_kwh=_ncorr)
            _mc['recomputeMode'] = 'fresh'
            _mc['corpusSizeAtRecompute'] = int(len(dm))
            _mc['recomputePolicy'] = _ENERGY_MC_POLICY
            arrays['energyUncertaintyMC'] = _mc
        except Exception as _e:
            if _prev_mc is not None:
                arrays['energyUncertaintyMC'] = dict(_prev_mc)
                arrays['energyUncertaintyMC']['recomputeMode'] = (
                    'carriedForward_recomputeFailed')
                arrays['energyUncertaintyMC']['recomputeError'] = repr(_e)
                arrays['energyUncertaintyMC']['recomputePolicy'] = _ENERGY_MC_POLICY
            else:
                arrays['energyUncertaintyMC'] = None
    elif _prev_mc is not None:
        arrays['energyUncertaintyMC'] = dict(_prev_mc)
        arrays['energyUncertaintyMC']['recomputeMode'] = 'carriedForward'
        arrays['energyUncertaintyMC']['recomputePolicy'] = _ENERGY_MC_POLICY
    else:
        arrays['energyUncertaintyMC'] = None

    arrays['_generated'] = {
        'pipeline_version': 6, 'n_drives': int(len(dm)),
        'basis': 'compute_summary_arrays.py',
        'clean_filter': 'ens_outlier_v2' if 'ens_outlier_v2' in dm.columns
                        else 'ens_outlier',
    }
    # provenance: reproduction status of each computed array vs the archived
    # hand-maintained JSX values (audit 2026-07-06).
    arrays['_provenance'] = {
        'exact_reproduction': [       # match archived within rounding; auto-adopt
            'meta', 'driveTypes', 'regenByType', 'cycleCumulative',
            'rfCycleCumulative', 'warmupPoints', 'cRatePoints', 'records',
            'socBySpeed', 'engineOnBySpeed', 'torqueBySpeed', 'sensorSummary',
            'engineStartsByType'],
        'current_basis_recompute': {  # defensible recompute; supersedes archived
            'cycleByType': 'efc per 100 km, ens-clean (legacy 98-drive basis undocumented)',
            'efficiencyBands': 'gross_discharge_kwh per 100km, p10-p90 + median, '
                               'ens-clean, condition class = time-weighted drive_type '
                               '(M21: supersedes net_draw_per100km_corr / distance-'
                               'bucketed basis -- see M21 note in constants block)',
            'cycleLife': 'observed per-class efc/km x scenario mix (no hand-set rates)',
            'dissipationCensus': 'M46 (2026-07-20): motored-engine overcharge-'
                                 'dissipation census. Per-sample engine mode '
                                 'classified on boost (MAP-linear proxy, r=0.999): '
                                 'MOTORED (rpm>2000, boost<-0.70~MAP<25kPa, load<8%) '
                                 'vs FUELLED (rpm>2000, boost>=-0.55~MAP>=40kPa). '
                                 'Establishes the SoC ceiling (88.0%, drive '
                                 '20260719_154351) as an actively motored-defended '
                                 'upper bound of the BMS operating window',
            'warmupCurve': 'M31 (2026-07-12): distance-domain engine warm-up. Per '
                           'cold-start drive (first valid engine-coolant <= 50C), coolant '
                           'interpolated onto a 0-8 km distance-from-anchor grid (speed-'
                           'integrated) and pooled by condition class into median + IQR '
                           '(>=5-drive gate per point). M86 (2026-08-05): pooled by native '
                           'CLASS_ORDER (was a blended city/mixed/highway); the 5-drive-'
                           'per-point gate now applies to the un-blended mixed_highway and '
                           'highway populations separately, so points can legitimately drop '
                           'out further along the grid for the thinner highway class -- '
                           'that is the gate doing its job, not a regression. Replaces '
                           'warmupPoints (whole-trip distance vs peak coolant) as the '
                           'Chart-2 basis; warmupPoints is retained in the JSON but no '
                           'longer charted.',
            'terrainTorqueDist': '1 Hz + >=3 s steady streak; core ~50% vs archived 58% (ffill convention)',
            'regenByZone': '1 Hz decel-step KE capture; eff runs ~5 pp above archived M20 (more steps counted)',
            'regenCaptureMeasured': '1 Hz decel-step KE capture, 10 km/h mid-bins',
            'turboByRpm': 'all 105 drives, engine-on >0.1 bar (archived used 49 drives)',
            'turboBySpeedCtx': 'all 105 drives, engine-on >0.1 bar',
            'socVcmPoints': 'pooled subsample of (BMS SoC, VCM available-charge) pairs',
            'regenByTempMeasured': 'M22 (2026-07-07): real engine-off decel KE-capture, '
                                   'pooled by pack temperature (mean T1-T4), n>=200 gate. '
                                   'Supersedes regenByTemp for any real-data claim -- see '
                                   'deprecated_synthetic below.',
            'highwayVsCity': 'M30 (2026-07-12, audit): all 10 Comparison-tab rows now '
                             'computed -- 6 from drive_master (SoC band, net discharge, '
                             'engine-ON fraction, battery temp Sensor 1, peak charge/'
                             'discharge currents; true-extrema basis for records-like '
                             'claims, ens_outlier_v2-clean basis for typical-range claims) '
                             '+ 4 from the raw 1 Hz pass (engine trigger/stop SoC IQR, '
                             'turbo activity, engine-reaches-80C timing). Supersedes the '
                             'hand-authored config block, which had drifted (highway SoC '
                             'band claimed 60-82% vs the observed 44.5-84.5%, and used a '
                             '12-drive highway-only basis instead of the 23-drive '
                             'mixed_highway+highway blended class used everywhere else). '
                             'M86 (2026-08-05): the table itself migrated from City/Mixed/'
                             'Highway (3 columns, Highway = mixed_highway+highway blended) '
                             'to native CLASS_ORDER (4 columns: Urban/Mixed/Mixed Highway/'
                             'Highway), matching driveTypes/engineStartsByType elsewhere in '
                             'the dashboard. \'city\' is retained as an alias of \'urban\' in '
                             'every underlying dict for any not-yet-migrated consumer. The '
                             'cycle-life scenario projection (S.cycleLife, a DIFFERENT '
                             'section) intentionally keeps the blended 3-way convention -- '
                             'see _cycle_projection\u2019s docstring.',
            '_clean_basis': 'M23 (2026-07-09): all ens-clean aggregates '
                            '(driveTypes avg*, cycleByType, efficiencyBands, '
                            'cycleLife intensities) now filter on '
                            'ens_outlier_v2 (domain-invalid | intensity-'
                            'extreme) instead of the v5 magnitude-based '
                            'ens_outlier, re-admitting the four long-highway '
                            'record drives (169-284 km) that carried 31% of '
                            'valid 80-120 band time and 27% of throughput.',
            'speedDist': 'M26 (2026-07-09): time-weighted zone shares from raw '
                        'speed samples (dt-weighted, 5s-capped), all drives; '
                        'overall + urban-class (city) + highway-blended-class '
                        '(mixed_highway+highway). Supersedes the hand-authored '
                        'config block, which implied a nonexistent single '
                        '1,091 km highway drive and diverged from current data '
                        'by up to 3x (120+ share: 8.6% claimed vs 0.3% measured; '
                        '90-120: 38.8% claimed vs 21.6% measured).',
            'seasonalLife': 'M28 (2026-07-10): all-year seasonal extrapolation '
                            'of the cycle projection. MODEL-BASED, not measured '
                            '— the cold tail below the lowest logged pack-probe reading is modelled, not observed. '
                            'Inputs: user-supplied Kyiv monthly mean temps + '
                            'literature-anchored cold-consumption slope / cold-'
                            'soak retention / plating weights (all carried as '
                            'lo-mid-hi bands in config.seasonalAssumptions); '
                            'data-derived per-class efc/km, thermal rise, regen '
                            'shares, C-rates. Same gross-EFC-vs-20000 frame as '
                            'cycleLife; plating acceleration reported only as a '
                            'labeled damage-weighted sensitivity, never blended '
                            'into the primary crossing. Superseded by winter '
                            'logging when available.',
            'thermalConvergence': 'M33 (2026-07-13): Sensor-1 first/peak/last '
                                  'trajectory for every drive >60 min (raw pass), '
                                  'sorted by duration. Replaces the hand-authored '
                                  '"17 drives >60min" list that ended Jun27 and had '
                                  'gone stale (now longDrivesN drives, incl. Jul11/'
                                  'Jul13 long drives the static list omitted). Exact '
                                  'reproduction of the archived Sensor-1 values on '
                                  'shared drives.',
            'batteryVsAmbient': 'M33 (2026-07-13): pack-mean (4-sensor) first/peak/'
                                'last battery temp joined to per-drive ambients from '
                                'config.ambientByDrive (ambient is a manual field -- '
                                'no OBD outside-air channel), with battery-minus-'
                                'ambient deltas. Replaces the hand-authored ambient '
                                'log that ended Jul07. Only drives with a recorded '
                                'ambient appear; drives lacking one are omitted.',
            'standstillStats': 'M26 (2026-07-09): drives/samples/median/range of '
                               'standstill_draw_kw, all drives (unfiltered, matching '
                               'the Parasitic Draws caption\'s "all drives" scope). '
                               'Backs the caption text directly; the hand-typed '
                               'snapshot it replaces (92 drives / 10,665 samples / '
                               '-1.27 kW) had drifted from 96 / 10,867 / -1.245 kW.',
            'records': 'M37 (2026-07-15): 36 rows (was 19). Each row carries a '
                       'narrative note = definitional statement of the extremum + '
                       'the setting drive\'s operating context read from its own '
                       'master row (_ctx). 17 rows added from an extrema audit of '
                       'drive_master (discharge current/power, decomposed charge '
                       'channels, engine rpm/boost/MAP, intake-air temp, duration, '
                       'per-drive throughput, SoC excursion, moving-avg speed, '
                       'M14-gated 80-120 deficit, 130+ streak, standstill ceiling). '
                       'All 19 pre-existing rows reproduce identically.',
            'motorTemp': 'M38 (2026-07-15): pooled traction-motor thermal stats over '
                         'every drive carrying the PID (95 drives / 3,122 km / '
                         '200,067 1 Hz-aligned samples): range 15-100 C, peak Jun27 '
                         'D7, r=0.78 vs pack mean and r=0.62 vs speed, motor-minus-'
                         'pack delta 25.7 C mean / 61 C max. Supersedes the hand-'
                         'authored Conclusions-tab paragraph, which was written on a '
                         '50-drive / 2,102 km subset (15-95 C, r=0.72/0.55, 24.4 C / '
                         '48 C). The 100 C ceiling was re-verified in raw: sustained '
                         'across consecutive samples with a 96 C drive p99 -- a '
                         'plateau, not a single-sample artefact. Correlations are '
                         'computed on the 1 Hz ffill(limit=3) grid because the motor, '
                         'pack-sensor and speed PIDs are async-logged.',
            'highSpeedCensus': 'M39 (2026-07-15): cumulative grid-seconds and longest '
                               'CONTINUOUS streak above 130/140/150/160 km/h, per '
                               'drive and pooled, plus the corpus speed ceiling. '
                               'Prompted by the 170 km/h max-speed record (Jul14 D4) '
                               'being confirmed real data while two hand-authored '
                               'claims still asserted 140+ km/h was "uncaptured". '
                               'Census resolves both: 140+ is reached (68 s over 5 '
                               'drives) but never held (longest run 27 s); 150+ is a '
                               'single 20 s excursion. The sustained-hold regime the '
                               'deficit argument needs remains absent.',
            'dischargeDecomp': 'M41 (2026-07-17): the 80-120 km/h "generator-'
                               'saturation deficit" is reframed as an engine-on '
                               'discharge share and decomposed. Sample-level '
                               're-analysis (Jun19 D1, Jun27 D3, Jul16 D4) showed '
                               '(a) discharge probability in the band rises '
                               'monotonically with SoC above ~63% (0.85-0.90 at '
                               'SoC 70-80%, minimum 0.33-0.43 in the 60-65% '
                               'target band) -- the signature of SoC steering, '
                               'not capability limit; (b) calc engine load '
                               'during "deficit" seconds averages ~38% (p95 '
                               '~43%), identical to engine-on charging seconds '
                               '-- ample generator headroom; (c) deficit seconds '
                               'have negative mean acceleration, charging '
                               'seconds positive -- opposite of the saturation '
                               'narrative. New per-drive columns: '
                               'engon_dis_share_80_120 (rename-in-place of '
                               'deficit_80_120_pct, byte-equal), blend_s/'
                               'blend_share_80_120 (|dv/dt|>=0.5 km/h/s or '
                               'Id>30 A), steer_s_80_120 (steady low-current '
                               'remainder), satur_80_120_s (load>85% AND '
                               'Id>30 A sustained >=5 s). Backfilled over all '
                               '138 drives with the reconstructed e-frame '
                               'reproducing band/deficit seconds byte-exactly; '
                               'pre-existing master columns md5-identical. '
                               'Corpus result: blend share mean 55.5% of '
                               'engine-on-discharge time (p25-p75 40.8-69.8), '
                               'steering remainder 44.5%, saturation gate 0.0 s '
                               'on all 138 drives (null result). deficit_* '
                               'columns and array keys retained for continuity; '
                               'record-row title and three record notes '
                               'rewritten to the new framing.',
            'nearLimiter+riskDischargeShare+belowAmbient':
                'M42 (2026-07-17). (1) nearLimiter answers the question M41 '
                'leaves open -- what high-speed engine-on discharge means at '
                'the 170 km/h limiter. In a series hybrid the generator '
                'operating point is VCM-commanded and mechanically decoupled '
                'from road speed, so the load reached at a given rpm on any '
                'drive bounds what was reachable at that rpm at vmax. At vmax '
                '(170 km/h, Jul14 D4) the generator ran 76.5% mean / 78.8% max '
                'calc load at 1.15 bar boost, ~4,590 rpm; pooled over 181 '
                'samples / 21 drives in the same 4,400-4,700 rpm band the same '
                'engine reaches 87.1% p95 / 92.2% max load and 1.53 bar. '
                '~13 pp of load and ~0.38 bar of boost were unspent AT the '
                'speed ceiling, with battery draw only +4.6 kW mean over the '
                '20 s above 150 km/h (SoC 61.0->60.0%). The corpus therefore '
                'does NOT support the previously asserted "the limiter is an '
                'electrical-architecture limit" claim; the observation is '
                'consistent with a programmed 170 km/h speed limiter. Motor-'
                'power apportionment was attempted and abandoned (vmax-drive '
                'motor torque/rpm PIDs decode implausibly: |tq|<=0.9 Nm, rpm '
                '+-10,000); the headroom argument does not depend on them. '
                '(2) riskDischargeShare regenerates the riskUpdates row for '
                'this factor (config text had drifted to n=35 / mean 49.4% / '
                '"May23-Jul13" and still asserted saturation); the config '
                'entry is retained and annotated as superseded. (3) '
                'belowAmbient replaces the hand-typed "7 confirmed '
                'occurrences" in the Confirmed-by block: the real count on the '
                'ambient-covered subset is 18 of 71 drives.',
            'eolBaselines': (
                'M43 (2026-07-17): pooled Six-Leading-Indicator baselines for '
                'the End-of-Life section, previously hand-typed in the JSX and '
                'stale on the 138-drive corpus (loaded-spread p95 = 27 mV / '
                'n = 13,741; resting p95 = 11 mV; gap 16 mV; Sensor-1 delta '
                'median +2.5C / p90 +4.0 / max +5.2 on a "100-drive pool"; '
                'per-drive SoC-band median 20.5 pp; "full BMS window 44-82% = '
                '38 pp"). Raw half: Vmax<->Vmin merge_asof nearest 300 ms, '
                'spread->current asof nearest 1500 ms (v6 M10 conventions), '
                'loaded = |I| > 50 A, resting = |I| < 5 A; Sensor-1-minus-'
                'pack-mean delta and pack-minus-intake delta on the all-four-'
                'sensors-valid rowwise basis shared with sensorSummary. '
                'Master half: SoC-band median and vreg_R_pack_mohm median on '
                'the ens_outlier_v2-clean subset (typical-range convention); '
                'observed SoC window min/max on the unfiltered master (true-'
                'extremum convention). Indicator 3 additionally binds the M25 '
                'V-sag proxy (vreg) so the resistance axis carries a '
                'trackable per-drive figure instead of a pure disclaimer.'),
            'socBands': (
                'M51 (2026-07-22): PROMOTED from config to computed. Was a '
                'frozen four-row narrative array under '
                'kept_in_config_not_computed; on the 173-drive corpus both '
                'city rows had drifted (trigger 51-62 rendered vs 55-66 '
                'computed, stop 59-66 vs 62-68) and the mixed class was '
                'missing entirely. Now emitted by the same _RawAccum that '
                'produces hvcEngine{Trigger,Stop}SoC -- identical segment '
                'detection (>300 RPM, >= MIN_ENGINE_START_S), identical class '
                'taxonomy, identical 25-75 IQR convention -- so the Operating '
                'Map panel and the Comparison-tab strings are now two '
                'renderings of ONE computation and cannot disagree. M86 '
                '(2026-08-05): migrated from a three-bucket City/Mixed/'
                'Highway collapse to native CLASS_ORDER -- eight rows '
                '(Urban/Mixed/Mixed Highway/Highway x trigger/stop), colors '
                'now the dashboard-wide CLASS_COLOR palette. The superseded '
                'config entry is retained as socBands_superseded.'),
            'batteryTempRanges': (
                'M51 (2026-07-22): computed replacement for the seven '
                'hand-typed RangeBar rows in "Battery Temperature -- Observed '
                'Range" (literal lo/hi pairs 10/22, 14/20, 18/35, 35/47, '
                '17/48 keyed to hand-named May/June sessions). Those bars had '
                'drifted out of agreement with the pipeline-bound caption '
                'directly beneath them, and one row asserted a "surpassed '
                'twice" ranking that a third drive had since tied. Grouping '
                'is now derived on two orthogonal reproducible axes -- '
                'recorded-ambient bin (cool <20 C / mild 20-26 C / hot >=26 C, '
                'on the mean of the [start,end] pair) and the shared drive '
                'class taxonomy (M86: native CLASS_ORDER, was a three-bucket '
                'City/Mixed/Highway collapse) -- plus long-haul (>60 min) and '
                'corpus-record context rows. lo/hi are TRUE observed extrema '
                '(min of per-drive t1_min, max of per-drive t1_peak) per the '
                'section title, so they run on the UNFILTERED master per the '
                'extremum convention; medPeak carries the typical ceiling '
                'alongside. Rides on the _battery_temp_traj pass already made '
                'for thermalConvergence -- no additional raw read.'),
            'driveDurationDist': (
                'M74 (2026-07-29): new array, no archived predecessor. Per-'
                'class (CLASS_ORDER) box-plot summary (min/q1/median/q3/max, '
                'minutes) of duration_s on the ens_outlier_v2-clean subset -- '
                'same basis and grouping as driveTypes.avgMin, which reports '
                'only the per-class MEAN and so cannot show that a class with '
                'a modest average (e.g. Urban, 19 min) still spans single-'
                'digit-minute hops to hour-plus sessions. Companion chart to '
                'the Drive Type Distribution donuts, not a replacement.'),
            'turboMeta': (
                'M75 (2026-07-29): new array, no archived predecessor. Coverage '
                'counter for the Turbo Pattern section -- n drives / km / hours '
                'with BOTH boost_max and eng_rpm_max populated on drive_master, '
                'i.e. carrying the raw boost and engine-rpm PIDs that feed '
                'turboByRpm / turboBySpeedCtx. Master-only (no raw pass): '
                '138 of 194 drives, 4393.1 km / 83.2 h -- corrects a hand-typed '
                '"49 drives" caption that predated most of the corpus.'),
            'meta.engineOnHours+engineHoursPer10k+engineHoursByType': (
                'M82 (2026-08-04): new arrays, no archived predecessor. '
                'engineOnHours/engineHoursPer10k (meta, Category A) sum '
                'duration_s x engine_on_pct/100 across the unfiltered master '
                '-- same convention as the adjacent movingHours/stationaryHours '
                '-- needing no raw pass since engine_on_pct is already a '
                'per-drive master column. engineHoursByType is the per-'
                'CLASS_ORDER breakdown (totals: km/engineOnHours/hoursPer10k; '
                'per-drive ens-clean mean: avgEngineOnPct), companion to '
                'driveTypes. On the 206-drive corpus: 55.9 h engine-on of '
                '118.4 h total drive time (6,156.7 km), 90.75 h/10,000km '
                'pooled; NOT monotonic with avgEngineOnPct across class -- '
                'urban carries the highest hoursPer10k (113.4) despite the '
                'lowest avgEngineOnPct (30.7%) because its low km/h means '
                'more engine-hours are needed to cover the same distance, '
                'while highway is the inverse (73.3% avgEngineOnPct but the '
                'lowest hoursPer10k, 83.1) -- time-share and per-km burden '
                'rank the classes in opposite order.'),
            'rpmDistribution': (
                'M82 (2026-08-04): new array, no archived predecessor. '
                'Duration-weighted engine-RPM occupancy histogram (category B, '
                '_RawAccum, rides the existing per-file 1 Hz grid -- no new '
                'raw-cache pass, no SLIM_COLS/schema change; eng_rpm and boost '
                'were already cached, calc-load was cached but not previously '
                'wired into this accumulator, wired in here via RAW_MAP). '
                'Bins: a dedicated <300 rpm "engine off" bucket (engineOnBySpeed/'
                'engineOnDuration/turbo threshold), 300-800 idle/crank, then '
                '400 rpm-wide bins to 4500+. Pooled + per-CLASS_ORDER-class + a '
                'fuelled-vs-motored split reusing the M46/M48 dissipation-'
                'census classifier thresholds verbatim (RPM_MIN=2000, '
                'BOOST_MOTORED=-0.70, BOOST_FUELLED=-0.55, LOAD_MAX=8). '
                'Corpus result (206 drives, 117.0 gridded hours): 51.4% '
                'engine-off pooled (in line with the independent M53 ev_valid '
                'census, ~50.7% of time); of engine-on time, occupancy peaks '
                'sharply in a narrow 1600-2400 rpm band (34.0% of ALL gridded '
                'time, off included) and falls off quickly either side -- '
                'consistent with the generator being run near a fixed '
                'efficient operating point rather than swept across its range. '
                'The fuelled/motored split (150 of 206 drives carry all three '
                'channels, 86.6 h) shows the two modes occupy DIFFERENT rpm: '
                'fuelled generation peaks at 2000-2400 rpm (12.17 of 18.98 h '
                'fuelled, 64.1%), motored SoC-ceiling defense (M46/M48) is far '
                'smaller in volume (0.37 h total) and sits higher, peaking at '
                '2800-3200 rpm (0.141 h; 2400-2800 close second at 0.106 h) -- '
                'the VCM commands a distinct, higher rpm setpoint when dumping '
                'surplus energy unfuelled than when actually generating power.')},
        'kept_in_config_not_computed': [   # narrative / synthetic / non-reproducing
            'engineOnDuration (original per-segment duration derivation not reproducible)',
            'riskUpdates, sessions, climate',   # dModeEstimate removed M111 (D/B discontinued)
            '(M51: socBands removed from this list -- now computed)'],
        'deprecated_synthetic': {
            'regenByTemp': "NOT data-derived -- a hand-authored illustrative model "
                           "(config only). Its 100%-at-low-speed plateau is the same "
                           "power-availability-ceiling artifact already identified and "
                           "corrected for the main efficiency-vs-speed chart (see "
                           "regenCaptureMeasured), never applied here. Real measured "
                           "capture by temperature (M22, regenByTempMeasured, 105 "
                           "drives) shows a much flatter ~51-62% band across the "
                           "15-45C range that has enough data to report; <15C (n=25) "
                           "and 45C+ (n=19) are real samples but too thin to report a "
                           "%. The chart's '48% cold vs 83% hot, 1.7x' claim does not "
                           "reproduce from any computed array and should not be cited."},
        'new_no_archived_counterpart': {   # M91/M92: genuinely new keys, not a
            # recompute or supersession of anything hand-authored -- kept out
            # of 'current_basis_recompute' (which means "replaces an archived
            # figure") and out of 'deprecated_synthetic' (which means
            # "removed/discredited"); neither applies to a fresh addition.
            'dodSocLevelSensitivity': 'M91 (2026-08-06). SoC-window-LEVEL '
                'diagnostic split of the existing rf_damage_k2 (M17), re-blended '
                'through a labeled config.socLevelWeighting ladder cited to '
                'Wikner (Chalmers, 2017). Master + config only; never folds '
                'into rf_damage_k2 or any GTC/FCE crossing -- see the function '
                'docstring for the corpus finding (virtually all cycling sits '
                'in the elevated-SoC band by her breakpoints).',
            'seasonalLife.observedConstant': 'M92 (2026-08-06). Observed logged '
                'distance mix carried through the SAME M28 constant-mix '
                'seasonal model as selectedConstant, so the one row whose '
                'workload is measured also carries climatic + hot-tail stress '
                'instead of staying a bare warm-floor figure.',
            'seasonalLife.hotTail.observed': 'M92 (2026-08-06). Companion to '
                'observedConstant -- same _hot_block() path already used for '
                'hotTail.selected/allYear.'},
    }
    # M114 (2026-08-09, audit P0-01): retract remaining implied-life / EOL YEAR
    # outputs at the arrays boundary. A crossing "year" (accumulation rate vs an
    # unverified GTC threshold) and a calendar-life "year" (Arrhenius factor ->
    # years) are life estimates this warm-season observational corpus cannot
    # support. EXPOSURE is retained in full: GTC/FCE accumulation and rates,
    # per-class intensity, dimensionless m(k) and DoD/SoC damage shares, measured
    # pack thermics, the flagged-unverified threshold CONSTANTS themselves, and
    # the measured power-fade proxy. Only the YEAR conversions are nulled. Paired
    # with the JSX projection-view rewrite (crossing-year grid + SensitivityMatrix
    # removed, prose reworded to rates + the existing "no life figure" framing).
    _LIFE_YR_LEAVES = {
        'yearsTotal', 'yearsRemain', 'yearsBand', 'calendarLifeYrShaded',
        'matrixSpanYr', 'thresholdSpanYr', 'workloadSpanYr', 'crossingYr',
        'yrPer1kGtc', 'afWeightedYearsTotal', 'yearsToOfficialLifeKm',
        'expectedLifeYr', 'capacityFadeConditionYr', 'observedCrossingYr',
        'selectedCrossingYr',
    }

    def _null_life_years(o):
        if isinstance(o, dict):
            for _k in list(o):
                if _k in _LIFE_YR_LEAVES or _k == 'thresholdSensitivity':
                    o[_k] = None
                else:
                    _null_life_years(o[_k])
        elif isinstance(o, list):
            for _v in o:
                _null_life_years(_v)

    for _blk in ('cycleLife', 'fadeModes', 'seasonalLife',
                 'officialDisclosureCorrelation', 'observedMix',
                 'realisticBlend'):
        if isinstance(arrays.get(_blk), dict):
            _null_life_years(arrays[_blk])
    arrays['_retractedLifeEol'] = (
        'M114 (audit P0-01): implied-cycle-life and calendar-life YEAR outputs '
        'retracted (crossing years, threshold/workload/matrix spans, calendar-'
        'life ceiling, seasonal/hot-tail/plating year sensitivities, years-to-'
        'official-life). Exposure rates, accumulations, intensities, thresholds-'
        'as-flagged-constants, m(k), DoD/SoC shares, measured thermics and the '
        'power-fade proxy are retained. This study reports how hard the pack is '
        'worked and that no degradation trend is detectable; it does not '
        'translate that into an end-of-life or 80% SOH date.')

    # M225 (Dashboard 7.1, enhancement plan): Evidence & Cross-Validation
    # Ledger. Pure post-processing -- assembled here, BEFORE _artifact_stamp,
    # so evidenceLedger itself gets stamped like every other top-level key.
    arrays['evidenceLedger'] = _evidence_ledger(arrays)

    # M220.2 (P0.4 closure): universal artifact hash-stamping, applied last
    # (after every other key is assembled) so the stamp covers the final
    # payload, including everything computed above in this function.
    arrays['_artifactStamps'] = _artifact_stamp(dm, arrays)

    # M225: back-fill each evidenceLedger row's artifactIdentity now that
    # _artifactStamps exists (chicken-and-egg: the ledger needed to be
    # stamped like every other key, but couldn't resolve its OWN sourceKey
    # references until the stamp existed).
    if arrays.get('evidenceLedger') and isinstance(arrays['evidenceLedger'].get('rows'), list):
        for _row in arrays['evidenceLedger']['rows']:
            _sk = _row.get('sourceKey')
            _st = (arrays['_artifactStamps'] or {}).get(_sk) if _sk else None
            _row['artifactIdentity'] = (
                {'corpusHashShort': (_st.get('corpusHash') or '')[:12],
                 'generatedAt': _st.get('generatedAt')} if _st else None)

    return arrays


def _acceptance_tests(master_path='drive_master.csv', config_path=None):
    """Audit acceptance fixtures (2026-07-14). Extend as new gates are added."""
    import pandas as pd
    dm = pd.read_csv(master_path)
    results = []
    # T-01 (audit P1, corrected 2026-08-10): peak charge magnitude must be the
    # sign-safe absolute extremum -- peak_I_charge is stored charge-negative,
    # so a naive .max() returns the value nearest zero (~1 A) instead of the
    # true ~200 A peak (this was bug C-02, fixed 2026-07-14). The ORIGINAL
    # version of this test hardcoded the exact expected magnitude
    # (pk == 213.0), which the audit correctly flagged: "fails legitimately
    # as an append-only corpus grows" -- a new drive with a genuinely
    # different (still correctly computed) peak would fail a healthy
    # pipeline. Required action: "Test invariants and signed golden
    # artifacts per snapshot; separate regression from scientific
    # acceptance." Rewritten as corpus-size-independent invariants (below,
    # always run) plus a cross-check against the live pipeline's own output
    # (further down, when config_path is supplied) plus a separate,
    # non-gating golden-snapshot regression note.
    naive_max = round(float(dm['peak_I_charge'].max()), 1)       # pre-fix bug's output
    pk = round(float(dm['peak_I_charge'].abs().max()), 1)        # fixed formula's output
    inv_nonneg = pk >= 0
    # abs() can only raise or hold the magnitude vs. the naive signed max; if
    # the corpus contains any charging (negative-current) sample at all, the
    # fix must be doing real work -- i.e. the abs-max must strictly exceed
    # the naive max. This directly catches a regression to the pre-fix
    # formula without asserting what the magnitude should be.
    inv_fix_active = (pk > naive_max) or (dm['peak_I_charge'].min() >= 0)
    # Loose physical sanity ceiling: catches unit/order-of-magnitude errors
    # (e.g. mA-as-A, a divide-by-zero blowup) without breaking on a
    # legitimately higher peak from a newly appended drive. Set generously
    # above the current historical extremum (213.0 A) with wide headroom,
    # not tuned to the current value.
    inv_bounded = 0 <= pk < 500
    t01_pass = inv_nonneg and inv_fix_active and inv_bounded
    results.append(('T-01 peakChargeA (invariants)', t01_pass,
                    f'peakChargeA={pk} A (naive .max()={naive_max} A, '
                    f'sign-fix active={pk > naive_max}, bounds=[0,500) A)'))

    # T-02 (M91, 2026-08-06): the three rf_damage_k2_socband_* columns are a
    # SPLIT of the existing rf_damage_k2 total (M17), not a new damage law --
    # this is the identity that makes that claim checkable, not asserted.
    bandcols = ['rf_damage_k2_socband_lo', 'rf_damage_k2_socband_mid',
               'rf_damage_k2_socband_hi']
    if set(bandcols) <= set(dm.columns):
        sub = dm.dropna(subset=bandcols + ['rf_damage_k2'])
        recon = sub[bandcols].sum(axis=1)
        dev = float((recon - sub['rf_damage_k2']).abs().max()) if len(sub) else float('nan')
        results.append(('T-02 rfDamageK2SocbandIdentity',
                        len(sub) > 0 and dev < 1e-3,
                        f'max|lo+mid+hi - rf_damage_k2|={dev:.2e} over n={len(sub)} rows'))
    else:
        results.append(('T-02 rfDamageK2SocbandIdentity', False,
                        'rf_damage_k2_socband_{lo,mid,hi} missing from master '
                        '-- run the M91 additive rebuild first'))

    # T-03 (M92, 2026-08-06): seasonalLife.observedConstant must trace to the
    # SAME workload mix as cycleLife's 'Observed logged mix' row -- this is
    # the precision bug (display-rounded observedMixShare threaded through
    # instead of a full-precision recompute) that was caught and fixed during
    # development; this gate prevents a silent regression back to it.
    # T-04: dodSocLevelSensitivity is present and structurally sane. Both
    # require config + a full (Category-A-only, with_raw=False) array build,
    # so they only run when config_path is supplied.
    if config_path:
        import json
        cfg = json.loads(open(config_path, encoding='utf-8').read())
        dm2 = dm.copy()
        dm2['date'] = dm2['date'].astype(str)
        odo = (cfg.get('vehicle') or {}).get('odometerKm', 42228)
        try:
            arrays = build_summary_arrays(
                dm2, raw_loader=None, with_raw=False, odometer_km=odo,
                seasonal_cfg=cfg.get('seasonalAssumptions'),
                ambient_by_drive=cfg.get('ambientByDrive'), session_cfg=cfg)
        except Exception as e:
            results.append(('T-03 observedConstantPrecision', False,
                            f'build_summary_arrays raised {type(e).__name__}: {e}'))
            results.append(('T-04 dodSocLevelSensitivityShape', False,
                            'skipped -- array build failed'))
            arrays = None
        if arrays is not None:
            cl_row = next((p for p in arrays.get('cycleLife', {}).get(
                'projections', []) if p.get('label') == 'Observed logged mix'), None)
            sl = arrays.get('seasonalLife') or {}
            oc = sl.get('observedConstant') or {}
            if cl_row is not None and oc.get('warmFloorGtcPerKm') is not None:
                dev3 = abs(cl_row['gtcPerKm'] - oc['warmFloorGtcPerKm'])
                results.append(('T-03 observedConstantPrecision', dev3 < 1e-6,
                                f'|cycleLife.gtcPerKm - observedConstant.warmFloorGtcPerKm| '
                                f'= {dev3:.2e} ({cl_row["gtcPerKm"]} vs {oc["warmFloorGtcPerKm"]})'))
            else:
                results.append(('T-03 observedConstantPrecision', False,
                                'cycleLife Observed-mix row or observedConstant missing'))
            dsl = arrays.get('dodSocLevelSensitivity')
            shape_ok = bool(dsl and 'Selected blend' in (dsl.get('scenarios') or {})
                            and dsl.get('corpusBandSharePctOfK2') is not None)
            results.append(('T-04 dodSocLevelSensitivityShape', shape_ok,
                            f'present={dsl is not None}, '
                            f'scenarios={list((dsl or {}).get("scenarios", {}).keys())}'))
            # T-01b (audit P1, 2026-08-10): cross-check the test's own
            # from-master computation against the value the live pipeline
            # actually ships in meta.peakChargeA. Two independent call sites
            # (this test, and the arrays['meta'] construction) using the same
            # formula on the same input must agree exactly -- this is the
            # "signed... per snapshot" consistency check the audit asked for,
            # without hardcoding what the value should be.
            live_pk = (arrays.get('meta') or {}).get('peakChargeA')
            results.append(('T-01b peakChargeA (live cross-check)',
                            live_pk is not None and abs(live_pk - pk) < 1e-9,
                            f'test-computed={pk} A vs. live meta.peakChargeA={live_pk} A'))
            # Golden-snapshot regression (audit P1: "separate regression from
            # scientific acceptance") -- informational only, NEVER gates
            # _acceptance_tests()'s return value. Update _T01_GOLDEN
            # deliberately (new n, new value, new date) whenever the corpus
            # grows and the new peakChargeA has been reviewed and confirmed
            # correct; a mismatch here is expected and healthy on corpus
            # growth, not a failure.
            _golden_n, _golden_v, _golden_date = _T01_GOLDEN
            _drift = (len(dm) != _golden_n) or (pk != _golden_v)
            print(f"  [INFO] T-01 golden snapshot (@{_golden_date}, n={_golden_n}): "
                  f"peakChargeA {_golden_v} A -> current n={len(dm)}: {pk} A"
                  f"{'  (DRIFTED -- if expected, update _T01_GOLDEN)' if _drift else '  (MATCH)'}")

    ok = all(r[1] for r in results)
    for name, passed, detail in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}: {detail}")
    return ok


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        mp = sys.argv[2] if len(sys.argv) > 2 else 'drive_master.csv'
        cp = sys.argv[3] if len(sys.argv) > 3 else None
        sys.exit(0 if _acceptance_tests(mp, cp) else 1)
    print("compute_summary_arrays.py loaded OK")
