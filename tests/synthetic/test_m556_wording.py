"""M556: every wording rule added by M553-M556 must FIRE on its target phrases and stay silent on the dashboard wording (a rule written with an uppercase literal or a doubled escape never fires: the gate normalises to lower case)."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as L

fire = {
    "M553-N13-window-use": ["the window is used up", "this proves the thesis", "measured net charge excursion", "usable capacity of 2.1 kWh", "pooled windows"],
    "M554-F17-N06-bridge": ["no usable raw current", "the union clock energy is true", "apparent capacity is true capacity"],
    "M555-N12-cell-observability": ["G01 is the sum of the cells", "G01 equals cell 1", "pack voltage equals the sum of cells", "sensor error in Max cell voltage", "simultaneous cell polling", "cell imbalance was measured"],
    "M557-N08-dependency": ["independent validation by a rolling origin split", "derived sibling validates its parent", "circular check confirms the result", "shared input check is independent"],
    "M559-N03-purpose": ["the engine runs to warm up", "fuel cut is confirmed", "confirmed dissipation", "the purpose of the engine is heating", "exclusive purpose label"],
    "M561-N02-uninterrupted": ["a reversal penalty", "sustained power rating", "continuous discharge capability", "steady power of 12 kW"],
    "M560-csr": ["the cell spread is balanced", "pairing did not matter", "unchanged by forward fill"],
    "M556-N05-signal-validity": ["the 12 V battery is dead", "failed DC/DC converter", "sensor fault", "measured 0 V", "not supported by the ECU", "intake air sensor fault", "zero-voltage supply"],
}
clean = ["highest mean power observed over a window with no change of direction (sample-interpolated zero)", "candidate labels are not exclusive and none states the purpose of the engine", "unresolved without the thermal context label", "fuel cut candidate (proxy)", "unavailable (all logged values equal 0 in 32 files)", "BMS-reported, logged channels, polled in a cycle: they are not simultaneous", "Max below Min beyond resolution in 0.69 % of polling-cycle pairs",
         "recoverable under an alternative alignment (union clock)", "share of the assumed 2.1 kWh window (verified:false)", "net charge excursion (Ah, integrated, estimated)", "Independent re-integration (M220, true trapezoidal)", "pre-registered decision rule; circular with its target by construction"]
for rid, phrases in fire.items():
    for ph in phrases:
        assert rid in L.scan_text(ph), (rid, ph)
for ph in clean:
    hit = [r for r in L.scan_text(ph) if r.split("-")[0] in ("M553", "M554", "M555", "M556", "M557", "M559", "M560", "M561")]
    assert not hit, (ph, hit)
print("test_m556_wording OK")
