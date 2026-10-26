#!/usr/bin/env python3
"""M514 (analyses/M514_spec.md Rev 2, frozen before any computation): joint instrumentation sensitivity matrix for the resistance-proxy (vreg_R_pack_mohm) months coefficient.
54 pre-declared cells A{0,1} x G{0,1,2} x C{0,1,2} x T{0,1,2} on one paired drive set F*; the published S1 estimate (powerFadeEquivalence.s1) stays the only primary. Reports disagreement; replaces nothing.
Per cell: slope, day / ISO-week / circular moving-block (L7, L14) percentile intervals with common random numbers across the cells of a group (the cells that share a drive subset), failed-draw
rule, decisive flag, and the pre-registered reading ladder. A1 proxies and logged-grid classes are cached per drive in resistance_joint_sidecar.csv (raw sha256 + method version + closure hash).
Writes the payload block resistanceJointSensitivity + stamp (additive) and analyses/M514_result.json. Never changes the master, powerFade, the bound or the TOST.
Usage: python tools/resistance_joint_matrix.py [--check] [--dry-run] [--nb 4000]   (--check recomputes from the tracked sidecar without raw files and compares with the payload)"""
import copy, datetime, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import powerfade_equivalence as PE
import m499_temp_spec as M9
import day_bootstrap as DB

METHOD_VERSION = 1
SIDECAR = os.path.join(ROOT, "resistance_joint_sidecar.csv")
COLS = ["file", "raw_sha256", "method_version", "a1_R", "a1_I", "a1_n", "cur_class", "volt_step", "reason"]
ALLOWED = ["/resistanceJointSensitivity", "/_artifactStamps/resistanceJointSensitivity"]
SEED, NB, MONTH_DAYS = 42, 4000, 30.44
N_REPEATS, MC_BASE = 8, 100000          # endpoint Monte Carlo SD: 8 repeats on separate streams default_rng(MC_BASE + 1000 * r + 10 * proc) (M494 rule)
COND_MAX, FAIL_CAP, MIN_GRID_DRIVES, MIN_GRID_DAYS = 1e9, 0.01, 10, 5
MIN_DRIVES, MIN_DAYS = 150, 50
NONASSESSABLE_SHARE, SPREAD_MAX = 0.25, 0.5
BLOCKS = (7, 14)
UNDEFINED = ("undefined", "undefined_sparse")
FACTORS = {"A": (0, 1), "G": (0, 1, 2), "C": (0, 1, 2), "T": (0, 1, 2)}
CELL_IDS = ["A%dG%dC%dT%d" % (a, g, c, t) for a in FACTORS["A"] for g in FACTORS["G"] for c in FACTORS["C"] for t in FACTORS["T"]]
REFERENCE = "A0G0C1T0"
R_, I_, N_, T_ = PE.RCOL, PE.ICOL, "n_vreg_samples", "T_pack_mean_avg"


# ------------------------------------------------------------------------------------------------ sidecar (A1 proxy and logged-grid class per drive)
def row_from_bytes(b):
    """Per-drive A1 (synchronous interpolation, M505 Rev 2 R1) proxy and the logged-grid class (signal_resolution.classify), by the production helpers."""
    import io
    import compute_drive_summary_v6 as D
    import vreg_alignment as VA
    import signal_resolution as SR
    df, t = D._prep_bytes(b)
    with VA.patched_asof("A1"):
        if getattr(D._asof, "_xt_variant", None) != "A1":
            raise SystemExit("STOP: alignment patch not active for variant A1")
        r = D._vsag_metrics(b, _prep=(df.copy(), t.copy() if hasattr(t, "copy") else t))
    g = pd.read_csv(io.BytesIO(b), dtype=str, low_memory=False, usecols=lambda c: c in (SR.ICOL, SR.VCOL))
    si = SR.stats(g[SR.ICOL]) if SR.ICOL in g.columns else SR.stats(pd.Series([], dtype=str))
    sv = SR.stats(g[SR.VCOL]) if SR.VCOL in g.columns else SR.stats(pd.Series([], dtype=str))
    return {"a1_R": r.get(R_), "a1_I": r.get(I_), "a1_n": r.get(N_), "cur_class": SR.classify(si, "current"), "volt_step": sv["grid_step"]}


