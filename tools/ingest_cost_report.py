#!/usr/bin/env python3
"""M610a (spec analyses/M610_spec.md Rev 1, A3 and R2): how much of an ingestion's wall-clock was repeated work, and why each run stopped. Read-only: reads runs/*/status.json and
failure.json, writes only the report (default analyses/ingest_cost_report.json).

Batch = consecutive runs up to and including the next run with result `ok` (a trailing run of failed runs is the OPEN batch). Per batch:
  executedMin   sum of the seconds of every stage execution (status ok / gate_failed / not_implemented; restored_from_checkpoint and skipped_unchanged cost no execution)
  uniqueMin     for each stage id executed in the batch, one execution: the last successful one, else the longest
  repeatedMin   executedMin - uniqueMin;   repeatedShare = repeatedMin / uniqueMin
Per stop (a run whose result is not ok): stage, return code, class and cause.
  class escalation = the stage stopped on a ruling-bound gate (return code 3 on a stage that is implemented, or the stop text names an acknowledgement option / the Director)
        environment = the log tail shows an environment error (missing file or module, permission, encoding, memory)
        hard        = everything else (an integrity or consistency gate, a failed assertion)
  cause = last non-empty line of the failure log tail (first 160 characters), so late hard stops can be grouped by what they actually said.
Resume misses: for every run after the first of a batch, `checkpoint.resumed` False with the recorded reason (and the `missReason` detail written by M610a: which data file, raw listing or XT_* variable differed).
No number in the report is typed: every figure comes from the run records.
Usage: python tools/ingest_cost_report.py [--runs-dir runs] [--out analyses/ingest_cost_report.json] [--last N]"""
import argparse, collections, glob, json, os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
EXECUTED = ("ok", "gate_failed", "not_implemented")
ENV_MARKERS = ("FileNotFoundError", "ModuleNotFoundError", "No module named", "PermissionError", "UnicodeEncodeError", "UnicodeDecodeError", "MemoryError", "OSError", "ENOENT", "Cannot find module")
LATE = ("release_check", "leaf_guard", "build_html")
ESC_MARKERS = ("--ack", "ack-", "Director", "ESCALATE", "STOP (Director)", "needs --ack", "XT_ACK")


def jload(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return None


def classify(rec, failure):
    tail = "\n".join((failure or {}).get("last_lines") or [])
    if rec.get("status") == "not_implemented":
        return "hard"
    if any(m in tail for m in ENV_MARKERS) and "Gate(" not in tail:
        return "environment"
    if rec.get("rc") == 3 or any(m in tail for m in ESC_MARKERS):
        return "escalation"
    return "hard"


def cause(failure):
    lines = [l.strip() for l in ((failure or {}).get("last_lines") or []) if l.strip()]
    return (lines[-1] if lines else "")[:160]


def build(runs_dir, last=None):
    runs = []
    for p in sorted(glob.glob(os.path.join(runs_dir, "20*", "status.json"))):
        s = jload(p)
        if isinstance(s, dict) and isinstance(s.get("stages"), list):
            runs.append((os.path.basename(os.path.dirname(p)), s, jload(os.path.join(os.path.dirname(p), "failure.json"))))
    batches, cur = [], []
    for r in runs:
        cur.append(r)
        if r[1].get("result") == "ok":
            batches.append(cur)
            cur = []
    if cur:
        batches.append(cur)
    out = {"runsDir": runs_dir, "batches": [], "totals": {}}
    cls, bystage = collections.Counter(), collections.Counter()
    late = collections.defaultdict(collections.Counter)
    for b in (batches[-last:] if last else batches):
        ex, per = 0.0, {}
        stops, misses = [], []
        for i, (rid, s, fl) in enumerate(b):
            for st in s["stages"]:
                if st.get("status") in EXECUTED:
                    sec = float(st.get("seconds") or 0)
                    ex += sec
                    q = per.setdefault(st["id"], {"ok": None, "max": 0.0})
                    q["max"] = max(q["max"], sec)
                    if st["status"] == "ok":
                        q["ok"] = sec
            if s.get("result") != "ok":
                bad = next((x for x in s["stages"] if x.get("status") not in ("ok", "restored_from_checkpoint", "skipped_unchanged")), None)
                if bad:
                    c = classify(bad, fl)
                    stops.append({"run": rid, "stage": bad["id"], "rc": bad.get("rc"), "class": c, "cause": cause(fl)})
                    cls[c] += 1
                    bystage[bad["id"]] += 1
                    if bad["id"] in LATE and c == "hard":
                        late[bad["id"]][cause(fl)] += 1
            ck = s.get("checkpoint") or {}
            if i > 0:
                misses.append({"run": rid, "resumed": bool(ck.get("resumed")), "restoredStages": ck.get("restoredStages", 0), "reason": ck.get("reason"), "missReason": ck.get("missReason")})
        uniq = sum((q["ok"] if q["ok"] is not None else q["max"]) for q in per.values())
        out["batches"].append({"firstRun": b[0][0], "lastRun": b[-1][0], "nRuns": len(b), "result": b[-1][1].get("result"), "open": b[-1][1].get("result") != "ok",
                               "executedMin": round(ex / 60, 1), "uniqueMin": round(uniq / 60, 1), "repeatedMin": round((ex - uniq) / 60, 1),
                               "repeatedShare": round((ex - uniq) / uniq, 3) if uniq else None, "stops": stops, "resumeAttempts": misses})
    out["totals"] = {"stopsByClass": dict(cls), "stopsByStage": dict(bystage.most_common()), "lateHardStopsByCause": {k: dict(v.most_common()) for k, v in late.items()},
                     "scopeBatches": len(out["batches"]), "runsAllTime": len(runs), "runsNotOkAllTime": sum(1 for r in runs if r[1].get("result") != "ok")}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", default=os.path.join(ROOT, "runs"))
    ap.add_argument("--out", default=os.path.join(ROOT, "analyses", "ingest_cost_report.json"))
    ap.add_argument("--last", type=int, help="only the last N batches")
    a = ap.parse_args()
    rep = build(a.runs_dir, a.last)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(rep, open(a.out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps(rep["totals"], ensure_ascii=False)[:1500])
    for b in rep["batches"][-3:]:
        print("batch %s..%s runs=%d %s executed=%s unique=%s repeated=%s min (share %s)" % (b["firstRun"], b["lastRun"], b["nRuns"], b["result"], b["executedMin"], b["uniqueMin"], b["repeatedMin"], b["repeatedShare"]))


if __name__ == "__main__":
    main()
