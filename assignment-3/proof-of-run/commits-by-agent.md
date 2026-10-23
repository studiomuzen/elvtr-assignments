# Commits made by the crew — Oct 2026

Attribution per commit is based on the message content (which worker drove the change) and the task-spec linkage. All commits land on `main` of the Unity project repo and run through HQ's gate.

Grouped by owning agent, newest-first within each group.

## HQ (opus)
_System-level: structured messaging, context budget, protection boundaries, validation bridge, architecture docs._

- **`c14670a`** — Architecture docs auto-generated from live crew state. New `scripts/gen_architecture.py` + wired into the PostToolUse hook + sentry got the model-parity check.
- **`04440c5`** — Validation bridge: PostToolUse hook on Write/Edit. JSON schema check for `Assets/Data/`, `.claude/state/`, `.claude/messages/` + Roslyn syntax check for `.cs`. 5 new schemas (`terrain_speed`, `level`, `map_manifest`, `project_state`, `message`).
- **`43ac811`** — Pre-change snapshot rule + live JSON hot reload with Play-mode test. Added the rule in CLAUDE.md and in forge / painter / cartographer charters.
- **`8eb0ee2`** — Context management: archive closed specs (220 moved via `git mv`), rolling decisions log (`decisions.md`, ≤ 2 pages, HQ-only writes), two-file reading rule.
- **`001bada`** — Structured message passing added. New `.claude/state/project.json`, `.claude/messages/<id>.json` schema with required `evidence`, protection boundaries, sentry's protected-path audit.
- **`234062e`** — Close civilian cluster + task 307; add overnight-continuation report. Four civilian tasks closed as superseded by prototype-scope decision.
- **`c1aab2d`** — Triage task specs — close 215 of 239 completed/superseded tasks (added `status: closed` + `closed_reason` per spec).

## forge (opus)
_C# gameplay code + Play-mode tests._

- **`5f9e19e`** — Fix HUD occupying ~37% of screen — reset localScale to (1,1,1) on bar + panels. Added `Assets/Tests/PlayMode/HudHeightTest.cs` with four `[UnityTest]` methods including camera-zoom + pan invariance (pilot-visor rule).
- **`bbb4987`** — MVP support scripts: `WaveSpawner`, 8-minute hold timer, result screen with Restart.
- **`b9b4c04`** — M4 Intel timing fix (`calmDurationSeconds` 10 → 2, `scoutInterval` 4 → 1) + `color_config` infantry entries.
- **`10bf9e6`** — Level-select dropdown + Build Settings scene list (runtime-generated dropdown scanning `Assets/Data/levels/*.json`).
- **`43ac811`** (shared with HQ) — `Assets/Scripts/Game/DataHotReload.cs` + `TerrainSpeed.cs` hot-reload wiring + `Assets/Tests/PlayMode/DataHotReloadTest.cs`.

## cartographer (haiku)
_Level scenes + JSON manifests from OpenStreetMap._

- **`5c46df6`** — L_05 Serebrianske Forest wooded hills + ravine — scene + manifest.
- **`7cd0a4f`** — L_04 Siverskyi Donets fields + river — scene + manifest.
- **`00176cc`** — L_03 Severodonetsk Azot industrial — scene + manifest.
- **`52eac16`** — L_02 Soledar town centre — scene + manifest.
- **`1133a51`** — MVP wiring + L_01 base.
- **`b0dd03b`** — Scene densification for Levels 01, 03, 04, 05 — populate geometry per manifests (12 houses in L_01, 4 boundary strips in L_03, 15 trees in L_04, road + ravine + 19 tree clumps + 2 clearings in L_05).
- **`ed848f3`** — Add FlatTest's camera + HUD + lighting + 22 shared systems to all 5 level scenes (temporary wrapper prefab so cross-references stayed intact).

## painter (opus)
_Vehicle sprites: Blender → pixelate v4 → color grade pipeline._

- **`d5c8848`** — Upright-orientation fix for all 17 vehicles — one contact sheet, awaiting approval. Introduced `scripts/build_orient_blend.py` + `scripts/render_upright_check.py` + the `art-source/orient_all.blend` hand-correction workflow.
- **`b1cc609`** — Agent model refresh, full-roster sprite sheets, Blender pipeline, CameraPan rewrite.
- **`23a1caa`** — Class-run batch 1: pixelation scale-consistency fix (`union_bbox()` across all 16 frames), pick sheets, terrain speed, unit cap, painter-b charter.

## sentry (opus)
_QA reports + protected-path audits._

- **`ebcffb4`** — Sentry audit artifacts for commit `001bada` — protected-path audit PASS. First application of the git-diff audit.
- **`612dfdb`** — MVP PASS — minimum playable battle verified in Play mode (6/6).
- Many `.claude/reports/sentry-*.md` per-task reports (not individually committed; land inline with the task they verify).

## playtest (sonnet)
_End-of-milestone full-battle playthroughs._

- Milestone reports under `.claude/reports/milestone-<id>-playtest.md`. The playtest agent runs at milestone boundaries only, so there are fewer dedicated commits than other workers; its output lives alongside the forge/cartographer commits that closed each milestone.

## ledger (haiku)
_JSON data + schemas._

- Ledger's work is nearly always bundled into other agents' commits (shipping a new squad JSON ships alongside the forge task that reads it). Dedicated ledger commits live further back in history, e.g. the squad-stat JSON pass. More recently, ledger's responsibility expanded to schema maintenance — the 5 new schemas in `04440c5` are ledger-domain even though they landed in an HQ-authored commit.

## Mixed / cleanup
- **`24636b4`** — Delete leftover medieval-theme files from pre-Ambush pivot (`CaravanMover.cs`, `GameManager.cs`, `HighwaymanPlayer.cs`, `HudController.cs`, `HighwaymanGreen.mat`, `WagonBrown.mat`). Not owned by one worker — HQ cleanup pass.
- **`b8c2435`** — Overnight run report. HQ-authored summary of the overnight class-run.

## Totals (visible window: last ~40 commits)

| Agent | Commits | Primary output |
|---|---|---|
| HQ | 7 | design doc + crew conventions + protection + validation |
| forge | 5 | gameplay C# + Play-mode tests |
| cartographer | 7 | 5 level scenes + manifests + MVP wiring |
| painter | 3 | vehicle sprite pipeline + 17-vehicle contact sheet |
| sentry | 2 commits + many inlined reports | QA verdicts + audit artifacts |
| playtest | milestone reports | end-of-milestone bug lists |
| ledger | bundled with others | JSON data + schema maintenance |
