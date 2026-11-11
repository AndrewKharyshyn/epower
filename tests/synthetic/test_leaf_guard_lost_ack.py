"""M608: leaf_guard condition `lost_leaf_ack` (spec analyses/M608_lost_leaf_ack_spec.md). A leaf of a list that new data emptied may vanish only when an acknowledgement pins the live master MD5,
a recorded ruling, and the exact leaf path with its previous value. Synthetic arrays; the ack lives in a temp dir (absolute path)."""
import copy, hashlib, json, os, sys, tempfile, shutil

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import leaf_guard as LG

MD5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
PREV = {"meta": {"thinBins": [{"label": "0-10", "n": 153}], "other": [{"label": "x", "n": 1}]}, "flags": {"v0": ["V8"]}}
CUR = {"meta": {"thinBins": [], "other": [{"label": "x", "n": 1}]}, "flags": {"v0": []}}


def main():
    tmp = tempfile.mkdtemp(prefix="xt_lla_")
    try:
        ackp = os.path.join(tmp, "ack.json")
        rules = [{"id": "thin", "rationale": "r", "milestone": "M608", "pathTemplate": "meta/thinBins/{i}/{key}", "condition": "lost_leaf_ack", "ackFile": ackp},
                 {"id": "v0", "rationale": "r", "milestone": "M608", "pathTemplate": "flags/v0/{i}", "condition": "lost_leaf_ack", "ackFile": ackp}]
        LG.check_rules(rules)
        good = {"ruling": "analyses/x_ruling.json", "masterMd5": MD5, "leaves": {"meta/thinBins/0/label": {"previous": "0-10"}, "meta/thinBins/0/n": {"previous": 153}, "flags/v0/0": {"previous": "V8"}}}
        # no ack file at all: every lost leaf is unexpected
        r = LG.guard(PREV, CUR, rules)
        assert r["nLost"] == 3 and r["nUnexpected"] == 3, r
        w = lambda a: json.dump(a, open(ackp, "w"))
        # pinned ack: all three accepted
        w(good)
        r = LG.guard(PREV, CUR, rules)
        assert r["nUnexpected"] == 0 and r["expectedByRule"] == {"thin": 2, "v0": 1}, r
        # a different master MD5, a missing ruling, a different previous value, a leaf not listed: refused
        a = copy.deepcopy(good); a["masterMd5"] = "0" * 32; w(a)
        assert LG.guard(PREV, CUR, rules)["nUnexpected"] == 3
        a = copy.deepcopy(good); del a["ruling"]; w(a)
        assert LG.guard(PREV, CUR, rules)["nUnexpected"] == 3
        a = copy.deepcopy(good); a["leaves"]["meta/thinBins/0/n"]["previous"] = 999; w(a)
        r = LG.guard(PREV, CUR, rules)
        assert r["nUnexpected"] == 1 and r["unexpected"] == ["meta/thinBins/0/n"], r
        a = copy.deepcopy(good); del a["leaves"]["flags/v0/0"]; w(a)
        r = LG.guard(PREV, CUR, rules)
        assert r["unexpected"] == ["flags/v0/0"], r
        # a loss under a path the rules do not name stays unexpected even with a full ack
        w(good)
        cur2 = copy.deepcopy(CUR); cur2["meta"]["other"] = []
        r = LG.guard(PREV, cur2, rules)
        assert sorted(r["unexpected"]) == ["meta/other/0/label", "meta/other/0/n"], r
        # a rule without ackFile is rejected at load time
        try:
            LG.check_rules([{"id": "bad", "rationale": "r", "milestone": "M608", "pathTemplate": "a/{i}", "condition": "lost_leaf_ack"}])
            raise AssertionError("a lost_leaf_ack rule without ackFile must be rejected")
        except SystemExit:
            pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("test_leaf_guard_lost_ack OK")


if __name__ == "__main__":
    main()
