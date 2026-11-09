#!/usr/bin/env python3
"""Turn one generated assault manifest into an isolated sim scenario, so the content is proven
to load and play in the engine (SimRunner) without a full battle.

    python3 tools/content_pipeline/manifest_to_sim.py [--manifest 0] [--out S34_generated_assault]

Mapping: the player line is a rifle squad + a heavy-weapons squad at the origin; the manifest's spawn
zone is placed 700 m ahead (north) or 700 m to the side (east). Waves cannot start late in the sandbox,
so a later wave starts further back by delay_s × 5 m/s. Armour starts lead_m ahead of the infantry it
leads; transports load their cargo squad (SimRunner `cargo`). Every enemy unit is ordered Forward to the
player line. Flags on: the vehicle movement rules (N247) so armour keeps column gaps.
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(REPO, "ELVATR GAME 1/Assets/Resources/Data/content/assault_manifests_01.json")
SIM = os.path.join(REPO, "ELVATR GAME 1/Assets/Data/sim")
ZONE_ORIGIN = {"enemy_north": (0.0, 700.0, (1, 0), (0, 1)), "enemy_east": (700.0, 0.0, (0, 1), (1, 0))}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--manifest", type=int, default=0)
    ap.add_argument("--out", default="S34_generated_assault"); a = ap.parse_args()
    doc = json.load(open(SRC)); m = doc["manifests"][a.manifest]
    units = [{"id": "P1", "template": "PlayerSquad_1", "pos": [-20, 0, 0], "order": "hold"},
             {"id": "P2", "template": "PlayerSquad_8", "pos": [20, 0, 0], "order": "hold"}]
    cargo_of = {u["cargo"] for w in m["waves"] for u in w["units"] if u.get("cargo")}
    enemy_ids = []
    for w in m["waves"]:
        ox, oz, along, depth = ZONE_ORIGIN[w["spawn_zone"]]
        back = w["delay_s"] * 5.0
        for u in w["units"]:
            dx, dd = u["offset_m"]
            dd = dd + back - u.get("lead_m", 0)          # armour starts lead_m ahead of the infantry
            x = ox + along[0] * (dx - 100) + depth[0] * dd
            z = oz + along[1] * (dx - 100) + depth[1] * dd
            e = {"id": u["id"], "template": u["template"], "pos": [round(x, 1), 0, round(z, 1)],
                 "order": "hold" if u["id"] in cargo_of else "forward", "goal": [0, 0, 0]}
            if u.get("cargo"): e["cargo"] = u["cargo"]
            units.append(e); enemy_ids.append(u["id"])
    sc = {
        "id": a.out,
        "title": f"Generated assault '{m['name']}' (content pipeline, manifest {a.manifest}) loads and advances",
        "problem": "Assignment 4: prove the pipeline's assault manifest is valid engine content — every unit spawns from its template, transports carry and unload their squads in the 300-600 m band, armour leads.",
        "duration_s": 60, "time_scale": 1, "fog_of_war": False, "playable_area": False, "seed": 3401,
        "camera": {"follow": enemy_ids[:3]},
        "flags": [{"name": "VehicleMovementRules", "value": True}],
        "units": units,
        "action": {"at_s": 1, "verb": "none"},
        "expect": [
            {"metric": "units_spawned", "op": "==", "value": len(units), "why": "every manifest unit maps to a sandbox template and spawns"},
            {"metric": "transport_unload_distance_m", "op": ">=", "value": 300, "why": "GDD 06: transports stop 300-600 m out and unload"},
            {"metric": "transport_unload_distance_m", "op": "<=", "value": 600, "why": "GDD 06: transports stop 300-600 m out and unload"},
            {"metric": "exceptions", "op": "==", "value": 0, "why": "the content loads without runtime errors"},
            {"metric": "log_errors", "op": "==", "value": 0, "why": "no error lines while the assault runs"},
        ],
    }
    out = os.path.join(SIM, a.out + ".json")
    json.dump(sc, open(out, "w"), indent=2, ensure_ascii=False); open(out, "a").write("\n")
    print(f"wrote {os.path.relpath(out, REPO)}: {len(units)} units ({len(enemy_ids)} from the manifest)")


if __name__ == "__main__":
    sys.exit(main())
