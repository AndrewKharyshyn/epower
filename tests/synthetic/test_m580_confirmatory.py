"""M580 (analyses/M580_spec.md Rev 1) known-answer tests: caveat fields of the M574 confirmatory block, the looks ledger (idempotent), the terminal evaluation (primary, fallback, frozen), the frozen pre-step fit,
and the tie-out of the real master to the blind audit analyses/M578_audit/m574_confirmatory.json."""
import json, os, sys, tempfile
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import m573_cell_spread_step as M


def synth(seed=1, n_post_days=6, per_day=4, cold_days=2, shift=3.0):
    """Pre-step drives 2026-07-01..2026-09-29 (T 15-40), post-cutoff drives from 2026-10-18; the first cold_days post days are colder than the pre-step minimum."""
    rng = np.random.default_rng(seed)
    rows = []
    for d in pd.date_range("2026-07-01", "2026-09-29", freq="2D"):
        for _ in range(3):
            T = rng.uniform(15, 40)
            rows.append({"date": d, "day": str(d.date()), "T": T, "I": rng.uniform(60, 140), "soc": rng.uniform(40, 80)})
    for k in range(n_post_days):
        d = pd.Timestamp("2026-10-18") + pd.Timedelta(days=k)
        for _ in range(per_day):
            T = rng.uniform(3, 10) if k < cold_days else rng.uniform(16, 38)
            rows.append({"date": d, "day": str(d.date()), "T": T, "I": rng.uniform(60, 140), "soc": rng.uniform(40, 80)})
    df = pd.DataFrame(rows)
    df["months"] = (df["date"] - df["date"].min()).dt.days / 30.4375
    df["y"] = 20 + 0.1 * df["T"] + 0.02 * df["I"] + 0.05 * df["soc"] + np.where(df["date"] >= pd.Timestamp("2026-10-01"), shift, 0.0) + rng.normal(0, 1.0, len(df))
    return df


# ---- fields of the evaluated block
dd = synth()
c = M.confirmatory(dd)
assert c["status"] == "evaluated" and c["nDrivesAfterCutoff"] == 24 and c["nDaysAfterCutoff"] == 6
post = dd[dd["date"] > pd.Timestamp(M.CUTOFF)]
pre = dd[dd["date"] < pd.Timestamp(M.STEP_DATE)]
assert c["preStepTRange"]["min"] == round(float(pre["T"].min()), 2) and c["preStepTRange"]["max"] == round(float(pre["T"].max()), 2) and c["preStepTRange"]["nFitDrives"] == len(pre)
assert abs(c["preStepTRange"]["p5"] - round(float(np.percentile(pre["T"], 5)), 2)) < 1e-9
assert c["nBelowPreStepTmin"] == int((post["T"] < pre["T"].min()).sum()) == 8 and c["nAbovePreStepTmax"] == 0
ir = c["inRangeSensitivity"]
assert ir["n"] == 16 and ir["days"] == 4 and ir["meetsSupportFloor"] is False and ir["label"] == "post hoc; below the floor"
assert ir["meanResidualMv"] is not None and len(ir["meanResidualCi95"]) == 2
assert c["predictionMet"] is (c["outcome"] == "raised level, flat slope")
assert isinstance(c["preStepFitHash"], str) and len(c["preStepFitHash"]) == 64 and M.confirmatory(dd)["preStepFitHash"] == c["preStepFitHash"]
# existing leaves are unchanged by the additive fields
base_keys = {"cutoff", "stepDate", "minDrives", "minDays", "nDrivesAfterCutoff", "nDaysAfterCutoff", "status", "meanResidualMv", "meanResidualCi95", "postStepSlope", "outcome", "preStepModel"}
assert base_keys <= set(c)
# a support floor that the in-range subset meets: the label changes
c2 = M.confirmatory(synth(n_post_days=8, per_day=8), min_n=10, min_days=5)      # 6 in-range days x 8 drives
assert c2["inRangeSensitivity"]["meetsSupportFloor"] is True and c2["inRangeSensitivity"]["label"] == "post hoc sensitivity"
# awaiting data keeps the old shape (no new number)
assert M.confirmatory(synth(n_post_days=2))["status"] == "awaiting data"

# ---- looks ledger: idempotent per master MD5, increments for a new master
with tempfile.TemporaryDirectory() as tmp:
    lp = os.path.join(tmp, "looks.json")
    sp = os.path.join(tmp, "spec.md"); open(sp, "w", encoding="utf-8").write("spec")
    a1, led1 = M.apply_looks(c, dd, "md5-A", path=lp, spec_path=sp)
    assert a1["evaluationNumber"] == 1 and a1["lookLabel"].startswith("first evaluation at the minimum support") is False      # 6 days != minDays 5: an interim look label
    assert a1["lookLabel"] == "interim look 1; not the terminal evaluation"
    a1b, led1b = M.apply_looks(c, dd, "md5-A", path=lp, spec_path=sp)
    assert a1b["evaluationNumber"] == 1 and len(led1b["looks"]) == 1                                                            # same master: not a second look
    assert a1["terminalEvaluation"]["status"] == "not reached" and a1["terminalEvaluation"]["nInRangeDrives"] == 16
    a2, led2 = M.apply_looks(c, dd, "md5-B", path=lp, spec_path=sp)
    assert a2["evaluationNumber"] == 2 and len(led2["looks"]) == 2
    # first look at exactly the minimum support is labelled as such
    dd5 = synth(n_post_days=5)
    c5 = M.confirmatory(dd5)
    a5, _ = M.apply_looks(c5, dd5, "md5-first", path=os.path.join(tmp, "l5.json"), spec_path=sp)
    assert a5["lookLabel"] == "first evaluation at the minimum support (5 days)"
    # frozen pre-step fit: a changed fit STOPs
    led = json.load(open(lp, encoding="utf-8")); led["preStepFit"]["hash"] = "0" * 64; json.dump(led, open(lp, "w", encoding="utf-8"))
    try:
        M.apply_looks(c, dd, "md5-C", path=lp, spec_path=sp)
    except SystemExit as e:
        assert "pre-step fit changed" in str(e)
    else:
        raise AssertionError("a changed pre-step fit must STOP")

