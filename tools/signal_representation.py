#!/usr/bin/env python3
"""M324 (GateA2) per-file signal-representation record for NEW drive files (spec: analyses/M324_gatea2_spec.md rev 2).

Descriptive only ("grid of this CSV copy", never "sensor resolution" or "rounding rule"); no quarantine rule beyond the per-channel R2 of
tools/plausibility_gate.py. Entries go to signal_representation.json (repo root): additive, atomic, sorted keys, fixed float format (reruns are
byte-identical). An existing key with a different sha256 fails closed unless it is named in `supersede` (the old entry is then kept under
'superseded'). Never applied to the published master; no pipeline/build reader consumes the file in M324.
Usage: python tools/signal_representation.py FILE [FILE ...] [--out PATH] [--supersede KEY]   (default --out signal_representation.json)"""
import hashlib, io, json, os, sys
import numpy as np
import pandas as pd

SCHEMA_VERSION = 1
MIN_DISTINCT = 5            # same minimum as the gate's R2: fewer distinct values give no grid statistic
TS_COL = "time"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_OUT = os.path.join(ROOT, "signal_representation.json")


class Conflict(Exception):
    pass


def norm_hash_bytes(b):
    """Same canonicalisation as corpus_manifest._norm_hash (BOM, EOL, trailing whitespace, trailing blank lines)."""
    if b.startswith(b"\xef\xbb\xbf"):
        b = b[3:]
    b = b.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    lines = [ln.rstrip() for ln in b.split(b"\n")]
    while lines and lines[-1] == b"":
        lines.pop()
    return hashlib.sha256(b"\n".join(lines)).hexdigest()


def _decimals(s):
    s = s.strip().lower().split("e")[0]
    return len(s.split(".")[1]) if "." in s else 0


def _channel(raw_col):
    num = pd.to_numeric(raw_col, errors="coerce")
    ok = num.notna()
    if not ok.any():
        return None
    v = num[ok].to_numpy(float)
    txt = raw_col[ok].astype(str)
    dec = txt.map(_decimals)
    n = len(v)
    hist = {}
    for k, c in dec.clip(upper=10).value_counts().items():
        hist["10+" if k == 10 else str(int(k))] = round(float(c) / n, 6)
    dist = np.unique(np.round(v, 9))
    step = None
    if len(dist) >= MIN_DISTINCT:
        d = np.round(np.diff(dist), 9)
        d = d[d > 0]
        step = round(float(d.min()), 9) if len(d) else None
    return {"n_nonnull": int(n), "n_distinct": int(len(dist)), "min": round(float(v.min()), 6), "max": round(float(v.max()), 6),
            "grid_step": step, "max_decimals": int(dec.max()),
            "decimals_share": dict(sorted(hist.items(), key=lambda kv: (len(kv[0]), kv[0]))),
            "share_on_0p1_grid": round(float((np.abs(v * 10 - np.round(v * 10)) < 1e-9).mean()), 6)}


def build_record(csv_bytes, gate=None):
    d = pd.read_csv(io.BytesIO(csv_bytes), dtype=str, keep_default_na=True, low_memory=False)
    cols = list(d.columns)
    rec = {"sha256": hashlib.sha256(csv_bytes).hexdigest(), "norm_hash": norm_hash_bytes(csv_bytes),
           "header_fingerprint": hashlib.sha256("\n".join(cols).encode("utf-8")).hexdigest(), "n_rows": int(len(d)),
           "timestamp_column": TS_COL if TS_COL in cols else None}
    if gate is not None:
        rec["gate"] = {"version": gate.get("gateVersion"), "flags": [f["rule"] for f in gate["flags"]], "checked": bool(gate["checked"]),
                       "untested_channels": gate.get("untestedChannels", [])}
    if TS_COL in cols:
        t = pd.to_datetime(d[TS_COL], format="mixed", errors="coerce")
        dt = t.diff().dt.total_seconds().mul(1000).dropna()
        dt = dt[dt > 0]
        rec["first_timestamp"], rec["last_timestamp"] = str(d[TS_COL].iloc[0]), str(d[TS_COL].iloc[-1])
        rec["cadence_ms"] = {"median": round(float(dt.median()), 3), "p95": round(float(dt.quantile(0.95)), 3)} if len(dt) else None
    ch = {}
    for c in cols:
        if c == TS_COL:
            continue
        x = _channel(d[c])
        if x is not None:
            ch[c] = x
    rec["channels"] = dict(sorted(ch.items()))
    return rec


def _dump(obj):
    return json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def write_entries(path, entries, supersede=()):
    """entries: {file_key: record}. Additive and atomic. Returns (added, unchanged, superseded) key lists."""
    doc = {"schema_version": SCHEMA_VERSION, "files": {}}
    if os.path.exists(path):
        doc = json.load(open(path, encoding="utf-8"))
        if doc.get("schema_version") != SCHEMA_VERSION:
            raise Conflict(f"schema_version {doc.get('schema_version')} != {SCHEMA_VERSION}")
    added, same, sup = [], [], []
    for k in sorted(entries):
        new = entries[k]
        old = doc["files"].get(k)
        if old is None:
            doc["files"][k] = new
            added.append(k)
        elif old["sha256"] == new["sha256"]:
            same.append(k)
        elif k in supersede:
            new = dict(new)
            new["superseded"] = [old] + list(old.pop("superseded", []) or [])
            doc["files"][k] = new
            sup.append(k)
        else:
            raise Conflict(f"{k}: recorded sha256 {old['sha256'][:12]} != new {new['sha256'][:12]} (use --supersede {k} for a legitimate re-export)")
    if added or sup:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(_dump(doc))
        os.replace(tmp, path)
    return added, same, sup


def main(argv):
    out, sup, files, i = DEFAULT_OUT, [], [], 0
    while i < len(argv):
        if argv[i] == "--out":
            out = argv[i + 1]; i += 2
        elif argv[i] == "--supersede":
            sup.append(argv[i + 1]); i += 2
        else:
            files.append(argv[i]); i += 1
    sys.path.insert(0, os.path.dirname(__file__))
    import plausibility_gate as pg
    ent = {}
    for p in files:
        b = open(p, "rb").read()
        ent[os.path.basename(p).replace(" ", "_")] = build_record(b, pg.check_bytes(b, os.path.basename(p)))
    print(json.dumps(dict(zip(("added", "unchanged", "superseded"), write_entries(out, ent, sup)))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
