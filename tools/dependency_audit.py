#!/usr/bin/env python3
"""M557 (spec analyses/M557_spec.md Rev 2): channel-dependency graph and independence audit of the evidence-ledger checks and the named negative controls (audit 2026-10-29 N08).
Declarations (hand-curated, never edited by this tool): channel_dependency_graph.json (nodes, parents, kinds) and independence_claims.json (13 claim rows: 6 ledger checks, 7 controls found by a deterministic key scan).
For every claim the tool computes, from the graph only, the ancestor sets and a CLASS (coding_check_only / circular / model_adequacy / shared_raw_input / independent_conditional_on_unverified_constant / independent; controls: negative_control when
their requirements pass), compares it with the declared class and with the pre-registered expectations, checks coverage against the evidence ledger and the payload key scan, reads the OBSERVED outcome of each control from the payload,
and reports wording conflicts without changing any validationStatus. Pure metadata and logic: no raw pass for the classes (the header check reads raw headers only). Modes: --check (writes analyses/M557_check.json) | --splice (check + additive
write of S.channelDependency). Usage: python tools/dependency_audit.py --check|--splice"""
import copy, datetime, hashlib, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M557_check.json")
GRAPH = os.path.join(ROOT, "channel_dependency_graph.json")
CLAIMS = os.path.join(ROOT, "independence_claims.json")
KINDS = ("raw_logged", "app_calculated", "latent_unlogged", "derived", "constant", "model_output", "external_reference")
DATA_KINDS = ("raw_logged", "app_calculated", "latent_unlogged", "external_reference")
AUDIT_ITEM = {"E1": 1, "E2": 2, "E3": 3, "E4": 4, "E5": 5, "E6": 6, "C1": 7, "C2": 8, "C3": 9, "C4": 10, "C5": 11, "C6": 12, "C7": 13}
PRE_REGISTERED = {"E1": "coding_check_only", "E2": "shared_raw_input", "E3": "circular", "E4": "model_adequacy", "E5": "model_adequacy", "E6": "shared_raw_input"}


# ---------------------------------------------------------------- kernel (pure, unit-tested)
def index(graph):
    return {n["id"]: n for n in graph["nodes"]}


def validate_graph(graph):
    """schema problems of the graph (empty list = valid): kinds, parents exist, acyclic, app_calculated and target / command nodes carry a parent."""
    nodes = index(graph)
    probs = []
    for n in graph["nodes"]:
        for k in ("id", "label", "kind", "source", "parents", "derivation"):
            if k not in n:
                probs.append((n.get("id"), "missing " + k))
        if n.get("kind") not in KINDS:
            probs.append((n.get("id"), "bad kind"))
        for p in n.get("parents", []):
            if p not in nodes:
                probs.append((n["id"], "unknown parent " + p))
        if n.get("kind") == "app_calculated" and not n.get("parents"):
            probs.append((n["id"], "app_calculated node without a declared parent"))
        if re.search(r"(target|commanded)", n["id"]) and n.get("kind") == "raw_logged" and not n.get("parents"):
            probs.append((n["id"], "target / command node without a declared parent"))
        if n.get("sameDerivationAs") and n["sameDerivationAs"] not in nodes:
            probs.append((n["id"], "unknown sameDerivationAs"))
        rn = n.get("responseNode")
        if rn is not None:
            if n.get("kind") != "model_output":
                probs.append((n["id"], "responseNode on a node that is not a model_output"))
            elif rn not in nodes or nodes[rn].get("kind") != "derived" or rn not in n.get("parents", []):
                probs.append((n["id"], "responseNode must be a derived parent of the declaring node"))
    # acyclic: depth-first colouring
    colour = {}
    def dfs(u, stack):
        colour[u] = 1
        for p in nodes[u].get("parents", []):
            if p in nodes:
                if colour.get(p) == 1:
                    probs.append((u, "cycle through " + p))
                elif colour.get(p) is None:
                    dfs(p, stack)
        colour[u] = 2
    for u in nodes:
        if colour.get(u) is None:
            dfs(u, [])
    return probs


def ancestors(nodes, nid):
    seen, stack = set(), list(nodes[nid].get("parents", []))
    while stack:
        u = stack.pop()
        if u not in seen:
            seen.add(u); stack.extend(nodes[u].get("parents", []))
    return seen


def descendants(nodes, nid):
    return {u for u in nodes if nid in ancestors(nodes, u)}


