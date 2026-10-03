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

    def test_constant_classes_single_source(self):
        # M353 (F18.r1): classes of the model-constant entries come from MC.CONSTANT_CLASS; every class is in the registry vocabulary
        for sym, k in MC.CONSTANT_CLASS.items():
            self.assertIn(k, BAR.KLASSES, sym)
            self.assertTrue(hasattr(MC, sym), sym)
        E = {e["id"]: e for e in ARR["assumptionsRegistry"]["entries"]}
        self.assertGreaterEqual(len(BAR.CLASS_SOURCES), 6)
        for eid, syms in BAR.CLASS_SOURCES.items():
            self.assertEqual({MC.CONSTANT_CLASS[s] for s in syms}, {E[eid]["klass"]}, eid)

    def test_offset_entry(self):
        e = {x["id"]: x for x in ARR["assumptionsRegistry"]["entries"]}["i_offset"]
        ou = ARR["offsetUncertainty"]
        self.assertEqual(e["klass"], "derived_corpus_constant")
        self.assertEqual(e["raw"], ou["pointEstimateA"])
        self.assertEqual(e["usedBy"], ou["correctionScope"]["appliesTo"])
        self.assertIn("not applied to gross throughput, GTC or FCE", e["sensitivity"])
        self.assertIn("one corpus-wide constant", e["label"])
        self.assertIn("two-pass", e["value"])
        self.assertEqual(DM["I_offset_2p_A_applied"].dropna().round(4).nunique(), 1)

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
