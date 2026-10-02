"""READ-ONLY sweep: hash every CSV in the Investigation folder (loose + inside ZIPs) with the
manifest's sha256 / normHash definitions and compare with raw_manifest.json. Writes nothing but a report."""
import hashlib, io, json, os, re, sys, zipfile
ROOT = r"C:\Users\AndriiKharyshyn\Downloads\X-Trail Investigation"
REPO = os.path.join(ROOT, "Repo", "xtrail-repo")
OUT = sys.argv[1]

def norm_hash(b):
    if b.startswith(b"\xef\xbb\xbf"): b = b[3:]
    b = b.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    lines = [ln.rstrip() for ln in b.split(b"\n")]
    while lines and lines[-1] == b"": lines.pop()
    return hashlib.sha256(b"\n".join(lines)).hexdigest()

man = json.load(open(os.path.join(REPO, "raw_manifest.json"), encoding="utf-8"))
recs = man["files"]
by_sha = {}; by_norm = {}
for r in recs:
    by_sha.setdefault(r["sha256"], []).append(r["record_id"])
    by_norm.setdefault(r["normHash"], []).append(r["record_id"])

# which manifest records currently FAIL against raw/
rawdir = os.path.join(REPO, "raw")
key_of = lambda n: (lambda d: d[:8] + "_" + d[8:14] + ".csv")(re.sub(r"\D", "", n)) if len(re.sub(r"\D", "", n)) >= 14 else None
cur = {}
for n in os.listdir(rawdir):
    k = key_of(n)
    if k: cur[k] = os.path.join(rawdir, n)
failing = []
for r in recs:
    if r["role"] != "canonical": continue
    p = cur.get(r["record_id"])
    if not p: failing.append(r["record_id"]); continue
    b = open(p, "rb").read()
    if hashlib.sha256(b).hexdigest() != r["sha256"] and norm_hash(b) != r["normHash"]:
        failing.append(r["record_id"])
failing = set(failing)

items = []
def add(src, name, b):
    items.append(dict(src=src, name=name, bytes=len(b), sha=hashlib.sha256(b).hexdigest(), norm=norm_hash(b)))

for n in sorted(os.listdir(ROOT)):
    p = os.path.join(ROOT, n)
    if os.path.isfile(p) and n.lower().endswith(".csv"):
        add("loose", n, open(p, "rb").read())
    elif os.path.isfile(p) and n.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(p) as z:
                for m in z.infolist():
                    if m.filename.lower().endswith(".csv") and not m.is_dir():
                        add(n, m.filename, z.read(m))
        except Exception as e:
            items.append(dict(src=n, name="<unreadable>", error=str(e)))

hits = {}  # record_id -> list of sources whose content matches the manifest identity
for it in items:
    if "sha" not in it: continue
    for rid in set(by_sha.get(it["sha"], []) + by_norm.get(it["norm"], [])):
        hits.setdefault(rid, []).append(dict(src=it["src"], name=it["name"],
                                              byte_identical=it["sha"] in by_sha, norm_identical=it["norm"] in by_norm))
canon = [r["record_id"] for r in recs if r["role"] == "canonical"]
rep = dict(
    scanned_items=len(items), loose_csv=sum(1 for i in items if i["src"] == "loose"),
    zips=len({i["src"] for i in items if i["src"] != "loose"}),
    unreadable=[i for i in items if "error" in i],
    canonical_total=len(canon), currently_failing=len(failing),
    failing_with_matching_original=sorted(r for r in failing if r in hits),
    n_failing_recovered=sum(1 for r in failing if r in hits),
    n_failing_not_recovered=sum(1 for r in failing if r not in hits),
    passing_also_found=sum(1 for r in canon if r not in failing and r in hits),
    hits={k: v[:3] for k, v in hits.items() if k in failing},
)
json.dump(rep, open(OUT, "w", encoding="utf-8"), indent=1)
print({k: (v if not isinstance(v, (list, dict)) else len(v)) for k, v in rep.items()})
