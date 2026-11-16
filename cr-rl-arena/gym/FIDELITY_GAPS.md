# Fidelity gaps vs. real Clash Royale

An honest, exhaustive accounting of where the `cr_sim` engine diverges from the
real game. The simulator faithfully models the **macro loop** — elixir tempo,
8-card cycle, two lanes + bridges, tower hitboxes, target commitment, collision,
crowns, and overtime — and is deterministic and self-consistent. It is **not** a
card-complete or frame-exact reimplementation. An agent trained here learns *this*
game well; it would **not** transfer to real Clash Royale as-is.

Tags: `[BUG]` wrong vs real CR (should fix) · `[SIMPLIFIED]` approximation of a
real mechanic · `[MISSING]` real mechanic absent entirely.

Severity (RL impact): **H** changes learned strategy · **M** noticeable ·
**L** minor/edge.

---

## STATUS CORRECTION — 2026-11-15 (audit against the live code)

Much of this file was written 2026-11-11/12 and **had gone stale**: it still lists
mechanics as open `[BUG]`/`[MISSING]` that are in fact implemented and covered by the
test suite (`cargo test --release`: 56/56 green at commit 265ddfb). Verified in the
current `engine.rs` / `cards.rs` / `data/cards.json`:

- **§1 King-tower activation — RESOLVED.** The king wakes only when the king itself is
  damaged (`apply_damage`: "The king wakes only when the KING ITSELF is damaged") or when
  a princess tower is **destroyed** — not on chip damage. Not a bug anymore.
- **§1 Deploying units targetable — RESOLVED.** Target acquisition skips `e.deploy > 0`
  ("a unit is a valid target only once placed"), so deploying units can't be hit.
- **§2/§3 Flat 0.2 s wind-up — RESOLVED.** Every card carries a real `load_time`
  (first-hit delay) from the decoded tables; the global constant is gone.
- **§3 Roster mechanics — RESOLVED.** death spawns/splits, spawner buildings, charge/dash
  (Prince/Bandit/Mega Knight/Battle Ram), ramp/siege (Inferno/Sparky/Mortar/X-Bow),
  shields, suicide units, enemy-side deploys (`deploy_anywhere`: Miner/Goblin Drill),
  reflect (Electro Giant), hook (Fisherman), jump+landing (Mega Knight), revive (Phoenix),
  champions + abilities, and **evolutions** (evo-cycle charge → evolved variant) are all
  implemented. Roster is 132 cards / 116 deployable.
- **§4 Spells & status — RESOLVED.** poison, rage, heal, freeze, slow, tornado (pull),
  clone, curse, rolling-pierce (Log/Bowler), knockback, and timed spawns are modeled; spells
  commit at cast and resolve on a short fuse (dodge window).
- **§9 Elixir Collector + Mirror — RESOLVED.** `elixir_per_pulse` grants the owner elixir
  (10 cap); `mirror:true` replays the last card at +1 elixir.
- **§6 Mass-weighted push — ALREADY DONE** (see the stale bullet in §6; push splits overlap
  by mass ratio and knockback uses `mass_resist`).

**Still genuinely open:** Goblinstein tether/revive activated ability; cross-lane aggro-pull
(approximation); champion ability cooldowns (Mighty Miner/Monk/Little Prince — numeric values
absent from the decoded data); tower-stat cross-check vs authoritative tables; and the
by-design scope items (20 Hz tick, 1v1-only, no event modes, queue-order matchmaking). The
per-section `[BUG]`/`[MISSING]` tags below are left in place but should be read through this
correction; a tag flipped inline is marked `[RESOLVED 2026-11-15]`.

---

## Resolved in the 2026-11-11 mechanics pass

- **King activation bug** — king now wakes only when it is damaged or a Princess
  tower is destroyed (not on Princess chip damage).
- **Deploying units are no longer targetable** until placement completes.
- **Per-card first-hit timing** — `load_time` per card replaces the flat 0.2 s.
- **Mass-weighted push** — collisions split inversely to `mass` (heavier moves less).
- **Shields** — `shield` hp absorbs before body hp (Guards, Dark Prince).
- **Death-spawns** — `death_spawn{card,count}` (Golem→golemites, Tombstone, …).
- **Spawner buildings** — `spawn{card,count,interval}` (Tombstone, Goblin Hut, Witch).
- **Status effects** — stun/freeze, slow, rage now modeled; movement + attack
  cadence honor them.
