#!/usr/bin/env python3
"""M767 (spec analyses/M767_spec.md Rev 2): additive CARRIED payload block `gradeClassShares` (display of the grade-class SHARES of the covered driving that the M762 result allows).

Reads ONLY the registered result analyses/M767_grade_class_shares.json, pinned by sha256 (a mismatch or a missing file writes nothing and exits 3). Every number is copied from a registered field (the raw value is kept beside the display rounding:
percent two decimals, half up on the decimal repr, the frozen M760 rule); every string is written here. The cohort block (E2) is NOT copied (result only, never displayed). The block is computed on the registered corpus (master d514d600..., 717 drives)
and is NOT refreshed by ingestion (carried). Writes only /gradeClassShares and its artifact stamp in summary_arrays.json (deep-diff guarded). Idempotent.
Usage: python tools/grade_shares_payload.py [--splice] [--dry-run] [--check]   (no flag = print the block)"""
import copy, hashlib, json, os, sys
from decimal import Decimal, ROUND_HALF_UP

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SRC_REL = "analyses/M767_grade_class_shares.json"
SRC_SHA = "b86d3aacbcb12b59d718180d2f086dd8aa605c5d8d254426824d591849a72052"
REGISTERED_MASTER = "d514d6009d6d9a0a168ad4fb09b9bb98"
KEY = "gradeClassShares"
SOURCES = ("F", "N", "A", "G")
PLAIN = {"below -3 pp": "Steep downhill", "-3 to -1 pp": "Gentle downhill", "-1 to 1 pp": "Level", "1 to 3 pp": "Gentle uphill", "above 3 pp": "Steep uphill"}
PLAIN_RANGE = {"below -3 pp": "road falls more than 3 m per 100 m", "-3 to -1 pp": "falls 1 to 3 m per 100 m", "-1 to 1 pp": "within 1 m per 100 m", "1 to 3 pp": "rises 1 to 3 m per 100 m", "above 3 pp": "rises more than 3 m per 100 m"}
PRODUCT_NAMES = {"F": "FABDEM", "N": "NASADEM", "A": "AW3D30", "G": "GLO-30"}


