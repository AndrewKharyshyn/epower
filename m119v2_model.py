#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""m119v2_model.py -- M147 (2026-08-20): M119-v2, the five-variable,
duration-aware discrete-time hazard model of engine start/stop.

This supersedes the M119 v1 binned-probability surface (_soc_hysteresis_summary
in compute_summary_arrays.py, kept intact and additive) with two SEPARATE 1 Hz
discrete-time hazard models:

  * a START model, fit on engine-OFF seconds, predicting a canonical engine
    start in the following second;
  * a STOP model, fit on engine-ON seconds, predicting a canonical engine
    stop in the following second.

Five primary predictors, all strictly lagged (information available at or
before second t, never after):

  1. SoC          -- continuous BMS SoC at t, carry-forward age <= 5 s.
  2. speed        -- validated vehicle speed at t (VCM primary / standard-OBD
                     fallback, the v6 pipeline's speed-source priority),
                     age <= 2 s.
  3. Tpack        -- mean of the T1-T4 pack sensors, >= 3 sensors required,
                     age <= 15 s.
  4. recent demand-- START: median battery DISCHARGE power over [t-8, t-2] s
                        (kW, = median max(0, -I*V/1000));
                     STOP:  median positive target-torque x speed demand INDEX
                        over [t-5, t-1] s (= median max(T_target,0)*v; a demand
                        index, NOT kW).
  5. state duration- START: offDurationS (s since last canonical stop);
                     STOP:  onDurationS  (s since current canonical start);
                     entered through log1p(), never as a raw linear term.

Structure (fit independently for start and stop):

  h(t) = alpha + f1(SoC) + f2(speed) + f3(Tpack) + f4(demand) + f5(log1p dur)
         + interactions [ SoC x demand, Tpack x demand, SoC x dur ]
         + day/drive dependence

Link: complementary log-log (discrete-time hazard). This is the only link
actually fit; fit_glm() accepts a 'logit' argument value but no logistic-link
refit is run or reported anywhere in this module's output -- there is
currently no logistic-link sensitivity check. (Deferred: see backlog below.)

Model-form correction (audit remediation, source-only pass): the design is an
UNPENALIZED fixed-basis complementary-log-log GLM (statsmodels sm.GLM(...).fit(),
no fit_regularized call, no penalty matrix, no smoothing-parameter selection,
no nested tuning anywhere in this module) with restricted-cubic-spline main
effects f1..f5 and three prespecified low-degree cross-product interaction
terms (SoC x demand, Tpack x demand, SoC x duration). Earlier revisions of
this docstring described these as "penalized interactions" / "tensor-product
smooths" / implied a GAM(M); those terms are incorrect for this frozen fit --
there is no penalization, smoothing-parameter selection, or GAMM anywhere in
the fitting code, and they have been removed from this docstring, from the
JSON methodology string, and from active dashboard prose. (Deferred: a true
penalized/GAM extension is recorded as future M119 backlog, not implemented
or executed in this pass.)

Random-effects disclosure. A full crossed (day x drive) binomial GAMM is not
tractable on the installed Python stack (no mgcv/lme4 equivalent). The smooth
additive structure and the cross-product interaction terms ARE fit exactly, as
fixed-knot restricted cubic-spline / low-degree product bases. Day/drive
dependence is handled by day-CLUSTERED robust covariance for coefficient
inference and by whole-day GROUPED CONTIGUOUS DAY-BLOCK k-fold cross-validation
for every reported generalization metric -- the operative guard against
treating individual seconds as independent. This blocked-CV scheme trains each
fold on ALL OTHER blocks, including blocks from LATER calendar dates than the
held-out fold; it is a leakage guard against pseudo-replication within a
calendar day, not a forward-only / rolling-origin (chronological) validation
scheme, and must not be described as "chronological" in a way that implies
train-on-past-only evaluation. (Genuine rolling-origin / forward-chaining
validation is implemented separately as rolling_origin_cv, M222.1.)

A day random-intercept GLMM sensitivity check (e.g. statsmodels
BinomialBayesMixedGLM) is NOT currently fit anywhere in this module -- no such
call exists in the fitting code below, and no such output is present in the
shipped JSON block. Any docstring or dashboard text claiming this sensitivity
exists is stale and has been removed. (Deferred: a real day-random-intercept
GLMM sensitivity, reporting the day-level variance component, is recorded as
future M119 backlog, not implemented or executed in this pass.)

This is an observational hazard model of when the powertrain tends to
start/stop the engine given the buffer state -- NOT a reconstruction of
Nissan's proprietary ECU control algorithm. Demand, SoC, speed, temperature
and state duration are evidence-calibrated as variables that add predictive
association beyond SoC alone in this fitted model; the model ladder does not
by itself isolate a causal importance ranking or reconstruct any control
algorithm.

Deferred M119-v2 methodological backlog (NOT implemented or executed in this
source-only remediation pass; for a future explicit user-triggered M119-v2
run only -- see module-level recompute policy in compute_summary_arrays.py):
  * raw vs. complete-case risk sets reported separately;
  * threshold/debounce sensitivity for the canonical transition detector;
  * a genuine logistic-link sensitivity refit (link='logit') alongside the
    primary complementary-log-log fit;
  * a day random-intercept GLMM sensitivity (e.g. BinomialBayesMixedGLM),
    reporting the day-level variance component;
  * support-density masks on the median-profile prediction curves;
  * any penalized-spline / smoothing-parameter-selected / GAM(M) extension
    of the current unpenalized fixed-basis design.
(Grid-origin left-censoring is handled since M231 via start_diag /
startDetectorBoundaryAudit; rolling-origin CV since M222.1.)
None of the above changes the fitted model or its sample and none may be
implemented by editing this module without a full refit; recomputing or
refitting M119-v2 is performed only on the user's explicit, session-scoped
request (see recompute-on-demand policy in compute_summary_arrays.py).

Refit history: M147 (2026-08-20, n=259 drives, the fit that was frozen and
carried forward through M148-M215) -- M216 (2026-09-03, n=320 drives,
explicit user-requested full recompute; see CHANGELOG M216 for the
memory-hygiene patch that made this recompute feasible in-sandbox and for
the before/after metric comparison) -- M285 (2026-09-19, n=410 drives; the
M258/M264 n=410 output never reached Project Knowledge, so it was re-run from
raw). All fits use the identical methodology described above -- each refit
changed the training sample and re-ran the SAME fixed specification; none
altered any term, link, knot-placement rule, or CV scheme.

The module is import-safe (used by compute_summary_arrays.build_summary_arrays
via socHysteresisV2 = build_m119v2(...)) and runnable standalone to regenerate
the JSON block from the raw corpus.
"""
from __future__ import annotations

import gc
import io
import math
import re
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

# --------------------------------------------------------------------------
# Raw-column literals (canonical; the same glyphs the v6 COL_MAP / slim cache
# use). RPM is the ENGINE/generator rpm ('Оберти двигуна'), NOT the traction
# motor rpm (rejected in M102).
# --------------------------------------------------------------------------
RPM_COL = '\u041e\u0431\u0435\u0440\u0442\u0438 \u0434\u0432\u0438\u0433\u0443\u043d\u0430 (rpm)'
SOC_COL = '[BMS] HV State of charge (%)'
SPEED_VCM = '[VCM] Vehicle Speed (km/h)'
SPEED_OBD = '\u0428\u0432\u0438\u0434\u043a\u0456\u0441\u0442\u044c \u0430\u0432\u0442\u043e\u043c\u043e\u0431\u0456\u043b\u044f (km/h)'
T_COLS = ['[BMS] HV Battery Temperature Sensor %d (\u2103)' % k for k in (1, 2, 3, 4)]
I_COL = '[BMS] HV Battery Current (A)'
V_COL = '[BMS] HV Battery voltage (V)'
TGT_TORQUE = '[VCM] Target Motor Torque (N\u22c5m)'
ENG_COOLANT = '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043e\u0445\u043e\u043b\u043e\u0434\u043d\u043e\u0457 \u0440\u0456\u0434\u0438\u043d\u0438 (\u2103)'

# Debounce thresholds (RPM, seconds) -- the ONE canonical transition
# definition. RPM band edges match M116/M118 (<=100 off, >800 running); the
# sustained-run requirements are the debounce v2 adds over the M116/M118
# single-sample trigger.
RPM_OFF = 100.0
RPM_ON = 800.0
START_OFF_S = 3     # >= 3 s sustained off before a start
START_ON_S = 2      # >= 2 s sustained running to confirm a start
STOP_OFF_S = 3      # >= 3 s sustained off to confirm a stop
# carry-forward ages (s)
AGE_SOC, AGE_SPEED, AGE_TEMP = 5, 2, 15
AGE_IV, AGE_TORQUE, AGE_COOLANT = 5, 3, 15
MIN_TEMP_SENSORS = 3


_NEEDED = [None, RPM_COL, SOC_COL, SPEED_VCM, SPEED_OBD, I_COL, V_COL,
           TGT_TORQUE, ENG_COOLANT] + T_COLS


def read_needed(path):
    """Parse only the columns M119-v2 consumes (a ~13-of-77 projection), which
    cuts the raw-CSV parse cost by roughly 5x versus a full read. 'time' plus
    any present model channel; returns a DataFrame or None."""
    try:
        head = pd.read_csv(path, nrows=0)
    except Exception:
        return None
    cols = set(head.columns)
    use = ['time'] + [c for c in _NEEDED if c and c in cols]
    if 'time' not in cols or RPM_COL not in cols:
        return None
    try:
        return pd.read_csv(path, usecols=use, low_memory=False)
    except Exception:
        return None


# ==========================================================================
# 1 Hz grid + canonical debounced detector
# ==========================================================================
def _one_hz(series, index, limit):
    """Resample an irregular (async-PID) numeric series onto a 1 Hz integer-
    second grid by bin-mean, then carry forward up to `limit` seconds."""
    s = series.dropna()
    if s.empty:
        return pd.Series(np.nan, index=index)
    g = s.resample('1s').mean()
    g = g.reindex(index)
    return g.ffill(limit=limit)


def build_grid(df):
    """Build the per-drive 1 Hz predictor grid from one raw frame. Returns a
    DataFrame indexed by integer-second timestamps or None if unusable.
    Every channel is carried forward only up to its specified maximum age, so
    no predictor uses information newer than its stated staleness bound."""
    if df is None or 'time' not in df.columns or RPM_COL not in df.columns:
        return None
    t = pd.to_datetime(df['time'], format='mixed', errors='coerce')
    ok = t.notna()
    if ok.sum() < 10:
        return None
    t = t[ok]
    df = df.loc[ok.values]
    t0, t1 = t.min().floor('1s'), t.max().ceil('1s')
    index = pd.date_range(t0, t1, freq='1s')

    # physical plausibility gates (match compute_drive_summary_v6 conventions:
    # pack sensors -40..80 C; SoC 0..100; speed 0..260). Out-of-range samples
    # are dropped to NaN before resampling so a single glitch cannot bias a bin.
    GATE = {
        SOC_COL: (0.0, 100.0), SPEED_VCM: (0.0, 260.0), SPEED_OBD: (0.0, 260.0),
        V_COL: (100.0, 500.0), I_COL: (-1000.0, 1000.0),
        ENG_COOLANT: (-40.0, 130.0),
    }
    for c in T_COLS:
        GATE[c] = (-40.0, 80.0)

    def col(name):
        if name not in df.columns:
            return pd.Series(np.nan, index=t.values)
        v = pd.to_numeric(df[name], errors='coerce').values.astype(float)
        if name in GATE:
            lo, hi = GATE[name]
            v = np.where((v < lo) | (v > hi), np.nan, v)
        return pd.Series(v, index=t.values)

    # RPM: ffill only across the ~1.3 s native cadence (limit 3 s) -- a longer
    # dropout stays NaN so it cannot masquerade as a sustained state.
    rpm = _one_hz(col(RPM_COL), index, limit=3)
    if rpm.notna().sum() < 10:
        return None

    soc = _one_hz(col(SOC_COL), index, limit=AGE_SOC)
    # speed source priority: VCM primary; OBD fallback if VCM sparse (< 20
    # native samples), mirroring compute_drive_summary_v6.
    vcm_raw = col(SPEED_VCM)
    if vcm_raw.notna().sum() >= 20:
        speed = _one_hz(vcm_raw, index, limit=AGE_SPEED)
        speed_source = 'vcm'
    else:
        speed = _one_hz(col(SPEED_OBD), index, limit=AGE_SPEED)
        speed_source = 'obd_fallback'

    # Pack temperature: >= MIN_TEMP_SENSORS of T1-T4 present after ageing.
    tg = pd.concat([_one_hz(col(c), index, limit=AGE_TEMP) for c in T_COLS], axis=1)
    tg.columns = ['T1', 'T2', 'T3', 'T4']
    tvalid = tg.notna().sum(axis=1)
    tpack = tg.mean(axis=1, skipna=True)
    tpack[tvalid < MIN_TEMP_SENSORS] = np.nan

    # Battery power channels for the START demand term.
    ig = _one_hz(col(I_COL), index, limit=AGE_IV)
    vg = _one_hz(col(V_COL), index, limit=AGE_IV)
    # M11: raw current is charge-positive. discharge power (kW) = max(0,-I*V/1000).
    dis_kw = (-(ig * vg) / 1000.0).clip(lower=0)
    chg_kw = ((ig * vg) / 1000.0).clip(lower=0)   # for the accum-charge sensitivity var

    # Torque x speed demand INDEX for the STOP demand term.
    tt = _one_hz(col(TGT_TORQUE), index, limit=AGE_TORQUE)
    torque_dmd = (tt.clip(lower=0) * speed)

    coolant = _one_hz(col(ENG_COOLANT), index, limit=AGE_COOLANT)

    g = pd.DataFrame({
        'rpm': rpm, 'soc': soc, 'speed': speed, 'tpack': tpack,
        'dis_kw': dis_kw, 'chg_kw': chg_kw, 'torque_dmd': torque_dmd,
        'coolant': coolant,
    }, index=index)
    g.attrs['speed_source'] = speed_source
    return g


def _run_starts(mask, minlen, n):
    """First index of every maximal True-run in `mask` of length >= minlen."""
    out = []
    i = 0
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            if (j - i + 1) >= minlen:
                out.append(i)
            i = j + 1
        else:
            i += 1
    return out


def detect_transitions(rpm):
    """Canonical debounced start/stop detector on a 1 Hz rpm series.

      start: a sustained OFF interval (RPM <= 100 for >= 3 s) FOLLOWED BY a
             sustained RUNNING interval (RPM > 800 for >= 2 s). The start
             second is the first second of the running run.
      stop:  a RUNNING second FOLLOWED BY a sustained OFF interval (RPM <= 100
             for >= 3 s). The stop second is the first second of the off run.

    Confirmation is run-based, NOT strict-adjacency: the RPM ramp transiting the
    100-800 mid-band between the two states does not defeat a transition, while
    a short (< 3 s off / < 2 s run) dropout or a missing-sample (NaN) gap forms
    no confirmed run and is therefore never counted as a transition. The engine
    state-machine label still defaults to OFF at the grid origin so on/off
    durations and every other downstream computation are BYTE-IDENTICAL to
    the pre-M231 behaviour; on_state, starts and stops are unchanged.

    M231 (audit F05, P1): the docstring's own >= 3 s prior-OFF rule for a
    START was never enforced -- any confirmed RUN run flipped the state
    machine regardless of whether a genuinely-observed >= START_OFF_S OFF
    run preceded it, or whether the machine's OFF label came from the
    initial assumption or from holding state silently across an unresolved
    NaN gap. Rather than changing which seconds count as starts (a second,
    larger, separately-scoped question about e.g. re-deriving on_state
    itself), this makes the confirmation status of each start EXPLICIT via
    a fourth return value, start_diag: dict[start-second -> flags]. Flags
    are independent and can co-occur:
      atGridOrigin        -- the start's first second is index 0 (no data
                              exists before the recording began: strictly
                              left-censored). A subset of noPriorConfirmedOff.
      noPriorConfirmedOff -- no run of >= START_OFF_S contiguous, valid OFF
                              seconds (RPM <= 100) has been OBSERVED anywhere
                              in the data before this start. The documented
                              rule was never actually satisfied; the state
                              machine's OFF label here came from the initial
                              assumption, not from evidence.
      afterUnknownGap     -- the sample immediately preceding the start's
                              first index is invalid (NaN): a missing-data
                              gap immediately abuts the start, so an
                              unobserved intermediate stop/start inside that
                              gap cannot be ruled out even though the prior
                              OFF confirmation itself (if any) is genuine.
    Verified against the audit's own four-row fixture table (RPM sequences
    900^4 / 0,900^3 / 0^3,NaN^10,900^3 / 0^3,900^3) reproducing exactly its
    stated atGridOrigin / noPriorConfirmedOff / afterUnknownGap / clean
    classification in each case.

    Returns (on_state Series[bool], start-second set, stop-second set,
    start_diag dict); on_state alternates strictly start -> stop -> start."""
    r = rpm.values.astype(float)
    n = len(r)
    valid = ~np.isnan(r)
    off = valid & (r <= RPM_OFF)
    run = valid & (r > RPM_ON)

    off_starts_stop_gate = _run_starts(off, STOP_OFF_S, n)     # unchanged: confirms STOP
    # M231: the START prior-off gate is tracked against its own named
    # constant (numerically == STOP_OFF_S today, but kept decoupled so a
    # future change to either threshold cannot silently couple the two
    # directions). Any off run long enough to be START_OFF_S-confirmed is,
    # by construction, disjoint from and fully completed before any run
    # that begins after it (the off/run masks are mutually exclusive), so a
    # simple "did a gate run start strictly before this start's index"
    # check is sufficient -- no separate end-index bookkeeping is needed.
    off_starts_start_gate = _run_starts(off, START_OFF_S, n)

    events = sorted(
        [(s, True) for s in _run_starts(run, START_ON_S, n)] +
        [(s, False) for s in off_starts_stop_gate])

    on = np.zeros(n, dtype=bool)
    starts, stops = set(), set()
    start_diag = {}
    state = False           # engine off at key-on (state-machine label only
                             # -- start_diag carries the actual evidence)
    last = 0
    ever_confirmed_off_before = False
    gate_i = 0
    for t, want in events:
        while gate_i < len(off_starts_start_gate) and off_starts_start_gate[gate_i] < t:
            ever_confirmed_off_before = True
            gate_i += 1
        if want == state:
            continue            # already in this confirmed state; ignore
        on[last:t] = state      # interval [last, t) held the previous state
        if want:
            starts.add(t)
            start_diag[t] = {
                'atGridOrigin': bool(t == 0),
                'noPriorConfirmedOff': not ever_confirmed_off_before,
                'afterUnknownGap': bool(t > 0 and not valid[t - 1]),
            }
        else:
            stops.add(t)
        state = want
        last = t
    on[last:n] = state
    return pd.Series(on, index=rpm.index), starts, stops, start_diag


# ==========================================================================
# per-drive at-risk sample tables (start-risk / stop-risk)
# ==========================================================================
def drive_samples(df, file_name, day_key):
    """Return (start_df, stop_df, start_diag_counts) of at-risk seconds with
    all lagged predictors and next-second outcomes, or (None, None, {}). No
    look-ahead: every predictor is computed from data at or before second t;
    only the outcome uses t+1.

    M231 (audit F05): starts flagged noPriorConfirmedOff by
    detect_transitions() are NOT labeled as a positive isStartNext
    outcome -- the documented >= START_OFF_S prior-off rule was never
    actually observed for them, so treating them as a confirmed engine
    start would train the hazard model on an unverifiable label. They are
    excluded from the at-risk table entirely (right-censored out), not
    relabeled as a negative, since "no start happened here" is equally
    unverifiable. atGridOrigin is a strict subset of noPriorConfirmedOff
    (index 0 can never have a prior confirmed run) and is excluded via the
    same flag. afterUnknownGap-flagged starts ARE kept as confirmed
    positives: the prior OFF confirmation for these is genuine evidence,
    the flag only notes that an additional unobserved transition inside the
    immediately-preceding gap cannot be ruled out -- a timing caveat, not a
    label-validity problem."""
    g = build_grid(df)
    if g is None:
        return None, None, {}
    on, starts, stops, start_diag = detect_transitions(g['rpm'])
    n = len(g)
    on_v = on.values
    idx = np.arange(n)

    diag_counts = {
        'nStartsRaw': len(starts),
        'nAtGridOrigin': sum(1 for f in start_diag.values() if f['atGridOrigin']),
        'nNoPriorConfirmedOff': sum(1 for f in start_diag.values()
                                     if f['noPriorConfirmedOff']),
        'nAfterUnknownGap': sum(1 for f in start_diag.values()
                                  if f['afterUnknownGap']),
    }

    # next-second transition indicators aligned to position t
    is_start_next = np.zeros(n, dtype=int)
    is_stop_next = np.zeros(n, dtype=int)
    start_excluded = np.zeros(n, dtype=bool)
    for t in starts:
        if t - 1 >= 0:
            if start_diag.get(t, {}).get('noPriorConfirmedOff'):
                start_excluded[t - 1] = True
            else:
                is_start_next[t - 1] = 1
    for t in stops:
        if t - 1 >= 0:
            is_stop_next[t - 1] = 1

    # segment structure: a segment begins at each state change (and at t=0).
    change = np.empty(n, dtype=bool)
    change[0] = True
    change[1:] = on_v[1:] != on_v[:-1]
    seg_start = np.where(change, idx, 0)
    seg_start = np.maximum.accumulate(seg_start)     # index where current state began
    dur = idx - seg_start
    off_dur = np.where(~on_v, dur, 0.0)
    on_dur = np.where(on_v, dur, 0.0)

    # lagged demand terms via shift+rolling median on the 1 Hz grid
    dstart = g['dis_kw'].shift(2).rolling(7, min_periods=4).median().values      # [t-8,t-2]
    dstop = g['torque_dmd'].shift(1).rolling(5, min_periods=3).median().values   # [t-5,t-1]

    soc_v = g['soc'].values
    soc_since = soc_v - soc_v[seg_start]             # SoC change since last transition

    # accumulated charge energy (kWh) since the current engine start; resets at
    # each segment boundary, retained only on ON seconds.
    chg_step = np.nan_to_num(g['chg_kw'].values) / 3600.0
    cs = np.cumsum(chg_step)
    csm1 = np.concatenate([[0.0], cs])               # cs[k-1] via csm1[k]
    accum_chg = np.where(on_v, cs - csm1[seg_start], 0.0)

    coolant_v = g['coolant'].values
    key_on_s = idx.astype(float)

    base = pd.DataFrame({
        'soc': soc_v, 'speed': g['speed'].values, 'tpack': g['tpack'].values,
        'offDurationS': off_dur, 'onDurationS': on_dur,
        'dStart': dstart, 'dStop': dstop,
        'socSince': soc_since, 'accumChgKwh': accum_chg,
        'coolant': coolant_v, 'keyOnS': key_on_s,
        'on': on_v, 'isStartNext': is_start_next, 'isStopNext': is_stop_next,
        'startExcluded': start_excluded,   # M231 (audit F05)
        'rpmValid': g['rpm'].notna().values,
    }, index=g.index)
    base['file'] = file_name
    base['day'] = day_key

    # at-risk-for-start: engine off at t, rpm defined at t and t+1.
    # M231 (audit F05): startExcluded drops the specific at-risk second
    # immediately preceding a noPriorConfirmedOff start -- an unverifiable
    # label, right-censored out rather than mislabeled either way.
    rpm_next = base['rpmValid'].shift(-1).fillna(False)
    sr = base[(~base['on']) & base['rpmValid'] & rpm_next
              & (~base['startExcluded'])].copy()
    sr = sr[['soc', 'speed', 'tpack', 'offDurationS', 'dStart',
             'socSince', 'accumChgKwh', 'coolant', 'keyOnS',
             'isStartNext', 'file', 'day']].rename(
        columns={'offDurationS': 'durationS', 'dStart': 'demand', 'isStartNext': 'y'})
    tr = base[(base['on']) & base['rpmValid'] & rpm_next].copy()
    tr = tr[['soc', 'speed', 'tpack', 'onDurationS', 'dStop',
             'socSince', 'accumChgKwh', 'coolant', 'keyOnS',
             'isStopNext', 'file', 'day']].rename(
        columns={'onDurationS': 'durationS', 'dStop': 'demand', 'isStopNext': 'y'})
    return sr, tr, diag_counts


# ==========================================================================
# restricted cubic spline basis (Harrell natural-spline parametrisation) and
# low-degree cross-product interaction bases (not penalized/tensor-product --
# see module docstring)
# ==========================================================================
def rcs_basis(x, knots):
    """Restricted (natural) cubic spline basis. len(knots)>=3 -> len(knots)-2
    columns (the first is the linear term). Returns (basis[n,k-1], knots)."""
    x = np.asarray(x, dtype=float)
    k = np.asarray(knots, dtype=float)
    nk = len(k)
    denom = (k[-1] - k[0]) ** 2
    cols = [x]
    for j in range(nk - 2):
        def tp(u, kj):
            d = (x - kj)
            return np.where(d > 0, d, 0.0) ** 3
        term = (tp(x, k[j])
                - tp(x, k[-2]) * (k[-1] - k[j]) / (k[-1] - k[-2])
                + tp(x, k[-1]) * (k[-2] - k[j]) / (k[-1] - k[-2]))
        cols.append(term / denom)
    return np.column_stack(cols), k


def _knots(x, n=5):
    """Interior+boundary knots at data quantiles; dedup for degenerate spread."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    qs = np.linspace(0.05, 0.95, n)
    k = np.unique(np.quantile(x, qs))
    if len(k) < 3:
        lo, hi = np.nanmin(x), np.nanmax(x)
        if hi <= lo:
            hi = lo + 1.0
        k = np.linspace(lo, hi, 3)
    return k


