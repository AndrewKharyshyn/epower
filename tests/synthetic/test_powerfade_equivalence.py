"""M486 known-answer tests (analyses/M486_spec.md Rev 2.1): the equivalence test on the primary resistance design. Constructed data only; the 'released' blocks are built from the same functions so every hard stop can be
triggered by perturbing one published value. Run: python tests/synthetic/test_powerfade_equivalence.py"""
import copy, os, re, sys, tempfile
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import degradation_trends as DT           # noqa: E402
import powerfade_equivalence as P         # noqa: E402


def ok(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + name + ((" -- " + str(detail)) if not cond else ""))
    if not cond:
        ok.bad += 1


ok.bad = 0
RC, IC = P.RCOL, P.ICOL


def make(seed=1, n_days=100, per_day=3, slope=0.0, noise=0.4, flag="bool", delta=0.5439):
    r = np.random.default_rng(seed)
    rows, dens = [], {}
    for dd in range(n_days):
        d = pd.Timestamp("2026-05-15") + pd.Timedelta(days=dd)
        for k in range(per_day):
            f = "f%03d_%d" % (dd, k)
            T, I = 25 + r.normal(0, 4), 120 + r.normal(0, 15)
            de, dc = 1.0 + 0.5 * (dd > 60) + r.normal(0, 0.05), 0.05 + 0.03 * (dd > 60) + r.normal(0, 0.003)
            y = 120 + slope * dd / 30.4375 + 0.3 * T + 0.02 * I + 4.0 * de + 20.0 * dc + r.normal(0, noise)
            rows.append({"file": f, "date": str(d.date()), "ens_outlier_v2": False if flag == "bool" else "False", RC: y, "T_pack_mean_avg": T, IC: I})
            dens[f] = (de, dc)
    dm = pd.DataFrame(rows)
    return dm, dens


def released_from(dm, dens, delta=0.5439):
    """The 'published' values for a constructed corpus, produced by the same code paths the tool must reproduce."""
    d = DT._prep(dm, RC, icol=IC)
    d["de"] = d["file"].map(lambda f: dens[f][0])
    d["dc"] = d["file"].map(lambda f: dens[f][1])
    co0 = DT._cluster_ols(d, covars=("T", "I"))
    co1 = DT._cluster_ols(d, covars=("T", "I", "de", "dc"))
    t0 = DT._tost(co0["slope"], co0["se"], delta, df=co0["nDays"] - 1)
    cc, hd = P.s1_rows(dm, dens)
    bt = P.bootstrap_s1(cc, hd, 500)
    rv = {"clusterRobustOLS": co0, "releasedEquivalence": {"label": "oem75pct_over14yr", "delta": delta, "pTOST": t0["pTOST"], "equivCI90": t0["equivCI90"]}, "proxyMedianMohm": 130.3}
    pf = {"nClean": co1["nObs"], "slopeMohmPerMoTctrl": round(co1["slope"], 3), "ci95MohmPerMo": [round(bt["ci95"][0], 3), round(bt["ci95"][1], 3)], "nBoot": bt["drawsUsed"], "cadenceControlled": True,
          "cadenceSensitivity": {"slopeMin": 0.2, "slopeMax": 0.9, "nSpecs": 7, "allIntervalsSpanZero": True}}
    return {"resistanceVreg": rv, "powerFade": pf}


def stops(dm, dens, rel, n_boot=500):
    try:
        P.compute_block(dm, dens, rel, n_boot=n_boot)
        return None
    except SystemExit as e:
        return str(e)


# (1) a consistent constructed corpus passes every stop; S0 and S1 are the released code path; the bound is read, not recomputed ----------------------------------------------------------
dm, dens = make(slope=3.0)
rel = released_from(dm, dens)
blk = P.compute_block(dm, dens, rel, n_boot=500)
d_ = DT._prep(dm, RC, icol=IC)
ok("(1) the S0 control equals _cluster_ols + _tost on the constructed data and S1 carries both density columns", blk["s0Control"]["slope"] == rel["resistanceVreg"]["clusterRobustOLS"]["slope"] and blk["s1"]["formula"] == "y ~ months + T + I + de + dc"
   and blk["s0Control"]["pTOST"] == rel["resistanceVreg"]["releasedEquivalence"]["pTOST"], (blk["s0Control"], blk["s1"]["formula"]))
rel2 = copy.deepcopy(rel)
rel2["resistanceVreg"]["proxyMedianMohm"] = 999.0
blk2 = P.compute_block(dm, dens, rel2, n_boot=500)
ok("(1) the bound is read from the released block as a constant: a different current median does not move it; a different released delta is read through", blk2["bound"]["value"] == blk["bound"]["value"] == 0.5439
   and blk2["bound"]["currentMedianMohm"] == 999.0 and P.compute_block(dm, dens, released_from(dm, dens, delta=0.9), n_boot=500)["bound"]["value"] == 0.9)
