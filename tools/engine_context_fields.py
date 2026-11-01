#!/usr/bin/env python3
"""M559 (spec analyses/M559_spec.md Rev 2): orthogonal engine-context fields (audit 2026-10-29 N03, F09 data part).
For every 1 s grid sample with the engine rotating (rpm above 400) four SEPARATE fields: rotation level, net pack-flow state (discharge-positive current, deadband), coolant context (age-checked, no grid fill) and
combustion evidence (legacy boost classes plus the calculated fuel rate as a sub-flag). Candidate labels (generation_net_charge, generation_with_pack_discharge, thermal_context, dissipation_candidate) are
non-exclusive; a sample with none stays unresolved. Rev 3: thermal_context = cold coolant only; labelled slow_fuelValid sub-stratum; probe with its own support. Grid rule identical to the M46 census (_dissipation_census: 1 s mean, ffill limit 3, speed priority), so the motored seconds reconcile exactly.
Per-drive records are cached by the raw sha256 and the extractor hash (ecf_cache/, git-ignored); aggregation never rereads raw. Modes: --check (writes analyses/M559_check.json) | --splice (check + additive write of S.engineContextFields).
Usage: python tools/engine_context_fields.py --check|--splice [--sample]"""
import copy, datetime, hashlib, inspect, io, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M559_check.json")
CACHE = os.path.join(ROOT, "ecf_cache")
SEED, DRAWS, MIN_DAYS = 42, 4000, 5
SUPPORT = (200, 10, 5)                                   # samples, drives, days (common support floor)
COLS = {"[BMS] HV Battery Current (A)": "I", "[BMS] HV State of charge (%)": "soc", "[VCM] Vehicle Speed (km/h)": "speed", "Оберти двигуна (rpm)": "rpm",
        "Розрахункове значення навантаження на двигун (%)": "load", "Розрахунковий наддув (bar)": "boost", "Витрати палива (L/h)": "fuel"}
COOL = "Температура охолодної рідини (℃)"
BASE = dict(rpm_on=400.0, flow_db=2.0, cool_cold=60.0, cool_warm=80.0, fuel_floor=0.0, boost_mot=-0.70, boost_fue=-0.55, load_max=8.0, rpm_hi=2000.0, cool_age=30.0, spin_s=3, speed_min=5.0, soc_hi=80.0)
VARIANTS = {"base": {}, "flow1A": {"flow_db": 1.0}, "flow5A": {"flow_db": 5.0}, "rpm600": {"rpm_on": 600.0}, "coolCold55": {"cool_cold": 55.0}, "coolCold65": {"cool_cold": 65.0},
            "coolWarm75": {"cool_warm": 75.0}, "coolWarm85": {"cool_warm": 85.0}, "fuel005": {"fuel_floor": 0.05}, "fuel010": {"fuel_floor": 0.10}}
LABELS = ("generation_net_charge", "generation_with_pack_discharge", "thermal_context", "dissipation_candidate")


# ---------------------------------------------------------------- kernel (pure, unit-tested)
def coolant_age(t_ns, ct_ns, cv):
    """value and age (s) of the last NON-NULL raw coolant sample at or before each grid time; NaN where none. No grid fill."""
    if len(ct_ns) == 0:
        return np.full(len(t_ns), np.nan), np.full(len(t_ns), np.nan)
    i = np.searchsorted(ct_ns, t_ns, side="right") - 1
    ok = i >= 0
    val = np.where(ok, cv[np.clip(i, 0, None)], np.nan)
    age = np.where(ok, (t_ns - ct_ns[np.clip(i, 0, None)]) / 1e9, np.nan)
    return val, age


