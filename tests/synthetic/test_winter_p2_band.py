"""M731 known-answer tests (analyses/M731_spec.md Rev 2.2, section 4): the realised-shift derivation (C-P2b), the thin-month rule, the isolation of the band runner from live modules and the vendored engine bytes.
The engine itself is exercised by tools/winter_p2_band_check.py (C-P2a, C-P2d), not here (minutes). No observation after the freeze is read by this test."""
import json, os, subprocess, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_p2_band as WB

NORMALS = [-3.2, -2.4, 1.8, 9.3, 15.5, 19.5, 21.3, 20.5, 15.1, 9.3, 3.7, -0.9]
BIAS = -0.9785


def frame(spec):
    """spec: {month: [(day_of_month, ambient_start, ambient_end), ...]} on 2026 -> a drive frame."""
    rows = []
    for m, lst in spec.items():
        for dm, a0, a1 in lst:
            d = "2026-%02d-%02d" % (m, dm)
            rows.append({"day": d, "start": pd.Timestamp(d + " 09:00"), "ambient_start_c": a0, "ambient_end_c": a1})
    return pd.DataFrame(rows)


# planted: January days with ambient exactly normal + bias + 3.0 -> shift 3.0 (days in the planted month, two drives on the first day)
a = NORMALS[0] + BIAS + 3.0
f = frame({1: [(d, a - 1.0, a + 1.0) for d in range(1, 8)] + [(1, a - 1.0, a + 1.0)]})
ad = WB.day_ambient(f)
assert len(ad) == 7 and np.allclose(ad["A_day"], a)
dr, tab, win = WB.realised_shifts(f, BIAS, NORMALS, nb=400)
assert win == [1] and tab[0]["days"] == 7 and tab[0]["thin"] is False and abs(tab[0]["shiftC"] - 3.0) < 1e-9
assert np.allclose(dr[:, 0], 3.0) and np.isnan(dr[:, 1:]).all()
# a month with spread: the day bootstrap centres on the month mean
rng = np.random.default_rng(0)
vals = rng.normal(0, 2, 20)
f2 = frame({12: [(d + 1, v - 1.0, v + 1.0) for d, v in enumerate(vals)]})
dr2, tab2, _ = WB.realised_shifts(f2, BIAS, NORMALS, nb=2000)
assert abs(dr2[:, 11].mean() - (vals.mean() - NORMALS[11] - BIAS)) < 0.15 and dr2[:, 11].std() > 0.1
# thin month: fewer than 5 days -> no draw, flagged
f3 = frame({2: [(1, 0, 0), (2, 0, 0), (3, 0, 0)]})
dr3, tab3, win3 = WB.realised_shifts(f3, BIAS, NORMALS, nb=100)
assert tab3[0]["thin"] is True and np.isnan(dr3[:, 1]).all() and win3 == [2]
# NaN ambients are dropped; a day with no ambient is not counted
f4 = frame({1: [(d, a - 1.0, a + 1.0) for d in range(1, 6)]})
f4.loc[0, ["ambient_start_c", "ambient_end_c"]] = np.nan
assert WB.realised_shifts(f4, BIAS, NORMALS, nb=50)[1][0]["days"] == 4 and WB.realised_shifts(f4, BIAS, NORMALS, nb=50)[1][0]["thin"] is True
# determinism
assert np.array_equal(WB.realised_shifts(f2, BIAS, NORMALS, nb=300)[0], WB.realised_shifts(f2, BIAS, NORMALS, nb=300)[0], equal_nan=True)
# frozen S3a / S3b tables used for thin Nov-Mar months
assert WB.S3A[12] == 4.0 and WB.S3A[11] == 2.0 and WB.S3B[1] == -6.0 and WB.S3B[3] == -3.0

# ---- the vendored engine bytes equal the index, and the runner imports only vendored modules
idx = json.load(open(os.path.join(ROOT, "analyses", "M731_frozen_engine", "index.json"), encoding="utf-8"))
import hashlib
for rel, rec in idx["files"].items():
    p = os.path.join(ROOT, "analyses", "M731_frozen_engine", "root", rel)
    assert hashlib.sha256(open(p, "rb").read()).hexdigest() == rec["sha256"], rel
src = open(os.path.join(ROOT, "tools", "winter_p2_band_run.py"), encoding="utf-8").read()
assert "assert os.path.dirname(os.path.abspath(m.__file__)) == os.path.abspath(VT)" in src
r = subprocess.run([sys.executable, "-I", "-c", "import sys, runpy; sys.argv=['x']; sys.path.insert(0, %r); import winter_p2_band_run as R; print(sorted(m.__file__ for m in (R.SE, R.ES, R.PM, R.SF)))" % os.path.join(ROOT, "tools")],
                   capture_output=True, text=True, cwd=ROOT)
assert r.returncode == 0, r.stderr[-400:]
assert all("M731_frozen_engine" in p for p in eval(r.stdout.strip().splitlines()[-1])), r.stdout
print("OK test_winter_p2_band")