class DesignSpec:
    """Holds the spline knot sets learned on the TRAIN fold and rebuilds an
    identical design matrix on any fold -- so validation never leaks test-fold
    knot placement. `terms` selects which predictors enter (for the model
    ladder)."""

    def __init__(self, terms, interactions, extra=()):
        self.terms = list(terms)
        self.interactions = list(interactions)
        self.extra = list(extra)   # sensitivity vars (linear)
        self.knots = {}
        self.centers = {}
        self.scale = {}            # (mean,std) per spline term, learned on train

    SPLINE_KNOTS = {'soc': 5, 'speed': 5, 'tpack': 4, 'demand': 4, 'logdur': 4}

    def _prep(self, d):
        out = pd.DataFrame(index=d.index)
        out['soc'] = d['soc']
        out['speed'] = d['speed'].clip(lower=0)
        out['tpack'] = d['tpack']
        out['demand'] = d['demand']
        out['logdur'] = np.log1p(d['durationS'].clip(lower=0))
        for e in self.extra:
            out[e] = d[e]
        return out

    def fit(self, d):
        p = self._prep(d)
        for t in self.terms:
            if t in self.SPLINE_KNOTS:
                col = p[t].values.astype(float)
                mu = float(np.nanmean(col))
                sd = float(np.nanstd(col)) or 1.0
                self.scale[t] = (mu, sd)
                z = (col - mu) / sd
                self.knots[t] = _knots(z, self.SPLINE_KNOTS[t])
        for e in self.extra:
            self.centers[e] = float(np.nanmean(p[e]))
        return self

    def transform(self, d):
        p = self._prep(d)
        mats, names = [np.ones((len(p), 1))], ['intercept']
        basis_cache = {}
        for t in self.terms:
            if t in self.knots:
                mu, sd = self.scale[t]
                z = (p[t].values.astype(float) - mu) / sd
                b, _ = rcs_basis(z, self.knots[t])
                basis_cache[t] = b
                mats.append(b)
                names += ['%s_%d' % (t, i) for i in range(b.shape[1])]
        # reduced tensor interactions: outer product of the LINEAR parts only
        # (first basis column of each factor) -- a low-df cross-product
        # interaction (NOT penalized -- no penalty term in the fit objective;
        # kept low-df by construction so it will not blow up the design).
        for a, b in self.interactions:
            if a in basis_cache and b in basis_cache:
                ta = basis_cache[a][:, [0]]
                tb = basis_cache[b][:, [0]]
                mats.append(ta * tb)
                names.append('%s_x_%s' % (a, b))
        for e in self.extra:
            v = (p[e].values - self.centers.get(e, 0.0)).reshape(-1, 1)
            mats.append(v)
            names.append(e)
        X = np.column_stack(mats)
        return X, names


