import os, sys, pickle, json
import numpy as np, pandas as pd

MASS = {'highway': 2000.0, 'mixed_highway': 2000.0, 'urban': 1890.0, 'mixed': 1890.0}
FALLBACK = 1950.0
TEMP_BINS = [(-99, -10, "<-10"), (-10, 0, "-10-0"), (0, 10, "0-10"), (10, 20, "10-20"), (20, 30, "20-30"),
             (30, 40, "30-40"), (40, 50, "40-50"), (50, 99, "50+")]
SOC_EDGES = [40, 50, 55, 60, 63, 66, 69, 72, 100]
K = 0.5 / 12.96 / 3.6e6      # kWh per (km/h)^2 per kg


def load(cache):
    m = pd.read_csv('drive_master.csv', usecols=['file', 'date', 'drive_type'])
    out = {}
    for _, r in m.iterrows():
        d = pickle.load(open(os.path.join(cache, r.file + '.pkl'), 'rb'))
        d['mass'] = MASS.get(r.drive_type, FALLBACK)
        d['date'] = r.date
        d['dtype'] = r.drive_type
        out[r.file] = d
    return out


def per_drive_table(D):
    rows = []
    for f, d in D.items():
        iv = d.get('iv')
        row = {'file': f, **{k: v for k, v in d['excl'].items()}}
        if iv is None or len(iv) == 0:
            row.update(nStrict=0, nPlateauKept=0, nTrimmedPlateau=0, chargeKwhKept=0.0, dv2Kept=0.0)
        else:
            kd = iv.kind
            kept = iv[kd < 2]
            row.update(nStrict=int((kd == 0).sum()), nPlateauKept=int((kd == 1).sum()), nTrimmedPlateau=int((kd == 2).sum()),
                       chargeKwhKept=float(kept.charge.sum()), dv2Kept=float(kept.dv2.sum()))
        rows.append(row)
    return pd.DataFrame(rows)


def kept_all(D):
    """returns (DataFrame of strict+kept plateau intervals, BD2, BCH, TOUCH arrays) and trimmed DataFrame"""
    fr = []; B2 = []; BC = []; TT = []; trim = []
    for f, d in D.items():
        iv = d.get('iv')
        if iv is None or len(iv) == 0:
            continue
        sel = (iv.kind < 2).to_numpy()
        x = iv[sel].copy()
        x['file'] = f; x['date'] = d['date']; x['mass'] = d['mass']
        x['ke'] = x.dv2 * K * d['mass']
        fr.append(x); B2.append(d['bin_dv2'][sel]); BC.append(d['bin_ch'][sel]); TT.append(d['touched'][sel])
        t = iv[~sel].copy(); t['file'] = f; trim.append(t)
    X = pd.concat(fr, ignore_index=True)
    return X, np.vstack(B2), np.vstack(BC), np.vstack(TT), pd.concat(trim, ignore_index=True)
