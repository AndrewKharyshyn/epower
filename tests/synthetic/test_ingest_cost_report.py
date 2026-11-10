"""M610a: tools/ingest_cost_report.py known answers on a toy runs directory (spec analyses/M610_spec.md Rev 1, A3 / R2)."""
import json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
import ingest_cost_report as CR


def put(root, rid, result, stages, failure=None, checkpoint=None):
    d = os.path.join(root, rid)
    os.makedirs(d)
    st = {"run": rid, "result": result, "stages": [{"id": x[0], "rc": (x[3] if len(x) > 3 else (0 if x[2] in ("ok", "restored_from_checkpoint") else 3)), "seconds": x[1], "status": x[2]} for x in stages]}
    if checkpoint:
        st["checkpoint"] = checkpoint
    json.dump(st, open(os.path.join(d, "status.json"), "w"))
    if failure:
        json.dump(failure, open(os.path.join(d, "failure.json"), "w"))


def main():
    tmp = tempfile.mkdtemp(prefix="xt_cost_")
    try:
        # batch 1: r1 stops at c on an acknowledgement (rc 3); r2 is a full rerun that fails a hard gate; r3 restores a, b and passes
        put(tmp, "20261101T000001Z", "gate_failed", [("a", 60, "ok"), ("b", 120, "ok"), ("c", 30, "gate_failed")], {"last_lines": ["Gate('needs --ack-estimator-change <reason>')"]})
        put(tmp, "20261101T000002Z", "gate_failed", [("a", 60, "ok"), ("b", 120, "ok"), ("c", 30, "gate_failed", 1)], {"last_lines": ["", "AssertionError: row count 12 != 13", ""]},
            {"resumed": False, "reason": "no valid checkpoint chain for this base state", "missReason": "data file changed: data/in.txt"})
        put(tmp, "20261101T000003Z", "ok", [("a", 0, "restored_from_checkpoint"), ("b", 0, "restored_from_checkpoint"), ("c", 40, "ok"), ("d", 10, "ok")], None,
            {"resumed": True, "restoredStages": 2})
        # batch 2 (open): an environment failure
        put(tmp, "20261102T000001Z", "gate_failed", [("a", 60, "ok"), ("b", 5, "gate_failed", 1)], {"last_lines": ["Traceback", "FileNotFoundError: [Errno 2] No such file: 'x'"]})
        rep = CR.build(tmp)
        b1, b2 = rep["batches"]
        assert (b1["nRuns"], b1["result"], b1["open"]) == (3, "ok", False), b1
        assert (b1["executedMin"], b1["uniqueMin"], b1["repeatedMin"], b1["repeatedShare"]) == (7.8, 3.8, 4.0, 1.043), b1       # 470 s executed, 230 s unique, 240 s repeated
        assert [(s["stage"], s["class"]) for s in b1["stops"]] == [("c", "escalation"), ("c", "hard")], b1["stops"]
        assert b1["stops"][1]["cause"].startswith("AssertionError"), b1["stops"][1]
        assert b1["resumeAttempts"][0]["resumed"] is False and b1["resumeAttempts"][0]["missReason"] == "data file changed: data/in.txt"
        assert b1["resumeAttempts"][1]["resumed"] and b1["resumeAttempts"][1]["restoredStages"] == 2
        assert b2["open"] and b2["stops"][0]["class"] == "environment" and b2["nRuns"] == 1, b2
        assert rep["totals"]["stopsByClass"] == {"escalation": 1, "hard": 1, "environment": 1}, rep["totals"]
        assert rep["totals"]["stopsByStage"] == {"c": 2, "b": 1}, rep["totals"]
        assert CR.build(tmp, last=1)["totals"]["scopeBatches"] == 1
        # no runs at all
        assert CR.build(os.path.join(tmp, "none"))["batches"] == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("test_ingest_cost_report OK")


if __name__ == "__main__":
    main()
