"""M513 known-answer tests (analyses/M513_spec.md Rev 2): stamps of declared blocks are derived from the declared dependencies only; lineage is append-only and grows only when an identity value changes;
computedAt is never the stamping time; the declared stamp survives stamp_basis and a second run."""
import copy, json, os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import stamp_common as SC
import stamp_dependencies_apply as AP
import stamp_basis as SB

MASTER, MASTER2, MAN, MAN2 = "a" * 32, "b" * 32, "c" * 64, "d" * 64
CFG = {"ambientByDrive": {"x.csv": [10, 12]}, "vehicle": {"mass": 1}, "wording": "free text"}
DEPS = {"ambTable": {"producerStages": ["s_amb"], "readsRaw": False, "readsRawManifest": False, "configSections": ["ambientByDrive"], "inputFiles": []},
        "rawBlock": {"producerStages": ["s_raw1", "s_raw2"], "readsRaw": True, "readsRawManifest": False, "configSections": [], "inputFiles": []}}
LEGACY = {"corpusHash": "z" * 32, "configHash": "k", "fullConfigHash": "f" * 32, "generatedAt": "2026-10-20T22:13:33+00:00", "pipelineVersion": 6, "computationStatus": "computed", "computationStatusNote": "M463: regenerated",
          "upstreamHashes": {"rawManifestCorpusHash": "old" * 20, "rawManifestSnapshotId": "2026-09-25_x"}, "reissuedFrom": "r", "reissueNote": "M312 reissue", "corpusHashSource": "file:drive_master.csv"}


def arrays(master=MASTER):
    st = {k: dict(copy.deepcopy(LEGACY), corpusHash=master) for k in ("ambTable", "rawBlock", "other")}
    return {"meta": {"totalDrives": 3}, "ambTable": {"v": 1}, "rawBlock": {"v": 2}, "other": {"v": 3}, "_artifactStamps": st}


def run(A, cfg=CFG, master=MASTER, manifest=MAN, env=None, backfill=False, attest=None, replay=None, now="2026-10-25T10:00:00+00:00"):
    env = dict(env or {}, XT_STAMP_NOW=now)
    return AP.derive_all(A, cfg, DEPS, master, manifest, env, ROOT, backfill, attest, "M513", replay)


# section hashes: a declared section changes the hash, an undeclared one does not
h0 = SC.section_hash(CFG, "ambientByDrive")
assert SC.section_hash(dict(CFG, ambientByDrive={"x.csv": [10, 13]}), "ambientByDrive") != h0
d0 = SC.identity(DEPS["ambTable"], MASTER, CFG, ROOT)
assert SC.same_identity(d0, SC.identity(DEPS["ambTable"], MASTER, dict(CFG, wording="edited"), ROOT))
assert not SC.same_identity(d0, SC.identity(DEPS["ambTable"], MASTER, dict(CFG, ambientByDrive={"y": 1}), ROOT))
assert h0 == SC.section_hash(json.loads(json.dumps(CFG, sort_keys=False)), "ambientByDrive")        # canonical: key order does not matter

# backfill: a block without evidence is left as it was; with evidence the legacy identity goes to the lineage
A = arrays()
st, rep = run(A, backfill=True)
assert "skipped" in rep["ambTable"] and st["ambTable"] == A["_artifactStamps"]["ambTable"]
replay = {"masterMd5": MASTER, "blocks": {"ambTable": {"identical": True}}}
st, rep = run(A, backfill=True, replay=replay)
s = st["ambTable"]
assert s["stampLineage"][0]["identity"]["upstreamHashes"]["rawManifestCorpusHash"] == "old" * 20 and s["stampLineage"][0]["identity"]["fullConfigHash"] == "f" * 32
assert "rawManifestCorpusHash" not in s["upstreamHashes"] and s["fullConfigHash"] is None and "reissueNote" not in s            # a non-raw block carries no raw-manifest field
assert s["computedAt"] is None and s["computedAtNote"] and s["computedAt"] != s["generatedAt"]                                    # never the stamping time
assert st["other"] == A["_artifactStamps"]["other"]                                                                              # undeclared stamps untouched
# raw block: attested identity is written, with the attestation source; absent attestation -> no raw identity
att = {"rawBlock": {"attested": True, "rawManifestCorpusHash": MAN, "source": "attested at M513 from git history (test)"}}
st2, _ = run(A, backfill=True, attest=att)
assert st2["rawBlock"]["upstreamHashes"]["rawManifestCorpusHash"] == MAN and "attested at M513" in st2["rawBlock"]["upstreamHashes"]["rawIdentitySource"]
st3, rep3 = run(A, backfill=True, attest={})
assert "skipped" in rep3["rawBlock"]

