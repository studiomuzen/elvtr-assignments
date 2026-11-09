#!/usr/bin/env python3
"""Self-test for the deterministic checks: feeds deliberately broken copies of the shipped outputs and
asserts each rule fires. No LLM calls.   python3 tools/content_pipeline/test_checks.py"""
import copy, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from run import deterministic          # noqa: E402
from content_types import TYPES        # noqa: E402

OUT = os.path.join(HERE, "out")
cases = []

def case(ctype, name, mutate, expect):
    good = json.load(open(os.path.join(OUT, TYPES[ctype]["out"])))
    assert not deterministic(good, TYPES[ctype]), f"{ctype}: shipped output should pass"
    bad = copy.deepcopy(good); mutate(bad)
    issues = deterministic(bad, TYPES[ctype])
    hit = [i for i in issues if expect in i]
    cases.append((ctype, name, bool(hit), hit[0] if hit else (issues[:1] or ["(no issue)"])[0]))

def transports(d):
    return [u for w in d["manifests"][0]["waves"] for u in w["units"] if u["template"] == "EnemyTransport_1"]

case("assault", "transport unloads at 200 m", lambda d: transports(d)[0].__setitem__("unload_m", 200), "outside GDD 06 300–600")
case("assault", "infantry wave first", lambda d: d["manifests"][0]["waves"][0].__setitem__("phase", "MechanizedInfantry"), "armour leads")
case("assault", "unit cap broken (18 units)", lambda d: d["manifests"][0]["waves"][-1]["units"].extend(
    [{"id": f"X{i}", "template": "EnemySquad_1", "offset_m": [i, 0]} for i in range(8)]), "unit cap")
case("assault", "unknown template", lambda d: d["manifests"][0]["waves"][0]["units"][0].__setitem__("template", "Abrams"), "schema")
case("unit_cards", "HMG range 300", lambda d: [w.__setitem__("range_m", 300) for c in d["cards"] if c["id"] == "heavy_mg_squad" for w in c["weapons"] if w["kind"] == "hmg"], "GDD 04 hmg range 220")
case("unit_cards", "HMG hurts tanks", lambda d: [w.__setitem__("damage_vs_heavy", 30) for c in d["cards"] if c["id"] == "heavy_mg_squad" for w in c["weapons"] if w["kind"] == "hmg"], "decision 5")
case("battle_text", "phase missing", lambda d: d["phase_radio"].pop("Bombardment"), "schema")
case("battle_text", "placeholder text", lambda d: d["event_log"]["drone_hit"].__setitem__(0, "TODO drone line"), "placeholder")
case("battle_text", "exclamation / tone", lambda d: d["phase_radio"]["Intel"].__setitem__(0, "Here they come, lads!"), "exclamation")
case("battle_text", "routing line without victory", lambda d: d.__setitem__("routing_message", "The enemy is routing."), "victory")

w = max(len(n) for _, n, _, _ in cases)
fails = 0
for ctype, name, ok, msg in cases:
    fails += not ok
    print(f"{'CAUGHT' if ok else 'MISSED'}  {ctype:<11} {name:<{w}}  -> {msg[:110]}")
print(f"\n{len(cases) - fails}/{len(cases)} broken inputs caught")
sys.exit(1 if fails else 0)