def _read(path):
    return pd.read_csv(path, dtype={"raw_sha256": str, "cur_class": str}, keep_default_na=False, na_values=[""])


def build_sidecar(master, loader, path=SIDECAR):
    import dep_hash
    import compute_drive_summary_v6 as _D
    import vreg_alignment as _VA
    import signal_resolution as _SR
    code = dep_hash.closure_hash([row_from_bytes], modules=(sys.modules[__name__], _D, _VA, _SR), extra={"method": METHOD_VERSION})
    code_ok = dep_hash.sidecar_code_ok(path, code)
    old = {r["file"]: r for r in _read(path).to_dict("records")} if os.path.exists(path) else {}
    rows = []
    for f in master["file"].astype(str):
        prev = old.get(f)
        ok_prev = code_ok and prev is not None and prev.get("method_version") == METHOD_VERSION and prev.get("reason") != "raw_file_missing"
        b = loader(f)
        if b is None:
            rows.append({"file": f, "raw_sha256": None, "method_version": METHOD_VERSION, "a1_R": None, "a1_I": None, "a1_n": None, "cur_class": None, "volt_step": None, "reason": "raw_file_missing"}); continue
        h = hashlib.sha256(b).hexdigest()
        if ok_prev and prev.get("raw_sha256") == h:
            rows.append({k: prev.get(k) for k in COLS}); continue
        r = row_from_bytes(b)
        rows.append({"file": f, "raw_sha256": h, "method_version": METHOD_VERSION, **r, "reason": None})
    out = pd.DataFrame(rows, columns=COLS)
    out.to_csv(path, index=False, lineterminator="\n", float_format="%.12g")
    dep_hash.sidecar_code_write(path, code)
    return _read(path)


# ------------------------------------------------------------------------------------------------ the paired set and the cell designs
def frozen_modal_pair(m503_path=os.path.join(ROOT, "analyses", "M503_result.json")):
    r = json.load(open(m503_path, encoding="utf-8"))
    mp = r["rev3DataInformed"]["modalPair"]
    return (mp["currentClass"], round(float(mp["voltageStep"]), 6)), hashlib.sha256(open(m503_path, "rb").read()).hexdigest()


def build_frame(dm, side, dens, modal):
    """F*: S1-eligible drives (clean, released coercion) that carry the A0 and A1 proxies, all covariates and a defined grid class. Sorted as the production S1 rows."""
    cc = PE._clean_files(dm, "released").copy()
    cc["date"] = cc["date"].astype(str)
    order = ["date", "time_start"] if "time_start" in cc.columns else ["date"]
    cc = cc.sort_values(order, kind="stable").reset_index(drop=True)
    s = side.set_index("file")
    for k_ in ("a1_R", "a1_I", "a1_n", "cur_class", "volt_step"):
        cc[k_] = cc["file"].map(s[k_]) if k_ in s.columns else np.nan
    for k_ in ("a1_R", "a1_I", "a1_n", "volt_step"):
        cc[k_] = pd.to_numeric(cc[k_], errors="coerce")
    cc["_de"] = cc["file"].map(lambda f: dens.get(f, (np.nan, np.nan))[0]).astype(float)
    cc["_dc"] = cc["file"].map(lambda f: dens.get(f, (np.nan, np.nan))[1]).astype(float)
    per = pd.to_numeric(cc["I_sample_period_s"], errors="coerce")
    import compute_drive_summary_v6 as D
    cc["_fast"] = np.where(per.notna(), (per < D.POWERFADE_FAST_S).astype(float), np.nan)
    cc["_defined"] = (~cc["cur_class"].isin(UNDEFINED)) & cc["cur_class"].notna() & cc["volt_step"].notna()
    cc["_chg"] = [(c, round(float(v), 6)) != modal if d else np.nan for c, v, d in zip(cc["cur_class"], cc["volt_step"], cc["_defined"])]
    need = [R_, I_, "a1_R", "a1_I", T_, "_de", "_dc", "_fast"]
    ok = cc[need].notna().all(axis=1) & np.isfinite(cc[need].astype(float)).all(axis=1) & cc["_defined"]
    return cc, cc[ok].copy().reset_index(drop=True)


