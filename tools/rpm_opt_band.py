#!/usr/bin/env python3
"""M525 (analyses/M525_spec.md Rev 2): OPT-band occupancy of logged engine rpm on the live corpus, with a day-clustered interval. Sibling payload key rpmOptBand (+ stamp); nothing else changes.

Estimand: duration-weighted share of ENGINE-ON time (rpm >= 300 on the 1 Hz grid, the rpmDistribution convention) with logged rpm in the CLOSED band [OPT_LO, OPT_HI] = [1850, 2150]
(model_constants), pooled over the drives of the master. Observed occupancy of a logged signal; not an efficiency or optimum-operation claim.

Per-drive fine-bin counts come from a tracked sidecar (rpm_opt_band_sidecar.csv) keyed by the raw-file SHA-256: only new or changed drives are re-parsed. The 1 Hz grid is built exactly as
compute_summary_arrays._RawAccum.add does for rpmDistribution (RAW_MAP rename, _ft time, ffill(limit=15) on the native series, resample('1s').mean(), ffill(limit=15)).

Usage: python tools/rpm_opt_band.py [--dry-run] [--check] [--rebuild]   (--dry-run writes analyses/M525_result.json only; without it the payload key and stamp are spliced)"""
import copy, datetime, hashlib, io, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

KEY = "rpmOptBand"
SIDECAR = os.path.join(ROOT, "rpm_opt_band_sidecar.csv")
SPEC = "analyses/M525_spec.md"
EXTRA_EDGES = [1750, 1800, 1900, 2100, 2200, 2250]       # pre-registered (M525 Rev 2 Q3)
NB, SEED = 4000, 42
FAITH_TOL_H = 0.002
BANDS = {"primary": (1850.0, 2150.0), "narrow50": (1900.0, 2100.0), "wide50": (1800.0, 2200.0), "wide100": (1750.0, 2250.0)}


def fine_edges(hist_edges, opt_lo, opt_hi):
    return sorted(set(hist_edges) | {opt_lo, opt_hi} | set(EXTRA_EDGES))


def grid_rpm(df, cs):
    """1 Hz rpm series of one drive, byte-faithful to _RawAccum.add (rpmDistribution)."""
    df = df.rename(columns={k: v for k, v in cs.RAW_MAP.items() if k in df.columns})
    if "time" not in df or "eng_rpm" not in df:
        return None
    t = cs._ft(df["time"], mixed=True)
    n_back = int((t.diff().dt.total_seconds() < 0).sum())       # read-only order check: the time column has no date, a midnight-crossing drive would go backwards (shared with rpmDistribution)
    rpm = pd.to_numeric(df["eng_rpm"], errors="coerce").ffill(limit=15)
    rpm = rpm.where(rpm >= 0)
    g1 = pd.DataFrame({"t": t, "eng_rpm": rpm.values}).dropna(subset=["t"]).set_index("t")
    hz = g1.resample("1s").mean().ffill(limit=15)
    return hz["eng_rpm"].dropna().values, n_back


def drive_counts(rr, edges, opt_hi):
    """(fine counts, samples exactly at opt_hi, total samples) for one drive's 1 Hz rpm values."""
    h, _ = np.histogram(rr, bins=edges)
    return h.astype(np.int64), int((rr == opt_hi).sum()), int(len(rr))


def between(counts, edges, lo, hi):
    """sum of the fine bins [edges[k], edges[k+1]) with lo <= edges[k] and edges[k+1] <= hi (columns of a 2-D or 1-D count array)."""
    ks = [k for k in range(len(edges) - 1) if edges[k] >= lo and edges[k + 1] <= hi]
    return counts[..., ks].sum(axis=-1)


def ratio_ci(num, den, days, nb=NB, seed=SEED):
    """pooled ratio of sums and a day-clustered percentile bootstrap interval (calendar day = cluster; ratio of sums inside every draw)."""
    ud, inv = np.unique(np.asarray(days), return_inverse=True)
    dn = np.bincount(inv, weights=num, minlength=len(ud)); dd = np.bincount(inv, weights=den, minlength=len(ud))
    pt = float(dn.sum() / dd.sum()) if dd.sum() > 0 else float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(ud), (nb, len(ud)))
    d_s = dd[idx].sum(1); ok = d_s > 0
    r = dn[idx].sum(1)[ok] / d_s[ok]
    lo, hi = np.percentile(r, [2.5, 97.5])
    return pt, [float(lo), float(hi)], int(len(ud)), int((~ok).sum())


