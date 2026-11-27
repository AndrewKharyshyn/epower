#!/usr/bin/env python3
"""M780 (spec analyses/M780_spec.md Rev 2): recompute ONLY the payload block `batteryTempRanges` (Thermal tab, "Battery Temperature - Observed Range") with the whole-range 5 C
ambient bins and splice it into summary_arrays.json (additive-splice pattern: compute the one key, deep-diff, leaf-level splice; no full pipeline run).

Inputs: drive_master.csv (all drives, unfiltered: extrema are unfiltered statistics, M51), the raw OBD files (Sensor-1 trajectories through compute_summary_arrays._battery_temp_traj,
the same function the pipeline uses), summary_config.json ambientByDrive. Gates (exit 1, nothing written, on failure):
  * drive_master.csv MD5 unchanged and equal to the pinned corpus MD5;
  * every non-ambient row (class, duration, record) is identical to the published block;
  * the sum of the ambient rows' n equals the published sum of the three old ambient rows (same drives, re-binned); the old 'Cool ambient (<20 C)' count equals the sum of the new bins below 20 C;
  * the deep diff touches only /batteryTempRanges and its artifact stamp.
Usage: python tools/battery_temp_ranges_refresh.py [--dry-run] [--report FILE]"""
import argparse, copy, datetime, hashlib, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
PINNED_MD5 = "d514d6009d6d9a0a168ad4fb09b9bb98"
KEY = "batteryTempRanges"


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def walk(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            yield from walk(a.get(k), b.get(k), path + "/" + k)
    elif a != b:
        yield path


def consistency(published, new):
    """Pure checks (known-answer tested): returns a list of failures."""
    fails = []
    pa = [r for r in published if r.get("group") == "ambient"]
    na = [r for r in new if r.get("group") == "ambient"]
    pn = [r for r in published if r.get("group") != "ambient"]
    nn = [r for r in new if r.get("group") != "ambient"]
    if pn != nn:
        fails.append("a non-ambient row differs from the published block")
    if sum(r["n"] for r in pa) != sum(r["n"] for r in na):
        fails.append("the ambient total n differs (%d published, %d new)" % (sum(r["n"] for r in pa), sum(r["n"] for r in na)))
    old_cool = [r for r in pa if r["label"].startswith("Cool ambient")]
    if old_cool:
        below20 = [r for r in na if r["ambHiC"] <= 20]
        if old_cool[0]["n"] != sum(r["n"] for r in below20):
            fails.append("the old cool row n (%d) differs from the new bins below 20 C (%d)" % (old_cool[0]["n"], sum(r["n"] for r in below20)))
        if below20 and (old_cool[0]["lo"] != min(r["lo"] for r in below20) or old_cool[0]["hi"] != max(r["hi"] for r in below20)):
            fails.append("the old cool row extrema differ from min/max over the new bins below 20 C")
    return fails


def build(dm, ambient, raw_loader):
    import compute_summary_arrays as C
    traj = C._battery_temp_traj(dm, raw_loader)
    return C._battery_temp_ranges(dm, traj, ambient)


def splice(block, dry=False, path=None):
    P = path or os.path.join(ROOT, "summary_arrays.json")
    raw = open(P, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    B = copy.deepcopy(A)
    B[KEY] = block
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    st = B["_artifactStamps"][KEY]
    st["computedAt"] = now
    st["generatedAt"] = now
    st["includedInReleaseAt"] = now
    st["computationStatus"] = "computed"
    st["computationStatusNote"] = "M780: recomputed alone by tools/battery_temp_ranges_refresh.py (spec analyses/M780_spec.md Rev 2): whole-range 5 C ambient bins; non-ambient rows unchanged"
    bad = [d for d in walk(A, B) if not d.startswith("/" + KEY) and not d.startswith("/_artifactStamps/" + KEY)]
    if bad:
        raise SystemExit("deep diff outside %s: %s" % (KEY, bad[:4]))
    if A.get(KEY) == block:
        return False
    if not dry:
        with open(P, "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps(B, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", default=None)
    a = ap.parse_args(argv)
    import pandas as pd
    import project_paths as pp
    master = os.path.join(ROOT, "drive_master.csv")
    before = md5(master)
    if before != PINNED_MD5:
        print("battery_temp_ranges_refresh: STOP (drive_master.csv MD5 %s is not the pinned corpus)" % before)
        return 1
    dm = pd.read_csv(master, encoding="utf-8-sig")
    cfg = json.load(open(os.path.join(ROOT, "summary_config.json"), encoding="utf-8"))
    ambient = cfg["ambientByDrive"]

    # master file keys come in two spellings (20260511_185709.csv and 2026-11-20_09-02-32.csv) while the raw files are named "2026-05-11 18-57-09.csv": match on the 14 date-time digits
    rawdir = pp.raw_dir()
    digits = lambda n: "".join(ch for ch in n[:19] if ch.isdigit())[:14]
    index = {}
    for name in os.listdir(rawdir):
        if name.lower().endswith(".csv") and not name.lower().startswith("e4orce"):
            index.setdefault(digits(name), os.path.join(rawdir, name))

    def raw_loader(fn):
        pth = index.get(digits(fn))
        if not pth:
            raise FileNotFoundError(fn)
        with open(pth, "rb") as fh:
            return fh.read()

    unresolved = [fn for fn in dm["file"] if digits(fn) not in index]
    if unresolved:
        print("battery_temp_ranges_refresh: STOP (%d master files have no raw file, e.g. %s)" % (len(unresolved), unresolved[:3]))
        return 1

    block = build(dm, ambient, raw_loader)
    published = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))[KEY]
    fails = consistency(published, block)
    rep = {"milestone": "M780", "spec": "analyses/M780_spec.md Rev 2", "masterMd5": before, "failures": fails,
           "ambientRows": [{k: r[k] for k in ("label", "ambLoC", "ambHiC", "regime", "n", "nDays", "lo", "hi", "medPeak", "p25Peak", "p75Peak")} for r in block if r.get("group") == "ambient"],
           "publishedAmbient": [{k: r[k] for k in ("label", "n", "lo", "hi", "medPeak")} for r in published if r.get("group") == "ambient"]}
    if a.report:
        with open(a.report, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rep, fh, indent=1, ensure_ascii=False)
    if fails:
        print("battery_temp_ranges_refresh: STOP, gates failed: %s" % fails)
        return 1
    assert md5(master) == before
    changed = splice(block, dry=a.dry_run)
    print("battery_temp_ranges_refresh: %s; ambient rows %d" % (("would write" if a.dry_run else "written") if changed else "unchanged", len(rep["ambientRows"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
