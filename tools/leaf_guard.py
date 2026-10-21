#!/usr/bin/env python3
"""Lost-leaf guard (M377a, analyses/M377_spec.md Rev 2 P6). An ingestion rebuild must not silently drop keys that the previous (committed)
summary_arrays.json carried: the M376 run lost 371 leaves (additive keys written by one-off splices, a frozen audit record, restamp notes).
A leaf of the previous arrays that is absent as ANY node (leaf or container) in the current arrays is "lost". A loss is EXPECTED only when it
matches a rule in analyses/leaf_guard_rules.json (id, rationale, milestone, pathTemplate, condition) AND the rule's data condition holds; every
other loss is UNEXPECTED and the tool exits 1. The Director owns the rule list; a rule change needs a spec.
pathTemplate: segments separated by "/", each an exact key, or a single-segment placeholder: {i} = a list index, {key} = one dict key (the
condition then checks that key). No other wildcard exists. A rule with "matchPrefix": true matches every lost leaf UNDER the template (the template
names a block, e.g. a block that is null in the current arrays).
Conditions (registered below): stamp_hash_changed | parent_null_in_current | sibling_present(sibling) | field_changed(entryDepth, field) |
cohort_min_support_crossed | placeholder_row_observed | moved_to_complement_list | field_changed_and_empty (M426, analyses/M426_spec.md).
Usage: python tools/leaf_guard.py [--previous git:HEAD | PATH] [--current summary_arrays.json] [--rules PATH] [--out PATH]"""
import argparse, json, os, subprocess, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def nodes(o, p=(), out=None):
    out = set() if out is None else out
    out.add(p)
    if isinstance(o, dict):
        for k, v in o.items():
            nodes(v, p + (k,), out)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            nodes(v, p + (i,), out)
    return out


