#!/usr/bin/env python3
"""M745: exact additive accounting of the EnergyIntensity.shoulder step between two repository states (analyses/M745_spec.md Rev 2).

Read-only: per-drive columns come from git blobs of the two commits; nothing in the working tree is modified except the result JSON.
V = 100 * sum(gross_throughput_kwh) / sum(distance_km) over paired canonical-clean shoulder drives (the refresh_seasonal_kpis.py rule).
Three factors move V(S0) to V(S1): f1 values of common drives re-derived, f2 removal of R, f3 addition of A (Shapley over the 2^3 grid).
Intervals: day-clustered percentile bootstrap (seed 42, 4000 draws, multinomial day weights shared by every cell). Descriptive accounting
of a published monitor value, never a cause.

Usage: python tools/m745_decomposition.py [--out analyses/M745_result.json]"""
import argparse, csv, hashlib, io, itertools, json, math, os, subprocess, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
S0_COMMIT, S1_COMMIT = "55ba671", "6d8f399"
WALK = [("M378 snapshot 2", "55ba671"), ("M388", "533000e"), ("M426", "32e8aaf"), ("M463", "3eb3f3c"), ("M575 snapshot 3", "6d8f399")]
SEED, B, ALPHA = 42, 4000, 0.05
KEY = ["seasonalCharts", "charts", "EnergyIntensity", "data", "shoulder"]


def git_text(commit, path):
    r = subprocess.run(["git", "show", "%s:%s" % (commit, path)], cwd=ROOT, capture_output=True)
    if r.returncode:
        raise SystemExit("m745: git show %s:%s failed" % (commit, path))
    return r.stdout.decode("utf-8")