def quantile_knots(T):
    return tuple(np.quantile(np.asarray(T, float), [1 / 3, 2 / 3]))      # numpy linear interpolation (Rev 2 R7)


def design(d, cell, t, knots):
    """Columns: const, months, <temperature terms>, I, [grid indicator], [de, dc], [fast]. The months coefficient is column 1."""
    a, g, c, tt = (int(cell[1]), int(cell[3]), int(cell[5]), int(cell[7]))
    T = d[T_].values.astype(float)
    I = d["a1_I"].values.astype(float) if a == 1 else d[I_].values.astype(float)
    if tt == 0:
        tc = [T]
    elif tt == 1:
        Tc = T - T.mean(); tc = [Tc, Tc ** 2]
    else:
        k1, k2 = knots; tc = [T, np.maximum(T - k1, 0), np.maximum(T - k2, 0)]
    cols = [np.ones(len(d)), t] + tc + [I]
    if g == 1:
        cols.append(d["_chg"].astype(float).values)
    if c >= 1:
        cols += [d["_de"].values.astype(float), d["_dc"].values.astype(float)]
    if c == 2:
        cols.append(d["_fast"].values.astype(float))
    y = (d["a1_R"] if a == 1 else d[R_]).values.astype(float)
    return np.column_stack(cols), y


# ------------------------------------------------------------------------------------------------ resampling engine (per-unit sufficient statistics, shared draws across the cells of a group)
class Group:
    """Cells that share one drive subset: unit labels are shared, so every cell sees the same resampled units (common random numbers). `units`: per-row integer unit index; `ncells` columns of draws."""

    def __init__(self, Xs, ys, units, nunits, month_codes=None):
        self.p = [X.shape[1] for X in Xs]
        self.U = nunits
        self.units = np.asarray(units)
        self.cells = []
        for X, y in zip(Xs, ys):
            p = X.shape[1]
            sc = np.sqrt((X ** 2).mean(axis=0)); sc[sc == 0] = 1.0
            Xs_ = X / sc
            A = np.zeros((nunits, p, p)); B = np.zeros((nunits, p)); S1 = np.zeros((nunits, p)); S2 = np.zeros((nunits, p))
            n = np.bincount(self.units, minlength=nunits).astype(float)
            for u in np.unique(self.units):
                r = self.units == u
                A[u] = Xs_[r].T @ Xs_[r]; B[u] = Xs_[r].T @ y[r]; S1[u] = Xs_[r].sum(axis=0); S2[u] = (Xs_[r] ** 2).sum(axis=0)
            varying = np.array([np.ptp(Xs_[:, j]) > 0 for j in range(p)])
            self.cells.append({"sc": sc, "A": A.reshape(nunits, p * p), "B": B, "n": n, "S1": S1, "S2": S2, "varying": varying, "p": p})
        self.month_code_unit = month_codes          # optional per-unit distinct-month code (day units only)

    def run(self, C):
        """C: (m, U) multiplicity matrix of the drawn units. Returns (m, ncells) months coefficients with NaN for failed draws."""
        m = C.shape[0]
        out = np.full((m, len(self.cells)), np.nan)
        if self.month_code_unit is not None:
            T01 = np.zeros((self.U, int(self.month_code_unit.max()) + 1)); T01[np.arange(self.U), self.month_code_unit] = 1.0
            keep_t = ((C > 0).astype(float) @ T01 > 0).sum(axis=1) >= 3
        else:
            keep_t = (C > 0).sum(axis=1) >= 3
        for k, c in enumerate(self.cells):
            p = c["p"]
            XtX = (C @ c["A"]).reshape(m, p, p)
            Xty = C @ c["B"]
            nrow = C @ c["n"]
            ok = keep_t & (nrow > 0)
            with np.errstate(divide="ignore", invalid="ignore"):
                mean = (C @ c["S1"]) / nrow[:, None]
                var = (C @ c["S2"]) / nrow[:, None] - mean ** 2
            ok &= ~(c["varying"][None, :] & (var <= 1e-12)).any(axis=1)
            cond = np.full(m, np.inf)
            if ok.any():
                cond[ok] = np.linalg.cond(XtX[ok])
            good = ok & np.isfinite(cond) & (cond < COND_MAX)
            if good.any():
                out[good, k] = np.linalg.solve(XtX[good], Xty[good][..., None])[..., 0][:, 1] / c["sc"][1]
        return out