def classify(nodes, target, validators):
    """computed class of a (target, validators) pair; returns (class, shared data ancestors, shared constants)."""
    vs = list(validators)
    if target in vs:
        return "circular", set(), set()
    ta = ancestors(nodes, target)
    for v in vs:
        if nodes[v].get("sameDerivationAs") == target or nodes[target].get("sameDerivationAs") == v:
            return "coding_check_only", ta & ancestors(nodes, v) & {u for u in nodes if nodes[u]["kind"] in DATA_KINDS}, set()
    for v in vs:
        va = ancestors(nodes, v)
        if v in ta or target in va:
            if nodes[target]["kind"] == "model_output" and nodes[v]["kind"] == "model_output" and target in va:
                return "model_adequacy", set(), set()
            return "circular", set(), set()
    shared = set()
    for v in vs:
        shared |= ta & ancestors(nodes, v)
    data = {u for u in shared if nodes[u]["kind"] in DATA_KINDS}
    unverified = {u for u in shared if nodes[u]["kind"] == "constant" and not nodes[u].get("verified", True)}
    # M565 R2b: nested specifications fitted to the same declared response are model_adequacy; the shared ancestors are returned unchanged (the rule changes the class, not the evidence)
    rn = nodes[target].get("responseNode")
    if rn and vs and nodes[target]["kind"] == "model_output" and all(nodes[v]["kind"] == "model_output" and nodes[v].get("responseNode") == rn for v in vs):
        return "model_adequacy", data, unverified
    if data:
        return "shared_raw_input", data, unverified
    if unverified:
        return "independent_conditional_on_unverified_constant", set(), unverified
    return "independent", set(), set()


def control_problems(nodes, claim, allowed_outcomes):
    probs = []
    if not claim.get("nullMechanism"):
        probs.append("no null mechanism")
    if claim.get("expectedOutcome") not in allowed_outcomes:
        probs.append("expectedOutcome missing or not allowed")
    if claim["target"] in descendants(nodes, claim["validators"][0]) if claim["validators"] else False:
        probs.append("the control target is a descendant of the control")
    return probs


def scalar_leaves(x, limit=10, prefix=""):
    out = {}
    if isinstance(x, dict):
        for k, v in x.items():
            if len(out) >= limit:
                break
            if isinstance(v, (bool, int, float)) or (isinstance(v, str) and len(v) <= 90):
                out[prefix + k] = v
            elif isinstance(v, (dict, list)):
                for kk, vv in scalar_leaves(v, limit - len(out), prefix + k + ".").items():
                    out[kk] = vv
    elif isinstance(x, list):
        for i, v in enumerate(x[:4]):
            for kk, vv in scalar_leaves(v, limit - len(out), prefix + f"[{i}]").items():
                out[kk] = vv
    return out


def scan_controls(payload, scan):
    pat = re.compile(scan["keyPattern"])
    excl = scan["exclusions"]
    hits, excluded_seen = [], set()
    def walk(x, p):
        if isinstance(x, dict):
            for k, v in x.items():
                if k.startswith("_") or (p == "" and k == "channelDependency"):   # M565: the tool's own output block is never scanned (a re-run would find its own keys)
                    continue
                if pat.match(k):
                    if k in excl:
                        excluded_seen.add(k)
                    else:
                        hits.append(p + "/" + k)
                walk(v, p + "/" + k)
        elif isinstance(x, list):
            for i, v in enumerate(x[:50]):
                walk(v, p + f"[{i}]")
    walk(payload, "")
    return sorted(hits), excluded_seen


def get_path(payload, path):
    x = payload
    for k in path.strip("/").split("/"):
        x = x[k]
    return x


# ---------------------------------------------------------------- driver
def raw_headers():
    raw_dir = os.environ.get("XT_RAW_DIR", os.path.join(ROOT, "raw"))
    import pandas as pd
    hs = set()
    for f in os.listdir(raw_dir):
        if f.endswith(".csv"):
            try:
                hs.update(pd.read_csv(os.path.join(raw_dir, f), nrows=0).columns)
            except Exception:
                pass
    return hs


