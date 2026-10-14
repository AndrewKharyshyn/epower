#!/usr/bin/env python3
"""M434 (audit F11 / F26): helpers for result-cache keys that must not outlive a data, parameter or dependency change.
- module_closure(path): the repo-local .py modules imported (transitively, static `import` / `from ... import`, including imports inside functions) by `path`, plus `path` itself.
- code_hash(paths): sha256 over (relative path, CRLF-normalised bytes) of the given files, order-independent.
- frame_hash(df, cols=None): sha256 over the exact values of a DataFrame (column names, dtypes, cell values), so a changed eligibility flag or metadata value in the same file list changes the key.
A false invalidation is cheap (one recompute); a stale hit silently corrupts a result, so the keys are deliberately broad."""
import ast, hashlib, os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SEARCH = (ROOT, os.path.join(ROOT, "tools"))


def _resolve(mod):
    rel = mod.replace(".", os.sep)
    for base in SEARCH:
        for cand in (os.path.join(base, rel + ".py"), os.path.join(base, rel, "__init__.py")):
            if os.path.isfile(cand):
                return os.path.abspath(cand)
    return None


def _imports(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            names.add(n.module)
            names.update(n.module + "." + a.name for a in n.names)      # `from tools import x` / `from pkg import submodule`
    return names


def module_closure(path):
    start = os.path.abspath(path)
    seen, stack = set(), [start]
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        for m in _imports(p):
            q = _resolve(m)
            if q and q not in seen:
                stack.append(q)
    return sorted(seen)


def code_hash(paths):
    h = hashlib.sha256()
    for p in sorted(os.path.abspath(x) for x in paths):
        h.update(os.path.relpath(p, ROOT).replace("\\", "/").encode() + b"\0")
        h.update(open(p, "rb").read().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def frame_hash(df, cols=None):
    import pandas as pd
    d = df if cols is None else df[list(cols)]
    h = hashlib.sha256()
    h.update("|".join("%s:%s" % (c, d[c].dtype) for c in d.columns).encode())
    h.update(pd.util.hash_pandas_object(d, index=True, categorize=False).values.tobytes())
    return h.hexdigest()