def draws_pick(G, nb, rng, kind):
    """Multiplicity matrices (chunks of 500). kind 'choice' = rng.choice(G, G) per draw (day: the production stream); 'integers' = rng.integers(0, G, G) per draw (ISO week: M499 cluster_boot stream)."""
    for s in range(0, nb, 500):
        m = min(500, nb - s)
        if kind == "choice":
            pick = np.stack([rng.choice(G, G) for _ in range(m)])
        else:
            pick = np.stack([rng.integers(0, G, G) for _ in range(m)])
        yield np.bincount((pick + G * np.arange(m)[:, None]).ravel(), minlength=m * G).reshape(m, G).astype(float)


def draws_blocks(D, L, nb, rng):
    """Circular moving blocks over the calendar axis: starts uniform over all D positions, ceil(D / L) blocks per draw, each covering L consecutive days (wrapping); returns coverage weights per day."""
    nbk = int(np.ceil(D / L))
    for s in range(0, nb, 500):
        m = min(500, nb - s)
        starts = rng.integers(0, D, size=(m, nbk))
        cnt = np.zeros((m, D))
        for j in range(nbk):
            np.add.at(cnt, (np.arange(m), starts[:, j]), 1.0)
        w = np.zeros((m, D))
        for k in range(L):
            w += np.roll(cnt, k, axis=1)
        yield w


def run_procedure(group, proc, nb, seed=None, rng=None):
    """All draws of one procedure for every cell of the group: shape (nb, ncells)."""
    out = []
    if proc == "day":
        rng = np.random.default_rng(SEED if seed is None else seed)
        for C in draws_pick(group.U, nb, rng, "choice"):
            out.append(group.run(C))
    elif proc == "week":
        rng = np.random.default_rng(SEED if seed is None else seed)
        for C in draws_pick(group.U, nb, rng, "integers"):
            out.append(group.run(C))
    return np.vstack(out)


def run_blocks(group_day, L, nb, seed):
    rng = np.random.default_rng(seed)
    return np.vstack([group_day.run(W) for W in draws_blocks(group_day.U, L, nb, rng)])


def interval(draws):
    v = draws[np.isfinite(draws)]
    if len(v) == 0:
        return None
    q = np.percentile(v, [2.5, 97.5])
    return [float(q[0]), float(q[1])]


def reading(ci):
    if ci is None:
        return None
    return "includesZero" if ci[0] <= 0 <= ci[1] else ("positive" if ci[0] > 0 else "negative")


# ------------------------------------------------------------------------------------------------ the matrix
def iso_labels(dates):
    iso = pd.to_datetime(pd.Series(dates)).dt.isocalendar()
    return (iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)).values


def make_group(sub, cell_list, t0, knots, with_blocks=True):
    """Build a Group for the cells of one subset: day units for day draws and blocks (calendar axis), ISO-week units for the week draws."""
    t = ((pd.to_datetime(sub["date"]) - t0).dt.days / MONTH_DAYS).values
    Xs, ys, pt = [], [], []
    for cell in cell_list:
        X, y = design(sub, cell, t, knots)
        Xs.append(X); ys.append(y)
        b = np.linalg.lstsq(X, y, rcond=None)[0]
        sc = np.sqrt((X ** 2).mean(axis=0)); sc[sc == 0] = 1.0
        pt.append({"slope": float(b[1]), "cond": float(np.linalg.cond(X / sc))})
    days = sub["date"].astype(str).values
    uniq, di = np.unique(days, return_inverse=True)
    tv = t[np.unique(di, return_index=True)[1]]
    _, mcodes = np.unique(tv, return_inverse=True)
    gday = Group(Xs, ys, di, len(uniq), mcodes)
    wk = iso_labels(days)
    uw, wi = np.unique(wk, return_inverse=True)
    gweek = Group(Xs, ys, wi, len(uw), None)
    dates = pd.to_datetime(uniq)
    axis = (dates - dates.min()).days.values
    D = int(axis.max()) + 1
    gcal = Group(Xs, ys, axis[di], D, None)
    return {"cells": cell_list, "pt": pt, "gday": gday, "gweek": gweek, "gcal": gcal, "D": D, "nWeeks": int(len(uw)), "nDays": int(len(uniq)), "n": int(len(sub)), "t": t}


