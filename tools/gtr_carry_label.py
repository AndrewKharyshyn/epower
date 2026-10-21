#!/usr/bin/env python3
"""M463 (Director ruling on the frozen reading-flip STOP): label the GTR-family blocks that an ingestion CARRIES instead of refreshing.
Adds ONE additive key, generatorTractionRecon.carriedAtIngestion, when sensitivity / simultaneity / speedSplit (refreshedBlocks) sit on a smaller drive set than the live headline
(generatorTractionRecon.nProduction). Every number is read from the payload (refreshedBlocks, gtrClosure, the live headline); the only typed text is the sentence frame.
The carried values are NOT changed. Deep diff: only /generatorTractionRecon/carriedAtIngestion (and the matching artifact-stamp note is untouched). Idempotent.
Usage: XT_INGEST_LABEL=M### python tools/gtr_carry_label.py [--dry-run] [--follow-up M###]"""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
DRY = "--dry-run" in sys.argv
FOLLOW = sys.argv[sys.argv.index("--follow-up") + 1] if "--follow-up" in sys.argv else "the follow-up milestone"


def build(G, label):
    rb = {p["block"]: p for p in G["refreshedBlocks"]}
    first = G["refreshedBlocks"][0]
    sc, cl = G["gtrClosure"]["scope"], G["gtrClosure"]["fGen"]
    base = G["sensitivity"][0]
    live = {"nProduction": G["nProduction"], "nDrives": G["nDrives"], "kmProduction": G["kmProduction"], "fGen": G["corpus"]["fGen"],
            "generator": G["corpus"]["generator"], "tractionGross": G["corpus"]["tractionGross"], "etaBus": G["corpus"]["etaBus"]}
    carried = {"sensitivity": {"nDrives": rb["sensitivity"]["nDrives"], "nDays": rb["sensitivity"]["nDays"], "baseFgen": base["fgen"]},
               "simultaneity": {"nDrives": rb["simultaneity"]["nDrives"], "nDays": rb["simultaneity"]["nDays"]},
               "speedSplit": {"nDrives": rb["speedSplit"]["nDrives"], "nDays": rb["speedSplit"]["nDays"]},
               "gtrClosure": {"nDrives": sc["nDrives"], "nDays": sc["nDays"], "fGen": cl["est"], "ci95": cl["ci95"], "ciContains0p5": cl["ciContains0p5"]}}
    s = ("Carried at ingestion %s, not recomputed: sensitivity, simultaneity and speedSplit sit on the %s set (%d drives, %d days) and gtrClosure on %d drives (%d days). "
         "The live GTR headline above is refreshed on %d drives: f_gen %s. The carried sensitivity BASE row shows f_gen %s and the carried closure f_gen %s (95%% CI %s to %s). "
         "The values are on different drive sets and the difference is not yet attributed (%s); the carried blocks are not a statement about the current corpus."
         % (label, first["basisMilestone"], first["nDrives"], first["nDays"], sc["nDrives"], sc["nDays"], live["nDrives"], live["fGen"], base["fgen"], cl["est"], cl["ci95"][0], cl["ci95"][1], FOLLOW))
    if live["fGen"] >= 0.5 and cl["ciContains0p5"]:
        s += " The live point estimate crossed 0.5 within an interval that already contained 0.5; the generator/battery supply split is not established."
    return {"milestone": label, "blocks": ["sensitivity", "simultaneity", "speedSplit", "gtrClosure"], "basisMilestone": first["basisMilestone"], "carried": carried, "liveHeadline": live,
            "followUp": FOLLOW, "statement": s}


def main():
    label = os.environ.get("XT_INGEST_LABEL")
    if not label:
        raise SystemExit("XT_INGEST_LABEL is required")
    raw = open("summary_arrays.json", "rb").read().decode("utf-8")
    A = json.loads(raw)
    if json.dumps(A, ensure_ascii=False, indent=1) not in (raw, raw.rstrip("\n")):
        raise SystemExit("serialisation round-trip differs: refusing to rewrite the file")
    G = A["generatorTractionRecon"]
    smallest = min(p["nDrives"] for p in G["refreshedBlocks"])
    if smallest >= G["nProduction"]:
        N = copy.deepcopy(A)
        N["generatorTractionRecon"].pop("carriedAtIngestion", None)       # refreshed blocks cover the live headline set: no carry label
        blk = None
    else:
        blk = build(G, label)
        N = copy.deepcopy(A)
        N["generatorTractionRecon"]["carriedAtIngestion"] = blk
    ch = [k for k in set(A["generatorTractionRecon"]) | set(N["generatorTractionRecon"]) if A["generatorTractionRecon"].get(k) != N["generatorTractionRecon"].get(k)]
    other = [k for k in A if k != "generatorTractionRecon" and A[k] != N[k]]
    assert not other and set(ch) <= {"carriedAtIngestion"}, (ch, other)
    print(json.dumps({"changed": ch, "statement": blk["statement"] if blk else None}, ensure_ascii=False))
    if not DRY and ch:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(N, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
        print("wrote summary_arrays.json")


if __name__ == "__main__":
    main()
