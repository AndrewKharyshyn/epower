#!/usr/bin/env python3
"""M513 (analyses/M513_spec.md Rev 2): stamps of DECLARED blocks are derived from tools/stamp_dependencies.json only.
`declaredIdentity` is the identity the stamp was last derived for {corpusHash, rawManifestCorpusHash, rawIdentitySource, configSectionHashes, inputFileMd5}; when the identity VALUES change
(never on generatedAt alone) the previous declaredIdentity is appended to the append-only `stampLineage` before it is replaced, so an in-place overwrite by restamp_blocks cannot lose it.
Pure functions: no file writes here."""
import copy, hashlib, json, os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEPS = os.path.join(ROOT, "tools", "stamp_dependencies.json")
IDENTITY_KEYS = ("corpusHash", "rawManifestCorpusHash", "configSectionHashes", "inputFileMd5")


def load_deps(path=DEPS):
    return json.load(open(path, encoding="utf-8"))["blocks"]


def section_hash(cfg, name):
    """md5 of the canonical JSON of one summary_config.json section (None when the section is absent)."""
    if name not in cfg:
        return None
    return hashlib.md5(json.dumps(cfg[name], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def file_md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest() if os.path.exists(path) else None


def identity(deps, master_md5, cfg, root, raw_manifest_hash=None, raw_source=None):
    """The identity of a declared block: only what the declaration says it depends on."""
    d = {"corpusHash": master_md5,
         "configSectionHashes": {n: section_hash(cfg, n) for n in deps.get("configSections", [])},
         "inputFileMd5": {f: file_md5(os.path.join(root, f)) for f in deps.get("inputFiles", [])}}
    if deps.get("readsRaw") or deps.get("readsRawManifest"):
        d["rawManifestCorpusHash"] = raw_manifest_hash
        d["rawIdentitySource"] = raw_source
    return d


def same_identity(a, b):
    return all(json.dumps((a or {}).get(k), sort_keys=True) == json.dumps((b or {}).get(k), sort_keys=True) for k in IDENTITY_KEYS)


def derive_stamp(stamp, new_identity, milestone, reason, now_iso):
    """Returns (new_stamp, appended). `stamp` is not modified. Keeps every other field of the stamp as it is."""
    s = copy.deepcopy(stamp)
    prior = s.get("declaredIdentity")
    lineage = list(s.get("stampLineage") or [])
    appended = False
    if prior is None:
        # first derivation: the legacy identity fields are the historical identity and go to the lineage
        legacy = {"corpusHash": s.get("corpusHash"), "upstreamHashes": s.get("upstreamHashes"), "fullConfigHash": s.get("fullConfigHash"), "generatedAt": s.get("generatedAt"),
                  "reissuedFrom": s.get("reissuedFrom"), "reissueNote": s.get("reissueNote")}
        lineage.append({"identity": {k: v for k, v in legacy.items() if v is not None}, "supersededAtMilestone": milestone, "supersededAt": now_iso,
                        "reason": "legacy stamp metadata (M294 raw-manifest backfill, M284 whole-config hash, fields cloned from another block) replaced by stamp metadata re-derived from declared dependencies"})
        appended = True
    elif not same_identity(prior, new_identity):
        lineage.append({"identity": prior, "supersededAtMilestone": milestone, "supersededAt": now_iso, "reason": reason})
        appended = True
    s["declaredIdentity"] = new_identity
    s["stampLineage"] = lineage
    s["corpusHash"] = new_identity["corpusHash"]
    up = {"driveMasterMd5": new_identity["corpusHash"]}
    if new_identity.get("rawManifestCorpusHash"):
        up["rawManifestCorpusHash"] = new_identity["rawManifestCorpusHash"]
        up["rawIdentitySource"] = new_identity.get("rawIdentitySource")
    up["configSectionHashes"] = new_identity.get("configSectionHashes") or {}
    up["inputFileMd5"] = new_identity.get("inputFileMd5") or {}
    s["upstreamHashes"] = up
    s["fullConfigHash"] = None
    s["fullConfigHashNote"] = ("whole-config hash retired for declared blocks (M513): the stamp names the md5 of each computational config section it reads "
                               "(upstreamHashes.configSectionHashes); the previous value is kept in stampLineage")
    s["dependencies"] = {"declaredIn": "tools/stamp_dependencies.json", "milestone": milestone}
    for k in ("reissuedFrom", "reissueNote"):
        s.pop(k, None)
    return s, appended


def verify_declared(A, cfg, deps, live_manifest):
    """M513 gate (release_check): returns (problems, infos) for the declared blocks. A problem FAILS the release: a declared block whose stamp was not derived from its declaration, whose
    config-section hashes differ from the live config sections, or whose raw identity (readsRaw / readsRawManifest) is present but differs from the live raw_manifest corpusHash. An absent raw
    identity (evidence missing, R7) is an info (WARN), never a pass-by-default."""
    problems, infos = [], []
    for k, d in deps.items():
        s = (A.get("_artifactStamps") or {}).get(k)
        if not s:
            problems.append("%s: no stamp" % k); continue
        di = s.get("declaredIdentity")
        if not di or not s.get("dependencies"):
            problems.append("%s: stamp not derived from the declared dependencies" % k); continue
        for name in d.get("configSections", []):
            if (di.get("configSectionHashes") or {}).get(name) != section_hash(cfg, name):
                problems.append("%s: config section %s differs from the live summary_config.json" % (k, name))
        if d.get("readsRaw") or d.get("readsRawManifest"):
            r = (s.get("upstreamHashes") or {}).get("rawManifestCorpusHash")
            if r is None:
                infos.append("%s: raw identity absent (evidence missing)" % k)
            elif r != live_manifest:
                problems.append("%s: raw identity %s differs from the live raw_manifest corpusHash %s" % (k, r[:12], (live_manifest or "")[:12]))
        elif (s.get("upstreamHashes") or {}).get("rawManifestCorpusHash") is not None:
            problems.append("%s: a block that does not read raw carries a raw-manifest identity" % k)
    for k, st in (A.get("_artifactStamps") or {}).items():          # M518: an undeclared block never carries another block's declared-dependency fields (a cloned stamp)
        if k not in deps and isinstance(st, dict) and any(f in st for f in DECLARED_FIELDS):
            problems.append("%s: an undeclared stamp carries declared-dependency fields (cloned from a declared block)" % k)
    return problems, infos


DECLARED_FIELDS = ("declaredIdentity", "stampLineage", "dependencies", "fullConfigHashNote")


def carry_declared(old, new):
    """M518: a splice that rebuilds a block's stamp from another block's stamp (copy of fuelContract / powerFadeEquivalence) must neither inherit that block's declared-dependency fields nor lose its own:
    the clone's declared fields are removed and the block's own previous ones (declaredIdentity, append-only stampLineage, dependencies) are carried over, so tools/stamp_dependencies_apply.py
    keeps appending to the same lineage at the next ingestion. Returns `new` (modified in place)."""
    for k in DECLARED_FIELDS:
        new.pop(k, None)
    if old and old.get("declaredIdentity"):
        for k in DECLARED_FIELDS:
            if k in old:
                new[k] = copy.deepcopy(old[k])
    return new
