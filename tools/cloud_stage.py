#!/usr/bin/env python3
"""M746 (spec analyses/M746_spec.md Rev 3 to Rev 5): optional, non-blocking ingestion stage `cloud_auxiliary` for the MyNISSAN cloud auxiliary tools.

Runs, in order, import (only when XT_CLOUD_EXPORTS holds ZIPs), coverage, clock_offset, tyre, thermal, grade, grade_shares, unlogged. Every tool runs in a subprocess (own timeout, process tree killed on timeout) with an
out-dir in a scratch directory; only after exit 0 are its files promoted by rename into analyses/cloud_retests/<tool>_<master md5 first 8>/. The registered results in analyses/ are NEVER written. Tools whose Rev 3
addendum is not registered yet (thermal, grade, unlogged: pinned to the registered master) are recorded as skipped_pinned_master. Status file: analyses/cloud_stage_status.json.
Protected files are hashed before and after each tool; a change is an integrity breach (remaining tools abort, exit 2). Tool failures, timeouts, missing inputs: exit 0. An exception in the wrapper is
recorded as wrapper_error, exit 0. Promotion of any result into the dashboard payload is NOT part of this stage (spec 10.2).

Usage: python tools/cloud_stage.py [--timeout SEC] [--only ID[,ID]] [--out-root DIR] [--status FILE]"""
import argparse, glob, hashlib, json, os, shutil, subprocess, sys, tempfile, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
P = lambda *a: os.path.join(ROOT, *a)
PY = sys.executable
STATUSES = ("ok", "skipped_no_store", "skipped_no_new_input", "skipped_up_to_date", "skipped_pinned_master", "skipped_no_dem", "skipped_upstream_failed", "skipped_opt_out", "skipped_locked", "failed", "timeout", "integrity_breach")
PROTECTED = ["drive_master.csv", "summary_arrays.json", "summary_config.json", "cohort_arrays.json", "raw_manifest.json", "release_identity.json", "analyses/M717_winter_predictions.json",
             "analyses/M726_extractor_registry.json", "analyses/M737_g0.json", "analyses/M734_thermal_forcing.json", "analyses/M734_park_gaps.csv", "analyses/M734_ambient_drives.csv",
             "analyses/M739_unlogged_exposure.json", "analyses/M767_grade_class_shares.json", "analyses/M762_dem_crosscheck.json", "analyses/M730_clock_offset.json", "analyses/M733_tyre_pressure.json",
             "analyses/M729_cloud_coverage.csv"]
PROTECTED_DIRS = ["analyses/M717_frozen_sources", "seasonal_fits_cache"]
# id, script, needs, retest outputs (names the tool writes), pinned (no Rev 3 addendum yet)
TOOLS = [
    ("import", "mynissan_import.py", [], [], False),
    ("coverage", "mynissan_coverage.py", [], ["M729_cloud_coverage.csv", "M729_cloud_gaps.csv", "M729_cloud_brief.json"], False),
    ("clock_offset", "mynissan_clock_offset.py", [], ["M730_clock_offset.json", "M730_clock_offset_drives.csv"], False),
    ("tyre", "mynissan_tyre.py", ["coverage"], ["M733_tyre_pressure.json", "M733_tyre_snapshots.csv"], False),
    ("thermal", "mynissan_thermal.py", ["coverage"], ["M734_thermal_forcing.json"], True),
    ("grade", "mynissan_grade.py", [], ["M737_g0.json"], True),
    ("grade_shares", "dem_grade_shares.py", [], ["grade_shares_retest.json"], False),
    ("unlogged", "mynissan_unlogged.py", [], ["M739_unlogged_exposure.json"], True),
]


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def sha_or_none(p):
    return sha256_file(p) if os.path.isfile(p) else None