def classify(g, cool, cool_age, flags, p):
    """g: 1 s grid DataFrame (rpm, boost, load, I discharge-positive, soc, speed, fuel); cool, cool_age arrays aligned to g; flags: file-level channel availability.
    Returns a DataFrame over the ROTATING rows with the four fields, the spin-up flag and the boolean candidate labels."""
    rpm = g["rpm"].to_numpy(float)
    on = np.where(np.isnan(rpm), False, rpm > p["rpm_on"])
    chg = np.zeros(len(g), bool)
    chg[1:] = on[1:] != on[:-1]
    k = int(p["spin_s"])
    near = np.zeros(len(g), bool)
    for s in range(-k, k + 1):
        sh = np.roll(chg, s)
        if s > 0:
            sh[:s] = False
        elif s < 0:
            sh[s:] = False
        near |= sh
    m = on
    r = pd.DataFrame(index=g.index[m])
    rp = rpm[m]
    r["rot"] = np.where(rp < 1000, "low", np.where(rp < 2000, "mid", "high"))
    I = g["I"].to_numpy(float)[m]
    r["flow"] = np.where(np.isnan(I), "unknown", np.where(I > p["flow_db"], "discharging", np.where(I < -p["flow_db"], "charging", "neutral")))
    cv, ca = cool[m], cool_age[m]
    r["thermal"] = np.where(np.isnan(cv) | np.isnan(ca) | (ca > p["cool_age"]), "unknown", np.where(cv <= p["cool_cold"], "cold", np.where(cv <= p["cool_warm"], "warming", "warm")))
    bo, ld = g["boost"].to_numpy(float)[m], g["load"].to_numpy(float)[m]
    have = bool(flags["hasBoost"] and flags["hasLoad"])
    r["comb"] = np.where((not have) | np.isnan(bo), "no_signal", np.where(bo < p["boost_mot"], "motored", np.where(bo >= p["boost_fue"], "fuelled", "ambiguous")))
    fu = g["fuel"].to_numpy(float)[m] if "fuel" in g else np.full(m.sum(), np.nan)
    r["fuelFlag"] = bool(flags["fuelOk"]) & (np.nan_to_num(fu, nan=0.0) > p["fuel_floor"])
    low_load = np.nan_to_num(ld, nan=0.0) < p["load_max"]
    r["lowLoad"] = low_load
    r["hasSoc"] = ~np.isnan(g["soc"].to_numpy(float)[m])
    r["hiRpm"] = rp > p["rpm_hi"]
    r["spin"] = near[m]
    sp = g["speed"].to_numpy(float)[m]
    soc = g["soc"].to_numpy(float)[m]
    supported = (r["comb"].to_numpy() == "fuelled") & r["fuelFlag"].to_numpy() & (np.nan_to_num(ld, nan=-1.0) >= p["load_max"])
    r["generation_net_charge"] = supported & (r["flow"].to_numpy() == "charging")
    r["generation_with_pack_discharge"] = supported & (r["flow"].to_numpy() == "discharging") & (np.nan_to_num(sp, nan=-1.0) > p["speed_min"])
    r["thermal_context"] = r["thermal"].to_numpy() == "cold"             # Rev 3 (Director): cold coolant only; the warming / warm bands stay a descriptive field
    r["dissipation_candidate"] = (r["comb"].to_numpy() == "motored") & low_load & r["hiRpm"].to_numpy() & ~r["spin"].to_numpy()
    r["socHi"] = np.nan_to_num(soc, nan=-1.0) >= p["soc_hi"]
    return r


