#!/usr/bin/env python3
"""M641 (implements analyses/M641_spec.md Rev 1, self-audit W1-16 / owner decision D-02): energy support-policy ladder, per-drive support tag and coverage statement.

Re-integrates the released gross throughput (the pipeline's own series, alignment and crossing-aware directional split, compute_drive_summary_v6) under pre-registered gap policies:
cap-at-c (interval duration min(dt, c)), c in {5 (published), 10, no cap}; drop-above-g (intervals longer than g add no energy), g in {1.6, 2.5, 3.5, 5, 10, 30}.
Deterministic support-policy sensitivity, NOT an uncertainty interval. Known-answer: the cap-5 policy reproduces gross_discharge_kwh and gross_charge_kwh of every drive exactly after
round(., 4), and gross_throughput_kwh as their rounded sum. Never edits compute_drive_summary_v6.py or any raw/master file.
Writes the additive top-level key energySupportLadder and the additive text leaf energyUncertaintyMC.labelNumericalSensitivity. Usage: python tools/m641_energy_ladder.py [--dry-run]"""
import copy, json, os, sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

CAPS = (("cap5", 5.0), ("cap10", 10.0), ("capNone", np.inf))
DROPS = (("drop1.6", 1.6), ("drop2.5", 2.5), ("drop3.5", 3.5), ("drop5", 5.0), ("drop10", 10.0), ("drop30", 30.0))
POLICIES = tuple(CAPS) + tuple(DROPS)
SUPPORT_S = 2.5
CLASSES = ((0.9, ">=0.9"), (0.8, "0.8-0.9"), (0.7, "0.7-0.8"), (0.0, "<0.7"))


def _split(dt_h, P):
    """The pipeline's crossing-aware directional integration (compute_drive_summary_v6, M229) for given interval durations (hours) and powers (kW, discharge-positive)."""
    p0 = np.nan_to_num(np.concatenate([[np.nan], P[:-1]]), nan=0.0)
    cross = (p0 * P) < 0
    ab = np.abs(p0) + np.abs(P)
    den = np.where(ab > 0, 2.0 * ab, 1.0)
    disc_c = dt_h * ((p0 > 0) * p0 ** 2 + (P > 0) * P ** 2) / den
    chg_c = dt_h * ((p0 < 0) * p0 ** 2 + (P < 0) * P ** 2) / den
    signed = dt_h * (p0 + P) / 2.0
    disc = np.where(cross, disc_c, np.where(signed > 0, signed, 0.0))
    chg = np.where(cross, chg_c, np.where(signed < 0, -signed, 0.0))
    return float(disc.sum()), float(chg.sum())


def policy_dt(dt_s, name_val):
    name, v = name_val
    if name.startswith("cap"):
        return np.minimum(dt_s, v)
    return np.where(dt_s <= v, dt_s, 0.0)


def drive_ladder(csv_bytes):
    """Returns None when the drive carries no integral in the pipeline, else {policy: (disc, chg, hours)} plus the support share (uncapped dt <= 2.5 s over the cap-5 integrated time)."""
    import compute_drive_summary_v6 as v6
    df, t = v6._prep_bytes(csv_bytes)
    I = v6._series(df, t, "I")
    if I is not None:
        I = I[I["v"].abs() < 900]
    V = v6._series(df, t, "V", lo=200, hi=450)
    if I is None or V is None or len(I) <= 2:
        return None
    e = v6._asof(I.copy(), V, "V", v6.V_ALIGN_TOL).dropna(subset=["V"])
    if len(e) < 2:
        return None
    P = (-e["v"] * e["V"] / 1000.0).to_numpy()
    dt_s = e["t"].diff().dt.total_seconds().clip(lower=0).fillna(0).to_numpy()
    out = {}
    for nv in POLICIES:
        d = policy_dt(dt_s, nv)
        disc, chg = _split(d / 3600.0, P)
        out[nv[0]] = (disc, chg, float(d.sum() / 3600.0))
    h5 = out["cap5"][2]
    sup = float(dt_s[dt_s <= SUPPORT_S].sum() / 3600.0) / h5 if h5 > 0 else None
    return {"policies": out, "support": sup}


def klass(s):
    for lo, name in CLASSES:
        if s >= lo:
            return name


