#!/usr/bin/env python3
"""M464 (spec analyses/M464_spec.md, component B): fast preflight of the late ingestion stages that failed in M463, run against the post-`ingest_core` state in a SANDBOX copy of the
working tree (the real tree is never written; the report states `wroteReal` after comparing the tree hash before and after).
Checks (minutes instead of the 40-50 min pipeline):
  m296_parity   m296_refresh_master_seasonal.py --dry-run (parity guard of the per-cohort call path against the fresh top-level blocks; stops before any write). When
                seasonal_drive_master.csv does not yet cover the master (state right after ingest_core), compute_seasonal.py runs first, inside the sandbox.
  regen_v2      tools/regen_v2_stage.py --dry-run (reconciliation G3, study-lock checks, regen_std flags, regen_display.build(arrays=...) gates, stray-key check).
The sandbox stages raw_only/ itself (tools/stage_raw.py) and shares only the content-keyed regen_cache/ with the real tree (the single allowed write, idempotent: a cache entry is
keyed by the raw-file SHA-256 and the extractor/policy hashes).
Precondition: the real tree holds the post-ingest_core master (a journaled run rolls back to the pre-ingestion master on failure); otherwise pass --with-ingest-core.
Usage: python tools/ingest_preflight.py [--with-ingest-core] [--check m296_parity regen_v2 ...] [--keep-sandbox] [--json PATH]      Exit 0 only if every selected check is ok."""
import argparse, json, os, shutil, subprocess, sys, tempfile, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_journal as RJ

SHARED = ("regen_cache",)                      # git-ignored content-keyed caches linked (not copied) into the sandbox
SKIP_TOP = RJ.EXCLUDE_TOP | set(SHARED)
CHECKS = ("m296_parity", "regen_v2")


def tree_hash(root):
    import hashlib
    h = hashlib.sha256()
    for rel, (_, sha) in sorted(RJ.tree(root).items()):
        h.update(("%s:%s\n" % (rel, sha)).encode())
    return h.hexdigest()