def procedures(grp, nb):
    """Draws for the four procedures and the endpoint Monte Carlo SD (8 repeats) of the two block procedures; returns per-cell dicts."""
    cells = grp["cells"]
    dd = run_procedure(grp["gday"], "day", nb)
    wd = run_procedure(grp["gweek"], "week", nb)
    res = {"day": dd, "week": wd}
    mc = {}
    for L in BLOCKS:
        res["M%d" % L] = run_blocks(grp["gcal"], L, nb, SEED + L) if grp["D"] >= 10 * L else None
        if res["M%d" % L] is not None:
            ends = []
            for r in range(N_REPEATS):
                dr = run_blocks(grp["gcal"], L, nb, MC_BASE + 1000 * r + L)
                ends.append([[np.percentile(dr[np.isfinite(dr[:, k]), k], q) for q in (2.5, 97.5)] for k in range(len(cells))])
            mc["M%d" % L] = np.std(np.array(ends), axis=0, ddof=1)             # (ncells, 2)
    grp["mc"] = mc
    return res


def cell_record(grp, res, k, nb, grid_ok):
    rec = {"id": grp["cells"][k], "slope": grp["pt"][k]["slope"], "n": grp["n"], "nDays": grp["nDays"], "nWeeks": grp["nWeeks"], "conditionNumber": grp["pt"][k]["cond"]}
    for proc in ("day", "week", "M7", "M14"):
        dr = res[proc]
        if dr is None:
            rec[proc] = {"fewBlocks": True, "ci95": None, "reading": None, "decisive": False}
            continue
        col = dr[:, k]
        failed = int(np.sum(~np.isfinite(col)))
        ci = interval(col)
        few = (proc == "week" and grp["nWeeks"] < 10)
        d = {"fewBlocks": bool(few), "ci95": ci, "reading": None if few else reading(ci), "failedDraws": failed, "failedShare": failed / nb}
        dec = (failed <= FAIL_CAP * nb) and not few and grp["pt"][k]["cond"] <= COND_MAX and ci is not None and grid_ok
        if proc in ("M7", "M14"):
            sd = grp["mc"][proc][k]
            d["endpointMcSd"] = [float(sd[0]), float(sd[1])]
            d["endpointWithinMcErrorOfZero"] = bool(min(abs(ci[0]), abs(ci[1])) <= 2 * max(sd)) if ci else None
            dec = dec and not d["endpointWithinMcErrorOfZero"]
        d["decisive"] = bool(dec)
        if few:
            d["ci95"] = None
        rec[proc] = d
    return rec


def pair_interval(res, k, ref):
    """Paired day interval of (cell - reference) on the draws where both are valid."""
    a, b = res["day"][:, k], res["day"][:, ref]
    ok = np.isfinite(a) & np.isfinite(b)
    return interval((a - b)[ok]) if ok.any() else None


