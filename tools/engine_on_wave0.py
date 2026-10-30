#!/usr/bin/env python3
"""M536 wave 0 (analyses/M536_spec.md section 9): evidence only, no payload key, no stage, no figure change.
(1) hold-limit sweep: the forward-fill limit set to L = 0, 5, 15 s at BOTH pipeline stages (native-row ffill and 1 Hz grid ffill; 15 = the pipeline); per drive: seconds in the resampled range, valid seconds, missing seconds
(NaN, separated from rpm = 0 seconds), seconds with rpm >= 300, > 400, >= 400 and in the 300-400 band. Per-drive sidecar engine_on_wave0_sidecar.csv (tracked; keyed by the raw-file SHA-256 and by
engine_on_wave0_sidecar.meta.json: source hash of wave0_row + the limits). Faithfulness: L = 15 equals the phase-1 sidecar (engine_on_evidence_sidecar.csv); STOP on mismatch.
(2) day-clustered intervals (seed 42, 4000 draws, ratio of sums) of the threshold term and the integration term, (3) hysteresis vs the plain > 400 rule, both from the phase-1 sidecar, (4) the code trace of the three producers
listed as unresolved (static, with file and line). Output analyses/M536_wave0.json (first output kept). Usage: python tools/engine_on_wave0.py [--build] [--rebuild]"""
import hashlib, inspect, io, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

SIDECAR = os.path.join(ROOT, "engine_on_wave0_sidecar.csv")
META = os.path.join(ROOT, "engine_on_wave0_sidecar.meta.json")
P1 = os.path.join(ROOT, "engine_on_evidence_sidecar.csv")
OUT = os.path.join(ROOT, "analyses", "M536_wave0.json")
SPEC = "analyses/M536_spec.md"
LIMITS = (0, 5, 15)
NB, SEED = 4000, 42
STAT = ("total", "valid", "zero", "ge300", "gt400", "ge400", "band")


def _ff(s, L):
    return s if L == 0 else s.ffill(limit=L)


def wave0_row(csv_bytes, cs):
    df = pd.read_csv(io.BytesIO(csv_bytes), low_memory=False)
    df = df.rename(columns={k: v for k, v in cs.RAW_MAP.items() if k in df.columns})
    if "time" not in df or "eng_rpm" not in df:
        return None
    t = cs._ft(df["time"], mixed=True)
    base = pd.to_numeric(df["eng_rpm"], errors="coerce")
    row = {}
    for L in LIMITS:
        rpm = _ff(base, L)
        rpm = rpm.where(rpm >= 0)
        g1 = pd.DataFrame({"t": t, "eng_rpm": rpm.values}).dropna(subset=["t"]).set_index("t")
        hz = _ff(g1.resample("1s").mean(), L)["eng_rpm"].values.astype(float)
        ok = ~np.isnan(hz); rz = np.nan_to_num(hz, nan=-1.0)
        row.update({"L%d_total" % L: int(len(hz)), "L%d_valid" % L: int(ok.sum()), "L%d_zero" % L: int((hz == 0).sum()), "L%d_ge300" % L: int((rz >= 300).sum()), "L%d_gt400" % L: int((rz > 400).sum()),
                    "L%d_ge400" % L: int((rz >= 400).sum()), "L%d_band" % L: int(((rz >= 300) & (rz < 400)).sum())})
    return row if row["L15_valid"] else None


def _src():
    return hashlib.sha256((inspect.getsource(wave0_row) + inspect.getsource(_ff) + repr(LIMITS)).encode()).hexdigest()


def build(dm, rebuild=False):
    import compute_summary_arrays as cs
    import ah_throughput as AH
    load = AH.raw_loader(); src = _src()
    meta = json.load(open(META, encoding="utf-8")) if os.path.exists(META) else {}
    old = {}
    if not rebuild and os.path.exists(SIDECAR) and meta.get("rowFnSha256") == src:
        old = pd.read_csv(SIDECAR, dtype={"sha256": str}).set_index("file").to_dict("index")
    rows, rep = [], 0
    for f, d in zip(dm["file"], dm["date"]):
        raw = load(f)
        if raw is None:
            continue
        sha = hashlib.sha256(raw).hexdigest(); prev = old.get(f)
        if prev and prev["sha256"] == sha:
            rows.append({"file": f, **prev}); continue
        r = wave0_row(raw, cs)
        if r is None:
            continue
        rows.append({"file": f, "sha256": sha, "date": d, **r}); rep += 1
    sc = pd.DataFrame(rows)
    sc.to_csv(SIDECAR, index=False, lineterminator="\n")
    json.dump({"rowFnSha256": src, "limits": list(LIMITS), "note": "evidence only (M536 wave 0)"}, open(META, "w", encoding="utf-8", newline=chr(10)), indent=1)
    return sc, rep


