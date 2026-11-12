"""M624 known-answer test (spec analyses/M624_spec.md Rev 1 R5): per-bin p25/p75 of per-drive medians and the support flag (>= 10 drives on >= 5 days)."""
import os, sys
import numpy as np, pandas as pd
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, REPO)
import compute_summary_arrays as C

def frame(base):
    t = np.arange(0, 400, 1.0)                               # 400 s, constant per-drive temperature = base (cold start: base < 60)
    cool = np.full_like(t, base)
    return pd.DataFrame({'time': pd.to_datetime('2026-06-01') + pd.to_timedelta(t, unit='s'), C._TWL_COOL: cool, C._TWL_OIL: cool})

def run(n_drives, n_days):
    rows = [{'file': 'f%d.csv' % i, 'date': '2026-06-%02d' % (1 + i % n_days)} for i in range(n_drives)]
    base = {r['file']: 20.0 + i for i, r in enumerate(rows)}          # per-drive medians 20, 21, ... (n_drives values)
    return C._thermal_warmup_lag(pd.DataFrame(rows), frame_loader=lambda fn: frame(base[fn])), sorted(base.values())

wc, v = run(12, 6)
assert wc['warmupCurves']['coolantP25C'][0] == round(float(np.percentile(v, 25)), 1) and wc['warmupCurves']['coolantP75C'][0] == round(float(np.percentile(v, 75)), 1)
assert wc['warmupCurves']['coolantSupported'][0] is True and wc['warmupCurves']['coolantSupported'][-1] is False      # last bin (600-900 s) has no samples: empty, unsupported
assert wc['warmupCurves']['coolantP25C'][-1] is None
for nd, nday, ok in ((9, 6, False), (10, 6, True), (12, 4, False), (12, 5, True)):
    w, _ = run(nd, nday)
    assert w['warmupCurves']['coolantSupported'][0] is ok, (nd, nday, w['warmupCurves']['coolantSupported'][0])
print("PASS test_m624_curves")