def md5_file(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def hash_protected(root=None):
    root = root or ROOT
    out = {}
    for rel in PROTECTED:
        p = os.path.join(root, rel)
        out[rel] = sha256_file(p) if os.path.isfile(p) else None
    for rel in PROTECTED_DIRS:
        d = os.path.join(root, rel)
        h = hashlib.sha256()
        if os.path.isdir(d):
            for dp, _dn, fn in sorted(os.walk(d)):
                for f in sorted(fn):
                    fp = os.path.join(dp, f)
                    h.update(os.path.relpath(fp, d).encode() + sha256_file(fp).encode())
            out[rel] = h.hexdigest()
        else:
            out[rel] = None
    return out


def kill_tree(proc):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def run_cmd(cmd, timeout, env):
    kw = {"creationflags": 0x00000200} if os.name == "nt" else {"start_new_session": True}
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=ROOT, **kw)
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), round(time.time() - t0, 1), False
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=10)
        except Exception:
            out, err = b"", b""
        return -9, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), round(time.time() - t0, 1), True


def store_dir():
    return os.environ.get("XT_CLOUD_STORE") or P("cloud_store")


def inputs_fingerprint(tid, script, master_md5, store_manifest_sha, extra):
    d = {"tool": sha_or_none(P("tools", script)), "master": master_md5, "store": store_manifest_sha, "raw": os.path.abspath(os.environ.get("XT_RAW_DIR") or P("raw")), "extra": extra}
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()


def tool_cmd(tid, script, scratch, master_md5, store, cov_dir):
    base = [PY, P("tools", script)]
    if tid == "import":
        return base + ["--auto", os.environ.get("XT_CLOUD_EXPORTS", ""), "--store", store]
    if tid == "coverage":
        return base + ["--store", store, "--out-dir", scratch]
    if tid == "clock_offset":
        return base + ["--store", store, "--raw", os.environ.get("XT_RAW_DIR") or P("raw"), "--out-dir", scratch]
    if tid == "tyre":
        return base + ["--store", store, "--out-dir", scratch, "--coverage", os.path.join(cov_dir, "M729_cloud_coverage.csv")]
    if tid == "grade_shares":
        return base + ["--run", "--retest", "--store", store, "--out-dir", scratch]
    return base