class Stop(Exception):
    pass


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load(root=ROOT, rel=SRC_REL, pin=SRC_SHA):
    """pin=None: a retest source (M746 Rev 5): its own sha256 is recorded in the block (sourceSha256) and checked by --check."""
    p = os.path.join(root, rel)
    if not os.path.exists(p):
        raise Stop("missing source %s" % rel)
    if pin is not None and sha256(p) != pin:
        raise Stop("registered source %s differs from its pinned sha256" % rel)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def r2(x):
    """Frozen display rounding: two decimals, half up on the decimal repr of the registered float."""
    return None if x is None else float(Decimal(repr(float(x))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def r1(x):
    return None if x is None else float(Decimal(repr(float(x))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


FLOORS = {"days": 30, "km": 100.0, "steps": 1000}


def build(res, pin=SRC_SHA, rel=SRC_REL):
    retest = bool(res.get("retest"))
    if retest:
        if res.get("registeredMd5") != REGISTERED_MASTER or not (res.get("nestedControl") or {}).get("stages_and_shares_equal_M762") or not all(res["control_R1"].values()):
            raise Stop("the retest does not carry the registered master identity and a passed nested control")
        ss = res["E1_shares_primary_steps_secondary_km"]
        if ss["n_steps"] < FLOORS["steps"] or ss["n_days"] < FLOORS["days"] or ss["km"] < FLOORS["km"]:
            raise Stop("the retest is below the support floors")
        if "retest on" not in str(res.get("retestLabel")):
            raise Stop("the retest carries no retestLabel")
    else:
        if res.get("masterMd5") != REGISTERED_MASTER:
            raise Stop("the registered result was not computed on the registered master")
        if not all(res["control_R1"].values()):
            raise Stop("the registered result does not carry a passed control R1")
    n_drives = int(res["drives"]) if retest else 717
    e1 = res["E1_shares_primary_steps_secondary_km"]
    e3 = res["E3_products"]
    e4 = res["E4_coverage_and_selection"]
    if len(e1["rows"]) != 5 or len(e3) != 5:
        raise Stop("unexpected class rows")
    mis = res["three_class_and_five_class_misclassification_vs_fabdem_pct"]["five_class"]
    classes = []
    for r, p in zip(e1["rows"], e3):
        if r["class"] != p["class"]:
            raise Stop("class rows disagree between E1 and E3")
        sup = r["support"]
        lo, hi = r["step_share_pct"]["ci95"]
        klo, khi = r["km_share_pct"]["ci95"]
        classes.append({
            "label": r["class"], "plainLabel": PLAIN[r["class"]], "plainRange": PLAIN_RANGE[r["class"]], "steps": int(sup["steps"]), "days": int(sup["days"]), "drives": int(sup["drives"]), "km": r1(sup["km"]), "intervalShown": bool(sup["interval_shown"]),
            "stepSharePct": {"est": r2(r["step_share_pct"]["est"]), "ci95": [r2(lo), r2(hi)], "raw": {"est": r["step_share_pct"]["est"], "ci95": [lo, hi]}},
            "kmSharePct": {"est": r2(r["km_share_pct"]["est"]), "ci95": [r2(klo), r2(khi)], "raw": {"est": r["km_share_pct"]["est"], "ci95": [klo, khi]}},
            "products": {PRODUCT_NAMES[k]: r2(p["by_product_step_share_pct"][k]) for k in SOURCES}, "productsRaw": {PRODUCT_NAMES[k]: p["by_product_step_share_pct"][k] for k in SOURCES},
            "bracketMinPct": r2(p["bracket_min"]), "bracketMaxPct": r2(p["bracket_max"]), "sourceDependent": p["source_dependent"],
        })
    cov = {"loggedKm": r1(e4["logged_km"]), "coveredKm": r1(e4["covered_km"]), "coveredSharePct": r1(e4["covered_share_of_logged_km_pct"]), "drives": int(e4["drives"]), "drivesWithCoveredStep": int(e4["drives_with_a_covered_step"]),
           "raw": {"loggedKm": e4["logged_km"], "coveredKm": e4["covered_km"], "coveredSharePct": e4["covered_share_of_logged_km_pct"]}}
    for key, out in (("by_stratum", "byLength"), ("by_month", "byMonth"), ("by_cohort", "byCohort")):
        cells = {}
        for name, c in e4[key].items():
            cells[name] = c if isinstance(c, str) else {"drives": int(c["drives"]), "loggedKm": r1(c["logged_km"]), "coveredKm": r1(c["covered_km"]), "coveredSharePct": r1(c["covered_share_pct"])}
        cov[out] = cells
    mix = e4["drive_level_speed_class_mix_km_weighted"]
    cov["speedMix"] = {k: ({m: r1(v) for m, v in mix[k].items()} if mix.get(k) else None) for k in ("all_logged", "covered", "uncovered_remainder")}
    exc = e4["steps_excluded_above_8pp"]
    sens = e4["fabdem_sensitivities_step_share_pct"]
    n_all = e1["n_steps"]
    dep = [c["label"] for c in classes if c["sourceDependent"]]
    stable = [c["label"] for c in classes if c["sourceDependent"] is False]
    def _g(r, p_):
        return {"est": r["step_share_pct"]["est"], "lo": p_["bracket_min"], "hi": p_["bracket_max"]}
    gg = [_g(r, p_) for r, p_ in zip(e1["rows"], e3)]
    lvl, gentle, steep = gg[2], [gg[1], gg[3]], [gg[0], gg[4]]
    block = {
        "basis": ("%s; M762 DEM manifest sha256 %s...; the registered result (717 drives) is unchanged" % (res["retestLabel"], res["m762ManifestSha256"][:8])) if retest else
                 ("computed on the registered corpus of 717 drives (master MD5 %s...; M762 DEM manifest sha256 %s...); later drives are not included" % (REGISTERED_MASTER[:8], res["m762ManifestSha256"][:8])),
        "registeredMasterMd5": REGISTERED_MASTER, "corpusDrives": n_drives, "sourceFile": rel, "sourceSha256": pin or sha256(os.path.join(ROOT, rel)), "resultToolSha256": res["toolSha256"], "seed": res["seed"], "nBoot": res["nBoot"],
        "status": ("auxiliary block from a labelled retest; descriptive monitoring only; not an article figure; the promotion step records the source file" if retest else "carried block, auxiliary; not an article figure; not refreshed by ingestion"),
        "staleness": {"carried": not retest, "corpusDrives": n_drives, "refreshedAt": None},
        "title": "Grade-class shares of the covered driving (estimated DEM step grade, cloud-step scale)",
        "stepSet": {"steps": int(e1["n_steps"]), "days": int(e1["n_days"]), "km": r1(e1["km"])},
        "classes": classes,
        "misclassificationPct": {"NASADEM": r1(mis["N"]), "AW3D30": r1(mis["A"]), "GLO-30": r1(mis["G"])},
        "coverage": cov,
        "excludedAbove8pp": {"steps": int(exc["n_steps"]), "belowMinus8": int(exc["below_minus_8"]), "above8": int(exc["above_8"]), "sharePct": r2(exc["share_of_steps_after_masks_pct"])},
        "fabdemSensitivityStepSharePct": {k: [r2(v) for v in vals] for k, vals in sens.items()},
        "limits": list(res["limits"]),
        "notes": {
            "lead": "Estimated grade-class shares of the COVERED driving: the share of the %s cloud-step stretches (300 to 900 m, at 8 km/h or more) in each class of the estimated FABDEM step grade, with day-clustered 95 %% intervals. The step-count share is primary; the kilometre-weighted share is a secondary view of the same classes. Selection: consecutive cloud rows at most 120 s apart, no first or last step of a drive, speed 8 km/h or more, then the DEM masks." % format(n_all, ","),
            "coverage": "The covered stretches are %s km of the %s km logged (%s %%): the shares describe where the covered driving takes place, not all driving. Coverage is selected by drive length (%s) and varies by month (%s)." % (
                cov["coveredKm"], cov["loggedKm"], cov["coveredSharePct"],
                "; ".join("%s %s %%" % (k, v["coveredSharePct"]) for k, v in cov["byLength"].items() if isinstance(v, dict)),
                "; ".join("%s %s %%" % (k, v["coveredSharePct"]) for k, v in cov["byMonth"].items() if isinstance(v, dict))),
            "products": "Four elevation products classify the same stretches; the bracket is their minimum and maximum, not an interval. Classes where another product lies outside the FABDEM interval: %s; stable across products: %s. GLO-30 is FABDEM's base (not independent), and FABDEM is the most central product: random DEM noise moves share out of the -1 to 1 pp class, so the bracket is not symmetric." % (
                ", ".join(dep) if dep else "none", ", ".join(stable) if stable else "none"),
            "labels": "Estimated DEM step grade (inter-product DEM error only, assumption-conditional, common-mode error not identified; not the error against the road grade). Not per-stretch labels: the class of a stretch differs between FABDEM and NASADEM on %s %% and AW3D30 on %s %% of the stretches." % (r1(mis["N"]), r1(mis["A"])),
            "excluded": "%d stretches (%s %%) with an estimated grade beyond 8 pp (%d steeper than -8, %d steeper than +8) are excluded as likely bridges, cuttings or position artefacts; the outer classes therefore cover 3 to 8 pp." % (exc["n_steps"], r2(exc["share_of_steps_after_masks_pct"]), exc["below_minus_8"], exc["above_8"]),
            "locked": "Regeneration, apparent KE recovery, fuel and traction energy by grade class are not shown here: they are a separate analysis (M768) that needs its own review before display.",
            "plain": {
                "what": "How much of the driving we can place on the map goes downhill, uphill or on the level. Each short stretch of road (300 to 900 m) is given an estimated slope from one public elevation map (FABDEM); the bar splits all %s stretches into five slope groups." % format(n_all, ","),
                "slope": "Slope is metres of rise per 100 m driven (1 % = 1 m per 100 m). Gentle means 1 to 3 %, steep means more than 3 %.",
                "coverage": "These stretches are %s %% of the logged kilometres (%s of %s km; the logged kilometres include every drive, also those flagged as outliers). Longer drives are over-represented, so read the bar as the driving we could map, not all driving." % (cov["coveredSharePct"], cov["coveredKm"], cov["loggedKm"]),
                "uncertainty": "The elevation maps are not exact. About %s %% of stretches fall in a different slope group on NASADEM than on FABDEM (AW3D30: %s %%). FABDEM, the map used here, gives the highest level share: the other maps put up to %s points less in level and up to %s points more in each gentle group. The steep groups stay within about %s points on every map. The 95 %% range in brackets covers day-to-day variation only, not differences between maps (for level, the NASADEM share of %s %% lies below it)." % (r1(mis["N"]), r1(mis["A"]), r1(lvl["est"] - lvl["lo"]), r1(max(g["hi"] - g["est"] for g in gentle)), r1(max(g["hi"] - g["lo"] for g in steep)), r2(lvl["lo"])),
                "use": "Energy, regeneration and fuel by slope group are not shown here (separate analysis M768, under review). This is not an energy result.",
            },
            "unsupported": "interval not shown: fewer than 20 stretches or 5 days in the class",
        },
    }
    return block


def walk(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            yield from walk(a.get(k), b.get(k), path + "/" + k)
    elif a != b:
        yield path


def splice(block, dry=False, path=None):
    P = path or os.path.join(ROOT, "summary_arrays.json")
    with open(P, encoding="utf-8", newline="") as f:
        raw = f.read()
    A = json.loads(raw)
    B = copy.deepcopy(A)
    B[KEY] = block
    if KEY not in (B.get("_artifactStamps") or {}):
        import datetime
        st = copy.deepcopy(B["_artifactStamps"]["powerFadeTemperatureSpecs"])
        for k in ("declaredIdentity", "stampLineage", "carriedForward", "upstreamHashes"):
            st.pop(k, None)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        st.update(corpusHash=REGISTERED_MASTER, generatedAt=now, includedInReleaseAt=now, computedAt=now, computationStatus="computed",
                  computationStatusNote="M767: copied by tools/grade_shares_payload.py from the registered grade-class share result (carried; spec analyses/M767_spec.md Rev 2)")
        B["_artifactStamps"][KEY] = st
    bad = [d for d in walk(A, B) if not d.startswith("/" + KEY) and not d.startswith("/_artifactStamps/" + KEY)]
    if bad:
        raise Stop("deep diff outside %s: %s" % (KEY, bad[:4]))
    if A.get(KEY) == block and KEY in (A.get("_artifactStamps") or {}):
        return False
    if not dry:
        with open(P, "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps(B, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return True


def delta(old, new, registered=None):
    """M746 Rev 5, 10.7: monitoring record of a refreshed block against the PREVIOUS displayed block (and the registered one). Not a test.
    escalate = a class leaves the PREVIOUS displayed interval, changes its support status (interval shown) or changes its source-dependent flag."""
    rows, esc = [], []
    for o, n in zip(old["classes"], new["classes"]):
        lo, hi = o["stepSharePct"]["ci95"]
        e = n["stepSharePct"]["est"]
        outside = bool(o["intervalShown"] and lo is not None and (e < lo or e > hi))
        rec = {"class": n["label"], "previousShare": o["stepSharePct"]["est"], "newShare": e, "outsidePreviousInterval": outside,
               "supportChanged": o["intervalShown"] != n["intervalShown"], "sourceDependentChanged": o["sourceDependent"] != n["sourceDependent"]}
        if registered:
            rlo, rhi = registered["classes"][len(rows)]["stepSharePct"]["ci95"]
            rec["outsideRegisteredInterval"] = bool(rlo is not None and (e < rlo or e > rhi))
        if outside or rec["supportChanged"] or rec["sourceDependentChanged"]:
            esc.append(n["label"])
        rows.append(rec)
    return {"rows": rows, "coveredSharePctPrevious": old["coverage"]["coveredSharePct"], "coveredSharePctNew": new["coverage"]["coveredSharePct"],
            "stepsPrevious": old["stepSet"]["steps"], "stepsNew": new["stepSet"]["steps"], "escalate": bool(esc), "escalatedClasses": esc,
            "note": "monitoring record, not a test; a displayed change goes to the owner as one line plus the rendered page; an escalation needs a blind audit and the Director before the block is replaced"}


def source_of(block):
    """The source recorded in a block: (relative path, pin or None for a retest file)."""
    rel = block.get("sourceFile") or SRC_REL
    return rel, (SRC_SHA if rel == SRC_REL else None)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    src = None
    if "--source" in argv:
        src = argv[argv.index("--source") + 1]
    try:
        with open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8") as f:
            A = json.load(f)
        if "--check" in argv:
            cur = A.get(KEY)
            if cur is None:
                print("grade_shares_payload: block MISSING")
                return 1
            rel, pin = source_of(cur)
            res = load(ROOT, rel, pin)
            if pin is None and sha256(os.path.join(ROOT, rel)) != cur.get("sourceSha256"):
                print("grade_shares_payload: the recorded source sha256 differs from the file")
                return 1
            block = build(res, pin if pin else cur["sourceSha256"], rel)
            ok = cur == block
            print("grade_shares_payload: block %s" % ("present and equal to its recorded source" if ok else "MISSING or different"))
            return 0 if ok else 1
        if src:
            rel = src.replace("\\", "/")
            block = build(load(ROOT, rel, None), None, rel)
        else:
            block = build(load())
        if "--delta" in argv or (src and "--splice" in argv):
            old = A.get(KEY)
            if old:
                d = delta(old, block, build(load()) if old.get("sourceFile") != SRC_REL else old)
                print("grade_shares_payload: delta " + json.dumps(d)[:1500])
                acc = argv[argv.index("--accept-escalated") + 1] if "--accept-escalated" in argv and argv.index("--accept-escalated") + 1 < len(argv) else None
                if acc and not os.path.isfile(os.path.join(ROOT, acc)):
                    print("grade_shares_payload: --accept-escalated needs the path of the audit or Director decision file (not found); nothing written")
                    return 4
                if d["escalate"] and not acc and "--splice" in argv:
                    print("grade_shares_payload: ESCALATED (a class left the previous displayed interval, changed support or changed its source flag): blind audit and Director before replacement; nothing written")
                    return 4
        if "--splice" in argv:
            dry = "--dry-run" in argv
            ch = splice(block, dry)
            print("grade_shares_payload: %s" % (("would write" if dry else "written") if ch else "unchanged"))
        else:
            print(json.dumps(block, indent=1)[:4000])
        return 0
    except Stop as e:
        print("grade_shares_payload: STOP (%s); nothing written" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
