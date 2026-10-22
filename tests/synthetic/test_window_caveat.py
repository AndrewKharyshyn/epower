"""M485 known-answer tests (analyses/M485_spec.md Rev 3): month-end cutoff rule, support rule, pinned formula, noNewData, sign rule, leave-last-k rows, daily-grid counts, the generated clause, reconciliation stop, additive splice, sentence.
Run: python tests/synthetic/test_window_caveat.py"""
import copy, os, re, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import degradation_trends as DT       # noqa: E402
import window_caveat as W             # noqa: E402

YC = "cell_spread_loaded_p95_mv"


def ok(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + name + ((" -- " + str(detail)) if not cond else ""))
    if not cond:
        ok.bad += 1


ok.bad = 0
TS = pd.Timestamp


def corpus(days, per_day=3, seed=1, slope=0.5, noise=0.6, flag="bool", ts=False, sparse_i_before=None):
    """Constructed master: one row per drive; days = list of Timestamps; y = 20 + slope * months + 0.05 T + 0.01 I + noise."""
    r = np.random.default_rng(seed)
    rows = []
    t0 = min(days)
    for d in days:
        for k in range(per_day):
            T, I = 25 + r.normal(0, 5), 150 + r.normal(0, 20)
            mo = (d - t0).days / DT.MONTH_DAYS
            dt = d + pd.Timedelta(hours=7 + 3 * k, minutes=13) if ts else d
            rows.append({"file": "%s_%d" % (d.date(), k), "date": str(dt) if ts else str(d.date()), "ens_outlier_v2": (False if flag == "bool" else "False"),
                         YC: 20 + slope * mo + 0.05 * T + 0.01 * I + r.normal(0, noise), "T_pack_mean_avg": T, "peak_I_discharge": I})
    dm = pd.DataFrame(rows)
    if sparse_i_before is not None:
        m = pd.to_datetime(dm["date"]).dt.normalize() <= TS(sparse_i_before)
        idx = dm.index[m]
        dm.loc[idx[: int(0.8 * len(idx))], "peak_I_discharge"] = np.nan
    return dm


alldays = list(pd.date_range("2026-05-15", "2026-10-17", freq="D"))

# (1) cutoff rule -------------------------------------------------------------------------------------------------------------------------------------------------
iso = lambda L: [str(c.date()) for c in L]
ok("(1) month-ends from the first to the month before the last, plus the last day", iso(W.cutoffs_for(TS("2026-05-15"), TS("2026-10-17"))) == ["2026-05-31", "2026-06-30", "2026-07-31", "2026-08-31", "2026-09-30", "2026-10-17"])
ok("(1) leap day", iso(W.cutoffs_for(TS("2028-02-10"), TS("2028-03-15"))) == ["2028-02-29", "2028-03-15"])
ok("(1) a last day that is a month end appears once", iso(W.cutoffs_for(TS("2026-05-15"), TS("2026-08-31"))) == ["2026-05-31", "2026-06-30", "2026-07-31", "2026-08-31"])
ok("(1) single-month window", iso(W.cutoffs_for(TS("2026-05-03"), TS("2026-05-20"))) == ["2026-05-20"])
ok("(1) year change", iso(W.cutoffs_for(TS("2026-11-20"), TS("2027-01-10"))) == ["2026-11-30", "2026-12-31", "2027-01-10"])

# (2) final row = the released model; counts from the rows ------------------------------------------------------------------------------------------------------
dm = corpus(alldays)
b = W.build(dm)
d = DT._prep(dm, YC, icol="peak_I_discharge")
co = DT._cluster_ols(d, covars=("T", "I"))
last = b["cutoffs"][-1]
ok("(2) the final cutoff row equals the released cluster-robust OLS (slope, interval, n, days) and reconcile() passes",
   (last["slope"], last["ci95"], last["nDrives"], last["nDays"]) == (co["slope"], co["ci95"], co["nObs"], co["nDays"]) and W.reconcile(b, co) is True)
