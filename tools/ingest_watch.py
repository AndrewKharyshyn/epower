#!/usr/bin/env python3
"""M575: live watcher for an ingestion run. One stdout line per event, so a Monitor (or a human) sees a failure the moment it happens:
  START <run>, STAGE <name> (each new <stage>.log), FAILED <stage> + the last log lines (failure.json), DONE (status.json final), EXIT (run_ingest process gone without a final status),
  STALL (no new file in the run directory for --stall minutes while the process is alive; e.g. a hung rollback or stage).
Usage: python tools/ingest_watch.py [--run RUNID] [--stall 10] [--poll 10]   (default: the newest run directory; waits up to 5 minutes for it to appear)"""
import argparse, json, os, subprocess, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
RUNS = os.path.join(ROOT, "runs")


def newest_run(after):
    ds = [d for d in os.listdir(RUNS) if not d.startswith(".") and os.path.isdir(os.path.join(RUNS, d)) and os.path.getmtime(os.path.join(RUNS, d)) >= after - 5]
    return max(ds) if ds else None


def ingest_alive():
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | Where-Object { $_.CommandLine -match 'run_ingest' } | Measure-Object).Count"],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return int(out or 0) > 0
    except Exception:
        return True


def say(*a):
    print(*a, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run"); ap.add_argument("--stall", type=float, default=10); ap.add_argument("--poll", type=float, default=10)
    a = ap.parse_args()
    t0 = time.time()
    run = a.run
    while not run:
        run = newest_run(t0)
        if not run:
            if time.time() - t0 > 300:
                say("NORUN no run directory appeared within 5 minutes"); return 2
            time.sleep(a.poll)
    d = os.path.join(RUNS, run)
    say("START", run)
    seen, last_new, stalled, idle_exit = set(), time.time(), False, 0
    while True:
        names = set(os.listdir(d)) if os.path.isdir(d) else set()
        for n in sorted(names - seen):
            if n.endswith(".log") and n not in ("preflight.log",):
                say("STAGE", n[:-4])
            seen.add(n); last_new = time.time(); stalled = False
        fp = os.path.join(d, "failure.json")
        if os.path.exists(fp):
            try:
                f = json.load(open(fp, encoding="utf-8"))
                say("FAILED", f.get("stage"), "rc=%s" % f.get("returncode"), "|", " / ".join(str(x) for x in f.get("last_lines", [])[-6:])[:900])
            except Exception as e:
                say("FAILED (failure.json unreadable: %r)" % e)
            say("NOTE the journal now rolls back; use python tools/run_ingest.py --recover only if the process does not finish within a few minutes")
            return 1
        sp = os.path.join(d, "status.json")
        if os.path.exists(sp):
            try:
                s = json.load(open(sp, encoding="utf-8"))
            except Exception:
                s = {}
            say("DONE" if str(s.get("status", s.get("result", ""))).lower() in ("ok", "green", "passed", "success", "committed", "done") else "ENDED", json.dumps(s)[:300])
            return 0
        alive = ingest_alive()
        idle_exit = 0 if alive else idle_exit + 1
        if idle_exit >= 2:
            say("EXIT the run_ingest process is gone with no final status/failure.json (killed or crashed); run: python tools/run_ingest.py --recover")
            return 1
        if alive and not stalled and time.time() - last_new > a.stall * 60:
            say("STALL no new file in %s for %.0f minutes (a long stage is normal for speedSplit/gtr_family/regen_v2 up to ~30 minutes; a hung rollback is not)" % (run, a.stall)); stalled = True
        time.sleep(a.poll)


if __name__ == "__main__":
    sys.exit(main())
