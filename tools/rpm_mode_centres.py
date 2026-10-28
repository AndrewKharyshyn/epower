#!/usr/bin/env python3
"""M527 (analyses/M527_spec.md Rev 2): recompute the historical M205 / M218 rpm-mode statistics (centres of mass of the ~2000 / ~1500 / ~1589 rpm modes, mass-in-window shares, the old 45/55 split,
background densities) on the live corpus with day-clustered intervals. Sibling payload key rpmModeCentres (+ stamp); nothing else changes.

Per-drive sidecar rpm_mode_centres_sidecar.csv (tracked, keyed by the raw-file SHA-256 AND by rpm_mode_centres_sidecar.meta.json: grid_rpm source hash + window list + bin range; a mismatch rebuilds all):
1 rpm bins [1400, 2100) of the pipeline 1 Hz rpm grid (tools/rpm_opt_band.grid_rpm, imported, not reimplemented), exact per-drive sums and counts of the six pre-registered windows on the 1 Hz grid and
on the native rows (native series: RAW_MAP rename, ffill(limit=15), negatives dropped; row-count weighted; a sensitivity only).
Usage: python tools/rpm_mode_centres.py [--dry-run] [--check] [--rebuild]"""
import copy, datetime, hashlib, inspect, io, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import rpm_opt_band as OB

KEY = "rpmModeCentres"
SIDECAR = os.path.join(ROOT, "rpm_mode_centres_sidecar.csv")
META = os.path.join(ROOT, "rpm_mode_centres_sidecar.meta.json")
SPEC = "analyses/M527_spec.md"
LO, HI = 1400, 2100
WINDOWS = {"c2000": (1975, 2025), "c2000n": (1985, 2015), "c1500": (1475, 1525), "c1500n": (1485, 1515), "c1589": (1564, 1614), "c1589n": (1574, 1604)}
WNAMES = list(WINDOWS)
NB, SEED = 4000, 42
FAITH_TOL_H = 0.002
# historical values (CHANGELOG M205 2026-09-01 at 307 drives; M218 2026-09-04 at 320 drives): stored with their source, no intervals
HISTORICAL = {
    "c2000": {"value": 2000.30, "source": "M205", "drives": 307, "window": [1975, 2025]},
    "c1500n": {"value": 1500.08, "source": "M205", "drives": 307, "window": [1485, 1515]},
    "c1500": {"range": [1499.69, 1500.08], "source": "M218", "drives": 320, "window": [1475, 1525], "note": "window dependent"},
    "c1589": {"range": [1588.62, 1589.29], "source": "M218", "drives": 320, "window": [1564, 1614], "note": "window dependent"},
    "S2_old_edge_split_pct": {"value": [45.3, 54.7], "source": "M205", "drives": 307, "note": "mass of the old 1900-2000 / 2000-2100 bins across the edge at 2000"},
    "S1_M205": {"value": ">96", "source": "M205", "drives": 307, "note": "96 %+ of that window's mass sits within +/-25 rpm of 2000 (ambiguous sentence)"},
    "S1_M218": {"value": ">90", "source": "M218", "drives": 320, "note": "more than 90 % of each spike's own mass in a single 10 rpm sub-bin"},
    "S3_background_s_per_rpm": {"value": {"1400-1475": 10.1, "1525-1564": 21.9, "1614-1975": 29.7}, "source": "M218", "drives": 320},
    "S3_spike_s_per_rpm": {"value": {"1475-1525": 274, "1564-1614": 183}, "source": "M218", "drives": 320},
}


def native_windows(df, cs):
    """native-row series after RAW_MAP / ffill(15) / negatives dropped: (sum, count) per window (a row-count weighted sensitivity)."""
    df = df.rename(columns={k: v for k, v in cs.RAW_MAP.items() if k in df.columns})
    if "eng_rpm" not in df:
        return [(0.0, 0)] * len(WNAMES)
    r = pd.to_numeric(df["eng_rpm"], errors="coerce").ffill(limit=15)
    v = r[r >= 0].dropna().values
    return [(float(v[(v >= a) & (v < b)].sum()), int(((v >= a) & (v < b)).sum())) for a, b in WINDOWS.values()]