def _clean(d, cols):
    m = np.ones(len(d), dtype=bool)
    for c in cols:
        m &= d[c].notna().values
    return d[m].copy()


# ==========================================================================
# fit + metrics
# ==========================================================================
import statsmodels.api as sm
from statsmodels.genmod.families.links import CLogLog, Logit


def fit_glm(X, y, groups=None, link='cloglog', maxiter=60):
    fam = sm.families.Binomial(link=CLogLog() if link == 'cloglog' else Logit())
    model = sm.GLM(y, X, family=fam)
    try:
        if groups is not None:
            return model.fit(cov_type='cluster', cov_kwds={'groups': groups},
                             maxiter=maxiter, tol=1e-8)
        return model.fit(maxiter=maxiter, tol=1e-8)
    except Exception:
        # fall back to an unpenalised OLS-on-linear-predictor start; return
        # whatever params IRLS reached rather than doubling the fit cost.
        return model.fit(maxiter=maxiter, tol=1e-6, scale=1.0)


def _predict(res, X):
    """M236 (audit F32 fix): apply the inverse link the model was ACTUALLY
    fit with, not a hardcoded cloglog inverse. fit_glm() supports
    link='logit' as well as the default 'cloglog', but this function
    previously always applied 1-exp(-exp(eta)) (the cloglog inverse)
    regardless -- a logit-fitted result would have silently received the
    wrong predictions (e.g. eta=0 -> 0.6321 instead of the correct 0.5).
    Dormant in practice: every current call site (run_ladder,
    sensitivity_screen, _final_fit, oos_predict, rolling_origin_predict,
    rolling_origin_cv) uses the default link='cloglog', so no reported
    score is affected by this fix -- it matters only once a logit
    sensitivity refit (mentioned as planned, never implemented) is added."""
    eta = X @ res.params
    eta = np.clip(eta, -30, 20)
    try:
        return np.asarray(res.model.family.link.inverse(eta))
    except Exception:
        # Fallback preserves the previous unconditional behavior if the
        # link object is ever unavailable for some reason.
        return 1.0 - np.exp(-np.exp(eta))


