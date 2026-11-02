"""M561 known answers KB1-KB4b (analyses/M561_spec.md Rev 2): uninterrupted-direction runs and the run-restricted exact window extremum."""
import os, sys, unittest
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import power_duration as PD
import power_duration_uninterrupted as U


def rec(ts, P):
    ts = np.array(ts, float); P = np.array(P, float)
    return U.drive_record(ts, P, np.abs(P) * 2.0, 0.0)


class TestUninterrupted(unittest.TestCase):
    def test_kb1_constant(self):
        r = rec(np.arange(0, 121, 1.0), np.full(121, 7.0))
        for W in (5, 10, 30, 60, 120):
            self.assertAlmostEqual(r["byW"][str(W)]["dis"]["exact"], 7.0, 9)
            self.assertAlmostEqual(r["m552"][str(W)]["dis"], 7.0, 9)
            self.assertIsNone(r["byW"][str(W)]["chg"]["exact"])

    def test_kb2_step_and_ramp(self):
        ts = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 60, 65, 70, 75, 80, 85, 90, 95, 100, 105, 110, 115, 120]; P = [10] * 13 + [-10] * 13
        r = rec(ts, P)
        self.assertAlmostEqual(r["byW"]["30"]["dis"]["exact"], 10.0, 9); self.assertAlmostEqual(r["byW"]["30"]["chg"]["exact"], 10.0, 9)
        self.assertIsNone(r["byW"]["120"]["dis"]["exact"]); self.assertIsNone(r["byW"]["120"]["chg"]["exact"])
        self.assertAlmostEqual(r["m552"]["120"]["dis"], 0.0, 9)
        runs = U.runs_of([0, 20], [10, -10])
        self.assertEqual(len(runs), 1); self.assertAlmostEqual(runs[0][0][-1], 10.0, 9)
        runs = U.runs_of([0, 20], [-10, 10])
        self.assertAlmostEqual(runs[0][0][-1], 10.0, 9)

    def test_kb3_reversal_inside_window(self):
        ts = list(range(0, 11)) + list(range(10, 16)) + list(range(15, 26)); P = [20] * 11 + [-10] * 6 + [20] * 11
        r = rec(ts, P)
        self.assertAlmostEqual(r["m552"]["10"]["dis"], 20.0, 9)
        self.assertAlmostEqual(r["byW"]["10"]["dis"]["exact"], 20.0, 9)
        self.assertIsNone(r["byW"]["30"]["dis"]["exact"])
        # net mean over the whole 25 s: (200 - 50 + 200) / 25 = 14
        self.assertAlmostEqual(PD.window_extremes(*PD.segments(np.array(ts, float), np.array(P, float))[0], 25)["max"], 14.0, 9)

    def test_kb4_zero_touch_and_split(self):
        self.assertEqual(len(U.runs_of([0, 5, 10], [10, 0, 10])), 1)
        self.assertEqual(len(U.runs_of([0, 5, 10], [10, -1e-9, 10])), 2)

    def test_kb4b_zero_between_opposite_signs(self):
        d = U.runs_of([0, 5, 10], [10, 0, -10]); c = U.runs_of([0, 5, 10], [-10, 0, 10])
        self.assertEqual(len(d), 1); self.assertAlmostEqual(d[0][0][-1], 5.0, 9)
        self.assertEqual(len(c), 1)
        self.assertEqual(len(U.runs_of([0, 5, 10], [-0.0, -0.0, 5])), 1)

    def test_no_interp_is_lower_bracket_of_interp(self):
        ts = np.arange(0, 61, 1.0); P = np.where(np.arange(61) < 30, 8.0, -8.0)
        a = U.run_best(U.runs_of(ts, P, True), 10); b = U.run_best(U.runs_of(ts, P, False), 10)
        self.assertGreaterEqual(a["exact"] + 1e-12, b["exact"])


if __name__ == "__main__":
    unittest.main()