def main():
    mode = "--splice" if "--splice" in sys.argv else "--check"
    graph = json.load(open(GRAPH, encoding="utf-8")); claims = json.load(open(CLAIMS, encoding="utf-8"))
    A = json.load(open(ARR, encoding="utf-8"))
    nodes = index(graph)
    res = {"milestone": "M557", "mode": mode, "graphSha256": hashlib.sha256(open(GRAPH, "rb").read()).hexdigest(), "claimsSha256": hashlib.sha256(open(CLAIMS, "rb").read()).hexdigest()}
    probs = validate_graph(graph)
    res["graphProblems"] = probs
    stops = []
    if probs:
        stops.append(("graph schema / acyclic (KA5)", probs[:5]))
    # KA6: header strings of raw_logged / app_calculated nodes exist in a raw file
    hdrs = raw_headers()
    miss_hdr = [n["id"] for n in graph["nodes"] if n["kind"] in ("raw_logged", "app_calculated") and n["source"] not in hdrs]
    res["headerCheck"] = {"nodes": sum(1 for n in graph["nodes"] if n["kind"] in ("raw_logged", "app_calculated")), "missing": miss_hdr}
    if miss_hdr:
        stops.append(("KA6 header strings not found in raw", miss_hdr))
    # coverage (KA4)
    ledger_checks = [(r["sourceKey"], i) for r in A["evidenceLedger"]["rows"] for i in range(len(r["checks"]))]
    claimed_ledger = [(c["ledgerRef"]["sourceKey"], c["ledgerRef"]["checkIndex"]) for c in claims["claims"] if c["origin"] == "ledger"]
    hits, excl_seen = scan_controls(A, claims["scan"])
    claimed_ctrl = sorted(c["payloadPath"] for c in claims["claims"] if c["origin"] == "control")
    cov = {"ledgerChecks": len(ledger_checks), "ledgerChecksWithoutClaim": [x for x in ledger_checks if x not in claimed_ledger], "claimsWithoutLedgerCheck": [x for x in claimed_ledger if x not in ledger_checks],
           "duplicateLedgerClaims": len(claimed_ledger) - len(set(claimed_ledger)), "scanHits": hits, "scanHitsWithoutClaim": [h for h in hits if h not in claimed_ctrl], "controlClaimsWithoutHit": [h for h in claimed_ctrl if h not in hits],
           "exclusionsSeen": sorted(excl_seen), "exclusionsWithoutJustification": [k for k in excl_seen if not claims["scan"]["exclusions"].get(k)]}
    res["coverage"] = cov
    if cov["ledgerChecksWithoutClaim"] or cov["claimsWithoutLedgerCheck"] or cov["duplicateLedgerClaims"] or cov["scanHitsWithoutClaim"] or cov["controlClaimsWithoutHit"] or cov["exclusionsWithoutJustification"]:
        stops.append(("KA4 coverage", {k: v for k, v in cov.items() if v and k not in ("ledgerChecks", "scanHits", "exclusionsSeen")}))
    if stops:
        res["STOP"] = stops
        json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1, default=str)
        print(json.dumps({"STOP": stops}, default=str)); sys.exit(2)
    rows = {r["sourceKey"]: r for r in A["evidenceLedger"]["rows"]}
    ap = os.path.join(ROOT, "analyses", "M557_audit_result.json")
    audit = json.load(open(ap, encoding="utf-8")) if os.path.exists(ap) else {}
    res["auditResultSha256"] = hashlib.sha256(open(ap, "rb").read()).hexdigest() if os.path.exists(ap) else None
    out_claims, conflicts, triggers = [], [], []
    for c in claims["claims"]:
        t, vs = c["target"], c["validators"]
        for u in [t] + vs:
            assert u in nodes, u
        row = {"id": c["id"], "origin": c["origin"], "target": t, "targetLabel": nodes[t]["label"], "validators": vs, "validatorLabels": [nodes[v]["label"] for v in vs], "declaredClass": c["declaredClass"],
               "channelAxis": c["channelAxis"], "sampleAxis": c["sampleAxis"], "algorithmAxis": c["algorithmAxis"]}
        cls, shared, unver = classify(nodes, t, vs)
        row["relation"] = cls
        row["sharedDataAncestors"] = sorted(shared); row["sharedUnverifiedConstants"] = sorted(unver)
        row["targetDataAncestors"] = sorted(u for u in ancestors(nodes, t) if nodes[u]["kind"] in DATA_KINDS)
        row["validatorDataAncestors"] = sorted({u for v in vs for u in ancestors(nodes, v) if nodes[v]["kind"] != "constant" and nodes[u]["kind"] in DATA_KINDS})
        if c["origin"] == "control":
            cp = control_problems(nodes, c, claims["expectedOutcomes"])
            row["computedClass"] = ("decision_rule" if c["expectedOutcome"] == "decision_rule" else "negative_control") if not cp else "control_requirements_failed"
            row["controlProblems"] = cp; row["expectedOutcome"] = c["expectedOutcome"]; row["nullMechanism"] = c["nullMechanism"]
            blk = get_path(A, c["payloadPath"])
            obs = scalar_leaves(blk)
            row["observedOutcome"] = obs
            moved = None
            for k, v in (blk.items() if isinstance(blk, dict) else []):
                if isinstance(v, dict) and "movementDetected" in v:
                    moved = (moved or []) + [(k, v["movementDetected"])]
            if moved is not None:
                row["movementByKey"] = dict(moved)
                if c["expectedOutcome"] == "null" and any(m for _, m in moved) or c["expectedOutcome"] in ("nonnull", "nonnull_one_sided") and not all(m for _, m in moved):
                    triggers.append((c["id"], "control moved against its expectedOutcome"))
            if not obs:
                triggers.append((c["id"], "no recorded outcome"))
            if "measured" in json.dumps(blk).lower():
                row["wordingFlags"] = ["the payload block text uses the word 'measured' (reported, not changed)"]
            if cp:
                triggers.append((c["id"], "; ".join(cp)))
        else:
            row["computedClass"] = cls
            lr = c["ledgerRef"]; lrow = rows[lr["sourceKey"]]; chk = lrow["checks"][lr["checkIndex"]]
            row["ledgerCheckLabel"] = chk["label"]; row["currentValidationStatus"] = chk.get("validationStatus"); row["rowValidationStatus"] = lrow.get("validationStatus"); row["evidenceClass"] = lrow.get("evidenceClass")
            wording = []
            def _hits(txt_):
                pos = [m for m in re.finditer(r"\bindependent(ly)?\b", txt_) if not re.search(r"\b(not|non|never)\b[^.;]{0,40}$", txt_[:m.start()])]
                neg = [m for m in re.finditer(r"\bindependent(ly)?\b", txt_) if re.search(r"\b(not|non|never)\b[^.;]{0,40}$", txt_[:m.start()])]
                return pos, neg
            lab_pos, lab_neg = _hits(chk["label"].lower()); note_pos, _ = _hits((lrow.get("notes") or "").lower())
            claims_indep = lab_pos or (note_pos and not lab_neg)         # a check whose own label negates independence is not charged with the row notes
            if claims_indep and cls in ("circular", "coding_check_only", "shared_raw_input", "model_adequacy"):
                wording.append("the ledger text says 'independent' but the computed class is " + cls)
            if lrow.get("evidenceClass") == "measured" and nodes[t]["kind"] in ("derived", "model_output"):
                wording.append("evidenceClass 'measured' on a " + nodes[t]["kind"] + " quantity")
            row["wordingConflicts"] = wording
            if wording:
                conflicts.append(c["id"])
            if wording and any("independent" in w for w in wording):
                triggers.append((c["id"], wording[0]))
            if unver:
                triggers.append((c["id"], "shares a verified:false constant: " + ",".join(sorted(unver))))
            if c["id"] in PRE_REGISTERED and cls != PRE_REGISTERED[c["id"]]:
                triggers.append((c["id"], f"computed {cls} differs from the pre-registered {PRE_REGISTERED[c['id']]}"))
        row["settledClass"] = c.get("settledClass") or row["computedClass"]
        if c.get("settledClass"):
            row["settledBy"] = c["settledBy"]
        if c.get("settledRelation"):
            row["settledRelation"] = c["settledRelation"]; row["settledBy"] = c["settledBy"]
        row["auditNotes"] = c.get("auditNotes", [])
        if c["id"] in PRE_REGISTERED:
            row["preRegisteredClass"] = PRE_REGISTERED[c["id"]]
            row["preRegisteredExpectationMet"] = bool(row["settledClass"] == PRE_REGISTERED[c["id"]])
        aud = audit.get(str(AUDIT_ITEM.get(c["id"], "")))
        if aud:
            row["auditor"] = {"class": aud.get("class"), "relation": aud.get("underlyingRelation"), "sharedInputs": aud.get("shared")}
            row["ancestorDisagreement"] = sorted(set(aud.get("shared") or []) - set(row["sharedDataAncestors"])) != [] and bool(row["sharedDataAncestors"] or aud.get("shared"))
        if c["id"] == "C2":
            ov = os.path.join(ROOT, "analyses", "M557_c2_overlap.json")
            if os.path.exists(ov):
                row["poolControlOverlap"] = json.load(open(ov, encoding="utf-8"))
        if c["declaredClass"] != row["computedClass"]:
            triggers.append((c["id"], f"declared {c['declaredClass']} differs from computed {row['computedClass']}"))
        out_claims.append(row)
    res["claims"] = out_claims
    res["nodeCounts"] = {k: sum(1 for n in graph["nodes"] if n["kind"] == k) for k in KINDS}
    res["conflictClaims"] = conflicts; res["triggers"] = triggers
    res["preRegisteredNotMet"] = [r["id"] for r in out_claims if r.get("preRegisteredExpectationMet") is False]
    res["settledOverrides"] = [r["id"] for r in out_claims if r["settledClass"] != r["computedClass"] or r.get("settledRelation")]
    try:
        sv = A.get("signalValidity", {}).get("entries", [])
        cols = {e["column"] for e in sv}
        res["reconciliation"] = {"signalValidityColumnsAlsoNodes": sorted(n["source"] for n in graph["nodes"] if n["source"] in cols), "note": "the M556 registry channels (BMS 12 V, intake air, supply voltages) are not used by any claim; no overlap is expected"}
    except Exception:
        res["reconciliation"] = None
    res["classCounts"] = {}
    for r in out_claims:
        res["classCounts"][r["computedClass"]] = res["classCounts"].get(r["computedClass"], 0) + 1
    json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1, default=str)
    print(json.dumps({"ok": True, "classCounts": res["classCounts"], "conflicts": conflicts, "triggers": triggers, "nodeCounts": res["nodeCounts"]}, default=str))
    if mode == "--splice":
        splice(res)


