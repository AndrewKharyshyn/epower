#!/usr/bin/env python3
"""Standard ambient-temperature protocol for ingestion (summary_config.json -> ambientByDrive).

Canonical stored form per drive file: a list of floats [start, *interim, end], always len >= 2.
  1 value  -> [v, v]              (start = end)
  2 values -> [start, end]
  3+ values-> [start, interim..., end]   (order = chronological; amb[-1] is always the end value)
Shorthand accepted on input: "+10", "+12->+13", "+17->+19->+17", or a list/scalar.
Consumers must read start = a[0], end = a[-1], drive mean = mean(a).

Usage:
  python tools/ambient_protocol.py check [--config summary_config.json]          # report non-canonical entries, exit 1 if any
  python tools/ambient_protocol.py normalize [--config ...] [--write]            # legacy scalar / len-1 -> canonical (dry-run unless --write)
  python tools/ambient_protocol.py add --spec spec.json [--raw-dir raw] [--write]
      spec.json: {"YYYY-MM-DD": ["+10", "+10", "+12->+13", ...]}  one entry per drive of that day in start-time order (D1, D2, ...)
      Fails if a day's drive count in raw/ differs from the spec, or a file already has an entry."""
import argparse, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def canonical(v):
    """Return canonical list[float] (len>=2) from shorthand str, scalar, or list. Raises ValueError."""
    if isinstance(v, str):
        parts = [p for p in re.split(r"\s*(?:->|→)\s*", v.strip()) if p != ""]
        vals = [float(p.replace("+", "")) for p in parts]
    elif isinstance(v, (int, float)) and not isinstance(v, bool):
        vals = [float(v)]
    elif isinstance(v, (list, tuple)) and v:
        vals = [float(x) for x in v]
    else:
        raise ValueError(f"unparseable ambient value: {v!r}")
    if not vals or any(x != x or not -50 <= x <= 60 for x in vals):
        raise ValueError(f"ambient out of domain (-50..60 C): {v!r}")
    return [vals[0], vals[0]] if len(vals) == 1 else vals


def is_canonical(v):
    return isinstance(v, list) and len(v) >= 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, cfg):
    # summary_config.json is indent=1, ensure_ascii=False, no trailing newline (byte-identical round-trip verified)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(cfg, ensure_ascii=False, indent=1))


def drive_files_by_day(raw_dir):
    days = {}
    for fn in sorted(os.listdir(raw_dir)):
        m = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})[ _](\d{2})-?(\d{2})-?(\d{2})\.csv$", fn)
        if m:
            days.setdefault(f"{m[1]}-{m[2]}-{m[3]}", []).append(fn)
    return days


def config_key(fn):
    """Config keys use 'YYYY-MM-DD_HH-MM-SS.csv' for recent drives (raw dir uses a space)."""
    return fn.replace(" ", "_")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "normalize", "add"])
    ap.add_argument("--config", default=os.path.join(ROOT, "summary_config.json"))
    ap.add_argument("--spec")
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    cfg = load(a.config)
    amb = cfg.setdefault("ambientByDrive", {})

    if a.cmd in ("check", "normalize"):
        bad = {k: v for k, v in amb.items() if not is_canonical(v)}
        print(json.dumps({"entries": len(amb), "non_canonical": len(bad), "sample": dict(list(bad.items())[:5])}))
        if a.cmd == "check":
            sys.exit(1 if bad else 0)
        for k, v in bad.items():
            amb[k] = canonical(v)
        if a.write and bad:
            save(a.config, cfg)
        print("written" if a.write and bad else "dry-run (no changes written)")
        return

    spec = load(a.spec)
    days = drive_files_by_day(a.raw_dir)
    new, errs = {}, []
    for day, vals in sorted(spec.items()):
        files = days.get(day, [])
        if len(files) != len(vals):
            errs.append(f"{day}: spec has {len(vals)} drives, raw has {len(files)}")
            continue
        for fn, v in zip(files, vals):
            k = config_key(fn)
            if k in amb:
                errs.append(f"{k}: already has an ambient entry")
                continue
            new[k] = canonical(v)
    print(json.dumps({"to_add": len(new), "errors": errs}, ensure_ascii=False))
    if errs:
        sys.exit(1)
    if a.write:
        amb.update(new)
        save(a.config, cfg)
        print("written")
    else:
        print("dry-run (no changes written)")


if __name__ == "__main__":
    main()
