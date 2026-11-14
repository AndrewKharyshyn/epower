"""M651 (P-07): generic leaf carry (deny-list) in ingest_core. Byte-level edits keep mixed line endings. ASCII only."""
def edit(p, pairs):
    b = open(p, 'rb').read()
    for o, n in pairs:
        ob = o.encode('utf-8')
        assert b.count(ob) == 1, (o[:70], b.count(ob))
        nl = b'\r\n' if b'\r\n' in b[b.index(ob):b.index(ob) + len(ob) + 4] or (b.count(b'\r\n') > b.count(b'\n') / 2) else b'\n'
        b = b.replace(ob, n.encode('utf-8').replace(b'\n', nl))
    open(p, 'wb').write(b)

edit('tools/ingest_core.py', [
 ('''ACK = {"reason": None, "recal": None}
''', '''ACK = {"reason": None, "recal": None}

# M651 (P-07): generic carry of previous leaves the builder does not produce (deny-list instead of the NESTED_CARRIED allow-list alone).
# Denied: `_artifactStamps` (the stamp stages own hash / time / basis; a carried stamp would be stale) and any path containing a list index (an element of a list cannot be matched by position
# after a rebuild; those leaves keep being restored by their own stages and stay visible in the early leaf_guard report). Leaves covered by a declared leaf_guard rule are expected losses and are not carried.
CARRY_DENY_TOP = ("_artifactStamps",)
CARRIED_LEAVES = []


def carry_lost_leaves(arrays, prev, rules):
    """Copy, from the previous payload into the fresh one, every subtree whose leaves the builder did not produce and that no declared rule expects to vanish. The copy is taken at the
    highest missing dict node (its parent exists in the fresh payload), so a missing branch is carried whole. Returns the sorted list of carried node paths (reported, NOT stored in the arrays).
    Carried values are the previous values (stale until the owning stage has run), like the top-level carry."""
    import copy
    import leaf_guard as LG
    cur_nodes = LG.nodes(arrays)
    carried = set()
    for p in LG.leaves(prev):
        if p in cur_nodes or not p or p[0] in CARRY_DENY_TOP or any(isinstance(x, int) for x in p):
            continue
        if any((r := LG.match(rl["pathTemplate"], p, bool(rl.get("matchPrefix")))) is not None and LG.CONDITIONS[rl["condition"]](prev, arrays, p, r, rl) for rl in rules):
            continue
        k = next(i for i in range(1, len(p) + 1) if p[:i] not in cur_nodes)      # shortest missing prefix
        parent = LG.get(arrays, p[:k - 1])
        if isinstance(parent, dict):
            carried.add(p[:k])
    out = []
    for node in sorted(carried, key=len):
        if any(node[:len(c)] == c for c in out):
            continue
        LG.get(arrays, node[:-1])[node[-1]] = copy.deepcopy(LG.get(prev, node))
        out.append(node)
    return sorted("/".join(map(str, c)) for c in out)
'''),
 ('''    CARRIED[:] = carry_forward(arrays, prev)   # reported by main(); NOT stored in the arrays file
''', '''    CARRIED[:] = carry_forward(arrays, prev)   # reported by main(); NOT stored in the arrays file
    CARRIED_LEAVES[:] = carry_lost_leaves(arrays, prev, json.load(open(os.path.join(ROOT, "analyses", "leaf_guard_rules.json"), encoding="utf-8")))      # M651 (P-07)
'''),
 ('report.update(carried_forward_keys_stale_until_stage_runs=list(CARRIED),', 'report.update(carried_forward_keys_stale_until_stage_runs=list(CARRIED), carried_leaf_nodes_stale_until_stage_runs=list(CARRIED_LEAVES),'),
])
print('ok')
