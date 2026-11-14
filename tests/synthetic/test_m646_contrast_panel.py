"""M646: the Compare difference panel binds to S.cohortContrast, shows every row's caption and the not-estimable state, and the payload block carries the Rev 1 fields."""
import json, os
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
J = open(os.path.join(REPO, "xtrail_summary.jsx"), encoding="utf-8").read().replace("\r\n", "\n")
i = J.index("function CmpContrastPanel("); seg = J[i:J.index("function CmpEcdfPanel(", i)]
assert "S.cohortContrast" in seg and "C.caption" in seg and "not estimable" in seg and "Exploratory: fewer than 10 effective days" in seg and "route-standardised" in seg
assert "<CmpContrastPanel/>" in J
import re
assert min(float(x) for x in re.findall(r"fontSize=\{([0-9.]+)\}", seg)) >= 9
A = json.load(open(os.path.join(REPO, "summary_arrays.json"), encoding="utf-8"))
C = A["cohortContrast"]
assert "thermal classes" in C["caption"] and "not a temperature effect" in C["caption"] and "Not an article figure" in C["caption"]
assert "no multiplicity correction" in C["method"] and set(C["metrics"]) == {"M1", "M2", "M3"} and "cohortContrast" in A["_artifactStamps"]
for m in C["metrics"].values():
    for c, e in m["contrasts"].items():
        assert set(e) >= {"support", "effectiveDays", "calendarWindows", "raw", "adjusted", "exploratory", "sensitivities"}
        if e["exploratory"]:
            assert "reading" not in e["raw"] and "reading" not in e["adjusted"], "no verdict wording for an exploratory contrast"
        for v in ("raw", "adjusted"):
            r = e[v]
            assert r["estimable"] is False and r.get("reason") or (r["draws"] == 4000 and r["seed"] == 42 and r["dropRate"] <= 0.01)
print("PASS test_m646_contrast_panel")
