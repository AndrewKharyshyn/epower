#!/usr/bin/env python3
"""M582a (spec analyses/M582_spec.md Rev 1): header-derived PID-set class of every master drive. Reads ONLY the header line of each canonical raw CSV (raw/ is read-only) and, for the two named
columns when present, their non-null fraction. Writes the sidecar pid_epoch.csv (one row per master drive, deterministic) and the additive payload block summary_arrays.json['pidEpoch'] (+ stamp).
Class: A = HV Battery Intake Air Temperature present and Motor Power Consumption absent; B = IAT absent and MPC present; C = both absent; D = both present. The class is derived from the header only,
never from the date; it is a post hoc, descriptive proxy for the logger configuration (no cadence effect and no causal mechanism is claimed). Usage: python tools/pid_epoch.py [--dry-run]"""
import argparse, copy, datetime, hashlib, json, os, re, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
IAT = "[BMS] HV Battery Intake Air Temperature (℃)"
MPC = "[VCM] Motor Power Consumption (%)"
Q3_FLOOR_DRIVES, Q3_FLOOR_DAYS = 10, 5
RULE = ("pidSetClass from the raw header only: A = '%s' present and '%s' absent; B = IAT absent and MPC present; C = both absent; D = both present" % (IAT, MPC))
DISCLOSURE = ("post hoc: the class was defined after the 2026-11-03 step had been seen in the data; it is a header-derived projection of the logger configuration, not an identified epoch; "
              "the column-set hash is reported only (too fine to use as a covariate) and the number of columns is descriptive only")
STATEMENT = ("PID-set class is a header-derived, post hoc proxy for the logger configuration; the period contrast is descriptive and confounded with date, regime and drive mix; "
             "no cadence effect and no causal mechanism is claimed")


def raw_name(master_file):
    """Master file name -> raw file name ('YYYYMMDD_HHMMSS.csv' and 'YYYY-MM-DD_HH-MM-SS.csv' both map to 'YYYY-MM-DD HH-MM-SS.csv')."""
    m = re.match(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.csv$", master_file)
    if m:
        return "%s-%s-%s %s-%s-%s.csv" % m.groups()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})\.csv$", master_file)
    if m:
        return "%s %s.csv" % m.groups()
    return None


def classify(iat, mpc):
    return "A" if (iat and not mpc) else ("B" if (mpc and not iat) else ("D" if (iat and mpc) else "C"))


def parse_columns(cols):
    """Pure: header column names -> (nColumns, nNamed, iatPresent, mpcPresent, setHash, nVcm)."""
    named = [c for c in cols if not str(c).startswith("Unnamed")]
    return (len(cols), len(named), IAT in cols, MPC in cols, hashlib.sha256("\n".join(sorted(named)).encode("utf-8")).hexdigest()[:12], sum(1 for c in named if str(c).startswith("[VCM]")))


def read_row(master_file, raw_dir):
    name = raw_name(master_file)
    p = os.path.join(raw_dir, name) if name else None
    if not p or not os.path.isfile(p):
        raise SystemExit("STOP: no raw file for master drive %s (expected %s)" % (master_file, name))
    cols = list(pd.read_csv(p, nrows=0, encoding="utf-8", encoding_errors="replace").columns)
    nc, nn, iat, mpc, h, nv = parse_columns(cols)
    nonnull = {}
    use = [c for c in (IAT, MPC) if c in cols]
    if use:
        t = pd.read_csv(p, usecols=use, encoding="utf-8", encoding_errors="replace", low_memory=False)
        nonnull = {c: float(t[c].notna().mean()) for c in use}
    return {"file": master_file, "nColumns": nc, "nNamedColumns": nn, "iatPresent": bool(iat), "mpcPresent": bool(mpc),
            "iatNonNullFraction": (round(nonnull[IAT], 4) if IAT in nonnull else np.nan), "mpcNonNullFraction": (round(nonnull[MPC], 4) if MPC in nonnull else np.nan),
            "pidSetClass": classify(iat, mpc), "pidSetHash": h, "nVcmColumns": nv}


def build_sidecar(dm, raw_dir):
    return pd.DataFrame([read_row(f, raw_dir) for f in dm["file"]])


def _q(s):
    s = s.dropna()
    return None if len(s) == 0 else {"n": int(len(s)), "median": round(float(s.median()), 3), "q25": round(float(s.quantile(.25)), 3), "q75": round(float(s.quantile(.75)), 3)}


