"""M633 (W1-12 a, c, e) tests: the GTR basis text counts clean drives against ALL fuel-instrumented rows, the regen exploratory notes declare the governing floor, mdeMohmPerMo carries its meaning."""
import json, os, re
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
A = json.load(open(os.path.join(REPO, "summary_arrays.json"), encoding="utf-8"))
G = A["generatorTractionRecon"]
m = re.search(r"(\d+) clean of (\d+) fuel-instrumented drives", G["basis"])
assert m, G["basis"]
assert int(m.group(1)) == G["nDrives"] and int(m.group(2)) == G["eligibilityAlignment"]["nFuelInstrumentedRows"] >= G["nProduction"]
for c, d in A["seasonalCharts"]["charts"]["GeneratorTractionRecon"]["data"].items():
    mm = re.search(r"(\d+) clean of (\d+) fuel-instrumented drives", d["basis"])
    assert mm and int(mm.group(1)) <= int(mm.group(2)), (c, d["basis"])
    assert " clean / " not in d["basis"]
jsx = open(os.path.join(REPO, "xtrail_summary.jsx"), encoding="utf-8").read()
assert jsx.count("The 5-calendar-day floor governs these totals; the 5-ISO-week floor applies only to the week-block sensitivity and the SOC-standardised view.") == 2
pf = A["powerFade"]
assert "CI half-width" in pf["mdeMohmPerMoMeaning"] and "not a power calculation" in pf["mdeMohmPerMoMeaning"] and "mdeMohmPerMo" in pf
src = open(os.path.join(REPO, "wire_gtr_seasonal.py"), encoding="utf-8").read()
assert "{nDrives} clean of {nFuelRows}" in src and "clean / {nProduction}" not in src
print("PASS test_m633_labels")
