#!/usr/bin/env python3
"""M419 (analyses/M419_spec.md, audit F06): artifact-stamp schema split. Every stamp gets `includedInReleaseAt` (the stamping pass == generatedAt, kept), `computedAt` and `inputBasis` {nDrives, masterMd5, source}, read from the block's
OWN fields where the block declares its basis (BLOCK_BASIS) and from the stamping pass otherwise; nothing is typed. Carried blocks get computationStatus 'carriedForward', basisNDrives == inputBasis.nDrives and a note generated from
those fields (restamp_blocks.py used to set carriedForward=true without the status and re-issued the basis of an older audit). The M293 carriedFromMaster / carryForwardNote pair is replaced by a derived `carriedBlocks` list
and the old text is kept as `supersededCarryNote`.
Idempotent; writes ONLY /_artifactStamps/* (asserted by a deep comparison of everything else). Usage: python tools/stamp_basis.py [--dry-run]"""
import copy, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NEW_FIELDS = ("includedInReleaseAt", "computedAt", "computedAtNote", "inputBasis")


def _g(o, path):
    for k in path.split("."):
        o = o[k]
    return o


def own_basis(A, key):
    """The block's own declaration of its basis, or None (the stamping-pass default then applies)."""
    B = A.get(key)
    if key == "masterRefitAudit":
        return {"nDrives": B["nRowsPublished"], "masterMd5": B["publishedMasterMD5"], "computedAt": B.get("generatedAt"),
                "source": "masterRefitAudit.nRowsPublished / publishedMasterMD5 / generatedAt",
                "note": "clean-room raw-to-master audit of %d rows (published master %s, generated %s); not re-run on the live corpus (master_refit_audit.py is audit-only); the %d-row rebuild from the repository archive is masterRefitProvenance"
                        % (B["nRowsPublished"], B["publishedMasterMD5"], B.get("generatedAt"), _g(A["masterRefitProvenance"], "rebuildFromRepositoryArchive.nRowsRebuilt"))}
    if key == "masterRefitProvenance":
        R = B["rebuildFromRepositoryArchive"]
        return {"nDrives": R["nRowsRebuilt"], "masterMd5": R["publishedMasterMD5"], "computedAt": B.get("generatedAt"),
                "source": "masterRefitProvenance.rebuildFromRepositoryArchive.nRowsRebuilt / publishedMasterMD5",
                "note": "historical provenance rebuild of %d rows (published master %s) from the former re-exports in raw/ (before M366); unchanged by later ingestions; the reference of record is masterRefitAudit"
                        % (R["nRowsRebuilt"], R["publishedMasterMD5"])}
    if key == "socHysteresisV2":
        return {"nDrives": B["nDrivesCovered"], "masterMd5": None, "computedAt": B.get("generatedAt"), "source": "socHysteresisV2.nDrivesCovered", "note": None}
    return None


CARRIED_BLOCKS = {"seasonalCharts": lambda A: list(A["seasonalCharts"]["_staleness"].get("stillStale") or []),
                  "generatorTractionRecon": lambda A: list((A["generatorTractionRecon"].get("staleBlocks") or {}).get("blocks") or [])}


def derive(A):
    """Returns the new _artifactStamps dict (a deep copy; A is not modified)."""
    st = copy.deepcopy(A["_artifactStamps"])
    total = A["meta"]["totalDrives"]
    for k, s in st.items():
        s["includedInReleaseAt"] = s.get("generatedAt")
        ob = own_basis(A, k) if k in A else None
        carried = bool(s.get("carriedForward")) or str(s.get("computationStatus", "")).startswith("carriedForward")
        if ob:
            s["inputBasis"] = {"nDrives": ob["nDrives"], "masterMd5": ob["masterMd5"], "source": ob["source"]}
            s["computedAt"] = ob["computedAt"]
            if ob["computedAt"] is None:
                s["computedAtNote"] = "the block carries no timestamp; the stamp time is the stamping pass, not the computation"
            else:
                s.pop("computedAtNote", None)
            if carried:
                s["computationStatus"] = "carriedForward"
                s["carriedForward"] = True
                s["basisNDrives"] = ob["nDrives"]
                if ob["note"]:
                    s["computationStatusNote"] = ob["note"]
        else:
            s["inputBasis"] = {"nDrives": total, "masterMd5": s.get("corpusHash"), "source": "stamping pass: meta.totalDrives, corpusHash"}
            s["computedAt"] = s.get("generatedAt")
            s.pop("computedAtNote", None)
        if "carriedFromMaster" in s:
            s["supersededCarryNote"] = s.pop("carryForwardNote", None)
            s.pop("carriedFromMaster")
        if k in CARRIED_BLOCKS:
            s["carriedBlocks"] = CARRIED_BLOCKS[k](A)
    return st


def check(A):
    """Coherence problems of the stamps (empty list = coherent): used by semantic_gate and the known-answer test."""
    bad = []
    for k, s in A["_artifactStamps"].items():
        ib = s.get("inputBasis")
        if s.get("includedInReleaseAt") != s.get("generatedAt"):
            bad.append((k, "includedInReleaseAt != generatedAt"))
        if not (isinstance(ib, dict) and isinstance(ib.get("nDrives"), int)):
            bad.append((k, "inputBasis.nDrives is not an integer"))
            continue
        if s.get("computedAt") is not None and s["computedAt"] > s.get("includedInReleaseAt", ""):
            bad.append((k, "computedAt later than the release inclusion"))
        if s.get("computedAt") is None and not s.get("computedAtNote"):
            bad.append((k, "computedAt null without a note"))
        carried = bool(s.get("carriedForward")) or str(s.get("computationStatus", "")).startswith("carriedForward")
        if carried:
            if s.get("computationStatus") != "carriedForward" or s.get("carriedForward") is not True:
                bad.append((k, "carried stamp without status carriedForward and the flag"))
            if s.get("basisNDrives") != ib["nDrives"]:
                bad.append((k, "basisNDrives != inputBasis.nDrives"))
            ob = own_basis(A, k) if k in A else None
            if ob and ob["nDrives"] != ib["nDrives"]:
                bad.append((k, "inputBasis.nDrives != the block's own declared count"))
            if k in ("masterRefitAudit", "masterRefitProvenance") and str(ib["nDrives"]) not in str(s.get("computationStatusNote")):
                bad.append((k, "note does not state the basis count"))
        else:
            if s.get("computationStatus") == "computed" and ("basisNDrives" in s or s.get("carriedForward")):
                bad.append((k, "computed stamp with a carry flag or basis"))
        if "carriedFromMaster" in s:
            bad.append((k, "outdated carriedFromMaster flag"))
    return bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    p = os.path.join(ROOT, "summary_arrays.json")
    raw = open(p, "r", encoding="utf-8", newline="").read()
    A = json.loads(raw)
    new = derive(A)
    B = copy.deepcopy(A)
    B["_artifactStamps"] = new
    assert {k: v for k, v in A.items() if k != "_artifactStamps"} == {k: v for k, v in B.items() if k != "_artifactStamps"}, "stamp_basis wrote outside /_artifactStamps"
    changed = sorted(k for k in new if new[k] != A["_artifactStamps"][k])
    print(json.dumps({"stamps": len(new), "changed": len(changed), "carried": sorted(k for k, s in new.items() if s.get("carriedForward"))}, indent=1))
    if "--dry-run" not in argv and changed:
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(B, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