- **Spell effects** — `effect` = poison (DoT zone) / rage / heal / freeze / slow,
  via a lingering area-effect system.
- **Per-card deploy time** and a summon-only (`deployable:false`) flag.
- **Roster expanded** to ~37 cards with level-11 stats exercising all of the above.

## Resolved in the 2026-11-11 multi-agent parity pass (roster now 85 cards)

A second pass closed most of §3–§12 below. Each mechanic class was implemented
data-driven, then integrated and re-verified (determinism preserved; 10 Rust + 3
Python tests pass; mechanics spot-checked at runtime).

- **Charge / dash variants** — Prince/Dark-Prince charge, Bandit dash (invuln while
  dashing, 2× on arrival), Battle Ram (charge → death-spawns Barbarians), Ram Rider
  (charge + snare), Mega Knight (deploy + jump landing AoE), Royal Hogs, Lumberjack
  (death Rage zone). Fields: `dash{…}`, `charge{…}`, `snare`, `knockback`, `dies_on_hit`.
- **Ramp-up / charge-shot / siege** — Inferno Tower & Inferno Dragon (3-stage
  `ramp_damage[]`, resets on retarget/stun), Sparky (`charge_time` big shot, reset on
  stun), Mortar (`min_range` dead zone) & X-Bow (`prefers_buildings`, long range).
- **Reflect & pull** — Electro Giant (reflects damage+stun to attackers in radius),
  Fisherman (hook pulls the target in, or pulls self to buildings).
- **Revive & chained multi-stage** — Phoenix (egg → reborn once, at `revive_hp_pct`);
  chained `death_spawn` (Elixir Golem → golemites → blobs; Goblin Giant).
- **Invisibility** — Royal Ghost (`invisible`): untargetable except a ~0.75 s window
  after each attack; area/splash still hits it.
- **Champions** — one-per-deck (`champion:true`), activatable ability via
  `Battle.activate_ability(player)` or the reserved `ABILITY_SLOT` in `step`: Archer
  Queen (cloak), Skeleton King (summon), Golden Knight (line dash). Deck validation
  rejects >1 champion.
- **Evolutions** — `evolved`/`evo_cycles` with a per-slot charge counter in reset()
  state: Evo Knight (shield), Evo Skeletons (×2 count), Evo Royal Giant (knockback).
- **Enemy-side win conditions** — `deploy_anywhere`: Miner, Goblin Drill (spawner +
  death burst), Graveyard (timed spawn zone), Goblin Barrel (instant spawn).
- **Building-aware pathfinding** — reactive local avoidance: ground units steer
  around a blocking non-target building instead of shoving into it (approximate).
- **Knockback & pull** — The Log / Bowler (rolling-line pierce + knockback), Tornado
  (`AeoKind::Pull`), Giant Snowball / Fireball / Rocket knockback; mass-scaled resist.
- **Projectile behaviors** — commit-to-ground (dodgeable spells via `homing:false`),
  chain (Electro Wizard/Spirit), pierce/boomerang line (Magic Archer, Executioner),
  on-hit slow/freeze (Ice Wizard, Ice Spirit), Lightning top-K-by-HP.
- **Economy & suicide units** — Elixir Collector (`elixir_per_pulse`), Mirror
  (`mirror:true`, replays last card at +1 elixir), Fire/Ice/Electro Spirit & Wall
  Breakers (`suicide` on-contact explode).

**Still outstanding after this pass:** exact stat verification against the decoded
tables (numbers are knowledge-entered level-11 values — hit speeds/ranges likeliest
to be off); the remaining long tail of the ~120-card roster and their rarer unique
behaviors; true tile-exact pathfinding and CR's exact aggro/target-priority rules;
2v2 / draft / event modes. These are refinements, not blockers.

Everything below is the original gap list; items above are now resolved.

---

## 1. Confirmed incorrect rules (bugs, not just simplifications)