def summarize(r, p):
    """seconds per cell, per label set and the probe; plain dict (JSON-safe)."""
    out = {"rot": int(len(r)), "cells": {}, "labelSets": {}, "legacyMot": 0, "newMot": 0}
    if not len(r):
        out.update(probe={"socHiNonCharging": 0, "dissipation": 0, "unresolvedNoCandidate": 0, "unresolvedExceptThermal": 0}, counts={})
        return out
    key = (r["flow"] + "|" + r["thermal"] + "|" + r["comb"] + "|" + np.where(r["fuelFlag"], "F", "n") + "|" + np.where(r["spin"], "S", "-"))
    out["cells"] = {k: int(v) for k, v in key.value_counts().items()}
    lab = r[list(LABELS)].to_numpy(bool)
    ls = pd.Series(["+".join(LABELS[j] for j in range(4) if row[j]) for row in lab], index=r.index)
    out["labelSets"] = {k: int(v) for k, v in ls.value_counts().items()}
    none = ~lab.any(axis=1)
    exc = ~lab[:, [0, 1, 3]].any(axis=1)
    hi = r["socHi"].to_numpy() & np.isin(r["flow"].to_numpy(), ("neutral", "discharging"))
    out["probe"] = {"socHiNonCharging": int(hi.sum()), "dissipation": int((hi & lab[:, 3]).sum()), "unresolvedNoCandidate": int((hi & none).sum()), "unresolvedExceptThermal": int((hi & exc).sum())}
    out["unresolvedNoCandidate"] = int(none.sum()); out["unresolvedExceptThermal"] = int(exc.sum())
    # legacy M46 rule on the same grid: rpm > 2000, soc present, boost < -0.70, load.fillna(0) < 8
    leg = r["hiRpm"].to_numpy() & r["hasSoc"].to_numpy() & (r["comb"].to_numpy() == "motored") & r["lowLoad"].to_numpy()
    out["newMot"] = int(leg.sum())
    cnt = {"flow_" + k: int(v) for k, v in r["flow"].value_counts().items()}
    cnt.update({"thermal_" + k: int(v) for k, v in r["thermal"].value_counts().items()})
    cnt.update({"comb_" + k: int(v) for k, v in r["comb"].value_counts().items()})
    cnt.update({"rot_" + k: int(v) for k, v in r["rot"].value_counts().items()})
    for L in LABELS:
        cnt["label_" + L] = int(r[L].sum())
    cb, ff = r["comb"].to_numpy(), r["fuelFlag"].to_numpy()
    cnt["unres_noSignal"] = int((none & (cb == "no_signal")).sum()); cnt["unres_fuelMissing"] = int((none & (cb == "fuelled") & ~ff).sum())
    cnt["unres_other"] = int(none.sum() - cnt["unres_noSignal"] - cnt["unres_fuelMissing"])
    cnt["spin"] = int(r["spin"].sum()); cnt["fuelFlagInFuelled"] = int((r["fuelFlag"] & (r["comb"] == "fuelled")).sum())
    cnt["nLabels0"] = int(none.sum()); cnt["nLabels1"] = int((lab.sum(axis=1) == 1).sum()); cnt["nLabels2"] = int((lab.sum(axis=1) == 2).sum()); cnt["nLabels3p"] = int((lab.sum(axis=1) >= 3).sum())
    out["counts"] = cnt
    return out


