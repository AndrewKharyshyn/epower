#!/usr/bin/env python3
"""M416 (audit F20, owner decision 2026-10-12): journaled release for the stage runner. All-or-nothing ingestion without changing the flat working tree.

Before the first stage the whole working tree (everything outside the excluded directories: raw originals, run logs, caches, .git, node_modules) is snapshotted: every file is copied to
runs/<run>/journal/files/ and hashed (sha256); journal.json records the state and the hashes and a lock file (runs/.release.lock) marks the release as in progress.
  * all stages green  -> COMMIT: the write set (files changed / created / deleted by the run) is recorded, the snapshot copies are deleted, the lock is released;
  * any stage failure, exception, SIGINT/SIGTERM -> ROLLBACK: every changed file is restored (temp file + os.replace), created files are removed, deleted files are re-created, and the
    whole tree is re-hashed against the snapshot (a mismatch is reported as rollback_failed, never as success);
  * the process died mid-run (journal still 'started') -> the next run refuses to start (exit 5) until `run_ingest.py --recover` rolls the tree back from the journal.
raw/ is never modified by a rollback (raw originals are never deleted); raw files added during the run are listed in the report.
The tree snapshot covers undeclared writes too (stages with no declared outputs); the committed journal lists the write set, so a stage that writes an undeclared file is visible.
Usage: python tools/release_journal.py --status | --recover   (library use: Journal(root, run_dir).begin()/commit()/rollback())"""
import datetime as dt, hashlib, json, os, shutil, sys, time

EXCLUDE_TOP = {".git", "node_modules", "runs", "raw", "raw_only", "raw_cache", "drive_raw_cache", "capacity_cache", "audit", "tabtext", ".pytest_cache", ".claude"}   # regenerable caches, git-ignored logs, raw originals
MAX_COPY_BYTES = 30_000_000   # larger files are hashed (changes are detected and reported) but not copied: a rollback cannot restore them and says so (rollback_failed)
EXCLUDE_ANY = {"__pycache__"}
EXCLUDE_SUFFIX = (".pyc",)
LOCK = os.path.join("runs", ".release.lock")


class ReleaseError(RuntimeError):
    pass


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def tree(root):
    """{relative posix path: [size, sha256]} of every file outside the excluded directories."""
    out = {}
    for d, dirs, files in os.walk(root):
        rel_d = os.path.relpath(d, root)
        if rel_d == ".":
            dirs[:] = [x for x in dirs if x not in EXCLUDE_TOP and x not in EXCLUDE_ANY]
        else:
            dirs[:] = [x for x in dirs if x not in EXCLUDE_ANY]
        for f in files:
            if f.endswith(EXCLUDE_SUFFIX):
                continue
            p = os.path.join(d, f)
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            out[os.path.relpath(p, root).replace(os.sep, "/")] = [os.path.getsize(p), _sha(p)]
    return out


def raw_listing(root):
    d = os.path.join(root, "raw")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def pid_alive(pid):
    if pid is None:
        return False
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))      # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok) and code.value == 259                                # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _atomic_copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".rj_tmp"
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


