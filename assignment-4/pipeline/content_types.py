"""Content types for the Ambush! content pipeline: which GDD files feed each one, the task text,
the JSON schema, the deterministic rule checks, and where the result is written in the game."""
import re

REPO_GAME_DATA = "ELVATR GAME 1/Assets/Resources/Data/content"
ENEMY_TEMPLATES = {
    "EnemyMBT_1": "armor", "EnemyIFV_1": "armor", "EnemyTransport_1": "transport",
    "EnemySquad_1": "infantry", "EnemyAA_1": "aa", "EnemyEWTruck": "ew", "EnemyPickup": "light",
    "T90": "armor", "Koalitsiya": "artillery",
}
PHASES = ["Intel", "Scouting", "Bombardment", "VehicleAdvance", "MechanizedInfantry"]
BANNED = re.compile(r"\b(lorem|ipsum|tbd|todo|placeholder|example|foo|bar|unit [0-9a-z]\b|xxx)\b", re.I)
PLACEHOLDERS = {"unit", "enemy", "distance", "squad", "vehicle", "zone", "count"}


def _strings(o, path="$"):
    if isinstance(o, str):
        yield path, o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _strings(v, f"{path}[{i}]")


def common_text_checks(doc):
    issues = []
    for path, s in _strings(doc):
        if BANNED.search(s):
            issues.append(f"{path}: placeholder/generic word in '{s[:60]}'")
        for ph in re.findall(r"\{(\w+)\}", s):
            if ph not in PLACEHOLDERS:
                issues.append(f"{path}: unknown placeholder {{{ph}}} (allowed: {sorted(PLACEHOLDERS)})")
    return issues


# ---------------------------------------------------------------- (a) assault manifests
ASSAULT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["level", "manifests"],
    "properties": {
        "level": {"const": "01"},
        "manifests": {"type": "array", "minItems": 2, "maxItems": 2, "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "name", "intent", "waves"],
            "properties": {
                "id": {"type": "string", "pattern": "^[a-z0-9_]+$"}, "name": {"type": "string", "minLength": 4},
                "intent": {"type": "string", "minLength": 20},
                "waves": {"type": "array", "minItems": 2, "maxItems": 3, "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["label", "phase", "delay_s", "spawn_zone", "units"],
                    "properties": {
                        "label": {"type": "string"}, "phase": {"enum": ["VehicleAdvance", "MechanizedInfantry"]},
                        "delay_s": {"type": "number", "minimum": 0, "maximum": 120},
                        "spawn_zone": {"enum": ["enemy_north", "enemy_east"]},
                        "units": {"type": "array", "minItems": 1, "items": {
                            "type": "object", "additionalProperties": False, "required": ["id", "template", "offset_m"],
                            "properties": {
                                "id": {"type": "string", "pattern": "^[A-Za-z0-9_]+$"},
                                "template": {"enum": sorted(ENEMY_TEMPLATES)},
                                "offset_m": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                                "cargo": {"type": "string"}, "unload_m": {"type": "number"},
                                "lead_m": {"type": "number"}}}}}}}}}}},
}


