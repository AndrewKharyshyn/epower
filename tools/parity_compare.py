#!/usr/bin/env python3
"""Parity comparator for tools/regen_seasonal_raw.py (M384, Director ruling "revise, then go"; spec analyses/M384_spec.md).

exact     canonical JSON of the fresh block equals the stored block.
superset  every leaf of the fresh block exists in the stored block with an identical value, and the stored block carries ADDITIONAL dict keys only at paths
          registered by the splice that owns them (post-build splices write them after the builders ran: a real ingestion rebuilds the top-level blocks fresh,
          a run with no new files does not). Arrays must have EQUAL length and every element is compared recursively: an extra stored array element is
          never "additive" (a type or phase that disappeared from the fresh output must fail). Any extra leaf outside the registered patterns fails.
differs   anything else; `reasons` lists the first offending paths.
The registry is READ from the owning splices (tools/post_splices.ADDITIVE_LEAVES, tools/m362_splice.ADDITIVE_KEYS), not kept here. The comparator does not check
that the additive leaves are correct or current: their own splices and gates do that."""
import json


def _norm(o):
    return json.loads(json.dumps(o, default=float))


def _np(path):
    """path with array indices normalised to [i]"""
    import re
    return re.sub(r"\[\d+\]", "[i]", path)


def _allowed(path, patterns):
    n = _np(path)
    return any(n == p or n.startswith(p + "/") for p in patterns)


def compare(fresh, stored, patterns=()):
    fresh, stored = _norm(fresh), _norm(stored)
    if json.dumps(fresh, sort_keys=True) == json.dumps(stored, sort_keys=True):
        return {"verdict": "exact", "additiveLeaves": 0, "reasons": []}
    reasons, extra = [], []

    def count(o):
        return sum(count(v) for v in o.values()) if isinstance(o, dict) else (sum(count(v) for v in o) if isinstance(o, list) else 1)

    def walk(f, s, p):
        if isinstance(f, dict):
            if not isinstance(s, dict):
                reasons.append(p + ": type"); return
            for k in f:
                if k not in s:
                    reasons.append(f"{p}/{k}: missing in stored")
                else:
                    walk(f[k], s[k], f"{p}/{k}")
            for k in s:
                if k not in f:
                    if _allowed(f"{p}/{k}", patterns):
                        extra.append(f"{p}/{k}")
                    else:
                        reasons.append(f"{p}/{k}: extra stored key not registered by an owning splice")
        elif isinstance(f, list):
            if not isinstance(s, list) or len(f) != len(s):
                reasons.append(f"{p}: array length {len(f)} (fresh) vs {len(s) if isinstance(s, list) else 'not a list'} (stored)"); return
            for i, (x, y) in enumerate(zip(f, s)):
                walk(x, y, f"{p}[{i}]")
        elif json.dumps(f) != json.dumps(s):                       # as strict as the canonical-JSON equality it replaces (1 vs 1.0 differs)
            reasons.append(f"{p}: {f!r} (fresh) vs {s!r} (stored)")

    walk(fresh, stored, "")
    if reasons:
        return {"verdict": "differs", "additiveLeaves": 0, "reasons": reasons[:10]}
    return {"verdict": "superset", "additiveLeaves": sum(count(_get(stored, x)) for x in extra) if extra else 0, "additiveKeys": sorted({_np(x) for x in extra})[:20], "reasons": []}


def _get(o, path):
    import re
    for tok in re.findall(r"\[(\d+)\]|/([^/\[\]]+)", path):
        o = o[int(tok[0])] if tok[0] != "" else o[tok[1]]
    return o


def registry():
    """chart id -> registered additive path patterns, read from the owning splices."""
    import os, sys
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (here, os.path.dirname(here)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import post_splices, m362_splice
    return {"CrawlStopGo": list(post_splices.ADDITIVE_LEAVES["CrawlStopGo"]),
            "EngineStartsByType": ["[i]/" + k for k in m362_splice.ADDITIVE_KEYS]}
