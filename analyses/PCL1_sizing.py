"""PCL-1 sizing simulation (spec analyses/PCL1_spec.md section 5). k calendar days are drawn with replacement from the existing corpus; each day's drives are assigned to two hypothetical arms in permuted blocks of two (random order
within each block, seed 42); the temperature and speed cells that meet the support floors (>= 200 strict-drop intervals, >= 10 drives, >= 5 days) in BOTH arms are counted. Native v2 cache arrays are used; the arms are hypothetical here
(the existing corpus has no randomized cadence). Output: analyses/PCL1_sizing.json (script-written)."""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import regen_v2_cache as K
import regen_v2_agg as G

dm, reg = G.load_master()
files = list(dm["file"])
T, H = K.load(files, "base", with_off=False)
d = T["drive"]
strict = (~T["iv_trimmed"]) & (~T["iv_plateau"])
tb = G.temp_bins()
tp = T["iv_tpack"]
tidx = np.full(len(tp), -1)
for j, (lo, hi, _) in enumerate(tb):
    tidx[np.isfinite(tp) & (tp >= lo) & (tp < hi)] = j
nd = len(files)
tc = np.zeros((nd, len(tb)))
sc = np.zeros((nd, 14))
m = strict & (tidx >= 0)
np.add.at(tc, (d[m], tidx[m]), 1)
np.add.at(sc, d[strict], T["bin_touch"][strict])
cells = np.hstack([tc, sc])
days = dm["date"].astype(str).str[:10].values
udays = sorted(set(days))
by_day = {u: np.where(days == u)[0] for u in udays}
rng = np.random.default_rng(42)


def assign(idx):
    """Permuted blocks of two: each consecutive pair of trips gets one fast and one slow arm in random order."""
    arms = {0: [], 1: []}
    for k in range(0, len(idx) - 1, 2):
        a = int(rng.integers(0, 2))
        arms[a].append(idx[k])
        arms[1 - a].append(idx[k + 1])
    return arms


def trial(k):
    pool = [u for u in udays if len(by_day[u]) >= 4]
    chosen = rng.choice(pool, size=k, replace=True)
    arms = {0: [], 1: []}
    for u in chosen:
        idx = by_day[u].copy()
        rng.shuffle(idx)
        a = assign(list(idx))
        for arm in (0, 1):
            arms[arm].extend((di, u) for di in a[arm])
    ok = []
    for c in range(cells.shape[1]):
        good = True
        for arm in (0, 1):
            ds = [(di, u) for di, u in arms[arm] if cells[di, c] > 0]
            n = sum(cells[di, c] for di, u in ds)
            good &= (n >= 200 and len(set(di for di, u in ds)) >= 10 and len(set(u for di, u in ds)) >= 5)
        ok.append(good)
    return np.array(ok)


out = {}
for k in (5, 10, 15, 20, 30, 40):
    r = np.array([trial(k) for _ in range(200)])
    t_ = r[:, :len(tb)].sum(axis=1)
    s_ = r[:, len(tb):].sum(axis=1)
    out[str(k)] = {"meanSupportedTemperatureCells": round(float(t_.mean()), 2), "meanSupportedSpeedCells": round(float(s_.mean()), 2),
                   "shareTrialsWithAtLeast3TempAnd5SpeedCells": round(float(((t_ >= 3) & (s_ >= 5)).mean()), 3)}
# precision at the view total (Director B1): the 95 % half-width of the day-clustered fast-minus-slow difference of the pooled ratio, per k, in hypothetical arms
import compute_summary_arrays as CSA
mass = np.array([CSA._mass_for_drive(t, f) for t, f in zip(dm["drive_type"], dm["file"])])
import regen_v2 as R2
keep = ~T["iv_trimmed"]
ke_d = np.bincount(d[keep], weights=(R2.KE_FACTOR * mass[d] * T["iv_dv2"])[keep], minlength=nd)
ch_d = np.bincount(d[keep], weights=T["iv_charge"][keep], minlength=nd)


