"""M658 second pass: Director decision (revise: minor text/field fixes, then ship payload-only). ASCII only."""


def rep(t, o, n):
    assert t.count(o) == 1, (o[:80], t.count(o))
    return t.replace(o, n)


p = 'tools/n06_bms_power_map.py'
t = open(p, encoding='utf-8').read()
t = rep(t, 'EXTRACTOR_VERSION = "n06-r2"', 'EXTRACTOR_VERSION = "n06-r3"')
# the I x V check also counts the time with logged charge power above 50 kW (the power of the check)
t = rep(t, '''            d["ivCheck"] = {"atMax": {"s": float(w[chg & atm].sum()), "exceed": float(w[chg & atm & (pe > pv)].sum())},
                            "belowMax": {"s": float(w[chg & ~atm].sum()), "exceed": float(w[chg & ~atm & (pe > pv)].sum())}}''',
        '''            d["ivCheck"] = {"atMax": {"s": float(w[chg & atm].sum()), "exceed": float(w[chg & atm & (pe > pv)].sum())},
                            "belowMax": {"s": float(w[chg & ~atm].sum()), "exceed": float(w[chg & ~atm & (pe > pv)].sum())},
                            "chargeAbove50kWSeconds": float(w[np.isfinite(pe) & (pe > 50.0)].sum()), "pairedSeconds": float(w[np.isfinite(pe)].sum())}''')
# distinct values counted on the quantised grid index, not as floats
t = rep(t, '''"distinctValuesWithin1kWBelowMaximum": len({v for f in parts_f for v in stats[f]["dir"][dname]["nearMaxValues"]}),''',
        '''"distinctValuesWithin1kWBelowMaximum": len({int(round(float(v) / Q)) for f in parts_f for v in stats[f]["dir"][dname]["nearMaxValues"]}),
                       "distinctValuesBasis": "counted on the 0.05 kW quantisation grid (integer grid index), per era",''')
# iv power statistic
t = rep(t, '''                A = np.array([byd[d] for d in ud])''', '''                A = np.array([byd[d] for d in ud])
                pw_s = sum((c or {}).get("chargeAbove50kWSeconds", 0.0) for c in iv); pr_s = sum((c or {}).get("pairedSeconds", 0.0) for c in iv)''')
t = rep(t, '''                                                        "note": "descriptive; never converts the value into a physical statement"}''',
        '''                                                        "power": {"timeShareLoggedChargePowerAbove50kW": round(pw_s / pr_s, 4) if pr_s else None, "pairedSeconds": round(pr_s, 1),
                                                                  "note": "the logged charge power is rarely near the reported limit, so the check has little power to detect an imposed cap or a saturated byte"},
                                                        "note": "descriptive; exceedance is rare at the logged maximum and absent below it; not evidence for or against saturation; the battery-current sign convention (charge-positive) is assumed"}''')
# monotone strings name era, quantity, band, bins
t = rep(t, '''                    mono[qn] = "increasing with pack temperature" if (inc and sep) else ("decreasing with pack temperature" if (dec and sep) else "no ordered relation is established")''',
        '''                    nm = {"belowMaxMedian": "below-maximum median", "maxShare": "logged-maximum share"}[qn]
                    binsTxt = "%d-%d C" % (sup[0], sup[-1] + 5)
                    pre = "%s era, %s direction, SoC 55-66 %%: " % (era, dname)
                    mono[qn] = (pre + nm + " is higher in each warmer supported bin (" + binsTxt + "); descriptive, not a temperature effect") if (inc and sep) else (
                        (pre + nm + " is lower in each warmer supported bin (" + binsTxt + "); descriptive, not a temperature effect") if (dec and sep) else (pre + nm + ": no ordered relation is established"))''')
t = rep(t, '''            ev["supportedPackTempRangeC"] = [min(sup), max(sup) + 5] if sup else None''',
        '''            ev["supportedPackTempOuterBinEdgesC"] = [min(sup), max(sup) + 5] if sup else None
            ev["supportedPackTempBinsC"] = sup''')
# block-level reading, disclosures and the not-independently-reproduced list
t = rep(t, '''    for era in ("hp", "kW"):
        block["eras"][era] = {}
''', '''    for era in ("hp", "kW"):
        block["eras"][era] = {}
    block["reading"] = ["BMS-reported possible power (logged / app-calculated); the input channel covers generator charging and regeneration and does not separate them",
                        "values at or above 63.70 kW are printed as at the logged maximum; zero-width intervals are degenerate, not precise",
                        "a cold-bin value is a cell value only; no ordered relation below the warm bins is established for the below-maximum median; the 5 C bin is exploratory",
                        "an ordering of the logged-maximum share is consistent with a saturated byte hiding a warm-bin rise and with a fixed cap; it identifies neither",
                        "no cross-era and no cold-versus-warm contrast; era and season are confounded; the below-maximum statistics are selected on the outcome",
                        "dropped samples (missing pack temperature or SoC) are not random; the cadence-regime sensitivity pools SoC and is not like-for-like"]
    block["disclosures"] = ["Rev 1.1 sample rules were ambiguous: the first blind audit pass did not reproduce the ladder; the Rev 1.2 rules (per-probe nearest reading within 5 s, SoC without the spike filter, I and V nearest within 2 s) were written after a result had been seen and the re-audit reproduced every audited field",
                            "output direction: the logged-maximum marker, not a ceiling (owner decision O1)", "no article use without the Opus audit and Andrii's sign-off"]
    block["notIndependentlyReproduced"] = ["bootstrap intervals", "longestRunAtMaximumS"]
''')
open(p, 'w', encoding='utf-8').write(t)

p = 'tests/synthetic/test_m658_bms_power_map.py'
t = open(p, encoding='utf-8').read()
t = rep(t, 'assert e2["supportedBinsContiguous"] is True and e2["monotone"]["belowMaxMedian"] == "increasing with pack temperature", e2["monotone"]',
        'assert e2["supportedBinsContiguous"] is True and e2["monotone"]["belowMaxMedian"] == "kW era, input direction, SoC 55-66 %: below-maximum median is higher in each warmer supported bin (10-30 C); descriptive, not a temperature effect", e2["monotone"]')
t = rep(t, 'assert ev["supportedPackTempRangeC"] == [10, 40] and ev["supportedBinsContiguous"] is False, (ev["supportedPackTempRangeC"], ev["supportedBinsContiguous"])',
        'assert ev["supportedPackTempOuterBinEdgesC"] == [10, 40] and ev["supportedPackTempBinsC"] == [10, 15, 20, 25, 35] and ev["supportedBinsContiguous"] is False')
t = rep(t, 'assert ev["monotone"]["belowMaxMedian"].startswith("no ordered relation is established"), ev["monotone"]', 'assert "no ordered relation is established" in ev["monotone"]["belowMaxMedian"], ev["monotone"]')
t = rep(t, 'assert e2["monotone"]["maxShare"].startswith("no ordered relation is established"), "ties (all 0) are not ordered"', 'assert "no ordered relation is established" in e2["monotone"]["maxShare"], "ties (all 0) are not ordered"')
t = rep(t, '# determinism and regimes', '# distinct values are counted on the grid, not as floats; fixed texts present\nassert ev["saturation"]["distinctValuesWithin1kWBelowMaximum"] == 1 and "notIndependentlyReproduced" in B and len(B["reading"]) == 6 and "power" in iv\n# determinism and regimes')
open(p, 'w', encoding='utf-8').write(t)
print('ok')