def blob_sha(commit, path):
    return subprocess.run(["git", "rev-parse", "%s:%s" % (commit, path)], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def _f(x):
    try:
        return float(x) if x not in (None, "", "None") else None
    except ValueError:
        return None


def load_state(commit):
    """Per-drive rows of one state plus the published shoulder block of that commit."""
    dm = {r["file"]: r for r in csv.DictReader(io.StringIO(git_text(commit, "drive_master.csv"), newline=""))}
    rows, parsed = {}, {}
    for r in csv.DictReader(io.StringIO(git_text(commit, "seasonal_drive_master.csv"), newline="")):
        m = dm.get(r["file"])
        if m is None:
            continue
        for col in ("ens_invalid", "ens_outlier_v2"):
            parsed.setdefault(col, {}); k = str(m.get(col)).strip(); parsed[col][k] = parsed[col].get(k, 0) + 1
        rows[r["file"]] = {"date": r["date"], "regime": r["thermal_regime"], "km": _f(m.get("distance_km")), "kwh": _f(m.get("gross_throughput_kwh")),
                           "km_seasonal": _f(r.get("distance_km")), "ambient": _f(r.get("ambient_time_mean_c")), "drive_type": r.get("drive_type"),
                           "excluded": str(m.get("ens_invalid")).strip().lower() == "true" or str(m.get("ens_outlier_v2")).strip().lower() == "true"}
    arr = json.loads(git_text(commit, "summary_arrays.json"))
    pub = arr
    for k in KEY:
        pub = pub[k]
    return {"commit": commit, "rows": rows, "parsedBooleans": parsed, "published": {"value": pub.get("value"), "n": pub.get("n"), "pairedKm": pub.get("pairedKm")}}


def eligible(r):
    return r["regime"] == "shoulder" and not r["excluded"] and r["kwh"] is not None and r["km"] is not None and r["km"] > 0


def recompute(state):
    el = [r for r in state["rows"].values() if eligible(r)]
    km = sum(r["km"] for r in el); kwh = sum(r["kwh"] for r in el)
    return {"value": 100.0 * kwh / km if km > 0 else None, "n": len(el), "pairedKm": round(km, 2)}


def g0(state, snapshot_value=None):
    """Gate G0 (spec section 3 and C1): the per-drive recomputation equals the published block of the commit (1e-6, n, paired km) and, if given, the kpis.jsonl value (1e-9)."""
    rc, pub = recompute(state), state["published"]
    ok_val = rc["value"] is not None and pub["value"] is not None and abs(rc["value"] - pub["value"]) <= 1e-6
    ok_n = rc["n"] == pub["n"]
    ok_km = pub["pairedKm"] is not None and abs(rc["pairedKm"] - pub["pairedKm"]) <= 0.01
    ok_snap = True if snapshot_value is None else (pub["value"] is not None and abs(pub["value"] - snapshot_value) <= 1e-9)
    return {"pass": bool(ok_val and ok_n and ok_km and ok_snap), "recomputed": rc, "published": pub, "valueOk": bool(ok_val), "nOk": bool(ok_n), "kmOk": bool(ok_km),
            "snapshotOk": bool(ok_snap), "snapshotValue": snapshot_value}


# ---- partition ----
def reason_added(f, s0):
    r0 = s0["rows"].get(f)
    if r0 is None:
        return "new_file"
    return "membership_change" if r0["regime"] != "shoulder" else "eligibility_change"


def reason_removed(f, s1):
    r1 = s1["rows"].get(f)
    if r1 is None:
        return "deleted_file"
    return "membership_change" if r1["regime"] != "shoulder" else "eligibility_change"


def partition(s0, s1):
    e0 = {f for f, r in s0["rows"].items() if eligible(r)}
    e1 = {f for f, r in s1["rows"].items() if eligible(r)}
    C, A, R = sorted(e0 & e1), sorted(e1 - e0), sorted(e0 - e1)
    return {"C": C, "A": A, "R": R, "reasonA": {f: reason_added(f, s0) for f in A}, "reasonR": {f: reason_removed(f, s1) for f in R}}


# ---- cells: players are named groups of drives; value arrays per group and per state ----
def build_groups(s0, s1, part, detail=False):
    """Returns (days, groups) with groups = {name: {'num','den'}: arrays over days, plus the base arrays}. Base = C at S0 values plus R at S0 values;
    the factor f1 replaces C(S0) by C(S1); f2 removes R; f3 adds A (S1 values)."""
    day_of = {}
    for f in part["C"] + part["A"]:
        day_of[f] = s1["rows"][f]["date"]
    for f in part["R"]:
        day_of[f] = s0["rows"][f]["date"]
    days = sorted(set(day_of.values())); ix = {d: i for i, d in enumerate(days)}
    G = len(days)

    def agg(files, st):
        num = np.zeros(G); den = np.zeros(G)
        for f in files:
            r = st["rows"][f]; i = ix[day_of[f]]
            num[i] += r["kwh"]; den[i] += r["km"]
        return {"num": num, "den": den}

    g = {"C0": agg(part["C"], s0), "C1": agg(part["C"], s1)}
    if not detail:
        g["R"] = agg(part["R"], s0); g["A"] = agg(part["A"], s1)
    else:
        for rs in ("deleted_file", "membership_change", "eligibility_change"):
            g["R:" + rs] = agg([f for f in part["R"] if part["reasonR"][f] == rs], s0)
        for rs in ("new_file", "membership_change", "eligibility_change"):
            g["A:" + rs] = agg([f for f in part["A"] if part["reasonA"][f] == rs], s1)
    return days, g


def players_of(groups):
    return [k for k in groups if k not in ("C0", "C1")]      # 'f1' is the C0 -> C1 switch; the others are R:* / A:* or R / A


def cell_value(groups, w, on, f1_on):
    """V of one grid cell. on = set of group names whose factor is ON: an R group is ON when REMOVED, an A group is ON when ADDED."""
    num = (groups["C1"]["num"] if f1_on else groups["C0"]["num"]).copy(); den = (groups["C1"]["den"] if f1_on else groups["C0"]["den"]).copy()
    for k, v in groups.items():
        if k in ("C0", "C1"):
            continue
        present = (k.startswith("A") and k in on) or (k.startswith("R") and k not in on)
        if present:
            num = num + v["num"]; den = den + v["den"]
    n_, d_ = w @ num, w @ den
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(d_ > 0, 100.0 * n_ / d_, np.nan)


def shapley(groups, w):
    """Shapley contributions over the players {f1} + the other groups for the weight matrix w (rows = draws or one row of ones). Returns dict name -> array over rows,
    plus V(S0) and V(S1). Each marginal is evaluated on the same weights."""
    names = ["f1"] + players_of(groups); P = len(names)
    cache = {}

    def val(mask):
        if mask not in cache:
            on = {names[i] for i in range(1, P) if mask >> i & 1}
            cache[mask] = cell_value(groups, w, on, bool(mask & 1))
        return cache[mask]
    out = {n: 0.0 for n in names}
    for i, n in enumerate(names):
        for sub in range(1 << P):
            if sub >> i & 1:
                continue
            k = bin(sub).count("1")
            wgt = math.factorial(k) * math.factorial(P - k - 1) / math.factorial(P)
            out[n] = out[n] + wgt * (val(sub | 1 << i) - val(sub))
    return out, val(0), val((1 << P) - 1)


def sequential(groups, w, order):
    names = ["f1", "f2", "f3"]
    # three-factor primary: R and A are single groups
    seq = {}
    on, f1 = set(), False
    prev = cell_value(groups, w, on, f1)
    for n in order:
        if n == "f1":
            f1 = True
        elif n == "f2":
            on.add("R")
        else:
            on.add("A")
        cur = cell_value(groups, w, on, f1); seq[n] = cur - prev; prev = cur
    return seq


def kish(den):
    s = float(den.sum()); s2 = float((den ** 2).sum())
    return (s * s / s2) if s2 > 0 else 0.0


def pct(a):
    a = np.asarray(a, float); a = a[~np.isnan(a)]
    return [float(np.quantile(a, ALPHA / 2)), float(np.quantile(a, 1 - ALPHA / 2))] if len(a) else [None, None]


def read_factor(contrib, ci, total, total_ci, eff_days):
    """Spec section 6 + C4: one factor's reading."""
    if eff_days < 5:
        return "exploratory (fewer than 5 effective days): no reading"
    if ci[0] is None:
        return "not estimable"
    excl = (ci[0] > 0) or (ci[1] < 0)
    same_sign = contrib * total > 0
    share = abs(contrib) / abs(total) if total else float("inf")
    if excl and same_sign and share >= 0.5:
        return "accounts for the step"
    if excl:
        return "contributes"
    return "not distinguishable from 0"


def overall(readings, total_ci):
    if total_ci[0] is not None and total_ci[0] <= 0 <= total_ci[1]:
        return "step not distinguishable from 0 on the common days"
    acc = [k for k, v in readings.items() if v == "accounts for the step"]
    con = [k for k, v in readings.items() if v == "contributes"]
    if len(acc) == 1 and not con:
        return {"f1": "re-derived values", "f2": "removal", "f3": "added drives"}[acc[0]]
    if len(acc) == 1 and con:
        return "mixed (dominant %s)" % {"f1": "re-derived values", "f2": "removal", "f3": "added drives"}[acc[0]]
    if len(acc) + len(con) >= 2:
        return "mixed"
    return "not attributable"


def draws(G, nb, seed):
    rng = np.random.default_rng(seed)
    return rng.multinomial(G, [1.0 / G] * G, size=nb).astype(float)


def run_decomposition(s0, s1, nb=B, seed=SEED):
    part = partition(s0, s1)
    days, g3 = build_groups(s0, s1, part, detail=False)
    G = len(days)
    w1 = np.ones((1, G))
    sh, v0, v1 = shapley(g3, w1)
    total = float(v1[0] - v0[0])
    assert abs(sum(float(sh[n][0]) for n in sh) - total) < 1e-9, "Shapley contributions do not sum to the total"
    W = draws(G, nb, seed)
    shb, v0b, v1b = shapley(g3, W)
    totb = v1b - v0b
    dropped = int(np.isnan(totb).sum())
    names = {"f1": "f1_values_rederived", "R": "f2_removed", "A": "f3_added"}
    ci_total = pct(totb)
    eff = {"f1": kish(g3["C1"]["den"]), "R": kish(g3["R"]["den"]), "A": kish(g3["A"]["den"])}
    contrib, readings = {}, {}
    for key, nm in names.items():
        c = float(sh[key][0]); ci = pct(shb[key])
        short = {"f1": "f1", "R": "f2", "A": "f3"}[key]
        contrib[nm] = {"value": c, "ci95": ci, "share": (c / total if total else None), "effectiveDays": round(eff[key], 2), "droppedDraws": int(np.isnan(shb[key]).sum())}
        readings[short] = read_factor(c, ci, total, ci_total, eff[key])
        contrib[nm]["reading"] = readings[short]
    # exact identity V(S1) = (1-w) V_C(S1) + w V_A(S1)
    nC, dC = g3["C1"]["num"].sum(), g3["C1"]["den"].sum(); nA, dA = g3["A"]["num"].sum(), g3["A"]["den"].sum()
    wA = dA / (dA + dC) if (dA + dC) > 0 else None
    VC = 100 * nC / dC if dC > 0 else None; VA = 100 * nA / dA if dA > 0 else None
    ident = None if wA is None or VC is None else (1 - wA) * VC + wA * (VA if VA is not None else 0.0)
    # ordered sequential sensitivities
    seq = {}
    for order in (("f1", "f2", "f3"), ("f3", "f2", "f1")):
        sq = sequential(g3, w1, order); seq["-".join(order)] = {k: float(v[0]) for k, v in sq.items()}
    # 7-player split (detail by reason)
    daysd, gd = build_groups(s0, s1, part, detail=True)
    shd, v0d, v1d = shapley(gd, w1); shdb, _, _ = shapley(gd, W)
    detail = {k: {"value": float(shd[k][0]), "ci95": pct(shdb[k]), "effectiveDays": round(kish(gd[k]["den"]) if k != "f1" else kish(gd["C1"]["den"]), 2)} for k in shd}
    assert abs(sum(float(shd[k][0]) for k in shd) - total) < 1e-9
    # sub-decomposition of f1 by column when the common drives differ (spec 7d)
    comm0 = 100 * g3["C0"]["num"].sum() / g3["C0"]["den"].sum() if g3["C0"]["den"].sum() > 0 else None
    comm1 = VC
    f1_split = None
    if comm0 is not None and comm1 is not None and abs(comm1 - comm0) > 1e-6:
        kwh0, kwh1 = g3["C0"]["num"].sum(), g3["C1"]["num"].sum(); km0, km1 = g3["C0"]["den"].sum(), g3["C1"]["den"].sum()
        # Shapley over the two columns of the C ratio (kwh, km): the other cells of the grid are unchanged
        a = 100 * kwh1 / km0 - 100 * kwh0 / km0; b = 100 * kwh0 / km1 - 100 * kwh0 / km0
        v_both = 100 * kwh1 / km1 - 100 * kwh0 / km0
        f1_split = {"kwhColumn": 0.5 * (a + (100 * kwh1 / km1 - 100 * kwh0 / km1)), "kmColumn": 0.5 * (b + (100 * kwh1 / km1 - 100 * kwh1 / km0)), "commonValueS0": comm0, "commonValueS1": comm1,
                    "kwhSum": [float(kwh0), float(kwh1)], "kmSum": [float(km0), float(km1)], "totalCommon": v_both}
    # block bootstrap sensitivity (7-day blocks of consecutive calendar days)
    blk = np.array([(__import__("datetime").date.fromisoformat(d).toordinal() // 7) for d in days]); ub = sorted(set(blk.tolist()))
    totals_blk = None
    if len(ub) >= 5:
        rng = np.random.default_rng(seed); bw = np.zeros((nb, G))
        for j in range(nb):
            pick = rng.integers(0, len(ub), size=len(ub))
            for p in pick:
                bw[j] += (blk == ub[p])
        shk, v0k, v1k = shapley(g3, bw); totals_blk = {"total": pct(v1k - v0k), "f1": pct(shk["f1"]), "f2": pct(shk["R"]), "f3": pct(shk["A"]), "nBlocks": len(ub)}
    covs = {}
    for nm, files, st in (("C", part["C"], s1), ("A", part["A"], s1), ("R", part["R"], s0)):
        rs = [st["rows"][f] for f in files]
        km = sum(r["km"] for r in rs)
        amb = [r["ambient"] for r in rs if r["ambient"] is not None]
        mon = {}
        for r in rs:
            mon[r["date"][:7]] = mon.get(r["date"][:7], 0) + 1
        dt = {}
        for r in rs:
            dt[r["drive_type"]] = dt.get(r["drive_type"], 0) + 1
        covs[nm] = {"nDrives": len(rs), "km": round(km, 2), "meanKmPerDrive": (km / len(rs) if rs else None), "ambientMeanC": (float(np.mean(amb)) if amb else None), "months": dict(sorted(mon.items())), "driveType": dt,
                    "ratioOfSumsS%d" % (1 if nm != "R" else 0): (100 * sum(r["kwh"] for r in rs) / km if km > 0 else None), "nDays": len({r["date"] for r in rs})}
    # column disagreement (spec concern): distance_km of seasonal vs drive_master for the common drives
    dis = [f for f in part["C"] + part["A"] if s1["rows"][f]["km_seasonal"] is not None and abs(s1["rows"][f]["km_seasonal"] - s1["rows"][f]["km"]) > 1e-9]
    dates_changed = [f for f in part["C"] if s0["rows"][f]["date"] != s1["rows"][f]["date"]]
    return {"counts": {"C": len(part["C"]), "A": len(part["A"]), "R": len(part["R"]),
                       "reasonA": {k: sum(1 for v in part["reasonA"].values() if v == k) for k in ("new_file", "membership_change", "eligibility_change")},
                       "reasonR": {k: sum(1 for v in part["reasonR"].values() if v == k) for k in ("deleted_file", "membership_change", "eligibility_change")}, "nDaysUnion": G},
            "V_S0": float(v0[0]), "V_S1": float(v1[0]), "V_S0_ci95": pct(v0b), "V_S1_ci95": pct(v1b), "total": total, "total_ci95": ci_total, "droppedDrawsTotal": dropped,
            "contributions": contrib, "overall": overall(readings, ci_total), "identity": {"w": wA, "V_C_S1": VC, "V_A_S1": VA, "reconstructed": ident, "V_S1": float(v1[0])},
            "sequential": seq, "detailByReason": detail, "f1ColumnSplit": f1_split, "blockBootstrap7d": totals_blk, "covariates": covs,
            "columnChecks": {"distanceSeasonalVsMasterDisagreeS1": len(dis), "commonDriveDateChanged": len(dates_changed)}}


def placebo(s1, part, nperm=200, nb=500, seed=SEED):
    """C3 (c2): permute the A/C label among S1 days; fraction of permutations in which the f3 interval excludes 0 (reported, not a gate)."""
    el = {f: r for f, r in s1["rows"].items() if eligible(r)}
    byday = {}
    for f, r in el.items():
        byday.setdefault(r["date"], []).append(f)
    alld = sorted(byday); a_days = sorted({el[f]["date"] for f in part["A"]})
    rng = np.random.default_rng(seed); excl = 0; done = 0
    for _ in range(nperm):
        pick = set(rng.choice(alld, size=len(a_days), replace=False).tolist())
        A = [f for d in pick for f in byday[d]]; Cc = [f for f in el if f not in set(A)]
        if not A or not Cc:
            continue
        day_ix = {d: i for i, d in enumerate(alld)}
        def agg(files):
            n_ = np.zeros(len(alld)); d_ = np.zeros(len(alld))
            for f in files:
                i = day_ix[el[f]["date"]]; n_[i] += el[f]["kwh"]; d_[i] += el[f]["km"]
            return n_, d_
        nA, dA = agg(A); nC, dC = agg(Cc)
        W = draws(len(alld), nb, int(rng.integers(1, 2 ** 31 - 1)))
        with np.errstate(divide="ignore", invalid="ignore"):
            v_all = 100 * (W @ (nA + nC)) / (W @ (dA + dC)); v_c = 100 * (W @ nC) / (W @ dC)
        lo, hi = pct(v_all - v_c); done += 1
        if lo is not None and (lo > 0 or hi < 0):
            excl += 1
    return {"nPermutations": done, "fractionIntervalExcludesZero": (excl / done if done else None), "note": "reported, not a gate (spec C3 c2)"}


def sha256_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default=os.path.join(ROOT, "analyses", "M745_result.json")); a = ap.parse_args()
    hist = [json.loads(l) for l in io.open(os.path.join(ROOT, "snapshots", "kpis.jsonl"), encoding="utf-8")]
    kname = "EnergyIntensity.shoulder"
    snap2, snap3 = hist[1]["kpis"][kname]["value"], hist[2]["kpis"][kname]["value"]
    s0, s1 = load_state(S0_COMMIT), load_state(S1_COMMIT)
    gate = {"S0": g0(s0, snap2), "S1": g0(s1, snap3)}
    res = {"spec": "analyses/M745_spec.md Rev 2", "commits": {"S0": S0_COMMIT, "S1": S1_COMMIT}, "G0": gate,
           "parsedBooleans": {"S0": s0["parsedBooleans"], "S1": s1["parsedBooleans"]}}
    walk = []
    for label, c in WALK:
        st = load_state(c) if c not in (S0_COMMIT, S1_COMMIT) else (s0 if c == S0_COMMIT else s1)
        gg = g0(st); walk.append({"label": label, "commit": c, "recomputed": gg["recomputed"], "published": gg["published"], "reproduces": gg["pass"], "nDrivesInMaster": len(st["rows"])})
    res["commitWalk"] = {"note": "point values only, no intervals, no reading (spec C7)", "rows": walk}
    head = load_state("HEAD"); res["endPointS2"] = {"commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(), "recomputed": recompute(head), "published": head["published"]}
    if not (gate["S0"]["pass"] and gate["S1"]["pass"]):
        res["result"] = "not decomposable: G0 failed (spec section 3); the definition or commit mapping differs"
    else:
        res["decomposition"] = run_decomposition(s0, s1)
        res["placebo"] = placebo(s1, partition(s0, s1))
    res["provenance"] = {"driveMasterMd5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest(), "scriptSha256": sha256_file(os.path.abspath(__file__)),
                         "specSha256": sha256_file(os.path.join(ROOT, "analyses", "M745_spec.md")), "blobs": {c: {f: blob_sha(c, f) for f in ("drive_master.csv", "seasonal_drive_master.csv", "summary_arrays.json")} for c in (S0_COMMIT, S1_COMMIT)},
                         "bootstrap": {"seed": SEED, "draws": B, "unit": "calendar day (multinomial weights over the union of days)"}}
    io.open(a.out, "w", encoding="utf-8", newline="").write(json.dumps(res, indent=1))
    print(json.dumps({"G0": {k: v["pass"] for k, v in gate.items()}, "overall": (res.get("decomposition") or {}).get("overall", res.get("result"))}))


if __name__ == "__main__":
    main()
