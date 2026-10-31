"""M545 G0 (analyses/M545_spec.md Rev 2 A0 / A5): the pure kernels of tools/engine_on_blocks.py at the stored gate (300) equal the former inline code of _RawAccum, which is FROZEN VERBATIM below (copied from compute_summary_arrays.py at tag M544),
on synthetic frames with NaN runs, boundary values (exactly 300, 400), negative-free rpm and short series. Also: the run taxonomy between 300 and 400 is split / drop / shorten, never merge; _RawAccum defaults to 300 and rejects nothing else."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import engine_on_blocks as E

Z_ENGINE = [0, 20, 40, 60, 80, 100, 120, 999]
Z_TURBO_SPD = [(0, 40, "0-40"), (40, 60, "40-60"), (60, 80, "60-80"), (80, 100, "80-100"), (100, 120, "100-120"), (120, 160, "120-160")]
RPM_BANDS = [(0, 1500, "<1500"), (1500, 2000, "1500-2000"), (2000, 2500, "2000-2500"), (2500, 9999, "2500+")]


# ---- FROZEN VERBATIM: former inline code (thr literal 300), wrapped only to return its accumulations ----
def old_runs(rr):
    valid = ~np.isnan(rr)
    eon = (rr > 300) & valid
    if valid.any():
        dd = np.diff(eon.astype(int), prepend=0)
        starts = np.where(dd == 1)[0]
        ends = np.where(np.diff(eon.astype(int), append=0) == -1)[0]
        nseg = min(len(starts), len(ends))
        durs = (ends[:nseg] - starts[:nseg] + 1).astype(float)
        return durs.tolist(), float(eon.sum()), float(valid.sum()), float(nseg)
    return None


def old_by_speed(sp, rp):
    z = np.digitize(sp, Z_ENGINE[1:-1])
    eng = rp > 300
    ok = ~np.isnan(sp) & ~np.isnan(rp)
    tot, on = np.zeros(7), np.zeros(7)
    for i in range(7):
        m = (z == i) & ok
        tot[i] += m.sum()
        on[i] += (eng & m).sum()
    return tot, on, bool(ok.any())


def old_turbo(bo, rp, sp):
    eng = rp > 300
    tr, ts = {}, {}
    for lo, hi, lbl in RPM_BANDS:
        m = (rp >= lo) & (rp < hi) & eng & ~np.isnan(bo)
        if not m.any():
            continue
        bb = bo[m]
        act = bb[bb > 0.1]
        tr[lbl] = (len(bb), len(act), act.sum(), float(bb.max()))
    for lo, hi, lbl in Z_TURBO_SPD:
        m = (sp >= lo) & (sp < hi) & eng & ~np.isnan(bo)
        if not m.any():
            continue
        bb = bo[m]
        ts[lbl] = (len(bb), (bb > 0.1).sum(), float(bb.max()))
    return tr, ts


def old_hvc(bo, rp):
    m = (rp > 300) & ~np.isnan(bo)
    if m.any():
        bb = bo[m]
        return int(len(bb)), int((bb > 0.1).sum()), float(bb.max())
    return None
# ---- end frozen ----


def frames(seed):
    r = np.random.default_rng(seed)
    n = int(r.integers(1, 400))
    rp = r.choice([0.0, 250.0, 300.0, 301.0, 350.0, 400.0, 401.0, 900.0, 1800.0, 2300.0, 3000.0], size=n)
    rp = rp.astype(float); rp[r.random(n) < 0.1] = np.nan
    sp = r.uniform(0, 160, n); sp[r.random(n) < 0.08] = np.nan
    bo = r.uniform(-0.3, 1.2, n); bo[r.random(n) < 0.1] = np.nan
    return rp, sp, bo


for seed in range(300):
    rp, sp, bo = frames(seed)
    o = old_runs(rp); k = E.engine_on_runs(rp, 300)
    assert (o is None) == (k is None)
    if o:
        assert o[0] == k["durs"].tolist() and o[1:] == (k["on"], k["valid"], k["nseg"]), seed
    ot, oo, oa = old_by_speed(sp, rp); kt, ko, ka = E.engine_on_by_speed(sp, rp, Z_ENGINE[1:-1], 7, 300)
    assert (ot == kt).all() and (oo == ko).all() and oa == ka, seed
    tr, ts = old_turbo(bo, rp, sp)
    ktr = E.turbo_by_rpm_band(bo, rp, RPM_BANDS, 300); kts = E.turbo_by_speed_zone(bo, rp, sp, Z_TURBO_SPD, 300)
    assert set(tr) == set(ktr) and set(ts) == set(kts), seed
    for l, v in tr.items():
        assert v == (ktr[l]["n"], ktr[l]["act"], ktr[l]["sumAct"], ktr[l]["max"]), (seed, l)
    for l, v in ts.items():
        assert v == (kts[l]["n"], kts[l]["act"], kts[l]["max"]), (seed, l)
    oh = old_hvc(bo, rp); kh = E.hvc_turbo_counts(bo, rp, 300)
    assert (oh is None) == (kh is None) and (oh is None or oh == (kh["n"], kh["act"], kh["max"])), seed

# boundary strictness: exactly 300 is NOT engine-on at 300; exactly 400 is NOT engine-on at 400
x = np.array([300.0, 301.0, 400.0, 401.0])
assert E.engine_on_runs(x, 300)["on"] == 3 and E.engine_on_runs(x, 400)["on"] == 1

# taxonomy: split, drop, shorten, never merge (higher threshold on-set is a subset)
r = np.array([0, 500, 600, 350, 600, 500, 0, 350, 350, 0, 900, 400, 0, 350, 800, 800, 0, 1000, 700, 380, 0], dtype=float)
lo, hi = E.engine_on_runs(r, 300)["durs"], E.engine_on_runs(r, 400)["durs"]
assert len(lo) == 5 and len(hi) == 5 and lo.sum() > hi.sum()      # 1 run split into 2, 1 dropped, shortened runs remain; sub-runs total 5 (4 original with one split) -> no merge

# _RawAccum wiring
import compute_summary_arrays as C
assert C.ENGINE_ON_STORED_RPM == 300 and C._RawAccum().eng_on_rpm == 300 and C._RawAccum(eng_on_rpm=400).eng_on_rpm == 400
print("OK test_engine_on_blocks_g0: 300 random frames kernel == frozen inline code, strict boundary, taxonomy, _RawAccum default 300")
