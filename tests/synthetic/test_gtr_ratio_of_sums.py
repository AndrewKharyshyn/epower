"""M471 (audit F01) known-answer test: the corpus efficiencies of the GTR headline are RATIOS OF ENERGY SUMS. (1) a two-drive example in which the mean of per-drive ratios differs from the ratio of sums; (2) the
audit's targets on the live 376 canonical-clean drives (computed here from the per-drive table, 5e-4 tolerance); (3) every cohort block uses the same reducer (recomputed independently from its own rows);
(4) f_gen, etaTankToTraction and the unchanged flows keep their former definitions; (5) the estimand names and the common-support table are present."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import pandas as pd
import wire_gtr_seasonal as W

# (1) two drives: A 10 km, fuel 40, eta 0.30, gen 10 ; B 30 km, fuel 60, eta 0.40, gen 24 (kWh/100 km)
fr = pd.DataFrame(dict(file=["a", "b"], drive_type=["urban", "highway"], distance_km=[10.0, 30.0], fuel_chem_kWh_100=[40.0, 60.0], eta_eng=[0.30, 0.40], generator_kWh_100=[10.0, 24.0],
                       traction_gross_kWh_100=[20.0, 30.0], traction_net_kWh_100=[15.0, 25.0], gen_to_traction_kWh_100=[8.0, 15.0], batt_to_traction_kWh_100=[12.0, 15.0],
                       regen_to_batt_kWh_100=[1.0, 2.0], gen_to_batt_kWh_100=[2.0, 9.0], f_gen=[0.4, 0.5], eta_fuel_bus=[0.25, 0.40], fuel_L_per_100km=[4.0, 6.0],
                       thermal_regime=["warm", "warm"], ens_excluded=[False, False]))
mean_of_ratios = (0.30 * 10 + 0.40 * 30) / 40                                            # 0.375
eng = (0.30 * 40 * 10 + 0.40 * 60 * 30) / 40; fuel = (40 * 10 + 60 * 30) / 40            # 19.5 / 55.0
a = W.aggregate(fr, "T", 2)
assert abs(mean_of_ratios - 0.375) < 1e-12 and a["corpus"]["etaEng"] == round(eng / fuel, 3) == 0.382 and a["corpus"]["etaEng"] != round(mean_of_ratios, 3)
gen = (10 * 10 + 24 * 30) / 40
assert a["corpus"]["etaBus"] == round(gen / fuel, 3) and a["flows"]["engineBrake"] == round(eng, 2) and a["flows"]["engineLoss"] == round(fuel - eng, 2) and a["flows"]["genpeLoss"] == round(eng - gen, 2)

# complete case: a third drive with unknown eta_eng must not enter the numerator while its fuel stays in the denominator
fr3 = pd.concat([fr, fr.iloc[[0]].assign(file="c", eta_eng=float("nan"), distance_km=100.0)], ignore_index=True)
assert W.aggregate(fr3, "T", 3)["corpus"]["etaEng"] == a["corpus"]["etaEng"]

# (2) live corpus targets
m = W.load_merged(); live = W.aggregate(m, "All", len(m))
assert live["nDrives"] == 376 or live["nDrives"] > 300
c = m[~m["ens_excluded"]]; c = c[c["f_gen"].notna()]
fuel_w = W.wavg(c, "fuel_chem_kWh_100")
cc = c[c["eta_eng"].notna()]          # complete case: eta_eng is null on some drives (unknown, not zero); numerator and denominator cover the same drives
eta_cc = float((cc["eta_eng"] * cc["fuel_chem_kWh_100"] * cc["distance_km"]).sum() / (cc["fuel_chem_kWh_100"] * cc["distance_km"]).sum()); eng_w = eta_cc * fuel_w
assert live["commonSupport"]["etaEngCompleteCase"]["nDrives"] == len(cc) < len(c)
assert abs(live["corpus"]["etaEng"] - eta_cc) < 5e-4 and abs(live["corpus"]["etaBus"] - W.wavg(c, "generator_kWh_100") / fuel_w) < 5e-4
assert abs(live["flows"]["engineBrake"] - eng_w) < 5e-3
if live["nDrives"] == 376:          # the audit's snapshot (606-drive master)
    assert abs(eng_w / fuel_w - 0.354695) < 5e-4 and abs(W.wavg(c, "generator_kWh_100") / fuel_w - 0.328538) < 5e-4 and abs(eng_w - 17.162749) < 5e-3

# (3) cohorts: same reducer on their own rows
for reg in ("warm", "shoulder"):
    sub = m[(m["thermal_regime"] == reg) & ~m["ens_excluded"]]; sub = sub[sub["f_gen"].notna()]
    d = W.aggregate(m[m["thermal_regime"] == reg], reg, len(sub))
    sc = sub[sub["eta_eng"].notna()]
    assert abs(d["corpus"]["etaEng"] - (sc["eta_eng"] * sc["fuel_chem_kWh_100"] * sc["distance_km"]).sum() / (sc["fuel_chem_kWh_100"] * sc["distance_km"]).sum()) < 5e-4, reg

# (4) unchanged definitions
w = c["distance_km"]
assert live["corpus"]["fGen"] == round((c["gen_to_traction_kWh_100"] * w).sum() / (c["traction_gross_kWh_100"] * w).sum(), 3)
assert live["flows"]["etaTankToTraction"] == round(W.wavg(c, "traction_net_kWh_100") / W.wavg(c, "fuel_chem_kWh_100"), 3)

# (5) estimand names + common support
e = live["estimands"]; cs = live["commonSupport"]
assert "NET" in e["etaTankToTraction"] and e["grossTractionBusPerFuel"] == round(W.wavg(c, "traction_gross_kWh_100") / fuel_w, 3) != live["flows"]["etaTankToTraction"]
assert cs["headline"]["nDrives"] == live["nDrives"] and cs["batteryBranches"]["nDrives"] + cs["droppedForMissingBatteryInput"]["nDrives"] == live["nDrives"]
assert abs(cs["batteryBranches"]["km"] + cs["droppedForMissingBatteryInput"]["km"] - cs["headline"]["km"]) < 0.11
print("OK test_gtr_ratio_of_sums (%d drives, etaEng %.4f, etaBus %.4f)" % (live["nDrives"], eta_cc, W.wavg(c, "generator_kWh_100") / fuel_w))
