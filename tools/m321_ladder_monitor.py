#!/usr/bin/env python3
"""M321 (spec: analyses/M321_spec.md rev 2): report-only drift monitor for the M119-v2 pack-temperature ladder (M320 Part C).
Reads the exact per-drive histogram cache analyses/M321_tpack_cache.json, compares the current corpus with the carried ladder
(summary_arrays.json -> socHysteresisV2.tempLadder) and writes ONLY socHysteresisV2.tempLadderMonitor (LF, isolation-checked).
  python tools/m321_ladder_monitor.py rebase --tables TABLES.pkl   # new frozen basis from the tools/m318_run.py tables (after a V2 refit + tools/m320_ladder.py)
  python tools/m321_ladder_monitor.py update                       # extend the cache for NON-basis files from raw_only/, recompute the monitor, splice
  python tools/m321_ladder_monitor.py check-path --n 30            # incremental path == tables path for the last 79 basis drives + N seeded-random earlier ones
`gate(arrays)` is imported by release_check.py. Thresholds, quantile rule and snap are IMPORTED from tools/m320_ladder.py (not duplicated).
Wording: W1 is a shift of the corpus pack-temperature distribution (seasonal, confounded), never model invalidity or degradation."""
import argparse, datetime, hashlib, json, os, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import m320_ladder as L

CACHE = os.path.join(ROOT, "analyses", "M321_tpack_cache.json")
ACKS = os.path.join(ROOT, "analyses", "M321_acknowledgements.json")
CODE_FILES = ("m119v2_model.py", "tools/m318_run.py", "tools/m320_ladder.py")
EARLY_DAYS = 20
SIDES = ("start", "stop")


# ------------------------------------------------------------------ hashing / io
def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def code_sha(root=ROOT):
    """Selection / complete-case code key (CRLF-normalised so a Windows checkout and CI agree)."""
    h = hashlib.sha256()
    for f in CODE_FILES:
        h.update(f.encode()); h.update(open(os.path.join(root, f), "rb").read().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def write_json_lf(path, obj, **kw):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, **kw))


def load_cache(path=CACHE):
    return json.load(open(path, encoding="utf-8"))


# ------------------------------------------------------------------ histograms
def entries_from_tables(S, T, files, model=None):
    """Exact complete-case histograms {file: {'day', 'start': {'%.4f': [n, events]}, 'stop': {...}}} from the at-risk tables."""
    m = model or L._model()
    out = {f: {"day": m._day_key(f), "start": {}, "stop": {}} for f in files}
    for side, t in (("start", S), ("stop", T)):
        cc = t.dropna(subset=m.CORE5)
        g = cc.assign(v=cc["tpack"].round(4)).groupby(["file", "v"]).agg(n=("y", "size"), ev=("y", "sum")).reset_index()
        for f, v, n, ev in g.itertuples(index=False):
            if f in out:
                out[f][side]["%.4f" % float(v)] = [int(n), int(ev)]
    return out


def rows_frame(entries, files, side):
    """Long frame (file, day, v, n, ev) for the given files."""
    recs = [(f, entries[f]["day"], float(v), n, ev) for f in files for v, (n, ev) in entries[f][side].items()]
    return pd.DataFrame(recs, columns=["file", "day", "v", "n", "ev"])


# ------------------------------------------------------------------ statistics (M320 definitions)
def quantile_set(df):
    if df.empty:
        return None
    v, n = df["v"].values, df["n"].values.astype(float)
    dtot = df.groupby("day")["n"].transform("sum").values.astype(float)
    out = {}
    for name, q in L.QUANTILES:
        qv = L.weighted_quantile(v, n, q)
        dq = L.weighted_quantile(v, n / dtot, q)
        out[name] = {"quantileValue": round(qv, 3), "snapped": L.snap(qv), "dayWeightedQuantileValue": round(dq, 3), "dayWeightedSnapped": L.snap(dq)}
    return out


