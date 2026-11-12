#!/usr/bin/env python3
"""P-05 (self-audit handoff, milestone M628): local mirror of the pull-request CI, so a push does not need CI to find what a laptop run would have found.

What it does (all from `.github/workflows/ci.yml`, never a second list):
  * parses the python unit-test list (the `ci_python_tests.txt` heredoc), the jsdom dashboard tests, the compile step and the import-integrity step with its typed master MD5;
  * copies the tracked files (working-tree content, so staged and unstaged edits are tested) to a TEMPORARY directory, links raw/, raw_only/, raw_cache/ and node_modules/ read-only-in-spirit
    (directory junctions; the tests never write into them), so tests that rewrite tracked files (cohort_arrays.json, ...) cannot clobber the checkout;
  * runs every command with PYTHONUTF8=1, PYTHONIOENCODING=utf-8, the eol shim on PYTHONPATH and XT_RAW_DIR=raw, a per-command timeout, and CONTINUES after a failure (CI stops a shard at its first failure:
    this reports ALL failures in one run);
  * applies a declared skip list (tools/ci_local_skip.json, key per platform, each entry with its reason): a skip is printed, never silent;
  * checks that the master MD5 typed in ci.yml equals the live drive_master.csv (release_check.py asserts the same);
  * writes runs/ci_local/<timestamp>.json (per command: status, seconds, last lines of output) and exits non-zero if anything failed.
It does NOT run the `release-check` job (python release_check.py, ~15 min): run that separately; `--release-check` appends it.
Usage: python tools/ci_local.py [--list] [--python-only | --js-only] [--only SUBSTR] [--timeout SEC] [--keep] [--release-check]"""
import argparse, datetime, hashlib, json, os, platform, re, shlex, shutil, subprocess, sys, tempfile, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CI = os.path.join(ROOT, ".github", "workflows", "ci.yml")
SKIP_FILE = os.path.join(ROOT, "tools", "ci_local_skip.json")
LINK_DIRS = ("raw", "raw_only", "raw_cache", "node_modules")


def parse_ci(text):
    """-> {'python': [cmd], 'js': [cmd], 'compile': cmd|None, 'import': cmd|None, 'anchorMd5': str|None}. The python list is the heredoc between `<<'LIST'` and `LIST`."""
    out = {"python": [], "js": [], "compile": None, "import": None, "anchorMd5": None}
    m = re.search(r"<<'LIST'\n(.*?)\n\s*LIST\n", text, re.S)
    if m:
        out["python"] = [ln.strip() for ln in m.group(1).split("\n") if ln.strip() and not ln.strip().startswith("#")]
    m = re.search(r"- name: Dashboard tests \(jsdom\)\n\s*run: \|\n((?:\s+node [^\n]+\n)+)", text)
    if m:
        out["js"] = [ln.strip() for ln in m.group(1).split("\n") if ln.strip()]
    m = re.search(r"run: (python -m compileall [^\n]+)", text)
    out["compile"] = m.group(1).strip() if m else None
    m = re.search(r"run: (python tools/verify_import\.py[^\n]*--expect-master-md5 ([0-9a-f]{32})[^\n]*)", text)
    if m:
        out["import"], out["anchorMd5"] = m.group(1).strip(), m.group(2)
    return out


def md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def tracked_files():
    r = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True)
    return [f for f in r.stdout.decode("utf-8").split("\0") if f]


def make_copy(dst):
    n = 0
    for f in tracked_files():
        if f.split("/")[0] in LINK_DIRS:
            continue
        s = os.path.join(ROOT, f)
        if not os.path.isfile(s):
            continue
        d = os.path.join(dst, f)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)
        n += 1
    for name in LINK_DIRS:
        src = os.path.join(ROOT, name)
        if not os.path.isdir(src):
            continue
        link = os.path.join(dst, name)
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", link, src], capture_output=True, check=True)
        else:
            os.symlink(src, link)
    return n