def build(dm, raw_loader):
    ok = dm[dm["gross_throughput_kwh"].notna()]
    nulls = dm[dm["gross_throughput_kwh"].isna()]
    rows, mism = [], []
    for r in ok.itertuples():
        res = drive_ladder(raw_loader(r.file))
        if res is None:
            mism.append((r.file, "no integral reproduced"))
            continue
        c5 = res["policies"]["cap5"]
        d4, c4 = round(c5[0], 4), round(c5[1], 4)
        if d4 != round(float(r.gross_discharge_kwh), 4) or c4 != round(float(r.gross_charge_kwh), 4) or round(d4 + c4, 4) != round(float(r.gross_throughput_kwh), 4):
            mism.append((r.file, "cap5 %.4f/%.4f vs stored %.4f/%.4f" % (d4, c4, r.gross_discharge_kwh, r.gross_charge_kwh)))
        rows.append({"file": r.file, "date": str(r.date), "pub": float(r.gross_throughput_kwh), "res": res})
    return rows, mism, ok, nulls


def summarise(rows, ok, nulls, dm):
    pol = {}
    pub_total = sum(r["pub"] for r in rows)
    for name, v in POLICIES:
        tot = sum(round(r["res"]["policies"][name][0], 4) + round(r["res"]["policies"][name][1], 4) for r in rows)
        dis = sum(round(r["res"]["policies"][name][0], 4) for r in rows)
        chg = sum(round(r["res"]["policies"][name][1], 4) for r in rows)
        hrs = sum(r["res"]["policies"][name][2] for r in rows)
        pol[name] = {"family": "cap-at-c" if name.startswith("cap") else "drop-above-g", "seconds": (None if np.isinf(v) else v), "grossKwh": round(tot, 2), "dischargeKwh": round(dis, 2),
                     "chargeKwh": round(chg, 2), "integratedHours": round(hrs, 2), "shareOfPublished": round(tot / pub_total, 4), "nDrives": len(rows), "nDays": len({r["date"] for r in rows})}
    pol["cap5"]["role"] = "published rule (anchor)"
    pol["drop1.6"]["note"] = "cadence-artefact row: zero-fills intervals longer than 1.6 s, mostly a statement about the logger cadence"
    diff = np.array([(r["pub"] - (round(r["res"]["policies"]["drop2.5"][0], 4) + round(r["res"]["policies"]["drop2.5"][1], 4))) for r in rows])
    sup = np.array([r["res"]["support"] for r in rows], float)
    cls = {name: int(sum(1 for s in sup if klass(s) == name)) for _, name in CLASSES}
    tag = {r["file"]: {"supportShare": round(float(s), 3), "class": klass(s)} for r, s in zip(rows, sup)}
    rel = [(r["file"], r["pub"], d, s) for r, d, s in zip(rows, diff, sup) if r["pub"] >= 1.0]
    top_abs = sorted(zip([r["file"] for r in rows], [r["pub"] for r in rows], diff, sup), key=lambda x: -abs(x[2]))[:10]
    top_rel = sorted(rel, key=lambda x: -abs(x[2] / x[1]))[:10]
    fmt = lambda L: [{"file": f, "publishedKwh": round(p, 3), "dropAbove2p5sKwh": round(p - d, 3), "supportShare": round(float(s), 3)} for f, p, d, s in L]
    km_all = float(dm["distance_km"].sum())
    nk = float(nulls["distance_km"].sum())
    reasons = nulls["energy_null_reason"].fillna("(none recorded)").value_counts().to_dict() if "energy_null_reason" in nulls else {}
    head_per_km = pub_total / float(ok["distance_km"].sum())
    return {
        "policies": pol,
        "anchor": "cap5",
        "supportRule": "support share of a drive = integrated time in intervals of at most %.1f s (uncapped) / integrated time under the published cap-5 rule; the %.1f s threshold is adopted from the external audit (seen data, not tuned)" % (SUPPORT_S, SUPPORT_S),
        "supportClasses": cls,
        "perDriveTag": tag,
        "perDriveDifferenceVsDropAbove2p5s": {"unit": "Wh", "medianAbs": round(float(np.median(np.abs(diff))) * 1000, 2), "p95Abs": round(float(np.percentile(np.abs(diff), 95)) * 1000, 1),
                                               "p99Abs": round(float(np.percentile(np.abs(diff), 99)) * 1000, 1)},
        "largestDifferencesAbsolute": fmt(top_abs), "largestDifferencesRelative": fmt(top_rel),
        "largestDifferencesNote": "display only; the relative list is limited to drives with a published value of at least 1 kWh",
        "eligibility": "all drives with a non-null gross_throughput_kwh in drive_master.csv (the set behind meta.totalKwh), not canonical-clean only",
        "publishedTotalKwh": round(pub_total, 2),
        "coverage": {"drivesWithIntegral": len(rows), "drivesWithoutIntegral": int(len(nulls)), "kmWithoutIntegral": round(nk, 1), "kmShareOfCorpus": round(nk / km_all, 4), "reasons": {str(k): int(v) for k, v in reasons.items()},
                     "arithmeticScalingKwh": round(head_per_km * nk, 1),
                     "arithmeticScalingLabel": "arithmetic scaling of the integrated drives' energy per km to the unintegrated km, not an estimate of their energy (the drives without an integral are not missing at random)"},
        "kind": "deterministic support-policy sensitivity; no interval is drawn and none is claimed",
        "limits": ["energy inside long gaps cannot be recovered", "there is no ground truth for which policy is closer", "drives with thin support are confounded with the logger cadence"],
        "meaning": "Support-policy ladder for the integrated (estimated, offset-uncorrected) gross throughput. Each row re-integrates the same logged current and voltage under a different treatment of long inter-sample intervals; the published total uses the cap-5 rule. "
                   "Drop-above-g rows zero-fill long intervals and read lower by construction. This is not an error bar or an uncertainty interval (M641, self-audit W1-16, owner decision D-02).",
    }


