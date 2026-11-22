"""M743 known-answer tests (analyses/M743_spec.md Rev 2): the per-KPI re-baseline marker of tools/delta_report.py on a synthetic temp repo.
Nothing is read from or written to the repository payload."""
import io, json, os, sys, tempfile, contextlib

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import delta_report as D

SPECS = {"kpis": [{"name": "A", "path": ["a", "v"], "ci": [["a", "lo"], ["a", "hi"]]}, {"name": "B", "path": ["b", "v"], "ci": [["b", "lo"], ["b", "hi"]]}]}


def kp(v, hw):
    return {"value": v, "ci": [v - hw, v + hw]}


def setup(td, hist, cur, extra_args):
    os.makedirs(os.path.join(td, "tools")); os.makedirs(os.path.join(td, "snapshots"))
    json.dump(SPECS, open(os.path.join(td, "tools", "kpi_paths.json"), "w", encoding="utf-8"))
    json.dump({"a": {"v": cur["A"][0], "lo": cur["A"][0] - cur["A"][1], "hi": cur["A"][0] + cur["A"][1]},
               "b": {"v": cur["B"][0], "lo": cur["B"][0] - cur["B"][1], "hi": cur["B"][0] + cur["B"][1]}}, open(os.path.join(td, "summary_arrays.json"), "w", encoding="utf-8"))
    with open(os.path.join(td, "snapshots", "kpis.jsonl"), "w", encoding="utf-8", newline="") as f:
        for i, h in enumerate(hist):
            rec = {"utc": "2026-01-0%dT00:00:00+00:00" % (i + 1), "kpis": h["kpis"]}
            if h.get("rebaseline"):
                rec["rebaseline"] = h["rebaseline"]
            f.write(json.dumps(rec) + "\n")


def run(td, args):
    D.ROOT = td
    old = sys.argv; sys.argv = ["delta_report.py"] + args
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            D.main()
        return None, json.load(open(os.path.join(td, "delta_report.json"), encoding="utf-8"))
    except SystemExit as e:
        return str(e), None
    finally:
        sys.argv = old


# planted history: A steps 26 -> 19.5 (step between snapshots 2 and 3), B stays flat
H = [{"kpis": {"A": kp(26.0, 2.5), "B": kp(10.0, 1.0)}}, {"kpis": {"A": kp(26.2, 2.5), "B": kp(10.0, 1.0)}},
     {"kpis": {"A": kp(19.5, 4.0), "B": kp(10.1, 1.0)}}, {"kpis": {"A": kp(19.6, 4.0), "B": kp(10.1, 1.0)}}]
CUR = {"A": (20.0, 4.0), "B": (10.2, 1.0)}

# K1a: no marker = old behaviour (first snapshot is the reference, cumulative flag fires for A only)
with tempfile.TemporaryDirectory() as td:
    setup(td, H, CUR, [])
    err, rep = run(td, [])
    assert err is None
    assert rep["flags"] == ["A: cumulative drift > baseline CI half-width"], rep["flags"]
    assert abs(rep["kpis"]["A"]["cumulative_drift"] - (20.0 - 26.0)) < 1e-12
    assert rep["kpis"]["A"]["baselineValue"] == 26.0 and "history" not in rep["kpis"]["A"]

# K1b: marker on A (record 3, complete CI) moves the reference; B keeps the first-snapshot reference
H2 = [dict(h) for h in H]; H2[2] = {"kpis": H[2]["kpis"], "rebaseline": ["A"]}
with tempfile.TemporaryDirectory() as td:
    setup(td, H2, CUR, [])
    err, rep = run(td, [])
    assert err is None and rep["flags"] == [], rep["flags"]
    a, b = rep["kpis"]["A"], rep["kpis"]["B"]
    assert a["baselineValue"] == 19.5 and a["baselineHalfWidth"] == 4.0 and abs(a["cumulative_drift"] - 0.5) < 1e-12
    assert a["firstSnapshotValue"] == 26.0 and len(a["history"]) == 4 and a["history"][-1]["value"] == 19.6
    assert b["baselineValue"] == 10.0 and "history" not in b, "an unmarked KPI keeps the old reference"

# K1c: a marker whose record lacks a complete CI is ignored (falls back to the first snapshot)
H3 = [dict(h) for h in H]; H3[2] = {"kpis": {"A": {"value": 19.5, "ci": [None, 23.5]}, "B": H[2]["kpis"]["B"]}, "rebaseline": ["A"]}
with tempfile.TemporaryDirectory() as td:
    setup(td, H3, CUR, [])
    err, rep = run(td, [])
    assert err is None and rep["kpis"]["A"]["baselineValue"] == 26.0

# K1d: --rebaseline guards (needs --commit and --milestone; unknown KPI; per-step flag refuses) and the append-only record
with tempfile.TemporaryDirectory() as td:
    setup(td, H, CUR, [])
    f = os.path.join(td, "snapshots", "kpis.jsonl"); before = open(f, "rb").read()
    err, _ = run(td, ["--rebaseline", "A"]); assert err and "needs --commit and --milestone" in err
    err, _ = run(td, ["--commit", "--rebaseline", "NOPE", "--milestone", "M743"]); assert err and "unknown KPIs" in err
    assert open(f, "rb").read() == before, "a refused call appends nothing"
    err, _ = run(td, ["--commit", "--rebaseline", "A", "--milestone", "M743"]); assert err is None
    after = open(f, "rb").read()
    assert after.startswith(before), "old lines are never rewritten"
    last = json.loads(after[len(before):].decode("utf-8"))
    assert last["rebaseline"] == ["A"] and last["rebaselineMilestone"] == "M743" and last["kpis"]["A"]["value"] == 20.0
    err, rep = run(td, [])          # the next run uses the new reference
    assert err is None and rep["kpis"]["A"]["baselineValue"] == 20.0 and rep["flags"] == [], rep["flags"]
with tempfile.TemporaryDirectory() as td:
    setup(td, H, {"A": (30.0, 4.0), "B": (10.2, 1.0)}, [])        # fresh shift of A: outside the previous CI
    f = os.path.join(td, "snapshots", "kpis.jsonl"); before = open(f, "rb").read()
    err, rep = run(td, ["--commit", "--rebaseline", "A", "--milestone", "M743"])
    assert err and "per-step flag" in err, err
    assert open(f, "rb").read() == before, "a refused re-baseline appends nothing"
print("test_delta_report_rebaseline: OK")
