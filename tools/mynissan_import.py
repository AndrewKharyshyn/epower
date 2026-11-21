#!/usr/bin/env python3
"""MyNISSAN cloud export importer (M729). AUXILIARY source; OBD stays primary.

Reads export ZIPs or unpacked folders holding the six CSV streams, merges them into a normalised, sha256-manifested
store (default <repo>/cloud_store, git-ignored; override with env XT_CLOUD_STORE or --store). Exact-row dedup, a
conflict log (same stream+timestamp, different non-blank value in one field), idempotent re-import. Optional stage:
no input found -> exit 0 with a one-line note, never blocks an ingestion. ZIP members are read in memory by known
base name only (nothing is extracted to disk).

Usage: python tools/mynissan_import.py [--store DIR] PATH [PATH ...]      (PATH = .zip, folder, or folder of .zip)
       python tools/mynissan_import.py --auto DIR                         (import every *.zip in DIR; skip if none)
API:   load_stream(store, name) -> list of (utc_epoch_seconds, row_dict) sorted by time.
"""
import argparse, csv, glob, gzip, hashlib, io, json, os, sys, zipfile
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STREAMS = ["Odometer", "Trip_Information", "Vehicle_Information", "Geolocation", "Vehicle_Autonomy", "System_Safety_Alerts"]
META = ("VIN", "Timestamp")
TS_FMT = "%Y-%m-%d %H:%M:%S.%f"


def default_store():
    return os.environ.get("XT_CLOUD_STORE") or os.path.join(ROOT, "cloud_store")


def to_epoch(ts):
    try:
        return datetime.strptime(ts, TS_FMT).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _read_csv_bytes(b):
    text = b.decode("utf-8-sig")
    r = csv.reader(io.StringIO(text, newline=""))
    rows = list(r)
    if not rows:
        return [], []
    return rows[0], rows[1:]


def collect_sources(paths):
    """-> list of (source_name, source_sha256, {stream: bytes}). Skips anything without a known stream CSV."""
    out = []
    files = []
    for p in paths:
        if os.path.isdir(p):
            z = sorted(glob.glob(os.path.join(p, "*.zip")))
            if z:
                files += z
            else:
                files.append(p)
        else:
            files.append(p)
    for p in files:
        streams, h = {}, hashlib.sha256()
        if os.path.isdir(p):
            for s in STREAMS:
                f = os.path.join(p, s + ".csv")
                if os.path.exists(f):
                    b = open(f, "rb").read(); streams[s] = b; h.update(s.encode() + sha256_bytes(b).encode())
        elif zipfile.is_zipfile(p):
            h.update(open(p, "rb").read())
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    base = os.path.basename(n)
                    if base.endswith(".csv") and base[:-4] in STREAMS and base[:-4] not in streams:
                        streams[base[:-4]] = z.read(n)
        if streams:
            out.append((os.path.basename(p.rstrip("/\\")), h.hexdigest(), streams))
    return out


def _load_store_rows(store, s):
    f = os.path.join(store, "streams", s + ".csv.gz")
    if not os.path.exists(f):
        return [], set()
    with gzip.open(f, "rt", encoding="utf-8", newline="") as fh:
        r = csv.reader(fh)
        rows = list(r)
    cols = rows[0]
    return cols, {tuple(x) for x in rows[1:]}