def assault_rules(doc):
    issues = []
    for m in doc.get("manifests", []):
        mid = m.get("id"); units = [u for w in m["waves"] for u in w["units"]]
        ids = [u["id"] for u in units]
        if len(ids) != len(set(ids)):
            issues.append(f"{mid}: duplicate unit ids")
        n = len(units)
        if not (10 <= n <= 15):
            issues.append(f"{mid}: {n} commandable units; GDD 03 unit cap is 10 to 15 per side")
        phases = [w["phase"] for w in m["waves"]]
        if phases[0] != "VehicleAdvance":
            issues.append(f"{mid}: first wave phase is {phases[0]}; GDD 06 armour leads, so wave 1 must be VehicleAdvance")
        if [PHASES.index(p) for p in phases] != sorted(PHASES.index(p) for p in phases):
            issues.append(f"{mid}: wave phases out of order {phases}")
        delays = [w["delay_s"] for w in m["waves"]]
        if delays != sorted(delays):
            issues.append(f"{mid}: wave delays not ascending {delays}")
        w1 = m["waves"][0]["units"]
        if not any(ENEMY_TEMPLATES[u["template"]] == "armor" for u in w1):
            issues.append(f"{mid}: wave 1 has no MBT/IFV — armour must lead")
        cargo_ids = set()
        for u in units:
            role = ENEMY_TEMPLATES[u["template"]]
            if role == "transport":
                if "cargo" not in u:
                    issues.append(f"{mid}/{u['id']}: transport without cargo")
                else:
                    cargo_ids.add(u["cargo"])
                    tgt = next((x for x in units if x["id"] == u["cargo"]), None)
                    if not tgt or ENEMY_TEMPLATES[tgt["template"]] != "infantry":
                        issues.append(f"{mid}/{u['id']}: cargo '{u['cargo']}' is not an infantry squad in this manifest")
                if not (300 <= u.get("unload_m", -1) <= 600):
                    issues.append(f"{mid}/{u['id']}: unload_m {u.get('unload_m')} outside GDD 06 300–600 m")
            elif "unload_m" in u or "cargo" in u:
                issues.append(f"{mid}/{u['id']}: only transports carry cargo / unload_m")
            if role == "armor" and not (50 <= u.get("lead_m", -1) <= 200):
                issues.append(f"{mid}/{u['id']}: armour lead_m {u.get('lead_m')} outside 50–200 m ahead of the infantry (research §2, armor_lead_open_m)")
        infantry = [u for u in units if ENEMY_TEMPLATES[u["template"]] == "infantry"]
        if not infantry:
            issues.append(f"{mid}: no infantry — a mechanised assault needs dismounts")
        if not cargo_ids:
            issues.append(f"{mid}: no transport carries infantry — GDD 06 transports unload at 300–600 m")
    if len(doc.get("manifests", [])) == 2 and doc["manifests"][0]["waves"] == doc["manifests"][1]["waves"]:
        issues.append("the two manifests are identical")
    return issues + common_text_checks(doc)


# ---------------------------------------------------------------- (b) unit cards
WEAPON = {"type": "object", "additionalProperties": False,
          "required": ["name", "kind", "range_m", "damage_vs_soft", "damage_vs_light", "damage_vs_heavy", "reload_s"],
          "properties": {"name": {"type": "string"}, "kind": {"enum": ["rifle", "hmg", "atgm", "rpg"]},
                         "range_m": {"type": "number"}, "damage_vs_soft": {"type": "number", "minimum": 0},
                         "damage_vs_light": {"type": "number", "minimum": 0}, "damage_vs_heavy": {"type": "number", "minimum": 0},
                         "reload_s": {"type": "number", "exclusiveMinimum": 0}}}
CARDS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["cards"],
    "properties": {"cards": {"type": "array", "minItems": 2, "maxItems": 2, "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "name", "side", "role", "soldiers", "hp_per_soldier", "weapons", "strong_against", "weak_against", "card_text"],
        "properties": {
            "id": {"enum": ["javelin_team", "heavy_mg_squad"]}, "name": {"type": "string"}, "side": {"enum": ["UA"]},
            "role": {"type": "string"}, "soldiers": {"type": "integer", "minimum": 2, "maximum": 6},
            "hp_per_soldier": {"type": "number", "minimum": 50, "maximum": 150},
            "weapons": {"type": "array", "minItems": 1, "items": WEAPON},
            "strong_against": {"type": "array", "items": {"enum": ["soft", "light", "heavy", "infantry"]}},
            "weak_against": {"type": "array", "items": {"type": "string"}},
            "card_text": {"type": "string", "minLength": 40, "maxLength": 220}}}}},
}
RANGES = {"rifle": 180, "hmg": 220, "atgm": 300, "rpg": 180}