def brier(y, p):
    return float(np.mean((p - y) ** 2))


def logloss(y, p):
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def pr_auc(y, p):
    from sklearn.metrics import average_precision_score
    if y.sum() == 0 or y.sum() == len(y):
        return None
    return float(average_precision_score(y, p))


def calibration(y, p):
    """Logistic recalibration: regress y on logit(p). slope~1, intercept~0 is
    well-calibrated."""
    p = np.clip(p, 1e-6, 1 - 1e-6)
    z = np.log(p / (1 - p)).reshape(-1, 1)
    Z = np.column_stack([np.ones(len(z)), z])
    try:
        res = sm.GLM(y, Z, family=sm.families.Binomial()).fit()
        return float(res.params[1]), float(res.params[0])
    except Exception:
        return None, None


# ==========================================================================
# model ladder, blocked-day CV, day-clustered bootstrap
# ==========================================================================
CORE5 = ['soc', 'speed', 'tpack', 'demand', 'durationS']
INTERACTIONS = [('soc', 'demand'), ('tpack', 'demand'), ('soc', 'logdur')]


def model_ladder():
    """The four nested specifications compared under blocked-day CV."""
    return {
        'socOnly':   DesignSpec(['soc'], []),
        'socSpeed':  DesignSpec(['soc', 'speed'], []),
        'fourVar':   DesignSpec(['soc', 'speed', 'tpack', 'demand'], []),
        'fiveVarDur': DesignSpec(['soc', 'speed', 'tpack', 'demand', 'logdur'],
                                 INTERACTIONS),
    }


def blocked_day_folds(days, k=5):
    """Assign each day to one of k CONTIGUOUS blocks of sorted calendar days --
    whole days are never split across folds, and each fold's test set is a
    distinct time window. NOTE: each fold is trained on ALL other blocks
    (including later-dated ones), so this is blocked k-fold CV, not a
    forward-only scheme. Returns {day: fold_id}."""
    uniq = sorted(pd.unique(days))
    edges = np.linspace(0, len(uniq), k + 1).astype(int)
    fold = {}
    for fi in range(k):
        for d in uniq[edges[fi]:edges[fi + 1]]:
            fold[d] = fi
    return fold


def rolling_origin_folds(days, min_train_days, step_days):
    """M222.1 (enhancement plan item M222, M119-v2 rolling-origin CV).
    Forward-chaining (rolling-origin) folds: sorted unique days split into
    a GROWING training history and a step_days-wide validation block that
    advances the cutoff each round.

    Structurally parallel to blocked_day_folds (whole days never split
    across train/validation -- the same leakage-guard granularity), but
    tests a MATERIALLY DIFFERENT question: blocked_day_folds trains each
    fold on ALL OTHER blocks, including blocks from LATER calendar dates
    than the held-out fold (a pseudo-replication leakage guard, not a
    forward-only scheme -- see the module docstring's own caution against
    describing it as "chronological" in a train-on-past-only sense). Here,
    every validation block is scored using ONLY data from strictly earlier
    days -- a genuine train-on-past-only evaluation, testing temporal
    drift / order-dependence rather than duplicating the blocked-day
    result.

    Returns a list of (train_days: frozenset, val_days: frozenset) tuples,
    one per rolling round. The first min_train_days days form the initial
    training history and are never themselves validated on (no prior data
    exists to train a model from)."""
    uniq = sorted(pd.unique(days))
    rounds = []
    i = min_train_days
    while i < len(uniq):
        train_days = frozenset(uniq[:i])
        val_days = frozenset(uniq[i:i + step_days])
        if val_days:
            rounds.append((train_days, val_days))
        i += step_days
    return rounds


