#!/usr/bin/env python3
"""M638 (implements analyses/M638_spec.md Rev 1, W1-08 part 2 / owner decision D-03): sample-resolved logged-time occupancy of the pack temperature.

E2 = (seconds with mean pack-probe reading >= t) / (seconds with a supported reading), pooled over drives, a ratio of sums.
Supported second: a 2 s midpoint-grid time (t0 + 1, t0 + 3, ...) at which at least 3 of the 4 pack probe channels have a reading no older than 45 s (sample and hold).
Pack temperature at that time = mean of the available probes. A reading equal to t counts as at or above t. Uncertainty: calendar-day-clustered percentile bootstrap
(seed 42, 4000 draws) recomputing the ratio of sums. The drive-average estimand E1 (driveTimeShareGeC) is not touched and has no interval.
Never edits raw files. Library functions here; the splice entry point is main()."""
import io, json, os, sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

PROBE_COLS = ['[BMS] HV Battery Temperature Sensor %d (℃)' % i for i in (1, 2, 3, 4)]
THRESH = (30, 35, 40)
GRID_S, HOLD_S, MIN_PROBES = 2.0, 45.0, 3


def hold(t, v, x, maxage):
    """Sample-and-hold of (t, v) at times x: last reading at or before x, NaN if older than maxage seconds or none yet."""
    j = np.searchsorted(t, x, side='right') - 1
    ok = j >= 0
    j = j.clip(0)
    out = v[j].astype(float)
    out[~ok | ((x - t[j]) > maxage)] = np.nan
    return out


def drive_occupancy(t_s, probes, grid=GRID_S, maxage=HOLD_S, min_probes=MIN_PROBES, use_max=False):
    """t_s: sample times in seconds (sorted); probes: list of (t, v) arrays per available channel. Returns per-drive seconds, or None if fewer than min_probes channels."""
    if len(probes) < min_probes or len(t_s) < 2:
        return None
    g = np.arange(t_s[0] + grid / 2.0, t_s[-1], grid)
    if not len(g):
        return None
    M = np.vstack([hold(pt, pv, g, maxage) for pt, pv in probes])
    nf = np.isfinite(M).sum(0)
    ok = nf >= min_probes
    out = {'supS': float(ok.sum() * grid), 'driveS': float(t_s[-1] - t_s[0]), 'nProbes': len(probes)}
    if not ok.any():
        return dict(out, **{'ge%d' % t: 0.0 for t in THRESH})
    Mo = M[:, ok]
    pm = np.nanmax(Mo, axis=0) if use_max else np.nanmean(Mo, axis=0)
    for t in THRESH:
        out['ge%d' % t] = float((pm >= t).sum() * grid)
    return out


def extract(csv_bytes, **kw):
    """Per-drive result from raw CSV bytes (header-selected probe columns); None if unusable. Adds the minimum nonzero reading step of the probes (resolution)."""
    import compute_summary_arrays as C
    try:
        head = pd.read_csv(io.BytesIO(csv_bytes), nrows=0).columns
    except Exception:
        return None
    cols = [c for c in PROBE_COLS if c in head]
    if len(cols) < MIN_PROBES:
        return {'excluded': 'fewer than %d pack probe channels in the header (%d)' % (MIN_PROBES, len(cols))}
    df = pd.read_csv(io.BytesIO(csv_bytes), usecols=['time'] + cols, low_memory=False)
    ts = C._ft(df['time'], mixed=True)
    t = (ts - ts.iloc[0]).dt.total_seconds().to_numpy()
    probes = []
    step = None
    for c in cols:
        v = pd.to_numeric(df[c], errors='coerce').to_numpy()
        m = np.isfinite(v) & np.isfinite(t)
        if m.sum() < 2:
            continue
        probes.append((t[m], v[m]))
        u = np.unique(v[m])
        if len(u) > 1:
            d = float(np.diff(u).min())
            step = d if step is None else min(step, d)
    r = drive_occupancy(t[np.isfinite(t)], probes, **kw)
    if r is None:
        return {'excluded': 'fewer than %d usable probe channels after parsing' % MIN_PROBES}
    r['step'] = step
    return r


def ratio_and_ci(rows, key, nb=4000, seed=42):
    """Pooled ratio of sums sum(key)/sum(supS) over rows, with the day-clustered percentile bootstrap (resample calendar days, recompute the ratio of sums)."""
    days = np.array([r['day'] for r in rows])
    num = np.array([r[key] for r in rows], float)
    den = np.array([r['supS'] for r in rows], float)
    point = float(num.sum() / den.sum())
    uniq = np.unique(days)
    if uniq.size < 3:
        return point, None
    dn = np.array([num[days == d].sum() for d in uniq])
    dd = np.array([den[days == d].sum() for d in uniq])
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(uniq), (nb, len(uniq)))
    boot = dn[idx].sum(1) / dd[idx].sum(1)
    return point, [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]


