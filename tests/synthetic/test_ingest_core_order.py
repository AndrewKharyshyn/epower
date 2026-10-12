"""M422: tools/ingest_core.py builds the Ah-throughput sidecar for the new drives BEFORE the arrays build (the rated-basis exposure coverage gate of M414/M415 needs a sidecar Ah value for every master drive;
a rehearsal ingestion of 20 new drives failed with ExposureCoverageError because the sidecar was only built by the later ah_throughput stage), the sidecar files are in the rollback list, and the
exposure coverage gate itself still fails when a master drive has a finite legacy gtc and no sidecar Ah (the gate was not weakened)."""
import os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
src = open("tools/ingest_core.py", encoding="utf-8").read()
i_master = src.index('_atomic(os.path.join(ROOT, "drive_master.csv"), lambda t: dm_new.to_csv(t, index=False))')
i_manifest = src.index('write_json(os.path.join(ROOT, "raw_manifest.json"), man')
i_ah = src.index("import ah_throughput as AH")
i_arrays = src.index("arrays = step4_arrays(dm_disk, stage, a.recompute_m119v2)")
assert i_master < i_manifest < i_ah < i_arrays, "the sidecar must be built after the master and manifest are written and before the arrays build"
assert "AH.main([]) != 0" in src[i_ah:i_arrays] and "raise Gate(" in src[i_ah:i_arrays]
m = re.search(r"^OUT_FILES = \[(.*?)\]", src, re.M)
assert m and '"ah_throughput.csv"' in m.group(1) and '"ah_throughput_summary.json"' in m.group(1), "the sidecar files must be restored on a failed ingestion"
stages = __import__("json").load(open("tools/ingest_stages.json", encoding="utf-8"))
ids = [x["id"] for x in (stages["stages"] if isinstance(stages, dict) else stages)]
assert ids.index("stamp_basis") < ids.index("leaf_guard") and ids.index("stamp_basis") > ids.index("ingest_core"), "stamp_basis must precede leaf_guard (the arrays build recreates the stamps)"
assert "ah_throughput" in ids and ids.index("ah_throughput") > ids.index("ingest_core"), "the stage stays as an idempotent re-check"
# the coverage gate still refuses a master drive without a sidecar Ah (no legacy fallback)
import pandas as pd
import exposure_frame as EF
dm = pd.read_csv("drive_master.csv", low_memory=False)
side = pd.read_csv("ah_throughput.csv", dtype={"raw_sha256": str}, keep_default_na=False, na_values=[""])
import tempfile
cut = side[side["file"] != dm.loc[dm["gtc"].notna(), "file"].iloc[0]]
tmp = os.path.join(tempfile.mkdtemp(), "side.csv")
cut.to_csv(tmp, index=False)
try:
    EF.exposure_frame(dm, "rated5Ah", sidecar_path=tmp)
    failed = False
except EF.ExposureCoverageError:
    failed = True
assert failed, "removing a sidecar row of a drive with a finite gtc must raise"
print("OK test_ingest_core_order")
