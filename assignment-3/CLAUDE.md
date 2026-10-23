# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Design brief, intentionally lean.** The full Game Design Document lives at `docs/GDD.pdf` (relative to the repo root). CLAUDE.md stays short on purpose — it loads every agent turn (GDD §9, §10.4). For anything not in this file, read the GDD.

## Game design — Ambush!

### Setting & premise
**Real-time tactics** game — a single live battle, **not an RTS economy**. Near-future war fought across the real map of Ukraine — present-day trench-and-drone warfare plus near-future kit (exosuits, EW, advanced drones). Grounded tone; **civilian casualties count against the score**. StarCraft-style three-quarter top-down camera, roads diagonal, pixel-art visuals.

**Not an RTS, not a turn-based game.** One **deployment phase** before each battle (position squads, assign specialists, spend supply) then one **real-time battle** that runs until victory, defeat, or retreat. **No turns, no production buildings, no resource gathering mid-battle** — supplies arrive on a fixed schedule between battles, not during. Reinforcements and new units are prepared in the Setup screen, not spawned mid-fight.

### Core loop (one turn = one battle cycle)
1. **Prep at HQ** — refill squads, upgrade units, assign specialists, spend the supply pool.
2. **Deploy & fortify** — position squads/vehicles, sappers build cover.
3. **Fight (real time)** — defender holds the line (or attacker assaults). Player issues orders; units carry them out on their own.
4. **Resolve** — territory tallied, casualties (own + civilian) tallied, veterancy updated.
5. **Resupply** — fixed-schedule, back to step 1.

Between-battle **strategic map** is the real map of Ukraine; the runtime **Front** agent picks the next battle location. Long-range strikes into strategic sites in Russia (ammo depot, airfield, refinery, rail hub, command post) weaken coming enemy waves.

### Command model
General orders only: **forward, hold, back, retreat**, each with a direction. No per-soldier micro. How well units execute depends on veterancy and battlefield intelligence. Fixed-zoom battle view; a map key (e.g. SPACE) opens a fog-of-war overview.

**Camera.** Diamond RTS pose (yaw 45°, tilt ~40°). **Much higher overview** than earlier revisions: at battle start, the entire player line AND all player units are on screen at once, with room for the approaching enemy force visible. Roughly **3–4× the previous view area**. Soldiers read as a few pixels each — intended. **The camera's playable view sits ABOVE the HUD bar** (see "HUD bar" below) — framing is tuned so the playable area occupies the top ~80% of the screen while the HUD bar occupies the bottom 20%. Zoom is fixed in battle view.

**Camera panning (StarCraft-style).**
- **Edge scrolling.** When the mouse cursor is within ~10 pixels of any screen edge, the camera pans in that direction. Diagonals at corners. Smooth, **constant speed**. Works in fullscreen AND in the editor Game View.
- **Arrow keys** also pan the camera (same speed and clamping).
- **Clamp to map bounds (including the buffer zone)** — the camera cannot scroll into empty space past the terrain.
- **The HUD bar does NOT block edge scrolling**: the bottom screen edge still scrolls the camera down even when the mouse is over the HUD.
- **Minimap click** jumps the camera to the clicked world point.
- **Camera height / zoom stays fixed** throughout — only horizontal panning (XZ in world space).

**HUD bar.** A single bar across the FULL WIDTH of the screen, taking up the bottom **20%** (lower fifth). All HUD elements live inside that bar: drone panel (left segment), selected-squad info + per-soldier HP bars (center segment), score + supplies (right segment). No HUD elements float outside the bar during normal play — the squad command box can still float at the selected unit's position above the bar.

**Map edges + buffer zone.** Terrain extends past the playable area on all sides as a visual buffer so the world doesn't end in a hard edge. Off-map spawners (enemy vehicles, reinforcements) drive or walk IN THROUGH THIS BUFFER. Units in the buffer are **not selectable and not commandable**; once a unit crosses the playable boundary it becomes fully commandable. The playable boundary is marked subtly (faint line or slight darkening outside it).

**Map dimensions (prototype).** The **playable battlefield is 900 m × 900 m** (X: −450..+450, Z: −450..+450). Buffer extends **200 m past every edge**, giving a ground plane of **1300 m × 1300 m**. The buffer is covered in ground and tree lines so there is never a visible void past the playable area. Zone layout: **player deployment zone bottom-left corner (X ≈ −450..−350, Z ≈ −450..−350)**, **enemy deployment zone top-right corner (X ≈ +350..+450, Z ≈ +350..+450)**, **both outside the town** and at least **600 m apart** (zone centers ≈1131 m apart). **Town/village** of 15–25 buildings sits roughly between the two zones (centered around origin, spanning ~X: −120..+120, Z: −120..+120), spread out along a diagonal road with real yards and gaps between houses. **Houses are ~10 m wide** (small ~6 m, medium ~12 m) — never wider than a squad's spread. **Camera does NOT show the whole map at battle start** — it stays at the current zoom and starts centered on the player zone; the player scrolls (edge-scroll + arrow keys) to see the rest, clamped to map edges. Unit sizes do NOT scale; only terrain and zone coordinates.

**Command box UI.** When a squad or vehicle is selected, a small floating panel appears beside it with four buttons: **Move Forward**, **Hold Position**, **Move Back**, **Retreat**. Clicking a button issues that order to the selected unit. Only units inside the playable area can be selected.

**Order behavior.**
- **Move Forward** — advance an *incremental* distance randomly chosen within a set range (not fixed, not all the way). On stop, each soldier picks the nearest cover if any is in range; otherwise goes prone.
- **Hold Position** — stay put. Use cover if nearby; otherwise prone.
- **Move Back** — pull back an *incremental* distance (same range mechanic). Same cover/prone rule on stop.
- **Retreat** — full retreat all the way back to base. The squad or vehicle is **out for the rest of the battle** (does not return).
- **Firefight auto-cover** — whenever a unit is under fire, if cover is nearby (next to or inside a building, tree line, trench, etc.), soldiers automatically move into it without a new order.

