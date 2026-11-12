"""M623 known-answer tests (spec analyses/M623_spec.md Rev 1 section 3 and R8): aux-load ambient bins and the warm-up curve time cap."""
import os, sys
import numpy as np, pandas as pd
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, REPO)
import compute_summary_arrays as C

# D1: edges, labels, NaN
labs = C._aux_bin_labels()
assert labs == ['<5', '5-10', '10-15', '15-20', '20-25', '25-30', '>=30'], labs
x = [4.9, 5.0, 9.9, 10.0, 14.9, 15.0, 29.9, 30.0, 45.0, float('nan')]
got = [labs[i] if i >= 0 else None for i in C._aux_bin_index(x)]
assert got == ['<5', '5-10', '5-10', '10-15', '10-15', '15-20', '25-30', '>=30', '>=30', None], got

# D1: sentence branches
def B(lab, n, d, med): return {'ambientBinC': lab, 'n': n, 'nDays': d, 'medianKw': med}
inc = C._aux_sentence([B('<5', 20, 6, 1.2), B('15-20', 30, 9, 1.0), B('20-25', 30, 9, 1.4), B('25-30', 12, 5, 1.9)])
assert 'increases from 1.00 kW in the 15-20 C bin to 1.90 kW in the 25-30 C bin' in inc and '<5 C: 1.20 kW (20 drives, 6 days)' in inc, inc
non = C._aux_sentence([B('15-20', 30, 9, 1.0), B('20-25', 30, 9, 1.8), B('25-30', 30, 9, 1.4)])
assert 'do not increase monotonically' in non and 'No bin below 15 C' in non, non
thin = C._aux_sentence([B('15-20', 30, 9, 1.0), B('20-25', 30, 4, 1.8)])           # 4 days: below the floor, listed, not compared
assert 'Fewer than two bins' in thin and '20-25' in thin and 'not compared' in thin, thin
for t in (inc, non, thin):
    assert 'rises monotonically above' not in t

# D1: _aux_load_ambient end to end (empty bin omitted, nDays, NaN-free)
rng = np.random.default_rng(1)
rows, amb = [], {}
for i in range(60):
    a = 2.0 if i < 20 else (22.0 if i < 50 else 33.0)
    f = 'f%02d.csv' % i
    rows.append({'file': f, 'standstill_draw_kw': 1.0 + (0.1 if a < 10 else 0.0) + 0.02 * i, 'date': '2026-0%d-%02d' % (5 + i // 28, 1 + i % 28)})
    amb[f] = [a]
blk = C._aux_load_ambient(pd.DataFrame(rows), ambient_by_drive=amb)
lab = [b['ambientBinC'] for b in blk['byAmbientBin']]
assert lab == ['<5', '20-25', '>=30'], lab                                           # empty bins omitted, not zero-filled
assert blk['byAmbientBin'][0]['n'] == 20 and all(b['nDays'] >= 1 for b in blk['byAmbientBin'])
assert 'rises monotonically above' not in blk['interpretation']

# D2: time cap: 599 -> '420-600', 600 and 899 -> '600-900', 900 excluded
def frame(tvals, cool):
    return pd.DataFrame({'time': pd.to_datetime('2026-06-01') + pd.to_timedelta(tvals, unit='s'), C._TWL_COOL: cool, C._TWL_OIL: cool})
t = np.arange(0, 2000, 1.0)      # the 900+ s samples (99 C) are the majority of the 600+ s samples: before M623 they set the last-bin median
cool = np.where(t < 600, 20.0 + 0.0 * t, np.where(t < 900, 50.0, 99.0))
dm = pd.DataFrame({'file': ['a.csv'], 'date': ['2026-06-01']})
out = C._thermal_warmup_lag(dm, frame_loader=lambda fn: frame(t, cool))
wc = out['warmupCurves']
assert wc['binLabels'][-1] == '600-900'
assert wc['coolantMedianC'][-1] == 50.0, wc['coolantMedianC']                        # 600-899 s only; before M623 the 900+ s samples (99 C) were in this bin
assert wc['coolantMedianC'][-2] == 20.0
assert wc['coolantNDrives'][-1] == 1 and wc['coolantNDays'][-1] == 1
print("PASS test_m623_bins")