def ladder(cells, ref_rec):
    """Pre-registered reading ladder (Rev 2 R8). Returns (level, details)."""
    day_dec = [c for c in cells if c["day"]["decisive"]]
    nonassess = (len(cells) - len(day_dec)) / len(cells) > NONASSESSABLE_SHARE
    slopes = [c["slope"] for c in cells]
    ref_ci = ref_rec["day"]["ci95"]
    half = (ref_ci[1] - ref_ci[0]) / 2 if ref_ci else None
    spread = (max(slopes) - min(slopes)) / (2 * half) if half else None
    ref_read = ref_rec["day"]["reading"]
    allints = [(c["id"], p, c[p]) for c in cells for p in ("day", "week", "M7", "M14") if c[p].get("decisive")]
    differs = [(i, p) for i, p, d in allints if d["reading"] != ref_read]
    sides = {d["reading"] for _, _, d in allints}
    l2 = bool(allints) and len(sides) == 1 and next(iter(sides)) in ("positive", "negative")
    if nonassess:
        lvl = "not assessable"
    elif l2:
        lvl = "L2"
    elif differs or (spread is not None and spread > SPREAD_MAX):
        lvl = "L1"
    else:
        lvl = "L0"
    return lvl, {"referenceReading": ref_read, "spreadRatio": spread, "referenceDayHalfWidth": half, "nCells": len(cells), "nDayDecisive": len(day_dec),
                 "nonDecisiveShare": (len(cells) - len(day_dec)) / len(cells), "nIntervalsDiffering": len(differs), "differing": differs, "l2Needs": "blind audit and Director decision before display"}


STATEMENT = ("Joint instrumentation sensitivity matrix of the resistance-proxy months coefficient (powerFade S1 design; 54 pre-declared cells: alignment A0/A1 x logged grid period G0/G1/G2 x cadence and support C0/C1/C2 x temperature "
             "specification T0/T1/T2) on one paired drive set. It reports how the reading changes across choices; it replaces no estimate, is a conditional association in one warm window (not a degradation rate, SOH or true resistance), "
             "and G1/G2 are aliased with calendar time (one contiguous logged-grid run). Cells are never selected or averaged.")