def dem_complete():
    d = os.environ.get("XT_DEM_DIR") or ""
    return bool(d) and all(os.path.isdir(os.path.join(d, s)) for s in ("fabdem", "nasadem", "aw3d30", "glo30"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=1200)
    ap.add_argument("--only", default="")
    ap.add_argument("--out-root", default=P("analyses", "cloud_retests"))
    ap.add_argument("--status", default=P("analyses", "cloud_stage_status.json"))
    a = ap.parse_args(argv)
    only = set(x for x in a.only.split(",") if x)
    status = {"stage": "cloud_auxiliary", "spec": "analyses/M746_spec.md Rev 5", "verified": False, "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tools": {}}
    code = 0
    lock = None
    try:
        store = store_dir()
        manifest = os.path.join(store, "manifest.json")
        has_store = os.path.exists(manifest)
        master = P("drive_master.csv")
        master_md5 = md5_file(master)
        status["masterMd5"] = master_md5
        store_sha = sha256_file(manifest) if has_store else None
        status["storeManifestSha256"] = store_sha
        if has_store:
            lock = os.path.join(store, ".cloud_stage.lock")
            if os.path.exists(lock):
                for tid, *_ in TOOLS:
                    status["tools"][tid] = {"status": "skipped_locked"}
                lock = None
                raise StopIteration
            open(lock, "w").write(str(os.getpid()))
        prev = {}
        if os.path.exists(a.status):
            try:
                prev = json.load(open(a.status, encoding="utf-8")).get("tools", {})
            except Exception:
                prev = {}
        env = dict(os.environ, PYTHONUTF8="1")
        before_all = hash_protected()
        cov_dir = None
        failed_ids = set()
        breach = False
        for tid, script, needs, outs, pinned in TOOLS:
            rec = {"status": None}
            status["tools"][tid] = rec
            if only and tid not in only:
                rec["status"] = "skipped_opt_out"
                continue
            if breach:
                rec["status"] = "integrity_breach"
                continue
            if not has_store:
                rec["status"] = "skipped_no_store"
                continue
            if pinned:
                rec["status"] = "skipped_pinned_master"
                continue
            if any(n in failed_ids for n in needs):
                rec["status"] = "skipped_upstream_failed"
                continue
            if tid == "import" and not (os.environ.get("XT_CLOUD_EXPORTS") and glob.glob(os.path.join(os.environ["XT_CLOUD_EXPORTS"], "*.zip"))):
                rec["status"] = "skipped_no_new_input"
                continue
            if tid == "grade_shares" and not dem_complete():
                rec["status"] = "skipped_no_dem"
                continue
            extra = {"dem": sha_or_none(P("analyses", "M762_dem_manifest.json")) if tid == "grade_shares" else None,
                     "cross": sha_or_none(P("tools", "dem_crosscheck.py")) if tid == "grade_shares" else None}
            fp = inputs_fingerprint(tid, script, master_md5, store_sha, extra)
            dest = os.path.join(a.out_root, "%s_%s" % (tid, master_md5[:8]))
            p_rec = prev.get(tid) or {}
            if tid != "import" and p_rec.get("fingerprint") == fp and outs and all(os.path.exists(os.path.join(dest, o)) and sha256_file(os.path.join(dest, o)) == (p_rec.get("outputs") or {}).get(o) for o in outs):
                rec.update(status="skipped_up_to_date", fingerprint=fp)
                if tid == "coverage":
                    cov_dir = dest
                continue
            scratch = tempfile.mkdtemp(prefix="cloud_%s_" % tid)
            cmd = tool_cmd(tid, script, scratch, master_md5, store, cov_dir or os.path.join(a.out_root, "coverage_%s" % master_md5[:8]))
            if tid == "tyre" and cov_dir is None:
                cmd[-1] = os.path.join(a.out_root, "coverage_%s" % master_md5[:8], "M729_cloud_coverage.csv")
            rc, so, se, secs, timed_out = run_cmd(cmd, a.timeout, env)
            rec.update(seconds=secs, exit_code=rc)
            after = hash_protected()
            changed = [k for k in before_all if before_all[k] != after[k]]
            if changed:
                rec.update(status="integrity_breach", changed=changed)
                breach = True
                code = 2
                shutil.rmtree(scratch, ignore_errors=True)
                continue
            if timed_out:
                rec["status"] = "timeout"
                failed_ids.add(tid)
            elif rc != 0 or any(not os.path.exists(os.path.join(scratch, o)) for o in outs):
                rec.update(status="failed", stderr=(se or so)[:300])
                failed_ids.add(tid)
            else:
                if tid != "import":
                    os.makedirs(dest, exist_ok=True)
                    shas = {}
                    for o in outs:
                        os.replace(os.path.join(scratch, o), os.path.join(dest, o))
                        shas[o] = sha256_file(os.path.join(dest, o))
                    rec.update(status="ok", fingerprint=fp, outputs=shas, promotedTo=os.path.relpath(dest, ROOT).replace("\\", "/"))
                    if tid == "coverage":
                        cov_dir = dest
                else:
                    rec["status"] = "ok"
            shutil.rmtree(scratch, ignore_errors=True)
        status["integrity"] = {"protectedUnchanged": not breach}
    except StopIteration:
        pass
    except Exception as e:                                         # a crash of the wrapper itself is recorded, never stops an ingestion
        status["wrapper_error"] = "%s: %s" % (type(e).__name__, str(e)[:200])
    finally:
        if lock and os.path.exists(lock):
            try:
                os.remove(lock)
            except OSError:
                pass
        status["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        os.makedirs(os.path.dirname(a.status), exist_ok=True)
        with open(a.status, "w", encoding="utf-8", newline="\n") as f:
            json.dump(status, f, indent=1)
    print("cloud_stage: " + ", ".join("%s=%s" % (k, v.get("status")) for k, v in status["tools"].items()) + (" | wrapper_error: %s" % status["wrapper_error"] if "wrapper_error" in status else ""))
    return code


if __name__ == "__main__":
    sys.exit(main())
