#!/usr/bin/env python3
"""M464 (spec analyses/M464_spec.md): stage checkpoints for tools/run_ingest.py.

After every green stage of a full journaled run the files the stage created or changed are copied to runs/.checkpoints/<base>/<NN>_<id>/ together with a chain key
K_i = H(K_{i-1}, stage id, code hash of the stage). `run_ingest.py --resume` restores the longest prefix of the stored chain whose keys equal the recomputed ones and
executes only the first stage whose code (or any earlier input) changed and everything after it. The data state excludes source files and documentation-like inputs (they
are tracked through the stage code hash, which follows the static import closure and string constants naming repository files), so a code fix invalidates its own stage and
the later stages but not the earlier ones. A change to any data file, the raw listing or the XT_* environment changes the base key and invalidates the whole chain.
The release journal (tools/release_journal.py) is untouched: it snapshots the tree before anything is restored and rolls back on any failure, including a failed restore.
Library use: cp = Checkpoints(root, stages); cp.begin(); k, info = cp.try_restore(); ... cp.save(stage) after each green stage; cp.discard() after a green run."""
import ast, hashlib, json, os, platform, re, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_journal as RJ

SRC_EXT = (".py", ".js", ".jsx", ".sh")
STORE = os.path.join("runs", ".checkpoints")
EXTRA_EXCLUDE_TOP = {"regen_cache"}                      # content-keyed cache: not part of the data state
CODELIKE_PREFIX = ("docs/", "tests/", "snapshots/")
CODELIKE_FILES = ("tools/ingest_stages.json", "CHANGELOG.md", "CLAUDE.md", "STATE.md", "state.json")
MAX_BYTES = RJ.MAX_COPY_BYTES
_PATH_RE = re.compile(r"^[\w./\\-]+$")


class CheckpointError(RuntimeError):
    pass


def is_codelike(rel):
    return rel.endswith(SRC_EXT) or rel in CODELIKE_FILES or rel.startswith(CODELIKE_PREFIX) or (rel.startswith("analyses/") and rel.endswith(".md"))


def _h(*parts):
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8") + b"\0")
    return h.hexdigest()