# idempotence and lineage rules
again, _ = run({**A, "_artifactStamps": st}, backfill=True, replay=replay)
assert again["ambTable"] == st["ambTable"]
base = copy.deepcopy(st)
A2 = {**A, "_artifactStamps": base}
A2["_artifactStamps"]["ambTable"]["generatedAt"] = "2026-10-26T00:00:00+00:00"          # restamp_blocks: generatedAt alone changes -> no lineage entry
st4, _ = run(A2, backfill=False)
assert len(st4["ambTable"]["stampLineage"]) == 1
st5, _ = run(A2, cfg=dict(CFG, ambientByDrive={"x.csv": [10, 99]}))                      # a declared config value changes -> one entry, earlier entries byte-identical
assert len(st5["ambTable"]["stampLineage"]) == 2 and st5["ambTable"]["stampLineage"][0] == base["ambTable"]["stampLineage"][0]
assert st5["ambTable"]["stampLineage"][1]["identity"] == base["ambTable"]["declaredIdentity"]
st6, _ = run(A2, master=MASTER2)                                                          # restamp_blocks overwrote corpusHash in place; the declared identity still records the previous master
A2b = copy.deepcopy(A2); A2b["_artifactStamps"]["ambTable"]["corpusHash"] = MASTER2
st6, _ = run(A2b, master=MASTER2)
assert st6["ambTable"]["stampLineage"][1]["identity"]["corpusHash"] == MASTER

# ingestion run: producers all OK -> run start is the computedAt, live raw identity written; a missing producer stage -> the prior raw identity is carried, not the live one
env = {"XT_RUN_STAGES_OK": "s_amb,s_raw1,s_raw2,other", "XT_RUN_STARTED_AT": "2026-10-25T09:00:00+00:00"}
A3 = {**A, "_artifactStamps": st2}
st7, rep7 = run(A3, manifest=MAN2, env=env)
assert st7["rawBlock"]["upstreamHashes"]["rawManifestCorpusHash"] == MAN2 and st7["rawBlock"]["computedAt"] == "2026-10-25T09:00:00+00:00" and rep7["rawBlock"]["ran"]
assert len(st7["rawBlock"]["stampLineage"]) == 2 and st7["rawBlock"]["stampLineage"][1]["identity"]["rawManifestCorpusHash"] == MAN
env2 = {"XT_RUN_STAGES_OK": "s_amb,s_raw1", "XT_RUN_STARTED_AT": "2026-10-25T09:00:00+00:00"}
st8, rep8 = run(A3, manifest=MAN2, env=env2)
assert st8["rawBlock"]["upstreamHashes"]["rawManifestCorpusHash"] == MAN and not rep8["rawBlock"]["ran"]

# outside an ingestion run (XT_RUN_STAGES_OK unset) no raw hash is written: the prior declared identity is carried
st9, rep9 = run(A3, manifest=MAN2, env={})
assert st9["rawBlock"]["upstreamHashes"]["rawManifestCorpusHash"] == MAN and not rep9["rawBlock"]["ran"]
# stage order: the declared-stamp pass runs after restamp_ingest and the config-editing stages, before build_html
_ids = [x["id"] for x in json.load(open("tools/ingest_stages.json", encoding="utf-8"))["stages"]]
assert _ids.index("extend_session_ledgers") < _ids.index("build_ambient_table") < _ids.index("restamp_ingest") < _ids.index("stamp_dependencies") < _ids.index("build_html")
assert all(_ids.index(p) < _ids.index("stamp_dependencies") for d in SC.load_deps().values() for p in d["producerStages"])

# stamp_basis honours the declared stamps and stays coherent; running it twice changes nothing
B = {**A, "_artifactStamps": st7}
d1 = SB.derive(B)
assert d1["rawBlock"]["computedAt"] == "2026-10-25T09:00:00+00:00" and d1["ambTable"]["computedAt"] == st7["ambTable"]["computedAt"]
assert d1["ambTable"].get("computedAtNote") == st7["ambTable"].get("computedAtNote")
B2 = {**B, "_artifactStamps": d1}
assert SB.derive(B2) == d1
print("test_stamp_dependencies: OK")

