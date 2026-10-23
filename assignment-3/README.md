# Assignment 3 — the Ambush! agent crew

**Ambush!** is a real-time, grounded, drone-era tactics game set across the real map of Ukraine. Trench-and-drone warfare, StarCraft-style three-quarter top-down camera, one deployment phase per battle → one real-time fight. **Not an RTS economy, not turn-based.** General orders only (forward / hold / back / retreat with a direction); how well units execute depends on veterancy and intelligence, not micro. Drones are a core pillar, with the full real-world counter stack modelled (jamming, shootdown, netting, concealment, interceptors, striking the operators). Civilian casualties count against the score.

This submission is the **multi-agent development crew** that builds the game — not the game itself. The game lives in a separate Unity 6 / URP project. Everything you need to run this crew against your own project is here, plus proof it ran against ours.

---

## 1. What the crew produces for the game

Every piece of the actual Unity project comes out of one of these workers. Each column maps crew output → game artefact:

| Output in the Unity project | Owner | Path |
|---|---|---|
| C# gameplay code + Play-mode tests | **forge** | `Assets/Scripts/`, `Assets/Tests/PlayMode/` |
| JSON data (unit stats, tech tree, terrain speeds, level manifests, drone defs) + JSON Schemas | **ledger** | `Assets/Data/`, `scripts/schemas/` |
| Pixel-art vehicle sprites (Blender → `pixelate_v4.py` → `color_grade.py`) | **painter** | `Assets/Art/Vehicles/<Name>_sheet.png` |
| Pixel-art infantry sprites (same pipeline, 5 roles × 2 sides × 4 poses × 8 directions) | **painter-b** | `Assets/Art/Vehicles/<Role><Side>_<Pose>_sheet.png` |
| Level `.unity` scenes + JSON manifests sourced from OpenStreetMap | **cartographer** | `Assets/Scenes/Level_<id>_<slug>.unity`, `Assets/Data/levels/<id>.json` |
| Per-task QA reports + protected-path audits + architecture-diagram parity checks | **sentry** | `.claude/reports/sentry-<id>.md` |
| End-of-milestone full-battle playthroughs + bug lists + ≥ 4 screenshots | **playtest** | `.claude/reports/milestone-<id>-playtest.md` |

HQ is the only agent allowed to edit `CLAUDE.md`, `.claude/agents/*.md`, `.claude/state/project.json`, and the task specs under `.claude/tasks/`.

---

## 2. Working crew — the roster

Models are the short-name form only (`opus` / `sonnet` / `haiku`). The full-ID form (e.g. `claude-sonnet-4-6`) silently falls back to the parent — see the stress-test findings below.