- `[RESOLVED 2026-11-15]` ~~`[BUG]` **H — King-tower activation is too eager.**~~ Fixed:
  `apply_damage` now wakes the king only on king-damage or princess-destruction. ~~The king wakes whenever
  *any* friendly tower takes *any* damage (`engine.rs::apply_damage`). Real rule:
  the king activates only when **it** is damaged or when a **Princess tower is
  destroyed** — chip damage to a Princess tower must not wake the king. Current
  behavior lets a single arrow on a Princess tower activate the king early.~~
- `[RESOLVED 2026-11-15]` ~~`[BUG]` **M — Deploying units are targetable.**~~ Fixed:
  acquisition skips `e.deploy > 0`, so a unit is a valid target only once placed. ~~During the 1 s deploy a unit is
  non-colliding but still `alive`, so it can be targeted and attacked. In CR a
  troop is not a valid target until placement completes.~~
- `[BUG]` **L — Attack wind-up resets on any target change but not on leaving/re-entering range symmetrically.** The generic 0.2 s wind-up (`engaged` flag) is a
  coarse stand-in for per-card load/first-hit timing (see §3).

## 2. Timing & tick model

- `[RESOLVED 2026-11-15]` **H — Flat 0.2 s attack wind-up for every card.** Fixed: every
  card now uses its real per-card `load_time` (first-hit delay) from the decoded tables. ~~Real CR has
  per-card **load time** and **first-hit** values; melee trades (Mini-PEKKA vs
  tank, Prince connect, Inferno lock) depend on them. One global constant is the
  single most impactful *mechanical* inaccuracy after the roster.~~
- `[SIMPLIFIED]` **M — 20 Hz tick rate.** The real engine advances on a finer
  internal timestep, so hit speeds, deploy times, and elixir quantize to 50 ms
  here and are not all frame-exact.
  - `[DEFERRED 2026-11-12]` (M7) Deliberately NOT changed: the core 20 Hz tick is the
    calibration base for every tuned stat, the stat-reconciled level-11 numbers, and
    the determinism/perf baseline — rescaling it would invalidate all of them for no
    fidelity gain. Agents are asked for a move on every tick; see §13.
- `[SIMPLIFIED]` **L — Hit cadence applies damage at cooldown edge**, not at the
  specific damage frame within an attack animation.

## 3. Card roster & per-card mechanics — the largest gap

- `[RESOLVED 2026-11-12]` **Roster expanded to 120 cards** (was 85). The 2026-11-12
  pass added the remaining standard in-use ladder cards straight from the decoded
  tables (Balloon, Giant Skeleton, Princess, Lava Hound+pups, Mega Minion, Hunter,
  Royal Recruits, Night Witch, Zappies, Electro Dragon, Firecracker, Skeleton
  Barrel, Skeleton Dragons, Battle Healer, Minion Giant, Goblin Demolisher, Goblin
  Machine, Berserker, Ronin, the Champions Mighty Miner / Monk / Little Prince /
  Boss Bandit, the buildings Bomb Tower / Barbarian Hut / Tesla / Furnace / Goblin
  Cage, and the spells Earthquake / Barbarian Barrel / Royal Delivery), each with
  real L11 stats and its core mechanic (death bombs, spawns, chains, shields,
  dashes, ramp). Deliberately skipped (unmappable to the current single-def model
  or using unmodelled mechanics): mixed-composition cards (Goblin Gang, Rascals),
  Mother Witch / Goblin Curse (curse-to-pig), Clone, Suspicious Bush (invis bush),
  Goblinstein (two-part champ), and all Super/Party/Chess event variants. Champion
  activated abilities for the new champions are not yet modelled (combat stats are).
  The bullets below are the ORIGINAL gap list — most are since resolved.

The gym originally shipped **18 generic cards**; real CR has ~120, most with unique
logic that *is* the strategy. Entire mechanic classes were absent:

- `[MISSING]` **H — Death spawns / splits:** Golem→golemites, Lava Hound→pups,
  Giant Skeleton bomb, Balloon death bomb, Goblin Barrel, Skeleton Barrel,
  Wall Breakers, Elixir Golem blobs, Goblin Giant.
- `[MISSING]` **H — Spawner buildings:** Tombstone, Barbarian/Goblin Hut, Furnace,
  Goblin Drill; and **Elixir Collector** (an entire economic axis).