def load_sidecar(edges):
    cols = ["file", "sha256", "date", "n_rr", "eq_hi", "n_back"] + ["b%d" % k for k in range(len(edges) - 1)]
    if os.path.exists(SIDECAR):
        sc = pd.read_csv(SIDECAR, dtype={"sha256": str})
        if list(sc.columns) == cols:
            return sc.set_index("file").to_dict("index"), cols
    return {}, cols


def build_sidecar(dm, edges, opt_hi, rebuild=False):
    import compute_summary_arrays as cs
    import ah_throughput as AH
    load = AH.raw_loader()
    old, cols = ({}, None) if rebuild else load_sidecar(edges)
    if cols is None:
        cols = ["file", "sha256", "date", "n_rr", "eq_hi", "n_back"] + ["b%d" % k for k in range(len(edges) - 1)]
    rows, reparsed = [], 0
    for f, d in zip(dm["file"], dm["date"]):
        raw = load(f)
        if raw is None:
            continue
        sha = hashlib.sha256(raw).hexdigest()
        prev = old.get(f)
        if prev and prev["sha256"] == sha and str(prev["date"]) == str(d):
            rows.append({"file": f, **prev}); continue
        g = grid_rpm(pd.read_csv(io.BytesIO(raw), low_memory=False), cs)
        if g is None or not len(g[0]):
            continue
        rr, nb_ = g
        h, eq, n = drive_counts(rr, edges, opt_hi)
        rows.append({"file": f, "sha256": sha, "date": d, "n_rr": n, "eq_hi": eq, "n_back": nb_, **{"b%d" % k: int(h[k]) for k in range(len(h))}})
        reparsed += 1
    sc = pd.DataFrame(rows, columns=cols)
    sc.to_csv(SIDECAR, index=False, lineterminator="\n")
    return sc, reparsed