| Agent | Model | Role | Input | Output | What breaks if removed |
|---|---|---|---|---|---|
| **hq** | `opus` | Orchestrator. Splits the user ask into small task specs; sole writer of shared state; ingests every structured message; rejects any missing evidence. | User asks + `.claude/state/project.json` + `decisions.md` + every incoming `.claude/messages/<id>.json` | `.claude/tasks/<id>-<slug>.json` task specs + updates to `project.json` + `decisions.md` | No orchestration. Workers freelance, task specs rot, the design doc drifts, nobody owns rejecting bad handoffs. |
| **forge** | `opus` | C# gameplay programmer. Writes production code + a Play-mode test per acceptance criterion. Never touches scenes, prefabs, materials, or UI assets. | Task spec + `project.json` + `decisions.md` + the current game code | New `Assets/Scripts/*.cs` + `Assets/Tests/PlayMode/*Tests.cs` + structured message with JUnit XML evidence | No new gameplay. Combat, HUD, drones, scoring — all code-authored. |
| **ledger** | `haiku` | Data author. Owns every JSON file under `Assets/Data/` plus the 8 JSON Schemas. No shipped file may trigger `WARNING skipped` from `validate_data.py`. | Task spec + the existing schema set + the data file to add/edit | New or edited `Assets/Data/*.json` + matching `scripts/schemas/*.schema.json` + validator-pass evidence | No data-driven tuning. Unit stats, tech-tree, terrain speeds all baked into code. |
| **painter** | `opus` | Vehicle sprite pipeline. Blender render → pixelate v4 → color grade. Hand-corrected orientation via `orient_all.blend`. | GLB in `art-source/models/` + `art-source/upright_rotations.json` + `color_config.json` | `Assets/Art/Vehicles/<Name>_sheet.png` + regenerated `_review_sheet.png` + `LICENSES.md` entry | No vehicles. All 17 real-world rigs (M1A2, T-90, PzH 2000, Tunguska, …) stay as placeholder cubes. |
| **painter-b** | `opus` | Infantry sprite pipeline, shared v4 settings with painter. | Rigged soldier GLB + poses + the shared color_config | `<Role><Side>_<Pose>_sheet.png` for every role × side × pose × direction | No soldier art. Battle camera reads just coloured blocks for every squad. |
| **cartographer** | `haiku` | Level builder. OpenStreetMap only; two-stage workflow (JSON manifest first, then Unity scene). Never edits scene YAML by hand. | OSM relation/way ID + the level spec + `project.json.assets.level_scenes` to avoid overwrites | `Assets/Data/levels/<id>.json` + `Assets/Scenes/Level_<id>_<slug>.unity` + console-clean evidence | No maps. The game can't load a scene to play on. |
| **sentry** | `opus` | QA. Fixed-format report, PASS/FAIL per `done_means` item, protected-path git-diff audit, architecture-diagram model-parity check. Never edits project files. | Task spec + `project.json` + `decisions.md` + the committed delta | `.claude/reports/sentry-<id>.md` + structured message with the verdict + bug list routed to forge | No verification. Broken builds ship. Protected files get silently rewritten by workers. Diagram drift goes unnoticed. |
| **playtest** | `sonnet` | End-of-milestone playtest. Plays a full battle from Setup → first contact → outcome. | The current state at a milestone boundary + the acceptance criteria from the milestone plan | `.claude/reports/milestone-<id>-playtest.md` + ≥ 4 screenshots + a bug list for forge | No end-to-end check. Per-task sentry pass isn't the same as "does the game feel playable in a real battle" — regressions sneak in. |

---

## 3. How a task flows through the crew

```
    Noah  ──┐
            ▼
          HQ (opus)
            │  reads  project.json + decisions.md + inbox + archive-on-demand
            │  writes .claude/tasks/<id>-<slug>.json  (one task per spec)
            ▼
    [forge | ledger | painter | painter-b | cartographer]
            │  reads  the task spec + project.json + decisions.md  (two-file rule)
            │  before changing anything: snapshot the current state → notes
            │  writes the artefact + .claude/messages/<id>.json (with evidence)
            │  shared handoff md → .claude/handoffs/<id>-<agent>.md
            ▼
          sentry (opus)
            │  reads  the task spec + the artefact + project.json
            │  runs   PlayMode test + protected-path git-diff audit
            │                       + architecture-diagram model-parity check
            │  writes .claude/reports/sentry-<id>.md  (Verdict: PASS | FAIL)
            │         + structured message tied to the task_id
            ▼
          HQ ingests the sentry message
            │  on PASS → updates project.json (assets, open_tasks), appends
            │            an entry to decisions.md, moves closed task spec
            │            to .claude/archive/tasks/
            │  on FAIL → routes the bug entry back to forge via a new task spec
            │  on BLOCKED (from any worker) → records the blocker in
            │            project.json.blocked[] with unblocks_tasks
            ▼
          back to Noah (or the next cycle)
```

**Rules the flow enforces, from CLAUDE.md:**

