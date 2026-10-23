"""M467 (external audit F04) known-answer test: the replay allowance for the frozen two-pass offset follows the EXACT eligible row set (published rows with a non-null I_offset_2p_A_applied), not a fixed
number: every eligible row may differ, one row more or a file outside the set is unexpected."""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd
import replay_master as R
rep = json.load(open("analyses/replay/replay_report_full.json", encoding="utf-8"))
pub = pd.read_csv("drive_master.csv", usecols=["file", "I_offset_2p_A_applied"])
el = pub.loc[pub["I_offset_2p_A_applied"].notna(), "file"].tolist()
base = copy.deepcopy(rep); base["columnsDiffering"] = {"I_offset_2p_A_applied": {"nRowsDiffer": len(el), "nNullPatternMismatch": 0, "maxAbsDiff": 0.0002, "files": el[:12], "filesAll": el}}
base["identities"] = {"offsetIdentityFailures": {}, "distanceIdentityFailures": [], "distanceDerivedOutsideRepaired": [], "repairedFiles": ["20260906_122920.csv"]}      # M489: the report carries the identities
assert R.check_expected(base) == []
over = copy.deepcopy(base); over["columnsDiffering"]["I_offset_2p_A_applied"]["nRowsDiffer"] = len(el) + 1
assert R.check_expected(over)
out = copy.deepcopy(base); out["columnsDiffering"]["I_offset_2p_A_applied"]["filesAll"] = el[:5] + ["not_in_set.csv"]       # M489 (A07): a hidden row beyond the first 12 is still found
assert R.check_expected(out)
old = copy.deepcopy(base); del old["columnsDiffering"]["I_offset_2p_A_applied"]["filesAll"]
assert R.check_expected(old), "a report without the full row list must fail"
big = copy.deepcopy(base); big["columnsDiffering"]["I_offset_2p_A_applied"]["maxAbsDiff"] = 0.01
assert R.check_expected(big)
print("OK test_replay_expected_eligible (%d eligible rows)" % len(el))
