#!/usr/bin/env python3
"""M705 (spec analyses/M705_spec.md Rev 1 + errata): occupancy of rpm windows around the quoted manufacturer points: C1 (window around the quoted best-BSFC point), C1b (below 1,500 rpm outside ramps), C2 (window around the
quoted maximum-output point). Ratio of sums on the state-machine 1 Hz grid from the per-drive histogram cache (tools/rpm_window_cache.py), calendar-day clusters, day-clustered percentile bootstrap (seed 42, 4000 draws).
Descriptive only: no comparison with a manufacturer value, no 'consistent' label, no margin. Modes: --study OUT.json | --splice (reads analyses/M705_study.json and analyses/M705_audit.json)."""
import hashlib, json, os, sys, datetime
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import rpm_window_cache as W

SEED, NB = 42, 4000
FLOOR_DRIVES, FLOOR_DAYS = 10, 5
STRATA = ("fast", "slow")
COHORTS = ("all", "cold", "shoulder", "warm")
ZLBL = ["0-20", "20-40", "40-60", "60-80", "80-100", "100-120", "120+", "no speed"]
MARKET = "EU market (stated by the owner in chat, 2026-11-16)"


def vidx(t, r, f=0, v=0):
    return W.VARIANTS.index((t, r, f, v))


def load_drives():
    import ah_throughput as AH
    m = pd.read_csv("drive_master.csv", usecols=["file", "date", "ens_outlier_v2"], low_memory=False)
    m = m[m["ens_outlier_v2"].astype(str) == "False"].reset_index(drop=True)
    cad = pd.read_csv("cadence_regime.csv").set_index("file")["regime"]
    coh = pd.read_csv("seasonal_drive_master.csv", usecols=["file", "thermal_regime"]).set_index("file")["thermal_regime"]
    sha_by = AH.manifest_sha_lookup(); loader = AH.raw_loader(os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    rows = []
    for _, r in m.iterrows():
        sha = sha_by(r["file"])
        if not sha:                                                       # same fallback as the cache builder: sha256 of the raw bytes
            b = loader(r["file"]); sha = hashlib.sha256(b).hexdigest() if b else None
        e = W.load_entry(sha) if sha else None
        if e is None:
            continue
        c = cad.get(r["file"]); c = c if isinstance(c, str) else "unknown"
        rows.append({"file": r["file"], "date": str(r["date"])[:10], "cadence": c, "cohort": coh[r["file"]], "H": e[0], "meta": e[1]})
    return rows


def day_arrays(drives, num_fn, den_fn):
    """-> (days, num[d], den[d], nDrivesWithDen)"""
    byday = {}
    nd = 0
    for d in drives:
        a, b = num_fn(d), den_fn(d)
        if b > 0:
            nd += 1
        x = byday.setdefault(d["date"], [0, 0]); x[0] += a; x[1] += b
    days = sorted(byday)
    return days, np.array([byday[k][0] for k in days], float), np.array([byday[k][1] for k in days], float), nd


def share(drives, num_fn, den_fn, rng_seed=SEED, nb=NB):
    days, num, den, nd = day_arrays(drives, num_fn, den_fn)
    nday = int((den > 0).sum())
    out = {"drives": nd, "days": nday, "seconds": int(den.sum()), "inWindowSeconds": int(num.sum())}
    if nd < FLOOR_DRIVES or nday < FLOOR_DAYS or den.sum() == 0:
        out["status"] = "not estimable (below the support floor of %d drives on %d days)" % (FLOOR_DRIVES, FLOOR_DAYS)
        return out
    pct = 100.0 * num.sum() / den.sum()
    rng = np.random.default_rng(rng_seed)
    idx = rng.integers(0, len(days), (nb, len(days)))
    dd = den[idx].sum(1); nn = num[idx].sum(1)
    ok = dd > 0
    bs = 100.0 * nn[ok] / dd[ok]
    out.update(pct=float(pct), ci95=[float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))], draws=int(ok.sum()))
    if num.sum() == 0:
        out["note"] = "no occupancy observed in %d drives on %d days" % (nd, nday)
    return out


def cells(rows):
    for s in STRATA:
        for c in COHORTS:
            ds = [d for d in rows if d["cadence"] == s and (c == "all" or d["cohort"] == c)]
            yield s, c, ds


def win_fn(var, lo, hi, zone=None):
    a, b = lo // W.BIN, hi // W.BIN
    if zone is None:
        return lambda d: int(d["H"][var][:, a:b].sum())
    return lambda d: int(d["H"][var][zone, a:b].sum())


def den_fn(var, zone=None):
    if zone is None:
        return lambda d: int(d["H"][var].sum())
    return lambda d: int(d["H"][var][zone].sum())


def build_c1(rows):
    out = {}
    prim = ("C1_150", "C1_100", "C1_250", "C1_150_shift-50", "C1_150_shift-25", "C1_150_shift+25", "C1_150_shift+50")
    for s, c, ds in cells(rows):
        cell = {}
        for t in W.THRS:
            v0 = vidx(t, 0)
            tc = {"windows": {}, "zones": {}, "sensitivities": {}}
            for name in prim:
                lo, hi = W.WINDOWS[name]
                tc["windows"][name] = {"windowRpm": [lo, hi], **share(ds, win_fn(v0, lo, hi), den_fn(v0))}
            lo, hi = W.WINDOWS["C1_150"]
            for z in range(W.NZONE):
                tc["zones"][ZLBL[z]] = share(ds, win_fn(v0, lo, hi, z), den_fn(v0, z))
            for nm, var in (("withoutFirst60s", vidx(t, 0, 1, 0)), ("reverseSecondsRemoved", vidx(t, 0, 0, 1))):
                tc["sensitivities"][nm] = share(ds, win_fn(var, lo, hi), den_fn(var))
            cell["thr%d" % t] = tc
        out.setdefault(s, {})[c] = cell
    return out


