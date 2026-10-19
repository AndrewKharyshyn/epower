"""M460 data-health inventory of the logged fuel-rate channel (no outcome statistic: no engine-state cross-tab, no distance share).
Per raw file with the channel 'Витрати палива (L/h)': number of samples, share of NaN, smallest positive value, number of distinct values, median sampling interval; the fuel counter 'Використане паливо (L)' present or not.
Output: fuel_channel_health.csv next to this script.  Usage: python analyses/M460_inventory/fuel_channel_health.py"""
import glob
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
import corpus_manifest as CM

FLOW, USED, TIME = 'Витрати палива (L/h)', 'Використане паливо (L)', 'time'
dm = pd.read_csv('drive_master.csv', low_memory=False)
canon = {CM._canonical(str(f)) for f in dm['file']}
rows = []
for f in sorted(glob.glob('raw/*.csv')):
    base = os.path.basename(f)
    try:
        h = pd.read_csv(f, nrows=0, encoding='utf-8-sig').columns.str.strip().tolist()
    except Exception:
        continue
    r = dict(file=base, canonical=CM._canonical(base) in canon, hasFlow=FLOW in h, hasUsed=USED in h)
    if FLOW in h:
        d = pd.read_csv(f, usecols=lambda c: c.strip() in (FLOW, USED, TIME), encoding='utf-8-sig')
        d.columns = d.columns.str.strip()
        x = pd.to_numeric(d[FLOW], errors='coerce')
        pos = x[x > 0]
        t = pd.to_datetime(d[TIME], errors='coerce')
        xt = t[x.notna()]
        dtm = xt.diff().dt.total_seconds().median() if len(xt) > 2 else np.nan
        r.update(nFlow=int(x.notna().sum()), nRows=int(len(d)), shareZero=float((x == 0).sum() / max(x.notna().sum(), 1)), minPositive=float(pos.min()) if len(pos) else np.nan,
                 nDistinct=int(x.nunique()), maxFlow=float(x.max()) if x.notna().any() else np.nan, medianDtS=float(dtm) if dtm == dtm else np.nan)
    rows.append(r)
df = pd.DataFrame(rows)
df.to_csv(os.path.join(HERE, 'fuel_channel_health.csv'), index=False)
s = df[df.hasFlow]
print('files with the fuel-rate channel:', len(s), 'canonical:', int(s.canonical.sum()), 'of', len(canon), '| with the fuel counter:', int(s.hasUsed.sum()))
print('minPositive (file medians):', s.minPositive.describe()[['min', '50%', 'max']].round(4).to_dict())
print('nDistinct (file medians):', s.nDistinct.describe()[['min', '50%', 'max']].to_dict())
print('median sampling interval s (file medians):', s.medianDtS.describe()[['min', '50%', 'max']].round(3).to_dict())
print('first / last dates with the channel:', sorted(s.file)[0], sorted(s.file)[-1])
