"""M610b (spec analyses/M610_spec.md Rev 1, T3 and R6/R8/R9): known answers for tools/stop_protocol.py.
 1. collect mode needs the runner's token FILE: no variables, a wrong token, or a deleted token file mean inactive (a stale variable cannot switch a later run into collect mode);
 2. outside a collect pass try_collect() is False and writes nothing (the tool then stops exactly as before);
 3. record schema: facts < 2 KB, recordSha256 stable for equal content and changed by a changed fact, upstream chain of earlier hashes (R8), sequence-numbered files;
 4. an ack is bound to a record only through its recordSha256;
 5. finish_pass exports the artifacts named by the records under provisional/ with the never-published label, one draft brief per stop, and stops.json;
 6. the gate table lists every converted hook as collectable and every other exit-3 tool as not collectable (R4)."""
import json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))
import stop_protocol as SP


def main():
    tmp = tempfile.mkdtemp(prefix="xt_stop_")
    try:
        rd = os.path.join(tmp, "runs", "r1")
        os.makedirs(rd)
        # 1. token validity
        assert not SP.collect_active({}) and not SP.collect_active({SP.TOKEN_ENV: "x"}) and not SP.collect_active({SP.DIR_ENV: rd})
        tok = SP.issue_token(rd)
        env = {SP.TOKEN_ENV: tok, SP.DIR_ENV: rd}
        assert SP.collect_active(env)
        assert not SP.collect_active({SP.TOKEN_ENV: "wrong", SP.DIR_ENV: rd})
        # 2. inactive: nothing written
        assert SP.try_collect("s", "g", {"a": 1}, ["ENV"], env={}) is False and not os.path.exists(os.path.join(rd, "stops"))
        # 3. records
        r1 = SP.record_stop("gtr_family_refresh", "flip", {"stops": ["x"]}, ["XT_ACK_GTR_FLIP"], {"k": "v"}, withheld=["b", "a"], artifacts=["analyses/x.json"], env=env)
        r2 = SP.record_stop("urban_week_block", "verdict", {"v": "depends"}, ["XT_ACK_URBAN_WEEK_BLOCK"], env=env)
        assert r1["upstream"] == [] and r2["upstream"] == [r1["recordSha256"]] and r1["withheld"] == ["a", "b"] and r1["kind"] == "escalation"
        names = sorted(os.listdir(os.path.join(rd, "stops")))
        assert names == ["001__gtr_family_refresh__flip.json", "002__urban_week_block__verdict.json"], names
        again = SP.build_record("gtr_family_refresh", "flip", {"stops": ["x"]}, ["XT_ACK_GTR_FLIP"], {"k": "v"}, ["b", "a"], ["analyses/x.json"], [])
        assert again["recordSha256"] == r1["recordSha256"], "equal content, equal hash"
        changed = SP.build_record("gtr_family_refresh", "flip", {"stops": ["y"]}, ["XT_ACK_GTR_FLIP"], {"k": "v"}, ["b", "a"], ["analyses/x.json"], [])
        assert changed["recordSha256"] != r1["recordSha256"], "a changed fact changes the hash"
        assert SP.build_record("gtr_family_refresh", "flip", {"stops": ["x"]}, ["XT_ACK_GTR_FLIP"], {"k": "v"}, ["b", "a"], ["analyses/x.json"], ["u"])["recordSha256"] != r1["recordSha256"], "upstream is part of the hash"
        try:
            SP.build_record("s", "g", {"big": "x" * 2100}, [], None, [], [], [])
            raise AssertionError("facts of 2 KB or more must be refused")
        except ValueError:
            pass
        # 4. ack binding
        assert SP.check_ack_binding(r1["recordSha256"], {"ruling": "R", "recordSha256": r1["recordSha256"]}) and not SP.check_ack_binding(r1["recordSha256"], {"recordSha256": r2["recordSha256"]}) and not SP.check_ack_binding(r1["recordSha256"], {"ruling": "R"})
        # 5. finish_pass
        os.makedirs(os.path.join(tmp, "analyses"))
        with open(os.path.join(tmp, "analyses", "x.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        s = SP.finish_pass(rd, tmp)
        assert s["count"] == 2 and s["firstStopStage"] == "gtr_family_refresh" and s["stages"] == ["gtr_family_refresh", "urban_week_block"], s
        assert os.path.isfile(os.path.join(rd, "provisional", "analyses", "x.json")) and "NEVER PUBLISHED" in open(os.path.join(rd, "provisional", "PROVISIONAL_NEVER_PUBLISHED.txt"), encoding="utf-8").read()
        briefs = sorted(os.listdir(os.path.join(rd, "briefs")))
        assert briefs == ["001_gtr_family_refresh.json", "002_urban_week_block.json"], briefs
        b2 = json.load(open(os.path.join(rd, "briefs", briefs[1]), encoding="utf-8"))
        assert b2["order"] == 2 and "PROVISIONAL" in b2["provisional"] and "voids every later record" in b2["rule"]
        assert json.load(open(os.path.join(rd, "stops.json"), encoding="utf-8"))["count"] == 2
        SP.close_token(rd)
        assert not SP.collect_active(env), "a closed pass is inactive again"
        # a second pass in the SAME run directory (run directories are named by the second) starts clean: no record of the first pass leaks into it (found by the Linux CI run of PR 296)
        assert os.path.isdir(os.path.join(rd, "stops")) and os.path.isfile(os.path.join(rd, "stops.json"))
        tok2 = SP.issue_token(rd)
        assert SP.load_records(rd) == [] and not os.path.exists(os.path.join(rd, "stops.json")) and not os.path.isdir(os.path.join(rd, "briefs")) and not os.path.isdir(os.path.join(rd, "provisional"))
        env2 = {SP.TOKEN_ENV: tok2, SP.DIR_ENV: rd}
        assert SP.record_stop("s", "g", {"a": 1}, ["E"], env=env2)["upstream"] == [], "the first record of the new pass has no upstream"
        SP.close_token(rd)
        # 6. gate table
        gt = json.load(open(os.path.join(REPO, "analyses", "M610_gate_table.json"), encoding="utf-8"))["gates"]
        yes = {g["tool"] for g in gt if g["collectable"]}
        assert yes == {"gtr_family_refresh_splice", "gtr_closure_refresh", "urban_week_block", "urban_balance"}, yes
        no = {g["tool"] for g in gt if not g["collectable"]}
        assert {"m338_lhv_splice", "m471_etabus_splice", "m473_splice", "m510_fuel_routemix_splice", "m511_fuel_eligibility_splice", "cold_neutral_context", "ingest_core", "leaf_guard", "release_check"} <= no
        for g in gt:
            assert g["reason"], g
        # every converted tool really calls the hook, and no other tool does
        hooked = {os.path.basename(p)[:-3] for p in (os.path.join(REPO, "tools", n) for n in os.listdir(os.path.join(REPO, "tools")) if n.endswith(".py")) if "try_collect(" in open(p, encoding="utf-8").read()} - {"stop_protocol"}
        assert hooked == yes, (hooked, yes)
        print("test_stop_protocol OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
