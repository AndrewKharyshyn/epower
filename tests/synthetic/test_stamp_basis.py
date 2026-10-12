"""M419 (audit F06): the stamp schema split. Known-answer tests on the live payload and mutation controls: includedInReleaseAt / computedAt / inputBasis are derived from the blocks' own fields, a carried block states its own basis
(masterRefitAudit 446 = nRowsPublished, masterRefitProvenance 489), nothing outside /_artifactStamps is touched, the tool is idempotent, and every incoherent stamp is caught by check()."""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import stamp_basis as S

A = json.load(open("summary_arrays.json", encoding="utf-8"))
assert S.check(A) == [], S.check(A)
st = A["_artifactStamps"]
a = st["masterRefitAudit"]
assert a["computationStatus"] == "carriedForward" and a["carriedForward"] is True
assert a["basisNDrives"] == a["inputBasis"]["nDrives"] == A["masterRefitAudit"]["nRowsPublished"]
assert a["inputBasis"]["masterMd5"] == A["masterRefitAudit"]["publishedMasterMD5"] and a["computedAt"] == A["masterRefitAudit"]["generatedAt"]
assert a["computedAt"] < a["includedInReleaseAt"] and str(a["basisNDrives"]) in a["computationStatusNote"]
p = st["masterRefitProvenance"]
assert p["basisNDrives"] == p["inputBasis"]["nDrives"] == A["masterRefitProvenance"]["rebuildFromRepositoryArchive"]["nRowsRebuilt"]
assert st["socHysteresisV2"]["basisNDrives"] == A["socHysteresisV2"]["nDrivesCovered"]
assert all("carriedFromMaster" not in v for v in st.values())
assert st["generatorTractionRecon"]["carriedBlocks"] == A["generatorTractionRecon"]["staleBlocks"]["blocks"] and st["seasonalCharts"]["carriedBlocks"] == A["seasonalCharts"]["_staleness"]["stillStale"]
# derive() is idempotent and writes only the stamps
new = S.derive(A)
assert new == A["_artifactStamps"], "derive() must be a fixed point on the committed payload"
B = copy.deepcopy(A); B["_artifactStamps"] = S.derive(B)
assert B == A
# default (computed) stamps: the stamping pass
c = st["thermalSupportLedger"]
assert c["computedAt"] == c["includedInReleaseAt"] == c["generatedAt"] and c["inputBasis"]["nDrives"] == A["meta"]["totalDrives"] and c["inputBasis"]["masterMd5"] == c["corpusHash"]


def bad(f):
    X = copy.deepcopy(A); f(X); return S.check(X)
assert bad(lambda X: X["_artifactStamps"]["masterRefitAudit"].update(basisNDrives=489)), "a hand-edited basis must fail"
assert bad(lambda X: X["_artifactStamps"]["masterRefitAudit"].update(computationStatus="computed")), "carry flag without status must fail"
assert bad(lambda X: X["_artifactStamps"]["serialDependence"].update(carriedForward=True, basisNDrives=554)), "a carry flag on a computed stamp must fail"
assert bad(lambda X: X["_artifactStamps"]["masterRefitAudit"].update(computationStatusNote="carried at the 489-drive basis")), "a note with another count must fail"
assert bad(lambda X: X["_artifactStamps"]["cohortMeta"].pop("inputBasis")), "a missing inputBasis must fail"
assert bad(lambda X: X["_artifactStamps"]["cohortMeta"].update(includedInReleaseAt="2000-01-01T00:00:00+00:00")), "includedInReleaseAt != generatedAt must fail"
assert bad(lambda X: X["_artifactStamps"]["cohortMeta"].update(carriedFromMaster=True)), "the outdated flag must fail"
assert bad(lambda X: X["masterRefitAudit"].update(nRowsPublished=489)), "a block whose own count differs from the stamp must fail"
assert bad(lambda X: X["_artifactStamps"]["cohortMeta"].update(computedAt="2999-01-01T00:00:00+00:00")), "computedAt after the inclusion must fail"
print("OK test_stamp_basis")
