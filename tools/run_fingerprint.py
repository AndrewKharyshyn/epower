#!/usr/bin/env python3
"""Run-level fingerprint for dependency-aware skipping (M385, audit 'dependency-driven rebuilding').

A no-change ingestion (no new raw file, no source change) re-runs ~25 stages that rewrite the same outputs. The fingerprint hashes everything those
stages can read: every source file (root and tools/: .py .js .jsx .sh), the stage list, the dependency lock, analyses/ (specs, pins and records
that stages read), the declared stage outputs (the exact state the previous run left), drive_master.csv, raw_manifest.json, the raw file listing
(name, size) and the interpreter / package versions / XT_* environment. If it equals the fingerprint recorded after the last fully green run, the
analysis stages would run on identical inputs. Components are kept separately so a mismatch names what changed. Outputs of the always-run stages
(the rendered dashboard) are excluded: they are rebuilt on every run.
This is opt-in (run_ingest --skip-unchanged); it is never a reason to skip the integrity/rendering/gate stages (ALWAYS_RUN)."""
import hashlib, json, os, platform, sys

FP_VERSION = 1
ALWAYS_RUN = ("preflight", "build_html", "jsdom", "release_check", "state")
EXCLUDED_OUTPUTS = ("xtrail_dashboard.html",)
SRC_EXT = (".py", ".js", ".jsx", ".sh")
PKGS = ("numpy", "pandas", "scipy", "scikit-learn", "statsmodels", "rainflow")


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _tree(root, sub, exts=None):
    base = os.path.join(root, sub) if sub else root
    out = {}
    if not os.path.isdir(base):
        return out
    if sub:
        walk = os.walk(base)
    else:
        walk = [(base, [], [f for f in os.listdir(base) if os.path.isfile(os.path.join(base, f))])]
    for dp, dn, fn in walk:
        dn[:] = [d for d in dn if d not in ("__pycache__", "node_modules", "eol_shim")] if sub else dn
        for f in fn:
            if exts is None or f.endswith(exts):
                p = os.path.join(dp, f)
                out[os.path.relpath(p, root).replace(os.sep, "/")] = _sha(p)
    return out


def _versions():
    from importlib import metadata
    v = {}
    for p in PKGS:
        try:
            v[p] = metadata.version(p)
        except Exception:
            v[p] = None
    return v


def components(root, stages):
    outs = sorted({o for s in stages for o in s.get("outputs", []) if o not in EXCLUDED_OUTPUTS})
    comp = {
        "version": FP_VERSION,
        "sources": hashlib.sha256(json.dumps({**_tree(root, "", SRC_EXT), **_tree(root, "tools", SRC_EXT)}, sort_keys=True).encode()).hexdigest(),
        "stageList": hashlib.sha256(json.dumps(stages, sort_keys=True).encode()).hexdigest(),
        "lock": hashlib.sha256(b"".join(_sha(os.path.join(root, f)).encode() for f in ("requirements.pinned.txt", "package-lock.json")
                                        if os.path.isfile(os.path.join(root, f)))).hexdigest(),
        "analyses": hashlib.sha256(json.dumps(_tree(root, "analyses"), sort_keys=True).encode()).hexdigest(),
        "outputs": hashlib.sha256(json.dumps({o: (_sha(os.path.join(root, o)) if os.path.isfile(os.path.join(root, o)) else None) for o in outs},
                                             sort_keys=True).encode()).hexdigest(),
        "master": _sha(os.path.join(root, "drive_master.csv")) if os.path.isfile(os.path.join(root, "drive_master.csv")) else None,
        "rawManifest": _sha(os.path.join(root, "raw_manifest.json")) if os.path.isfile(os.path.join(root, "raw_manifest.json")) else None,
        "rawListing": None,
        "env": hashlib.sha256(json.dumps({"python": platform.python_version(), "pkgs": _versions(),
                                          "xt": {k: v for k, v in sorted(os.environ.items()) if k.startswith("XT_") and k != "XT_RAW_DIR"}},
                                         sort_keys=True).encode()).hexdigest(),
    }
    rd = os.path.join(root, "raw")
    if os.path.isdir(rd):
        comp["rawListing"] = hashlib.sha256(json.dumps(sorted((f, os.path.getsize(os.path.join(rd, f))) for f in os.listdir(rd)), sort_keys=True).encode()).hexdigest()
    return comp


def fingerprint(comp):
    return hashlib.sha256(json.dumps(comp, sort_keys=True).encode()).hexdigest()


def ledger_path(root):
    return os.path.join(root, "runs", "last_green_fingerprint.json")


def load_ledger(root):
    p = ledger_path(root)
    if not os.path.isfile(p):
        return None
    try:
        d = json.load(open(p, encoding="utf-8"))
        return d if d.get("components", {}).get("version") == FP_VERSION else None
    except Exception:
        return None


def save_ledger(root, comp, run):
    os.makedirs(os.path.join(root, "runs"), exist_ok=True)
    json.dump({"run": run, "fingerprint": fingerprint(comp), "components": comp}, open(ledger_path(root), "w", encoding="utf-8", newline="\n"), indent=1)


def plan(root, stages, skip_unchanged):
    """-> (skip_ids, reason, comp). Skips every non-ALWAYS_RUN stage only when the fingerprint equals the last green one."""
    comp = components(root, stages)
    if not skip_unchanged:
        return set(), "skip-unchanged not requested", comp
    led = load_ledger(root)
    if led is None:
        return set(), "no valid ledger from a previous fully green run: running everything", comp
    if led["fingerprint"] == fingerprint(comp):
        return {s["id"] for s in stages if s["id"] not in ALWAYS_RUN}, "fingerprint equal to the last fully green run (run %s)" % led.get("run"), comp
    changed = sorted(k for k in comp if comp[k] != led["components"].get(k))
    return set(), "changed since the last green run: %s" % ", ".join(changed), comp