class Journal:
    def __init__(self, root, run_dir):
        self.root = os.path.abspath(root)
        self.run_dir = os.path.abspath(run_dir)
        self.jdir = os.path.join(self.run_dir, "journal")
        self.jpath = os.path.join(self.jdir, "journal.json")
        self.files_dir = os.path.join(self.jdir, "files")
        self.state = None
        self.data = {}

    # ---------------------------------------------------------------- bookkeeping
    def _write(self):
        os.makedirs(self.jdir, exist_ok=True)
        tmp = self.jpath + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(self.data, f, indent=1)
        os.replace(tmp, self.jpath)

    def _lock_path(self):
        return os.path.join(self.root, LOCK)

    @staticmethod
    def open_journals(root):
        """Journals of this tree whose state is not final (started / kept_for_debug / rollback_failed), newest first."""
        out = []
        rd = os.path.join(root, "runs")
        if os.path.isdir(rd):
            for n in sorted(os.listdir(rd), reverse=True):
                jp = os.path.join(rd, n, "journal", "journal.json")
                if os.path.isfile(jp):
                    d = json.load(open(jp, encoding="utf-8"))
                    if d.get("state") in ("started", "kept_for_debug", "rollback_failed"):
                        out.append((n, d))
        return out

    def begin(self, meta=None):
        lp = self._lock_path()
        if os.path.exists(lp):
            lk = json.load(open(lp, encoding="utf-8"))
            if pid_alive(lk.get("pid")) and lk.get("pid") != os.getpid():
                raise ReleaseError("a release is in progress (run %s, pid %s): refusing to start a second one" % (lk.get("run"), lk.get("pid")))
            raise ReleaseError("an interrupted release is on record (run %s): run `python tools/run_ingest.py --recover` first" % lk.get("run"))
        pend = self.open_journals(self.root)
        if pend:
            raise ReleaseError("unfinished release journal(s) %s: run `python tools/run_ingest.py --recover` first" % [n for n, _ in pend])
        t0 = time.time()
        snap = tree(self.root)
        os.makedirs(self.files_dir, exist_ok=True)
        uncopied = sorted(r for r, v in snap.items() if v[0] > MAX_COPY_BYTES)
        for rel in snap:
            if rel not in uncopied:
                _atomic_copy(os.path.join(self.root, rel), os.path.join(self.files_dir, rel))
        self.data = {"run": os.path.basename(self.run_dir), "state": "started", "startedAt": _now(), "pid": os.getpid(), "root": self.root, "meta": meta or {},
                     "snapshot": snap, "nFiles": len(snap), "bytes": int(sum(v[0] for v in snap.values())), "rawListing": raw_listing(self.root), "uncopiedLargeFiles": uncopied, "snapshotSeconds": round(time.time() - t0, 2)}
        self._write()
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        with open(lp, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"run": self.data["run"], "pid": os.getpid(), "startedAt": self.data["startedAt"]}, f)
        return self.data

    def _release_lock(self):
        try:
            os.remove(self._lock_path())
        except OSError:
            pass

    def _diff(self, now, snap):
        changed = sorted(r for r in now if r in snap and now[r][1] != snap[r][1])
        created = sorted(r for r in now if r not in snap)
        deleted = sorted(r for r in snap if r not in now)
        return changed, created, deleted

    def _drop_copies(self):
        shutil.rmtree(self.files_dir, ignore_errors=True)

    # ---------------------------------------------------------------- commit
    def commit(self, declared_outputs=()):
        snap = self.data["snapshot"]
        now = tree(self.root)
        changed, created, deleted = self._diff(now, snap)
        declared = set(declared_outputs)
        self.data.update(state="committed", committedAt=_now(), writeSet={"changed": changed, "created": created, "deleted": deleted},
                         undeclaredWrites=sorted(f for f in (changed + created + deleted) if f not in declared),
                         rawAdded=sorted(set(raw_listing(self.root)) - set(self.data.get("rawListing", []))))
        self._write()
        self._drop_copies()
        self._release_lock()
        return self.data

    # ---------------------------------------------------------------- rollback
    def rollback(self, reason, keep_copies=False):
        """Restore the snapshot. Returns the report; state 'rolled_back' only if the re-hashed tree equals the snapshot."""
        snap = self.data["snapshot"]
        now = tree(self.root)
        changed, created, deleted = self._diff(now, snap)
        errors = []
        for rel in changed + deleted:
            if rel in self.data.get("uncopiedLargeFiles", []):
                errors.append("cannot restore %s: larger than %d bytes, not copied" % (rel, MAX_COPY_BYTES))
                continue
            try:
                _atomic_copy(os.path.join(self.files_dir, rel), os.path.join(self.root, rel))
            except OSError as ex:
                errors.append("restore %s: %r" % (rel, ex))
        for rel in created:
            try:
                os.remove(os.path.join(self.root, rel))
            except OSError as ex:
                errors.append("remove %s: %r" % (rel, ex))
        after = tree(self.root)
        mism = sorted(r for r in set(after) | set(snap) if after.get(r, [None, None])[1] != snap.get(r, [None, None])[1])
        ok = not errors and not mism
        self.data.update(state="rolled_back" if ok else "rollback_failed", rolledBackAt=_now(), reason=str(reason)[:500],
                         restored={"changed": changed, "created": created, "deleted": deleted}, rollbackErrors=errors[:20], rollbackMismatches=mism[:50],
                         rawAdded=sorted(set(raw_listing(self.root)) - set(self.data.get("rawListing", []))))
        self._write()
        if ok:
            if not keep_copies:
                self._drop_copies()
            self._release_lock()
        return self.data

    def keep_for_debug(self, reason):
        """Leave the mixed state in place for inspection; the journal stays open (the next run needs --recover)."""
        self.data.update(state="kept_for_debug", keptAt=_now(), reason=str(reason)[:500])
        self._write()
        return self.data

    # ---------------------------------------------------------------- recovery of an interrupted run
    @staticmethod
    def recover(root):
        reports = []
        for name, d in Journal.open_journals(root):
            j = Journal(root, os.path.join(root, "runs", name))
            j.data = d
            if d["state"] == "started" and pid_alive(d.get("pid")):
                raise ReleaseError("run %s is still running (pid %s)" % (name, d.get("pid")))
            if not os.path.isdir(j.files_dir):
                raise ReleaseError("journal %s has no snapshot copies (cannot roll back)" % name)
            rep = j.rollback("recovery of an interrupted or kept release")
            reports.append({"run": name, "state": rep["state"], "restored": {k: len(v) for k, v in rep["restored"].items()}, "mismatches": rep["rollbackMismatches"][:10]})
        lp = os.path.join(root, LOCK)
        if os.path.exists(lp) and all(r["state"] == "rolled_back" for r in reports):
            try:
                os.remove(lp)
            except OSError:
                pass
        return reports


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if "--recover" in argv:
        try:
            rep = Journal.recover(root)
        except ReleaseError as ex:
            print(json.dumps({"error": str(ex)})); return 4
        print(json.dumps({"recovered": rep}, indent=1)); return 0 if all(r["state"] == "rolled_back" for r in rep) else 4
    op = Journal.open_journals(root)
    lk = os.path.join(root, LOCK)
    print(json.dumps({"openJournals": [{"run": n, "state": d["state"]} for n, d in op], "lock": json.load(open(lk, encoding="utf-8")) if os.path.exists(lk) else None}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
