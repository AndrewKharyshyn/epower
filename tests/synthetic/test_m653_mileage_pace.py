"""M653: the mileage pace (usageRate.yearsToOfficialLifeKm) is shown as plain arithmetic: equals round(officialLifeKm / kmPerYr, 1) from the same block, the builder no longer nulls it, the card says it is not a
battery-life estimate, the other modelled year outputs stay retracted (test_m632_official_fields). Run: python tests/synthetic/test_m653_mileage_pace.py"""
import json, os, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
A = json.load(open("summary_arrays.json", encoding="utf-8"))
ur = A["officialDisclosureCorrelation"]["usageRate"]
assert ur["yearsToOfficialLifeKm"] == round(ur["officialLifeKm"] / ur["kmPerYr"], 1), ur
assert "years-to-official-life" not in A["_retractedLifeEol"] and "mileage pace" in A["_retractedLifeEol"]
src = open("compute_summary_arrays.py", encoding="utf-8").read()
assert "'afWeightedYearsTotal', 'yearsToOfficialLifeKm'" not in src and "'yearsToOfficialLifeKm'" in src      # still produced, no longer in the retraction set
assert "arithmetic, not a battery-life estimate" in open("xtrail_summary.jsx", encoding="utf-8").read()
r = subprocess.run([sys.executable, "tools/m653_mileage_pace.py", "--dry-run"], capture_output=True, text=True)
assert r.returncode == 0 and '"changed": false' in r.stdout, r.stdout           # idempotent
print("PASS test_m653_mileage_pace")