- **Protected paths.** `CLAUDE.md`, `.claude/agents/*.md`, `.claude/state/project.json`, `.claude/tasks/*.json` are HQ-only writes. If a worker thinks one of those needs to change, it emits a `status: blocked` message naming the file + the specific edit — HQ decides.
- **Pre-change snapshot.** Before editing a scene / prefab / material / JSON config, forge / cartographer / painter must read the current state (hierarchy, components, serialized values) and include that snapshot in the message's `notes`. No change without the snapshot.
- **Two-file reading rule.** Every worker starts a task reading only `project.json` + `decisions.md`. Historic reports, archived task specs, event logs — none of that is loaded by default. If a worker needs more, it emits `status: blocked` naming the artefact.
- **Structured handoff.** Every worker's `.claude/messages/<task-id>.json` must include an `evidence` array that resolves to real files or `test_result:*` / `sentry_report:*` tokens. HQ rejects any message with empty / unresolvable evidence.
- **Hot reload.** JSON configs under `Assets/Data/` reload while Play mode is running when the file changes on disk. Enforced by `DataHotReloadTest.cs`.
- **Hooks.** Every Write / Edit runs the PostToolUse hook: JSON schema check (if under `Assets/Data`, `.claude/state`, `.claude/messages`), Roslyn syntax check (if `.cs`), architecture-diagram regen (if CLAUDE.md, agent files, or task specs changed). On failure the hook exits 2 and Claude feeds the error back to the agent to fix.

---

## 4. Architecture diagrams

Three Mermaid diagrams at **[`docs/architecture.md`](docs/architecture.md)**, auto-generated by `scripts/gen_architecture.py` from the live crew state. The PostToolUse hook regenerates them on every edit to an agent file, CLAUDE.md, or a task spec — so the diagrams never drift from the source. Sentry fails the task if any agent's diagram-model doesn't match its frontmatter.

- **(a) Agent hierarchy** — Noah → HQ → each worker → Sentry → HQ, with every node showing its configured model (roles).
- **(b) Shared memory map** — read / write edges for `project.json`, `decisions.md`, `.claude/messages/`, `.claude/inbox/`, `.claude/tasks/`, `CLAUDE.md`, `.claude/archive/tasks/` (connections + data flow).
- **(c) Open-task dependency graph** — the live tasks from `.claude/tasks/` plus blocker nodes from `project.json.blocked[]`, drawn with "blocks" edges to every task in each blocker's `unblocks_tasks` array.

---

## 5. Proof it ran

Under `proof-of-run/`:

| File | What it proves |
|---|---|
| [`run-report.md`](proof-of-run/run-report.md) | One continuation run that produced 5 commits: HUD fix, medieval-cleanup, task triage (215 of 239 closed), scene densification for L_01/L_03/L_04/L_05, civilian cluster closure, agent-model attribution fix. |
| [`commits-by-agent.md`](proof-of-run/commits-by-agent.md) | ~25 recent commits grouped by owning agent, each line naming the artefact that commit produced. |
| [`message-01-sentry-protected-path-audit.json`](proof-of-run/message-01-sentry-protected-path-audit.json) | Real `status: done` message from sentry's protected-path audit on commit `001bada`. Evidence: `sentry_report:*` + `test_result:git-diff-audit-pass` + `test_result:non-hq-subagent-count=0`. |
| [`message-02-cartographer-densification-done.json`](proof-of-run/message-02-cartographer-densification-done.json) | Cartographer's `status: done` for task 307 (scene densification across L_01 / L_03 / L_04 / L_05). Includes the required pre-change snapshot inside `notes`. |
| [`message-03-painter-blocked.json`](proof-of-run/message-03-painter-blocked.json) | Painter's `status: blocked` for a sprite redo, citing the live `project.json.blocked[0]` entry (vehicle re-renders gated on user hand-correction in `orient_all.blend`). Shows the "worker proposes, HQ decides" flow — painter does NOT edit the task spec. |
| [`before/hud_bug_37pct.png`](proof-of-run/before/hud_bug_37pct.png) | HUD visibly occupying ~37 % of a 1920 × 1080 frame — the bug we hit six rebuild passes in a row. |
| [`after/hud_fixed_18pct.png`](proof-of-run/after/hud_fixed_18pct.png) | Same frame after the fix. HUD lands at 18 % as designed. Enforced going forward by `HudHeightTest.cs` with four `[UnityTest]` methods including an explicit camera-zoom + pan invariance (pilot-visor rule). |