def drive_row(raw_bytes, cs):
    df = pd.read_csv(io.BytesIO(raw_bytes), low_memory=False)
    g = OB.grid_rpm(df.copy(), cs)
    if g is None or not len(g[0]):
        return None
    rr = g[0]
    h, _ = np.histogram(rr[(rr >= LO) & (rr < HI)], bins=np.arange(LO, HI + 1))      # half-open [LO, HI): np.histogram closes its LAST bin, so samples exactly at HI must be excluded (found by the faithfulness gate)
    ws = [(float(rr[(rr >= a) & (rr < b)].sum()), int(((rr >= a) & (rr < b)).sum())) for a, b in WINDOWS.values()]
    return len(rr), h.astype(np.int64), ws, native_windows(df, cs)


def cols():
    c = ["file", "sha256", "date", "n_rr"] + ["b%d" % k for k in range(LO, HI)]
    for n in WNAMES:
        c += ["gs_" + n, "gn_" + n]
    for n in WNAMES:
        c += ["ns_" + n, "nn_" + n]
    return c


def meta_now():
    return {"gridRpmSourceSha256": hashlib.sha256(inspect.getsource(OB.grid_rpm).encode("utf-8")).hexdigest(), "windows": {k: list(v) for k, v in WINDOWS.items()}, "binRange": [LO, HI], "binning": "half-open [LO, HI): samples at HI excluded"}


def build_sidecar(dm, rebuild=False):
    import compute_summary_arrays as cs
    import ah_throughput as AH
    load = AH.raw_loader()
    m = meta_now()
    old = {}
    ok_meta = os.path.exists(META) and json.load(open(META, encoding="utf-8")) == m
    if os.path.exists(SIDECAR) and ok_meta and not rebuild:
        sc = pd.read_csv(SIDECAR, dtype={"sha256": str})
        if list(sc.columns) == cols():
            old = sc.set_index("file").to_dict("index")
    rows, reparsed = [], 0
    for f, d in zip(dm["file"], dm["date"]):
        raw = load(f)
        if raw is None:
            continue
        sha = hashlib.sha256(raw).hexdigest()
        prev = old.get(f)
        if prev and prev["sha256"] == sha and str(prev["date"]) == str(d):
            rows.append({"file": f, **prev}); continue
        r = drive_row(raw, cs)
        if r is None:
            continue
        n, h, ws, nw = r
        row = {"file": f, "sha256": sha, "date": d, "n_rr": n}
        row.update({"b%d" % (LO + k): int(h[k]) for k in range(len(h))})
        for nm, (s, c) in zip(WNAMES, ws):
            row["gs_" + nm] = s; row["gn_" + nm] = c
        for nm, (s, c) in zip(WNAMES, nw):
            row["ns_" + nm] = s; row["nn_" + nm] = c
        rows.append(row); reparsed += 1
    sc = pd.DataFrame(rows, columns=cols())
    sc.to_csv(SIDECAR, index=False, lineterminator="\n", float_format="%.6f")
    json.dump(m, open(META, "w", encoding="utf-8", newline="\n"), indent=1)
    return sc, reparsed


def centre(sc, name, prefix, mask=None, nb=NB):
    s = sc[prefix + "s_" + name].values.astype(float); n = sc[prefix + "n_" + name].values.astype(float)
    days = sc["date"].astype(str).values
    if mask is not None:
        s, n, days = s[mask], n[mask], days[mask]
    pt, ci, nd, _ = OB.ratio_ci(s, n, days, nb)
    return {"centre": round(pt, 3), "ci95": [round(ci[0], 3), round(ci[1], 3)], "nSamples": int(n.sum()), "nDrives": int((n > 0).sum()), "nDays": nd}


def mass(B, lo, hi):
    return B[:, lo - LO:hi - LO].sum(axis=1).astype(float)


def excess_share(B, days, flanks, nb=NB):
    """reading (b) of the M205 sentence: window excess over the flank background / excess in [1900, 2100). flanks = ((lo1, hi1), (lo2, hi2)); the density d is the flank mass per rpm."""
    (a1, b1), (a2, b2) = flanks
    d = (mass(B, a1, b1) + mass(B, a2, b2)) / float((b1 - a1) + (b2 - a2))
    pt, ci, nd, _ = OB.ratio_ci(mass(B, 1975, 2025) - 50.0 * d, mass(B, 1900, 2100) - 200.0 * d, days, nb)
    return {"pct": round(100 * pt, 3), "ci95Pct": [round(100 * ci[0], 3), round(100 * ci[1], 3)], "nDays": nd, "backgroundFlanks": [[a1, b1], [a2, b2]]}