def band_support(df, level):
    m = (df["v"] >= level - L.BAND) & (df["v"] <= level + L.BAND)
    ev = m & (df["ev"] > 0)
    nd = int(df.loc[ev, "day"].nunique())
    ne = int(df.loc[m, "ev"].sum())
    return {"nEvents": ne, "nDays": nd, "nAtRiskS": int(df.loc[m, "n"].sum()), "admissible": bool(ne >= L.GATE_EVENTS and nd >= L.GATE_DAYS)}


def _g(x):
    return f"{x:g}"


def w2_candidates(cur, finals):
    """W2 rev 3: grid levels L <= min(finals) - 2*BAND (disjoint from the lowest final level's band) whose closed band passes the gate.
    At L == min(finals) - 2*BAND the candidate band shares its endpoint value with the neighbouring band: the endpoint count is reported and
    the candidate is labelled boundary-dependent if excluding the endpoint rows flips the gate. L + STEP of that bound is never a candidate."""
    bound = min(finals) - 2 * L.BAND
    out = []
    lvl = L.snap(L.T_RANGE[0])
    while lvl <= bound + 1e-9:
        s = band_support(cur, lvl)
        if s["admissible"]:
            ep = lvl + L.BAND
            shared = abs(lvl - bound) < 1e-9
            at_ep = cur[np.isclose(cur["v"], ep)]
            dep = bool(shared and not band_support(cur[~np.isclose(cur["v"], ep)], lvl)["admissible"])
            out.append({"level": lvl, **s, "earlySupport": bool(s["nDays"] < EARLY_DAYS), "sharedEndpointC": (ep if shared else None),
                        "nAtSharedEndpoint": ({"nAtRiskS": int(at_ep["n"].sum()), "nEvents": int(at_ep["ev"].sum())} if shared else None), "boundaryDependent": dep})
        lvl += L.STEP
    return out


def w2_rev2_literal(cur, finals):
    """DIAGNOSTIC ONLY (never used for a warning): the defective rev-2 rule (any grid level colder than the lowest final level minus one step)."""
    out, lvl = [], L.snap(L.T_RANGE[0])
    while lvl <= min(finals) - L.STEP + 1e-9:
        s = band_support(cur, lvl)
        if s["admissible"]:
            out.append({"level": lvl, **s})
        lvl += L.STEP
    return out