def _src_hash():
    return hashlib.sha256("".join(inspect.getsource(f) for f in (coolant_age, classify, summarize, drive_record, _grid, _legacy_motored)).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- per-drive extraction
def _grid(df):
    import compute_summary_arrays as C
    df, _ = C._apply_speed_priority(df)
    g = df.set_index(C._ft(df["time"]))
    keep = [c for c in COLS if c in g.columns]
    g = g[keep].apply(pd.to_numeric, errors="coerce").rename(columns=COLS)
    return g.resample("1s").mean().ffill(limit=3), df


def drive_record(b):
    import compute_summary_arrays as C
    hdr = list(pd.read_csv(io.BytesIO(b), nrows=0).columns)
    if "time" not in hdr:
        return {"ok": False, "why": "no time column"}
    need = lambda c: c in COLS or c == "time" or c == C._SPEED_OBD_RAW or c == COOL
    df = pd.read_csv(io.BytesIO(b), usecols=lambda c: need(c), low_memory=False)
    g, df2 = _grid(df)
    fu = g["fuel"].to_numpy(float) if "fuel" in g else np.array([])
    flags = {"hasBoost": "boost" in g and bool(np.isfinite(g["boost"]).any()), "hasLoad": "load" in g and bool(np.isfinite(g["load"]).any()),
             "fuelOk": bool("fuel" in g and np.nanmax(np.where(np.isfinite(fu), fu, 0.0)) > 0), "hasCool": COOL in df.columns and bool(pd.to_numeric(df[COOL], errors="coerce").notna().any()), "hasRpm": "rpm" in g}
    if not flags["hasRpm"] or "I" not in g:
        return {"ok": False, "why": "no rpm or current channel", "flags": flags}
    g["I"] = -g["I"]                                              # BMS current is charge-positive (M11); fields use discharge-positive
    for c in ("boost", "load", "fuel", "soc", "speed"):
        if c not in g:
            g[c] = np.nan
    tns = g.index.values.astype("datetime64[ns]").astype("int64")
    if flags["hasCool"]:
        ct = pd.to_numeric(df[COOL], errors="coerce")
        tt = pd.Series(pd.to_datetime(C._ft(df["time"]))).values.astype("datetime64[ns]").astype("int64")
        mk = ct.notna().to_numpy()
        order = np.argsort(tt[mk], kind="stable")
        cool, age = coolant_age(tns, tt[mk][order], ct.to_numpy(float)[mk][order])
    else:
        cool, age = np.full(len(g), np.nan), np.full(len(g), np.nan)
    rec = {"ok": True, "flags": flags, "gridSeconds": int(len(g)), "variants": {}}
    for name, over in VARIANTS.items():
        p = dict(BASE); p.update(over)
        rec["variants"][name] = summarize(classify(g, cool, age, flags, p), p)
    rec["variants"]["base"]["legacyMot"] = _legacy_motored(g, flags)
    return rec


def _legacy_motored(g, flags):
    """the M46 census rule, verbatim from _dissipation_census (independent of classify): on = rpm > 800, dropna(soc, rpm, boost); rpm > 2000, boost < -0.70, load.fillna(0) < 8; drives without boost / load / soc channels contribute nothing."""
    if not (flags["hasBoost"] and flags["hasLoad"]) or not np.isfinite(g["soc"].to_numpy(float)).any():
        return 0
    on = g[g["rpm"] > 800].dropna(subset=["soc", "rpm", "boost"])
    base = on["rpm"] > 2000.0
    return int((base & (on["boost"] < -0.70) & (on["load"].fillna(0) < 8.0)).sum())


# ---------------------------------------------------------------- loading with the cache
def load_records(only=None):
    import compute_summary_arrays as C
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    cr = pd.read_csv("cadence_regime.csv")[["file", "regime"]]
    cad = dict(zip(cr.file, cr.regime))
    bad = C._canonical_bad(dm)
    raw_dir = os.environ.get("XT_RAW_DIR", os.path.join(ROOT, "raw"))
    dig = lambda s: "".join(ch for ch in s if ch.isdigit())[:14]
    rawmap = {}
    for f in os.listdir(raw_dir):
        if f.endswith(".csv"):
            rawmap.setdefault(dig(f), []).append(f)
    os.makedirs(CACHE, exist_ok=True)
    sh = _src_hash()
    recs, stats = {}, {"cacheHits": 0, "extracted": 0, "noRaw": 0, "notOk": 0}
    for i, r in dm.iterrows():
        fn = r["file"]
        if only and fn not in only:
            continue
        cand = rawmap.get(dig(fn))
        if not cand:
            stats["noRaw"] += 1; continue
        b = open(os.path.join(raw_dir, cand[0]), "rb").read()
        digest = hashlib.sha256(b).hexdigest()
        cp = os.path.join(CACHE, f"{digest}_{sh}.json")
        if os.path.exists(cp):
            rec = json.load(open(cp, encoding="utf-8")); stats["cacheHits"] += 1
        else:
            rec = drive_record(b)
            json.dump(rec, open(cp, "w", encoding="utf-8")); stats["extracted"] += 1
        if not rec.get("ok"):
            stats["notOk"] += 1
        c_ = cad.get(fn)
        recs[fn] = {"rec": rec, "file": fn, "rawSha256": digest, "cadence": c_ if isinstance(c_, str) else "unknown", "canonClean": bool(not bad.iloc[i]),
                    "day": (lambda s: f"{s[:4]}-{s[4:6]}-{s[6:8]}")("".join(c for c in fn if c.isdigit()))}
    return dm, recs, stats


# ---------------------------------------------------------------- aggregation
def _boot(num, den, days):
    from cell_observability import _pooled_share
    return _pooled_share(num, den, days)


def _share(sub, var, key, den_key="rot", sec="counts"):
    num = [(a["rec"]["variants"][var][sec].get(key, 0) if sec == "counts" else a["rec"]["variants"][var].get(key, 0)) for a in sub]
    den = [a["rec"]["variants"][var]["rot"] if den_key == "rot" else a["rec"]["variants"][var]["counts"].get(den_key, 0) for a in sub]
    return _boot(num, den, [a["day"] for a in sub])


def stratum_block(sub):
    b = {"nDrives": len(sub), "nDays": len({a["day"] for a in sub}), "rotatingSeconds": int(sum(a["rec"]["variants"]["base"]["rot"] for a in sub))}
    for grp, keys in (("flow", ("charging", "neutral", "discharging", "unknown")), ("thermal", ("cold", "warming", "warm", "unknown")), ("comb", ("motored", "ambiguous", "fuelled", "no_signal")), ("rotation", ("low", "mid", "high"))):
        pref = {"flow": "flow_", "thermal": "thermal_", "comb": "comb_", "rotation": "rot_"}[grp]
        b[grp] = {k: _share(sub, "base", pref + k) for k in keys}
    b["fuelFlagShareOfFuelled"] = _share(sub, "base", "fuelFlagInFuelled", den_key="comb_fuelled")
    b["labels"] = {L: _share(sub, "base", "label_" + L) for L in LABELS}
    b["unresolvedNoCandidate"] = _share(sub, "base", "nLabels0")
    b["unresolvedExceptThermal"] = _boot([a["rec"]["variants"]["base"].get("unresolvedExceptThermal", 0) for a in sub], [a["rec"]["variants"]["base"]["rot"] for a in sub], [a["day"] for a in sub])
    b["spinUpShare"] = _share(sub, "base", "spin")
    b["mixedFunctions"] = {k: _share(sub, "base", k) for k in ("nLabels0", "nLabels1", "nLabels2", "nLabels3p")}
    den_p = [a["rec"]["variants"]["base"]["probe"]["socHiNonCharging"] for a in sub]
    used = [a for a, d in zip(sub, den_p) if d > 0]
    p_s, p_dr, p_dy = int(sum(den_p)), len(used), len({a["day"] for a in used})
    p_ok = bool(p_s >= SUPPORT[0] and p_dr >= SUPPORT[1] and p_dy >= SUPPORT[2])
    def pr(k):
        sh = _boot([a["rec"]["variants"]["base"]["probe"][k] for a in used], [a["rec"]["variants"]["base"]["probe"]["socHiNonCharging"] for a in used], [a["day"] for a in used])
        if sh and not p_ok:
            sh = {"share": sh["share"], "ci95": None, "pairs": sh["pairs"], "violations": sh["violations"], "nDrives": sh["nDrives"], "nDays": sh["nDays"]}
        return sh
    b["acceptanceProbe"] = {"rotatingSocAtLeast80NeutralOrDischargingSeconds": p_s, "nDrives": p_dr, "nDays": p_dy, "supported": p_ok, "exploratory": True,
                            "dissipationCandidateShare": pr("dissipation"), "unresolvedNoCandidateShare": pr("unresolvedNoCandidate"), "unresolvedExceptThermalShare": pr("unresolvedExceptThermal")}
    b["unresolvedReasons"] = {k: _share(sub, "base", "unres_" + k) for k in ("noSignal", "fuelMissing", "other")}
    b["thermalBandTable"] = {name: {"warming": _share(sub, name, "thermal_warming"), "warm": _share(sub, name, "thermal_warm"), "cold": _share(sub, name, "thermal_cold")} for name in ("coolWarm75", "base", "coolWarm85")}
    cells = {}
    for a in sub:
        for k, v in a["rec"]["variants"]["base"]["cells"].items():
            c = cells.setdefault(k, {"seconds": 0, "drives": 0, "days": set()}); c["seconds"] += v; c["drives"] += 1; c["days"].add(a["day"])
    b["crossTable"] = {k: {"seconds": c["seconds"], "nDrives": c["drives"], "nDays": len(c["days"]), "supported": bool(c["seconds"] >= SUPPORT[0] and c["drives"] >= SUPPORT[1] and len(c["days"]) >= SUPPORT[2])} for k, c in sorted(cells.items())}
    b["crossTableSupportedCells"] = int(sum(1 for c in b["crossTable"].values() if c["supported"]))
    sens = {}
    for name in VARIANTS:
        if name == "base":
            continue
        row = {}
        for key in ("label_generation_net_charge", "label_generation_with_pack_discharge", "label_thermal_context", "label_dissipation_candidate", "nLabels0", "flow_charging", "flow_discharging", "thermal_cold", "thermal_warm"):
            s0, s1 = _share(sub, "base", key), _share(sub, name, key)
            row[key] = round(100 * abs((s1 or {"share": 0})["share"] - (s0 or {"share": 0})["share"]), 3) if s0 and s1 else None
        sens[name] = row
    b["sensitivityPp"] = sens
    b["sensitivityMaxPp"] = max([v for r in sens.values() for v in r.values() if v is not None] or [0])
    return b


def known_answers(recs):
    n = {"drives": 0, "legacyEqNew": 0}; miss = {"legacyEqNew": []}
    for fn, a in recs.items():
        r = a["rec"]
        if not r.get("ok"):
            continue
        v = r["variants"]["base"]
        n["drives"] += 1; n["legacyEqNew"] += 1
        if v["legacyMot"] != v["newMot"]:
            miss["legacyEqNew"].append(fn)
    leg = sum(a["rec"]["variants"]["base"]["legacyMot"] for a in recs.values() if a["rec"].get("ok"))
    pay = json.load(open(ARR, encoding="utf-8")).get("dissipationCensus", {}).get("motored", {}).get("nSamples")
    return {"n": n, "misses": {k: v for k, v in miss.items() if v}, "legacyMotoredSecondsFromCache": int(leg), "dissipationCensusPayloadMotoredSamples": pay, "residualSeconds": (None if pay is None else int(leg - pay))}


def main():
    mode = "--splice" if "--splice" in sys.argv else "--check"
    only = None
    if "--sample" in sys.argv:
        only = {w["file"] for w in json.load(open(os.path.join(ROOT, "analyses", "M559_audit_sample.json"), encoding="utf-8"))["windows"]}
    dm, recs, stats = load_records(only)
    ka = known_answers(recs)
    res = {"milestone": "M559", "mode": mode, "stats": stats, "knownAnswer": ka, "extractorSourceHash": _src_hash()}
    el = {fn: a for fn, a in recs.items() if a["rec"].get("ok") and a["canonClean"]}
    res["eligible"] = {"masterRows": int(len(dm)), "withRaw": len(recs), "ok": sum(1 for a in recs.values() if a["rec"].get("ok")), "canonClean": len(el),
                       "fuelAllZeroOrMissing": sum(1 for a in el.values() if not a["rec"]["flags"]["fuelOk"]), "noBoostOrLoad": sum(1 for a in el.values() if not (a["rec"]["flags"]["hasBoost"] and a["rec"]["flags"]["hasLoad"])),
                       "noCoolant": sum(1 for a in el.values() if not a["rec"]["flags"]["hasCool"])}
    res["strata"] = {}
    for c in ("fast", "slow", "unknown"):
        sub = [a for a in el.values() if a["cadence"] == c and a["rec"]["variants"]["base"]["rot"] > 0]
        if sub:
            res["strata"][c] = stratum_block(sub)
            if c == "slow":
                fv = [a for a in sub if a["rec"]["flags"]["fuelOk"] and a["rec"]["flags"]["hasBoost"] and a["rec"]["flags"]["hasLoad"]]
                if fv:
                    res["strata"]["slow_fuelValid"] = stratum_block(fv)
    res["rawListSha256"] = hashlib.sha256(json.dumps(sorted((a["file"], a["rawSha256"]) for a in recs.values())).encode()).hexdigest()
    json.dump(res, open(OUT if not only else OUT.replace(".json", "_sample.json"), "w", encoding="utf-8"), indent=1, default=float)
    print(json.dumps({"ok": True, "stats": stats, "knownAnswer": ka, "eligible": res["eligible"]}, default=float))
    if (ka["misses"] or ka["residualSeconds"] not in (0, None)) and mode == "--splice":
        print(json.dumps({"STOP": "known-answer miss (KA4 residual)", **ka}, default=float)); sys.exit(2)
    if mode == "--splice" and not only:
        splice(res)


def splice(res):
    """additive write of S.engineContextFields (+ stamp); no existing key changes."""
    flags = {}
    for k, st in res["strata"].items():
        unk = (st["thermal"]["unknown"] or {"share": 0})["share"]
        flags[k] = {"coolantUnknownShareOver50Pct": bool(unk > 0.5), "sensitivityOver5pp": bool(st["sensitivityMaxPp"] > 5.0),
                    "unresolvedNoCandidateUnder10Pct": bool(st["unresolvedNoCandidate"] and st["unresolvedNoCandidate"]["share"] < 0.10)}
    block = {"_provenance": "GENERATED by tools/engine_context_fields.py (M559). Do not hand-edit.", "schemaVersion": 1,
             "basis": "raw bytes; 1 s grid identical to the M46 dissipation census (1 s mean, forward fill limit 3, speed priority); engine rotating = rpm > 400; current discharge-positive; coolant by the last non-null raw sample, valid <= 30 s; raw/ = sha256-verified originals (M366)",
             "inputs": {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "rawListSha256": res["rawListSha256"]},
             "seed": SEED, "draws": DRAWS, "minDays": MIN_DAYS, "params": BASE, "variants": list(VARIANTS), "labels": list(LABELS), "support": {"minSeconds": SUPPORT[0], "minDrives": SUPPORT[1], "minDays": SUPPORT[2]},
             "eligible": res["eligible"], "knownAnswer": res["knownAnswer"], "strata": res["strata"], "flags": flags,
             "limits": ["rotation is logged; combustion and purpose are not: the calculated boost, load and fuel rate are proxies (the fuel rate is app-calculated), there is no injector or fuel-cut signal",
                        "candidate labels are non-exclusive and none states the purpose of the engine; a sample with no candidate is unresolved",
                        "the thermal context label fires on every cold-coolant (<= 60 C) rotating sample, so the unresolved share is reported with and without it; the warming and warm values stay a descriptive field with a 75 / 80 / 85 C band table (Rev 3)",
                        "the thresholds are analysis bands (400 rpm, 2 A deadband, 60 / 80 C, 30 s coolant age), pre-registered and not fitted; sensitivities are reported",
                        "strata are cadence groups from the existing regime rule and are never pooled; the legacy panels are unchanged"]}
    block = json.loads(json.dumps(block, default=float))
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("engineContextFields", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    stamps_before = {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "engineContextFields"}
    A2["engineContextFields"] = block
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=block["inputs"]["driveMasterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M559: computed by tools/engine_context_fields.py from the raw bytes; additive, no published value recomputed; not M299-reproducible.", upstreamHashes=dict(block["inputs"]))
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A2["_artifactStamps"]["engineContextFields"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    assert stamps_before == {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "engineContextFields"}
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)
    print(json.dumps({"engineContextFields": "written"}))


if __name__ == "__main__":
    main()