def _link_dir(src, dst):
    """symlink, else a Windows junction, else False (the caller reports the cache as unshared)."""
    try:
        os.symlink(src, dst, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        r = subprocess.run(["cmd", "/c", "mklink", "/J", dst, src], capture_output=True)
        return r.returncode == 0
    return False


def make_sandbox(root, parent=None):
    sb = tempfile.mkdtemp(prefix="xt_preflight_", dir=parent)
    for d, dirs, files in os.walk(root):
        rel_d = os.path.relpath(d, root)
        if rel_d == ".":
            dirs[:] = [x for x in dirs if x not in SKIP_TOP and x not in RJ.EXCLUDE_ANY]
        else:
            dirs[:] = [x for x in dirs if x not in RJ.EXCLUDE_ANY]
        for f in files:
            if f.endswith(RJ.EXCLUDE_SUFFIX):
                continue
            p = os.path.join(d, f)
            if os.path.isfile(p) and not os.path.islink(p):
                dst = os.path.join(sb, os.path.relpath(p, root))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(p, dst)
    linked = []
    for n in SHARED:
        s = os.path.join(root, n)
        os.makedirs(s, exist_ok=True) if n == "regen_cache" else None
        if os.path.isdir(s) and _link_dir(s, os.path.join(sb, n)):
            linked.append(n)
    return sb, linked


def remove_sandbox(sb):
    for n in SHARED:                                           # unlink links first: rmtree must never follow them into the real cache
        p = os.path.join(sb, n)
        if os.path.islink(p) or (os.name == "nt" and os.path.isdir(p) and os.path.exists(p) and _is_junction(p)):
            try:
                os.rmdir(p)
            except OSError:
                try:
                    os.unlink(p)
                except OSError:
                    pass
    shutil.rmtree(sb, ignore_errors=True)


def _is_junction(p):
    try:
        import stat
        return bool(os.lstat(p).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (AttributeError, OSError):
        return False


def seasonal_covers_master(sb):
    import csv
    try:
        with open(os.path.join(sb, "drive_master.csv"), newline="", encoding="utf-8") as f:
            m = {r["file"] for r in csv.DictReader(f)}
        with open(os.path.join(sb, "seasonal_drive_master.csv"), newline="", encoding="utf-8") as f:
            s = {r["file"] for r in csv.DictReader(f)}
    except (OSError, KeyError):
        return False
    return m <= s


def sh(sb, cmd, env, timeout):
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable] + cmd, cwd=sb, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        rc, out = r.returncode, (r.stdout + r.stderr)
    except subprocess.TimeoutExpired:
        rc, out = 124, "timeout after %d s" % timeout
    return rc, out, round(time.time() - t0, 1)


def run(root, checks, keep=False, timeout=3600, with_ingest_core=False):
    before = tree_hash(root)
    sb, linked = make_sandbox(root)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    shim = os.path.join(sb, "tools", "eol_shim")
    env["PYTHONPATH"] = shim + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["XT_RAW_DIR"] = os.path.join(root, "raw")
    env.pop("XT_RAW_DIR_STAGED", None)
    rep = {"sandbox": sb if keep else "(removed)", "sharedCaches": linked, "checks": []}
    try:
        if with_ingest_core:                                   # state right after ingest_core: the real tree still holds the pre-ingestion master after a journaled rollback
            rc, out, sec = sh(sb, ["tools/ingest_core.py"], env, timeout)
            rep["checks"].append({"id": "ingest_core(sandbox)", "status": "ok" if rc == 0 else "prereq_failed", "seconds": sec, "detail": out[-400:] if rc else ""})
            if rc:
                return dict(rep, ok=False, wroteReal=tree_hash(root) != before) if remove_sandbox(sb) is None else rep
        rc, out, sec = sh(sb, ["tools/stage_raw.py", "--raw-dir", env["XT_RAW_DIR"]], env, timeout)
        rep["checks"].append({"id": "stage_raw(sandbox)", "status": "ok" if rc == 0 else "prereq_failed", "seconds": sec, "detail": out[-400:] if rc else ""})
        ok_prereq = rc == 0
        for cid in checks:
            if not ok_prereq:
                rep["checks"].append({"id": cid, "status": "skipped", "detail": "stage_raw failed in the sandbox"}); continue
            if cid == "m296_parity":
                if not seasonal_covers_master(sb):
                    rc, out, sec = sh(sb, ["compute_seasonal.py"], env, timeout)
                    rep["checks"].append({"id": "compute_seasonal(sandbox)", "status": "ok" if rc == 0 else "prereq_failed", "seconds": sec, "detail": out[-400:] if rc else ""})
                    if rc:
                        rep["checks"].append({"id": cid, "status": "skipped", "detail": "seasonal prerequisite failed"}); continue
                rc, out, sec = sh(sb, ["m296_refresh_master_seasonal.py", "--dry-run"], env, timeout)
            elif cid == "regen_v2":
                rc, out, sec = sh(sb, ["tools/regen_v2_stage.py", "--dry-run"], env, timeout)
            else:
                raise SystemExit("unknown check %r; valid: %s" % (cid, CHECKS))
            rep["checks"].append({"id": cid, "status": "ok" if rc == 0 else "failed", "seconds": sec, "detail": out.strip()[-600:]})
    finally:
        if not keep:
            remove_sandbox(sb)
    rep["wroteReal"] = tree_hash(root) != before
    rep["ok"] = all(c["status"] == "ok" for c in rep["checks"]) and not rep["wroteReal"]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", nargs="*", default=list(CHECKS))
    ap.add_argument("--with-ingest-core", action="store_true", help="run tools/ingest_core.py in the sandbox first (needed when the real tree is still at the pre-ingestion master; minutes)")
    ap.add_argument("--keep-sandbox", action="store_true")
    ap.add_argument("--json")
    ap.add_argument("--timeout", type=int, default=3600)
    a = ap.parse_args(argv)
    rep = run(ROOT, a.check, a.keep_sandbox, a.timeout, a.with_ingest_core)
    if a.json:
        with open(a.json, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rep, f, indent=1)
    print(json.dumps(rep, indent=1))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