def oos_predict(tbl, spec, fold_map, link='cloglog'):
    """Blocked-day OOS predictions: for each fold, learn knots+scale
    and fit on the OTHER folds, predict the held-out fold. Returns an aligned
    prediction vector (NaN where a fold could not be scored)."""
    y = tbl['y'].values.astype(float)
    folds = tbl['day'].map(fold_map).values
    pred = np.full(len(tbl), np.nan)
    for fi in sorted(set(folds)):
        tr = tbl[folds != fi]
        te_mask = folds == fi
        if te_mask.sum() == 0 or tr['y'].sum() < 5:
            continue
        s = DesignSpec(spec.terms, spec.interactions, spec.extra).fit(tr)
        Xtr, _ = s.transform(tr)
        res = fit_glm(Xtr, tr['y'].values.astype(float), link=link)
        Xte, _ = s.transform(tbl[te_mask])
        pred[te_mask] = _predict(res, Xte)
        # Memory hygiene (M216, 2026-09-03, explicit user-requested recompute):
        # statsmodels GLMResults/GLM hold internal back-references (model <->
        # results <-> data attributes) that form reference cycles CPython's
        # refcounting alone cannot free; across the ~20-fit-per-model x
        # multi-model ladder + sensitivity screen sequence these accumulated
        # unreclaimed in the M148-documented OOM. Explicit del + a forced
        # cyclic-GC pass at every fold boundary bounds peak RSS to
        # O(one fold's working set) instead of O(all folds fit so far).
        # Pure memory hygiene -- fit_glm/_predict/DesignSpec numerics are
        # byte-for-byte unchanged; no effect on any fitted coefficient,
        # metric, or prediction.
        del tr, te_mask, s, Xtr, res, Xte
        gc.collect()
    return pred


def rolling_origin_predict(tbl, spec, rounds, link='cloglog'):
    """M222.1: genuine forward-chaining OOS predictions -- for each rolling
    round (train_days, val_days) from rolling_origin_folds, fits ONLY on
    the round's train_days (strictly earlier than val_days) and predicts
    the val_days block. Structurally parallel to oos_predict (same
    DesignSpec-refit-per-round / memory-hygiene pattern), but the fold
    semantics are fundamentally different: oos_predict's held-out fold can
    train on chronologically LATER data, this cannot. Returns an aligned
    prediction vector (NaN where a round could not be scored -- e.g. too
    few training events yet, or nothing falls in the validation block for
    this table)."""
    days = tbl['day'].values
    pred = np.full(len(tbl), np.nan)
    for train_days, val_days in rounds:
        tr_mask = np.isin(days, list(train_days))
        va_mask = np.isin(days, list(val_days))
        if va_mask.sum() == 0 or tbl.loc[tr_mask, 'y'].sum() < 5:
            continue
        tr = tbl[tr_mask]
        s = DesignSpec(spec.terms, spec.interactions, spec.extra).fit(tr)
        Xtr, _ = s.transform(tr)
        res = fit_glm(Xtr, tr['y'].values.astype(float), link=link)
        Xva, _ = s.transform(tbl[va_mask])
        pred[va_mask] = _predict(res, Xva)
        del tr, s, Xtr, res, Xva      # M216-style memory hygiene, same rationale
        gc.collect()
    return pred


def rolling_origin_cv(tbl, min_train_days, step_days, link='cloglog'):
    """M222.1: run the ALREADY-SELECTED fiveVarDur spec (not the nested
    ladder search -- that stays blocked-CV-only, unchanged) across
    rolling-origin folds on the same complete-case sample run_ladder uses.
    Reported explicitly ALONGSIDE the existing blocked-day CV, never as a
    replacement (per the enhancement proposal's own framing and this
    project's honest-null discipline): if rolling-origin performance
    degrades relative to blocked-day, that is a finding to report, not a
    result to reconcile away."""
    cc = tbl.dropna(subset=CORE5).reset_index(drop=True)
    spec = DesignSpec(['soc', 'speed', 'tpack', 'demand', 'logdur'], INTERACTIONS)
    rounds = rolling_origin_folds(cc['day'].values, min_train_days, step_days)
    if not rounds:
        return {'nRounds': 0, 'note': 'insufficient distinct days for the '
                'requested minTrainDays/stepDays -- no rounds generated.'}
    p = rolling_origin_predict(cc, spec, rounds, link=link)
    scored = ~np.isnan(p)
    y = cc['y'].values.astype(float)
    metrics = _metrics(y[scored], p[scored]) if scored.any() else None
    ll_lo, ll_hi = day_bootstrap(cc, p, logloss)
    pr_lo, pr_hi = day_bootstrap(cc, p, lambda yv, q: pr_auc(yv, q) or np.nan)
    per_round = []
    for ri, (train_days, val_days) in enumerate(rounds):
        va_mask = np.isin(cc['day'].values, list(val_days)) & scored
        if va_mask.sum() == 0:
            continue
        per_round.append({
            'round': ri, 'nTrainDays': len(train_days), 'nValDays': len(val_days),
            'nValAtRisk': int(va_mask.sum()),
            'nValEvents': int(y[va_mask].sum()),
            'logLoss': round(logloss(y[va_mask], p[va_mask]), 6),
            'brier': round(brier(y[va_mask], p[va_mask]), 6)})
    return {
        'nRounds': len(rounds), 'minTrainDays': min_train_days,
        'stepDays': step_days,
        'nScored': int(scored.sum()), 'nTotal': int(len(cc)),
        'pooled': metrics,
        'pooledLogLossCI': [ll_lo, ll_hi], 'pooledPrAucCI': [pr_lo, pr_hi],
        'perRound': per_round,
        'note': ('Alongside the existing blocked-day CV above, not a '
                'replacement: this is a genuine train-on-past-only '
                '(forward-chaining) evaluation of the SAME already-selected '
                'five-variable duration-aware spec, testing temporal '
                'drift / order-dependence rather than the pseudo-'
                'replication leakage guard blocked-day CV tests. A '
                'materially worse rolling-origin result than the blocked-'
                'day result is reported as a finding, not reconciled away.'),
    }


def _metrics(y, p):
    m = ~np.isnan(p)
    y, p = y[m], p[m]
    slope, icpt = calibration(y, p)
    pa = pr_auc(y, p)
    return {
        'n': int(len(y)), 'events': int(y.sum()),
        'brier': round(brier(y, p), 6),
        'logLoss': round(logloss(y, p), 6),
        'prAuc': (round(pa, 4) if pa is not None else None),
        'calSlope': (round(slope, 3) if slope is not None else None),
        'calIntercept': (round(icpt, 3) if icpt is not None else None),
        'obsEvents': int(y.sum()), 'predEvents': round(float(p.sum()), 1),
    }


# M318: project-standard day-clustered percentile bootstrap (4000 draws, seed 42). The legacy
# defaults (b=300, seed=0) are reachable by setting these module variables (M318 sensitivity S1/R1).
BOOT_B = 4000
BOOT_SEED = 42


def day_bootstrap(tbl, p, fn, b=None, seed=None):
    """Day-clustered bootstrap CI of a scalar metric fn(y,p): resample whole
    days with replacement, recompute on the pooled OOS predictions."""
    b = BOOT_B if b is None else b
    seed = BOOT_SEED if seed is None else seed
    rng = np.random.default_rng(seed)
    y = tbl['y'].values.astype(float)
    days = tbl['day'].values
    valid = ~np.isnan(p)
    by = {}
    for d in pd.unique(days):
        idx = np.where((days == d) & valid)[0]
        if len(idx):
            by[d] = idx
    keys = list(by.keys())
    out = []
    for _ in range(b):
        pick = rng.choice(keys, size=len(keys), replace=True)
        idx = np.concatenate([by[d] for d in pick])
        try:
            out.append(fn(y[idx], p[idx]))
        except Exception:
            pass
    if not out:
        return None, None
    return round(float(np.percentile(out, 2.5)), 5), round(float(np.percentile(out, 97.5)), 5)