ok("(2) summary counts follow the rows", b["summary"]["nEvaluableCutoffs"] == sum(r["status"] == "ok" for r in b["cutoffs"]) and b["summary"]["nIntervalExcludesZero"] == sum(bool(r.get("excludesZero")) for r in b["cutoffs"] if r["status"] == "ok"))
ok("(2) window facts: first and last eligible day, span, drives, days", b["window"]["firstDay"] == "2026-05-15" and b["window"]["lastDay"] == "2026-10-17" and b["window"]["spanDays"] == 155
   and b["window"]["spanMonths"] == round(155 / 30.4375, 1) and b["window"]["nDrives"] == 3 * len(alldays) and b["window"]["nDays"] == len(alldays))
try:
    W.reconcile(b, dict(co, slope=co["slope"] + 0.01))
    stopped = False
except SystemExit:
    stopped = True
ok("(2) a mismatch with the released fit stops the stage", stopped)

# (3) pure summary: constructed sign pattern, zero sign, exclusions ------------------------------------------------------------------------------------------------
mk = lambda c, sg, ex=False, st="ok": {"cutoff": c, "status": st, "sign": sg, "excludesZero": ex}
rows = [mk("a", 1), mk("b", -1), mk("c", 0), mk("d", -1), mk("e", 1, True), {"cutoff": "x", "status": "noNewData"}, {"cutoff": "y", "status": "notEvaluable"}]
s = W.summarize_rows(rows, "e")
ok("(3) sign changes counted over evaluable rows only; an exactly-zero estimate is no change: 1,-1,0,-1,1 -> 2 changes", s["nSignChanges"] == 2 and s["nEvaluableCutoffs"] == 5 and s["nIntervalExcludesZero"] == 1, s)
ok("(3) first cutoff excluding zero and whether it is the last day", s["firstCutoffExcludingZero"] == "e" and s["firstCutoffExcludingZeroIsLastDay"] is True
   and W.summarize_rows([mk("a", 1, True), mk("b", 1)], "b")["firstCutoffExcludingZeroIsLastDay"] is False and W.summarize_rows([mk("a", 1)], "a")["firstCutoffExcludingZero"] is None)
ok("(3) no sign change for an all-positive series", W.summarize_rows([mk("a", 1), mk("b", 1), mk("c", 1)], "c")["nSignChanges"] == 0)

# (4) support rule ------------------------------------------------------------------------------------------------------------------------------------------------
thin = corpus(list(pd.date_range("2026-05-28", "2026-05-31", freq="D")) + list(pd.date_range("2026-06-01", "2026-09-10", freq="D")), per_day=3)
bt = W.build(thin)
first = bt["cutoffs"][0]
ok("(4) a thin first cutoff (4 days, 12 drives) is not evaluable (support) and is outside m", first["status"] == "notEvaluable" and first["reason"] == "support" and bt["summary"]["nEvaluableCutoffs"] == len(bt["cutoffs"]) - 1, first)

# (5) pinned formula: sparse covariate in the early subset ---------------------------------------------------------------------------------------------------------
sp = corpus(alldays, sparse_i_before="2026-06-30")
bs = W.build(sp)
ok("(5) a covariate present in under half of an early subset makes the row not evaluable (covariate support) instead of fitting another formula",
   bs["cutoffs"][0]["status"] == "notEvaluable" and bs["cutoffs"][0]["reason"] == "covariate support" and bs["cutoffs"][-1]["status"] == "ok", [(r["cutoff"], r["status"], r.get("reason")) for r in bs["cutoffs"]])

# (6) noNewData month -----------------------------------------------------------------------------------------------------------------------------------------------
gap = corpus(list(pd.date_range("2026-05-15", "2026-06-20", freq="D")) + list(pd.date_range("2026-08-05", "2026-09-20", freq="D")))
bg = W.build(gap)
st = {r["cutoff"]: r["status"] for r in bg["cutoffs"]}
ok("(6) a month-end with no new eligible drive is noNewData and out of m, k, s (June has data up to the 20th, July none)", st["2026-07-31"] == "noNewData" and st["2026-06-30"] == "ok"
   and bg["summary"]["nEvaluableCutoffs"] == sum(1 for r in bg["cutoffs"] if r["status"] == "ok"), st)