**Movement speed by terrain + unit type.** Base speed is the "field" rate; terrain and chassis multiply it:
- **Road** — fast (×1.4 for all ground units). Diagonal roads through the map are the fastest route for both sides.
- **Field** — normal (×1.0). Open ground, hedges, light undergrowth.
- **Forest / tree line / rubble / wreckage** — slow (×0.5). Hard to push through; cover but reduced speed.
- **Mud / wet terrain** — **tracked vehicles ×0.9**, **wheeled vehicles ×0.5** (tracks handle it better than wheels). Infantry ×0.7.
- **Trench** — infantry only, ×0.6 (crouched movement).
Specialists carry their squad's base speed; a squad's net speed is the slowest member's speed. Vehicle-type modifier (tracked vs wheeled) is a property on the vehicle class; terrain-type modifier is a property on the tile/surface sampled at the unit's current position.

**Unit cap (per-battle).**
- Around **10–15 commandable ground units per side** — a mix of squads and vehicles. The playable number is intentionally small so each unit matters.
- Total scene population including individual soldiers caps around **50 units total per side** (≈ 10 squads × 5 soldiers + a handful of vehicles). This is the budget tactical AI, pathfinding, and the Commander agent are tuned for.
- Enemy waves respect the cap: a new wave spawns only when prior wave attrition leaves budget. HQ/Commander will not deploy over the cap.

### Setup screen (pre-battle)
Every battle is preceded by a **Setup scene** (`Assets/Scenes/Setup.unity`) that loads before the battle scene. For now the Setup screen has two parts; the strategic map, supplies, and reinforcement screens land here later.

**1. Tech tree panel.** Four branches × four tiers (from the GDD):
- **Drones / Missiles**
- **Infantry**
- **Vehicles**
- **Economy**

Each node shows: name, what it unlocks, and state — **Locked**, **Available**, **Researching**, or **Done**. Tech advances with **time only**: a single research slot, progress advances per battle day. The player picks which available node to research next; a researching node completes after N battle days (per-node cost).

Unlocks must actually apply in battle. Example effects:
- An infantry upgrade makes it available to squads (e.g. unlocking Heavy Weapons tier adds that specialist slot option).
- A drone-tier unlock changes the drone buttons / HUD options (e.g. tier 2 drone adds a second drone-type button).
- A vehicle unlock adds a new vehicle slot to the player roster.
- An economy unlock grows the per-battle supply pool.

**Tech tree data lives in `Assets/Data/techtree.json`** and is owned by ledger. Forge builds the Setup scene UI and the apply-unlocks wiring.

**2. Start Battle button.** Loads the battle scene (`FlatTest.unity` for prototype; replaced by the level-select dropdown below as the 5 fixed levels ship).

**3. Level-select dropdown (test-only).** A dropdown lists the 5 hand-built levels (village edge / town centre / industrial / open fields / wooded hills). Picking one and clicking Start Battle loads that level's `.unity` scene instead of `FlatTest`. The dropdown is for development; the campaign uses the Front runtime agent to pick live.

Icons on the tech tree are **placeholder** until the art pipeline lands.

### Battle sequence
A battle unfolds in a loose script; not every phase fires every time, but when they do, they fire in this order.

1. **Intel phase.** Battle opens with an on-screen intelligence report ("Enemy forces approaching...") and a short calm before the attack. Player squads start in **concealment**.
2. **Enemy scouting.** Enemy drones scout the line. Each player unit has a reveal chance scaled by its cover. The UI clearly shows each unit's state: **REVEALED** vs **CONCEALED** (icon or outline).
3. **Bombardment.** Sometimes artillery / drone bombardment hits **revealed** positions while the player holds in cover.
4. **Vehicle advance.** Enemy vehicles advance. In easier scenarios, vehicles can come first (no scouting, no bombardment). Player can respond with vehicles or drones, and chooses whether vehicles or infantry advance first.
5. **Mechanized infantry.** Enemy infantry rides in transports, stops **just outside the range of the player's ground weapons** (drones can still reach), disembarks, and advances on foot behind their vehicles.

### Vehicles
Full roster lives in GDD §Vehicles. Prototype focuses on the first four slots per side.

**Full prototype roster** (3D models under `art-source/models/`, rendered via the Abrams pipeline — see "Art direction"):

**Player (Ukraine) — 9 slots:**
- **MBTs**: **M1A2 Abrams** · **Leopard 2 A6** · **Challenger 2**
- **IFV**: **M2 Bradley**
- **Transport**: **MRAP** (Ukrainian paint on the SPM-3 hull)
- **Technical**: **Ukrainian pickup + ZU-23-2** (`pickup_zu-23-2`)
- **AA**: **Gepard** (Flakpanzer)
- **Howitzer**: **PzH 2000**
- **EW truck**: **Renault TRM radar truck**

**Enemy (Russia) — 8 slots:**
- **MBTs**: **T-90** · **T-72B3**
- **IFV**: **BMP-3M**
- **Transport**: **BTR-82A** (BTR-3E hull in Russian paint — Azov brigade donor model)
- **Technical**: **Russian DShK technical**
- **AA**: **Tunguska** (ZPRK 2K22)
- **Howitzer**: **2S35 Koalitsiya-SV** (replaces 2S19 Msta)
- **EW truck**: Renault TRM radar truck reused with Russian paint.

(Deferred: cage / standoff armor variants, Leopard 2 vs Challenger 2 stat differentiation.)

**Vehicle rules.**
- Vehicles have their own health and take the same four orders as squads (**forward, hold, back, retreat**) through the **same command box UI**.
- **Hard counters** — rifle squads cannot kill tanks. Only anti-tank weapons, tanks, or drones can.
- Transports and IFVs **carry one squad**; enemy transports drop their infantry **just outside the player's ground-weapon range** (drones can still hit them).
- Anti-air vehicles **shoot down drones** within their range.
- Player chooses whether vehicles or infantry advance first.

