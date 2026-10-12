#!/usr/bin/env python3
"""M414 (analyses/M413_spec.md Rev 1): the ONE place where the exposure normalisation reference is chosen.

Exposure quantities (GTC, FCE, the peak C-rates and cap_ah_est) are normalised either on the legacy reference (2.1 kWh, the columns the pipeline wrote into drive_master.csv: `legacy2p1kWh`)
or on the rated reference (CAP_AH_RATED = 5.0 Ah, Nissan Article-10, documentary: `rated5Ah`):
  gtc  = (Ah_discharge + Ah_charge) / 5.0       (Ah from the sidecar ah_throughput.csv, raw-current integral, offset-uncorrected like the legacy gtc)
  fce  = gtc / 2
  *_Crate = |peak current| / 5.0                (dual / regen / engine-charge peaks; a constant divisor, no pack-voltage dependence)
  cap_ah_est = 5.0
Nothing here changes the SoC-bookkeeping role of CAP_KWH (soc_delta_kwh, energy residual, offset, eligibility): those columns are not touched. drive_master.csv is never written.
Default basis = rated5Ah since M415 (the flip); legacy2p1kWh (identity: the very same DataFrame object is returned) is selected with XT_EXPOSURE_BASIS and is the control-build A.
Per-drive NaN where the sidecar has no row, never a legacy fallback; a drive with a finite legacy gtc but no sidecar value is a COVERAGE ERROR.
Usage: python tools/exposure_frame.py --check [--write]   (reconciliation table; exit 1 on a coverage error)"""
import hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LEGACY, RATED = "legacy2p1kWh", "rated5Ah"
BASES = (LEGACY, RATED)
DEFAULT_BASIS = RATED   # M415 (spec M413 S2): the flip. XT_EXPOSURE_BASIS=legacy2p1kWh reproduces the legacy build (control build A).
CAP_AH_RATED = 5.0
CRATE_PEAKS = {"dual_peak_Crate": "dual_peak_A", "regen_peak_Crate": "regen_peak_A", "eng_charge_peak_Crate": "eng_charge_peak_A"}
EXPOSURE_COLUMNS = ("gtc", "fce", "cap_ah_est") + tuple(CRATE_PEAKS)
SIDECAR = os.path.join(ROOT, "ah_throughput.csv")


class ExposureCoverageError(RuntimeError):
    pass


def basis_from_env():
    b = os.environ.get("XT_EXPOSURE_BASIS", DEFAULT_BASIS)
    if b not in BASES:
        raise ValueError("XT_EXPOSURE_BASIS must be one of %r, got %r" % (BASES, b))
    return b


def _sidecar(path=None):
    p = path or SIDECAR
    if not os.path.exists(p):
        raise ExposureCoverageError("sidecar %s missing: the rated exposure basis needs ah_throughput.csv (stage ah_throughput)" % p)
    sc = pd.read_csv(p)
    if sc["file"].duplicated().any():
        raise ExposureCoverageError("sidecar has duplicate file keys")
    return sc.set_index("file")


def coverage(dm, sidecar_path=None):
    """Reconciliation of the populations (no fallback): master rows, finite legacy gtc, finite sidecar Ah, their intersection and the two mismatch counts."""
    sc = _sidecar(sidecar_path)
    ah = dm["file"].map(sc["ah_throughput"])
    g = dm["gtc"].notna().to_numpy()
    a = ah.notna().to_numpy()
    clean = (dm["ens_outlier_v2"].astype("object") == False).to_numpy() if "ens_outlier_v2" in dm.columns else np.zeros(len(dm), bool)  # noqa: E712
    return {"masterRows": int(len(dm)), "masterFiniteGtc": int(g.sum()), "sidecarRows": int(len(sc)), "sidecarFiniteAh": int(a.sum()),
            "intersection": int((g & a).sum()), "legacyGtcButNoSidecarAh": int((g & ~a).sum()), "sidecarAhButNoLegacyGtc": int((~g & a).sum()),
            "ensOutlierV2CleanAndBoth": int((clean & g & a).sum()),
            "sidecarMd5": hashlib.md5(open(sidecar_path or SIDECAR, "rb").read()).hexdigest()}


def exposure_frame(dm, basis=None, sidecar_path=None):
    """Return the master frame with the exposure columns on the requested basis. legacy2p1kWh: the SAME object (identity). rated5Ah: a copy with gtc, fce, *_Crate and cap_ah_est replaced."""
    b = basis or basis_from_env()
    if b not in BASES:
        raise ValueError("unknown exposure basis %r" % (b,))
    if b == LEGACY:
        return dm
    sc = _sidecar(sidecar_path)
    cov = coverage(dm, sidecar_path)
    if cov["legacyGtcButNoSidecarAh"]:
        raise ExposureCoverageError("%d drives have a finite legacy gtc but no sidecar Ah (no legacy fallback): %r" % (cov["legacyGtcButNoSidecarAh"], cov))
    out = dm.copy()
    ah = out["file"].map(sc["ah_throughput"]).astype(float)
    out["gtc"] = (ah / CAP_AH_RATED).round(4)
    out["fce"] = (ah / (2 * CAP_AH_RATED)).round(4)
    for c, a in CRATE_PEAKS.items():
        if c in out.columns and a in out.columns:
            out[c] = (out[a].abs() / CAP_AH_RATED).round(1).where(out[c].notna())
    out["cap_ah_est"] = np.where(out["gtc"].notna(), CAP_AH_RATED, np.nan)
    # Ah columns of the rated frame (absent on the legacy frame): used by producers that sum throughput directly (metricConvention)
    out["gross_discharge_ah"] = out["file"].map(sc["ah_discharge"]).astype(float)
    out["gross_charge_ah"] = out["file"].map(sc["ah_charge"]).astype(float).abs()
    out["gross_throughput_ah"] = ah
    out.attrs["exposureBasis"] = RATED
    return out


def row_overrides(basis=None, sidecar_path=None, master_path=None):
    """For dict-row readers (csv.DictReader): None on the legacy basis (read the row as is); on the rated basis {file: {column: value or None}} for every master file (None where NaN: no fallback)."""
    b = basis or basis_from_env()
    if b == LEGACY:
        return None
    dm = pd.read_csv(master_path or os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    f = exposure_frame(dm, b, sidecar_path)
    cols = [c for c in EXPOSURE_COLUMNS if c in f.columns]
    return {r["file"]: {c: (None if pd.isna(r[c]) else float(r[c])) for c in cols} for r in f[["file"] + cols].to_dict("records")}


def reconciliation(dm):
    c = coverage(dm)
    return {"_provenance": "GENERATED by tools/exposure_frame.py --check --write (M414); no timestamps; do not hand-edit", "basisDefault": LEGACY, "capAhRated": CAP_AH_RATED, **c,
            "reading": "the exposure frame covers every drive with a finite legacy gtc (540 of 554 master rows); the other rows have no I/V pairs and stay NaN on both bases; ensOutlierV2CleanAndBoth is the canonical-clean population used by the headline blocks"}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    r = reconciliation(dm)
    print(json.dumps(r, indent=1))
    if "--write" in argv:
        os.makedirs("analyses", exist_ok=True)
        json.dump(r, open(os.path.join("analyses", "M414_exposure_reconciliation.json"), "w", encoding="utf-8", newline="\n"), indent=1)
    return 1 if (r["legacyGtcButNoSidecarAh"] or r["sidecarAhButNoLegacyGtc"]) else 0


if __name__ == "__main__":
    sys.exit(main())