def load_skips():
    try:
        d = json.load(open(SKIP_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    key = "windows" if os.name == "nt" else platform.system().lower()
    return d.get(key, {})


def run_cmd(cmd, cwd, env, timeout):
    parts = shlex.split(cmd, posix=True)
    if parts and parts[0] == "python":
        parts[0] = sys.executable
    t0 = time.time()
    try:
        r = subprocess.run(parts, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        tail = (r.stdout + r.stderr).strip().split("\n")[-12:]
        return ("pass" if r.returncode == 0 else "fail"), round(time.time() - t0, 1), r.returncode, tail
    except subprocess.TimeoutExpired:
        return "fail", round(time.time() - t0, 1), None, ["TIMEOUT after %ss" % timeout]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--python-only", action="store_true")
    ap.add_argument("--js-only", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--release-check", action="store_true")
    a = ap.parse_args(argv)
    text = open(CI, encoding="utf-8").read()
    ci = parse_ci(text)
    cmds = []
    if ci["compile"]:
        cmds.append(("compile", ci["compile"]))
    if ci["import"]:
        cmds.append(("import", ci["import"]))
    if not a.js_only:
        cmds += [("python", c) for c in ci["python"]]
    if not a.python_only:
        cmds += [("js", c) for c in ci["js"]]
    if a.only:
        cmds = [(k, c) for k, c in cmds if a.only in c]
    if a.list:
        for k, c in cmds:
            print("%-8s %s" % (k, c))
        print("%d commands; anchor md5 in ci.yml %s" % (len(cmds), ci["anchorMd5"]))
        return 0
    live = md5(os.path.join(ROOT, "drive_master.csv"))
    anchor_ok = ci["anchorMd5"] == live
    print("anchor: ci.yml master MD5 %s %s live %s" % (ci["anchorMd5"], "==" if anchor_ok else "!=", live))
    tmp = tempfile.mkdtemp(prefix="xt_ci_local_")
    print("copying tracked files to", tmp)
    n = make_copy(tmp)
    print("copied %d files; linked %s" % (n, ", ".join(x for x in LINK_DIRS if os.path.isdir(os.path.join(ROOT, x)))))
    env = dict(os.environ)
    env.pop("XT_RAW_DIR", None)                      # as in ci.yml: XT_RAW_DIR=raw is set for the import-integrity step ONLY; the unit tests must not inherit it (test_run_fingerprint relies on it)
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    shim = os.path.join(tmp, "tools", "eol_shim")
    env["PYTHONPATH"] = shim + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    skips = load_skips()
    results, t_all = [], time.time()
    for k, c in cmds:
        if c in skips:
            print("SKIP  %-6s %s  (%s)" % (k, c, skips[c]))
            results.append({"kind": k, "cmd": c, "status": "skip", "reason": skips[c]})
            continue
        script = shlex.split(c)[1] if len(shlex.split(c)) > 1 else ""
        if script.endswith((".py", ".js")) and not os.path.isfile(os.path.join(tmp, script)):
            print("FAIL  %-6s %s  (file not in the tracked set: git add it)" % (k, c))
            results.append({"kind": k, "cmd": c, "status": "fail", "seconds": 0, "tail": ["not tracked by git (git add the file before the run)"]})
            continue
        cenv = dict(env, XT_RAW_DIR="raw") if k == "import" else env
        st, secs, rc, tail = run_cmd(c, tmp, cenv, a.timeout)
        print("%s  %-6s %s  (%ss)" % ("PASS" if st == "pass" else "FAIL", k, c, secs))
        if st != "pass":
            for ln in tail[-6:]:
                print("      | " + ln[:200])
        results.append({"kind": k, "cmd": c, "status": st, "seconds": secs, "returncode": rc, "tail": tail if st != "pass" else []})
    failed = [r for r in results if r["status"] == "fail"]
    print("\nci_local: %d commands, %d failed, %d skipped, %.0f s; anchor %s" % (len(results), len(failed), sum(1 for r in results if r["status"] == "skip"), time.time() - t_all, "ok" if anchor_ok else "MISMATCH"))
    for r in failed:
        print("  FAILED: " + r["cmd"])
    rc = 1 if (failed or not anchor_ok) else 0
    if a.release_check:
        print("\nrunning release_check.py (several minutes) ...")
        rr = subprocess.run([sys.executable, "release_check.py"], cwd=ROOT, env=env)
        rc = rc or rr.returncode
    outdir = os.path.join(ROOT, "runs", "ci_local")
    os.makedirs(outdir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    with open(os.path.join(outdir, stamp + ".json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"timestamp": stamp, "platform": platform.platform(), "python": sys.version.split()[0], "anchor": {"ci": ci["anchorMd5"], "live": live, "ok": anchor_ok}, "results": results}, f, indent=1)
    if not a.keep:
        if os.name == "nt":
            for name in LINK_DIRS:
                p = os.path.join(tmp, name)
                if os.path.isdir(p):
                    subprocess.run(["cmd", "/c", "rmdir", p], capture_output=True)       # remove the junction itself, never the target
        shutil.rmtree(tmp, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