# ---- terminal evaluation: primary point, frozen afterwards
big = synth(n_post_days=14, per_day=4, cold_days=2)          # in-range drives: 12 days x 4 = 48 >= 20 on >= 10 days
D = M.terminal_day(big)
inr = big[(big["date"] > pd.Timestamp(M.CUTOFF)) & (big["T"] >= big[big["date"] < pd.Timestamp(M.STEP_DATE)]["T"].min())]
assert D is not None and D == "2026-10-29"                  # first in-range day index 2 (Oct 20) .. 10th in-range day is Oct 29, 40 drives >= 20
with tempfile.TemporaryDirectory() as tmp:
    lp = os.path.join(tmp, "looks.json"); sp = os.path.join(tmp, "spec.md"); open(sp, "w", encoding="utf-8").write("spec")
    cb = M.confirmatory(big)
    t1, led = M.apply_looks(cb, big, "m1", path=lp, spec_path=sp)
    T1 = t1["terminalEvaluation"]
    assert T1["frozen"] is True and T1["dataThrough"] == "2026-10-29" and T1["how"] == "primary" and t1["lookLabel"].startswith("terminal evaluation")
    assert T1["n"] == int(((big["date"] > pd.Timestamp(M.CUTOFF)) & (big["date"] <= pd.Timestamp("2026-10-29"))).sum())
    # a later look keeps the frozen terminal record unchanged and is descriptive
    bigger = pd.concat([big, synth(seed=9, n_post_days=1).assign(date=pd.Timestamp("2026-12-01"), day="2026-12-01").iloc[-4:]]).reset_index(drop=True)
    t2, led2 = M.apply_looks(M.confirmatory(bigger), bigger, "m2", path=lp, spec_path=sp)
    assert t2["terminalEvaluation"] == T1 and t2["evaluationNumber"] == 2 and t2["lookLabel"] == "after the terminal evaluation; descriptive"

# ---- fallback: no in-range coverage, data through the fallback date
cold = synth(n_post_days=6, per_day=4, cold_days=6)           # every post drive is below the pre-step range
assert M.terminal_day(cold) is None
late = pd.concat([cold, cold.iloc[-4:].assign(date=pd.Timestamp("2027-02-02"), day="2027-02-02")]).reset_index(drop=True)
with tempfile.TemporaryDirectory() as tmp:
    lp = os.path.join(tmp, "looks.json"); sp = os.path.join(tmp, "spec.md"); open(sp, "w", encoding="utf-8").write("spec")
    tf, _ = M.apply_looks(M.confirmatory(late), late, "mf", path=lp, spec_path=sp)
    assert tf["terminalEvaluation"]["how"] == "fallback" and tf["terminalEvaluation"]["dataThrough"] == "2027-01-31"
    assert tf["terminalEvaluation"]["n"] == int(((late["date"] > pd.Timestamp(M.CUTOFF)) & (late["date"] <= pd.Timestamp("2027-01-31"))).sum())

# ---- tie-out to the blind audit on the real master (M578 master, 632 drives)
aud = json.load(open(os.path.join(ROOT, "analyses", "M578_audit", "m574_confirmatory.json"), encoding="utf-8"))
dm = pd.read_csv("drive_master.csv", low_memory=False)
import hashlib
if hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest() == "1574a8156a36c6ea4ea1dfdaafc7cc72":
    d = M.build_frame(dm)
    real = d.dropna(subset=["soc", "socr", "lrest"]).copy()
    rc = M.confirmatory(real)
    assert rc["nDrivesAfterCutoff"] == aud["post"]["n"] and rc["nDaysAfterCutoff"] == aud["post"]["days"] and rc["preStepModel"]["n"] == aud["pre_n"]
    assert abs(rc["meanResidualMv"] - aud["resid"]["mean"]) < 1e-3 and all(abs(x - y) < 1e-3 for x, y in zip(rc["meanResidualCi95"], aud["resid"]["ci"]))
    assert abs(rc["postStepSlope"]["est"] - aud["slope"]["b"]) < 1e-3 and rc["postStepSlope"]["n"] == aud["slope"]["n"] and rc["postStepSlope"]["G"] == aud["slope"]["G"]
    assert rc["preStepTRange"]["min"] == aud["Tmin"] and abs(rc["preStepTRange"]["p5"] - aud["T_p5"]) < 0.011 and rc["preStepTRange"]["max"] == aud["Tmax_pre"]
    assert rc["nBelowPreStepTmin"] == aud["post_T_below_min"] and rc["predictionMet"] is aud["labels_fit"]["raised_flat"] and rc["outcome"] == "continued rise"
    r2 = aud["resid_inrange"]
    assert rc["inRangeSensitivity"]["n"] == r2["n"] and rc["inRangeSensitivity"]["days"] == r2["G"] and abs(rc["inRangeSensitivity"]["meanResidualMv"] - r2["mean"]) < 1e-3
    assert all(abs(x - y) < 1e-3 for x, y in zip(rc["inRangeSensitivity"]["meanResidualCi95"], r2["ci"]))
print("test_m580_confirmatory: OK")
