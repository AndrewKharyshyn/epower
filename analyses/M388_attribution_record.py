"""M388 attribution record (Director ruling, M388): writes analyses/M388_attribution.json from the scratch attribution run.
Procedure (scratch copy, nothing written to the repo tree): hybrid master = current master with the rows of the 292 previously pinned closure IDs
replaced by their rows from the pre-M388 master (git HEAD:drive_master.csv); stage_raw; gtr_closure_diag.py --ingest (identity check against the pinned file).
Usage: python analyses/M388_attribution_record.py <scratch_dir> (contains old_master.csv, diag.log, repo/)"""
import hashlib, json, os, sys, re
d = sys.argv[1]
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
md5 = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()
log = open(os.path.join(d, "diag.log"), encoding="utf-8").read()
m = re.search(r"M377c checks passed: (\{.*\})", log)
rec = {"scratchLogChecks": json.loads(m.group(1)) if m else None, "identityStop": "STOP" in log,
       "preM388MasterMd5": md5(os.path.join(d, "old_master.csv")),
       "hybridMasterSha256": sha(os.path.join(d, "repo", "drive_master.csv")),
       "postM388MasterMd5": md5("drive_master.csv"),
       "pinnedPreviousPerDriveSha256": sha("analyses/M377c_closure_perdrive.csv"),
       "scratchScriptSha256": sha("analyses/M377c_attribution_scratch.py"), "nPreviousIds": 292, "exitCode": 0}
json.dump(rec, open("analyses/M388_attribution.json", "w", encoding="utf-8", newline="\n"), indent=1)
print(json.dumps(rec, indent=1))