All three messages validate against `scripts/schemas/message.schema.json`.

---

## 6. Problems found and how they were fixed

The crew tripped over the same shapes of bug enough times that each one became a rule. The full stress-test list (18 findings) lives at `docs/gdd-changes.md § Agent stress-test findings` in the live Unity-project repo. The four that most shaped the crew design:

### 1. Agent model config silently falling back to Opus
All five sonnet-tier agent files had `model: claude-sonnet-4-6` (the full ID) in frontmatter. Claude Code's parser only accepts the short enum (`opus` / `sonnet` / `haiku`); unknown values silently inherit from the parent (which was opus). Entire overnight sonnet workload got billed as opus with no warning. **Fix:** reverted all five to the short-name form. Added `Short-name form only.` as a hard rule in CLAUDE.md § Agent roster — models. Caught because the cost tab showed zero sonnet usage.

### 2. HUD visually 37% despite `anchor_ratio = 0.18`
Five prior fix passes each tweaked a surface symptom — anchor Y, header overlap, bestFit on text — without unifying the system. Real bug was `localScale 3.13` on the panels combined with `localScale 0.67` on HudBar: net 2.1× visual multiplier on top of a correct anchor. The initial Play-mode test measured `rect.height / rect.height` which is anchor-local and ignored localScale, so the test passed while the eye disagreed. **Fix:** found via `GetWorldCorners` (world-space, post-scale). Reset every HUD transform to `(1,1,1)`. Added the **pilot-visor rule** and four `[UnityTest]` methods including camera-zoom + pan invariance (delta < 0.001). Before/after shots live under `proof-of-run/`.

### 3. Auto-detected vehicle orientation got 16 of 17 wrong
A deterministic 24-way signed-axis-permutation search over SO(3) + a "mass on top → flip" heuristic. The `Z = shortest-dim` check passed in `orientation.json` for every vehicle, but the actual rendered sprites still showed 16 of 17 vehicles on their sides. **Fix:** gave up on auto-detect. `scripts/build_orient_blend.py` generates `art-source/orient_all.blend` with all 17 GLBs in a row, each parented to a labelled `<Name>_root` Empty. User rotates each Empty by hand in Blender GUI. `scripts/export_orient_rotations.py` dumps the resulting Euler to `art-source/upright_rotations.json`. Render script reads from that file as canonical. **Lesson: when input is author-dependent (Sketchfab conventions vary), a human eyeball + a cached matrix beats any axis heuristic.**

### 4. Cartographer wrongly declared a task blocked
The haiku-model cartographer agent reported task 307 as *blocked* because `manage_gameobject` "can't target specific scene files" — technically true, but the standard pattern is `manage_scene load` to make a scene active, then `manage_gameobject` operates on it. **Fix:** main (opus) drove the task directly. Added a handoff note documenting the pattern. The deeper fix: per-agent "Shared project state (read before every task)" blocks now mention this kind of blocker vs. "ask HQ" judgment explicitly, and the structured message's `status: blocked` path requires naming the specific tool and the attempted invocation.

### The system-level fix
Items 1 and 2 drove the biggest design pivot: **structured handoff messages at `.claude/messages/<task-id>.json`** with a required `evidence` block, HQ rejects empty / unresolvable evidence, workers never edit the task spec, protected paths (CLAUDE.md, agent files, project.json, task specs) are HQ-only, and sentry's per-task verify includes a protected-path git-diff audit + an architecture-diagram model-parity check. That stack is what prevents those classes of mistake from happening twice.

---