- `[MISSING]` **H — Charge / dash variants:** only a generic Prince-style charge
  exists. Dark Prince (shield), Battle Ram, Ram Rider (charge+snare), Bandit
  (dash+invuln), Royal Hogs, Elite Barbarians, Lumberjack (death Rage).
- `[MISSING]` **H — Ramp / charge-up attacks:** Inferno Tower & Inferno Dragon
  (ramping damage), Sparky (charged shot, reset on stun), Mortar/X-Bow (siege).
- `[MISSING]` **H — Shields:** Dark Prince, Guards, Royal Recruits (absorb one hit).
- `[MISSING]` **H — "Deploy anywhere" win conditions:** Miner, Goblin Drill,
  Graveyard, Goblin Barrel land on the **enemy** side. The gym restricts troop
  deploys to your own territory (+ opened pocket), so these can't be represented.
- `[MISSING]` **M — Reflect / on-hit effects:** Electro Giant (zaps attackers),
  Fisherman (hook/pull), Mega Knight (jump + spawn/landing damage).
- `[MISSING]` **M — Revive / multi-stage:** Phoenix revive; Golem/Lava/Goblin
  Giant/Elixir Golem staged splits.
- `[MISSING]` **M — Invisibility:** Royal Ghost.
- `[MISSING]` **M — Champions** (one-per-deck + activatable ability): Golden
  Knight, Skeleton King, Archer Queen, Mighty Miner, Monk, Little Prince, etc.
- `[MISSING]` **M — Evolutions** (evolved stats/behavior + evo-cycle counter).
- `[SIMPLIFIED]` **M — Multi-unit spawn formation** uses a simple line offset, not
  CR's per-card spawn formations/positions.
  - `[RESOLVED 2026-11-12]` (M6) `spawn_offset` now places grouped spawns in compact
    per-count formations — side-by-side pairs, triangles, 2×2 squares, diamond+centre,
    2×3 blocks, and a centred grid for larger counts — instead of one row. Offsets stay
    <~1 tile (on/next to the deploy tile) and are pure fixed-point (deterministic).

## 4. Spells & status effects

The spell system is **instant area damage + optional stun only**
(`engine.rs::cast_spell`). Missing:

- `[MISSING]` **H — Lingering/area effects:** Poison & Earthquake (DoT over time,
  Earthquake building bonus), Rage (speed/attack buff zone), Heal, Tornado (pull),
  Graveyard (timed skeleton spawns), Clone, Freeze (duration lock), Barbarian
  Barrel / Log (rolling line + knockback/rollthrough), Giant Snowball & Ice spells
  (slow), Lightning (3 highest-HP targets + stun), Fireball/Rocket knockback.
- `[SIMPLIFIED]` **M — Spells are near-instant** (high projectile speed), so there
  is no cast→travel dodge window as in CR.
  - `[RESOLVED 2026-11-12]` (M3) Spells now commit to their ground point at cast time
    but resolve a short, data-plausible number of ticks later (a "fuse" derived from a
    fixed drop distance ÷ the card's projectile speed: Zap/Lightning ~0.25 s,
    Fireball/Rocket ~0.5 s; effect-only spells ~0.3 s). Damage/crown/effect behaviour is
    unchanged — only time-shifted — so a fast troop can walk out of the blast. Pending
    casts are part of reset() state (replay-deterministic).
- `[SIMPLIFIED]` **L — Crown-tower damage reduction** is a flat `crown_pct`
  (~30%); real per-spell crown-tower damage values differ.

## 5. Movement & pathfinding

- `[RESOLVED 2026-11-12]` **True tile pathfinding.** Ground units now route on
  the 18×32 tile grid via a BFS **flow field** computed from each target's
  footprint over a passability grid (river impassable except on the bridges;
  towers and buildings are solid tiles). A unit heads straight at its target when
  it has clear line of sight, and otherwise descends the flow field — string-
  pulled to the farthest visible tile on the route — so it genuinely **routes
  around** placed buildings (Cannon, Tombstone, etc.) and to the correct bridge
  instead of shoving against obstacles. Fields are a pure function of (blocked
  tiles, target footprint, jump flag) and are memoised across ticks (invalidated
  when the obstacle layout changes or the target changes tile), so determinism is
  unchanged and the hot path stays fast. Replaces the old "aim at the nearest
  bridge mouth" heuristic and the reactive local-avoidance pass.
  (`engine.rs`: `PathGrid`, `PathCache`, `path_goal`.)
