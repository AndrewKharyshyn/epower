"""M414 known-answer tests for tools/exposure_frame.py (spec analyses/M413_spec.md Rev 1): the legacy basis is the identity, the rated basis reproduces the capacityBasis.exposure totals,
the coverage gate has no legacy fallback, and the reconciliation table matches the committed file."""
import json, os, shutil, sys, tempfile
import numpy as np
import pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import exposure_frame as XF

dm = pd.read_csv("drive_master.csv", low_memory=False)
os.environ.pop("XT_EXPOSURE_BASIS", None)

# 1. default basis is the rated one since M415 (the flip); the legacy basis is the very same object (control build A), and an unknown basis is refused
os.environ.pop("XT_EXPOSURE_BASIS", None)
assert XF.DEFAULT_BASIS == "rated5Ah" and XF.basis_from_env() == "rated5Ah"
assert XF.exposure_frame(dm, "legacy2p1kWh") is dm
os.environ["XT_EXPOSURE_BASIS"] = "legacy2p1kWh"
assert XF.exposure_frame(dm) is dm and XF.row_overrides() is None
os.environ.pop("XT_EXPOSURE_BASIS", None)
try:
    XF.exposure_frame(dm, "nonsense"); raise SystemExit("unknown basis accepted")
except ValueError:
    pass
os.environ["XT_EXPOSURE_BASIS"] = "rated5Ah"
assert XF.basis_from_env() == "rated5Ah"
os.environ["XT_EXPOSURE_BASIS"] = "bad"
try:
    XF.basis_from_env(); raise SystemExit("bad env accepted")
except ValueError:
    pass
os.environ.pop("XT_EXPOSURE_BASIS", None)

# 2. coverage: master finite gtc and sidecar finite Ah are the same set (no fallback needed), and the reconciliation file is current
cov = XF.coverage(dm)
assert cov["legacyGtcButNoSidecarAh"] == 0 and cov["sidecarAhButNoLegacyGtc"] == 0 and cov["intersection"] == cov["masterFiniteGtc"] == cov["sidecarFiniteAh"], cov
rec = json.load(open("analyses/M414_exposure_reconciliation.json", encoding="utf-8")) if os.path.exists("analyses/M414_exposure_reconciliation.json") else None
if rec is not None:
    assert all(rec[k] == cov[k] for k in ("masterRows", "masterFiniteGtc", "sidecarFiniteAh", "intersection", "ensOutlierV2CleanAndBoth")), (rec, cov)

# 3. rated frame: definitions
rf = XF.exposure_frame(dm, "rated5Ah")
assert rf is not dm and rf.attrs["exposureBasis"] == "rated5Ah" and list(rf.columns) == list(dm.columns) + ["gross_discharge_ah", "gross_charge_ah", "gross_throughput_ah"] and len(rf) == len(dm)
sc = pd.read_csv("ah_throughput.csv").set_index("file")
ah = dm["file"].map(sc["ah_throughput"])
fin = ah.notna().to_numpy()
assert np.allclose(rf.loc[fin, "gtc"], (ah[fin] / 5.0).round(4), atol=1e-12, rtol=0)
assert np.allclose(rf.loc[fin, "fce"], (ah[fin] / 10.0).round(4), atol=1e-12, rtol=0)
assert (rf.loc[fin, "cap_ah_est"] == 5.0).all() and rf.loc[~fin, ["gtc", "fce", "cap_ah_est"]].isna().all().all()
for c, a in XF.CRATE_PEAKS.items():
    m = dm[c].notna().to_numpy()
    assert np.allclose(rf.loc[m, c], (dm.loc[m, a].abs() / 5.0).round(1), atol=1e-12, rtol=0), c
    assert rf.loc[~m, c].isna().all()
# the master itself is untouched (columns other than the exposure ones, and the original frame)
other = [c for c in dm.columns if c not in XF.EXPOSURE_COLUMNS]
assert np.allclose(rf.loc[fin, "gross_throughput_ah"], ah[fin]) and np.allclose(rf.loc[fin, "gross_discharge_ah"] + rf.loc[fin, "gross_charge_ah"], ah[fin], atol=1e-6)
assert rf[other].equals(dm[other])
assert dm["gtc"].equals(pd.read_csv("drive_master.csv", low_memory=False)["gtc"])

# 4. rated totals reproduce capacityBasis.exposure (script-written payload) on the canonical-clean population
a = json.load(open("summary_arrays.json", encoding="utf-8"))
ex = a["capacityBasis"]["exposure"]
clean = (dm["ens_outlier_v2"].astype("object") == False).to_numpy() & fin  # noqa: E712
assert abs(ah[clean].sum() / 5.0 - ex["chargeReferences"]["rated_5.0Ah"]["grossTurnoverAhPerRef"]) < 0.06
assert abs(rf.loc[clean, "gtc"].sum() - ex["chargeReferences"]["rated_5.0Ah"]["grossTurnoverAhPerRef"]) < 0.06
assert abs(dm.loc[clean, "gtc"].sum() - ex["energyReferences"]["legacy_2.1kWh"]["grossTurnoverGTC"]) < 0.06
ratio = rf.loc[fin, "gtc"].sum() / dm.loc[fin, "gtc"].sum()
assert 1.10 < ratio < 1.20

# 5. coverage gate: a drive with a finite legacy gtc and no sidecar Ah is an error (never a legacy fallback)
tmp = tempfile.mkdtemp()
try:
    p = os.path.join(tmp, "ah.csv")
    s2 = pd.read_csv("ah_throughput.csv")
    s2.loc[s2["ah_throughput"].notna().idxmax(), "ah_throughput"] = np.nan
    s2.to_csv(p, index=False)
    try:
        XF.exposure_frame(dm, "rated5Ah", sidecar_path=p); raise SystemExit("coverage error not raised")
    except XF.ExposureCoverageError:
        pass
    s3 = pd.read_csv("ah_throughput.csv")
    s3 = pd.concat([s3, s3.iloc[[0]]])
    s3.to_csv(p, index=False)
    try:
        XF.exposure_frame(dm, "rated5Ah", sidecar_path=p); raise SystemExit("duplicate keys accepted")
    except XF.ExposureCoverageError:
        pass
    try:
        XF.exposure_frame(dm, "rated5Ah", sidecar_path=os.path.join(tmp, "missing.csv")); raise SystemExit("missing sidecar accepted")
    except XF.ExposureCoverageError:
        pass
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 6. dict-row overrides: None on the legacy basis; on the rated basis every master file is present, NaN as None (no fallback)
assert XF.row_overrides("legacy2p1kWh") is None
ov = XF.row_overrides("rated5Ah")
assert set(ov) == set(dm["file"]) and all(ov[f]["gtc"] is None for f in dm.loc[~fin, "file"])
f0 = dm.loc[fin, "file"].iloc[0]
assert abs(ov[f0]["gtc"] - float(rf.loc[rf["file"] == f0, "gtc"].iloc[0])) < 1e-12 and ov[f0]["cap_ah_est"] == 5.0
print("OK test_exposure_frame")
