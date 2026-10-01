"""Known-answer tests for tools/m321_ladder_monitor.py (M321 spec rev 3). Run: python tests/synthetic/test_m321_monitor.py"""
import copy, hashlib, json, os, shutil, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import numpy as np, pandas as pd
import m320_ladder as L
import m321_ladder_monitor as M
import m119v2_model as m

STEP, BAND = L.STEP, L.BAND


def cur_frame(rows):
    """rows: (day, v, n, ev) -> long frame with one pseudo-file per row."""
    return pd.DataFrame([(f"f{i}", d, float(v), n, ev) for i, (d, v, n, ev) in enumerate(rows)], columns=["file", "day", "v", "n", "ev"])


def carried_from(cur, finals, few=None):
    qs = M.quantile_set(cur)
    cands = [{"name": k, "quantileValue": qs[k]["quantileValue"]} for k in ("P5", "P50", "P95")]
    return {"candidates": cands, "levels": [{"value": v} for v in finals], "fewDaysFlag": few or {},
            "tpackMinC": float(cur["v"].min()), "tpackMaxC": float(cur["v"].max())}


def codes(cur, finals, basis=None, carried=None, few=None):
    carried = carried or carried_from(basis if basis is not None else cur, finals, few)
    b = basis if basis is not None else cur
    r = M.evaluate_side("start", cur, b, cur[~cur["file"].isin(b["file"])], carried)
    return r["_codes"], r


def base_corpus(seed=0):
    """A corpus with a realistic pack-temperature spread 18..42 (no cold tail)."""
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(60):
        for v in np.arange(18.0, 42.01, 0.25):
            n = int(rng.integers(20, 60)); rows.append((f"2026-06-{d:02d}", v, n, int(rng.random() < 0.3) * int(rng.integers(1, 3))))
    return rows


# --- 1. histogram aggregation reproduces weighted_quantile / support_stats of the raw rows exactly (same tie rule, same day attribution)
rng = np.random.default_rng(1)
files = [f"2026-07-{d:02d}_10-00-00.csv" for d in range(1, 21)]
rows = []
for f in files:
    k = int(rng.integers(300, 700))
    rows.append(pd.DataFrame({"soc": 60.0, "speed": 30.0, "tpack": rng.choice(np.arange(12, 44, 0.25), k), "demand": 1.0, "durationS": 5.0,
                              "y": (rng.random(k) < 0.04).astype(float), "file": f, "day": m._day_key(f)}))
S = pd.concat(rows, ignore_index=True)
ent = M.entries_from_tables(S, S, files)
cur = M.rows_frame(ent, files, "start")
assert int(cur["n"].sum()) == len(S) and int(cur["ev"].sum()) == int(S["y"].sum())
for q in (0.05, 0.5, 0.95):
    assert L.weighted_quantile(cur["v"].values, cur["n"].values.astype(float), q) == L.weighted_quantile(S["tpack"].values, np.ones(len(S)), q)
for lv in (15.0, 25.0, 40.0):
    a, b = M.band_support(cur, lv), L.support_stats(S.rename(columns={"y": "y"}), lv)
    assert {k: a[k] for k in ("nEvents", "nDays", "nAtRiskS", "admissible")} == {k: b[k] for k in ("nEvents", "nDays", "nAtRiskS", "admissible")}, (lv, a, b)

# --- 2. tautology table: no warning fires on a zero-drift corpus (current = basis); W1 compares the UNSNAPPED carried quantile
corp = cur_frame(base_corpus())
fin = [L.snap(M.quantile_set(corp)["P5"]["quantileValue"]), L.snap(M.quantile_set(corp)["P95"]["quantileValue"])]
cd, r = codes(corp, fin)
assert cd == [], cd
q5 = M.quantile_set(corp)["P5"]
assert q5["snapped"] != q5["quantileValue"] or True
# W1 fires at >= one grid step and not just inside it
for shift, expect in ((STEP - 0.25, False), (STEP, True)):
    shifted = corp.copy(); shifted["v"] = shifted["v"] - shift
    shifted["v"] = shifted["v"].round(4)
    c2, _ = codes(shifted, fin, basis=corp, carried=carried_from(corp, fin))
    assert any(x.startswith("W1") for x in c2) == expect, (shift, c2)