def run_ladder(tbl, k=5, link='cloglog'):
    """Fit the four-model ladder under blocked-day CV on the common
    complete-case (5-var) sample; return per-model OOS metrics + day-clustered
    bootstrap CIs on logLoss and prAuc for the headline model."""
    cc = tbl.dropna(subset=CORE5).reset_index(drop=True)
    fold_map = blocked_day_folds(cc['day'].values, k)
    results = {}
    preds = {}
    for name, spec in model_ladder().items():
        p = oos_predict(cc, spec, fold_map, link=link)
        results[name] = _metrics(cc['y'].values.astype(float), p)
        # Memory hygiene (M216): only the headline five-variable model's OOS
        # predictions ('fiveVarDur') and the SoC-only baseline ('socOnly',
        # needed downstream by build_m119v2's socOnlyPrAucCI bootstrap) are
        # kept; the two middle ladder rungs' prediction vectors are dropped
        # as soon as their metrics are recorded. No effect on results[name]
        # (already computed) or on any value read from `preds` elsewhere.
        if name in ('fiveVarDur', 'socOnly'):
            preds[name] = p
        else:
            del p
        gc.collect()
    # bootstrap CIs on the full five-var model
    p5 = preds['fiveVarDur']
    ll_lo, ll_hi = day_bootstrap(cc, p5, logloss)
    pr_lo, pr_hi = day_bootstrap(cc, p5, lambda y, q: pr_auc(y, q) or np.nan)
    results['fiveVarDur']['logLossCI'] = [ll_lo, ll_hi]
    results['fiveVarDur']['prAucCI'] = [pr_lo, pr_hi]
    return {'nSample': int(len(cc)), 'nEvents': int(cc['y'].sum()),
            'nDays': int(cc['day'].nunique()), 'kFolds': k,
            'ladder': results}, cc, fold_map, preds


def sensitivity_screen(tbl, fold_map, candidates, k=5, link='cloglog'):
    """Add each candidate sensitivity variable to the full five-var model, one
    at a time; retain only those that IMPROVE blocked-CV OOS log loss. Returns a
    per-candidate delta table (negative delta = improvement)."""
    cc = tbl.dropna(subset=CORE5).reset_index(drop=True)
    full_terms = ['soc', 'speed', 'tpack', 'demand', 'logdur']
    base_spec = DesignSpec(full_terms, INTERACTIONS)
    base_p = oos_predict(cc, base_spec, fold_map, link=link)
    base_ll = logloss(cc['y'].values.astype(float)[~np.isnan(base_p)],
                      base_p[~np.isnan(base_p)])
    out = []
    for cand in candidates:
        sub = cc.dropna(subset=[cand]).reset_index(drop=True)
        # refit base on the SAME sub-sample so the delta is like-for-like
        fm = blocked_day_folds(sub['day'].values, k)
        bp = oos_predict(sub, base_spec, fm, link=link)
        yv = sub['y'].values.astype(float)
        base_ll_sub = logloss(yv[~np.isnan(bp)], bp[~np.isnan(bp)])
        spec = DesignSpec(full_terms, INTERACTIONS, extra=[cand])
        cp = oos_predict(sub, spec, fm, link=link)
        cand_ll = logloss(yv[~np.isnan(cp)], cp[~np.isnan(cp)])
        out.append({'var': cand, 'nSample': int(len(sub)),
                    'baseLogLoss': round(base_ll_sub, 6),
                    'withVarLogLoss': round(cand_ll, 6),
                    'deltaLogLoss': round(cand_ll - base_ll_sub, 6),
                    'retained': bool(cand_ll < base_ll_sub - 1e-5)})
        # Memory hygiene (M216) -- see oos_predict; each candidate re-runs two
        # full oos_predict passes (2 x k folds), the single largest memory
        # driver in build_m119v2 after run_ladder itself. Pure cleanup, no
        # numeric effect.
        del sub, fm, bp, yv, spec, cp
        gc.collect()
    return {'baseLogLossFullSample': round(base_ll, 6), 'candidates': out}


# ==========================================================================
# final full-data fit, partial dependence, prediction surfaces, JSON assembly
# ==========================================================================
SURF_SOC = list(np.arange(40, 86, 5.0))            # SoC axis (%)
SURF_SPEED = list(np.arange(0, 131, 10.0))         # speed axis (km/h)


def _final_fit(tbl, link='cloglog'):
    """Fit the five-variable duration-aware model on the FULL complete-case
    sample with day-clustered robust covariance; return (result, spec, cc)."""
    cc = tbl.dropna(subset=CORE5).reset_index(drop=True)
    spec = DesignSpec(['soc', 'speed', 'tpack', 'demand', 'logdur'],
                      INTERACTIONS).fit(cc)
    X, names = spec.transform(cc)
    res = fit_glm(X, cc['y'].values.astype(float),
                  groups=cc['day'].values, link=link)
    return res, spec, cc, names


def _partial_dependence(res, spec, cc, which_demand):
    """1-D partial-dependence curves: sweep each predictor across its observed
    range holding the others at their sample median. Returns per-predictor
    lists of {x, p}."""
    med = {c: float(np.nanmedian(cc[c])) for c in ['soc', 'speed', 'tpack',
                                                    'demand', 'durationS']}
    sweeps = {
        'soc': np.linspace(*np.nanpercentile(cc['soc'], [2, 98]), 40),
        'speed': np.linspace(0, float(np.nanpercentile(cc['speed'], 99)), 40),
        'tpack': np.linspace(*np.nanpercentile(cc['tpack'], [2, 98]), 40),
        'demand': np.linspace(0, float(np.nanpercentile(cc['demand'], 98)), 40),
        'durationS': np.linspace(0, float(np.nanpercentile(cc['durationS'], 98)), 40),
    }
    out = {}
    for var, xs in sweeps.items():
        d = pd.DataFrame({k: np.full(len(xs), med[k]) for k in med})
        d[var] = xs
        X, _ = spec.transform(d)
        p = _predict(res, X)
        out[var] = [{'x': round(float(x), 2), 'p': round(float(pi), 6)}
                    for x, pi in zip(xs, p)]
    return out


def _median_profile_caption_stats(pd_block):
    """Compact shape summary of each median-profile (partial-dependence)
    curve -- first point, last point, and the argmin/argmax -- computed
    purely from the already-serialized `partialDependence` curves. Exists so
    dashboard/article captions can bind to S.medianProfileCaptionStats.*
    instead of hand-typed literals (M210); additive and refit-free, so it
    is recomputed correctly whenever partialDependence is (re)built,
    including on a future full M119-v2 refit."""
    out = {}
    for tag in ('start', 'stop'):
        out[tag] = {}
        for var, arr in pd_block[tag].items():
            xs = [d['x'] for d in arr]
            ps = [d['p'] for d in arr]
            imin = min(range(len(ps)), key=lambda i: ps[i])
            imax = max(range(len(ps)), key=lambda i: ps[i])
            out[tag][var] = {
                'x0': xs[0], 'p0': ps[0],
                'xEnd': xs[-1], 'pEnd': ps[-1],
                'xAtMinP': xs[imin], 'minP': ps[imin],
                'xAtMaxP': xs[imax], 'maxP': ps[imax],
            }
    return out


def _support_mask(cc, soc_ax, spd_ax, min_n=20):
    """Count observed at-risk seconds in each SoC x speed cell; 1 = supported
    (n >= min_n), 0 = masked. Cells outside observed support are hidden on the
    dashboard rather than shown as confident extrapolations."""
    soc = cc['soc'].values
    spd = cc['speed'].values
    mask = []
    for si in range(len(soc_ax)):
        row = []
        s_lo = soc_ax[si] - 2.5
        s_hi = soc_ax[si] + 2.5
        for vi in range(len(spd_ax)):
            v_lo = spd_ax[vi] - 5
            v_hi = spd_ax[vi] + 5
            n = int(np.sum((soc >= s_lo) & (soc < s_hi) &
                           (spd >= v_lo) & (spd < v_hi)))
            row.append(1 if n >= min_n else 0)
        mask.append(row)
    return mask