def cards_rules(doc):
    issues = []
    cards = {c["id"]: c for c in doc.get("cards", [])}
    if set(cards) != {"javelin_team", "heavy_mg_squad"}:
        issues.append(f"cards must be exactly javelin_team and heavy_mg_squad, got {sorted(cards)}")
    for c in doc.get("cards", []):
        for w in c["weapons"]:
            want = RANGES[w["kind"]]
            if w["range_m"] != want:
                issues.append(f"{c['id']}/{w['name']}: range_m {w['range_m']} ≠ GDD 04 {w['kind']} range {want}")
            if w["kind"] == "rifle" and (w["damage_vs_light"] or w["damage_vs_heavy"]):
                issues.append(f"{c['id']}/{w['name']}: rifles damage soft-skin only (decision 5)")
            if w["kind"] == "hmg" and (w["damage_vs_light"] <= 0 or w["damage_vs_heavy"] != 0):
                issues.append(f"{c['id']}/{w['name']}: HMG must damage light armour and not heavy (decision 5)")
            if w["kind"] in ("atgm", "rpg") and w["damage_vs_heavy"] <= 0:
                issues.append(f"{c['id']}/{w['name']}: AT weapon must damage heavy armour")
        kinds = {w["kind"] for w in c["weapons"]}
        if c["id"] == "javelin_team" and "atgm" not in kinds:
            issues.append("javelin_team has no atgm weapon")
        if c["id"] == "heavy_mg_squad" and "hmg" not in kinds:
            issues.append("heavy_mg_squad has no hmg weapon")
    return issues + common_text_checks(doc)


# ---------------------------------------------------------------- (c) in-battle text
LINES = {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string", "minLength": 8, "maxLength": 90}}
TEXT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["briefing", "phase_radio", "event_log", "routing_message"],
    "properties": {
        "briefing": {"type": "object", "additionalProperties": False, "required": ["title", "lines"],
                     "properties": {"title": {"type": "string", "maxLength": 40},
                                    "lines": {"type": "array", "minItems": 3, "maxItems": 5, "items": {"type": "string", "maxLength": 110}}}},
        "phase_radio": {"type": "object", "additionalProperties": False, "required": PHASES,
                        "properties": {p: LINES for p in PHASES}},
        "event_log": {"type": "object", "additionalProperties": False,
                      "required": ["enemy_spotted", "squad_lost", "vehicle_destroyed", "drone_hit", "artillery_incoming", "transport_unloading"],
                      "properties": {k: LINES for k in ["enemy_spotted", "squad_lost", "vehicle_destroyed", "drone_hit", "artillery_incoming", "transport_unloading"]}},
        "routing_message": {"type": "string", "minLength": 10, "maxLength": 70},
    },
}


def text_rules(doc):
    issues = []
    seen = {}
    for path, s in _strings(doc):
        k = s.strip().lower()
        if k in seen:
            issues.append(f"{path}: duplicate of {seen[k]}")
        seen[k] = path
        if "!" in s and path != "$.briefing.title":
            issues.append(f"{path}: exclamation mark — the tone is grounded and serious (GDD 01)")
    if "rout" not in doc.get("routing_message", "").lower():
        issues.append("routing_message must say the enemy is routing (GDD 13 decision 29: 'victory is near' once the rout starts)")
    if "victory" not in doc.get("routing_message", "").lower():
        issues.append("routing_message must carry 'victory is near' (decision 29)")
    for k, lines in doc.get("event_log", {}).items():
        if k in ("squad_lost", "vehicle_destroyed", "enemy_spotted") and not any("{" in l for l in lines):
            issues.append(f"$.event_log.{k}: at least one line must name the unit with a placeholder like {{unit}}")
    return issues + common_text_checks(doc)