- `[SIMPLIFIED]` **L — Bank-hugging / corner-clipping** near the river still
  differs slightly from CR's exact sub-tile pathing (the grid resolves to whole
  tiles; `block_river` + collisions keep motion legal at the sub-tile level).
- `[SIMPLIFIED]` **L — Instant turning** (no facing/turn delay).

## 6. Collision & physics

- `[RESOLVED 2026-11-15]` **H — Mass-weighted push** (this "no mass" bullet is stale).
  Fixed: overlap splits by mass ratio and knockback uses `mass_resist`, so a Knight shoves a
  Skeleton far more than the reverse. Old description follows: ~~Each body pushes the
  other equally.~~ Real CR is **mass/push-weight** based: a Knight shoves a Skeleton
  far more than the reverse, and some units resist pushing. This changes surrounds,
  pig-pushing, and tank-behind-support positioning.
- `[SIMPLIFIED]` **L — Two relaxation passes/tick**; dense crowds settle
  approximately, not exactly as CR's solver would.

## 7. Targeting & aggro

- `[SIMPLIFIED]` **M — Leash distances are invented** (`sight + 2.5`), not CR
  values; retarget/lock thresholds therefore differ.
  - `[RESOLVED 2026-11-12]` (M1) The invented `sight + 2.5` leash is gone: a unit now
    holds its committed target only while the target stays inside the unit's own aggro
    radius (`sight.max(range)`, data-derived). Once the target leaves that radius the
    unit re-acquires — for a lane pusher that means falling back to marching on the
    nearest tower. Building-only targeters still never drop a building objective.
- `[SIMPLIFIED]` **M — Acquisition is nearest-valid-in-sight.** CR has specific
  target-priority and aggro-pull rules (pulling a unit off its lane) that are only
  approximated.
  - `[RESOLVED 2026-11-12]` (M1) Target priority is honored where the data supports it:
    buildings-only (hard filter) and building-preferring (X-Bow) units now also re-scan
    off a currently-held troop so an in-sight building can take priority. Acquisition
    stays deterministic (nearest valid; ties → lower entity index). General aggro-pull
    across lanes remains an approximation.
- `[SIMPLIFIED]` **L — Tower targeting** locks nearest and holds; real tower
  retarget timing/priority is approximated.

## 8. Deploy mechanics

- `[SIMPLIFIED]` **M — Flat 1.0 s deploy time** for all cards; real deploy/placement
  times vary by card.
  - `[RESOLVED 2026-11-12]` (M4) `spawn_unit` uses each card's own `deploy_ticks`
    (from the real `deploy_time`, e.g. Golem 3.0 s, Mortar/X-Bow 3.5 s), falling back to
    the named `DEPLOY_TICKS` (1.0 s) constant only when a card has none.
- `[MISSING]` **M — Enemy-side deploys** (see Miner/Graveyard/Drill/Barrel in §3).
- `[SIMPLIFIED]` **L — Deployable rows** use `y < 15` (river rows 15–16); close to
  but not pixel-matched with CR's deploy boundary and the exact pocket shape after
  a tower falls.

## 9. Elixir & economy

- `[RESOLVED 2026-11-15]` **M — Elixir Collector / Pump** — modeled: `elixir_per_pulse`
  grants the owner elixir each pulse (respects the 10 cap).
- `[RESOLVED 2026-11-15]` **L — Mirror** — modeled: `mirror:true` replays the owner's
  last-deployed card at +1 elixir.
- `[SIMPLIFIED]` **L — Overtime elixir multiplier/duration** (2 min, 3×) is a
  reasonable config, not matched to a specific CR mode/patch.
- Correct: start 5, cap 10, 2.8 s regen, 2× starting at 1:00 remaining.

## 10. Towers & win conditions

- `[SIMPLIFIED]` **M — Overtime tiebreak** = lowest remaining tower HP; approximates
  CR's rule but isn't matched to a specific mode.
  - `[RESOLVED 2026-11-12]` (M5) Overtime is now sudden death: the first player to pull
    ahead on crowns (destroy a tower) in OT wins immediately. A same-tick exchange that
    leaves crowns tied keeps play going. Lowest-remaining-tower-HP is used only as the
    final fallback when OT expires still tied (a dead-even board is a draw).