def _surfaces(res, spec, cc, temp_levels=None):
    """SoC x speed transition-probability grids at selectable temperature,
    demand and current-state-duration levels, plus the observed-support mask."""
    # M320: `temp_levels` lets the caller supply the data-driven, support-gated
    # ladder (tools/m320_ladder.py); the legacy fixed literals remain the default
    # so a call without it is byte-identical to the M318 surfaces.
    if temp_levels is None:
        temp_levels = [{'label': 'cool ~20C', 'value': 20.0},
                       {'label': 'warm ~28C', 'value': 28.0},
                       {'label': 'hot ~35C', 'value': 35.0}]
    dq = np.nanpercentile(cc['demand'], [25, 50, 90])
    demand_levels = [{'label': 'low', 'value': round(float(dq[0]), 2), 'pctile': 25},
                     {'label': 'median', 'value': round(float(dq[1]), 2), 'pctile': 50},
                     {'label': 'high', 'value': round(float(dq[2]), 2), 'pctile': 90}]
    dur_levels = [{'label': 'fresh 2s', 'value': 2.0},
                  {'label': 'settled 15s', 'value': 15.0},
                  {'label': 'long 60s', 'value': 60.0}]
    soc_ax, spd_ax = SURF_SOC, SURF_SPEED
    SS, VV = np.meshgrid(soc_ax, spd_ax, indexing='ij')
    flat_soc, flat_spd = SS.ravel(), VV.ravel()
    med_t = float(np.nanmedian(cc['tpack']))
    grids = {}
    for ti, tl in enumerate(temp_levels):
        for di, dl in enumerate(demand_levels):
            for ui, ul in enumerate(dur_levels):
                d = pd.DataFrame({
                    'soc': flat_soc, 'speed': flat_spd,
                    'tpack': np.full(flat_soc.size, tl['value']),
                    'demand': np.full(flat_soc.size, dl['value']),
                    'durationS': np.full(flat_soc.size, ul['value']),
                })
                X, _ = spec.transform(d)
                p = _predict(res, X).reshape(len(soc_ax), len(spd_ax))
                grids['T%d_D%d_U%d' % (ti, di, ui)] = [
                    [round(float(x), 6) for x in row] for row in p]
    return {
        'socAxis': [round(float(x), 1) for x in soc_ax],
        'speedAxis': [round(float(x), 1) for x in spd_ax],
        'tempLevels': temp_levels, 'demandLevels': demand_levels,
        'durationLevels': dur_levels,
        'supportMask': _support_mask(cc, soc_ax, spd_ax),
        'grids': grids,
        'medianTpackC': round(med_t, 1),
    }


# M285 (2026-09-19): the methodology string below is now written CORRECTLY AT
# SOURCE. M179/M258 claimed to have removed the "penalised reduced tensor
# interactions" / "BLOCKED chronological cross-validation" wording from
# assemble(); M264 found the claim had not landed in the file and patched
# only that session's output. Both corrections are now in the string itself,
# and the module-level guard below fails import-time tests (and the
# release check) if either legacy phrase ever reappears.
_METHODOLOGY_FORBIDDEN_PHRASES = (
    'penalised reduced tensor interactions',
    'penalized reduced tensor interactions',
    'BLOCKED chronological cross-validation',
)

_METHODOLOGY_TEXT = (
    'M119-v2 (M147): two SEPARATE 1 Hz discrete-time hazard models -- a '
    'START model on engine-off seconds and a STOP model on engine-on '
    'seconds -- each predicting a canonical debounced transition in the '
    'following second. Five strictly-lagged predictors: SoC (age<=5s), '
    'validated speed (VCM/OBD priority, age<=2s), pack temperature '
    '(mean of >=3 of T1-T4, age<=15s), recent demand (START: median '
    'battery discharge kW over [t-8,t-2]; STOP: median '
    'max(target-torque,0) x speed demand INDEX over [t-5,t-1]) and '
    'log1p(state duration). Complementary-log-log link (discrete-time '
    'hazard); unpenalized fixed-basis GLM with restricted-cubic-spline '
    'smooths f1..f5 and low-degree cross-product interaction terms '
    '(not penalized -- no fit_regularized call, no penalty matrix, no '
    'smoothing-parameter selection anywhere in the fitting code) SoC x '
    'demand, T x demand, SoC x duration. Random-effects disclosure: a full '
    'crossed day x drive binomial GAMM is not tractable on the Python '
    'stack; the additive smooths and interactions are fit exactly, '
    'day/drive dependence is carried by day-clustered robust covariance '
    'for inference and by whole-day GROUPED CONTIGUOUS DAY-BLOCK k-fold '
    'cross-validation (each fold trains on all other blocks, including '
    'later-dated ones -- a leakage guard against same-day pseudo-'
    'replication, not a forward-only / rolling-origin split) for every '
    'reported generalization metric (the operative guard against '
    'treating seconds as independent); a separate forward-chaining '
    'rolling-origin validation is reported under sensitivity.rollingOrigin. '
    'The four-model ladder (SoC only '
    '-> +speed -> four-variable -> full five-variable duration-aware) '
    'improves monotonically on Brier, log loss and PR-AUC for both '
    'models, with day-clustered bootstrap CIs on the five-variable vs '
    'SoC-only PR-AUC that do not overlap -- SoC alone is a weak trigger '
    'predictor once speed, demand, temperature and state duration are '
    'known. Mechanistic sensitivity variables (SoC change since last '
    'transition, accumulated charge since start, engine coolant '
    'temperature, time since key-on) were tested but are not part of '
    'the primary five; only engine-coolant temperature gives a '
    'non-negligible out-of-sample improvement, and for the STOP model '
    'only.')

assert not any(_p.lower() in _METHODOLOGY_TEXT.lower()
               for _p in _METHODOLOGY_FORBIDDEN_PHRASES), \
    'M285 guard: legacy overclaiming methodology wording reintroduced'


def assemble(S, T, ladder_start, ladder_stop, sens_start, sens_stop,
             boot_ci=None, n_drives=None, n_days=None, speed_sources=None):
    """Assemble the full socHysteresisV2 JSON block from the model artefacts."""
    res_s, spec_s, cc_s, names_s = _final_fit(S)
    res_t, spec_t, cc_t, names_t = _final_fit(T)
    if boot_ci:
        if 'start' in boot_ci and 'fiveVarDur' in ladder_start:
            ladder_start['fiveVarDur']['logLossCI'] = boot_ci['start']['logLossCI']
            ladder_start['fiveVarDur']['prAucCI'] = boot_ci['start']['prAucCI']
            ladder_start['socOnly']['prAucCI'] = boot_ci['start']['socOnlyPrAucCI']
        if 'stop' in boot_ci and 'fiveVarDur' in ladder_stop:
            ladder_stop['fiveVarDur']['logLossCI'] = boot_ci['stop']['logLossCI']
            ladder_stop['fiveVarDur']['prAucCI'] = boot_ci['stop']['prAucCI']
            ladder_stop['socOnly']['prAucCI'] = boot_ci['stop']['socOnlyPrAucCI']
    pd_block = {
        'start': _partial_dependence(res_s, spec_s, cc_s, 'dStart'),
        'stop': _partial_dependence(res_t, spec_t, cc_t, 'dStop')}
    block = {
        'link': 'cloglog',
        'nDrivesCovered': n_drives, 'nDays': n_days,
        'speedSources': speed_sources or {},
        'nStartAtRisk': int(len(S)), 'nStartEvents': int(S['y'].sum()),
        'startRatePct': round(float(S['y'].mean()) * 100, 3),
        'nStopAtRisk': int(len(T)), 'nStopEvents': int(T['y'].sum()),
        'stopRatePct': round(float(T['y'].mean()) * 100, 3),
        'detector': {'rpmOff': RPM_OFF, 'rpmOn': RPM_ON,
                     'startOffS': START_OFF_S, 'startOnS': START_ON_S,
                     'stopOffS': STOP_OFF_S,
                     'note': ('One canonical debounced RPM detector (run-'
                              'confirmation, shared definition with the '
                              'M116/M118 engine-start trigger family). A '
                              'transition needs a sustained confirmed run on '
                              'both sides; short dropouts and missing samples '
                              'form no run and are never counted. M231 '
                              '(audit F05): startOffS is now actually '
                              'enforced for START model training -- a '
                              'candidate start is excluded from '
                              'nStartAtRisk/nStartEvents above unless a '
                              'genuinely-observed run of >= startOffS '
                              'contiguous OFF seconds precedes it somewhere '
                              'in the drive (see startDetectorBoundaryAudit '
                              'for the excluded/flagged counts); previously '
                              'startOffS was reported here but never '
                              'actually checked by the detector.')},
        'predictorAges': {'socS': AGE_SOC, 'speedS': AGE_SPEED, 'tempS': AGE_TEMP,
                          'minTempSensors': MIN_TEMP_SENSORS,
                          'demandStartWindowS': [8, 2], 'demandStopWindowS': [5, 1]},
        'ladder': {'start': ladder_start, 'stop': ladder_stop},
        'sensitivity': {'start': sens_start, 'stop': sens_stop},
        'partialDependence': pd_block,
        'medianProfileCaptionStats': _median_profile_caption_stats(pd_block),
        'surfaces': {'start': _surfaces(res_s, spec_s, cc_s),
                     'stop': _surfaces(res_t, spec_t, cc_t)},
        'methodology': _METHODOLOGY_TEXT,
        'disclaimer': (
            'A five-variable, duration-aware observational model of engine '
            'start/stop probability conditional on SoC, speed, pack '
            'temperature, recent demand and elapsed engine-state duration -- '
            'not a reconstruction of Nissan’s proprietary ECU algorithm.'),
    }
    return block