TYPES = {
    "assault": {
        "gdd": ["docs/gdd/06-ai.md", "docs/gdd/03-units-and-scale.md", "docs/gdd/07-map-flattest.md"],
        "extra": ["ELVATR GAME 1/Assets/Resources/Data/levels/01.json"],
        "task": ("Write TWO different enemy assault manifests for FlatTest (level 01). Each manifest is a plan the "
                 "WaveSpawner plays: 2–3 waves. Wave 1 is the VehicleAdvance phase and MUST be led by armour (MBT/IFV) "
                 "with transports carrying infantry squads behind; later waves are MechanizedInfantry. Transports set "
                 "unload_m between 300 and 600 m (distance from the nearest player unit where the cargo dismounts) and "
                 "name their cargo squad id; armour sets lead_m 50–200 (how far ahead of the infantry it holds). "
                 "offset_m is [x, z] metres inside the spawn zone (x along the zone, z depth behind its edge, 0–60). "
                 "Respect the unit cap of 10 to 15 commandable units per manifest (vehicles + squads, cargo squads count). "
                 "Use only these templates: " + ", ".join(sorted(ENEMY_TEMPLATES)) + ". Make the two manifests tactically "
                 "different (e.g. one frontal push from the north on the road, one with the main effort from the east) "
                 "and describe each in 'intent' in one or two staff-style sentences."),
        "schema": ASSAULT_SCHEMA, "rules": assault_rules, "out": "assault_manifests_01.json",
    },
    "unit_cards": {
        "gdd": ["docs/gdd/03-units-and-scale.md", "docs/gdd/04-combat.md"],
        "extra": ["ELVATR GAME 1/Assets/Resources/Data/weapons.json"],
        "task": ("Write unit data cards for two Ukrainian units: the Javelin team (id javelin_team) and the heavy machine-gun "
                 "squad (id heavy_mg_squad). Use the GDD fire ranges exactly (small arms 180 m, heavy machine gun 220 m, "
                 "Javelin/ATGM 300 m) and the damage classes: rifles hurt soft-skin only, the HMG hurts soft and light armour "
                 "but not heavy, AT weapons hurt heavy armour. Give each weapon a kind (rifle|hmg|atgm|rpg). card_text is the "
                 "one-line tooltip a player reads on the unit card (what it is for, what it fears)."),
        "schema": CARDS_SCHEMA, "rules": cards_rules, "out": "unit_cards.json",
    },
    "battle_text": {
        "gdd": ["docs/gdd/01-vision.md", "docs/gdd/06-ai.md", "docs/gdd/09-ux-audio-accessibility.md", "docs/gdd/12-decisions.md"],
        "extra": [],
        "task": ("Write the in-battle text for one FlatTest battle: a pre-battle briefing (title + 3–5 lines a company "
                 "commander reads before the assault), HQ radio/intel lines for each battle phase in order Intel, Scouting, "
                 "Bombardment, VehicleAdvance, MechanizedInfantry (2–4 lines each, ≤ 90 chars), event-log lines for "
                 "enemy_spotted, squad_lost, vehicle_destroyed, drone_hit, artillery_incoming, transport_unloading (2–4 each, "
                 "≤ 90 chars; use placeholders {unit} {enemy} {distance} {squad} {vehicle} {zone} {count} where a name or "
                 "number goes), and routing_message: the one line shown when the enemy starts to rout, which must say "
                 "the enemy is routing and that victory is near (≤ 70 chars). Grounded, terse radio voice. The assault order in "
                 "FlatTest is armour first (VehicleAdvance), then mechanised infantry carried by transports (MechanizedInfantry): "
                 "transports exist, so decision 4's 'armour leads' applies — never say infantry comes first. The player has four "
                 "orders only (Forward, Hold, Back, Retreat); do not invent fire orders."),
        "schema": TEXT_SCHEMA, "rules": text_rules, "out": "battle_text.json",
    },
}