ok("(1) a large true slope gives notEstablished under both procedures", blk["verdict"] == "notEstablished" and blk["procedures"] == {"cr1TostInside": False, "bootstrap90Inside": False}, blk["procedures"])
dm0, dens0 = make(slope=0.0, noise=0.05, n_days=150)
rel0 = released_from(dm0, dens0, delta=0.5439)
b0 = P.compute_block(dm0, dens0, rel0, n_boot=500)
ok("(1) a constructed zero slope with a tight interval inside the bound gives established (both procedures inside)", b0["verdict"] == "established" and b0["procedures"]["cr1TostInside"] and b0["procedures"]["bootstrap90Inside"], (b0["s1"], b0["bootstrap"]["ci90"]))

# (2) decision rule ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
ok("(2) established / procedureDependent (either one) / notEstablished", P.verdict_from(True, True) == "established" and P.verdict_from(True, False) == "procedureDependent" and P.verdict_from(False, True) == "procedureDependent"
   and P.verdict_from(False, False) == "notEstablished")

# (3) hard stops --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
r_ = copy.deepcopy(rel)
r_["resistanceVreg"]["clusterRobustOLS"]["slope"] += 0.01
ok("(3) (i) an S0 control that differs from the released fit stops", (stops(dm, dens, r_) or "").startswith("STOP (i)"))
r_ = copy.deepcopy(rel)
r_["powerFade"]["slopeMohmPerMoTctrl"] += 0.01
ok("(3) (ii) an S1 slope that differs from the published one by more than 0.002 stops", (stops(dm, dens, r_) or "").startswith("STOP (ii)"))
r_ = copy.deepcopy(rel)
r_["powerFade"]["ci95MohmPerMo"][1] += 0.01
ok("(3) (iii) a bootstrap that does not reproduce the published 95 % interval stops", (stops(dm, dens, r_) or "").startswith("STOP (iii)"))
r_ = copy.deepcopy(rel)
r_["powerFade"]["nBoot"] -= 1
ok("(3) (iii) a published nBoot different from the draws used stops", (stops(dm, dens, r_) or "").startswith("STOP (iii)"))
r_ = copy.deepcopy(rel)
r_["powerFade"]["cadenceControlled"] = False
ok("(3) (vi) a published design that did not engage the density correction stops", (stops(dm, dens, r_) or "").startswith("STOP (vi)"))
r_ = copy.deepcopy(rel)
r_["powerFade"]["nClean"] += 1
ok("(3) (v) a file-set size different from powerFade.nClean stops", (stops(dm, dens, r_) or "").startswith("STOP (v)"))
dms, denss = make(flag="str")
ok("(3) (v) string-valued flags make the released coercion and _as_bool disagree: stop", (stops(dms, denss, released_from(make()[0], make()[1])) or "").startswith("STOP (v)"))
dsp = dict(dens)
for i, f in enumerate(list(dsp)):
    if i % 10 < 6:
        dsp[f] = (np.nan, np.nan)
ok("(3) density present on 40 % of the rows (half or fewer) stops (it never silently becomes S0)", (stops(dm, dsp, rel) or "").startswith(("STOP (iv)", "STOP (v)")), stops(dm, dsp, rel))

