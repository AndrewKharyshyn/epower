"""M457 inventory of the BMS possible-power channels in raw/ (coverage, unit label and value range per file; no outcome statistic). Output: mf_inventory.csv next to this script.
Usage: python analyses/M457_inventory/mf_inventory.py"""
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

CH = {'inHp': '[BMS] Input possible power (hp)', 'outHp': '[BMS] Output possible power (hp)', 'inKw': '[BMS] Input possible power (kW)', 'outKw': '[BMS] Output possible power (kW)',
      'inShort': '[BMS] Input possible power (Short) (hp)', 'g07': 'G07 BMS Power Limits ()', 'regMax': '[VCM] Motor Regenerable Power Maximum (%)'}
dm = pd.read_csv('drive_master.csv', low_memory=False)
canon = {CM._canonical(str(f)) for f in dm['file']}
rows = []
for f in sorted(glob.glob('raw/*.csv')):
    try:
        h = pd.read_csv(f, nrows=0, encoding='utf-8-sig').columns.str.strip().tolist()
    except Exception:
        continue
    has = {k: (v in h) for k, v in CH.items()}
    r = dict(file=os.path.basename(f), canonical=CM._canonical(os.path.basename(f)) in canon, unit=None)
    for k in ('inHp', 'inKw', 'inShort'):
        if has[k]:
            r['unit'] = {'inHp': 'hp', 'inKw': 'kW', 'inShort': 'hpShort'}[k]
            d = pd.read_csv(f, usecols=lambda c, v=CH[k]: c.strip() == v, encoding='utf-8-sig')
            x = pd.to_numeric(d.iloc[:, 0], errors='coerce')
            r.update(n=int(x.notna().sum()), p50=float(x.median()) if x.notna().any() else None, vmin=float(x.min()) if x.notna().any() else None, vmax=float(x.max()) if x.notna().any() else None)
    r['hasG07'], r['hasRegMax'] = has['g07'], has['regMax']
    rows.append(r)
df = pd.DataFrame(rows)
df.to_csv(os.path.join(HERE, 'mf_inventory.csv'), index=False)
print(df['unit'].value_counts(dropna=False).to_dict())
for u in ('hp', 'kW', 'hpShort'):
    s = df[df.unit == u]
    if len(s):
        print(u, 'files', len(s), 'canonical', int(s.canonical.sum()), 'min of vmin', s.vmin.min(), 'max of vmax', s.vmax.max(), 'median of vmax', round(s.vmax.median(), 3))