def build_c1b(rows):
    out = {}
    for s, c, ds in cells(rows):
        cell = {}
        for t in W.THRS:
            tc = {}
            for r in (5, 3, 10, 0):
                v = vidx(t, r)
                tc["ramp%ds" % r] = {nm: {"windowRpm": list(W.WINDOWS[nm]), **share(ds, win_fn(v, *W.WINDOWS[nm]), den_fn(v))} for nm in ("C1b_lt1500", "C1b_lt1475", "C1b_lt1525", "C1b_1475_1525")}
            v5 = {"withoutFirst60s": vidx(t, 5, 1, 0), "reverseSecondsRemoved": vidx(t, 5, 0, 1)}
            tc["sensitivities"] = {nm: share(ds, win_fn(v, *W.WINDOWS["C1b_lt1500"]), den_fn(v)) for nm, v in v5.items()}
            # ramp bookkeeping (counts of fully excluded runs and censored edges, summed over the cell)
            ti = list(W.THRS).index(t)
            for r in (3, 5, 10):
                ri = list(W.RAMPS).index(r)
                tc["ramp%ds" % r]["bookkeeping"] = {"runsFullyExcluded": int(sum(d["meta"][ti, ri, 1] for d in ds)), "censoredRunEdges": int(sum(d["meta"][ti, ri, 2] for d in ds))}
            cell["thr%d" % t] = tc
        out.setdefault(s, {})[c] = cell
    return out


def build_c2(rows):
    out = {}
    prim = ("C2_100", "C2_200", "C2_100_shift-50", "C2_100_shift-25", "C2_100_shift+25", "C2_100_shift+50")
    for s, c, ds in cells(rows):
        cell = {}
        for t in W.THRS:
            v0 = vidx(t, 0); tc = {"windows": {}, "sensitivities": {}}
            for name in prim:
                lo, hi = W.WINDOWS[name]
                sh = share(ds, win_fn(v0, lo, hi), den_fn(v0))
                sh["drivesWithAnyOccupancy"] = int(sum(1 for d in ds if win_fn(v0, lo, hi)(d) > 0))
                tc["windows"][name] = {"windowRpm": [lo, hi], **sh}
            lo, hi = W.WINDOWS["C2_100"]
            for nm, var in (("withoutFirst60s", vidx(t, 0, 1, 0)), ("reverseSecondsRemoved", vidx(t, 0, 0, 1))):
                tc["sensitivities"][nm] = share(ds, win_fn(var, lo, hi), den_fn(var))
            cell["thr%d" % t] = tc
        out.setdefault(s, {})[c] = cell
    return out


def reconcile(rows):
    sc = json.load(open("engine_on_blocks_sidecar.json", encoding="utf-8"))["drives"]
    import ah_throughput as AH
    diffs = []; missing = []
    for d in rows:
        e = sc.get(d["file"]) or sc.get(d["file"].replace("_", " ", 1))
        if e is None:
            missing.append(d["file"]); continue
        diffs.append(int(d["meta"][1, 0, 0]) - int(round(e["eod"][0])))
    a = np.array(diffs)
    return {"comparedDrives": int(len(a)), "equal": int((a == 0).sum()), "medianAbsDiffSeconds": float(np.median(np.abs(a))) if len(a) else None, "maxAbsDiffSeconds": int(np.abs(a).max()) if len(a) else None,
            "missingInSidecar": len(missing), "reading": "disclosure, not a gate: the state-machine grid (1 s mean, carry 3 s) differs from the engine-on rule grid of the sidecar (M543 grid); thr 400, no ramp exclusion"}


def sources():
    p1 = json.load(open("analyses/M704_transcription_pass1.json", encoding="utf-8")); reg = json.load(open("analyses/M704_sources.json", encoding="utf-8"))
    sha = {k: v["sha256"][:16] for k, v in reg["documents"].items()}
    by = {s["id"]: s for s in p1["statements"]}
    def rec(i):
        s = by[i]; return {"id": i, "doc": s["doc"], "pdfPage": s["pdfPage"], "printedPage": s["printedPage"], "quantity": s["quantity"], "paraphrase": s["value"], "sourceSha256Prefix": sha[s["doc"]], "applies": s.get("applies", "X-TRAIL e-POWER")}
    return {"C1": [rec("S1")], "C1b": [rec("S4")], "C2": [rec("S5")], "notComparable80": rec("S3")}


def run_study(out):
    rows = load_drives()
    rows = [d for d in rows if d["cadence"] in STRATA]
    res = {"spec": "analyses/M705_spec.md Rev 1", "seed": SEED, "draws": NB, "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "cacheCodeHash": W.code_hash(),
           "nDrives": len(rows), "nDaysTotal": int(len({d["date"] for d in rows})), "reconciliation": reconcile(rows), "sources": sources(), "c1": build_c1(rows), "c1b": build_c1b(rows), "c2": build_c2(rows)}
    json.dump(res, open(out, "w", encoding="utf-8"), indent=0)
    p = res["c1"]["slow"]["all"]["thr400"]["windows"]["C1_150"]; q = res["c1b"]["slow"]["all"]["thr400"]["ramp5s"]["C1b_lt1500"]
    print(json.dumps({"drives": res["nDrives"], "reconciliation": res["reconciliation"], "C1 slow all thr400 150": {k: p.get(k) for k in ("pct", "ci95", "drives", "days")}, "C1b slow all thr400 r5": {k: q.get(k) for k in ("pct", "ci95")}}))


if __name__ == "__main__":
    if "--study" in sys.argv:
        run_study(sys.argv[sys.argv.index("--study") + 1])