## 7. How to run it

The crew runs under [Claude Code](https://claude.ai/code) against your own Unity 6 project.

1. **Install** Claude Code and point it at this package's `.claude/` directory as the per-project state. The `CLAUDE.md` here is the per-project system prompt; `.claude/agents/*.md` are the available sub-agents; `.claude/settings.json` installs the hooks.
2. **Copy** `scripts/` and `docs/` into your Unity project (or path them from your project back to this directory — your call).
3. **Open** Claude Code at the project root and hand it a user ask, e.g.:
   > *"Add a wave spawner that fires the next enemy squad at Z=410 after 120 s. Verify it in Play mode."*
   HQ writes `.claude/tasks/<id>-wave-spawner.json`, assigns forge, forge writes `WaveSpawner.cs` + a Play-mode test, sentry runs the test + a protected-path audit, HQ ingests the sentry message and either closes the task or re-routes.
4. **Hooks** fire on every Write / Edit. JSON files get schema-validated, `.cs` files get a fast Roslyn syntax check, and `docs/architecture.md` regenerates whenever an agent file / CLAUDE.md / task spec changes. On failure the hook exits 2 and the agent sees the error block as the tool result.
5. **Resource caps** (CLAUDE.md § Resource limits — dev machine): 24 GB RAM, max 2 parallel headless Blender processes (never 3+), max 4 parallel sub-agents (≤ 2 painters), never run Blender during Unity Play mode.

Outside dependencies: Blender 4, Unity 6000.4.6f1 (bundled Roslyn under `DotNetSdkRoslyn/csc.dll`), Python 3 with `jsonschema` + `Pillow`.

---

## 8. Package manifest

```
assignment-3/
├── README.md                                  ← this file
├── CLAUDE.md                                  ← the living design doc the crew reads every turn
├── .claude/
│   ├── settings.json                          ← Claude Code hooks (log + validate)
│   ├── agents/                                ← 8 agent charters, one per worker + HQ
│   └── hooks/
│       └── validate_write_or_edit.py          ← PostToolUse: JSON schema + C# syntax + architecture regen
├── docs/
│   └── architecture.md                        ← 3 Mermaid diagrams (roles, connections, data flow)
├── scripts/
│   ├── gen_architecture.py                    ← regenerates docs/architecture.md
│   ├── validate_data.py                       ← ledger's schema validator
│   ├── schemas/                               ← 8 JSON Schemas
│   ├── blender_render_v2.py                   ← vehicle render pipeline
│   ├── pixelate_v4.py                         ← pixel-art post-process (locked v4 standard)
│   ├── color_grade.py                         ← camo tint + grading
│   ├── build_orient_blend.py                  ← builds orient_all.blend for hand-correction
│   ├── export_orient_rotations.py             ← dumps hand-corrected Euler to upright_rotations.json
│   ├── render_upright_check.py                ← 17-vehicle contact-sheet renderer (2 Blender parallel)
│   ├── build_pick_sheets.py                   ← 6-angle pick sheet per vehicle
│   └── run_playmode_tests.sh                  ← Unity CLI Play-mode test runner
└── proof-of-run/
    ├── run-report.md                          ← one recent multi-commit run
    ├── commits-by-agent.md                    ← ~25 recent commits grouped by owning agent
    ├── message-01-sentry-protected-path-audit.json
    ├── message-02-cartographer-densification-done.json
    ├── message-03-painter-blocked.json
    ├── before/hud_bug_37pct.png
    └── after/hud_fixed_18pct.png
```

## 9. No secrets

- No API keys, tokens, passwords, or credentials in any file in this package.
- `.claude/settings.local.json` (user-local permission grants) is deliberately **not** included.
- The vehicle 3D models referenced in CLAUDE.md's `# Art direction` are commercial-licensed CC-BY / CC0; the manifest + per-model licence lines live in the main Unity project repo under `art-source/` and `Assets/Art/LICENSES.md`.