def compute(dm, side, dens, nb=NB, quick=False):
    modal, m503_sha = frozen_modal_pair()
    cc, F = build_frame(dm, side, dens, modal)
    pe = json.load(open("summary_arrays.json", encoding="utf-8"))["powerFadeEquivalence"]["s1"]
    # fidelity (S1 set, production design)
    s1set = cc[np.isfinite(cc["_de"]) & np.isfinite(cc["_dc"])]
    t0s = pd.to_datetime(cc["date"]).min()
    f0 = M9.fit(s1set, "T0", t0s, (0.0, 0.0), nb)[0]
    fid = {"slope": round(f0["slope"], 4), "publishedSlope": pe["slope"], "n": f0["n"], "publishedN": pe["nDrives"], "nDays": f0["nDays"], "publishedNDays": pe["nDays"]}
    fid["passed"] = bool(fid["slope"] == round(pe["slope"], 4) and fid["n"] == fid["publishedN"] and fid["nDays"] == fid["publishedNDays"])
    if not fid["passed"]:
        raise SystemExit("M514 STOP: the S1 refit does not reproduce the published S1: %s" % json.dumps(fid))
    if len(F) < MIN_DRIVES or F["date"].nunique() < MIN_DAYS:
        raise SystemExit("M514 STOP: F* has %d drives on %d days (< %d / %d): Director" % (len(F), F["date"].nunique(), MIN_DRIVES, MIN_DAYS))
    t0 = pd.to_datetime(F["date"]).min()
    knots = quantile_knots(F[T_].values)
    nchg = int(F["_chg"].astype(float).sum()); chg_days = int(F.loc[F["_chg"].astype(bool), "date"].nunique())
    grid_ok = nchg >= MIN_GRID_DRIVES and chg_days >= MIN_GRID_DAYS
    S2 = F[~F["_chg"].astype(bool)].reset_index(drop=True)
    s2_ok = len(S2) >= MIN_DRIVES and S2["date"].nunique() >= MIN_DAYS
    cells_F = [c for c in CELL_IDS if c[3] in "01"]
    cells_S2 = [c for c in CELL_IDS if c[3] == "2"]
    comp = [c[:3] + "0" + c[4:] for c in cells_S2]              # G0 companions on the G2 subset
    gF = make_group(F, cells_F, t0, knots)
    gS = make_group(S2, cells_S2 + comp, t0, knots)
    rF, rS = procedures(gF, nb), procedures(gS, nb)
    recs, pairs = {}, {}
    ref_k = gF["cells"].index(REFERENCE)
    for k, cid in enumerate(gF["cells"]):
        r = cell_record(gF, rF, k, nb, True if cid[3] == "0" else grid_ok)
        r["pairedDifferenceFromReferenceDay"] = None if cid == REFERENCE else pair_interval(rF, k, ref_k)
        recs[cid] = r
    for k, cid in enumerate(gS["cells"][:len(cells_S2)]):
        r = cell_record(gS, rS, k, nb, grid_ok and s2_ok)      # G2 cells need the grid-change drives (>= 10 on >= 5 days) and the G2 subset stop thresholds
        r["subset"] = "G2: gridChange drives excluded"
        comp_k = gS["cells"].index(comp[k])
        r["pairedDifferenceFromG0OnSameSubsetDay"] = pair_interval(rS, k, comp_k)
        r["g0OnSameSubset"] = {"id": comp[k], "slope": gS["pt"][comp_k]["slope"], "dayCi95": interval(rS["day"][:, comp_k])}
        recs[cid] = r
    cells = [recs[c] for c in CELL_IDS]
    ref = recs[REFERENCE]
    lvl, det = ladder(cells, ref)
    dec = {p: [c[p]["reading"] for c in cells if c[p].get("decisive")] for p in ("day", "week", "M7", "M14")}
    counts = {p: {"decisive": len(v), "excludeZero": int(sum(1 for x in v if x in ("positive", "negative"))), "positive": int(sum(1 for x in v if x == "positive"))} for p, v in dec.items()}
    pos = {"A": 1, "G": 3, "C": 5, "T": 7}
    margins = {f: {str(l): float(np.mean([c["slope"] for c in cells if c["id"][pos[f]] == str(l)])) for l in FACTORS[f]} for f in "AGCT"}
    slopes = [c["slope"] for c in cells]
    support = {}
    for a in (0, 1):
        for g in (0, 1, 2):
            cid = "A%dG%dC1T0" % (a, g)
            sub = (S2 if g == 2 else F)
            nn = sub["a1_n"] if a == 1 else sub[N_]
            support[cid] = {"nDrivesWithNVregSamplesAtLeast2xMin": int((nn >= 600).sum()), "n": int(len(sub))}
    blk = {"label": "joint instrumentation sensitivity matrix of the resistance-proxy (vreg_R_pack_mohm) months coefficient, powerFade S1 design; estimated proxy, a conditional association in one warm window, not a degradation rate, SOH or true resistance",
           "spec": "analyses/M514_spec.md (Rev 2)", "specSha256": hashlib.sha256(open("analyses/M514_spec.md", "rb").read()).hexdigest(),
           "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(),
           "seed": SEED, "nBoot": nb, "factors": {"A": "A0 production alignment | A1 synchronous-interpolation variant (M505 Rev 2 R1)", "G": "G0 none | G1 gridChange indicator | G2 gridChange drives excluded",
                                                  "C": "C0 none | C1 eff_dt_s + coverage_frac (S1) | C2 C1 + fast-regime indicator (powerFade S3)", "T": "T0 linear | T1 quadratic | T2 hinge (knots frozen on F* terciles)"},
           "gridDefinition": {"modalPairFrozen": {"currentClass": modal[0], "voltageStep": modal[1]}, "m503ResultSha256": m503_sha, "rule": "gridChange = (current class, round(voltage step, 6)) differs from the frozen modal pair; undefined classes leave F*"},
           "pairedSet": {"nDrives": int(len(F)), "nDays": int(F["date"].nunique()), "nGridChangeDrives": nchg, "nGridChangeDays": chg_days, "g2Subset": {"nDrives": int(len(S2)), "nDays": int(S2["date"].nunique())}, "knots": [float(k) for k in knots]},
           "fidelity": fid, "reference": {"id": REFERENCE, "note": "A0,G0,C1,T0 evaluated on F*; the published S1 estimate remains the only primary", "slope": ref["slope"], "dayCi95": ref["day"]["ci95"],
                                           "restrictionDeltaVsPublishedS1": {"slope": ref["slope"] - pe["slope"], "nDrivesF": int(len(F)), "nDrivesS1": pe["nDrives"], "nDaysF": int(F["date"].nunique()), "nDaysS1": pe["nDays"]}},
           "cells": cells, "summary": {"nCells": len(cells), "slopeRange": [min(slopes), max(slopes)], "nPositiveSlopes": int(sum(1 for s in slopes if s > 0)), "spreadRatio": det["spreadRatio"],
                                       "intervalCounts": counts, "levelMeansDescriptive": margins, "supportMarginDescriptive": support},
           "ladder": {"level": lvl, **det}, "statement": STATEMENT,
           "repeatedLooks": "re-run at every ingestion, no alpha spending; up to 216 intervals, no multiplicity adjustment; a ladder change escalates to the Director",
           "blindAuditRef": _audit_ref(),
           "mcRule": "an M7/M14 interval is non-decisive when its endpoint nearest zero lies within 2 x the larger Monte Carlo SD of the two endpoints (8 repeats on separate streams; the 2 x SD threshold is an implementation choice taken from the M494 result review, recorded here)"}
    return blk


