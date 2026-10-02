"""M-F03 step 1a (read-only): recover the 333 canonical raw files that fail raw_manifest.json from the original
exports in the Investigation folder (loose CSVs + ZIPs), verify sha256 against the manifest, and copy each to a
SEPARATE directory (never raw/). Writes originals_recovered_report.json. Does not touch raw/ or raw_manifest.json.
Usage: python tools/originals_recover.py OUT_DIR REPORT_JSON [--dry-run]"""
import hashlib, io, json, os, re, shutil, sys, zipfile
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(REPO))
OUT, REPORT = sys.argv[1], sys.argv[2]
DRY = "--dry-run" in sys.argv
if os.path.abspath(OUT).startswith(os.path.abspath(os.path.join(REPO, "raw"))):
    sys.exit("refusing: OUT_DIR inside raw/")

def norm_hash(b):
    if b.startswith(b"\xef\xbb\xbf"): b = b[3:]
    b = b.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    lines = [ln.rstrip() for ln in b.split(b"\n")]
    while lines and lines[-1] == b"": lines.pop()
    return hashlib.sha256(b"\n".join(lines)).hexdigest()

recs = {r["record_id"]: r for r in json.load(open(os.path.join(REPO, "raw_manifest.json"), encoding="utf-8"))["files"]}
rawdir = os.path.join(REPO, "raw")
key_of = lambda n: (lambda d: d[:8] + "_" + d[8:14] + ".csv")(re.sub(r"\D", "", n)) if len(re.sub(r"\D", "", n)) >= 14 else None
cur = {key_of(n): os.path.join(rawdir, n) for n in os.listdir(rawdir) if key_of(n)}
failing = {}
for rid, r in recs.items():
    if r["role"] != "canonical": continue
    p = cur.get(rid)
    b = open(p, "rb").read() if p else None
    if b is None or (hashlib.sha256(b).hexdigest() != r["sha256"] and norm_hash(b) != r["normHash"]):
        failing[rid] = (p, b)

cands = {}  # sha -> list of (src, name, getter)
def reg(src, name, b):
    cands.setdefault(hashlib.sha256(b).hexdigest(), []).append((src, name, b))
for n in sorted(os.listdir(ROOT)):
    p = os.path.join(ROOT, n)
    if os.path.isfile(p) and n.lower().endswith(".csv"):
        reg("loose", n, open(p, "rb").read())
    elif os.path.isfile(p) and n.lower().endswith(".zip"):
        with zipfile.ZipFile(p) as z:
            for m in z.infolist():
                if m.filename.lower().endswith(".csv") and not m.is_dir():
                    reg(n, m.filename, z.read(m))

if not DRY: os.makedirs(OUT, exist_ok=True)
rows, ok, bad = [], 0, []
for rid, (p, rawb) in sorted(failing.items()):
    want = recs[rid]["sha256"]
    hit = cands.get(want)
    if not hit:
        bad.append(rid); rows.append(dict(record_id=rid, recovered=False)); continue
    src = sorted(hit, key=lambda h: (h[0] != "loose", h[0]))[0]
    b = src[2]
    assert hashlib.sha256(b).hexdigest() == want
    if not DRY:
        with open(os.path.join(OUT, rid), "wb") as f: f.write(b)
        assert hashlib.sha256(open(os.path.join(OUT, rid), "rb").read()).hexdigest() == want
    ok += 1
    rows.append(dict(record_id=rid, recovered=True, source=src[0], source_name=src[1], n_sources=len(hit),
                     bytes_orig=len(b), bytes_raw=len(rawb) if rawb else None,
                     raw_norm_equal=(norm_hash(rawb) == norm_hash(b)) if rawb else None,
                     lines_orig=b.count(b"\n"), lines_raw=rawb.count(b"\n") if rawb else None))
rep = dict(dry_run=DRY, out_dir=OUT, n_failing=len(failing), n_recovered_sha_verified=ok, not_recovered=bad,
           n_raw_norm_equal=sum(1 for r in rows if r.get("raw_norm_equal")),
           n_line_count_differs=sum(1 for r in rows if r.get("recovered") and r["lines_orig"] != r["lines_raw"]),
           by_source={s: sum(1 for r in rows if r.get("source") == s) for s in {r.get("source") for r in rows if r.get("recovered")}},
           files=rows)
json.dump(rep, open(REPORT, "w", encoding="utf-8"), indent=1)
print({k: v for k, v in rep.items() if k != "files"})
