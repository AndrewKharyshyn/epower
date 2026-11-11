#!/usr/bin/env python3
"""M613 / M610b pilot comparator (Director ruling 2026-11-11, required change 6): compare a collect pass with the real run that follows it.
Both runs are made with `--record-normalised` on the same commit, with only the acknowledgement inputs differing. For every stage BEFORE the first stop record that WITHHELD an effect (a stage whose
splice the pass skipped; its dependants downstream are provisional) the normalised output hashes (tools/state_hash.py: only the pre-registered run-time stamp leaves dropped) of every declared output must
be equal between the pass and the real run, which includes drive_master.csv (the ingest_core stage). A difference in a later stage is reported as `provisionalDifferences` and never as a failure, because
a withheld record explains it only downstream; a difference before it is a problem (the pass interfered or a run-time leaf is missing from the pre-registered list).
Zero stop records is a non-interference result only (all stages are compared). Usage: python tools/collect_pass_compare.py PASS_RUN_DIR REAL_RUN_DIR [--json OUT]
       python tools/collect_pass_compare.py --urban-balance PASS_RUN_DIR PREV_SUMMARY_ARRAYS.json NEW_SUMMARY_ARRAYS.json"""
import json, os, sys


def _load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def compare(pass_dir, real_dir):
    ps, rs = _load(os.path.join(pass_dir, "status.json")), _load(os.path.join(real_dir, "status.json"))
    sp = os.path.join(pass_dir, "stops.json")
    recs = _load(sp)["records"] if os.path.isfile(sp) else []
    first_withheld = next((r["stage"] for r in recs if r.get("withheld")), None)
    rst = {s["id"]: s for s in rs["stages"]}
    problems, provisional, compared = [], [], []
    seen_withheld = False
    for st in ps["stages"]:
        sid = st["id"]
        if sid == first_withheld:
            seen_withheld = True
        a, b = st.get("outputsNormalised"), (rst.get(sid) or {}).get("outputsNormalised")
        if sid not in rst:
            (provisional if seen_withheld else problems).append("%s: stage missing in the real run" % sid)
            continue
        if a is None or b is None:
            problems.append("%s: no outputsNormalised (run both with --record-normalised)" % sid)
            continue
        diff = sorted(o for o in set(a) | set(b) if a.get(o) != b.get(o))
        if seen_withheld:
            if diff:
                provisional.append("%s: %s" % (sid, ", ".join(diff)))
            continue
        compared.append(sid)
        if diff:
            problems.append("%s: outputs differ: %s" % (sid, ", ".join(diff)))
    return {"ok": not problems, "firstWithheldStage": first_withheld, "nStopRecords": len(recs), "nCompared": len(compared), "problems": problems[:50], "provisionalDifferences": provisional[:100],
            "note": "zero stop records: non-interference only" if not recs else "stages after the first withheld stage are provisional"}


def urban_balance_check(pass_dir, prev_arrays, new_arrays):
    """Director required change 7: the `--ack-verdict-change` flag of urban_balance is not fact-bound, so the pass record's from/to verdicts are compared by script with the payload change the real run
    produced (`prev_arrays` = the pre-batch summary_arrays.json, `new_arrays` = the real run's). Returns (ok, message); no record = nothing to check."""
    sp = os.path.join(pass_dir, "stops.json")
    recs = [r for r in (_load(sp)["records"] if os.path.isfile(sp) else []) if r["stage"] == "urban_balance"]
    if not recs:
        return True, "no urban_balance record in the pass"
    f = recs[0]["facts"]
    old = (prev_arrays.get("urbanContrastBalance") or {}).get("overallVerdict")
    new = (new_arrays.get("urbanContrastBalance") or {}).get("overallVerdict")
    ok = f.get("from") == old and f.get("to") == new
    return ok, "record from/to %r -> %r; payload before/after %r -> %r" % (f.get("from"), f.get("to"), old, new)


def main(argv):
    if len(argv) >= 4 and argv[0] == "--urban-balance":
        ok, msg = urban_balance_check(argv[1], _load(argv[2]), _load(argv[3]))
        print(json.dumps({"ok": ok, "message": msg}))
        return 0 if ok else 1
    if len(argv) < 2:
        print(__doc__)
        return 2
    res = compare(argv[0], argv[1])
    if "--json" in argv:
        with open(argv[argv.index("--json") + 1], "w", encoding="utf-8", newline="\n") as f:
            json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