def _write_gz(path, header, rows):
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    data = buf.getvalue().encode("utf-8")
    tmp = path + ".tmp"
    with open(tmp, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as g:
            g.write(data)
    os.replace(tmp, path)
    return sha256_bytes(open(path, "rb").read())


def import_sources(paths, store=None):
    store = store or default_store()
    srcs = collect_sources(paths)
    if not srcs:
        print("mynissan_import: no cloud export found, stage skipped (optional)")
        return {"skipped": True}
    os.makedirs(os.path.join(store, "streams"), exist_ok=True)
    mpath = os.path.join(store, "manifest.json")
    manifest = json.load(open(mpath, encoding="utf-8")) if os.path.exists(mpath) else {
        "role": "auxiliary", "archiveOfRecord": False, "primarySource": "OBD", "sources": {}, "streams": {}}
    conflicts = []
    for s in STREAMS:
        cols, rows = _load_store_rows(store, s)
        for name, sha, streams in srcs:
            if s not in streams:
                continue
            hdr, data = _read_csv_bytes(streams[s])
            if not hdr:
                continue
            for c in hdr:
                if c not in cols:
                    cols.append(c)
            idx = {c: i for i, c in enumerate(cols)}
            pad = len(cols)
            if rows and len(next(iter(rows))) < pad:
                rows = {tuple(r) + ("",) * (pad - len(r)) for r in rows}
            for d in data:
                row = [""] * pad
                for c, v in zip(hdr, d):
                    row[idx[c]] = v.strip()
                rows.add(tuple(row))
        if not cols or not rows:
            continue
        pad = len(cols)
        rows = {tuple(r) + ("",) * (pad - len(r)) for r in rows}
        ti = cols.index("Timestamp")
        ordered = sorted(rows, key=lambda r: (r[ti], r))
        # conflicts: same timestamp, one field with >1 distinct non-blank values
        i = 0
        while i < len(ordered):
            j = i
            while j + 1 < len(ordered) and ordered[j + 1][ti] == ordered[i][ti]:
                j += 1
            if j > i:
                for ci, c in enumerate(cols):
                    if c in META:
                        continue
                    vals = sorted({r[ci] for r in ordered[i:j + 1] if r[ci] != ""})
                    if len(vals) > 1:
                        conflicts.append((s, ordered[i][ti], c, "|".join(vals)))
            i = j + 1
        gz_sha = _write_gz(os.path.join(store, "streams", s + ".csv.gz"), cols, ordered)
        pop = [c for ci, c in enumerate(cols) if c not in META and any(r[ci] != "" for r in ordered)]
        manifest["streams"][s] = {"rows": len(ordered), "tmin": ordered[0][ti], "tmax": ordered[-1][ti], "columns": len(cols),
                                  "populated": pop, "blank": [c for c in cols if c not in META and c not in pop], "sha256": gz_sha}
    for name, sha, streams in srcs:
        parsed = {s: _read_csv_bytes(b) for s, b in streams.items()}
        ts = [r[parsed[s][0].index("Timestamp")] for s in parsed for r in parsed[s][1] if parsed[s][0] and r]
        manifest["sources"][sha] = {"name": name, "streams": sorted(streams), "tmin": min(ts) if ts else None, "tmax": max(ts) if ts else None,
                                    "rows_read": {s: len(parsed[s][1]) for s in parsed}}
    cp = os.path.join(store, "conflicts.csv")
    buf = io.StringIO(newline=""); w = csv.writer(buf, lineterminator="\n")
    w.writerow(["stream", "timestamp_utc", "field", "values"]); w.writerows(sorted(conflicts))
    open(cp, "w", encoding="utf-8", newline="").write(buf.getvalue())
    manifest["conflicts"] = len(conflicts)
    manifest["store_digest"] = sha256_bytes("".join(manifest["streams"][s]["sha256"] for s in STREAMS if s in manifest["streams"]).encode())
    json.dump(manifest, open(mpath, "w", encoding="utf-8"), indent=1, sort_keys=True)
    print(f"mynissan_import: {len(srcs)} source(s), digest {manifest['store_digest'][:12]}, conflicts {len(conflicts)}")
    return manifest


def load_stream(store, name):
    f = os.path.join(store, "streams", name + ".csv.gz")
    if not os.path.exists(f):
        return []
    with gzip.open(f, "rt", encoding="utf-8", newline="") as fh:
        r = csv.DictReader(fh)
        out = [(to_epoch(x["Timestamp"]), x) for x in r]
    out.sort(key=lambda a: a[0])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--store")
    ap.add_argument("--auto", help="folder to scan for *.zip; skipped silently when empty or missing")
    a = ap.parse_args(argv)
    paths = list(a.paths)
    if a.auto:
        paths += [a.auto] if os.path.isdir(a.auto) else []
    import_sources(paths, a.store)
    return 0


if __name__ == "__main__":
    sys.exit(main())