def splice(res):
    """additive write of S.channelDependency (+ stamp); no existing key changes."""
    block = {"_provenance": "GENERATED by tools/dependency_audit.py (M557). Do not hand-edit; the declarations are channel_dependency_graph.json and independence_claims.json (hand-curated, reviewed).", "schemaVersion": 1,
             "inputs": {"graphSha256": res["graphSha256"], "claimsSha256": res["claimsSha256"], "driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()},
             "rule": {"classes": "coding_check_only (same derivation) / circular (ancestor, descendant or the target inside the validator set) / model_adequacy (same model re-split or richer order, or nested specifications that declare the same responseNode, M565) / shared_raw_input / independent_conditional_on_unverified_constant / independent",
                      "controls": "negative_control when a null mechanism, an expected outcome and a target that is not a descendant of the control are present; the observed outcome is read from the payload",
                      "conflicts": "a wording conflict is reported beside the ledger row; no validationStatus is changed here"},
             "nodeCounts": res["nodeCounts"], "headerCheck": res["headerCheck"], "coverage": res["coverage"], "claims": res["claims"], "classCounts": res["classCounts"], "conflictClaims": res["conflictClaims"], "triggers": res["triggers"], "preRegisteredNotMet": res["preRegisteredNotMet"], "settledOverrides": res["settledOverrides"],
             "blindAudit": {"resultSha256": res.get("auditResultSha256"), "note": "settled by the Director after the blind audit; computedClass is what the R2 rule outputs from the graph, settledClass is a Director override (R2 cannot see two model_output siblings that share a derived response and rows)"}, "reconciliation": res["reconciliation"],
             "limits": ["the declarations are hand-curated and reviewed; the tool computes classes from them but does not discover dependencies from code", "a class describes the relation of a check to its target, not whether the check is useful: a shared-input or model-adequacy check can still be informative",
                        "no validationStatus is lowered here; conflicts are reported for a separate Director ruling", "latent inputs (inside the app, the ECU or the VCM) are declared, not observed"]}
    block = json.loads(json.dumps(block, default=str))
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("channelDependency", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    stamps_before = {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "channelDependency"}
    A2["channelDependency"] = block
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=block["inputs"]["driveMasterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M557: computed by tools/dependency_audit.py from the hand-curated declarations and the payload; additive, no published value recomputed.", upstreamHashes={"graphSha256": res["graphSha256"], "claimsSha256": res["claimsSha256"]})
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A2["_artifactStamps"]["channelDependency"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    assert stamps_before == {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "channelDependency"}
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)
    print(json.dumps({"channelDependency": "written"}))


if __name__ == "__main__":
    main()