# (7) string-valued flag and timestamped dates -------------------------------------------------------------------------------------------------------------------------
sd = corpus(alldays, flag="str", ts=True)
sd.loc[sd.index[:6], "ens_outlier_v2"] = "True"
bd = W.build(sd)
ok("(7) string-valued ens_outlier_v2 is read as released (the 6 flagged drives are excluded) and timestamped dates work", bd["window"]["nDrives"] == 3 * len(alldays) - 6 and bd["cutoffs"][-1]["status"] == "ok")
late = corpus([TS("2026-05-15"), TS("2026-05-16"), TS("2026-05-30")] + list(pd.date_range("2026-06-01", "2026-06-30", freq="D")), ts=True)
late.loc[late["file"].str.startswith("2026-05-30"), "date"] = "2026-05-31 23:50:00"
bl = W.build(late)
may = bl["cutoffs"][0]
ok("(7) a drive at 23:50 on the month-end day counts in that month-end cutoff", may["cutoff"] == "2026-05-31" and (may["status"] != "ok" or may["nDrives"] == 15) and bl["cutoffs"][0]["cutoff"] == "2026-05-31", may)

# (8) leave-last-k series (Rev 3) ------------------------------------------------------------------------------------------------------------------------------------
lk = {r["k"]: r for r in b["leaveLastK"]}
ok("(8) k = 8, 12, 16 are all reported; each drops exactly k latest eligible days (cutoff = the day before them), keeps the pinned formula and sits outside the counts",
   sorted(lk) == [8, 12, 16] and all(lk[k]["nDays"] == len(alldays) - k and lk[k]["status"] == "ok" and lk[k]["cutoff"] == str((alldays[-1] - pd.Timedelta(days=k)).date()) for k in lk)
   and b["summary"]["nEvaluableCutoffs"] == sum(r["status"] == "ok" for r in b["cutoffs"]), lk)
ok("(8) a 10-day window gives notEvaluable leave-last-k rows (support, or nothing left to fit), not a fit", all(r["status"] == "notEvaluable" for r in W.build(corpus(list(pd.date_range("2026-05-15", "2026-05-24", freq="D"))))["leaveLastK"]))

# (8b) daily grid (Rev 3): counts equal a brute-force loop over every eligible day ----------------------------------------------------------------------------------------
dly = b["daily"]
bf = []
for dd_ in alldays:
    sub = dm[pd.to_datetime(dm["date"]).dt.normalize() <= dd_]
    c_, w_ = W.fit_subset(sub)
    if c_ is not None:
        bf.append(c_)
sg_ = [int(np.sign(c["slope"])) for c in bf]
ok("(8b) daily counts equal the brute-force loop (evaluable fits, positive / negative exclusions of zero, sign changes)", dly == {"nEvaluable": len(bf), "nExcludeZeroPos": sum(c["ci95"][0] > 0 for c in bf), "nExcludeZeroNeg": sum(c["ci95"][1] < 0 for c in bf),
                                                                                                                   "nSignChanges": sum(1 for a_, b_ in zip(sg_, sg_[1:]) if a_ * b_ < 0)}, (dly, len(bf)))
ok("(8b) the early days below the support rule are not counted as evaluable fits", dly["nEvaluable"] < len(alldays) and dly["nEvaluable"] > 0)

# (9) additive splice ---------------------------------------------------------------------------------------------------------------------------------------------------
A = {"meta": {"totalDrives": 1}, "someBlock": {"a": 1}, "_artifactStamps": {"fuelContract": {"corpusHash": "x", "generatedAt": "t", "carriedForward": True}}}
blk = W._clean(b)
new, ch, bad = W.splice(A, blk, "abc", now=pd.Timestamp("2026-10-22").to_pydatetime())
new2, ch2, bad2 = W.splice(new, blk, "abc", now=pd.Timestamp("2026-10-23").to_pydatetime())
ok("(9) only /windowCaveat and its stamp change; a second run with the same block and corpus hash changes nothing", bad == [] and sorted(ch) == ["/_artifactStamps/windowCaveat", "/windowCaveat"] and ch2 == [] and new["someBlock"] == A["someBlock"], (ch, ch2, bad))