def evaluate_side(side, cur, basis_df, new_df, carried):
    """Warnings and statistics for one side. `cur` = pooled long frame; `carried` = socHysteresisV2.tempLadder[side]."""
    cq = {c["name"]: c["quantileValue"] for c in carried["candidates"]}      # UNSNAPPED carried quantile values (P5 18.75 snaps to 20)
    finals = [l["value"] for l in carried["levels"]]
    bobs = basis_df[basis_df["n"] > 0]
    fit_min, fit_max = float(bobs["v"].min()), float(bobs["v"].max())          # fit-basis range from the cache's own basis population (same complete-case rows)
    obs = cur[cur["n"] > 0]
    cur_min, cur_max = float(obs["v"].min()), float(obs["v"].max())
    qs = quantile_set(cur)
    w, info, codes = [], [], []
    # W1: distribution shift of the corpus pack temperature (>= 1 grid step from the carried quantile value)
    for name, _ in L.QUANTILES:
        if abs(qs[name]["quantileValue"] - cq[name]) >= L.STEP:
            codes.append(f"W1:{side}:{name}")
            w.append(f"W1 shift of the corpus pack-temperature distribution ({side}): {name} {_g(cq[name])} -> {_g(qs[name]['quantileValue'])} C (>= one grid step); seasonal and confounded, a refit decision, not model invalidity")
    # W2 (rev 3, post-hoc): a colder level on a band that does NOT overlap the lowest carried final level's band passes the support gate
    cold = w2_candidates(cur, finals)
    if cold:
        c0 = cold[0]
        codes.append(f"W2:{side}:{_g(c0['level'])}")
        w.append(f"W2 cold candidate ({side}): the {_g(c0['level'])} C band passes the support gate ({c0['nEvents']} events, {c0['nDays']} event days)" +
                 (" - early support (< 20 event days)" if c0["earlySupport"] else "") + (" - boundary-dependent (the gate flips without the shared endpoint rows)" if c0["boundaryDependent"] else "") +
                 "; a colder level needs a new spec, no silent refit")
    # W3 / W3-info: observed range vs the fit-basis range
    ext = max(0.0, fit_min - cur_min, cur_max - fit_max)
    out_rows = cur[(cur["v"] < fit_min) | (cur["v"] > fit_max)]
    if ext > 0:
        outside = {"nAtRiskS": int(out_rows["n"].sum()), "nEvents": int(out_rows["ev"].sum()), "nDays": int(out_rows["day"].nunique())}
        info.append(f"W3-info ({side}): the observed pack temperature {_g(cur_min)}-{_g(cur_max)} C extends beyond the fit-basis range {_g(fit_min)}-{_g(fit_max)} C "
                    f"({outside['nAtRiskS']} at-risk s, {outside['nEvents']} events, {outside['nDays']} days outside)")
        codes.append(f"W3i:{side}")
    else:
        outside = {"nAtRiskS": 0, "nEvents": 0, "nDays": 0}
    if cur_min <= fit_min - L.STEP + 1e-9 or cur_max >= fit_max + L.STEP - 1e-9:
        codes.append(f"W3:{side}")
        w.append(f"W3 range extension ({side}): observed {_g(cur_min)}-{_g(cur_max)} C vs fit-basis {_g(fit_min)}-{_g(fit_max)} C (>= one grid step); the fit has no data there: a new spec is needed")
    # W4: a carried final level lost its support
    sup = {_g(l): band_support(cur, l) for l in finals}
    for l in finals:
        if not sup[_g(l)]["admissible"]:
            codes.append(f"W4:{side}:{_g(l)}")
            w.append(f"W4 support loss ({side}): the carried level {_g(l)} C no longer passes the gate ({sup[_g(l)]['nEvents']} events, {sup[_g(l)]['nDays']} event days)")
    hi = max(finals)
    if carried.get("fewDaysFlag") and any(carried["fewDaysFlag"].values()) and sup[_g(hi)]["nDays"] >= EARLY_DAYS:
        info.append(f"info ({side}): the {_g(hi)} C band now has {sup[_g(hi)]['nDays']} event days (>= 20); the limited-day-support caution can be reconsidered at the next refit")
    return {"quantilesPooled": qs, "quantilesBasis": quantile_set(basis_df), "quantilesNew": quantile_set(new_df),
            "carriedQuantileValues": cq, "supportAtCarriedLevels": sup, "observedRangeC": [cur_min, cur_max], "fitBasisRangeC": [fit_min, fit_max], "fitBasisRangeArraysC": [carried["tpackMinC"], carried["tpackMaxC"]],
            "outsideFitRange": outside, "coldCandidates": cold, "coldCandidate": (cold[0] if cold else None),
            "warnings": w, "information": info, "_codes": codes}


def status_of(codes):
    if any(c.startswith(("W2", "W3:")) for c in codes):
        return "warn-newspec"
    if any(c.startswith(("W1", "W4")) for c in codes):
        return "warn-refit"
    return "ok"


def warning_set_hash(codes):
    return hashlib.sha256(json.dumps(sorted(c for c in codes if not c.startswith("W3i"))).encode()).hexdigest()


