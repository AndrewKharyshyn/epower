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
STAGE_ENV = ("XT_INGEST_LABEL", "XT_ALLOW_STALE_CARRY", "XT_RECOMPUTE_M119V2")
STAGE_ENV_ONLY = {"XT_ALLOW_STALE_CARRY": ("build_html",)}          # M575: read by one stage only: it must not change the hash of every stage whose code merely names it                         # M575: env inputs that only some stages read: hashed into those stages' code hash (when set), not into the base key
EXTRA_EXCLUDE_TOP = {"regen_cache"}                      # content-keyed cache: not part of the data state
CODELIKE_PREFIX = ("docs/", "tests/", "snapshots/")
CODELIKE_FILES = ("tools/ingest_stages.json", "CHANGELOG.md", "CLAUDE.md", "STATE.md", "state.json")
NO_CODE_HASH = ("CHANGELOG.md", "STATE.md", "state.json")          # M621 (P-02a): documentation written every milestone; still code-like (excluded from the data state) but never part of a stage's code hash
NARROW_VIEWS = {"refresh_cohort_meta": {"xtrail_summary.jsx": r"COHORT_MIN_SUPPORT_DRIVES\s*=\s*\d+"}}   # M621 (P-02a): stage id -> file -> the only lines of it the stage reads (a jsx wording fix must not restart at this stage)
MAX_BYTES = RJ.MAX_COPY_BYTES
_PATH_RE = re.compile(r"^[\w./\\-]+$")


class CheckpointError(RuntimeError):
    pass


is_ack_input = RJ.is_ack_input          # M609: single definition shared with the release journal (a rollback must not delete a late-written ack)


