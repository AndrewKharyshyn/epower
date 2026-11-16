"""M698 (spec analyses/M695_spec.md section 14 condition 4): concordance of the VCM vehicle speed and the standard OBD vehicle speed on drives that log BOTH PIDs.
Run BEFORE any OBD-stratum episode result. Thresholds frozen in the spec: zero-state agreement >= 0.95 and median lag <= 1 sample."""
import hashlib, json, os, sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import reverse_mask as R

OUT = os.path.join(ROOT, "analyses", "M698_speed_concordance.json")
ZERO_AGREE_MIN = 0.95
LAG_MAX = 1


def onsets(ts, v):
    return ts[1:][(v[1:] > 0) & (v[:-1] == 0)]


def drive_concordance(csv_bytes, tau0):
    a = R.aligned(csv_bytes, "vcm")
    b = R.aligned(csv_bytes, "obd")
    if a is None or b is None or len(a["ts"]) != len(b["ts"]):
        return None
    ok = np.isfinite(a["v"]) & np.isfinite(b["v"])
    if ok.sum() < 50:
        return None
    vv, vo = a["v"][ok], b["v"][ok]
    d = vo - vv
    zero = float(np.mean((vv == 0) == (vo == 0)))
    lags = {}
    for k in range(-3, 4):
        x, y = (vv[: len(vv) - k], vo[k:]) if k >= 0 else (vv[-k:], vo[: len(vo) + k])
        if len(x) > 20 and np.std(x) > 0 and np.std(y) > 0:
            lags[k] = float(np.corrcoef(x, y)[0, 1])
    lag = max(lags, key=lags.get) if lags else None
    on_v, on_o = onsets(a["ts"][ok], vv), onsets(b["ts"][ok], vo)
    dd = []
    for t in on_v:
        if len(on_o):
            dd.append(float(on_o[np.argmin(np.abs(on_o - t))] - t))
    la = R.analyse(a, tau0, detail=True)
    lb = R.analyse(b, tau0, detail=True)
    same = float(np.mean(la["labels"] == lb["labels"])) if ("labels" in la and "labels" in lb and len(la["labels"]) == len(lb["labels"])) else None
    return {"nSamples": int(ok.sum()), "medianAbsDiffKmh": float(np.median(np.abs(d))), "shareWithin1Kmh": float(np.mean(np.abs(d) <= 1)), "zeroStateAgreement": zero, "lagSamples": lag,
            "medianAbsOnsetDiffS": float(np.median(np.abs(dd))) if dd else None, "labelConcordance": same, "episodesVcm": len(la["episodes"]), "episodesObd": len(lb["episodes"])}


def main():
    import ah_throughput as AH
    tau0 = R.load_tau0()
    m = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), usecols=["file", "date", "ens_outlier_v2", "ens_invalid"], low_memory=False)
    clean = ~(m["ens_outlier_v2"].map(lambda x: x is True or x == "True") | m["ens_invalid"].map(lambda x: x is True or x == "True"))
    m = m[clean].reset_index(drop=True)
    loader = AH.raw_loader(os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    rows = []
    for _, r in m.iterrows():
        by = loader(r["file"])
        if by is None:
            continue
        c = drive_concordance(by, tau0)
        if c:
            rows.append({**c, "file": r["file"], "date": str(r["date"])[:10]})
    out = {"spec": "analyses/M695_spec.md section 14 condition 4", "purpose": "concordance of VCM and OBD vehicle speed on drives that log both PIDs, run before any OBD-stratum episode result",
           "nDrivesWithBoth": len(rows), "nDays": len({r["date"] for r in rows}), "thresholds": {"zeroStateAgreementMin": ZERO_AGREE_MIN, "medianLagSamplesMax": LAG_MAX}}
    if rows:
        zs = [r["zeroStateAgreement"] for r in rows]
        lg = [abs(r["lagSamples"]) for r in rows if r["lagSamples"] is not None]
        ons = [r["medianAbsOnsetDiffS"] for r in rows if r["medianAbsOnsetDiffS"] is not None]
        lc = [r["labelConcordance"] for r in rows if r["labelConcordance"] is not None]
        out["corpus"] = {"medianZeroStateAgreement": round(float(np.median(zs)), 4), "medianAbsLagSamples": float(np.median(lg)) if lg else None,
                         "medianAbsDiffKmh": round(float(np.median([r["medianAbsDiffKmh"] for r in rows])), 3), "medianShareWithin1Kmh": round(float(np.median([r["shareWithin1Kmh"] for r in rows])), 4),
                         "medianAbsOnsetDiffS": round(float(np.median(ons)), 3) if ons else None, "medianLabelConcordance": round(float(np.median(lc)), 4) if lc else None,
                         "episodesVcmTotal": int(sum(r["episodesVcm"] for r in rows)), "episodesObdTotal": int(sum(r["episodesObd"] for r in rows))}
        c = out["corpus"]
        out["status"] = "concordant" if (c["medianZeroStateAgreement"] >= ZERO_AGREE_MIN and (c["medianAbsLagSamples"] or 0) <= LAG_MAX) else "descriptive only, speed source not concordant"
    else:
        out["status"] = "unvalidated against VCM (no drive logs both PIDs)"
    out["limits"] = "the drives that log both PIDs are the earlier logger configuration; the OBD-only drives are later (a different configuration), so concordance on the early drives is evidence about the PID timing path, not a proof for the later drives"
    out["scriptSha256"] = hashlib.sha256(open(__file__, "rb").read()).hexdigest()
    json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: out.get(k) for k in ("nDrivesWithBoth", "nDays", "corpus", "status")}))


if __name__ == "__main__":
    main()