def build_monitor(arrays, cache, files, master_md5, raw_sha_now=None, now=None):
    """The tempLadderMonitor block for the current master `files` from the cache + carried ladder."""
    ladder = arrays["socHysteresisV2"]["tempLadder"]
    basis = set(cache["basis"]["files"])
    entries = cache["entries"]
    block = {"masterMd5": master_md5, "basisNDrives": ladder["start"]["basisNDrives"], "currentNDrives": len(files),
             "newDrivesSinceBasis": len([f for f in files if f not in basis]), "cacheSha256": None, "selectionCodeSha256": code_sha(),
             "policy": "W2/W3 start a new spec; no silent refit. W1/W4 call for a refit decision. Model-derived monitoring statistics; the F03 label of the V2 block applies.",
             "generated": now or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    f03 = []
    if raw_sha_now is not None:
        f03 = sorted(f for f in cache["basis"]["files"] if f in raw_sha_now and raw_sha_now[f] != cache["basis"]["rawSha256"].get(f))
    block["f03ProvenanceFlag"] = {"basisFilesWithChangedRawSha256": f03, "note": "reported separately; basis entries are frozen and never recomputed into drift"}
    codes, sides = [], {}
    code_stale = cache["basis"]["selectionCodeSha256"] != block["selectionCodeSha256"]
    for s in SIDES:
        cur = rows_frame(entries, files, s)
        bdf = cur[cur["file"].isin(basis)]
        ndf = cur[~cur["file"].isin(basis)]
        r = evaluate_side(s, cur, bdf, ndf, ladder[s])
        codes += r.pop("_codes")
        sides[s] = r
    block["sides"] = sides
    block["warningCodes"] = sorted(codes)
    block["warningSetHash"] = warning_set_hash(codes)
    block["warnings"] = [x for s in SIDES for x in sides[s]["warnings"]]
    block["information"] = [x for s in SIDES for x in sides[s]["information"]]
    block["status"] = "cache-invalid" if code_stale else status_of(codes)
    return block


# ------------------------------------------------------------------ gate (imported by release_check.py)
def ref_resolves(ref, root=ROOT):
    """An acknowledgement `ref` must name an existing CHANGELOG '## M###' heading (first token, e.g. 'M322 ...') or an existing analyses/<spec> file."""
    import re
    ref = str(ref or "").strip()
    if not ref:
        return False
    tok = ref.split()[0]
    if re.fullmatch(r"M\d+", tok):
        cl = os.path.join(root, "CHANGELOG.md")
        if not os.path.exists(cl):
            return False
        with open(cl, "r", encoding="utf-8", errors="replace") as f:
            return any(line.startswith("## " + tok + " ") or line.rstrip() == "## " + tok for line in f)
    return os.path.isfile(os.path.join(root, "analyses", os.path.basename(tok))) or os.path.isfile(os.path.join(root, tok))


def ack_valid(a, mon, root=ROOT):
    """Hash + resolvable ref + the ack was written for THIS basis (selection-code hash and basis size): an ack from an old basis cannot clear a
    recurring warning set after a rebase (Director C1). The date is typed by hand and is not checked."""
    return bool(a.get("warningSetHash") == mon.get("warningSetHash") and ref_resolves(a.get("ref"), root)
                and a.get("selectionCodeSha256") == mon.get("selectionCodeSha256") and a.get("basisNDrives") == mon.get("basisNDrives"))


def gate(arrays, root=ROOT):
    """-> (fails, warns). Spec item 7."""
    fails, warns = [], []
    v2 = arrays.get("socHysteresisV2") or {}
    mon = v2.get("tempLadderMonitor")
    lad = v2.get("tempLadder")
    if not lad:
        return ["M321: socHysteresisV2.tempLadder missing (run tools/m320_ladder.py after a V2 refit)"], warns
    for s in SIDES:
        if lad[s].get("basisNDrives") != v2.get("corpusSizeAtRecompute"):
            fails.append(f"M321: tempLadder.{s}.basisNDrives {lad[s].get('basisNDrives')} != socHysteresisV2.corpusSizeAtRecompute {v2.get('corpusSizeAtRecompute')} (V2 refit without a re-derived ladder)")
    if not mon:
        return fails + ["M321: socHysteresisV2.tempLadderMonitor missing (run tools/m321_ladder_monitor.py update)"], warns
    master = os.path.join(root, "drive_master.csv")
    md5 = hashlib.md5(open(master, "rb").read()).hexdigest()
    if mon.get("masterMd5") != md5:
        fails.append("M321: monitor masterMd5 differs from the current drive_master.csv (monitor stale)")
    total = (arrays.get("meta") or {}).get("totalDrives")
    if mon.get("currentNDrives") != total:
        fails.append(f"M321: monitor currentNDrives {mon.get('currentNDrives')} != meta.totalDrives {total}")
    cpath = os.path.join(root, "analyses", "M321_tpack_cache.json")
    if not os.path.exists(cpath):
        return fails + ["M321: analyses/M321_tpack_cache.json missing"], warns
    craw = open(cpath, "rb").read()
    if mon.get("cacheSha256") != sha256_bytes(craw):
        fails.append("M321: monitor cacheSha256 does not match analyses/M321_tpack_cache.json")
    cache = json.loads(craw.decode("utf-8"))
    files = set(pd.read_csv(master, usecols=["file"])["file"].astype(str))
    if set(cache["entries"]) != files:
        fails.append(f"M321: cache file set != master file set (cache {len(cache['entries'])}, master {len(files)})")
    if mon.get("selectionCodeSha256") != code_sha(root) or mon.get("status") == "cache-invalid" or cache["basis"]["selectionCodeSha256"] != code_sha(root):
        fails.append("M321: selection code changed since the cache basis (status cache-invalid): re-run tools/m321_ladder_monitor.py rebase")
    if mon.get("status") == "warn-newspec":
        acks = json.load(open(os.path.join(root, "analyses", "M321_acknowledgements.json"), encoding="utf-8")) if os.path.exists(os.path.join(root, "analyses", "M321_acknowledgements.json")) else []
        if not any(ack_valid(a, mon, root) for a in acks):
            fails.append(f"M321: W2/W3 active ({'; '.join(mon.get('warnings', []))}) without a valid acknowledgement record for warningSetHash {mon.get('warningSetHash')[:12]} "
                         f"(needs warningSetHash, a ref naming an existing CHANGELOG '## M###' heading or analyses/ spec file, and this basis: selectionCodeSha256 + basisNDrives)")
    for x in mon.get("warnings", []) + mon.get("information", []):
        warns.append("M321 " + x)
    for f in (mon.get("f03ProvenanceFlag") or {}).get("basisFilesWithChangedRawSha256", []):
        warns.append(f"M321 F03 provenance flag: raw sha256 of basis file {f} differs from its basis entry (not counted as drift)")
    return fails, warns


# ------------------------------------------------------------------ commands
def _master():
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    return dm, hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()


def _raw_dir(a):
    return a.raw_dir or os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw_only")


def cmd_rebase(a):
    import pickle
    P = pickle.load(open(a.tables, "rb"))
    S, T = P["tables"][0], P["tables"][1]
    files = list(P["files"])
    dm, md5 = _master()
    assert files == list(dm["file"]), "tables must cover exactly the current master files (rebase after the refit on the live corpus)"
    rd = _raw_dir(a)
    ent = entries_from_tables(S, T, files)
    sha = {f: file_sha(os.path.join(rd, f)) for f in files}
    for f in files:
        ent[f]["rawSha256"] = sha[f]
    cache = {"schema": 1, "fields": "entries[file][side]['%.4f' tpack] = [n at-risk seconds, n events] over complete-case rows",
             "basis": {"nDrives": len(files), "files": files, "rawSha256": sha, "selectionCodeSha256": code_sha(), "masterMd5": md5,
                       "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")},
             "stats": {s: {"distinctValues": len({v for f in files for v in ent[f][s]})} for s in SIDES}, "entries": ent}
    write_json_lf(CACHE, cache, sort_keys=True, separators=(",", ":"))
    print(json.dumps({"rebased": len(files), "bytes": os.path.getsize(CACHE), "stats": cache["stats"]}))


