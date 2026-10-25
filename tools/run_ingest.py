#!/usr/bin/env python3
"""Stage runner. Zero LLM tokens. Runs tools/ingest_stages.json in order, stops on the first failure, writes:
  runs/<UTC-ts>/status.json  (compact, <2 KB: stage results + sha256 of declared outputs)
  runs/<UTC-ts>/<stage>.log  (full output)
  runs/<UTC-ts>/failure.json (stage, returncode, last 50 log lines) on failure
Usage: python tools/run_ingest.py [--dry-run] [--from ID] [--only ID] [--skip ID ...]
Exit codes: 0 ok, 1 gate failed, 3 stage not implemented, 4 rollback/recovery failed, 5 an unfinished release journal blocks the start (run --recover). No automatic retries, no parameter changes.
M416 (audit F20): the run is a journaled release (tools/release_journal.py): the working tree outside raw/ is snapshotted before the first stage; a failed stage, an exception or SIGINT/SIGTERM rolls every file back
and verifies the tree hash, a green run commits and records its write set. --keep-on-failure leaves the state for inspection (journal stays open until --recover); --no-journal disables it (development only);
--recover rolls an interrupted or kept release back."""
import argparse, datetime as dt, hashlib, json, os, signal, subprocess, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def sha(path):
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()[:16]


def select_stages(stages, only=None, frm=None, skip=()):
    """F10 (audit 2026-10-05): every requested stage ID must exist and the selection must not be empty (an unknown --only used to run
    zero stages and exit 0)."""
    ids = [s["id"] for s in stages]
    bad = [x for x in ([only] if only else []) + ([frm] if frm else []) + list(skip or []) if x not in ids]
    if bad:
        raise ValueError("unknown stage ID(s) %s; valid IDs: %s" % (bad, ids))
    if only:
        stages = [s for s in stages if s["id"] == only]
    elif frm:
        stages = stages[ids.index(frm):]
    stages = [s for s in stages if s["id"] not in (skip or ())]
    if not stages:
        raise ValueError("the stage selection is empty (nothing would run)")
    return stages


def resolve_cmd(cmd):
    """M397: stage commands start with 'python3'. On Windows that name resolves to the Microsoft Store app-execution alias (WindowsApps\\python3.exe), which intermittently fails to launch
    (WinError 1920 in the 2026-10-11 replay: three stages started, the fourth did not) and then also runs a different interpreter than the orchestrator. Launch the stage with the
    interpreter that is running this script instead. Other commands (node, ...) are unchanged."""
    cmd = list(cmd)
    if cmd and cmd[0] in ("python3", "python"):
        cmd[0] = sys.executable
    return cmd