def share(B, days, num_lo, num_hi, den_lo, den_hi, nb=NB):
    pt, ci, nd, _ = OB.ratio_ci(mass(B, num_lo, num_hi), mass(B, den_lo, den_hi), days, nb)
    return {"pct": round(100 * pt, 3), "ci95Pct": [round(100 * ci[0], 3), round(100 * ci[1], 3)], "nDays": nd}


def compute(sc, dm, A, nb=NB):
    bc = ["b%d" % k for k in range(LO, HI)]
    B = sc[bc].values.astype(np.int64); days = sc["date"].astype(str).values
    out = {}
    rd = A["rpmDistribution"]; ph = dict(zip(rd["bins"], rd["pooledHours"]))
    edges = [(1400, 1475, "1400-1475"), (1475, 1525, "1475-1525"), (1525, 1564, "1525-1564 (valley)"), (1564, 1614, "1564-1614"), (1614, 1975, "1614-1975 (valley)"), (1975, 2025, "1975-2025"), (2025, 2100, "2025-2100")]
    diffs = {lab: round(abs(round(float(mass(B, a, b).sum()) / 3600.0, 3) - ph[lab]), 6) for a, b, lab in edges}
    win_ok = all(int(sc["gn_" + n].sum()) == int(mass(B, a, b).sum()) for n, (a, b) in WINDOWS.items())
    n_rr = int((sc["n_rr"] > 0).sum())
    out["faithfulness"] = {"maxAbsDiffHours": max(diffs.values()), "tolHours": FAITH_TOL_H, "perBin": diffs, "windowCountsEqualBinSums": bool(win_ok), "driveCountWithRpm": n_rr, "rpmDistributionDriveCount": rd["coverage"]["nDrives"],
                           "driveCountInRange": int((B.sum(axis=1) > 0).sum()),
                           "passed": bool(max(diffs.values()) <= FAITH_TOL_H and win_ok and n_rr == rd["coverage"]["nDrives"])}
    out["centres"] = {n: centre(sc, n, "g", None, nb) for n in WNAMES}
    out["centresNativeRows"] = {n: centre(sc, n, "n", None, nb) for n in WNAMES}
    # per-drive distribution (descriptive): drives with >= 60 samples in the window
    pdm = {}
    for n in WNAMES:
        m = sc["gn_" + n].values >= 60
        v = (sc["gs_" + n].values[m] / sc["gn_" + n].values[m])
        pdm[n] = {"median": round(float(np.median(v)), 3), "p25": round(float(np.percentile(v, 25)), 3), "p75": round(float(np.percentile(v, 75)), 3), "nDrives": int(m.sum())}
    out["perDriveCentre"] = pdm
    # shares (S1 a/b, S2) with day-clustered intervals
    s1a = share(B, days, 1975, 2025, 1900, 2100, nb)
    # reading (b): PRE-REGISTERED flanks [1900,1975)+[2025,2100) (Rev 1 sec. 1). With these flanks the excess share is 100 % by construction (the flanks carry no excess by definition): reported, uninformative.
    s1b = excess_share(B, days, ((1900, 1975), (2025, 2100)), nb)
    # labelled deviation (Director review of the first output): OUTER flanks [1900,1950)+[2050,2100) as the informative variant
    s1b_outer = excess_share(B, days, ((1900, 1950), (2050, 2100)), nb)
    s2 = share(B, days, 1900, 2000, 1900, 2100, nb)
    best10 = {}
    for n in ("c2000", "c1500", "c1589"):
        a, b = WINDOWS[n]; cnt = B[:, a - LO:b - LO].sum(axis=0).astype(float); tot = cnt.sum()
        sl = [cnt[i:i + 10].sum() for i in range(len(cnt) - 9)]
        best10[n] = {"pct": round(100 * max(sl) / tot, 2), "startRpm": int(a + int(np.argmax(sl)))}
    out["shares"] = {"S1a_window_over_1900_2100_pct": s1a, "S1b_preregistered_flanks_pct_100_by_construction": s1b, "S1b_outer_flank_variant_pct_labelled_deviation": s1b_outer, "S2_1900_2000_over_1900_2100_pct": s2, "S1_M218_best_10rpm_subbin_of_window_mass": best10}
    dens = {}
    for a, b, lab in [(1400, 1475, "1400-1475"), (1525, 1564, "1525-1564"), (1614, 1975, "1614-1975"), (1475, 1525, "1475-1525 (spike)"), (1564, 1614, "1564-1614 (spike)"), (1975, 2025, "1975-2025 (spike)")]:
        dens[lab] = round(float(mass(B, a, b).sum()) / (b - a), 2)
    out["densitiesSecondsPerRpm"] = dens
    # sensitivities: regime periods, canonical-outlier exclusion, historical subsets
    cr = pd.read_csv(os.path.join(ROOT, "cadence_regime.csv")).set_index("file")["regime"]
    reg = sc["file"].map(cr).values
    out["pollingRegimePeriods"] = {lab: {n: centre(sc, n, "g", reg == lab, nb) for n in ("c2000", "c1500", "c1589")} for lab in ("slow", "fast")}
    ex = dm.set_index("file")["ens_outlier_v2"].reindex(sc["file"]).fillna(False).astype(bool).values
    out["ensOutlierV2Excluded"] = {n: centre(sc, n, "g", ~ex, nb) for n in ("c2000", "c1500", "c1589")}
    order = np.lexsort((sc["file"].values, sc["date"].astype(str).values))
    hist = {}
    for nm, k in (("first307_M205", 307), ("first320_M218", 320)):
        mk = np.zeros(len(sc), dtype=bool); mk[order[:k]] = True
        Bm, dm_ = B[mk], days[mk]
        s1b_o = excess_share(Bm, dm_, ((1900, 1950), (2050, 2100)), nb)
        s1b_p = excess_share(Bm, dm_, ((1900, 1975), (2025, 2100)), nb)
        b10 = {}
        for n in ("c2000", "c1500", "c1589"):
            a_, b_ = WINDOWS[n]; cnt = Bm[:, a_ - LO:b_ - LO].sum(axis=0).astype(float)
            b10[n] = round(100 * max(cnt[i:i + 10].sum() for i in range(len(cnt) - 9)) / cnt.sum(), 2)
        # shares on the historical subsets (added to the output after the first run: required by the Director Q1 ruling; computed from the same sidecar, no re-parse)
        hist[nm] = {"drives": int(mk.sum()), "lastDate": str(sc["date"].values[order[k - 1]]), **{n: centre(sc, n, "g", mk, nb) for n in WNAMES},
                    "shares": {"S1a_pct": share(Bm, dm_, 1975, 2025, 1900, 2100, nb), "S1b_preregistered_flanks_pct": s1b_p, "S1b_outer_flank_variant_pct": s1b_o,
                               "S2_pct": share(Bm, dm_, 1900, 2000, 1900, 2100, nb), "best10rpmSubbinPct": b10}}
    out["historicalSubsets"] = hist
    # tripwires (A4; descriptive flags for the Director, not tests)
    tw = {}
    live = out["centres"]
    for n, h in (("c2000", HISTORICAL["c2000"]["value"]), ("c1500n", HISTORICAL["c1500n"]["value"])):
        tw["centre_vs_historical_" + n] = {"diffRpm": round(live[n]["centre"] - h, 3), "outsideLiveCI": bool(not (live[n]["ci95"][0] <= h <= live[n]["ci95"][1])), "over1rpm": bool(abs(live[n]["centre"] - h) > 1.0)}
    for n, rg in (("c1500", HISTORICAL["c1500"]["range"]), ("c1589", HISTORICAL["c1589"]["range"])):
        tw["centre_vs_historical_" + n] = {"outsideHistoricalRange": bool(not (rg[0] - 1.0 <= live[n]["centre"] <= rg[1] + 1.0)), "diffToNearestEndRpm": round(min(abs(live[n]["centre"] - rg[0]), abs(live[n]["centre"] - rg[1])), 3)}
    tw["S2_diff_pp"] = round(s2["pct"] - 45.3, 3)
    tw["S1a_vs_96_pp"] = round(s1a["pct"] - 96.0, 3); tw["S1b_outer_vs_96_pp"] = round(s1b_outer["pct"] - 96.0, 3); tw["S1_readings_disagree_pp"] = round(abs(s1a["pct"] - s1b_outer["pct"]), 3)
    tw["pooled_vs_per_drive_median_over1rpm"] = {n: bool(abs(out["centres"][n]["centre"] - pdm[n]["median"]) > 1.0) for n in ("c2000", "c1500", "c1589")}
    tw["outlier_exclusion_shift_over0p5rpm"] = {n: bool(abs(out["ensOutlierV2Excluded"][n]["centre"] - live[n]["centre"]) > 0.5) for n in ("c2000", "c1500", "c1589")}
    tw["regime_difference_over1rpm"] = {n: bool(abs(out["pollingRegimePeriods"]["slow"][n]["centre"] - out["pollingRegimePeriods"]["fast"][n]["centre"]) > 1.0) for n in ("c2000", "c1500", "c1589")}
    out["tripwires"] = tw
    return out