**Defensive battle setup (prototype's primary mode).**
- **Enemy vehicles start off-map** and drive in from the far edge of the map, opposite the player's line, in **staggered waves** along roads where possible.
- The player side gets **only a few vehicles**, reflecting the real wartime imbalance: by default **one IFV and one anti-air**, with an **occasional tank**. They start **on the map** in **concealed positions** (tree lines, behind buildings) and follow the **same concealment and reveal rules as squads**. **No off-map player reserves.**

**Starting positions (deployment zones).**
- **Player (Ukraine) deployment zone**: the **bottom-left corner** of the playable area. All player squads and vehicles start **inside this zone**, concealed. Zone is shown at battle start as a **faint blue tinted area** on the ground.
- **Enemy (Russia) deployment zone**: the **top-right corner** of the playable area, with their actual spawn **off-map beyond the top-right edge**. Enemy forces enter the playable area along the **roads** from that corner. Zone is shown as a **faint red tinted area**.
- **The middle of the map is empty at battle start.** No starting units in the center — the full battlefield (fields, village edge, tree lines, roads) sits between the two zones.
- Zone tints fade out shortly after the first contact.

### Drone HUD
Slim bar at the **bottom** of the screen, out of the way. Shows which squads can launch drones. Click one or several drone buttons to **arm** them. Move the cursor onto the battlefield to see a wide highlighted **target area** locked to the cursor (an approximate impact zone). Click to launch — drones fly there and strike within that area. **Multiple armed drones launch together.**

### Tactical AI (behavior trees)
The player's order (forward, hold, back, retreat) sets the **goal**. Within that goal, each unit fights on its own via a behavior tree. The AI must **never abandon the order** — hold stays near its position, forward keeps advancing between cover, retreat overrides everything.

- **Line of sight.** Units track which enemies can see them. When exposed to a threat they can't beat (infantry facing a tank, a vehicle facing an anti-tank team), they **break LOS** — move behind a building, tree line, or terrain, or pull back a short distance — then resume the order.
- **Cover (infantry).** Prefer firing from cover. Peek to shoot, duck between bursts. Under heavy fire, stay down.
- **Cover (vehicles).** Fire from concealed or partially covered positions. Reverse out of sight after firing or when targeted. Avoid open ground when anti-tank threats are known.
- **Target choice.** Engage what you can actually damage — rifles shoot infantry; AT weapons and tanks target vehicles; AA targets drones.
- **Veterancy scales it.** Green units react slower and pick worse cover; veterans react faster and choose better positions.

### Maps — fixed hand-built roster (NO random/agentic generation)

The game ships **5 finite, hand-built levels**. No runtime map generation, no per-load randomness, no seed-driven variation. Each level is drawn ONCE from real Ukrainian OpenStreetMap data by the cartographer, saved as a scene + a JSON manifest, and shipped as-is.

**The 5 levels:**

| # | Type | Design |
|---|---|---|
| 1 | Urban — village edge | Houses at the village boundary + open approach fields. Dirt road through the village. Picks up the earlier "village outskirts" work. |
| 2 | Urban — small town centre | Grid streets, blocks of houses + two or three larger buildings. A square or market space the attacker must cross. |
| 3 | Urban — industrial | Factory halls, rail yard with sidings, concrete walls + stacked materials for cover. |
| 4 | Terrain — open fields | Hedgerowed fields, a few tree lines, **a river crossing** (one bridge, no fords for vehicles). |
| 5 | Terrain — wooded hills | Low ridges + a steep ravine, **one road** that threads through the woods, bottlenecked. |

**Per-level requirements (all 5):**
- Playable area **≥ 900 m × 900 m**; terrain extends past the playable edge in every direction so there is no visible void (see § Map dimensions).
- **Player start and enemy start at opposite sides** of the playable area, zone centres **≥ 600 m apart**.
- Each level ships as **its own `.unity` scene** (`Assets/Scenes/Level_<id>_<slug>.unity`) PLUS a **JSON manifest** at `Assets/Data/levels/<id>.json` listing: name, real-world location, OSM source (way/relation ID + URL), size, start-zone bounds, cover-point coordinates.
- The OSM source line is **required** — refuse to merge a level without it.

**Front (runtime agent) no longer generates maps.** Its only level-selection responsibility is **picking which of the 5 ships** for the next battle based on current-front-line heuristics. The map itself is already on disk.

**Setup screen gets a level-select dropdown** (test-only; the campaign uses Front for live selection). See § Setup screen.

### Art direction
**Top-down pixel art in the spirit of Hyperlight Drifter** — clean shapes, strong colors, readable at small size — but **real-world and military**, not sci-fi. One consistent palette and pixel density across every asset.

**Vehicle sprite pixelation (APPROVED v4 standard).**
- Longest body side per vehicle = `round(real_length_m * 64 / 9.83)` pixels — MBTs 64px, smaller vehicles scale down.
- Lanczos area downscale from the raw Blender render, binary alpha threshold at 100, MedianFilter(3), posterize to 32 levels/channel, Contrast ×1.15, Sharpen ×1.30, **no outline**, 40%-opacity soft drop shadow under the body.
- Unity import: Pixels Per Unit set so 1 art-pixel = 2×2 screen pixels, Filter Mode = Point, Compression = None.
- Pipeline: `scripts/blender_render_v2.py` → `scripts/pixelate_v4.py`.

**Vehicle pipeline.** Find licensed 3D models (**commercial-use or CC-BY**) of the real vehicles on each side.
- Western (Ukraine): M1A2 Abrams, Leopard 2, M2 Bradley, MRAP, Gepard.
- Eastern (Russia): T-72, T-90, BMP-3, BTR-82A, Tunguska.

Render each model from **our exact battle-camera angle** (yaw 45°, pitch ~40°), then pixelate to the one consistent palette and pixel density. Size every vehicle to **real scale against the soldier sprite** (an Abrams must look like an Abrams next to a man). Log every model's source and license in `Assets/Art/LICENSES.md`.

### Organic squad spacing
Soldier-level spacing rules; the squad never bunches, never forms a grid or line.

- **In the open:** soldiers keep a **minimum spacing** from each other. No bunching, no lines, no grids. Positions are irregular and each soldier adjusts to where his squadmates are.
- **Cover available:** soldiers share cover and may stand close together **only when they're in the same cover**.
- **Lots of cover:** the squad **spreads across several cover spots** instead of piling into one.
- **Few cover spots:** some soldiers group tight in the cover, the rest **go prone in the open at spacing**.
- **Re-evaluate constantly** as they move; **stagger timing** so they don't all move at once.
- **Squad cohesion still applies** — no soldier drifts far from the squad center (per "Infantry independent movement" below).

### Infantry independent movement
Each soldier moves independently, like he has his own mind. **No marching in formation, no moving in sync.**

- Each soldier picks his own path and pace: some sprint ahead to the next cover, some hang back, some stop briefly. They move in **short rushes** rather than at a steady speed.
- **Squad cohesion** — no soldier drifts more than a set distance from the squad's center; stragglers catch up.
- **Spacing** — looks like a real squad in combat seen from above: spread out, never bunched, irregular spacing, no straight lines or grid.
- **Under fire** — soldiers move **one or two at a time** while the others cover (bounding overwatch), instead of all at once.
- **Cover selection** — each soldier picks his own cover spot near the squad's position, not the same spot.

### Squads
5-soldier squads with **per-soldier health bars**. All start as **Rifleman** and upgrade to one of: **Exosuit trooper**, **Heavy weapons**, **Drone operator**, **Engineer** (max one specialist per squad). Reinforcing keeps veterancy; a wiped squad loses it.

### Vehicles
Three classes, eight slots. Heavy armor (tanks, howitzers), light armor (IFV, anti-air), light/transport (MRAP, EW truck, technical). Each side fields its own real-world models — player: Leopard 2, M1A2, PzH 2000, M2 Bradley, Gepard, MRAP, EW truck, armed pickup; enemy: T-90, T-72, 2S19, BMP-3, Tunguska, BTR-82A, EW truck, armed pickup. Cage / standoff armor upgradable.

### Drones (core pillar)
Scarce by design. On-map **drone teams** launch short-range (FPV kamikaze, scout, loitering munition) and **ground drones** (MG / recovery / anti-tank). Off-map **long-range strikes** hit strategic sites. **All six real-world counters** modeled: EW jamming, shootdown, netting / cage armor, concealment, interceptor drones, striking operators (on-map teams only).

### Hard counters
**Rifle squads cannot effectively damage tanks** — armor is answered with heavy weapons or drones. Picking the right tool for the threat is a core skill. Sentry treats violations of hard-counter rules as design bugs.

### Scoring
Two axes, kept separate from supplies:
- **Territory** gained or lost.
- **Casualties** — own soldiers + **civilian casualties you cause** (artillery, bombing, drone strikes all count).

Supplies (finite pool funding units, refills, drones, munitions) are what you fight *with*; score is how you're *judged*.

### Attack mode
Same systems, roles reversed: scouting → bombardment → main force. Civilian casualties still count.

## Prototype scope — build this first

Prove the core command loop. Everything else deferred.

**In scope:** one small defensive-line map (tree line + trench) · 2–3 five-soldier squads with per-soldier HP · one enemy assault wave · forward / hold / back / retreat commands with direction · one limited-count drone strike · basic scoring (territory + casualties).

**Out of scope:** vehicles · veterancy · specialist upgrades · attack mode · the full drone-counter set · art beyond placeholder shapes · the runtime agents (Front and Commander — rule-based fallbacks instead).

**Success criterion:** can the player hold or lose the line through nothing but command-and-execute, with casualties and territory telling an honest story at the end? If yes, build vehicles / drones / counters / veterancy on top.

---

## Art review goes to the dashboard, never to Preview

**Never run `open <png>` on a review image.** The dashboard already serves the Art Review tab from the sprite sheets on disk. For every art pass:

1. Save shipped vehicle sprites to **`ELVATR GAME 1/Assets/Art/Vehicles/<Name>_sheet.png`** (the dashboard watches this folder — files starting with `_` or containing `preview` are hidden from the Art Review tab, so keep the shipped filename clean).
2. Do NOT produce ad-hoc `_review_*.png` composites intended for the user to open locally. The dashboard renders each sheet as a 4×4 frame grid at 2× NN automatically.
3. After writing the sheets, the only thing to say to the user is **"new art ready in the dashboard."** No "I opened the file", no `open` command, no Preview.
4. Intermediate pipeline artifacts (`art-source/pixelated_raw/`, `art-source/renders_v2/`, etc.) are still fine — those don't display in Preview.

## Design-change log (CLAUDE.md ↔ GDD)

The GDD at `docs/GDD.pdf` is **frozen** — the shipped assignment artifact, never edited after submission. CLAUDE.md is the **living** design doc. Any divergence between them is tracked in `docs/gdd-changes.md`.

**Rule.** Every design or agent change goes into **CLAUDE.md first**, then gets a one-line entry in `docs/gdd-changes.md` under the matching GDD section (`§1`, `§4.4`, `§10.2`, etc). This includes:

- Design changes (civilian rules, setup flow, HUD layout, map specs, vehicle roster swaps, art pipeline, deployment zones, order behavior, new UI widgets).
- Agent changes (model tier, tool set, charter boundaries, new agents, pipeline additions, QA tier changes).

If a change touches CLAUDE.md but no `gdd-changes.md` line lands in the same commit, treat the commit as incomplete.

## Tiered QA (token budget)

Testing is tiered so most task-level verification runs headless with no screenshots and no user-visible noise:

1. **Per-task — Play-mode tests via Unity Test Framework.** `com.unity.test-framework` is in the project manifest. Test code lives under `Assets/Tests/PlayMode/` behind an `Ambush.PlayModeTests` asmdef. Forge is responsible for writing a Play-mode test for every new feature it ships (camera pan works, selection fires, orders move squads, units take damage, battle ends on breakthrough). Sentry runs them from the CLI after every task via `scripts/run_playmode_tests.sh`. Output = pass/fail text + JUnit XML in `.claude/reports/last-playmode-tests.xml`. **No screenshots at this tier.**
2. **Per-feature — one screenshot check.** At the end of a self-contained feature (not every task), sentry takes exactly ONE 16:9 Play-mode screenshot at Scale 1x and verifies the visible result matches the spec. The feature only "ships" if the screenshot passes.
3. **Per-milestone — playtest agent.** At the end of each milestone in `.claude/plans/milestones.md`, the dedicated `playtest` agent plays a full battle in Play mode, writes a bug report with key screenshots to `.claude/reports/milestone-<id>-playtest.md`, and gives a PASS / PARTIAL / FAIL verdict against the milestone's acceptance criteria.

If a per-task Play-mode test fails twice on sonnet, HQ may retry once on opus; if it still fails, log the milestone+task in `.claude/reports/blocked.md` and move on — don't halt the whole run.

## Context budget — what agents read at task start

The crew runs with a **fixed two-file reading list** at the start of every task. No agent silently loads old reports, archived task specs, handoffs, or event logs.

**Required reads (every agent, every task):**
1. **`.claude/state/project.json`** — the structured snapshot of shipped assets, approvals, blockers, decisions, open task IDs. HQ-only write.
2. **`.claude/state/decisions.md`** — the human-readable rolling summary: a compressed "what you need to know on day one" section at the top, plus the most recent per-run entries below. Kept under 2 pages. HQ writes a new entry at the end of every run and compresses older entries into the top summary.

That's it. The task spec at `.claude/tasks/<id>-<slug>.json` is the third input (the *what*), but the two files above are the *context* every agent starts from.

**Not read by default:**
- `.claude/archive/tasks/*.json` — closed / superseded task specs. Lookup-on-demand only; HQ names a specific file if a worker needs the history.
- `.claude/reports/sentry-*.md`, `.claude/reports/milestone-*-playtest.md` — written by sentry / playtest for the record, not loaded into any agent's working context unless HQ cites a specific report in the next task spec's `notes` field.
- `.claude/handoffs/*.md`, `.claude/messages/*.json` — HQ ingests these between tasks; workers don't read them.
- `.claude/logs/events.jsonl` — dashboard telemetry only.
- `art-source/*.log` — Blender run logs; the painter / painter-b reads only its own current log, not sibling or historic logs.

If a worker finds they need something outside the required reads to complete a task, they emit a `status: blocked` structured message naming the artifact they need. HQ decides whether to fold the fact into `project.json`, cite the file in a reworked task spec's `notes`, or hand it back as "do it with what you have."

## Shared project state

**File:** `.claude/state/project.json` — the single source of truth for cross-task state (shipped assets, approvals, blocked items, design decisions, open task IDs).

**Protocol:**
- **Every agent reads `project.json` before starting a task** (first of the two required reads above). The task spec names *what* to do; `project.json` names *what already exists / what's blocked / what's been decided* so the agent doesn't duplicate shipped work or trip over an open block.
- **Only HQ writes to `project.json`.** Workers (forge, ledger, painter, painter-b, cartographer, sentry, playtest) may **never** modify this file. HQ updates it between tasks after ingesting the previous worker's structured message.
- **Schema** (`schema_version: 1`): top-level keys `updated_at`, `updated_by: "hq"`, `schema_version`, `assets`, `approvals`, `blocked`, `decisions`, `open_tasks`. Mutations always bump `updated_at` and keep `updated_by` = `"hq"`.
- **Breakage policy:** `python -m json.tool .claude/state/project.json` must exit 0 at all times. HQ validates before saving; if HQ hits a partial write, it must restore from the previous commit.

The dashboard reads `project.json` for the pipeline overview panel — the shipped-asset and open-blocker tiles are driven by this file.

## Rolling decisions log — HQ writes after every run

**File:** `.claude/state/decisions.md` — the human-readable half of the context budget.

**Shape:**
- **Rolling summary** at the top (≤ 20 bullets). Compressed every run: anything older than the most-recent ~5 entries folds into one-liners here. This is the "if a new agent walked in cold, what do they need to know" paragraph.
- **Open blockers snapshot** right under the summary (mirrors `project.json.blocked` with short prose).
- **Chronological entries** below (newest first). Each entry: date header + three subsections — *What changed.* *Why.* *Blocked.* Keep each entry under ~150 words.
- **Hard length cap: 2 pages** (~1500 words / ~80 lines rendered). If `decisions.md` exceeds the cap, HQ's next write MUST roll older entries up into the top summary before adding the new one.

**Write protocol (HQ-only):**
- End of every run (success, partial, or hit-a-wall): HQ appends one new entry at the top of the chronological block.
- If the file length exceeds the cap, roll older entries into the top summary, delete those sections, re-save.
- Validate: `wc -l .claude/state/decisions.md` ≤ ~80 after the write.

**Archive of closed task specs** lives at `.claude/archive/tasks/*.json`. Agents do NOT read this folder by default — the summary in `decisions.md` + the task-id references in `project.json.decisions[]` are the condensed history. If HQ needs a specific archived spec for a redo or reference, HQ names the exact path in the next task spec's `notes` field.

## Structured handoff messages

**File per worker-task:** `.claude/messages/<task-id>.json` — the structured deliverable that proves a worker finished. One file per (task_id, agent). Replaces the free-form handoff markdown as the authoritative "done" signal (though the markdown handoff under `.claude/handoffs/` stays as a human-readable narrative companion).

**Required schema (strict — HQ parses this):**

```json
{
  "task_id": "<id or batch-id>",
  "agent": "forge | ledger | painter | painter-b | cartographer | sentry | playtest",
  "status": "done | failed | blocked",
  "outputs": ["path/to/file1", "path/to/file2"],
  "evidence": [
    "path/to/screenshot.png",
    "path/to/test-result.xml",
    "test_result:play-mode-pass",
    "sentry_report:.claude/reports/sentry-<id>.md"
  ],
  "notes": "≤ 2 lines on anything surprising, deferred, or escalation-worthy",
  "model": "haiku | sonnet | opus",
  "timestamp": "<ISO 8601>"
}
```

**Rules:**
- `evidence` is **required** and **non-empty**. HQ **rejects** any message where `evidence` is missing, empty, or whose entries don't resolve to real files or recognized `test_result:*` / `sentry_report:*` tokens. A rejected message is sent back to the originating agent as an inbox entry; it does NOT advance the pipeline.
- `outputs` lists shipped artifact paths (code files, scene files, sprite sheets, data JSON, etc).
- `evidence` lists the proof those outputs work:
  - **forge** → the PlayMode JUnit XML path + the test method name that passed.
  - **painter / painter-b** → the sheet path + the dashboard review tile path.
  - **ledger** → the validator exit output or a `test_result:validate_data-pass` token.
  - **cartographer** → the manifest path + a sentry screenshot path (or a signed-off handoff).
  - **sentry** → the report path with `Verdict: PASS | FAIL`.
  - **playtest** → the milestone report + its ≥ 4 screenshots.
- `status = "blocked"` requires `notes` to name what the block is and who owns it (user / design / another agent). HQ moves the item into `project.json.blocked[]`.
- `status = "failed"` requires `notes` to name the specific `done_means` item that fell over and the error signal (console line, test assertion, sentry FAIL verdict).

**Shared handoff markdown (companion, still required):** every agent also writes a short prose note to `.claude/handoffs/<task-id>-<agent>.md` for the dashboard's live-pipeline view (format below). The structured message is the enforceable contract; the markdown is the human narrative.

```markdown
---
task_id: <id or batch-id>
agent: <hq | forge | ledger | painter | painter-b | cartographer | sentry | playtest>
status: done | blocked | failed
model: <haiku | sonnet | opus>
timestamp: <ISO 8601>
---

**Artifacts:**
- <path 1>
- <path 2>

**Checks:**
- [x] <done_means item 1 — pass/fail>
- [x] <done_means item 2 — pass/fail>

**Next:** <who should pick this up and what to do>

**Notes:** <≤2 lines on anything surprising or deferred>
```

Missing handoff markdown means the dashboard thinks the agent is still working; missing structured message means HQ treats the task as not-yet-delivered.

## Agent output contracts

Every agent file in `.claude/agents/` ends with an **Output contract** section that spells out what the agent must return, the exact file path(s) it must land at, and how its success is checked. The dashboard, hq, and sentry all parse these artifacts, so the shapes are strict.

Per-agent contracts (read these before assigning or reviewing work):
- **hq** → task-spec JSON at `.claude/tasks/<id>-<slug>.json` with `goal`, `files`, `assigned_agent`, `done_means`, `test_cmd`, `acceptance_test`. HQ also owns writes to `.claude/state/project.json`, writes to `.claude/state/decisions.md` at the end of every run, moves closed task specs via `git mv` to `.claude/archive/tasks/`, and ingests every worker's `.claude/messages/<task-id>.json`.
- **forge** → C# compiling with zero errors + a passing Play-mode test under `Assets/Tests/PlayMode/`; verified by `scripts/run_playmode_tests.sh`. Structured message evidence = JUnit XML + test method name.
- **ledger** → JSON under `Assets/Data/` that passes `python scripts/validate_data.py`. No shipped file may trigger `WARNING skipped`; missing schemas must be added or escalated. Evidence = validator exit output.
- **painter** → sprite sheet at the locked v4 size + grade under `Assets/Art/Vehicles/<Name>_sheet.png`, plus regenerated `_review_sheet.png` and a `LICENSES.md` entry. Evidence = sheet path + dashboard review tile path.
- **cartographer** → `Assets/Data/levels/<id>.json` with `source`, `grid`, `seed`, `defensive_line`, `roads`, `spawn_zones` + a materialized `Level_<id>` scene parent saved to disk. Evidence = manifest path + Unity console clean + a sentry screenshot.
- **sentry** → fixed-format report at `.claude/reports/sentry-<task-id>.md`: task id, each `done_means` item as `[PASS/FAIL]`, screenshot paths, `Verdict: PASS | FAIL`. Evidence = report path with its own `Verdict:` line.
- **playtest** → milestone report at `.claude/reports/milestone-<id>-playtest.md` with ≥4 screenshots and `Verdict: PASS | PARTIAL | FAIL`. Evidence = report path + the 4 screenshot paths.

## Pre-change snapshot — forge / cartographer / painter

Before editing an existing scene, prefab, material, or JSON config, **forge / cartographer / painter MUST read the current state and include a snapshot of it in the `notes` field of their `.claude/messages/<task-id>.json` handoff**. Three guarantees come out of this:

1. **Reversibility.** If a change breaks the build, the "before" state in `notes` is the fastest path to a correct revert — no git-blame archaeology.
2. **Design-reality parity.** The snapshot catches the case where the task spec was written against a stale understanding of the scene / config. If HQ reads the snapshot and realizes the task spec is wrong, it rewrites the spec; the agent does NOT edit the task spec itself.
3. **Repeatability.** When the user asks "what did the HudBar look like before the fix?" the snapshot in `notes` answers it in one lookup.

**Minimum snapshot content, per asset class:**
- **Scene edit (cartographer, forge for UI scripts that touch a scene)** — root-GameObject names, parent/child hierarchy of the subtree being changed, every MonoBehaviour on the touched GameObjects + their serialized field values, every reference the subtree holds into other GameObjects (component targets, UI canvas refs). Pull via `manage_gameobject get` + `manage_components get` through UnityMCP.
- **Prefab edit (forge, cartographer)** — same as scene but for the prefab's instance root. Note any PrefabOverrides.
- **Material edit (painter, cartographer)** — shader name, every exposed property + current value, Material.renderQueue.
- **JSON config edit (ledger, forge, cartographer for level manifests)** — the full file contents OR a tight diff-style diff against HEAD if the file is large.
- **C# constant edit (forge)** — the current value of the constant/field + a 2-line context from the enclosing method.

**Never edit the task spec.** The task spec at `.claude/tasks/<id>-<slug>.json` is HQ-owned. If the task spec is incompatible with the snapshot the agent just took, that's a signal to HQ — emit a `status: blocked` structured message naming the spec file, the field that's wrong, and quoting the snapshot evidence. HQ reworks the spec. The agent does NOT silently reinterpret, rewrite, or amend the spec.

**No change without the snapshot.** If a worker ships a `status: done` message that changed a scene / prefab / material / JSON file but does NOT include a snapshot block in `notes`, HQ rejects the message and sends it back for a redo. Sentry's protected-path audit treats this as a FAIL alongside the git-touched-CLAUDE.md FAIL.

## Architecture docs (auto-generated)

`docs/architecture.md` holds three Mermaid diagrams generated from the live crew state by `scripts/gen_architecture.py`:

- **(a) Agent hierarchy** — Noah gates → HQ → every worker → Sentry → HQ, with each agent's model badge pulled from its `.claude/agents/*.md` frontmatter.
- **(b) Shared memory map** — read / write edges for `project.json`, `decisions.md`, `.claude/messages/`, `.claude/inbox/`, `.claude/tasks/`, `CLAUDE.md`, and `.claude/archive/tasks/`.
- **(c) Open-task dependency graph** — live tasks from `.claude/tasks/` plus blocker→task edges inferred from `project.json.blocked[*].unblocks_tasks`.

**Never edit `docs/architecture.md` by hand.** The PostToolUse hook (`.claude/hooks/validate_write_or_edit.py`) re-runs the generator after any `Write` / `Edit` that touches `CLAUDE.md`, `.claude/agents/*.md`, `.claude/tasks/*.json`, or `.claude/state/project.json`. If a diagram looks wrong, fix the source (agent frontmatter, task JSON, or `project.json`) and the hook regenerates the doc.

Sentry's per-task verify includes a **model-parity check**: parse `model:` from every agent's frontmatter + grep `docs/architecture.md` for the matching node, FAIL if any agent's diagram model doesn't match its file. Documented in `.claude/agents/sentry.md`.

## Validation bridge — PostToolUse hook

A Claude Code `PostToolUse` hook validates every `Write` / `Edit` that touches a schema-bound file. Script: `.claude/hooks/validate_write_or_edit.py`. Wired via `matcher: "Write|Edit"` in `.claude/settings.json`.

**What it checks:**

- **JSON files** under `ELVATR GAME 1/Assets/Data/`, `.claude/state/`, or `.claude/messages/` → `scripts/validate_data.py` runs the full JSON-Schema check against `scripts/schemas/*.schema.json`. Every file in those three roots must have a schema; the schema lookup table lives in `scripts/validate_data.py :: get_schema_for_file`.
- **C# files** under `ELVATR GAME 1/Assets/` → fast standalone syntax check via Unity's bundled Roslyn (`DotNetSdkRoslyn/csc.dll` run through `NetCoreRuntime/dotnet`). The hook deliberately compiles each file in isolation (no `-r:UnityEngine.dll`, no `-r:Ambush.*`, no mscorlib) and tolerates reference / predefined-type errors — those are false positives in isolation. It catches real syntax breakage: `CS1xxx` (bad expressions, missing braces, invalid tokens) and anything structural. The deep type-level compile is still enforced by sentry's per-task Play-mode run.

**On failure:** the hook writes the error block to stderr and exits with **code 2**. Claude Code treats exit 2 as "tool failed," so the originating agent sees the error block as the tool result and can fix + re-save. The hook re-runs on the next `Write` / `Edit`.

**Logging:** every pass / fail / skip appends one JSON line to `.claude/logs/validation.jsonl`:
```json
{"ts":"<ISO>","ts_epoch":<float>,"event":"json_validate|cs_syntax_check",
 "tool":"Write|Edit","file":"<repo-rel path>","result":"pass|fail|skipped",
 "errors":[...], "fix":""}
```

Count caught errors with:
```bash
jq -s 'group_by(.result) | map({(.[0].result): length}) | add' \
  .claude/logs/validation.jsonl
```

**Schema coverage (`scripts/schemas/`):**

| File pattern | Schema |
|---|---|
| `Assets/Data/Squads/*.json` | `squad.schema.json` |
| `Assets/Data/techtree.json` | `techtree.schema.json` |
| `Assets/Data/squad_veterancy.json` | `squad_veterancy.schema.json` |
| `Assets/Data/terrain_speed.json` | `terrain_speed.schema.json` |
| `Assets/Data/Maps/*.json` | `map_manifest.schema.json` |
| `Assets/Data/levels/*.json` | `level.schema.json` |
| `.claude/state/project.json` | `project_state.schema.json` |
| `.claude/messages/*.json` | `message.schema.json` |

**No shipped data file may trigger `WARNING skipped`** — ledger's rule from day one. If a new JSON type lands, the matching schema MUST land in the same commit; `scripts/validate_data.py` must learn its path mapping.

**Ledger's responsibility:** add + maintain schemas. When a worker proposes a new JSON format (via a `status: blocked` message), ledger builds the schema, updates `validate_data.py`'s path mapping, and verifies every existing file of that type validates. The schema set is part of the design surface, not an afterthought.

## Live JSON hot reload (Play mode)

**File:** `Assets/Scripts/Game/DataHotReload.cs` — a singleton MonoBehaviour that polls registered `Assets/Data/*.json` files for mtime changes and fires per-file reload callbacks. Registered systems get `Load()`-called while Play mode is running, so values can be tuned live without restarting the scene.

**Registered loaders (as of 2026-10-23):**
- `TerrainSpeed` → `Assets/Data/terrain_speed.json` (road / field / forest / mud / trench multipliers per chassis).

**Pattern for a new loader:**
```csharp
private void Awake()
{
    Load();
    if (dataJson == null)  // only when loading from disk, not a baked TextAsset
    {
        var path = Path.Combine(Application.dataPath, "Data", "my_config.json");
        DataHotReload.Watch(path, Load);
    }
}

public void Load() { /* re-read + re-parse; idempotent */ }
```

The `Load()` method must be **public** (so the test harness + hot-reload callback can both call it), **idempotent** (clear state before populating — a hot reload must leave the system in the same shape as a fresh `Load()`), and **tolerant of a bad JSON** (log + keep the old values; don't throw).

**Enforcement:** `Assets/Tests/PlayMode/DataHotReloadTest.cs` writes a sentinel multiplier into `terrain_speed.json` during Play mode, forces a `DataHotReload.PollOnce()`, and asserts `TerrainSpeed.GetMultiplier("road", Chassis.Tracked)` matches the sentinel. Then restores the original. If a future loader joins the pattern, add a sibling `[UnityTest]` method in the same file.

**Scope caveat:** Hot reload is Editor + Mac-standalone only (anywhere `Application.dataPath` resolves to a readable Assets folder on disk). Shipping builds bake the TextAsset into the binary; the watcher is a no-op there, which is fine — Play-mode / in-editor tuning is the point.

## Agent protection boundaries

Workers may **never** edit:
- **`CLAUDE.md`** (the authoritative design doc).
- **`.claude/agents/*.md`** (any agent charter, including their own).
- **`.claude/state/project.json`** (HQ-only write).
- **`.claude/tasks/<id>-<slug>.json`** (any task spec — HQ-owned; workers propose changes via a `status: blocked` message naming the spec file + field).

If a worker believes a design rule, charter boundary, or project-state entry needs to change, they do **not** make the edit. Instead they emit a structured message with `status = "blocked"` and `notes` that:
1. Name the specific file + line/section that should change.
2. State the reason (incompatible with the task spec, inconsistent with another decision, obvious bug, etc).
3. Suggest the smallest edit that would unblock the task.

HQ reads the blocked message, decides whether to make the design change (and update CLAUDE.md + `project.json.decisions`), rewrite the task spec, or hand it back to the worker as "do it the current way." Only HQ touches CLAUDE.md and agent files. This keeps the design doc coherent and prevents workers from locally re-interpreting rules.

Enforcement:
- Sentry's static-verify pass fails any run where a non-HQ agent has git-touched `CLAUDE.md`, `.claude/agents/*.md`, or `.claude/state/project.json` within the task window.
- HQ, when ingesting a message, cross-checks the agent's reported `outputs` against this prohibition and rejects anything that lists one of those paths.

## Inbox messages (user ↔ agent)

The local dashboard at `http://localhost:8787` writes operator messages to `.claude/inbox/<agent>.md`. **HQ checks every inbox file between tasks** (before writing the next task-spec JSON) and delivers any pending messages:
- If an inbox message changes scope, hq folds it into the next task spec's `notes` field and clears the inbox entry by appending a `[delivered <ISO 8601>]` line beneath it.
- If an inbox message is directed at a specific agent (e.g. painter: "redo T-90 with darker camo"), hq writes a dedicated task spec for that agent and marks the inbox entry delivered.
- Never silently delete inbox messages — always append the delivered line so the dashboard shows an audit trail.

Painter has one extra inbox hook: approve/redo clicks on the art review tab append structured entries to `.claude/inbox/painter.md`, and every click is also logged append-only to `ELVATR GAME 1/Assets/Art/approvals.md`.

## Resource limits (dev machine)

The dev machine has **24 GB RAM**. Respect it:
- **Headless Blender (`blender -b`) may run up to 2 in parallel.** Enough RAM to pipeline a vehicle render + an infantry render at the same time (painter + painter-b), but **never 3 or more** — a third headless process will swap-thrash. Serialize batches beyond 2 through a shell loop.
- **Never run Blender while Unity is in Play mode.** Unity + Blender together exhaust memory. The 2-parallel rule above applies only when Unity is NOT in Play; drop to 0 Blender during Play.
- **Cap parallel sub-agents at 4** during long autonomous runs — of which **at most 2 may be painters** (one painter on vehicles + one painter-b on infantry; everything else — forge, ledger, cartographer, sentry — is non-painter headroom). Default steady-state cap stays at 3; the 4-with-2-painters cap is for class-run / overnight passes when the painter pipelines are hot.
- **Opus escalation on sonnet failures.** If a task fails twice on `sonnet` (forge / painter / painter-b / sentry), hq may retry it ONCE on `opus` before stopping for user review. If the opus retry also fails, stop and report — do not loop further.

## Repo layout

Two independent trees at the repo root:
- **`ELVATR GAME 1/`** — the Unity project (Unity **6000.4.6f1**, URP). Folder name has a space; quote it in shell commands.
- **`mcp-server-src/`** — vendored checkout of [CoplayDev/unity-mcp](https://github.com/CoplayDev/unity-mcp), local-dev reference only. Not a build dependency; UPM pulls the package via git URL. That subtree has its own `CLAUDE.md`; read it before changing anything under it.

Repo-root `.venv/` is for running the Python MCP server from `mcp-server-src/Server/` locally.

## Unity project essentials

- Entry scene: `ELVATR GAME 1/Assets/Scenes/SampleScene.unity`
- **Scripts**: `ELVATR GAME 1/Assets/Scripts/` · **Data**: `ELVATR GAME 1/Assets/Data/` · **Art**: `ELVATR GAME 1/Assets/Art/` (with `LICENSES.md` manifest)
- URP, **Input System 1.19** (new system — not legacy `Input.*`), 2D tooling, Timeline, Visual Scripting
- `com.coplaydev.unity-mcp` installed; Editor exposes MCP tools over a bridge

## Preferred workflow: drive the Editor via MCP

When the Editor is open and connected, prefer MCP tool calls over editing scene/asset YAML by hand (direct YAML edits risk GUID breakage).

| Task | Tool |
|---|---|
| Create/modify/delete GameObjects, set transforms | `mcp__UnityMCP__manage_gameobject` |
| Add/remove components, set component properties | `mcp__UnityMCP__manage_components` |
| Create material assets, assign to renderers | `mcp__UnityMCP__manage_material` |
| Create folders / move / rename assets | `mcp__UnityMCP__manage_asset` |
| Create a new C# script asset | `mcp__UnityMCP__create_script` (then `refresh_unity` with `compile: request` before adding the component) |
| Find GameObjects by name/tag/component | `mcp__UnityMCP__find_gameobjects` |
| Reposition cameras, screenshots | `mcp__UnityMCP__manage_camera` |

The `unity-mcp-skill` skill has the full tool catalog and workflow patterns.

Caveats observed in this project:
- `manage_material create` fails if the target folder doesn't exist — create folders first with `manage_asset create_folder`.
- After `create_script`, call `refresh_unity` with `compile: request` and `wait_for_ready: true` before `manage_components add` on the new type.
- Primitive color via `manage_material set_renderer_color` uses a MaterialPropertyBlock — fine for prototypes but doesn't persist as an asset. Use `create` + `assign_material_to_renderer` for a reusable `.mat`.
- **Script name collisions.** Common names like `PlayerController` collide with bundled Visual Scripting types (`VariableExamples+PlayerController`) and fail `manage_components add` with "ambiguous type". Prefix game classes (e.g. `AmbushPlayerController`, `SquadController`).

## Running / testing

- **Playmode / EditMode tests**: open the project in Unity → `Window → General → Test Runner`. `com.unity.test-framework` is installed; no test assembly yet under `Assets/`.
- **Building**: Unity's `File → Build Profiles` (no CLI build script in this repo).
- `mcp-server-src/` has its own Python test suite (`uv run pytest`) — only relevant if you're changing the vendored MCP server.

## Art direction

All Ambush! visuals are **pixel art at a fixed three-quarter top-down camera angle** (45° yaw, ~40° tilt). This ensures every unit, vehicle, and prop reads correctly from a single viewpoint.

### Vehicle rendering pipeline

The painter agent produces vehicle sprite sheets via the `Blender → pixelate` production pipeline:

1. **`scripts/blender_render_glb.py`** — Imports a GLB model into a template Blender scene, scales it to match a reference footprint (the Abrams), and renders 16 rotation frames at the fixed camera angle.
2. **`scripts/pixelate_sprite_sheet.py`** — Post-processes each frame: crops to a union bounding box, nearest-neighbor downscales to 64px, adds a 1px outline, and stitches frames into a horizontal sprite sheet.
3. **`scripts/create_art_review.py`** — Generates a composite review sheet stacking all vehicle sprites for quality inspection.

See `.claude/agents/painter.md` for full pipeline specification and usage.

### Pending: side coloration & dye pass

All vehicle GLBs render with their source Sketchfab textures (as-is). A **later dye pass** will tone Ukrainian vehicles with a slight olive green and Russian vehicles with a darker, more desaturated green to reinforce faction identity. For now, the sheet review is in uniform lighting and camera framing across the entire roster.