def leaves(o, p=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leaves(v, p + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from leaves(v, p + (i,))
    else:
        yield p


def get(o, p):
    for k in p:
        o = o[k]
    return o


def match(template, path, prefix=False):
    """Return the bound placeholders (dict) or None."""
    seg = template.split("/")
    if prefix:
        if len(path) <= len(seg):
            return None
        path = path[:len(seg)]
    elif len(seg) != len(path):
        return None
    bound = {}
    for s, k in zip(seg, path):
        if s == "{i}":
            if not isinstance(k, int):
                return None
        elif s == "{key}":
            if not isinstance(k, str):
                return None
            bound["key"] = k
        elif s != str(k):
            return None
    return bound


def cond_stamp_hash_changed(prev, cur, path, bound, rule):
    k = bound.get("key")
    try:
        a, b = prev["_artifactStamps"][k]["corpusHash"], cur["_artifactStamps"][k]["corpusHash"]
    except (KeyError, TypeError):
        return False
    return a != b


def cond_parent_null_in_current(prev, cur, path, bound, rule):
    n = len(rule["pathTemplate"].split("/")) if rule.get("matchPrefix") else 1
    n = len(path) - n if rule.get("matchPrefix") else 1
    try:
        return get(cur, path[:len(path) - n]) is None
    except (KeyError, IndexError, TypeError):
        return False


def cond_sibling_present(prev, cur, path, bound, rule):
    try:
        par = get(cur, path[:-1])
    except (KeyError, IndexError, TypeError):
        return False
    return isinstance(par, dict) and bool(par.get(rule["sibling"]))


def cond_field_changed(prev, cur, path, bound, rule):
    """The entry n levels up from the lost leaf (entryDepth = its length as a path prefix) has a field whose value differs between the previous and the current arrays."""
    ent = path[:rule["entryDepth"]]
    try:
        return get(prev, ent + (rule["field"],)) != get(cur, ent + (rule["field"],))
    except (KeyError, IndexError, TypeError):
        return False


def _unrender(fmt, key):
    """Inverse of fmt.replace('{c}', c): the cohort name inside a key such as 'cohort cold_insufficient' (None when the key does not fit)."""
    pre, _, suf = fmt.partition("{c}")
    if key.startswith(pre) and key.endswith(suf) and len(key) > len(pre) + len(suf):
        return key[len(pre):len(key) - len(suf)]
    return None


def _min_support(prev, cur):
    """(min drives, min days) of the cohort support rule when it is IDENTICAL in the previous and the current arrays, else None (a changed rule is not a data effect)."""
    try:
        pm = prev["seasonalCharts"]["_meta"]["cohortSuppressedBelowMinSupport"]["minDrivesForStatistics"]
        cm = cur["seasonalCharts"]["_meta"]["cohortSuppressedBelowMinSupport"]["minDrivesForStatistics"]
        pd_, cd = prev["comparisonCube"]["_meta"]["minSupport"], cur["comparisonCube"]["_meta"]["minSupport"]
    except (KeyError, TypeError):
        return None
    if pm != cm or pd_ != cd or pd_.get("drives") != pm:
        return None
    return pm, pd_["days"]


def cond_field_changed_and_empty(prev, cur, path, bound, rule):
    """M426 (Director ruling, re-binning of the regen-by-temperature chart). Like field_changed (the entry entryDepth levels up has a `field` that differs between the
    previous and the current arrays) AND the current entry is EMPTY: n == 0 and eff is None. A leaf may vanish only from a row whose bin was renamed and now holds no samples
    (a layout artefact of the new bin scheme, never a populated bin losing its range)."""
    if not cond_field_changed(prev, cur, path, bound, rule):
        return False
    try:
        row = get(cur, path[:rule["entryDepth"]])
        return row.get("n") == 0 and row.get("eff") is None
    except (KeyError, IndexError, TypeError, AttributeError):
        return False


def cond_cohort_min_support_crossed(prev, cur, path, bound, rule):
    """M426 (Director ruling). A cohort-suppression leaf may vanish only because the cohort CROSSED the pre-registered support rule: the rule (min drives, min days)
    is unchanged; the cohort was not inference-available before and is now (eligibleForCohortView >= min drives, nDaysObserved >= min days) and is no longer listed
    in cohortSuppressedBelowMinSupport.nObserved. Optional rule keys: keyFormat (the bound key is e.g. 'cohort {c}_insufficient'), currentKeyFormat (the renamed key
    must exist in the same container of the current arrays), prevValue (the lost leaf's previous value), curCountField (the sibling block in the current arrays has
    this count >= min drives)."""
    key = bound.get("key")
    c = _unrender(rule["keyFormat"], key) if rule.get("keyFormat") else key
    ms = _min_support(prev, cur)
    if c is None or ms is None:
        return False
    m, dmin = ms
    try:
        pc, cc = prev["cohortMeta"][c], cur["cohortMeta"][c]
        if pc.get("inferenceAvailable") is True:
            return False
        if cc.get("inferenceAvailable") is not True or cc["eligibleForCohortView"] < m or cc["nDaysObserved"] < dmin:
            return False
        if c in cur["seasonalCharts"]["_meta"]["cohortSuppressedBelowMinSupport"]["nObserved"]:
            return False
        if rule.get("currentKeyFormat"):
            tpl = rule["pathTemplate"].split("/")
            new_blk = get(cur, tuple(tpl[:-1]))[rule["currentKeyFormat"].replace("{c}", c)]
            if rule.get("matchPrefix"):
                get(new_blk, path[len(tpl):])         # the lost leaf must have its counterpart at the same relative path in the renamed block
        if "prevValue" in rule and get(prev, path) != rule["prevValue"]:
            return False
        if rule.get("curCountField"):
            blk = get(cur, path[:-1])
            if not isinstance(blk, dict) or not isinstance(blk.get(rule["curCountField"]), (int, float)) or blk[rule["curCountField"]] < m:
                return False
    except (KeyError, IndexError, TypeError):
        return False
    return True


def cond_placeholder_row_observed(prev, cur, path, bound, rule):
    """M426. A 'not_observed' placeholder class row may lose its placeholder leaves (allowedLeaves only) when the SAME class row (classKey in the previous row ==
    classKey or key in the current row) is now an observed row: no 'status' leaf and at least one of observedFields non-null (a count field 'n' / 'drives' must be >= 1)."""
    ent = path[:rule["entryDepth"]]
    if len(path) != len(ent) + 1 or path[-1] not in rule["allowedLeaves"]:
        return False
    try:
        pr, cr = get(prev, ent), get(cur, ent)
        if pr.get("status") != "not_observed" or "status" in cr or pr.get("classKey") is None:
            return False
        if cr.get("classKey", cr.get("key")) != pr["classKey"]:
            return False
        vals = [cr.get(f) for f in rule["observedFields"]]
        if not any(v is not None for v in vals):
            return False
        return all(cr[f] >= 1 for f in ("n", "drives") if cr.get(f) is not None)          # any count the row carries must be >= 1
    except (KeyError, IndexError, TypeError, AttributeError):
        return False


def cond_moved_to_complement_list(prev, cur, path, bound, rule):
    """M426. A list entry may vanish from rowsIncludingZero (lostListField) only because the row names moved to the complement list: the current list is shorter, every
    dropped name is now in the complement list, the union of row names is unchanged and the classification is unchanged (a flip fails and goes to the Director)."""
    try:
        rr_p, rr_c = get(prev, path[:-2]), get(cur, path[:-2])
        a, b = rule["listField"], rule["complementField"]
        if path[-2] != a:
            return False
        dropped = set(rr_p[a]) - set(rr_c[a])
        return (len(rr_c[a]) < len(rr_p[a]) and dropped <= set(rr_c[b]) and set(rr_p[a]) | set(rr_p[b]) == set(rr_c[a]) | set(rr_c[b])
                and rr_p.get("classification") == rr_c.get("classification"))
    except (KeyError, IndexError, TypeError, AttributeError):
        return False


def _refit_transition_ok(prev, cur, rule):
    """M463 (Director ruling, analyses/M463_leaf_guard_addendum.md): the exact one-shot M119-v2 refit transition. Previous block carriedForward at prevCorpus drives, current block
    fresh at curCorpus drives with frozenBasis false. The exact previous/current values make it unable to fire on any later ingestion."""
    try:
        p, c = prev["socHysteresisV2"], cur["socHysteresisV2"]
        return (p.get("recomputeMode") == rule["prevMode"] and p.get("corpusSizeAtRecompute") == rule["prevCorpus"] and c.get("recomputeMode") == rule["curMode"]
                and c.get("corpusSizeAtRecompute") == rule["curCorpus"] and c.get("frozenBasis") is False)
    except (KeyError, TypeError, AttributeError):
        return False


def cond_refit_recompute_transition(prev, cur, path, bound, rule):
    """M463. A leaf of the M119-v2 block (or of its artifact stamp) may vanish only inside the declared refit transition AND only as a shrink: the block named by the rule
    template (for a prefix rule) or the parent container (for an exact rule) must still exist, non-null, in the current arrays (a deleted block fails)."""
    if not _refit_transition_ok(prev, cur, rule):
        return False
    n = rule.get("anchorDepth") or len(rule["pathTemplate"].split("/"))        # anchorDepth: the container that must still exist (default: the template block)
    anchor = path[:n] if (rule.get("matchPrefix") or rule.get("anchorDepth")) else path[:-1]
    try:
        return get(cur, anchor) is not None
    except (KeyError, IndexError, TypeError):
        return False


def _sha256_file(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def cond_f03_list_cleared_by_refit(prev, cur, path, bound, rule):
    """M463. The F03 changed-raw-hash list of the M119-v2 monitor may be emptied only inside the declared refit transition, only when the current list is EMPTY, and only for a file
    whose archived raw copy now has the sha256 recorded in raw_manifest.json (so the entry cannot be dropped while the file still mismatches)."""
    if not _refit_transition_ok(prev, cur, rule) or not isinstance(path[-1], int):
        return False
    try:
        if get(cur, path[:-1]) != []:
            return False
        name = get(prev, path)
        rec = [r for r in json.load(open(os.path.join(ROOT, "raw_manifest.json"), encoding="utf-8"))["files"] if r.get("raw_name") == name]
        d = os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
        import re
        m_ = re.fullmatch(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.csv", name)
        cands = (name, name.replace("_", " ", 1)) + (("%s-%s-%s %s-%s-%s.csv" % m_.groups(),) if m_ else ())     # config keys use '_' or the compact form, the raw directory 'YYYY-MM-DD HH-MM-SS.csv'
        f = next((os.path.join(d, c) for c in cands if os.path.exists(os.path.join(d, c))), None)
        return len(rec) == 1 and f is not None and _sha256_file(f) == rec[0]["sha256"]
    except (KeyError, IndexError, TypeError, OSError, ValueError):
        return False


def cond_fit_attempts_shortened_converged(prev, cur, path, bound, rule):
    """M463. An entry of a fit-attempts list (a fallback attempt that failed or was tried first) may vanish only because the current list is SHORTER (the lost index is past its end) and
    its final attempt converged without error, so the estimate comes from a converged fit (a worse outcome, or a failed final attempt, fails)."""
    try:
        lst = get(cur, path[:-2])
        i = path[-2]
        last = lst[-1]
        return isinstance(lst, list) and isinstance(i, int) and i >= len(lst) and len(lst) >= 1 and last.get("converged") is True and last.get("error") is None
    except (KeyError, IndexError, TypeError, AttributeError):
        return False


def cond_list_shortened_nonempty(prev, cur, path, bound, rule):
    """M463. An element of a list may vanish only because the current list is shorter (the lost index is past its end) and still non-empty (a modal sequence that changed length;
    an emptied or deleted list fails)."""
    try:
        lst = get(cur, path[:-1])
        return isinstance(lst, list) and isinstance(path[-1], int) and len(lst) >= 1 and path[-1] >= len(lst)
    except (KeyError, IndexError, TypeError):
        return False


def cond_two_part_switch(prev, cur, path, bound, rule):
    """M463 (diagnosis of the CrawlStopGo cold losses). The phase-energy estimator reports a two-part block when zeroShare >= threshold (0.25) and a plain day-bootstrap median otherwise
    (compute_summary_arrays.py, pre-registered). A leaf under `twoPart` may vanish only when the zeroShare fell below the threshold and the current block has `bootMedian`;
    a leaf under `bootMedian` only when the zeroShare rose to the threshold or above and the current block has `twoPart`. The metric block is the prefix named by the rule template."""
    n = len(rule["pathTemplate"].split("/"))
    try:
        pb, cb = get(prev, path[:n]), get(cur, path[:n])
        t = rule["threshold"]
        sub = path[n]
        if sub == "twoPart":
            return pb["zeroShare"] >= t and cb["zeroShare"] < t and "bootMedian" in cb and "twoPart" not in cb
        if sub == "bootMedian":
            return pb["zeroShare"] < t and cb["zeroShare"] >= t and "twoPart" in cb and "bootMedian" not in cb
    except (KeyError, IndexError, TypeError):
        return False
    return False


CONDITIONS = {"field_changed": cond_field_changed, "stamp_hash_changed": cond_stamp_hash_changed, "parent_null_in_current": cond_parent_null_in_current, "sibling_present": cond_sibling_present,
              "field_changed_and_empty": cond_field_changed_and_empty, "cohort_min_support_crossed": cond_cohort_min_support_crossed, "placeholder_row_observed": cond_placeholder_row_observed, "moved_to_complement_list": cond_moved_to_complement_list,
              "refit_recompute_transition": cond_refit_recompute_transition, "f03_list_cleared_by_refit": cond_f03_list_cleared_by_refit, "fit_attempts_shortened_converged": cond_fit_attempts_shortened_converged,
              "list_shortened_nonempty": cond_list_shortened_nonempty, "two_part_switch": cond_two_part_switch}


REQUIRED_PARAMS = {"sibling_present": ("sibling",), "field_changed": ("entryDepth", "field"), "field_changed_and_empty": ("entryDepth", "field"), "placeholder_row_observed": ("entryDepth", "allowedLeaves", "observedFields"),
                   "moved_to_complement_list": ("listField", "complementField"),
                   "refit_recompute_transition": ("prevMode", "curMode", "prevCorpus", "curCorpus"), "f03_list_cleared_by_refit": ("prevMode", "curMode", "prevCorpus", "curCorpus"),
                   "two_part_switch": ("threshold",)}


def check_rules(rules):
    for r in rules:
        for k in ("id", "rationale", "milestone", "pathTemplate", "condition"):
            if not r.get(k):
                raise SystemExit(f"leaf_guard rule {r.get('id')!r}: missing {k}")
        if r["condition"] not in CONDITIONS:
            raise SystemExit(f"leaf_guard rule {r['id']!r}: unknown condition {r['condition']!r}")
        for k in REQUIRED_PARAMS.get(r["condition"], ()):
            if r.get(k) in (None, "", []):
                raise SystemExit(f"leaf_guard rule {r['id']!r}: condition {r['condition']!r} needs parameter {k!r}")
        if any(("*" in s or s not in ("{i}", "{key}") and s.startswith("{")) for s in r["pathTemplate"].split("/")):
            raise SystemExit(f"leaf_guard rule {r['id']!r}: only exact keys, {{i}} and {{key}} are allowed in pathTemplate")


def guard(prev, cur, rules):
    check_rules(rules)
    cur_nodes = nodes(cur)
    lost = [p for p in leaves(prev) if p not in cur_nodes]
    expected, unexpected = {}, []
    for p in lost:
        ok = False
        for r in rules:
            b = match(r["pathTemplate"], p, bool(r.get("matchPrefix")))
            if b is not None and CONDITIONS[r["condition"]](prev, cur, p, b, r):
                expected[r["id"]] = expected.get(r["id"], 0) + 1
                ok = True
                break
        if not ok:
            unexpected.append("/".join(map(str, p)))
    return {"nPreviousLeaves": sum(1 for _ in leaves(prev)), "nLost": len(lost), "expectedByRule": expected, "nUnexpected": len(unexpected), "unexpected": unexpected}


def load_previous(spec):
    if spec.startswith("git:"):
        ref = spec[4:]
        out = subprocess.run(["git", "show", f"{ref}:summary_arrays.json"], cwd=ROOT, capture_output=True)
        if out.returncode != 0:
            raise SystemExit("git show failed: " + out.stderr.decode("utf-8", "replace")[-300:])
        return json.loads(out.stdout.decode("utf-8"))
    return json.load(open(spec, encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--previous", default="git:HEAD")
    ap.add_argument("--current", default=os.path.join(ROOT, "summary_arrays.json"))
    ap.add_argument("--rules", default=os.path.join(ROOT, "analyses", "leaf_guard_rules.json"))
    ap.add_argument("--out")
    a = ap.parse_args()
    prev = load_previous(a.previous)
    cur = json.load(open(a.current, encoding="utf-8"))
    rules = json.load(open(a.rules, encoding="utf-8"))
    rep = guard(prev, cur, rules)
    rep["previous"] = a.previous
    rep["rules"] = [r["id"] for r in rules]
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rep, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: rep[k] for k in ("nPreviousLeaves", "nLost", "expectedByRule", "nUnexpected")}, ensure_ascii=False))
    if rep["nUnexpected"]:
        print("UNEXPECTED LOSSES (first 30):", file=sys.stderr)
        for u in rep["unexpected"][:30]:
            print("  " + u, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