def compute(sc, dm, A, hist_edges, edges, opt_lo, opt_hi, nb=NB):
    bcols = [c for c in sc.columns if c.startswith("b")]
    C = sc[bcols].values.astype(np.int64)
    eq = sc["eq_hi"].values.astype(np.int64)
    days = sc["date"].astype(str).values
    on = between(C, edges, 300.0, 1e9)                    # engine-on seconds per drive (bins above the 0-300 bin; the last bin is the top bin)
    out = {}
    # faithfulness gate: fine bins collapsed to RPM_HIST_EDGES reproduce the stored rpmDistribution.pooledHours; drive count equals coverage
    rd = A["rpmDistribution"]
    coarse = [float(between(C.sum(0), edges, hist_edges[i], hist_edges[i + 1])) / 3600.0 for i in range(len(hist_edges) - 1)]
    ph = rd["pooledHours"]
    diffs = [abs(round(c, 3) - p) for c, p in zip(coarse, ph)]
    n_with = int((sc["n_rr"] > 0).sum())
    out["timeOrder"] = {"drivesWithBackwardsTime": int((sc["n_back"] > 0).sum()), "nDrives": int(len(sc)), "note": "read-only count; the time column has no date, so a midnight-crossing drive would go backwards; same convention as rpmDistribution"}
    out["faithfulness"] = {"maxAbsDiffHours": round(max(diffs), 6), "tolHours": FAITH_TOL_H, "nBins": len(ph), "driveCount": n_with, "storedDriveCount": rd["coverage"]["nDrives"],
                           "passed": bool(max(diffs) <= FAITH_TOL_H and n_with == rd["coverage"]["nDrives"])}
    # primary (closed band [lo, hi]: half-open fine bins plus the samples exactly at hi)
    def band(lo, hi, closed=False):
        b = between(C, edges, lo, hi)
        return b + eq if closed else b
    pb = band(opt_lo, opt_hi, True)
    pt, ci, nd, nbad = ratio_ci(pb, on, days, nb)
    out["primary"] = {"pct": round(100 * pt, 3), "ci95Pct": [round(100 * ci[0], 3), round(100 * ci[1], 3)], "nDrives": int((on > 0).sum()), "nDays": nd, "nDaysWithEngineOn": int(len(np.unique(days[on > 0]))),
                      "engineOnSeconds": int(on.sum()), "bandSeconds": int(pb.sum()), "band": [opt_lo, opt_hi], "bootstrap": {"B": nb, "seed": SEED, "unit": "calendar day", "degenerateDraws": nbad}}
    share = pb[on > 0] / on[on > 0]
    out["perDrive"] = {"median": round(100 * float(np.median(share)), 2), "p25": round(100 * float(np.percentile(share, 25)), 2), "p75": round(100 * float(np.percentile(share, 75)), 2), "n": int(len(share))}
    # anchored secondary (rpm_opt_pass formula on the stored pooled hours; sub-bin shares from this pass)
    cnt = C.sum(0)
    bins = dict(zip(rd["bins"], ph))
    s1 = float(between(cnt, edges, 1850, 1975)) / float(between(cnt, edges, 1614, 1975))
    s2 = float(between(cnt, edges, 2100, 2150)) / float(between(cnt, edges, 2100, 2400))
    opt_h = bins["1975-2025"] + bins["2025-2100"] + s1 * bins["1614-1975 (valley)"] + s2 * bins["2100-2400"]
    eon_h = sum(v for k, v in bins.items() if k != "0 (engine off)")
    anch = 100 * opt_h / eon_h
    out["anchored"] = {"pct": round(anch, 3), "diffVsDirectPp": round(anch - 100 * pt, 3), "note": "stored pooled hours + raw sub-bin shares; the direct ratio is primary"}
    # edge sensitivity (band-definition range, not a CI; half-open fine bins)
    out["edgeSensitivity"] = {k: round(100 * float(band(lo, hi).sum()) / float(on.sum()), 3) for k, (lo, hi) in BANDS.items() if k != "primary"}
    # cadence regime (slow / fast logger; unlabelled drives excluded) and the canonical exclusion
    cr = pd.read_csv(os.path.join(ROOT, "cadence_regime.csv")).set_index("file")["regime"]
    reg = sc["file"].map(cr).values
    strata = {}
    for lab in ("slow", "fast"):
        m = reg == lab
        if m.sum() and on[m].sum() > 0:
            p, c, d, _ = ratio_ci(pb[m], on[m], days[m], nb)
            strata[lab] = {"pct": round(100 * p, 3), "ci95Pct": [round(100 * c[0], 3), round(100 * c[1], 3)], "nDrives": int((on[m] > 0).sum()), "nDays": d}
    out["cadenceStrata"] = strata
    ex = dm.set_index("file")["ens_outlier_v2"].reindex(sc["file"]).fillna(False).astype(bool).values
    p, c, d, _ = ratio_ci(pb[~ex], on[~ex], days[~ex], nb)
    out["ensOutlierV2Excluded"] = {"pct": round(100 * p, 3), "ci95Pct": [round(100 * c[0], 3), round(100 * c[1], 3)], "nDrives": int((on[~ex] > 0).sum()), "nDays": d, "nExcluded": int(ex.sum())}
    return out