def _audit_ref():
    p = os.path.join(ROOT, "analyses", "M514_audit.json")
    if not os.path.exists(p):
        return None
    a = json.load(open(p, encoding="utf-8"))
    return {"file": "analyses/M514_audit.json", "sha256": hashlib.sha256(open(p, "rb").read()).hexdigest(), "cellsCovered": sorted(a["cellsCovered"]), "notCovered": a["notCovered"], "verdict": a["verdict"]}


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), 5)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def splice(A, blk, master_md5="", now=None):
    new = copy.deepcopy(A)
    new["resistanceJointSensitivity"] = blk
    old = (A.get("_artifactStamps") or {}).get("resistanceJointSensitivity")
    if old and A.get("resistanceJointSensitivity") == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"]["resistanceJointSensitivity"] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M514: derived by tools/resistance_joint_matrix.py from drive_master.csv, powerfade_density.csv and the tracked resistance_joint_sidecar.csv (analyses/M514_spec.md Rev 2)",
                  upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
        new["_artifactStamps"]["resistanceJointSensitivity"] = st
    ch = [k for k in set(A) | set(new) if A.get(k) != new.get(k)]
    bad = [k for k in ch if k not in ("resistanceJointSensitivity", "_artifactStamps")]      # the stamp dict is checked entry by entry below
    st_bad = [k for k in set(A["_artifactStamps"]) | set(new["_artifactStamps"]) if A["_artifactStamps"].get(k) != new["_artifactStamps"].get(k) and k != "resistanceJointSensitivity"]
    return new, ch, bad + st_bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    nb = int(argv[argv.index("--nb") + 1]) if "--nb" in argv else NB
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A0 = json.loads(raw)
    if "--check" in argv:
        side = _read(SIDECAR)
    else:
        import ah_throughput as AH
        side = build_sidecar(dm, AH.raw_loader())
    ps = PE._read(PE.SIDECAR)
    dens = {r["file"]: (float(r["eff_dt_s"]) if pd.notna(r["eff_dt_s"]) else np.nan, float(r["coverage_frac"]) if pd.notna(r["coverage_frac"]) else np.nan) for r in ps.to_dict("records")}
    blk = _clean(compute(dm, side, dens, nb))
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    if "--check" in argv:
        have = A0.get("resistanceJointSensitivity")
        bad = have != blk
        print(json.dumps({"check": "resistanceJointSensitivity", "matchesPayload": not bad, "ladder": blk["ladder"]["level"]}))
        return 1 if bad else 0
    new, changed, bad = splice(A0, blk, md5)
    json.dump(blk, open("analyses/M514_result.json", "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False)
    print(json.dumps({"nChanged": len(changed), "outsideAllowList": bad, "ladder": blk["ladder"]["level"], "referenceSlope": blk["reference"]["slope"], "spreadRatio": blk["summary"]["spreadRatio"]}))
    if bad:
        return 1
    if "--dry-run" not in argv and changed:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
