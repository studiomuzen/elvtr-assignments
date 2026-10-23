# Overnight-list continuation — 2026-10-23 afternoon

Follow-up to `.claude/reports/overnight.md`. Four user asks landed in sequence
plus the overnight "deferred to next session" list.

Commits (chronological, nothing pushed):

1. **`5f9e19e`** — HUD fix. BarBackground / LeftPanel / CenterPanel / RightPanel
   had `localScale (3.13, 3.13, 3.13)` and HudBar had `(0.67, 0.67, 0.67)` from
   an earlier HUD pass. Net multiplier 2.1× pushed the 18 % anchor to ~38 %
   visually. Reset to `(1,1,1)` on every HUD transform. Verified at four
   resolutions:
   - 960×1080 half-width: 17.96 %
   - 1920×1080: 18.15 %
   - 1280×720: 18.19 %
   - 3840×2160 (Scale 2x): 18.15 %
   Also added `Assets/Tests/PlayMode/HudHeightTest.cs` with four UnityTest
   methods asserting `bg.rect.height / HudRoot.rect.height ≤ 0.20` AND unchanged
   under camera zoom/pan (pilot-visor rule) AND stable across reference
   resolutions.

2. **`24636b4`** — Deleted medieval-theme leftovers from the pre-Ambush pivot:
   `CaravanMover.cs`, `GameManager.cs`, `HighwaymanPlayer.cs`, `HudController.cs`,
   `HighwaymanGreen.mat`, `WagonBrown.mat`. `SampleScene.unity`, `Ground.mat`,
   `RoadGray.mat` were already clean of medieval content, kept as-is. Compile
   stayed clean post-delete.

3. **`c1aab2d`** — Triaged all 239 task specs. 215 closed, 24 open. Added
   `status: closed` + `closed_reason` fields to every closed spec. Dashboard
   `compute_task_timeline` derives status from events, not JSON — the new
   field is additive.

4. **`b0dd03b`** — Scene densification for Levels 01, 03, 04, 05 per each
   manifest's data of record:
   - L_01: 12 houses under `Village/Houses` (BuildingBody.mat, 6–12 m footprints)
   - L_03: 4 boundary strips at X=±450, Z=±450 (BoundaryGray.mat)
   - L_04: 15 scattered trees (TreeTrunk.mat), river band avoided
   - L_05: Road + Ravine + 19 tree clumps (×3-5 capsules each) + 2 clearings
   Clears the four scope-overflow bullets from the earlier overnight report.
   The first cartographer agent (haiku) wrongly reported this blocked; main
   drove it via execute_code in one pass.

5. Civilian cluster manually closed as superseded by prototype-scope decision
   — tasks 125, 126, 130, 190.

Final open-task count: **20**
- 17 painter sprite redos — user-blocked (orientation picks)
- 1 painter repick-bmp3 — user-blocked
- 1 cartographer: StrategicMap scene (new feature, needs design input)
- 1 sentry: StrategicMap verify (depends on above)
- (and 1 forge MinimapClickToJump — minimap UI is a missing prerequisite)

**Agent-model attribution fix (not a commit).** During the overnight run,
`.claude/agents/forge.md`, `painter.md`, `painter-b.md`, `sentry.md`, and
`playtest.md` had their `model:` field drifted from `sonnet` to
`claude-sonnet-4-6`, which the Agent-tool enum / frontmatter parser doesn't
accept — Claude Code silently inherited from the parent (opus), which is why
the cost tab showed zero Sonnet usage. Reverted all five to the short-name
form `sonnet`. The reverts match HEAD exactly, so there is no diff to commit
— the fix is simply the absence of the drift. Future runs of forge / painter
/ painter-b / sentry / playtest will bill to Sonnet.

Everything above remains **local only**. Nothing pushed.