# ==========================================================================
# pipeline entry point
# ==========================================================================
_DAY_KEY_RE = re.compile(r'(\d{4})\D?(\d{2})\D?(\d{2})')


def _day_key(fn):
    """Calendar-day key YYYY-MM-DD from a compact (20260910_074344.csv) or dash
    (2026-09-10_07-43-44.csv) file name. Re-applies the M286 P0-1 fix: the former
    fn[:8] returned '2026-09-' for every dash-format name, merging distinct
    calendar days into one cluster (M318 blind audit)."""
    m = _DAY_KEY_RE.search(str(fn))
    return "%s-%s-%s" % m.groups() if m else str(fn)[:10]


def _corpus_tables(dm, raw_loader=None, raw_dir=None):
    import os as _os
    S, T, cov, srcs = [], [], 0, {}
    # M231 (audit F05): corpus-wide tally of the detect_transitions() start
    # boundary diagnostics, for transparency alongside the trained models.
    diag_totals = {'nStartsRaw': 0, 'nAtGridOrigin': 0,
                   'nNoPriorConfirmedOff': 0, 'nAfterUnknownGap': 0}
    for fn in dm['file']:
        df = None
        if raw_loader is not None:
            try:
                raw = raw_loader(fn)
                head = pd.read_csv(io.BytesIO(raw), nrows=0)
                use = ['time'] + [c for c in _NEEDED if c and c in set(head.columns)]
                if 'time' in head.columns and RPM_COL in head.columns:
                    df = pd.read_csv(io.BytesIO(raw), usecols=use, low_memory=False)
            except Exception:
                df = None
        elif raw_dir is not None:
            df = read_needed(_os.path.join(raw_dir, fn))
        else:
            df = read_needed(fn)
        if df is None:
            continue
        sr, tr, dc = drive_samples(df, fn, _day_key(fn))
        if sr is None and tr is None:
            continue
        g = build_grid(df)
        src = g.attrs.get('speed_source', '?') if g is not None else '?'
        srcs[src] = srcs.get(src, 0) + 1
        cov += 1
        if sr is not None and len(sr):
            S.append(sr)
        if tr is not None and len(tr):
            T.append(tr)
        for k in diag_totals:
            diag_totals[k] += dc.get(k, 0)
        # Memory hygiene (M216): drop the per-drive 1Hz grid/raw frame
        # reference explicitly and force a cyclic-GC pass every 20 files --
        # frequent enough to keep peak RSS bounded across a 320-file corpus,
        # infrequent enough that the gc.collect() overhead is negligible
        # against the per-file CSV-parse cost. No effect on sr/tr contents.
        del df, g
        if cov % 20 == 0:
            gc.collect()
    S = pd.concat(S, ignore_index=True) if S else pd.DataFrame()
    T = pd.concat(T, ignore_index=True) if T else pd.DataFrame()
    return S, T, cov, srcs, diag_totals


def build_m119v2(dm, raw_loader=None, raw_dir=None):
    """Pipeline entry: build corpus tables from raw frames, run the ladder,
    the sensitivity screen and the final fit, and return the socHysteresisV2
    JSON block. Reproduces the milestone artefact from source."""
    S, T, cov, srcs, start_diag_totals = _corpus_tables(
        dm, raw_loader=raw_loader, raw_dir=raw_dir)
    if S.empty or T.empty:
        return {'nDrivesCovered': cov}
    res_s, cc_s, fm_s, pr_s = run_ladder(S, k=5)
    gc.collect()  # M216 memory hygiene: release START ladder's intermediate state before STOP
    res_t, cc_t, fm_t, pr_t = run_ladder(T, k=5)
    gc.collect()
    sens_s = sensitivity_screen(S, fm_s, ['socSince', 'coolant', 'keyOnS'])
    gc.collect()
    sens_t = sensitivity_screen(T, fm_t, ['socSince', 'accumChgKwh', 'coolant', 'keyOnS'])
    gc.collect()
    boot = {
        'start': {'logLossCI': res_s['ladder']['fiveVarDur']['logLossCI'],
                  'prAucCI': res_s['ladder']['fiveVarDur']['prAucCI'],
                  'socOnlyPrAucCI': day_bootstrap(
                      cc_s, pr_s['socOnly'], lambda y, q: pr_auc(y, q) or np.nan)},
        'stop': {'logLossCI': res_t['ladder']['fiveVarDur']['logLossCI'],
                 'prAucCI': res_t['ladder']['fiveVarDur']['prAucCI'],
                 'socOnlyPrAucCI': day_bootstrap(
                     cc_t, pr_t['socOnly'], lambda y, q: pr_auc(y, q) or np.nan)},
    }
    out = assemble(S, T, res_s['ladder'], res_t['ladder'],
                   sens_s['candidates'], sens_t['candidates'],
                   boot_ci=boot, n_drives=cov, n_days=int(S['day'].nunique()),
                   speed_sources=srcs)
    if isinstance(out, dict):
        # M231 (audit F05): corpus-wide start-boundary diagnostics, computed
        # from the SAME _corpus_tables pass already used to fit the models
        # above (no second raw pass). nNoPriorConfirmedOff of these were
        # excluded from START model training (see drive_samples); the
        # remainder (afterUnknownGap only) were retained as confirmed
        # positives with a timing caveat.
        out['startDetectorBoundaryAudit'] = {
            **start_diag_totals,
            'nExcludedFromTraining': start_diag_totals['nNoPriorConfirmedOff'],
            'note': ('M231 (audit F05): detect_transitions() previously '
                     'assumed the engine OFF at the grid origin and let any '
                     'confirmed running run flip the state machine '
                     'regardless of whether the documented >= '
                     f'{START_OFF_S}s prior-OFF rule was actually observed, '
                     'or whether the OFF label was only being held across '
                     'an unresolved data gap. These are now explicit, '
                     'non-exclusive diagnostic categories over the '
                     f'{start_diag_totals["nStartsRaw"]} raw confirmed '
                     'starts in this corpus: atGridOrigin (a strict subset '
                     'of noPriorConfirmedOff -- no data exists before the '
                     'recording began), noPriorConfirmedOff (the >=3s '
                     'prior-off rule was never actually satisfied by an '
                     'observed run -- excluded from START model training as '
                     'an unverifiable label, not relabeled as a negative), '
                     'and afterUnknownGap (the prior OFF confirmation is '
                     'genuine, but an unobserved intermediate stop/start '
                     'inside the immediately-preceding data gap cannot be '
                     'ruled out -- retained as a confirmed positive with '
                     'this timing caveat disclosed).')}
    return out


def rolling_origin_validation(dm, raw_loader=None, raw_dir=None,
                              min_train_days=40, step_days=5):
    """M222.1 entry point: builds the corpus at-risk tables (the SAME
    _corpus_tables pass build_m119v2 itself uses -- not a second, different
    extraction) and runs rolling_origin_cv for both the START and STOP
    tables against the already-selected fiveVarDur spec. Returns
    {'start': ..., 'stop': ...} for socHysteresisV2.sensitivity.rollingOrigin,
    or None if the corpus tables come back empty. Independent of
    build_m119v2()'s own recompute-on-demand gate: this is a validation
    exercise re-fitting one fixed spec across folds, not a re-run of the
    nested ladder search, and can be (and was, M222) run and attached to
    an otherwise-carried-forward socHysteresisV2 block without refitting
    the model itself."""
    S, T, cov, srcs, _start_diag_totals = _corpus_tables(
        dm, raw_loader=raw_loader, raw_dir=raw_dir)
    if S.empty or T.empty:
        return None
    ro_start = rolling_origin_cv(S, min_train_days, step_days)
    gc.collect()
    ro_stop = rolling_origin_cv(T, min_train_days, step_days)
    gc.collect()
    return {'start': ro_start, 'stop': ro_stop}