def trial_total(k, level, B=300):
    """One hypothetical trial: point difference and the interval (at the level) of the fast-minus-slow difference of the pooled all-drive ratio over k drawn days."""
    pool = [u for u in udays if len(by_day[u]) >= 4]
    chosen = rng.choice(pool, size=k, replace=True)
    Cf = np.zeros(k); Kf = np.zeros(k); Cs = np.zeros(k); Ks = np.zeros(k)
    for i, u in enumerate(chosen):
        idx = by_day[u].copy()
        rng.shuffle(idx)
        a_ = assign(list(idx))
        Cf[i], Kf[i] = ch_d[a_[0]].sum(), ke_d[a_[0]].sum()
        Cs[i], Ks[i] = ch_d[a_[1]].sum(), ke_d[a_[1]].sum()
    pt = 100 * Cf.sum() / Kf.sum() - 100 * Cs.sum() / Ks.sum()
    bi = rng.integers(0, k, (B, k))
    diff = 100 * Cf[bi].sum(1) / Kf[bi].sum(1) - 100 * Cs[bi].sum(1) / Ks[bi].sum(1)
    lo = (100.0 - level) / 2.0
    return pt, float(np.percentile(diff, lo)), float(np.percentile(diff, 100.0 - lo))


# view-total tolerances of the gate (spec section 4, Director Rev 2.1): own bracket maxima (borrowed values and the 0-10 km/h bin excluded) + the pooled mass half-width of the all-drive total
b = json.load(open(os.path.join(ROOT, "analyses", "M442_result_rerun.json"), encoding="utf-8"))["bracket"]["b"]
def own_max(kind):
    dd = b[kind]; br = set(dd.get("_borrowed", []))
    return max(v for k, v in dd.items() if not k.startswith("_") and v is not None and k not in br and not (kind == "speed" and k == "0-10"))
mr = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))["regenCaptureV2H"]["cohorts"]["all"]["totals"]["massRange"]
hw_mass = (mr[1] - mr[0]) / 2.0
tols = {"temperatureTotal": round(own_max("temperature") + hw_mass, 3), "speedTotal": round(own_max("speed") + hw_mass, 3), "pooledMassHalfWidth": round(hw_mass, 3)}
prec = {}
for k, level in ((30, 95.0), (60, 95.0), (80, 95.0), (100, 95.0), (160, 97.5)):
    tr = [trial_total(k, level) for _ in range(200)]
    hw = np.array([(hi - lo_) / 2.0 for _, lo_, hi in tr])
    ok = {name: float(np.mean([(lo_ >= -t) and (hi <= t) for _, lo_, hi in tr])) for name, t in (("temperatureTotal", tols["temperatureTotal"]), ("speedTotal", tols["speedTotal"]))}
    prec[str(k)] = {"intervalLevel": level, "medianHalfWidthPp": round(float(np.median(hw)), 2), "p90HalfWidthPp": round(float(np.percentile(hw, 90)), 2),
                    "pTotalOkTemperature": round(ok["temperatureTotal"], 3), "pTotalOkSpeed": round(ok["speedTotal"], 3), "pPassUpperBound": round(min(ok.values()), 3)}
res = {"note": "PCL-1 sizing: k calendar days (days with >= 4 drives) drawn with replacement from the existing corpus, drives assigned to two hypothetical arms in permuted blocks of two; cells supported in BOTH arms; 200 trials per k, seed 42; native v2 strict-drop interval counts",
       "daysWithAtLeast4Drives": int(sum(1 for v in by_day.values() if len(v) >= 4)), "daysTotal": len(udays), "byPairedDays": out, "totalPrecisionHypotheticalArms": {"note": "half-width of the day-clustered fast-minus-slow difference of the pooled all-drive ratio under hypothetical arms and NO true cadence effect (variance of the day-level ratio only); pTotalOk = share of trials whose whole interval lies inside the view-total tolerance; pPassUpperBound = the smaller of the two (an upper bound of P(PASS): the cell conditions are not simulated); B = 300 resamples, 200 trials per k, seed 42; k = 160 uses the 97.5 % level of the extension", "tolerances": tols, "byPairedDays": prec}}
with open(os.path.join(ROOT, "analyses", "PCL1_sizing.json"), "w", encoding="utf-8", newline="\n") as f:
    json.dump(res, f, indent=1)
print(json.dumps(res, indent=1))