def summarise(rows, excluded, nb=4000, seed=42):
    ok = [r for r in rows if r['supS'] > 0]
    out = {'thresholdsC': list(THRESH), 'share': {}, 'ci95': {}, 'draws': nb, 'seed': seed, 'cluster': 'calendar day'}
    for t in THRESH:
        p, ci = ratio_and_ci(ok, 'ge%d' % t, nb, seed)
        out['share'][str(t)] = round(p, 4)
        out['ci95'][str(t)] = [round(ci[0], 4), round(ci[1], 4)] if ci else None
    out['supportedHours'] = round(sum(r['supS'] for r in ok) / 3600.0, 1)
    out['driveHours'] = round(sum(r['driveS'] for r in rows) / 3600.0, 1)
    out['coverageShare'] = round(sum(r['supS'] for r in ok) / sum(r['driveS'] for r in rows), 4)
    out['nDrives'] = len(ok)
    out['nDays'] = len({r['day'] for r in ok})
    out['nExcludedDrives'] = len(excluded)
    out['excludedReasons'] = sorted({e for e in excluded})
    steps = [r['step'] for r in ok if r.get('step')]
    out['probeResolutionC'] = round(float(min(steps)), 3) if steps else None
    return out


def run(dm, raw_loader, eligibility='canonical', **kw):
    """eligibility 'canonical' = ens_outlier_v2 false (production); 'all' = every master row (audit-emulation mode, known-answer only)."""
    d = dm if eligibility == 'all' else dm[~dm['ens_outlier_v2'].astype(bool)]
    rows, excluded = [], []
    for fn, day in zip(d['file'], d['date']):
        r = extract(raw_loader(fn), **kw)
        if r is None or 'excluded' in r:
            excluded.append((r or {}).get('excluded', 'unreadable file'))
            continue
        r['day'] = str(day)
        r['file'] = fn
        rows.append(r)
    return rows, excluded


RULE = ('2 s midpoint grid; supported when at least 3 of the 4 pack probe channels (' + '; '.join(PROBE_COLS) + ') hold a reading no older than 45 s '
        '(sample and hold); pack temperature = mean of the available probes; a reading equal to the threshold counts as at or above it; pooled ratio of sums over canonical-clean drives')
MEANING = ('Share of logged drive time (supported seconds) with a mean pack-probe reading at or above the threshold (sample-resolved). Logged BMS sensor readings (an occupancy of logged readings, not an exposure measurement). '
           'A different estimand from driveTimeShareGeC (share of drive time in drives whose drive-average pack temperature is at or above the threshold), which carries no interval. '
           'Read the two side by side; neither stands alone as a hot-tail figure (M638, self-audit W1-08, owner decision D-03).')


def build_block(dm, raw_loader, nb=4000):
    rows, excl = run(dm, raw_loader)
    blk = summarise(rows, excl, nb)
    blk['rule'] = RULE
    blk['meaning'] = MEANING
    sens = {}
    for name, kw in (('hold30s', {'maxage': 30.0}), ('hold60s', {'maxage': 60.0}), ('grid1s', {'grid': 1.0}), ('all4probes', {'min_probes': 4}), ('hottestProbe', {'use_max': True})):
        r2, e2 = run(dm, raw_loader, **kw)
        s2 = summarise(r2, e2, nb)
        sens[name] = {'share': s2['share'], 'supportedHours': s2['supportedHours'], 'nDrives': s2['nDrives']}
    blk['sensitivities'] = sens
    return blk, rows


def main(argv):
    import copy
    dry = '--dry-run' in argv
    dm = pd.read_csv(os.path.join(ROOT, 'drive_master.csv'), low_memory=False)

    def loader(fn):
        with open(os.path.join(ROOT, 'raw_only', fn), 'rb') as f:
            return f.read()

    # known-answer, mode (i): audit emulation over all master rows must reproduce the self-audit scan within 0.2 pp / 1 h
    ra, ea = run(dm, loader, eligibility='all')
    sa = summarise(ra, ea, nb=200)
    ka = {'allRows': {'share35': sa['share']['35'], 'share40': sa['share']['40'], 'supportedHours': sa['supportedHours']},
          'target': {'share35': 0.3897, 'share40': 0.1045, 'supportedHours': 237.5}}
    ok = abs(sa['share']['35'] - 0.3897) <= 0.002 and abs(sa['share']['40'] - 0.1045) <= 0.002 and abs(sa['supportedHours'] - 237.5) <= 1.0
    ka['pass'] = bool(ok)
    print(json.dumps(ka))
    if not ok:
        print('STOP: known-answer mismatch (spec section 3 R1); nothing written')
        return 3
    blk, rows = build_block(dm, loader)
    blk['knownAnswer'] = {'auditEmulationAllRows': ka['allRows'], 'target': ka['target'], 'productionCanonicalCleanDelta': {
        'share35': round(blk['share']['35'] - ka['allRows']['share35'], 4), 'share40': round(blk['share']['40'] - ka['allRows']['share40'], 4)},
        'attribution': 'eligibility (canonical-clean versus all master rows) and loader (repository frame reader versus the audit scan reader)'}
    print(json.dumps(blk, indent=1)[:3000])
    if dry:
        return 0
    p = os.path.join(ROOT, 'summary_arrays.json')
    raw = open(p, encoding='utf-8', newline='').read()
    A = json.loads(raw)
    B = copy.deepcopy(A)
    B['seasonalLife']['hotTail']['packThermalMeasured']['sampleOccupancy'] = blk
    open(p, 'w', encoding='utf-8', newline='').write(json.dumps(B, ensure_ascii=False, indent=1) + ('\n' if raw.endswith('\n') else ''))
    print('written')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