- `[RESOLVED 2026-11-15]` **L — Tower stats verified.** Cross-checked the sim's tower defs
  (Princess HP 2534 / dmg 90 / hit 0.8 s / range 7.5; King HP 4008 / dmg 90 / hit 1.0 s /
  range 7.0, dormant) against the canonical level-11 Tournament-Standard values — exact match
  (the 2534 / 4008 HP figures are the precise lvl-11 numbers). The crown/match **rules** match
  the decoded `battle_constants.json` authoritatively: `crowns_per_princess_tower = 1`,
  `crowns_for_king_tower = 3`, `king_tower_ends_match = true`. No discrepancies; no change needed.
- Correct: Princess = 1 crown, King = 3 and ends the match; king dormant until
  activated (modulo the activation bug in §1).

## 11. Projectiles

- `[SIMPLIFIED]` **M — Projectiles home to the target entity**; most real CR
  projectiles commit to a position and can be dodged by movement.
  - `[RESOLVED 2026-11-12]` (M2) Homing is now per-shot: single-target "tracking" shots
    (Musketeer, Archers, Dart Goblin, …) home to the entity (matching the decoded
    `projectiles.toml`, where direct shots are `Homing = true`), while splash/area shots
    (Bomber, Wizard, Baby Dragon, Sparky, Mortar, …) commit to the fire-time ground point
    and are dodgeable. Driven by `proj_homes()` with an explicit per-card `homing` override
    (the real `Homing` flag). Pierce/roll shots never home (unchanged).
- `[MISSING]` **L — Projectile-specific behavior:** pierce (Magic Archer, Dart
  Goblin line), returning axe (Executioner), bounce/pierce (Bowler), recoil.

## 12. Stat accuracy

- `[RESOLVED 2026-11-12]` **Card stats reconciled against the decoded `csv_logic`
  tables.** Every card's HP, damage, hit speed, load time, range, speed, mass,
  collision radius, sight, deploy time, targeting (incl. buildings-only), flying,
  spawn count, elixir, and splash radius are now taken straight from the decoded
  character/projectile/area-effect TOMLs; spell damage, radius, and crown-tower
  damage from their projectile/AEO defs. 79/85 cards updated (522 field changes).
  - **Level-11 scaling** uses the authoritative `rarities.csv` `PowerLevelMultiplier`
    table: level 1 = base, **level 11 (tournament standard) = round(base × 2.56)**
    (the 256% entry, identical across rarities). Verified against known values —
    Fireball 269→689, Lightning 413→1057, P.E.K.K.A 1469→3761, Golem 2000→5120.
  - Spell crown-tower damage is now per-spell (`crown_pct` = 100 + the file's
    `CrownTowerDamagePercent`, e.g. Fireball 23, Zap 25, Log 13) rather than a flat
    placeholder; Zap/Freeze read their `{BaseDamage,TowerDamage}` structs directly.