def _extend(cache, dm, rd):
    m = L._model()
    new = [f for f in dm["file"] if f not in cache["entries"]]
    if new:
        def loader(fn):
            with open(os.path.join(rd, fn), "rb") as fh:
                return fh.read()
        sub = dm[dm["file"].isin(new)]
        S, T = m._corpus_tables(sub, raw_loader=loader, raw_dir=rd)[:2]
        ent = entries_from_tables(S, T, new, model=m)
        for f in new:
            ent[f]["rawSha256"] = file_sha(os.path.join(rd, f))
            cache["entries"][f] = ent[f]
    return new


def cmd_update(a):
    cache = load_cache()
    dm, md5 = _master()
    rd = _raw_dir(a)
    files = list(dm["file"])
    new = _extend(cache, dm, rd)
    assert set(cache["entries"]) >= set(files), "cache lacks master files"
    for f in list(cache["entries"]):
        if f not in set(files):            # a master file removed: never silently kept
            raise SystemExit(f"cache entry {f} is not in the master")
    if new:
        write_json_lf(CACHE, cache, sort_keys=True, separators=(",", ":"))
    craw = open(CACHE, "rb").read()
    raw_now = {f: file_sha(os.path.join(rd, f)) for f in cache["basis"]["files"] if os.path.exists(os.path.join(rd, f))}
    p = os.path.join(ROOT, "summary_arrays.json")
    A = json.load(open(p, encoding="utf-8"))
    block = build_monitor(A, cache, files, md5, raw_sha_now=raw_now)
    block["cacheSha256"] = sha256_bytes(craw)
    v2 = A["socHysteresisV2"]
    v2["tempLadderMonitor"] = block
    st = A["_artifactStamps"]["socHysteresisV2"]
    note = st.get("computationStatusNote") or ""
    if "M321" not in note:
        st["computationStatusNote"] = (note + " | M321: tempLadderMonitor added (report-only drift monitor for the M320 ladder; fit and ladder unchanged).").lstrip(" |")
    head = json.loads(subprocess.check_output(["git", "show", "HEAD:summary_arrays.json"], cwd=ROOT).decode("utf-8"))
    write_json_lf(p, A, ensure_ascii=False, indent=1)
    A2 = json.load(open(p, encoding="utf-8"))
    diff = sorted(k for k in set(A2) | set(head) if A2.get(k) != head.get(k))
    sub = sorted(k for k in set(A2["socHysteresisV2"]) | set(head["socHysteresisV2"]) if A2["socHysteresisV2"].get(k) != head["socHysteresisV2"].get(k))
    print(json.dumps({"status": block["status"], "warnings": block["warnings"], "information": block["information"], "newFilesCached": len(new),
                      "arrays_keys_changed_vs_HEAD": diff, "socHysteresisV2_keys_changed_vs_HEAD": sub}))


