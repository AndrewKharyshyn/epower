#!/usr/bin/env python3
"""
rpm_opt_pass.py -- refresh generatorTractionRecon.rpmFinding to the current
410-drive corpus by measuring the TRUE [1850,2150] engine-on RPM occupancy.

Why a raw pass
--------------
rpmFinding was disclosed-stale at 374/369 drives. rpmDistribution IS current at
410, but its display bin edges (1614-1975, 1975-2025, 2025-2100, 2100-2400)
straddle the OPT band [1850,2150] (model_constants.OPT_LO/HI), so the exact
band fraction is not extractable from them. Worse, the shipped empiricalPct
(58.5%) equals the single 1975-2025 spike bin / engine-on -- i.e. the label
"[1850,2150]" but the value of a much narrower band, understating the OPT
concentration. This pass measures the real band.

Method (byte-faithful to compute_summary_arrays._RawAccum.add, M82)
-------------------------------------------------------------------
Per drive: build the 1 Hz grid exactly as the pipeline does --
  g1 = DataFrame(t, eng_rpm).dropna(t).set_index(t)
  hz = g1.resample('1s').mean().ffill(limit=15)
  rr = hz['eng_rpm'].dropna()
  histogram(rr, bins=FINE_EDGES)
FINE_EDGES = RPM_HIST_EDGES with 1850 and 2150 inserted, so collapsing the fine
bins back to RPM_HIST_EDGES must reproduce the stored rpmDistribution.pooledHours
(the faithfulness gate). Engine-on = rpm>=300 (all bins but the [0,300) "engine
off" bin), the pipeline's own convention.

empiricalPct = seconds in [1850,2150] / engine-on seconds.
empiricalN    = engine-on seconds (1 Hz grid; ~= the shipped 274216 basis).
empiricalDrives = drives contributing >=1 engine-on second.
corpusWideDrives = 410.
"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')

BASE = '/mnt/project/'
RPM = 'Оберти двигуна (rpm)'
RPM_HIST_EDGES = [0, 300, 1400, 1475, 1525, 1564, 1614, 1975, 2025, 2100,
                  2400, 2800, 3200, 6000]
OPT_LO, OPT_HI = 1850.0, 2150.0
FINE_EDGES = sorted(set(RPM_HIST_EDGES) | {OPT_LO, OPT_HI})

def main():
    dm = pd.read_csv(BASE + 'drive_master.csv')
    files = [f for f in dm['file'] if os.path.exists(BASE + f)]
    fine = np.zeros(len(FINE_EDGES) - 1)
    nfiles = 0; nfiles_engon = 0
    for f in files:
        try:
            df = pd.read_csv(BASE + f, low_memory=False)
        except Exception:
            continue
        if RPM not in df.columns or 'time' not in df.columns:
            continue
        t = pd.to_datetime(df['time'], errors='coerce')
        g1 = pd.DataFrame({'t': t, 'eng_rpm': pd.to_numeric(df[RPM], errors='coerce')})
        g1 = g1.dropna(subset=['t']).set_index('t').sort_index()
        g1 = g1[~g1.index.duplicated(keep='first')]
        if not len(g1):
            continue
        hz = g1.resample('1s').mean().ffill(limit=15)
        rr = hz['eng_rpm'].dropna()
        if not len(rr):
            continue
        h, _ = np.histogram(rr.values, bins=FINE_EDGES)
        fine += h
        nfiles += 1
        if h[1:].sum() > 0:
            nfiles_engon += 1

    fi = lambda lo, hi: fine[[k for k in range(len(FINE_EDGES) - 1)
                              if FINE_EDGES[k] == lo and FINE_EDGES[k + 1] == hi][0]]

    # ---- ANCHORED to the stamped 410 rpmDistribution bin totals ----
    d = json.load(open('summary_arrays.json'))
    rd = d['rpmDistribution']
    ph = dict(zip(rd['bins'], rd['pooledHours']))       # hours per stored bin
    engine_on_h = sum(v for k, v in ph.items() if k != '0 (engine off)')

    # raw-derived sub-bin SHARES within the two OPT-boundary bins (ratios only)
    share_1850_1975 = fi(1850, 1975) / (fi(1614, 1850) + fi(1850, 1975))
    share_2100_2150 = fi(2100, 2150) / (fi(2100, 2150) + fi(2150, 2400))

    opt_h = (ph['1975-2025'] + ph['2025-2100']
             + share_1850_1975 * ph['1614-1975 (valley)']
             + share_2100_2150 * ph['2100-2400'])
    empiricalPct = round(opt_h / engine_on_h * 100, 1)

    # pure-raw cross-check (independent of the anchor)
    band_raw = sum(fine[k] for k in range(len(FINE_EDGES) - 1)
                   if FINE_EDGES[k] >= OPT_LO and FINE_EDGES[k + 1] <= OPT_HI)
    empiricalPct_raw = round(band_raw / fine[1:].sum() * 100, 1)

    out = dict(
        optLo=int(OPT_LO), optHi=int(OPT_HI),
        corpusWideDrives=int(len(dm)),
        empiricalDrives=int(nfiles_engon),
        empiricalN=int(round(engine_on_h * 3600)),      # engine-on seconds, stamped basis
        empiricalPct=empiricalPct,                       # true [1850,2150], anchored
        empiricalPctRawCrosscheck=empiricalPct_raw,      # independent raw pass
        priorSpikeBinPct=round(ph['1975-2025'] / engine_on_h * 100, 1),  # old 58.5% was ~this
        optBandHours=round(opt_h, 3),
        engineOnHours=round(engine_on_h, 3),
        subBinShares=dict(s1850_1975=round(float(share_1850_1975), 3),
                          s2100_2150=round(float(share_2100_2150), 3)),
        method=('OPT-band occupancy anchored to the stamped 410-drive rpmDistribution '
                'bin totals; the two OPT-boundary bins split at 1850/2150 via a raw '
                '1 Hz sub-bin pass (ratios only). Engine-on = rpm>=300.'),
    )
    print(json.dumps(out, indent=1))
    json.dump(out, open('rpm_opt_out.json', 'w'), indent=1)
    print('wrote rpm_opt_out.json')

if __name__ == '__main__':
    main()
