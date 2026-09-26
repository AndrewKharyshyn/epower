#!/usr/bin/env python3
"""Drift tests: assumptionsRegistry must equal a fresh rebuild from its sources, and prose literals
that quote pipeline counts must equal their derived form. Run from the project/work dir."""
import json, sys, os, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import build_assumptions_registry as BAR
import model_constants as MC
from derived_literals import gtr_limitations_head

ARR = json.load(open("summary_arrays.json")); CFG = json.load(open("summary_config.json"))
DM = pd.read_csv("drive_master.csv", low_memory=False)


class T(unittest.TestCase):
    def test_registry_matches_rebuild(self):
        self.assertEqual(ARR["assumptionsRegistry"]["entries"], json.loads(json.dumps(BAR.build(CFG, ARR))))

    def test_schema(self):
        self.assertTrue(BAR.validate(ARR["assumptionsRegistry"]["entries"]))
        r = ARR["assumptionsRegistry"]
        self.assertEqual(r["nEntries"], len(r["entries"]))
        self.assertEqual(r["nUnverified"], sum(1 for e in r["entries"] if not e["verified"]))

    def test_required_assumptions_present(self):
        ids = {e["id"] for e in ARR["assumptionsRegistry"]["entries"]}
        for need in ("cap_kwh", "mass_kg", "fuel_lhv", "bsfc_surface", "woehler_k", "scenario_threshold_gtc",
                     "odometer_km", "cold_gate_engine", "thermal_regime_bins"):
            self.assertIn(need, ids)

    def test_values_track_sources(self):
        E = {e["id"]: e for e in ARR["assumptionsRegistry"]["entries"]}
        self.assertEqual(E["cap_kwh"]["raw"], CFG["vehicle"]["capacityKwh"])          # config vs provenance agree
        self.assertEqual(E["fuel_lhv"]["raw"], MC.LHV_MJ_PER_KG[0])
        self.assertEqual(E["woehler_k"]["raw"]["reference"], CFG["kExponentLadder"]["kReference"])
        self.assertEqual(E["scenario_threshold_gtc"]["raw"], CFG["kExponentLadder"]["referenceThresholdGtc"])
        self.assertEqual(E["odometer_km"]["raw"], CFG["vehicle"]["odometerKm"])
        self.assertEqual(E["cold_gate_engine"]["raw"]["oil_c"], MC.COLD_OIL_T_C)

    def test_gtr_limitations_derived(self):
        l1, l2 = gtr_limitations_head(ARR, float(DM["distance_km"].sum()), DM["drive_type"].value_counts().to_dict())
        self.assertEqual(ARR["generatorTractionRecon"]["limitations"][:2], [l1, l2])
        self.assertNotIn("145/374", " ".join(ARR["generatorTractionRecon"]["limitations"]))

    def test_determinism_scope_labelled(self):
        d = ARR["determinism"]
        self.assertEqual(d["harness"], "ml16_determinism_check")
        self.assertEqual(d, {**d, **{k: CFG["auditMetadata"]["determinism"][k] for k in ("harness", "scopeLabel", "releaseTest")}})


if __name__ == "__main__":
    unittest.main(verbosity=1)