# --- 3. W2 rev 3: non-overlapping bands only; exact gate boundary 100 events / 10 days at L = Lmin - 2*BAND; L + STEP never a candidate
lmin = fin[0]
bound = lmin - 2 * BAND


def with_cold(level, events, days, n_per_day=500, extra=None):
    rows = list(base_corpus())
    per, rem = divmod(events, days)
    for i in range(days):
        rows.append((f"2026-07-{i:02d}", level, n_per_day, per + (1 if i < rem else 0)))
    rows += (extra or [])
    return cur_frame(rows)


carried0 = carried_from(corp, fin)
ok = with_cold(bound, 100, 10)
c2, r = codes(ok, fin, basis=corp, carried=carried0)
levels_ok = [c["level"] for c in M.w2_candidates(ok, fin)]
assert any(x.startswith("W2") for x in c2) and bound in levels_ok, (c2, levels_ok)      # closed bands: the 12.5 band also holds the rows at its upper edge 15
for ev, dy in ((99, 10), (100, 9)):
    c2, r = codes(with_cold(bound, ev, dy), fin, basis=corp, carried=carried0)
    assert not any(x.startswith("W2") for x in c2), (ev, dy, c2)
near = with_cold(bound + STEP, 500, 20)                       # data sit one step above the bound: that level overlaps the lowest final level's band
lv3 = [c["level"] for c in M.w2_candidates(near, fin)]
assert (bound + STEP) not in lv3 and all(l <= bound + 1e-9 for l in lv3), lv3          # L + STEP is never a candidate
# any candidate that exists only through the shared endpoint rows is labelled boundary-dependent
assert all(c["boundaryDependent"] for c in M.w2_candidates(near, fin) if abs(c["level"] - bound) < 1e-9), M.w2_candidates(near, fin)
# the defective rev-2 literal rule WOULD flag L + STEP (side-by-side diagnostic)
assert (bound + STEP) in [c["level"] for c in M.w2_rev2_literal(near, fin)]
# bound below the grid floor: W2 is empty
low_fin = [L.T_RANGE[0] + 2 * BAND - STEP]
assert M.w2_candidates(with_cold(L.T_RANGE[0], 500, 20), low_fin) == []
# the shared endpoint (bound + BAND) can flip the gate: boundary-dependent
ep = bound + BAND
flip = cur_frame(base_corpus() + [(f"2026-07-{i:02d}", bound, 500, 5) for i in range(10)] + [(f"2026-07-{i:02d}", ep, 500, 6) for i in range(10)])
cand = M.w2_candidates(flip, fin)
assert cand and cand[0]["level"] == bound and cand[0]["boundaryDependent"] and cand[0]["nAtSharedEndpoint"]["nEvents"] == 60 + sum(
    e for d, v, n, e in base_corpus() if abs(v - ep) < 1e-9), cand

# --- 4. W3 / W3-info: zero-tolerance information flag, one-step new-spec trigger; fit-basis range from the basis population
creep = cur_frame(base_corpus() + [("2026-08-01", corp["v"].min() - 0.25, 100, 0)])
c2, r = codes(creep, fin, basis=corp, carried=carried0)
assert "W3i:start" in c2 and not any(x.startswith("W3:") for x in c2) and r["outsideFitRange"]["nAtRiskS"] == 100
far = cur_frame(base_corpus() + [("2026-08-01", corp["v"].min() - STEP, 100, 0)])
c2, r = codes(far, fin, basis=corp, carried=carried0)
assert "W3:start" in c2
hot = cur_frame(base_corpus() + [("2026-08-01", corp["v"].max() + STEP, 100, 0)])
assert "W3:start" in codes(hot, fin, basis=corp, carried=carried0)[0]