def is_codelike(rel):
    return is_ack_input(rel) or rel.endswith(SRC_EXT) or rel in CODELIKE_FILES or rel.startswith(CODELIKE_PREFIX) or (rel.startswith("analyses/") and rel.endswith(".md"))


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
                if f.endswith(RJ.EXCLUDE_SUFFIX) or RJ.skip_root_file(rel_d, f):
                    continue
                p = os.path.join(d, f)
                if os.path.islink(p) or not os.path.isfile(p):
                    continue
                rel = os.path.relpath(p, self.root).replace(os.sep, "/")
                (aux if is_codelike(rel) else data)[rel] = self._sha(p)
                sizes[rel] = os.path.getsize(p)
        return data, aux, sizes

    def env_identity(self):
        return _h(*self.env_components().values())

    def env_components(self):
        """M610a: the parts of the environment identity, by name (their values joined in this order are the identity)."""
        raw = os.path.join(self.root, "raw")
        listing = sorted((f, os.path.getsize(os.path.join(raw, f)), os.stat(os.path.join(raw, f)).st_mtime_ns) for f in os.listdir(raw)) if os.path.isdir(raw) else []
        xt = {k: v for k, v in sorted(os.environ.items()) if k.startswith("XT_") and k != "XT_RAW_DIR" and not k.startswith("XT_ACK_") and k not in STAGE_ENV}      # M575: acks are consulted only by the stage that stops on them
        import subprocess
        try:                                                   # blobs of the files that stages read from git (leaf_guard git:HEAD, m321 update): a code-only commit does not change them
            head = subprocess.run(["git", "rev-parse", "HEAD:summary_arrays.json", "HEAD:summary_config.json", "HEAD:drive_master.csv"], cwd=self.root, capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            head = "nogit"
        import run_fingerprint as RF
        return {"raw listing": json.dumps(listing), "XT_* variables": json.dumps(xt), "python version": "%d.%d" % sys.version_info[:2], "platform": platform.system(),
                "tool versions": json.dumps(RF._versions(), sort_keys=True, default=str), "git blobs of summary_arrays/summary_config/drive_master at HEAD": head}

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
        return {r for r in out if is_codelike(r) and r not in NO_CODE_HASH}      # data files are covered by the data state, not by the code hash

    def closure(self, rel, narrow=()):
        """Static closure: source files are followed for imports and named files; any other referenced file (documentation, CHANGELOG) is a leaf."""
        key = (rel, tuple(sorted(narrow)))
        if key in self._closure:
            return self._closure[key]
        seen, todo = set(), [rel]
        while todo:
            r = todo.pop()
            if r in seen:
                continue
            seen.add(r)
            if r.endswith(SRC_EXT) and r not in narrow:       # a narrowed file is hashed by its read lines only and not followed
                todo.extend(self._refs(r) - seen)
        self._closure[key] = sorted(seen)
        return self._closure[key]

    def narrow_for(self, stage):
        """M621: files the stage reads only in part (see NARROW_VIEWS); shared with tools/stage_order.py so the lint and the hash agree."""
        return tuple(NARROW_VIEWS.get(stage["id"], {}))

    def _narrow_sha(self, rel, pattern):
        lines = [ln.strip() for ln in open(os.path.join(self.root, rel), encoding="utf-8", errors="replace").read().splitlines() if re.search(pattern, ln)]
        return _h(pattern, json.dumps(lines))

    def code_hash(self, stage):
        narrow = NARROW_VIEWS.get(stage["id"], {})
        files = set()
        for a in stage["cmd"]:
            r = self._resolve(a.replace("\\", "/")) if _PATH_RE.match(a) else None
            if r:
                files |= set(self.closure(r, tuple(narrow)))
        body = [(f, self._narrow_sha(f, narrow[f]) if f in narrow else RJ._sha(os.path.join(self.root, f))) for f in sorted(files) if os.path.isfile(os.path.join(self.root, f))]
        definition = {k: stage.get(k) for k in ("id", "cmd", "env", "outputs")}
        envs = []
        for v in STAGE_ENV:
            if v in STAGE_ENV_ONLY and stage["id"] not in STAGE_ENV_ONLY[v]:
                continue
            if v in os.environ and any(v in open(os.path.join(self.root, f), encoding="utf-8", errors="replace").read() for f, _ in body if f.endswith(SRC_EXT)):
                envs.append((v, os.environ[v]))
        if envs:                                                # unchanged hash for stages that do not read a set variable (checkpoints stay valid)
            return _h(json.dumps(definition, sort_keys=True), json.dumps(body), json.dumps(envs))
        return _h(json.dumps(definition, sort_keys=True), json.dumps(body))

    # ------------------------------------------------------------------ chain
    def begin(self):
        data, aux, _ = self.scan()
        self.prev, self.prev_aux = data, aux
        comps = self.env_components()
        self.base_parts = {"data": data, "env": {k: _h(v) for k, v in comps.items()}}
        self.base = _h(json.dumps(sorted(data.items())), _h(*comps.values()))
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
            info = {"reason": "no valid checkpoint chain for this base state" if not entries else "first stage changed or chain not restorable"}
            if not entries:
                mr = self.miss_reason()
                if mr:
                    info["missReason"] = mr
            self.discard()
            self.n = 0
            return 0, info
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
        self._stale_tail = [name for name, _e in entries[k:]]              # M575: the stale tail is removed lazily, at the first save of this run: a run killed before any new stage finished keeps the stored chain
        info = {"restoredStages": k, "lastRestored": applied[-1][1]["id"], "firstExecuted": self.stages[k]["id"] if k < len(self.stages) else None}
        if k < len(entries) or k < len(self.stages):
            info["reason"] = "stage %s: code or earlier inputs changed, or no checkpoint" % (self.stages[k]["id"] if k < len(self.stages) else "-")
        return k, info

    def miss_reason(self, limit=8):
        """M610a (spec R2): why no stored chain matches the current base key: compare the current parts with the most recently written other chain (base.json). None if there is none."""
        try:
            others = [os.path.join(self.store, d) for d in os.listdir(self.store) if os.path.join(self.store, d) != self.chain_dir]
            others = [d for d in others if os.path.isfile(os.path.join(d, "base.json"))]
            if not others or not getattr(self, "base_parts", None):
                return None
            prev = json.load(open(os.path.join(max(others, key=lambda d: os.path.getmtime(os.path.join(d, "base.json"))), "base.json"), encoding="utf-8"))
        except (OSError, ValueError):
            return None
        cur = self.base_parts
        parts = []
        for label, names in (("data file changed", sorted(r for r in cur["data"] if r in prev["data"] and cur["data"][r] != prev["data"][r])),
                             ("data file added", sorted(r for r in cur["data"] if r not in prev["data"])),
                             ("data file removed", sorted(r for r in prev["data"] if r not in cur["data"]))):
            if names:
                parts.append("%s: %s%s" % (label, ", ".join(names[:limit]), " (+%d more)" % (len(names) - limit) if len(names) > limit else ""))
        env = sorted(k for k in cur["env"] if cur["env"][k] != prev["env"].get(k))
        if env:
            parts.append("environment differs: " + ", ".join(env))
        return "; ".join(parts) or "base key differs from the stored chain in a way the stored parts do not show"

    def save(self, stage):
        """Record the files the (green) stage created / changed / deleted. Never raises: a stage that cannot be checkpointed ends the chain."""
        if self.dead:
            return
        try:
            i = self.n
            for name in getattr(self, "_stale_tail", []):
                shutil.rmtree(os.path.join(self.chain_dir, name), ignore_errors=True)
            self._stale_tail = []
            if i == 0 and os.path.isdir(self.chain_dir):                      # a fresh (non-resumed) chain replaces the stored one
                shutil.rmtree(self.chain_dir, ignore_errors=True)
            data, aux, sizes = self.scan()
            written = {r: s for r, s in data.items() if self.prev.get(r) != s}
            deleted = sorted(r for r in self.prev if r not in data)
            restorable = aux == self.prev_aux and all(sizes[r] <= MAX_BYTES for r in written)
            self.key = _h(self.key, stage["id"], self.code_hash(stage))
            ed = self._entry_dir(i, stage["id"])
            os.makedirs(ed, exist_ok=True)
            if i == 0 and getattr(self, "base_parts", None):                     # M610a: the parts of the base key, so a later miss can say what differed
                json.dump(self.base_parts, open(os.path.join(self.chain_dir, "base.json"), "w", encoding="utf-8", newline="\n"))
            if restorable:
                for r in written:
                    RJ._atomic_copy(os.path.join(self.root, r), os.path.join(ed, "files", r))
            else:
                self.notes.append("stage %s not checkpointed (writes a source/doc file or a file above %d bytes)" % (stage["id"], MAX_BYTES))
            tmp = os.path.join(ed, "entry.json.tmp")
            json.dump({"id": stage["id"], "key": self.key, "post": _h(json.dumps(sorted(data.items()))), "written": written, "deleted": deleted, "restorable": restorable},
                      open(tmp, "w", encoding="utf-8", newline="\n"))
            os.replace(tmp, os.path.join(ed, "entry.json"))
            if i == 0 and getattr(self, "run_started_at", None):                  # M611: the start of the run that began this chain; a resumed run adopts it (one coherent stamp instant)
                json.dump({"runStartedAt": self.run_started_at}, open(os.path.join(self.chain_dir, "chain_start.json"), "w", encoding="utf-8", newline="\n"))
            self.prev, self.prev_aux, self.n = data, aux, i + 1
            if not restorable:
                self.dead = True
        except Exception as ex:                                              # checkpoints are an optimisation; never fail the ingestion because of them
            self.notes.append("checkpoint of %s failed: %r" % (stage["id"], ex))
            self.dead = True

    def chain_start(self):
        """M611: ISO start of the run that began the stored chain, or None (no record)."""
        try:
            return json.load(open(os.path.join(self.chain_dir, "chain_start.json"), encoding="utf-8")).get("runStartedAt")
        except (OSError, ValueError, AttributeError, TypeError):
            return None

    def discard(self):
        if self.chain_dir:
            shutil.rmtree(self.chain_dir, ignore_errors=True)