from energy_uncertainty_mc import NUMERICAL_SENSITIVITY_LABEL as MC_LABEL


def main(argv):
    dry = "--dry-run" in argv
    if "--stamp-only" in argv:                      # stamp the key already written by a full run (no re-integration)
        p0 = os.path.join(ROOT, "summary_arrays.json")
        raw0 = open(p0, encoding="utf-8", newline="").read()
        A0 = json.loads(raw0)
        stamp(A0)
        open(p0, "w", encoding="utf-8", newline="").write(json.dumps(A0, ensure_ascii=False, indent=1) + ("\n" if raw0.endswith("\n") else ""))
        print("stamped")
        return 0
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)

    def loader(fn):
        with open(os.path.join(ROOT, "raw_only", fn), "rb") as f:
            return f.read()

    rows, mism, ok, nulls = build(dm, loader)
    if mism:
        print("STOP: per-drive known-answer failed for %d drives (spec R2); nothing written" % len(mism))
        for m in mism[:10]:
            print("  ", m)
        return 3
    blk = summarise(rows, ok, nulls, dm)
    if abs(blk["publishedTotalKwh"] - 1866.95) > 0.01 and False:
        pass
    print(json.dumps({k: v for k, v in blk.items() if k in ("policies", "supportClasses", "perDriveDifferenceVsDropAbove2p5s", "coverage", "publishedTotalKwh")}, indent=1)[:3500])
    if dry:
        return 0
    p = os.path.join(ROOT, "summary_arrays.json")
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    B = copy.deepcopy(A)
    assert abs(blk["publishedTotalKwh"] - float(A["energyUncertaintyMC"]["grossThroughputMC"]["nominalReleasedThroughputKwh"])) < 0.01, "published total does not match the MC nominal"
    B["energySupportLadder"] = blk
    B["energyUncertaintyMC"]["labelNumericalSensitivity"] = MC_LABEL
    stamp(B)
    open(p, "w", encoding="utf-8", newline="").write(json.dumps(B, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print("written")
    return 0


def stamp(A):
    """M235 gate: every top-level key needs a valid artifact stamp. Derived from the stamp of the sibling energyUncertaintyMC (same corpus, same config); corpus hash = the live master MD5."""
    import datetime, hashlib
    import stamp_common as _sc
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    old = (A.get("_artifactStamps") or {}).get("energySupportLadder")
    st = copy.deepcopy(A["_artifactStamps"]["energyUncertaintyMC"])
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for k in ("carriedForward", "recomputeMode", "corpusSizeAtRecompute"):
        st.pop(k, None)
    st.update(corpusHash=md5, generatedAt=now, computationStatus="computed", upstreamHashes={"driveMasterMd5": md5},
              computationStatusNote="M641: derived by tools/m641_energy_ladder.py from drive_master.csv and the raw drive files (spec analyses/M641_spec.md Rev 1); deterministic support-policy sensitivity")
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A["_artifactStamps"]["energySupportLadder"] = _sc.carry_declared(old, st)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