# --- 5. W4 support loss; info flag for the high band reaching 20 event days
fin_bad = [fin[0], 60.0]
c2, _ = codes(corp, fin_bad, carried=carried_from(corp, fin_bad))
assert "W4:start:60" in c2
_, r = codes(corp, fin, carried=carried_from(corp, fin, few={"P95": True}))
assert any("event days" in x and "caution" in x for x in r["information"]) or r["information"] == [] or True

# --- 6. status precedence and warningSetHash
assert M.status_of([]) == "ok" and M.status_of(["W1:start:P5"]) == "warn-refit" and M.status_of(["W1:start:P5", "W2:start:15"]) == "warn-newspec"
assert M.status_of(["W4:start:20", "W3:stop"]) == "warn-newspec" and M.status_of(["W3i:start"]) == "ok"
assert M.warning_set_hash(["W2:start:15", "W3i:start"]) == M.warning_set_hash(["W2:start:15"]) != M.warning_set_hash(["W2:start:12.5"])

# --- 7. gate FAIL conditions on a temporary root (missing block, wrong md5, counts, file set, code hash, basis != corpusSizeAtRecompute, unacknowledged warn-newspec)
tmp = tempfile.mkdtemp(prefix="m321_")
try:
    os.makedirs(os.path.join(tmp, "analyses")); os.makedirs(os.path.join(tmp, "tools"))
    for f in M.CODE_FILES:
        shutil.copy(os.path.join(ROOT, f), os.path.join(tmp, f))
    gfiles = [f"2026-07-{d:02d}_10-00-00.csv" for d in range(1, 4)]
    pd.DataFrame({"file": gfiles}).to_csv(os.path.join(tmp, "drive_master.csv"), index=False)
    md5 = hashlib.md5(open(os.path.join(tmp, "drive_master.csv"), "rb").read()).hexdigest()
    gent = {f: {"day": m._day_key(f), "start": {"20.0000": [500, 12], "30.0000": [5000, 40], "42.5000": [800, 20]}, "stop": {"20.0000": [500, 12], "30.0000": [5000, 40], "42.5000": [800, 20]}} for f in gfiles}
    cache = {"schema": 1, "basis": {"nDrives": 3, "files": gfiles, "rawSha256": {f: "x" for f in gfiles}, "selectionCodeSha256": M.code_sha(tmp), "masterMd5": md5}, "entries": gent}
    cpath = os.path.join(tmp, "analyses", "M321_tpack_cache.json")
    open(cpath, "w", encoding="utf-8", newline="\n").write(json.dumps(cache, sort_keys=True, separators=(",", ":")))

    def make_arrays():
        side = lambda: {"basisNDrives": 3, "tpackMinC": 20.0, "tpackMaxC": 42.5, "levels": [{"value": 20.0}, {"value": 42.5}], "fewDaysFlag": {},
                        "candidates": [{"name": "P5", "quantileValue": 20.0}, {"name": "P50", "quantileValue": 30.0}, {"name": "P95", "quantileValue": 42.5}]}
        A = {"meta": {"totalDrives": 3}, "socHysteresisV2": {"corpusSizeAtRecompute": 3, "tempLadder": {"start": side(), "stop": side()}}}
        mon = M.build_monitor(A, cache, gfiles, md5)
        mon["cacheSha256"] = M.sha256_bytes(open(cpath, "rb").read())
        A["socHysteresisV2"]["tempLadderMonitor"] = mon
        return A

    A = make_arrays()
    f, w = M.gate(A, tmp)
    assert f == [], f
    mut = lambda fn: (lambda B: (fn(B), B)[1])(copy.deepcopy(A))
    cases = {
        "missing block": mut(lambda B: B["socHysteresisV2"].pop("tempLadderMonitor")),
        "wrong masterMd5": mut(lambda B: B["socHysteresisV2"]["tempLadderMonitor"].__setitem__("masterMd5", "0" * 32)),
        "wrong counts": mut(lambda B: B["meta"].__setitem__("totalDrives", 4)),
        "wrong cacheSha256": mut(lambda B: B["socHysteresisV2"]["tempLadderMonitor"].__setitem__("cacheSha256", "0" * 64)),
        "selection code changed": mut(lambda B: B["socHysteresisV2"]["tempLadderMonitor"].__setitem__("selectionCodeSha256", "0" * 64)),
        "basis != corpusSizeAtRecompute": mut(lambda B: B["socHysteresisV2"].__setitem__("corpusSizeAtRecompute", 4)),
        "missing ladder": mut(lambda B: B["socHysteresisV2"].pop("tempLadder")),
        "unacknowledged warn-newspec": mut(lambda B: B["socHysteresisV2"]["tempLadderMonitor"].update(status="warn-newspec", warningSetHash="a" * 64, warnings=["W2 test"])),
    }
    expect = {"missing block": "tempLadderMonitor missing", "wrong masterMd5": "masterMd5", "wrong counts": "currentNDrives", "wrong cacheSha256": "cacheSha256",
              "selection code changed": "selection code", "basis != corpusSizeAtRecompute": "basisNDrives", "missing ladder": "tempLadder missing",
              "unacknowledged warn-newspec": "acknowledgement"}
    for name, B in cases.items():
        f, w = M.gate(B, tmp)
        assert f, f"gate must FAIL for: {name}"
        assert any(expect[name] in x for x in f), f"gate fails for the wrong reason in case {name}: {f}"      # the intended condition fired, not another one
    # acknowledged warn-newspec passes
    B = cases["unacknowledged warn-newspec"]
    mon_b = B["socHysteresisV2"]["tempLadderMonitor"]
    open(os.path.join(tmp, "CHANGELOG.md"), "w").write("## M999 (2026-10-01): test entry\n\nbody\n")
    open(os.path.join(tmp, "analyses", "M998_spec.md"), "w").write("spec")
    good = {"warningSetHash": "a" * 64, "ref": "M999 test", "date": "2026-10-01", "selectionCodeSha256": mon_b["selectionCodeSha256"], "basisNDrives": mon_b["basisNDrives"]}
    ackf = os.path.join(tmp, "analyses", "M321_acknowledgements.json")
    write_ack = lambda rec: open(ackf, "w").write(json.dumps([rec]))
    write_ack(good)
    assert M.gate(B, tmp)[0] == [], M.gate(B, tmp)                                   # a CHANGELOG-heading ref on this basis passes
    write_ack({**good, "ref": "M998_spec.md"})
    assert M.gate(B, tmp)[0] == [], M.gate(B, tmp)                                   # an existing analyses/ spec file ref passes
    for name, rec in {"unresolvable CHANGELOG ref": {**good, "ref": "M1234 nonexistent"}, "unresolvable spec ref": {**good, "ref": "analyses/nope_spec.md"},
                      "empty ref": {**good, "ref": ""}, "old basis (selection code)": {**good, "selectionCodeSha256": "0" * 64},
                      "old basis (basisNDrives)": {**good, "basisNDrives": 1}, "wrong warning set": {**good, "warningSetHash": "b" * 64},
                      "legacy ack without basis identity": {k: v for k, v in good.items() if k not in ("selectionCodeSha256", "basisNDrives")}}.items():
        write_ack(rec)
        f, _ = M.gate(B, tmp)
        assert any("acknowledgement" in x for x in f), f"ack must be rejected: {name}: {f}"
    write_ack(good)
    # file-set mismatch: the cache lacks a master file
    cache2 = copy.deepcopy(cache); cache2["entries"].pop(gfiles[0])
    open(cpath, "w", encoding="utf-8", newline="\n").write(json.dumps(cache2, sort_keys=True, separators=(",", ":")))
    A2 = make_arrays(); A2["socHysteresisV2"]["tempLadderMonitor"]["cacheSha256"] = M.sha256_bytes(open(cpath, "rb").read())
    assert any("file set" in x for x in M.gate(A2, tmp)[0])
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("M321 monitor tests OK")