def rpm_resolution():
    """grid step of the engine rpm channel across the files recorded in signal_representation.json (the 1 Hz means smear the native quantisation; native rows are integers when the step is 1)."""
    p = os.path.join(ROOT, "signal_representation.json")
    if not os.path.exists(p):
        return {"status": "not_available"}
    d = json.load(open(p, encoding="utf-8"))
    steps = {}
    for fn, rec in (d.get("files") or {}).items():
        ch = (rec.get("channels") or {}).get("Оберти двигуна (rpm)")
        if ch and ch.get("grid_step") is not None:
            steps[str(ch["grid_step"])] = steps.get(str(ch["grid_step"]), 0) + 1
    return {"status": "ok", "source": "signal_representation.json", "filesWithChannel": int(sum(steps.values())), "gridStepCounts": steps}


def build_block(dm, A, nb=NB, rebuild=False):
    sc, reparsed = build_sidecar(dm, rebuild)
    r = compute(sc, dm, A, nb)
    sha = lambda p: hashlib.sha256(open(os.path.join(ROOT, p), "rb").read()).hexdigest()
    return {"estimand": "duration-weighted centre of mass (mean logged engine rpm of the 1 Hz grid samples) of the ~2000, ~1500 and ~1589 rpm modes in pre-registered windows, mass-in-window shares and the old 45/55 split, pooled over drives",
            "basis": "observed occupancy of logged engine rpm (ECU-reported via the logging app, resampled to 1 s means, ffill limit 15 s); the rpm channel resolution is 1 rpm; not a measured setpoint, not an efficiency or optimum claim",
            "descriptive": True, "displayed": False, "rpmChannelResolution": rpm_resolution(), "windows": {k: list(v) for k, v in WINDOWS.items()}, "historical": HISTORICAL, **r,
            "deviationFromHistoricalPass": "M205/M218 replayed the 1 Hz grid at 5 rpm resolution on the archive of that date; this pass uses 1 rpm bins plus exact window sums on the sha256-verified originals (M366); historical values carry no intervals",
            "limits": ["window ranges are window dependence, not uncertainty", "day bootstrap does not capture serial day correlation", "the polling-regime split is confounded with calendar date, season and ambient", "the faithfulness gate shares grid_rpm and tests the sidecar plumbing, not fidelity to raw (the blind audit implements the convention independently)"],
            "provenance": {"spec": SPEC, "specSha256": sha(SPEC), "toolSha256": sha("tools/rpm_mode_centres.py"), "sidecar": "rpm_mode_centres_sidecar.csv", "sidecarSha256": sha("rpm_mode_centres_sidecar.csv"),
                           "masterMd5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest(), "reparsedDrives": reparsed}}


def splice(A, blk, master_md5="", now=None):
    new = copy.deepcopy(A)
    new[KEY] = blk
    old = (A.get("_artifactStamps") or {}).get(KEY)
    if old and A.get(KEY) == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"][KEY] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M527: derived by tools/rpm_mode_centres.py from drive_master.csv, the raw drive files through rpm_mode_centres_sidecar.csv (keyed by raw sha256) and the stored rpmDistribution (faithfulness gate)",
                  upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
        import stamp_common as _sc
        new["_artifactStamps"][KEY] = _sc.carry_declared(old, st)
    ch = [k for k in set(A) | set(new) if A.get(k) != new.get(k)]
    bad = [k for k in ch if k not in (KEY, "_artifactStamps")]
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
        print(json.dumps({"check": "rpmModeCentres", "matchesPayload": keep(have) == keep(blk)}))
        return 0 if keep(have) == keep(blk) else 1
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    new, ch, bad = splice(A, blk, md5)
    res = os.path.join("analyses", "M527_result.json")
    if not os.path.exists(res):                                    # run-once lock: the first output is kept
        json.dump(blk, open(res, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False)
    print(json.dumps({"centres": {k: (v["centre"], v["ci95"]) for k, v in blk["centres"].items()}, "faithfulness": blk["faithfulness"]["passed"], "nChanged": len(ch), "outsideAllowList": bad}))
    if bad:
        return 1
    if "--dry-run" not in argv and ch:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + (chr(10) if raw_txt.endswith(chr(10)) else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
