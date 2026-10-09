"""M394 (analyses/M394_spec.md): unfuelled (motored) engine-spin events, shared by the ingestion monitor and its tests. Library, no side effects.

Physics context (compute_summary_arrays._dissipation_census, M46): in the series-hybrid architecture the ICE couples only to the generator. When the pack cannot accept surplus energy the VCM can
dump it by MOTORING the engine through the generator: the engine is spun UNFUELLED (throttle closed, deep intake vacuum, calculated load ~0) at elevated rpm. A cold pack accepts less charge, so
this mode is expected to become more frequent in winter (hypothesis from the architecture, NOT yet observed: no drive below 10 C has a sustained event).

Two detectors on the 1 s grid (thresholds fixed, not tuned):
  PUB  = rpm > 2000 and boost < -0.70 (MAP ~ < 25 kPa) and calc load < 8          the published census classifier (needs rpm, boost, load, soc)
  FUEL = rpm > 1200 and logged fuel rate < 0.2 L/h and absolute throttle B < 10 %  independent indicator (app-calculated fuel rate; only the 60-column logging generation)
An EVENT is a run of >= 3 consecutive true seconds. SUSTAINED = duration >= 10 s and |rpm slope| < 30 rpm/s: not an engine start / stop transient (FUEL alone fires on spin-up and
spin-down: in the 2026-10 cross-check 80 FUEL-only events had a median duration of 5 s and 69 % falling rpm). Fuel rate / engine power are app-calculated: say 'logged', never 'measured'. Event duration counts grid rows after dropping rows with a missing needed channel. The FUEL events seen so far
sit at 1520-1736 rpm (just above the ~1500 rpm generator floor): they are 'fuel-indicated unfuelled spin' (logged fuel < 0.2 L/h, throttle < 10 %); low-power fuelled generation with a
quantised fuel rate is not ruled out, and the SUSTAINED test is the only guard at the floor."""
import io
import numpy as np
import pandas as pd

RPM_PUB, BOOST_PUB, LOAD_PUB = 2000.0, -0.70, 8.0
RPM_FUEL, FUEL_MAX_LH, THR_MAX_PCT = 1200.0, 0.2, 10.0
EVENT_MIN_S, SUSTAINED_MIN_S, SUSTAINED_SLOPE = 3, 10, 30.0
COLS = {'[BMS] HV Battery Current (A)': 'I', '[BMS] HV State of charge (%)': 'soc', '[VCM] Vehicle Speed (km/h)': 'speed',
        'Оберти двигуна (rpm)': 'rpm', 'Розрахункове значення навантаження на двигун (%)': 'load', 'Розрахунковий наддув (bar)': 'boost',
        'Миттєва витрата палива (л/год) (L/h)': 'fuel', 'Абсолютне положення дросельної заслінки B (%)': 'thr'}
PUB_CHANNELS = ('rpm', 'boost', 'load', 'soc')


def grid_from_csv_bytes(b):
    """1 s mean grid of the channels used here, or None. Same resampling as the census (mean, forward fill of at most 3 s). The bins are aligned to the wall-clock second of the
    time-of-day index (pandas resample), NOT to the first row: event counts depend on this phase (M394 audit: 22 vs 24 census events with first-row bins)."""
    df = pd.read_csv(io.BytesIO(b), usecols=lambda c: c in COLS or c == 'time', low_memory=False)
    if 'time' not in df.columns:
        return None
    t = pd.to_timedelta(df['time'], errors='coerce')
    ok = t.notna().to_numpy()
    if ok.sum() < 3:
        return None
    g = df.loc[ok].drop(columns=['time']).rename(columns=COLS).apply(pd.to_numeric, errors='coerce')
    g.index = pd.Timestamp('1900-01-01') + t[ok]
    return g.resample('1s').mean().ffill(limit=3)


def channels(g):
    return sorted(c for c in COLS.values() if g is not None and c in g.columns and g[c].notna().any())


def _runs(mask):
    m = np.asarray(mask, dtype=bool)
    i = 0
    while i < len(m):
        if m[i]:
            j = i
            while j + 1 < len(m) and m[j + 1]:
                j += 1
            yield i, j
            i = j + 1
        else:
            i += 1


def detect(g, kind):
    """Events of kind 'PUB' or 'FUEL' on the grid g. Returns a list of dicts (t0 = seconds from the grid start). A detector whose channels are missing returns None (not evaluable)."""
    if g is None:
        return None
    if kind == 'PUB':
        if not all(c in g.columns and g[c].notna().any() for c in PUB_CHANNELS):
            return None
        d = g.dropna(subset=['rpm', 'boost', 'soc'])
        mask = ((d['rpm'] > RPM_PUB) & (d['boost'] < BOOST_PUB) & (d['load'].fillna(0) < LOAD_PUB)).to_numpy()
    else:
        if not all(c in g.columns and g[c].notna().any() for c in ('rpm', 'fuel', 'thr', 'soc')):
            return None
        d = g.dropna(subset=['rpm', 'fuel', 'thr', 'soc'])
        mask = ((d['rpm'] > RPM_FUEL) & (d['fuel'] < FUEL_MAX_LH) & (d['thr'] < THR_MAX_PCT)).to_numpy()
    out = []
    t0 = d.index[0] if len(d) else None
    for i, j in _runs(mask):
        n = j - i + 1
        if n < EVENT_MIN_S:
            continue
        seg = d.iloc[i:j + 1]
        slope = float(np.polyfit(np.arange(n), seg['rpm'].to_numpy(), 1)[0]) if n >= 3 else 0.0
        out.append({'t0_s': float((seg.index[0] - t0).total_seconds()), 'dur_s': int(n), 'rpm_mean': round(float(seg['rpm'].mean()), 1), 'rpm_slope_per_s': round(slope, 2),
                    'soc_mean': round(float(seg['soc'].mean()), 1),
                    'speed_mean': round(float(seg['speed'].mean()), 1) if 'speed' in seg and seg['speed'].notna().any() else None,
                    'I_mean': round(float(seg['I'].mean()), 1) if 'I' in seg and seg['I'].notna().any() else None,
                    'fuel_mean': round(float(seg['fuel'].mean()), 2) if 'fuel' in seg and seg['fuel'].notna().any() else None,
                    'sustained': bool(n >= SUSTAINED_MIN_S and abs(slope) < SUSTAINED_SLOPE)})
    return out


def overlaps(a, b):
    return a['t0_s'] < b['t0_s'] + b['dur_s'] and b['t0_s'] < a['t0_s'] + a['dur_s']
