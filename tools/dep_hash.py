#!/usr/bin/env python3
"""M489 (audit Update 7 A05): dependency-closure hash for the per-drive caches (pair_cache/, regen_cache/). A cache key that hashes only the extractor file misses a change in a shared helper the extractor calls
(a loader, a series builder, a nearest-time join, a column map): the entry would be reused although the code that produced it changed. closure_hash() hashes the SOURCE of every function reachable from the roots
(through the names each code object references, resolved against the function's own globals, then against the extra modules given), the VALUE of every simple module-level constant they reference, and the whole file
of any repository module a root or helper refers to as a module object (conservative: a change anywhere in that module forces a rebuild), plus the interpreter-independent library versions the arrays depend on.
Over-inclusion is deliberate (a rebuild is cheap, a silently stale cache is not); a name that resolves to nothing is ignored. Pure function of the code and constants: no I/O besides reading source files."""
import hashlib, inspect, json, os, sys, types

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_SIMPLE = (int, float, str, bool, type(None))


def _simple(v):
    if isinstance(v, _SIMPLE):
        return True
    if isinstance(v, (tuple, list, set, frozenset)):
        return len(v) < 200 and all(_simple(x) for x in v)
    if isinstance(v, dict):
        return len(v) < 200 and all(_simple(k) and _simple(x) for k, x in v.items())
    return False


def _in_repo(path):
    try:
        return os.path.commonpath([os.path.abspath(path), ROOT]) == ROOT
    except ValueError:
        return False


def _names(code):
    out = set(code.co_names)
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            out |= _names(c)
    return out


def closure(roots, modules=()):
    """-> (functions, constants, module_files): the closure of the roots. `roots` are functions; `modules` are extra modules whose top-level names are searched after the function's own globals."""
    funcs, consts, files = {}, {}, set()
    stack = list(roots)
    while stack:
        f = stack.pop()
        if isinstance(f, types.MethodType):
            f = f.__func__
        key = "%s.%s" % (getattr(f, "__module__", "?"), getattr(f, "__qualname__", repr(f)))
        if key in funcs or not isinstance(f, types.FunctionType):
            continue
        funcs[key] = inspect.getsource(f)
        for n in _names(f.__code__):
            for scope in [f.__globals__] + [m.__dict__ for m in modules]:
                if n not in scope:
                    continue
                v = scope[n]
                if isinstance(v, types.FunctionType) and _in_repo(inspect.getsourcefile(v) or ""):
                    stack.append(v)
                elif isinstance(v, types.ModuleType) and getattr(v, "__file__", None) and _in_repo(v.__file__):
                    files.add(os.path.abspath(v.__file__))
                elif _simple(v) and not n.startswith("__"):
                    consts["%s.%s" % (scope.get("__name__", "?"), n)] = repr(v)
    return funcs, consts, sorted(files)


def closure_hash(roots, modules=(), extra=None):
    """Hex SHA-256 over the closure sources, constants, referenced repository module files, the numpy/pandas versions and `extra` (a JSON-able dict: schema / field lists / versions)."""
    funcs, consts, files = closure(roots, modules)
    h = hashlib.sha256()
    for k in sorted(funcs):
        h.update(k.encode()); h.update(funcs[k].encode())
    h.update(json.dumps(consts, sort_keys=True).encode())
    for p in files:
        h.update(os.path.relpath(p, ROOT).encode()); h.update(open(p, "rb").read())
    h.update(json.dumps({"numpy": np.__version__, "pandas": pd.__version__, "extra": extra}, sort_keys=True, default=str).encode())
    return h.hexdigest()
