#!/usr/bin/env python3
"""Stage runner. Zero LLM tokens. Runs tools/ingest_stages.json in order, stops on the first failure, writes:
  runs/<UTC-ts>/status.json  (compact, <2 KB: stage results + sha256 of declared outputs)
  runs/<UTC-ts>/<stage>.log  (full output)
  runs/<UTC-ts>/failure.json (stage, returncode, last 50 log lines) on failure
Usage: python tools/run_ingest.py [--dry-run] [--from ID] [--only ID] [--skip ID ...]
Exit codes: 0 ok, 1 gate failed, 3 stage not implemented. No automatic retries, no parameter changes."""
import argparse, datetime as dt, hashlib, json, os, subprocess, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from", dest="frm")
    ap.add_argument("--only")
    ap.add_argument("--skip", nargs="*", default=[])
    a = ap.parse_args()
    cfg = json.load(open(os.path.join(ROOT, "tools", "ingest_stages.json")))
    stages = cfg["stages"]
    try:
        stages = select_stages(stages, a.only, a.frm, a.skip)
    except ValueError as e:
        print("run_ingest: " + str(e), file=sys.stderr)
        return 2

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rd = os.path.join(ROOT, "runs", ts)
    if a.dry_run:
        print(json.dumps([{"id": s["id"], "cmd": s["cmd"], "verified": s.get("verified"), "implemented": s.get("implemented", True)} for s in stages], indent=1))
        return 0
    os.makedirs(rd, exist_ok=True)
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
    for s in stages:
        t0 = time.time()
        log = os.path.join(rd, s["id"] + ".log")
        with open(log, "w") as lf:
            senv = dict(env)
            for k, v in (s.get("env") or {}).items():          # per-stage env; "$ROOT" expands to the repo root
                senv[k] = v.replace("$ROOT", ROOT)
            r = subprocess.run(s["cmd"], cwd=ROOT, env=senv, stdout=lf, stderr=subprocess.STDOUT)
        rec = {"id": s["id"], "rc": r.returncode, "seconds": round(time.time() - t0, 1),
               "outputs": {o: sha(os.path.join(ROOT, o)) for o in s.get("outputs", [])}}
        if r.returncode == 3 and s.get("implemented") is False:
            rec["status"] = "not_implemented"
        else:
            rec["status"] = "ok" if r.returncode == 0 else "gate_failed"
        status["stages"].append(rec)
        if rec["status"] != "ok":
            status["result"] = rec["status"]
            tail = open(log, errors="replace").read().splitlines()[-50:]
            json.dump({"stage": s["id"], "title": s["title"], "returncode": r.returncode, "status": rec["status"],
                       "log": os.path.relpath(log, ROOT), "last_lines": tail}, open(os.path.join(rd, "failure.json"), "w"), indent=1)
            rc_final = 3 if rec["status"] == "not_implemented" else 1
            break
    json.dump(status, open(os.path.join(rd, "status.json"), "w"), indent=1)
    print(json.dumps({"run": ts, "result": status["result"], "status_path": os.path.relpath(os.path.join(rd, "status.json"), ROOT)}))
    return rc_final


if __name__ == "__main__":
    sys.exit(main())