# R5 on the real payload (read-only): simulate the next ingestion on a copy: the master changes, restamp_blocks --regen overwrites corpusHash / generatedAt in place, every producer stage ran OK
# in the run -> lineage persists and grows by exactly one entry per declared block, the stamps stay coherent under stamp_basis, a second pass changes nothing
if os.path.exists("summary_arrays.json") and os.path.exists("raw_manifest.json"):
    R = json.load(open("summary_arrays.json", encoding="utf-8"))
    deps = SC.load_deps()
    if all((R["_artifactStamps"].get(k) or {}).get("declaredIdentity") for k in deps):
        cfg = json.load(open("summary_config.json", encoding="utf-8"))
        live_master = R["_artifactStamps"]["cohortMeta"]["corpusHash"]
        new_master, new_manifest = "e" * 32, "f" * 64
        C = copy.deepcopy(R)
        for k in deps:
            C["_artifactStamps"][k].update(corpusHash=new_master, generatedAt="2026-12-01T00:00:00+00:00", computationStatus="computed")
        stages = sorted({p for d in deps.values() for p in d["producerStages"]})
        envr = {"XT_RUN_STAGES_OK": ",".join(stages), "XT_RUN_STARTED_AT": "2026-12-01T00:00:00+00:00"}
        n1, _ = AP.derive_all(C, cfg, deps, new_master, new_manifest, envr, ROOT, False, None, "M999", None)
        for k in deps:
            assert len(n1[k]["stampLineage"]) == len(R["_artifactStamps"][k]["stampLineage"]) + 1, k
            assert n1[k]["stampLineage"][:-1] == R["_artifactStamps"][k]["stampLineage"], k            # earlier entries byte-identical
            assert n1[k]["stampLineage"][-1]["identity"]["corpusHash"] == live_master, k
        D = {**C, "_artifactStamps": n1}
        D["_artifactStamps"] = SB.derive(D)
        assert SB.check(D) == [], SB.check(D)
        n2, _ = AP.derive_all(D, cfg, deps, new_master, new_manifest, envr, ROOT, False, None, "M999", None)
        assert all(n2[k] == D["_artifactStamps"][k] for k in deps)
# gate (release_check): negative controls
Dd = {"ambTable": DEPS["ambTable"], "rawBlock": DEPS["rawBlock"]}
good, _ = run(A, backfill=True, replay={"masterMd5": MASTER, "blocks": {"ambTable": {"identical": True}}}, attest=att)
Ag = {**A, "_artifactStamps": good}
pb, inf = SC.verify_declared(Ag, CFG, Dd, MAN)
assert pb == [] and inf == []
pb, _ = SC.verify_declared(Ag, CFG, Dd, MAN2)                                   # stale raw hash on a readsRaw block -> FAIL
assert any("rawBlock" in x and "raw identity" in x for x in pb)
pb, _ = SC.verify_declared(Ag, dict(CFG, ambientByDrive={"q": 1}), Dd, MAN)    # declared config section changed -> FAIL
assert any("ambTable" in x and "ambientByDrive" in x for x in pb)
pb, _ = SC.verify_declared(Ag, dict(CFG, wording="edited"), Dd, MAN)           # undeclared section edited -> no FAIL
assert pb == []
Ab = copy.deepcopy(Ag); Ab["_artifactStamps"]["rawBlock"]["upstreamHashes"].pop("rawManifestCorpusHash")
pb, inf = SC.verify_declared(Ab, CFG, Dd, MAN)                                  # absent raw identity -> WARN only
assert pb == [] and any("rawBlock" in x for x in inf)
Ac = copy.deepcopy(Ag); Ac["_artifactStamps"]["ambTable"]["upstreamHashes"]["rawManifestCorpusHash"] = MAN
assert any("does not read raw" in x for x in SC.verify_declared(Ac, CFG, Dd, MAN)[0])    # a non-raw block carries no raw identity
assert any("not derived" in x for x in SC.verify_declared(A, CFG, Dd, MAN)[0])          # legacy stamp -> not derived
# M518: splices that rebuild a block's stamp from a clone (fuelContract / powerFadeEquivalence) keep the block's own declared fields and never inherit the clone's
import powerfade_equivalence as _PE, engine_runtime as _ER, stamp_common as _SCm
_old = {"corpusHash": "a" * 32, "declaredIdentity": {"corpusHash": "a" * 32}, "stampLineage": [{"identity": {"x": 1}}], "dependencies": {"declaredIn": "t"}, "fullConfigHashNote": "n", "generatedAt": "g"}
_clone = {"corpusHash": "z" * 32, "declaredIdentity": {"corpusHash": "clone"}, "stampLineage": [{"identity": {"clone": 1}}], "dependencies": {"declaredIn": "clone"}, "generatedAt": "g2"}
_new = _SCm.carry_declared(_old, dict(_clone))
assert _new["declaredIdentity"] == _old["declaredIdentity"] and _new["stampLineage"] == _old["stampLineage"] and _new["dependencies"] == _old["dependencies"] and _new["generatedAt"] == "g2"
_new2 = _SCm.carry_declared(None, dict(_clone))
assert not any(k in _new2 for k in _SCm.DECLARED_FIELDS)                         # a first-time stamp never inherits another block's lineage
_A = {"_artifactStamps": {"fuelContract": dict(_clone), "engineRuntime": dict(_old)}, "engineRuntime": {"v": 1}}
_n, _, _bad = _ER.splice(_A, {"v": 2}, "b" * 32)
assert _n["_artifactStamps"]["engineRuntime"]["stampLineage"] == _old["stampLineage"] and _n["_artifactStamps"]["engineRuntime"]["corpusHash"] == "b" * 32 and not _bad
print("test_stamp_dependencies (next-ingestion simulation): OK")