def build_block(dm, side, regime, master_md5):
    """Pure: payload block from the master frame (file, date, time_start, I_sample_period_s), the sidecar and the cadence regime frame (file, regime)."""
    d = dm[["file", "date", "time_start", "I_sample_period_s"]].merge(side[["file", "pidSetClass", "iatNonNullFraction", "mpcNonNullFraction", "pidSetHash"]], on="file").merge(regime[["file", "regime"]], on="file", how="left")
    d["t"] = pd.to_datetime(d["date"].astype(str) + " " + d["time_start"].astype(str), errors="coerce")
    d = d.sort_values(["t", "file"]).reset_index(drop=True)
    d["day"] = d["date"].astype(str).str[:10]
    counts = {}
    for k in "ABCD":
        g = d[d["pidSetClass"] == k]
        counts[k] = {"drives": int(len(g)), "days": int(g["day"].nunique()), "firstDate": (g["day"].min() if len(g) else None), "lastDate": (g["day"].max() if len(g) else None),
                     "periodS": _q(g["I_sample_period_s"]), "iatNonNullFraction": _q(g["iatNonNullFraction"]), "mpcNonNullFraction": _q(g["mpcNonNullFraction"])}
    by_regime = {k: {r: _q(d[(d["pidSetClass"] == k) & (d["regime"] == r)]["I_sample_period_s"]) for r in ("fast", "slow")} for k in "ABCD"}
    runs, cur = [], None
    for r in d.itertuples():
        if cur and cur["cls"] == r.pidSetClass:
            cur["n"] += 1; cur["days"].add(r.day); cur["end"] = r.day; cur["lastFile"] = r.file
        else:
            if cur:
                runs.append(cur)
            cur = {"cls": r.pidSetClass, "n": 1, "days": {r.day}, "start": r.day, "end": r.day, "firstFile": r.file, "lastFile": r.file}
    if cur:
        runs.append(cur)
    for x in runs:
        x["days"] = len(x["days"])
    last_b = next((x for x in reversed(runs) if x["cls"] == "B"), None)
    final_b = bool(runs and runs[-1]["cls"] == "B")
    both = []
    for day, g in d.groupby("day"):
        if set(g["pidSetClass"]) >= {"A", "B"}:
            both.append({"day": day, **{k: _q(g[g["pidSetClass"] == k]["I_sample_period_s"]) or {"n": int((g["pidSetClass"] == k).sum())} for k in ("A", "B")}})
    ready = bool(final_b and last_b["n"] >= Q3_FLOOR_DRIVES and last_b["days"] >= Q3_FLOOR_DAYS)
    rare = {k: [{"file": r.file, "day": r.day} for r in d[d["pidSetClass"] == k].itertuples()] for k in "CD"}
    early_b = [{"file": r.file, "day": r.day} for r in d[d["pidSetClass"] == "B"].itertuples() if not (final_b and r.file >= last_b["firstFile"] and r.t >= d[d["file"] == last_b["firstFile"]]["t"].iloc[0])]
    return {"rule": RULE, "disclosure": DISCLOSURE, "statement": STATEMENT, "nDrives": int(len(d)), "masterMd5": master_md5,
            "counts": counts, "periodByClassAndRegime": by_regime, "earlyClassB": early_b, "classC": rare["C"], "classD": rare["D"], "distinctColumnSets": int(d["pidSetHash"].nunique()),
            "runs": [{k: v for k, v in x.items() if k != "firstFile"} for x in runs[-12:]],
            "withinDayContrast": {"note": "days that contain both a class A and a class B drive; descriptive, no interval, no inference", "days": both},
            "q3Readiness": {"indicator": "pidSetClass B, final consecutive run in time order", "runDrives": (last_b["n"] if final_b else 0), "runDays": (last_b["days"] if final_b else 0),
                            "floorDrives": Q3_FLOOR_DRIVES, "floorDays": Q3_FLOOR_DAYS, "status": "testable under M577 Rev 2" if ready else "not identified (floors not met)"},
            "source": "raw CSV headers via tools/pid_epoch.py; sidecar pid_epoch.csv; spec analyses/M582_spec.md Rev 1"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); a = ap.parse_args()
    os.chdir(ROOT)
    raw_dir = os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    side = build_sidecar(dm, raw_dir)
    reg = pd.read_csv("cadence_regime.csv")
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    blk = build_block(dm, side, reg, md5)
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    new = copy.deepcopy(A)
    new["pidEpoch"] = blk
    old_st = (A.get("_artifactStamps") or {}).get("pidEpoch")
    if A.get("pidEpoch") == blk and old_st and old_st.get("corpusHash") == md5 and old_st.get("includedInReleaseAt") == old_st.get("generatedAt") == old_st.get("computedAt"):
        new["_artifactStamps"]["pidEpoch"] = old_st
    else:
        st = copy.deepcopy(A["_artifactStamps"]["loggerCadence"])
        st.update(corpusHash=md5, generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
                  computationStatusNote="M582a: derived by tools/pid_epoch.py from the raw CSV headers (header-only read, plus the non-null fraction of two named columns); descriptive, additive, post hoc; no published value recomputed; not M299-reproducible.",
                  upstreamHashes={"driveMasterMd5": md5})
        st.pop("carriedForward", None)
        st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]      # every top-level key carries a coherent stamp (M419)
        new["_artifactStamps"]["pidEpoch"] = st
    chk = copy.deepcopy(new); chk.pop("pidEpoch"); chk["_artifactStamps"].pop("pidEpoch")
    base = copy.deepcopy(A); base.pop("pidEpoch", None); base["_artifactStamps"].pop("pidEpoch", None)
    assert chk == base, "only the pidEpoch key and its stamp may change"
    summ = {"counts": {k: v["drives"] for k, v in blk["counts"].items()}, "q3": blk["q3Readiness"]["status"]}
    if a.dry_run:
        print(json.dumps(summ))
        return
    side.to_csv("pid_epoch.csv", index=False, lineterminator="\n")
    if new != A:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1))
    print(json.dumps(summ))


if __name__ == "__main__":
    main()