# (4) sidecar: incremental by raw sha256, byte-identical rebuild, production density -------------------------------------------------------------------------------------------------
def raw_csv(period, n=300, cov_every=1):
    rows = ["time,[BMS] HV Battery Current (A),[VCM] Vehicle Speed (km/h)"]
    for i in range(n):
        t = i * period
        rows.append("%02d:%02d:%09.6f,%s,%s" % (int(t // 3600), int((t % 3600) // 60), t % 60, ("%.1f" % (-10.0 - i % 7)) if i % cov_every == 0 else "", "50"))
    return "\n".join(rows).encode("utf-8")


b1, b2 = raw_csv(0.8), raw_csv(0.8, cov_every=2)
import compute_drive_summary_v6 as D
dd1 = D._i_channel_sampling_density(["x"], lambda f: b1)["x"]
ok("(4) density_from_bytes equals the production function (0.8 s updates, all rows: median 0.8, coverage 1.0)", P.density_from_bytes(b1) == dd1 and abs(dd1[0] - 0.8) < 1e-6 and abs(dd1[1] - 1.0) < 1e-9, dd1)
master = pd.DataFrame({"file": ["a.csv", "b.csv"], "date": ["2026-05-15", "2026-05-16"], RC: [100.0, 101.0]})
byts = {"a.csv": b1, "b.csv": b2}
sha = {f: __import__("hashlib").sha256(b).hexdigest() for f, b in byts.items()}
calls = []
with tempfile.TemporaryDirectory() as td:
    path = os.path.join(td, "pd.csv")
    s1_ = P.build_density(master, lambda f: (calls.append(f), byts[f])[1], lambda f: sha[f], path=path)
    n1 = len(calls)
    raw1 = open(path, "rb").read()
    s2_ = P.build_density(master, lambda f: (_ for _ in ()).throw(AssertionError("raw read on reuse")), lambda f: sha[f], path=path)
    raw2 = open(path, "rb").read()
    ok("(4) the sidecar is incremental by raw sha256 (no raw file read on reuse) and the rebuild is byte-identical", n1 == 2 and raw1 == raw2 and list(s1_["file"]) == ["a.csv", "b.csv"] and (s1_["raw_sha256"] == pd.Series(sha).reindex(["a.csv", "b.csv"]).values).all())
    ok("(4) a 1.6 s update with every second row carrying a sample gives median 1.6 and coverage 0.5", abs(float(s1_.loc[1, "eff_dt_s"]) - 1.6) < 1e-6 and abs(float(s1_.loc[1, "coverage_frac"]) - 0.5) < 1e-6, s1_)
    sha2 = dict(sha, **{"a.csv": "0" * 64})
    P.build_density(master, lambda f: byts[f], lambda f: sha2[f], path=path)
    ok("(4) a changed raw hash recomputes that drive (the stored hash is the hash of the bytes read)", pd.read_csv(path)["raw_sha256"].iloc[0] == sha["a.csv"])

# (5) additive, coherent stamp ------------------------------------------------------------------------------------------------------------------------------------------------------------------
A = {"meta": {"totalDrives": 1}, "someBlock": {"a": 1}, "_artifactStamps": {"fuelContract": {"corpusHash": "x", "generatedAt": "t", "carriedForward": True}}}
cb = P._clean(blk)
new, ch, bad = P.splice(A, cb, "abc", now=pd.Timestamp("2026-10-22").to_pydatetime())
new2, ch2, bad2 = P.splice(new, cb, "abc", now=pd.Timestamp("2026-10-23").to_pydatetime())
stp = new["_artifactStamps"]["powerFadeEquivalence"]
ok("(5) only /powerFadeEquivalence and its stamp change; a second run changes nothing; the stamp is coherent (M419)", bad == [] and sorted(ch) == ["/_artifactStamps/powerFadeEquivalence", "/powerFadeEquivalence"] and ch2 == []
   and stp["includedInReleaseAt"] == stp["computedAt"] == stp["generatedAt"] and "carriedForward" not in stp and new["someBlock"] == A["someBlock"], (ch, ch2, bad))

# (6) sentence ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
forb = re.compile(r"no degradation|stable|proves|confirms|fade rate|cadence controlled|cadence-corrected|measured resistance|no equivalence test exists", re.I)
for v, frag in (("notEstablished", "equivalence not established."), ("procedureDependent", "procedure-dependent, equivalence not established."), ("established", "within the locked bound over this window.")):
    t = copy.deepcopy(cb)
    t["verdict"] = v
    s_ = P.sentence(t)
    ok("(6) sentence for %s" % v, frag in s_ and "density-adjusted partial slope" in s_ and "M395" in s_ and ". This is not evidence of no change." in s_ and "every 95 % interval spans zero" in s_ and not forb.search(s_), s_)
ok("(6) Rev 3: maximum SE for equivalence = bound / t0.95,df (0.5439 and df 97 give about 0.3275)", abs(P.se_max_for_equivalence(0.5439, 97) - 0.3275) < 1e-4, P.se_max_for_equivalence(0.5439, 97))
t_ = copy.deepcopy(cb)
t_["s1"].update(se=0.557, seMaxForEquivalence=0.3275, equivalenceAttainable=False)
ok("(6) Rev 3: the not-attainable clause (even a slope of exactly 0 would not lie inside the bound), 3-decimal numbers", "At this precision the test could not show equivalence: it requires an SE below 0.328 m\u03a9/month (bound / t0.95,df), the observed SE is 0.557, so even a slope estimate of exactly 0 would not lie inside the bound." in P.sentence(t_), P.sentence(t_)[-260:])
t_["s1"].update(se=0.2, equivalenceAttainable=True)
ok("(6) Rev 3: the attainable clause", "The observed SE 0.200 is below the 0.328 m\u03a9/month needed for equivalence to be attainable." in P.sentence(t_))
t_["cadenceRange"] = {}
ok("(6) Rev 3: an empty cadence clause still gives a capitalised new sentence (no lowercase 'this')", ". This is not evidence of no change." in P.sentence(t_) and ". this is" not in P.sentence(t_))
ok("(6) Rev 3: the block carries the field and flag", cb["s1"]["seMaxForEquivalence"] == round(P.se_max_for_equivalence(cb["bound"]["value"], cb["s1"]["df"]), 4) and cb["s1"]["equivalenceAttainable"] == (cb["s1"]["se"] < cb["s1"]["seMaxForEquivalence"]))
ok("(6) the short clause for the S0 panels", P.short(cb) == "primary design (S1): equivalence not established")

# (7) imports ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
src = open(os.path.join(ROOT, "tools", "powerfade_equivalence.py"), encoding="utf-8").read()
ok("(7) the tool imports nothing from the m480* tools", not re.search(r"^\s*(import|from)\s+m480", src, re.M))

if ok.bad:
    sys.exit(1)
print("OK test_powerfade_equivalence")