- `[RESOLVED 2026-11-12, follow-up pass]` the four caveats from the first pass are closed:
  1. **Magic Archer** was found in the decoded data under its dev name `EliteArcher`
     (`BlueExportName = "magic_archer"`): base HP 207→**530**, dmg 53→**136** — now exact.
  2. **Towers** reconciled to authoritative tournament-standard values: Princess
     **2534 HP / 90 dmg**, King **4008 HP / 90 dmg** (both tower damage was wrongly 109;
     the first pass's ×1.81 King-HP extrapolation to 4344 was wrong — real is 4008). Real
     building collision radii applied (Princess 1.0, King 1.4). No per-level tower table
     exists in the data (only +8%/level king-level constants, which are approximations).
  3. **Per-level rounding** proven to be **round-half-up, one step from the level-1 base**
     (`(base×256+50)/100`), discriminated against floor (Fireball 688.64→689) and ceil
     (Knight 690→1766 not 1767); the "≤1 diff" was stale web data, not a rounding error —
     existing values were already exact, 0 cards changed.
  4. **Mechanic sub-stats** re-derived from the tables (20 corrections): shields
     (guards 256, dark_prince 241), Inferno ramp stages (tower [44,159,847] @2.0s,
     dragon [36,120,422]), charge/dash (battle_ram/ram_rider speed ×2.0, bandit dash 6.0,
     mega_knight land radius 2.2, ram_rider snare 2.0s), buff durations (rage 4.5s,
     freeze 3.5s, snowball slow 3.0s, poison 92 dps, ice_spirit freeze 1.1s, ice_wizard
     slow 2.5s), electro_giant reflect radius 2.0, witch spawn count 4, goblin_hut spawn
     interval 2.2s. A few leaves were deliberately left (evo_knight uses a 60%
     damage-reduction buff not a flat shield; mega_knight has distinct jump-vs-deploy
     land damage the single field can't hold) — see the stat-fix report.

- **Separately** (correctness, not a stat): fixed a crown-accounting bug where destroying
  the King tower stacked its 3 crowns on top of princess-tower crowns (could reach 4).
  King death now sets the total to 3; princess crowns cap at 3. Regression test
  `king_tower_kill_caps_crowns_at_three`; verified ≤3 across 40 seeds.

## 13. Interface / observability caveats (sim design, not CR mechanics)

- `[RESOLVED 2026-11-12]` **Observability guard added — opponent hidden info is
  no longer reachable through the raw API.** The competition `obs` already
  **hid** opponent hand, next card, and elixir (only the full board + your own
  hand/elixir/crowns are exposed) — matching CR's hidden information — but the
  raw `Battle` still exposed `elixir(opponent)`, `hand(opponent)`, etc., so local
  self-play could "cheat". Now `Battle.view(player)` returns a read-only
  `PlayerView` (new pyclass in `src/env.rs`, registered in `src/lib.rs`,
  re-exported from `python/cr_sim/__init__.py`) that a competition harness hands
  to each agent instead of the raw `Battle`. The view exposes the full board
  (`entities`/`towers`/`projectiles`), its **own** hand/next-card/elixir/crowns/
  champion-status, the opponent's crown count + tower state (public), and the
  fog-of-war `observe()`/`legal()` for its seat — its private getters take **no
  player argument** and there is no accessor for the opponent's hand, next card,
  or elixir, so an agent *structurally* cannot peek. The view is read-only (no
  `step`/`reset`/`activate_ability`) and does not touch simulation state, so
  determinism is unaffected. The raw `Battle` getters remain for the trusted
  harness, debugging, and replay. Proven by Rust `env::view_tests` (seat/clamp
  logic) and Python `tests/test_fog.py` (own state readable; `view(0).hand(1)` /
  `.elixir(1)` raise `TypeError`; no opponent private key in `observe()`).
- `[RESOLVED]` **M — Decision cadence.** The server asks each agent for a move on
  every tick (20 Hz), the same as stepping the simulator locally, so agents can act
  on any tick as in CR. Changing the tick rate itself is deliberately deferred
  (see §2).

## 14. Scope not modeled at all

- `[MISSING]` 1v1 only — no 2v2, draft, Touchdown, or event rulesets.
- `[MISSING]` No trophy/ladder matchmaking (server pairs by queue order, not skill
  bands); the Elo ranking is the competition's own, not CR's.
- `[MISSING]` No pre-game (deck-draw order is a seeded shuffle; CR's exact initial
  draw rules are approximated).

---

## Priority order to close gaps (suggested)

1. **Correctness quick wins:** fix king activation (§1), deploying-unit
   targetability (§1).
2. **Per-card timing:** add `first_hit` / `load_time` fields and use them instead
   of the flat wind-up (§2, §3).
3. **Status-effect & spell framework:** slow / freeze / stun / rage / DoT /
   knockback / pull, so most spells and control cards become expressible (§4).
4. **Death-spawns & spawner buildings** (§3) — unlocks a large slice of the roster.
5. **Mass-weighted push** (§6) — done 2026-11-11. ~~building-aware pathfinding (§5)~~
   **Done 2026-11-12**: replaced with a true tile flow-field pathfinder.
6. ~~**Verify stats** against authoritative tables (§12).~~ **Done 2026-11-12** —
   all card/tower stats reconciled against the decoded `csv_logic` tables.

None of these block the hackathon: the current engine is a coherent, deterministic
RTS. They are what it would take to approach real-CR parity.