stp = new["_artifactStamps"]["windowCaveat"]
ok("(9) the stamp is coherent (includedInReleaseAt = computedAt = generatedAt, M419) and the carried-forward flag is gone", stp["includedInReleaseAt"] == stp["computedAt"] == stp["generatedAt"] and "carriedForward" not in stp)
A_bad = copy.deepcopy(new)
A_bad["_artifactStamps"]["windowCaveat"]["includedInReleaseAt"] = "2020-01-01T00:00:00+00:00"
new3, ch3, bad3 = W.splice(A_bad, blk, "abc", now=pd.Timestamp("2026-10-24").to_pydatetime())
ok("(9) an incoherent existing stamp is re-issued instead of reused", new3["_artifactStamps"]["windowCaveat"]["includedInReleaseAt"] == new3["_artifactStamps"]["windowCaveat"]["generatedAt"] and ch3 and all(c.startswith("/_artifactStamps/windowCaveat/") for c in ch3) and bad3 == [], ch3)

# (10) sentence ---------------------------------------------------------------------------------------------------------------------------------------------------------
sent = W.sentence(blk)
forb = re.compile(r"persist|stable|unstable|stability|robust|confirmed|validated|trend over time|replicated|degradation|SOH|capacity loss|earlier dashboard release|onset|became significant", re.I)
ok("(10) the sentence is generated from the block, names cell-spread, carries no first-exclusion date and none of the forbidden words", sent.startswith("Cell-spread observation window %.1f months (%d drives on %d days)" % (blk["window"]["spanMonths"], blk["window"]["nDrives"], blk["window"]["nDays"]))
   and not forb.search(sent) and "2026-" not in sent and "no claim beyond the released interval" in sent, sent)
for sc, exp in (({"nIntervalExcludesZero": 0, "nEvaluableCutoffs": 6, "nSignChanges": 0}, "0 of 6 cutoffs and the point estimate changed sign 0 times"), ({"nIntervalExcludesZero": 6, "nEvaluableCutoffs": 6, "nSignChanges": 3}, "6 of 6 cutoffs and the point estimate changed sign 3 times")):
    t = copy.deepcopy(blk)
    t["summary"].update(sc)
    ok("(10) sentence counts %s" % exp[:22], exp in W.sentence(t))

# (10b) the generated clause (Rev 3 (c)) ----------------------------------------------------------------------------------------------------------------------------------
cl = lambda rows_: W.lastk_clause({"leaveLastK": rows_})
R_ = lambda k, ex, st="ok": {"k": k, "status": st, "excludesZero": ex}
ok("(10b) K = the smallest k whose interval includes zero", cl([R_(8, True), R_(12, False), R_(16, False)]) == "the interval includes zero when the last 12 days are removed" and cl([R_(8, False), R_(12, False)]) == "the interval includes zero when the last 8 days are removed")
ok("(10b) none includes zero: the evaluable k are listed", cl([R_(8, True), R_(12, True), R_(16, True)]) == "the interval excludes zero after removal of the last 8, 12 and 16 days" and cl([R_(8, True)]) == "the interval excludes zero after removal of the last 8 days")
ok("(10b) a notEvaluable row is skipped; with no evaluable row the clause is omitted", cl([R_(8, None, "notEvaluable"), R_(12, True), R_(16, False)]) == "the interval includes zero when the last 16 days are removed" and cl([R_(8, None, "notEvaluable")]) == "")
ts_ = copy.deepcopy(blk)
ts_["leaveLastK"] = []
ts_["daily"] = {"nEvaluable": 50, "nExcludeZeroPos": 3, "nExcludeZeroNeg": 2, "nSignChanges": 9}
st_ = W.sentence(ts_)
ok("(10b) the sentence carries the daily-grid clause (a of b, p positive, q negative) and no last-k clause when none is evaluable, and stays free of the forbidden words",
   "month-end cutoffs are one fixed grid (at daily cutoffs the interval excluded zero at 5 of 50, 3 positive, 2 negative); the refits are nested" in st_
   and not re.search(r"fragile|mostly null|no effect|significance rate|degradation rate|sensitive endpoint|" + forb.pattern, st_, re.I), st_)

# (11) the tool does not use the M480 tools ------------------------------------------------------------------------------------------------------------------------------
src = open(os.path.join(ROOT, "tools", "window_caveat.py"), encoding="utf-8").read()
ok("(11) tools/window_caveat.py imports nothing from the m480* tools", not re.search(r"^\s*(import|from)\s+m480", src, re.M))

if ok.bad:
    sys.exit(1)
print("OK test_window_caveat")