def build_block(dm, A, now=None, nb=NB, rebuild=False):
    import compute_summary_arrays as cs
    import model_constants as MC
    hist_edges = list(cs.RPM_HIST_EDGES)
    edges = fine_edges(hist_edges, MC.OPT_LO, MC.OPT_HI)
    sc, reparsed = build_sidecar(dm, edges, MC.OPT_HI, rebuild)
    r = compute(sc, dm, A, hist_edges, edges, MC.OPT_LO, MC.OPT_HI, nb)
    sha = lambda p: hashlib.sha256(open(os.path.join(ROOT, p), "rb").read()).hexdigest()
    blk = {"estimand": "duration-weighted share of engine-on time (rpm >= 300, 1 Hz grid) with logged rpm in the closed band [1850, 2150] (model_constants OPT_LO/OPT_HI), pooled over drives",
           "basis": "observed occupancy of logged engine rpm; not an efficiency, BSFC or optimum-operation claim; the band edges come from external OEM context",
           "descriptive": True, "displayed": False, "supersedes": "generatorTractionRecon.rpmFinding (numeric leaves; 410-drive one-off pass)", **r,
           "limits": ["day bootstrap does not capture serial day correlation", "rpm is ECU-reported via the logging app and resampled to 1 s means (ffill limit 15 s)", "band edges are external OEM context"],
           "provenance": {"spec": SPEC, "specSha256": sha(SPEC), "toolSha256": sha("tools/rpm_opt_band.py"), "sidecar": "rpm_opt_band_sidecar.csv", "sidecarSha256": sha("rpm_opt_band_sidecar.csv"),
                          "masterMd5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest(), "reparsedDrives": reparsed}}
    return blk


def splice(A, blk, master_md5="", now=None):
    new = copy.deepcopy(A)
    new[KEY] = blk
    rf = (new.get("generatorTractionRecon") or {}).get("rpmFinding")
    if isinstance(rf, dict):                                      # the only change to an existing block: a label; the numeric leaves stay byte-unchanged
        rf["supersededBy"] = KEY
        rf["supersededNote"] = "numeric leaves are the one-off 410-drive pass (397 drives with engine-on time) and are not refreshed; the live occupancy with a day-clustered interval is in rpmOptBand (M525)"
    old = (A.get("_artifactStamps") or {}).get(KEY)
    if old and A.get(KEY) == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"][KEY] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M525: derived by tools/rpm_opt_band.py from drive_master.csv, the raw drive files through rpm_opt_band_sidecar.csv (keyed by raw sha256) and the stored rpmDistribution (faithfulness gate)",
                  upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
        import stamp_common as _sc
        new["_artifactStamps"][KEY] = _sc.carry_declared(old, st)
    ch = [k for k in set(A) | set(new) if A.get(k) != new.get(k)]
    bad = [k for k in ch if k not in (KEY, "_artifactStamps", "generatorTractionRecon")]
    gb, ga = (A.get("generatorTractionRecon") or {}), (new.get("generatorTractionRecon") or {})
    for k in set(gb) | set(ga):
        if k != "rpmFinding" and gb.get(k) != ga.get(k):
            bad.append("generatorTractionRecon." + k)
    rb, ra = (gb.get("rpmFinding") or {}), (ga.get("rpmFinding") or {})
    for k in set(rb) | set(ra):
        if k not in ("supersededBy", "supersededNote") and rb.get(k) != ra.get(k):
            bad.append("generatorTractionRecon.rpmFinding." + k)
    st_bad = [k for k in set(A["_artifactStamps"]) | set(new["_artifactStamps"]) if A["_artifactStamps"].get(k) != new["_artifactStamps"].get(k) and k != KEY]
    return new, ch, bad + st_bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    raw_txt = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A = json.loads(raw_txt)
    blk = build_block(dm, A, rebuild="--rebuild" in argv)
    if not blk["faithfulness"]["passed"]:
        print(json.dumps({"STOP": "faithfulness gate failed", "faithfulness": blk["faithfulness"]}))
        return 1
    if "--check" in argv:
        have = A.get(KEY)
        keep = lambda b: {k: v for k, v in (b or {}).items() if k != "provenance"}
        print(json.dumps({"check": "rpmOptBand", "matchesPayload": keep(have) == keep(blk)}))
        return 0 if keep(have) == keep(blk) else 1
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    new, ch, bad = splice(A, blk, md5)
    res = os.path.join("analyses", "M525_result.json")
    if not os.path.exists(res):                                    # run-once lock: the first output is kept
        json.dump(blk, open(res, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False)
    print(json.dumps({"primary": blk["primary"], "anchored": blk["anchored"], "faithfulness": blk["faithfulness"], "nChanged": len(ch), "outsideAllowList": bad}))
    if bad:
        return 1
    if "--dry-run" not in argv and ch:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + (chr(10) if raw_txt.endswith(chr(10)) else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