def launch(cmd, **kw):
    """subprocess.run, but a launch failure (OSError: the stage never started) is returned as a failed stage with the error in its log instead of crashing the whole run before status.json / failure.json are written."""
    try:
        return subprocess.run(resolve_cmd(cmd), **kw), None
    except OSError as ex:
        class _Failed:                                           # same interface as CompletedProcess for the fields used below
            returncode = 127
        return _Failed(), repr(ex)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from", dest="frm")
    ap.add_argument("--only")
    ap.add_argument("--skip", nargs="*", default=[])
    ap.add_argument("--skip-unchanged", action="store_true",
                    help="M385: skip every analysis stage when the run fingerprint (sources, data, outputs, raw listing, environment) equals the last fully green run; "
                         "preflight/build_html/jsdom/release_check/state always run (tools/run_fingerprint.py)")
    ap.add_argument("--no-journal", action="store_true", help="M416: no snapshot/rollback (development only)")
    ap.add_argument("--keep-on-failure", action="store_true", help="M416: on failure leave the mixed state in place for inspection (the journal stays open; the next run needs --recover)")
    ap.add_argument("--resume", action="store_true", help="M464: restore the longest valid prefix of the stage checkpoints of a previous failed full run (same data state, unchanged stage code) and execute only the first changed/failed stage and later ones; the journal still snapshots first and rolls back on any failure")
    ap.add_argument("--no-checkpoints", action="store_true", help="M464: do not save stage checkpoints (full journaled runs save them by default under runs/.checkpoints/)")
    ap.add_argument("--recover", action="store_true", help="M416: roll back an interrupted or kept release from its journal, then exit")
    a = ap.parse_args()
    import release_journal as RJ
    if a.recover:
        try:
            rep_ = RJ.Journal.recover(ROOT)
        except RJ.ReleaseError as ex:
            print(json.dumps({"error": str(ex)}), file=sys.stderr)
            return 4
        print(json.dumps({"recovered": rep_}))
        return 0 if all(r["state"] == "rolled_back" for r in rep_) else 4
    cfg = json.load(open(os.path.join(ROOT, "tools", "ingest_stages.json")))
    stages = cfg["stages"]
    try:
        stages = select_stages(stages, a.only, a.frm, a.skip)
    except ValueError as e:
        print("run_ingest: " + str(e), file=sys.stderr)
        return 2

    import run_fingerprint as RF
    full_run = not (a.only or a.frm or a.skip)
    skip_ids, skip_reason = set(), "skip-unchanged not requested"
    if a.skip_unchanged and full_run:
        skip_ids, skip_reason, _ = RF.plan(ROOT, cfg["stages"], True)
    if a.skip_unchanged:
        print("run_ingest: skip-unchanged: %s%s" % (skip_reason, " -> skipping %d stages" % len(skip_ids) if skip_ids else ""), file=sys.stderr)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_started_at = dt.datetime.now(dt.timezone.utc).isoformat()     # M513: ISO start of this run (XT_RUN_STARTED_AT for the stamp pass)
    rd = os.path.join(ROOT, "runs", ts)
    if a.dry_run:
        print(json.dumps([{"id": s["id"], "cmd": s["cmd"], "verified": s.get("verified"), "implemented": s.get("implemented", True)} for s in stages], indent=1))
        return 0
    os.makedirs(rd, exist_ok=True)
    journal = None
    if not a.no_journal:
        journal = RJ.Journal(ROOT, rd)
        try:
            journal.begin({"stages": [s["id"] for s in stages], "argv": sys.argv[1:]})
        except RJ.ReleaseError as ex:
            print(json.dumps({"error": str(ex)}), file=sys.stderr)
            return 5
        def _on_signal(signum, frame):                    # SIGTERM / SIGBREAK: unwind like Ctrl-C so the rollback below runs
            raise KeyboardInterrupt("signal %s" % signum)
        for _sig in ("SIGTERM", "SIGBREAK"):
            if hasattr(signal, _sig):
                signal.signal(getattr(signal, _sig), _on_signal)
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")          # repo files are UTF-8; Windows default (cp1251/cp1252) breaks open() without encoding=
    env.setdefault("PYTHONIOENCODING", "utf-8")
    shim = os.path.join(ROOT, "tools", "eol_shim")      # text-mode writes default to LF (repo canonical bytes; see tools/eol_shim/sitecustomize.py)
    env["PYTHONPATH"] = shim + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    if os.path.isdir(os.path.join(ROOT, "raw")):
        # M369: always raw/ (was setdefault: an inherited XT_RAW_DIR=raw_only, the staged view without the comparison files, failed preflight).
        # Stages that need the staged view declare it in tools/ingest_stages.json "env".
        want = os.path.join(ROOT, "raw")
        if env.get("XT_RAW_DIR") and os.path.abspath(env["XT_RAW_DIR"]) != os.path.abspath(want):
            print(f"NOTE: XT_RAW_DIR={env['XT_RAW_DIR']} overridden with {want} for run_ingest (per-stage env still applies)", file=sys.stderr)
        env["XT_RAW_DIR"] = want
    status = {"run": ts, "stages": [], "result": "ok"}
    rc_final = 0
    cp, k_restored = None, 0
    try:
        if journal is not None and full_run and not skip_ids and not a.skip_unchanged and not a.no_checkpoints:
            import ingest_checkpoint as ICP
            cp = ICP.Checkpoints(ROOT, cfg["stages"])
        elif a.resume:
            print("run_ingest: --resume needs a full journaled run with checkpoints (no --only/--from/--skip/--no-journal/--skip-unchanged/--no-checkpoints): running normally", file=sys.stderr)
        if cp is not None:
            cp.begin()
            if a.resume:
                try:
                    k_restored, cinfo = cp.try_restore()
                except Exception as ex:                       # CheckpointError, or a corrupt entry / failed copy: discard the chain, roll back
                    cp.discard()                                  # a chain that cannot be restored must not fail every later --resume
                    k_restored, cinfo = -1, {"reason": "restore failed: %s" % ex}
                status["checkpoint"] = dict(cinfo, resumed=k_restored > 0)
                print("run_ingest: --resume: %s" % json.dumps(status["checkpoint"]), file=sys.stderr)
                if k_restored < 0:
                    raise RuntimeError("checkpoint restore failed: " + cinfo["reason"])
        for idx, s in enumerate(stages):
            if idx < k_restored and not s.get("rerun_on_resume"):     # rerun_on_resume: stage writes state outside the checkpointed data state (raw_only/); idempotent, re-executed after a restore
                status["stages"].append({"id": s["id"], "rc": 0, "seconds": 0.0, "status": "restored_from_checkpoint",
                                         "outputs": {o: sha(os.path.join(ROOT, o)) for o in s.get("outputs", [])}})
                continue
            if s["id"] in skip_ids:
                status["stages"].append({"id": s["id"], "rc": None, "seconds": 0.0, "status": "skipped_unchanged", "reason": skip_reason})
                continue
            t0 = time.time()
            log = os.path.join(rd, s["id"] + ".log")
            with open(log, "w") as lf:
                senv = dict(env)
                senv["XT_RUN_STAGES_OK"] = ",".join(r_["id"] for r_ in status["stages"] if r_.get("status") in ("ok", "restored_from_checkpoint"))     # M513: the run record the stamp pass reads
                senv["XT_RUN_STARTED_AT"] = run_started_at
                for k, v in (s.get("env") or {}).items():          # per-stage env; "$ROOT" expands to the repo root
                    senv[k] = v.replace("$ROOT", ROOT)
                r, launch_error = launch(s["cmd"], cwd=ROOT, env=senv, stdout=lf, stderr=subprocess.STDOUT)
                if launch_error:
                    lf.write("run_ingest: the stage could not be launched: %s (command %r)\n" % (launch_error, s["cmd"]))
            rec = {"id": s["id"], "rc": r.returncode, "seconds": round(time.time() - t0, 1),
                   "outputs": {o: sha(os.path.join(ROOT, o)) for o in s.get("outputs", [])}}
            if r.returncode == 3 and s.get("implemented") is False:
                rec["status"] = "not_implemented"
            else:
                rec["status"] = "ok" if r.returncode == 0 else "gate_failed"
            status["stages"].append(rec)
            if rec["status"] == "ok" and cp is not None and idx >= k_restored:
                cp.save(s)
            if rec["status"] != "ok":
                status["result"] = rec["status"]
                tail = open(log, errors="replace").read().splitlines()[-50:]
                json.dump({"stage": s["id"], "title": s["title"], "returncode": r.returncode, "status": rec["status"],
                           "log": os.path.relpath(log, ROOT), "last_lines": tail}, open(os.path.join(rd, "failure.json"), "w"), indent=1)
                rc_final = 3 if rec["status"] == "not_implemented" else 1
                break
    except BaseException as ex:                                  # M416: exception or signal mid-run: roll back, then re-raise
        if journal is not None:
            rb = journal.rollback("exception: %r" % (ex,)) if not a.keep_on_failure else journal.keep_for_debug("exception: %r" % (ex,))
            print(json.dumps({"journal": rb["state"], "run": ts}), file=sys.stderr)
        raise
    if cp is not None:
        if cp.notes:
            status.setdefault("checkpoint", {})["notes"] = cp.notes[:5]
        if status["result"] == "ok":
            cp.discard()                                          # a green full run needs no chain
    if journal is not None:
        declared = {o for st in cfg["stages"] for o in (st.get("outputs") or [])}
        if status["result"] == "ok":
            jd = journal.commit(declared)
            status["journal"] = {"state": jd["state"], "nChanged": len(jd["writeSet"]["changed"]), "nCreated": len(jd["writeSet"]["created"]), "nDeleted": len(jd["writeSet"]["deleted"]),
                                 "undeclaredWrites": jd["undeclaredWrites"][:50], "rawAdded": jd["rawAdded"][:20]}
        elif a.keep_on_failure:
            jd = journal.keep_for_debug("stage failure: %s" % status["result"])
            status["journal"] = {"state": jd["state"], "note": "mixed state left in place; run tools/run_ingest.py --recover to roll back"}
        else:
            jd = journal.rollback("stage failure: %s" % status["result"])
            status["journal"] = {"state": jd["state"], "restored": {k: len(v) for k, v in jd["restored"].items()}, "mismatches": jd["rollbackMismatches"][:10], "rawAdded": jd["rawAdded"][:20]}
            if jd["state"] != "rolled_back":
                rc_final = 4
    json.dump(status, open(os.path.join(rd, "status.json"), "w"), indent=1)
    if full_run and not skip_ids and status["result"] == "ok":
        RF.save_ledger(ROOT, RF.components(ROOT, cfg["stages"]), ts)      # M385: state left by a fully green, fully executed run
    print(json.dumps({"run": ts, "result": status["result"], "status_path": os.path.relpath(os.path.join(rd, "status.json"), ROOT)}))
    return rc_final


if __name__ == "__main__":
    sys.exit(main())