def cmd_check_path(a):
    """Path equivalence: the incremental raw_only path reproduces the tables-path cache entries exactly."""
    cache = load_cache()
    dm, _ = _master()
    files = list(dm["file"])
    pick = files[-79:] + list(np.random.default_rng(42).choice(files[:-79], size=a.n, replace=False)) if a.n else files[-79:]
    rd = _raw_dir(a)
    m = L._model()
    sub = dm[dm["file"].isin(pick)]
    def loader(fn):
        with open(os.path.join(rd, fn), "rb") as fh:
            return fh.read()
    S, T = m._corpus_tables(sub, raw_loader=loader, raw_dir=rd)[:2]
    ent = entries_from_tables(S, T, list(pick), model=m)
    bad = [f for f in pick if any(ent[f][k] != cache["entries"][f][k] for k in ("day", "start", "stop"))]
    print(json.dumps({"checked": len(pick), "mismatches": bad}))
    sys.exit(1 if bad else 0)


def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("rebase"); r.add_argument("--tables", required=True); r.add_argument("--raw-dir"); r.set_defaults(f=cmd_rebase)
    u = sp.add_parser("update"); u.add_argument("--raw-dir"); u.set_defaults(f=cmd_update)
    c = sp.add_parser("check-path"); c.add_argument("--n", type=int, default=30); c.add_argument("--raw-dir"); c.set_defaults(f=cmd_check_path)
    a = ap.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