class Checkpoints:
    def __init__(self, root, stages, store=None):
        self.root = os.path.abspath(root)
        self.stages = stages
        self.store = store or os.path.join(self.root, STORE)
        self._closure = {}
        self._shacache = {}
        self.chain_dir = None
        self.key = None
        self.prev = None          # {rel: sha} data state after the last restored / saved stage
        self.prev_aux = None      # {rel: sha} of the code-like files at the same point
        self.n = 0                # number of stages in the stored chain so far
        self.dead = False         # the chain ended (a stage could not be checkpointed)
        self.notes = []

    # ------------------------------------------------------------------ state
    def _sha(self, p):
        st = os.stat(p)
        k = (st.st_size, st.st_mtime_ns)
        c = self._shacache.get(p)
        if c and c[0] == k and (c[2] - st.st_mtime_ns / 1e9) > 3:
            return c[1]
        import time
        sha = RJ._sha(p)
        self._shacache[p] = (k, sha, time.time())
        return sha

    def scan(self):
        """-> (data, aux, sizes): data = non-code-like files (path -> sha), aux = code-like files (path -> sha)."""
        data, aux, sizes = {}, {}, {}
        for d, dirs, files in os.walk(self.root):
            rel_d = os.path.relpath(d, self.root)
            if rel_d == ".":
                dirs[:] = [x for x in dirs if x not in RJ.EXCLUDE_TOP and x not in RJ.EXCLUDE_ANY and x not in EXTRA_EXCLUDE_TOP]
            else:
                dirs[:] = [x for x in dirs if x not in RJ.EXCLUDE_ANY]
            for f in files:
                if f.endswith(RJ.EXCLUDE_SUFFIX):
                    continue
                p = os.path.join(d, f)
                if os.path.islink(p) or not os.path.isfile(p):
                    continue
                rel = os.path.relpath(p, self.root).replace(os.sep, "/")
                (aux if is_codelike(rel) else data)[rel] = self._sha(p)
                sizes[rel] = os.path.getsize(p)
        return data, aux, sizes

    def env_identity(self):
        raw = os.path.join(self.root, "raw")
        listing = sorted((f, os.path.getsize(os.path.join(raw, f)), os.stat(os.path.join(raw, f)).st_mtime_ns) for f in os.listdir(raw)) if os.path.isdir(raw) else []
        xt = {k: v for k, v in sorted(os.environ.items()) if k.startswith("XT_") and k != "XT_RAW_DIR"}
        import subprocess
        try:                                                   # blobs of the files that stages read from git (leaf_guard git:HEAD, m321 update): a code-only commit does not change them
            head = subprocess.run(["git", "rev-parse", "HEAD:summary_arrays.json", "HEAD:summary_config.json", "HEAD:drive_master.csv"], cwd=self.root, capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            head = "nogit"
        import run_fingerprint as RF
        return _h(json.dumps(listing), json.dumps(xt), "%d.%d" % sys.version_info[:2], platform.system(), json.dumps(RF._versions(), sort_keys=True, default=str), head)

    # ------------------------------------------------------------------ code hash
    def _resolve(self, name, rel_to=None):
        for base in ([os.path.dirname(rel_to)] if rel_to else []) + ["", "tools"]:
            p = os.path.normpath(os.path.join(self.root, base, name))
            if os.path.isfile(p) and os.path.abspath(p).startswith(self.root):
                return os.path.relpath(p, self.root).replace(os.sep, "/")
        return None

    def _refs(self, rel):
        """Repository files referenced by one source file: local imports and string constants naming existing files."""
        p = os.path.join(self.root, rel)
        try:
            text = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            return set()
        out = set()
        if rel.endswith(".py"):
            try:
                tree = ast.parse(text)
            except SyntaxError:
                tree = None
            if tree is not None:
                for n in ast.walk(tree):
                    mods = []
                    if isinstance(n, ast.Import):
                        mods = [a.name for a in n.names]
                    elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                        mods = [n.module] + [n.module + "." + a.name for a in n.names]
                    for m in mods:
                        r = self._resolve(m.replace(".", "/") + ".py", rel)
                        if r:
                            out.add(r)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str) and re.match(r"^[A-Za-z_]\w*$", n.value):     # __import__('mod') / import_module('mod')
                        r = self._resolve(n.value + ".py", rel)
                        if r:
                            out.add(r)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) < 200 and _PATH_RE.match(n.value):
                        r = self._resolve(n.value.replace("\\", "/"), rel)
                        if r and not r.startswith("raw/"):
                            out.add(r)
        else:
            for tok in re.findall(r"[\w./\\-]+\.(?:py|js|sh|md)\b", text):
                r = self._resolve(tok.replace("\\", "/"), rel)
                if r:
                    out.add(r)
        out.discard(rel)
        return {r for r in out if is_codelike(r)}      # data files are covered by the data state, not by the code hash

    def closure(self, rel):
        """Static closure: source files are followed for imports and named files; any other referenced file (documentation, CHANGELOG) is a leaf."""
        if rel in self._closure:
            return self._closure[rel]
        seen, todo = set(), [rel]
        while todo:
            r = todo.pop()
            if r in seen:
                continue
            seen.add(r)
            if r.endswith(SRC_EXT):
                todo.extend(self._refs(r) - seen)
        self._closure[rel] = sorted(seen)
        return self._closure[rel]

    def code_hash(self, stage):
        files = set()
        for a in stage["cmd"]:
            r = self._resolve(a.replace("\\", "/")) if _PATH_RE.match(a) else None
            if r:
                files |= set(self.closure(r))
        body = [(f, RJ._sha(os.path.join(self.root, f))) for f in sorted(files) if os.path.isfile(os.path.join(self.root, f))]
        definition = {k: stage.get(k) for k in ("id", "cmd", "env", "outputs")}
        return _h(json.dumps(definition, sort_keys=True), json.dumps(body))

    # ------------------------------------------------------------------ chain
    def begin(self):
        data, aux, _ = self.scan()
        self.prev, self.prev_aux = data, aux
        self.base = _h(json.dumps(sorted(data.items())), self.env_identity())
        self.key = self.base
        self.chain_dir = os.path.join(self.store, self.base[:16])
        return self.base

    def _entry_dir(self, i, sid):
        return os.path.join(self.chain_dir, "%02d_%s" % (i, sid))

    def _load_entries(self):
        out = []
        if os.path.isdir(self.chain_dir):
            for n in sorted(os.listdir(self.chain_dir)):
                ep = os.path.join(self.chain_dir, n, "entry.json")
                if os.path.isfile(ep):
                    out.append((n, json.load(open(ep, encoding="utf-8"))))
        return out

    def try_restore(self):
        """Restore the longest valid prefix. -> (k, info). Raises CheckpointError when the restored tree does not match the recorded state (caller rolls back)."""
        entries = self._load_entries()
        k, key, applied = 0, self.base, []
        for i, s in enumerate(self.stages):
            if i >= len(entries):
                break
            name, e = entries[i]
            key = _h(key, s["id"], self.code_hash(s))
            if e.get("id") != s["id"] or e.get("key") != key or not e.get("restorable") or s.get("resumable") is False:
                break
            applied.append((name, e))
            k = i + 1
        if not k:
            self.discard()
            self.n = 0
            return 0, {"reason": "no valid checkpoint chain for this base state" if not entries else "first stage changed or chain not restorable"}
        for name, e in applied:
            for rel in e["deleted"]:
                p = os.path.join(self.root, rel)
                if os.path.exists(p):
                    os.remove(p)
            for rel in e["written"]:
                RJ._atomic_copy(os.path.join(self.chain_dir, name, "files", rel), os.path.join(self.root, rel))
        data, aux, _ = self.scan()
        if _h(json.dumps(sorted(data.items()))) != applied[-1][1]["post"]:
            raise CheckpointError("restored tree does not match the recorded state after stage %s" % applied[-1][1]["id"])
        self.prev, self.prev_aux, self.key, self.n = data, aux, applied[-1][1]["key"], k
        for name, _e in entries[k:]:                                          # stale tail
            shutil.rmtree(os.path.join(self.chain_dir, name), ignore_errors=True)
        info = {"restoredStages": k, "lastRestored": applied[-1][1]["id"], "firstExecuted": self.stages[k]["id"] if k < len(self.stages) else None}
        if k < len(entries) or k < len(self.stages):
            info["reason"] = "stage %s: code or earlier inputs changed, or no checkpoint" % (self.stages[k]["id"] if k < len(self.stages) else "-")
        return k, info

    def save(self, stage):
        """Record the files the (green) stage created / changed / deleted. Never raises: a stage that cannot be checkpointed ends the chain."""
        if self.dead:
            return
        try:
            i = self.n
            if i == 0 and os.path.isdir(self.chain_dir):                      # a fresh (non-resumed) chain replaces the stored one
                shutil.rmtree(self.chain_dir, ignore_errors=True)
            data, aux, sizes = self.scan()
            written = {r: s for r, s in data.items() if self.prev.get(r) != s}
            deleted = sorted(r for r in self.prev if r not in data)
            restorable = aux == self.prev_aux and all(sizes[r] <= MAX_BYTES for r in written)
            self.key = _h(self.key, stage["id"], self.code_hash(stage))
            ed = self._entry_dir(i, stage["id"])
            os.makedirs(ed, exist_ok=True)
            if restorable:
                for r in written:
                    RJ._atomic_copy(os.path.join(self.root, r), os.path.join(ed, "files", r))
            else:
                self.notes.append("stage %s not checkpointed (writes a source/doc file or a file above %d bytes)" % (stage["id"], MAX_BYTES))
            tmp = os.path.join(ed, "entry.json.tmp")
            json.dump({"id": stage["id"], "key": self.key, "post": _h(json.dumps(sorted(data.items()))), "written": written, "deleted": deleted, "restorable": restorable},
                      open(tmp, "w", encoding="utf-8", newline="\n"))
            os.replace(tmp, os.path.join(ed, "entry.json"))
            self.prev, self.prev_aux, self.n = data, aux, i + 1
            if not restorable:
                self.dead = True
        except Exception as ex:                                              # checkpoints are an optimisation; never fail the ingestion because of them
            self.notes.append("checkpoint of %s failed: %r" % (stage["id"], ex))
            self.dead = True

    def discard(self):
        if self.chain_dir:
            shutil.rmtree(self.chain_dir, ignore_errors=True)