def ratio_ci(num, den, days, nb=NB, seed=SEED):
    ud, inv = np.unique(np.asarray(days), return_inverse=True)
    dn = np.bincount(inv, weights=num, minlength=len(ud)); dd = np.bincount(inv, weights=den, minlength=len(ud))
    pt = float(dn.sum() / dd.sum())
    idx = np.random.default_rng(seed).integers(0, len(ud), (nb, len(ud)))
    ds = dd[idx].sum(1); ok = ds > 0
    r = dn[idx].sum(1)[ok] / ds[ok]
    lo, hi = np.percentile(r, [2.5, 97.5])
    return {"pct": round(100 * pt, 4), "ci95Pct": [round(100 * float(lo), 4), round(100 * float(hi), 4)], "nDays": int(len(ud))}


TRACE = {
    "rpmFinding": {"payload": "generatorTractionRecon.rpmFinding", "producer": "rpm_opt_pass.py (one-off 410-drive pass)", "rule": "engine-on = rpm >= 300 on the pipeline 1 Hz grid (all RPM_HIST bins but [0,300))",
                   "evidence": "rpm_opt_pass.py lines 19-25 (grid), 39-40 (RPM_HIST_EDGES [0, 300, 1400, ...]), 75-87 (anchored to the stored rpmDistribution bin totals)", "family": "B1 (>= 300, 1 Hz grid, duration weighted)",
                   "status": "traced; numeric leaves are the 410-drive pass, not refreshed, superseded by rpmOptBand (M525, also B1); migrates with the B1 family"},
    "simultaneity": {"payload": "generatorTractionRecon.simultaneity", "producer": "simultaneity_gtr.py", "rule": "engine-on second = reconstructed generator power Pgen_t > 0 (eon = Pg > 0.0), weighted by dt",
                     "evidence": "simultaneity_gtr.py line 8 (docstring) and lines 96-103 (eon = Pg > 0.0)", "family": "generator-active (reconstructed Pgen > 0): NOT an rpm rule",
                     "status": "traced; stays a separately named concept (generator-active), never migrates to an rpm threshold; its engineOnHours leaf is generator-active hours"},
    "engineStateMachine": {"payload": "engineStateMachine", "producer": "compute_summary_arrays._engine_state_machine / _esm_classify / _esm_grid", "rule": "per-second state on a 1 Hz grid: off rpm < 400, low 400-1400, loadPoint 1400-2300, mid 2300-3200, high >= 3200 (boundaries >=); NaN rpm seconds excluded (state -1)",
                           "evidence": "compute_summary_arrays.py line 11238 (_ESM_EDGES = [400, 1400, 2300, 3200]), lines 11271-11278 (_esm_classify: rpm >= edge, non-finite -> -1)", "family": "400 family with a >= boundary on the 1 Hz grid (engine_runtime uses > 400 on intervals)",
                     "status": "traced; the boundary differs from engine_runtime (> 400 vs >= 400); 5 seconds at exactly 400 rpm in a 20-drive sample"}}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    if "--build" in argv or not os.path.exists(SIDECAR):
        sc, rep = build(dm, "--rebuild" in argv); print("sidecar rows", len(sc), "reparsed", rep)
    sc = pd.read_csv(SIDECAR, dtype={"sha256": str}); p1 = pd.read_csv(P1, dtype={"sha256": str})
    m = sc.merge(p1[["file", "grid_valid_s", "g_ge300", "g_gt400", "band_300_400_s", "grid_total_s", "grid_zero_s", "int_gt400", "hyst_hold1_s", "hyst_hold2_s", "hyst_hold3_s", "hyst_hold5_s"]], on="file", how="inner")
    a1 = bool((m["L15_valid"] == m["grid_valid_s"]).all() and (m["L15_ge300"] == m["g_ge300"]).all() and (m["L15_gt400"] == m["g_gt400"]).all() and (m["L15_band"] == m["band_300_400_s"]).all()
              and (m["L15_total"] == m["grid_total_s"]).all() and (m["L15_zero"] == m["grid_zero_s"]).all() and len(m) == len(sc) == len(p1))
    if not a1:
        print(json.dumps({"STOP": "L = 15 does not reproduce the phase-1 sidecar"})); return 1
    reg = pd.read_csv("cadence_regime.csv").set_index("file")["regime"]
    sc["regime"] = sc["file"].map(reg).fillna("unlabelled")
    H = lambda c, d=sc: float(d[c].sum()) / 3600.0
    b1 = H("L15_ge300")
    out = {"nDrives": int(len(sc)), "a1_L15_reproducesPhase1": a1, "holdLimitSweep": {}}
    for L in LIMITS:
        out["holdLimitSweep"]["L%d" % L] = {"totalHours": round(H("L%d_total" % L), 4), "validHours": round(H("L%d_valid" % L), 4), "missingHours": round(H("L%d_total" % L) - H("L%d_valid" % L), 4), "zeroHours": round(H("L%d_zero" % L), 4),
                                            "ge300_h": round(H("L%d_ge300" % L), 4), "gt400_h": round(H("L%d_gt400" % L), 4), "ge400_h": round(H("L%d_ge400" % L), 4), "band_h": round(H("L%d_band" % L), 4),
                                            "ge300_changeVsL15_pctOfB1": round(100 * (H("L%d_ge300" % L) - b1) / b1, 4), "gt400_changeVsL15_pctOfB1": round(100 * (H("L%d_gt400" % L) - H("L15_gt400")) / b1, 4)}
    strata = {}
    for g, s in sc.groupby("regime"):
        strata[g] = {"nDrives": int(len(s))}
        for L in LIMITS:
            tot = float(s["L%d_total" % L].sum())
            strata[g]["L%d" % L] = {"missingPctOfSeconds": round(100 * (tot - float(s["L%d_valid" % L].sum())) / tot, 3), "bandPctOfGe300": round(100 * float(s["L%d_band" % L].sum()) / max(1.0, float(s["L%d_ge300" % L].sum())), 3)}
    out["byCadenceRegime"] = strata
    d = p1
    d = d.assign(thr=d["g_ge300"] - d["g_gt400"]).dropna(subset=["int_gt400"]); d = d.assign(integ=d["g_gt400"] - d["int_gt400"] * 1.0)
    out["intervals"] = {"thresholdTermPctOfGe300": ratio_ci(d["thr"].values.astype(float), d["g_ge300"].values.astype(float), d["date"].values),
                        "integrationTermPctOfGt400": ratio_ci(d["integ"].values.astype(float), d["g_gt400"].values.astype(float), d["date"].values)}
    out["hysteresisVsPlainGt400"] = {("hold%d" % h): {"hours": round(H("hyst_hold%d_s" % h, p1), 4), "diffVsGt400_h": round(H("hyst_hold%d_s" % h, p1) - H("g_gt400", p1), 4),
                                                       "diffPctOfB1": round(100 * (H("hyst_hold%d_s" % h, p1) - H("g_gt400", p1)) / b1, 4)} for h in (1, 2, 3, 5)}
    sweep = out["holdLimitSweep"]
    miss = [strata[g]["L15"]["missingPctOfSeconds"] for g in ("fast", "slow") if g in strata]
    out["tripwires"] = {"holdLimitChangesOnHoursOver1PctOfB1": {k: bool(abs(v["ge300_changeVsL15_pctOfB1"]) > 1) for k, v in sweep.items()},
                        "nanSecondsDifferOver2xBetweenStrata": bool(len(miss) == 2 and min(miss) > 0 and max(miss) / min(miss) > 2), "missingPctOfSecondsFastSlowL15": miss,
                        "hysteresisVsGt400Over1PctOfB1": {k: bool(abs(v["diffPctOfB1"]) > 1) for k, v in out["hysteresisVsPlainGt400"].items()}}
    out["codeTrace"] = TRACE
    out["provenance"] = {"spec": SPEC, "specSha256": hashlib.sha256(open(SPEC, "rb").read()).hexdigest(), "toolSha256": hashlib.sha256(open("tools/engine_on_wave0.py", "rb").read()).hexdigest(),
                         "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "sidecars": ["engine_on_wave0_sidecar.csv", "engine_on_evidence_sidecar.csv"]}
    if not os.path.exists(OUT):
        json.dump(out, open(OUT, "w", encoding="utf-8", newline=chr(10)), indent=1, ensure_ascii=False)
    print(json.dumps({k: out[k] for k in ("holdLimitSweep", "byCadenceRegime", "intervals", "hysteresisVsPlainGt400", "tripwires")}, default=float)[:3800])
    return 0


if __name__ == "__main__":
    sys.exit(main())
