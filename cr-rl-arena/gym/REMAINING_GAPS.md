# Remaining fidelity gaps — work list (2026-11-12)

Authoritative checklist of what's left after the pathfinding rewrite, the 85→120
roster expansion, the observability guard, and the medium-gap pass. Work the
**actionable** items top-down; **scope decisions** are confirmed-and-documented,
not implemented.

## How to work this list (worker instructions)
- **Determinism is sacred.** All gameplay math is fixed-point Q16.16 (`src/fixed.rs`).
  No floats in gameplay state, no order-dependent `HashMap` iteration, no wall-clock,
  no unseeded RNG. Two runs of a seed must stay bit-identical.
- **Real values only.** Pull stats/ability data from the decoded tables at
  `/home/clio/projects/clashroyale/client-new/data/csv_logic/` (characters/*.toml,
  projectiles.toml, area_effect_objects.toml, spells_*.csv, actions.toml). Level-11 =
  `round(base × 2.56)`; times/1000, ranges/1000, Speed/60, Mass/10. A prebuilt index
  of every object is at the session scratchpad `game_index.json` (+ `resolve_stats.py`).
- **One item at a time.** For each item: make the real change, add/adjust a Rust
  `#[test]` proving it, run `cd gym && cargo test --release` (green), then tick the box
  here with a one-line note **and the commit SHA**, and `git commit` (author
  `Alex <42507764+ilumn@users.noreply.github.com>`, **no** Claude attribution footer).
- **Check a box only when the code actually does it.** A ticked box with no real diff +
  passing test behind it will be rejected on audit. If an item can't be done faithfully,
  mark it `[~]` DEFERRED with the concrete reason, don't fake a `[x]`.
- Do **not** run `maturin develop`/`pytest` (shared venv); `cargo test` is your gate.
- Keep edits off the pathfinding core (`PathGrid`/`PathCache`/`path_goal`) unless an item
  requires it.

---

## A. Actionable

- [x] **A1 — New champions' activated abilities.** Mighty Miner, Monk, Little Prince,
  Boss Bandit are deck-legal with real combat but no activated ability (`ability` = None).
  Model each ability faithfully using the decoded ability data (cost/cooldown/duration/
  damage from the character TOMLs + `ManaCostFromSummonerMana` in `spells_characters.csv`).
  Existing `AbilityKind` is `Cloak|Summon|Dash` (see `archer_queen`/`skeleton_king`/
  `golden_knight` in `cards.json` and `activate_ability` in `engine.rs`). Add new ability
  kinds if a champion needs one (e.g. Monk's deflect/pushback, Little Prince's power shot /
  Guardian, Mighty Miner's bomb-dash), or approximate to the nearest kind and document it.
  Acceptance: each of the 4 champions has a working `ability{...}` that fires via
  `Battle.activate_ability`, with a test per champion asserting the effect.
  DONE: added 3 new `AbilityKind`s (`LaneBomb`, `Deflect`, `Warp`) + reused `Summon`.
  Mighty Miner `lanebomb` = switch to mirror lane (reflect x) + drop a 333-dmg (L11 of
  MightyMinerExplosion BaseDamage 130) / 3.0-tile-radius / 1.8-knockback blast at the old
  spot; Monk `deflect` = 4.0s (AbilityStateDuration 4000) 65%-damage-reduction window
  (ShieldBoostMonk DamageReduction=65), applied in `apply_damage`; Little Prince `summon` =
  1 `guardian` (ChampionGuard 1600hp/233dmg, added as new `deployable:false` card); Boss
  Bandit `warp` = 6-tile (WarpY 6000) forward warp + 1.0s (SpawnTime 1000) cloak + target
  reset. Costs (ManaCost) exact: MM/Monk/BB=1, LP=3. Cooldowns: Boss Bandit 3.0s exact
  (Cooldown=3000); MM 3.5s / Monk 12.0s / LP 20.0s are documented APPROXIMATIONS — the
  decoded tables store only the leveled stat-tag `ability_cooldown`, not its numeric. Tests:
  `mighty_miner_lanebomb_damages_and_switches_lane`, `monk_deflect_reduces_incoming_damage`,
  `little_prince_summons_guardian`, `boss_bandit_warps_forward_and_cloaks`,
  `champion_abilities_are_deterministic`. `cargo test --release`: 29/29 pass. Commit: 65abdcb
- [x] **A2 — Hunter shotgun burst + Firecracker recoil.** Hunter currently fires one
  weak projectile (per-pellet damage); real Hunter deals many pellets (big point-blank
  burst, falls off with range). Model its effective multi-pellet damage from the data
  (pellet count × per-pellet) without overpowering it at range. Firecracker should apply
  its self-recoil knockback on firing. Acceptance: Hunter kills far faster point-blank
  than at max range; a test covers both; Firecracker recoils. Resolve real numbers from
  the tables (HunterProjectile / `MultipleProjectiles` / Firecracker recoil fields).
  DONE: added `pellets` + `recoil` card fields. Hunter `pellets:10` (`MultipleProjectiles=10`;
  per-pellet base 33 => L11 84, which is exactly today's `damage:84`); the fired shot now
  carries `per_hit × pellets_that_connect` via `Engine::shotgun_damage` — all 10 point-blank,
  falling linearly to 1 at max range (gap/range), so 840 point-blank vs 84 at the edge, no
  range buff. Firecracker `recoil:1.0` (`AttackPushBack=1000`) shoves the shooter backward
  (away from target, river/bounds-respected) once per shot. Tests:
  `hunter_shotgun_falloff_is_monotonic`, `hunter_fires_bigger_burst_point_blank_than_far`,
  `firecracker_recoils_backward_on_firing`. `cargo test --release`: 32/32 pass. Commit: c362471
- [x] **A3 — Battle Healer heal aura.** Battle Healer continuously heals nearby allies
  (and herself) in a radius. Model it (reuse the area-effect/heal system — see `Heal`
  `SpellEffect` and `apply_area_effects`). Acceptance: allies in her radius regain hp over
  time; a test asserts a damaged nearby ally heals while she's alive. Pull heal rate/radius
  from the decoded data.
  DONE: new `heal_aura{power,radius,interval}` card field + `Engine::apply_heal_auras`
  (re-anchored to the healer each pulse so it tracks her movement). battle_healer heals
  friendly TROOPS (incl. self, no buildings/towers — CR `friendly_troop_no_buildings`)
  within radius 3.0 (`BattleHealerAll` AEO Radius 3000) by 26 hp every 0.25s (HitFrequency
  250) = ~104/s ≈ the L11 HealPerSecond (40 base ×2.56 = 102). Filters on `alive()` so a
  healer dying this tick can't self-resurrect via its own aura (caught + fixed by the
  second test). Tests: `battle_healer_heals_nearby_ally_and_self` (incl. a far ally that is
  NOT healed), `heal_aura_stops_when_healer_dies`. `cargo test --release`: 34/34 pass.
  Commit: 5372752
- [x] **A4 — Mixed-composition cards (Goblin Gang, Rascals).** These deploy a MIX of unit
  types in one card (Goblin Gang = 3 stab goblins + 3 spear goblins; Rascals = 1 Rascal Boy
  tank + 2 Rascal Girls ranged). The engine spawns `count` of ONE def. Add a
  secondary-spawn-on-deploy mechanism (e.g. a `deploy_spawn{card,count}` field, or reuse the
  spawn system at deploy) so these are faithful, then add the two cards to `cards.json` with
  real stats. Acceptance: deploying each yields the correct mixed group; a test verifies the
  counts/types. (Add the summon-only sub-units as `deployable:false`.)
  DONE: added a `deploy_spawn{card,count}` field + the place_card branch that spawns the
  secondary group one tile toward the owner's side. Both cards added with real stats from
  spells_characters.csv + the sub-unit TOMLs (L11 ×2.56): `goblin_gang` (elixir 3, 3×
  Goblin_Stab 202hp/125dmg melee + deploy_spawn 3× existing `spear_goblins`), `rascals`
  (elixir 5, 1× RascalBoy 1833hp/218dmg tank + deploy_spawn 2× new `rascal_girl` 261hp/125dmg
  ranged, `deployable:false`). Goblin Gang reuses the existing spear_goblins def (spawn_unit
  spawns one entity per call, ignoring that def's own count). Tests:
  `goblin_gang_deploys_three_stab_plus_three_spear`, `rascals_deploys_one_boy_plus_two_girls`,
  `mix_card_deck_legality`, `mixed_deploy_is_deterministic`. `cargo test --release`: 38/38
  pass. Commit: e4b43a1
- [x] **A5 — Targeting/aggro exactness.** M1 set the leash to `sight.max(range)`; refine
  acquisition toward CR's real rules where the data supports it: correct retarget timing,
  and not dropping a committed target prematurely. Keep it deterministic (nearest valid;
  ties → lower entity id). Acceptance: a test showing a unit holds its committed target
  within leash and only re-acquires when it should.
  DONE: M1's `sight.max(range)` leash is already the CR-plausible aggro radius (kept; the
  M1 regression test still passes, so I did NOT widen it — CR drops a target that leaves
  sight). The concrete refinement: acquisition tie-breaks were implicit (scan/index order);
  made them an explicit `(gap, id)` lexicographic rule via a `better()` comparator across
  all three scans (march / sight / building-priority) so equal-distance targets always
  resolve to the LOWER entity id independent of entity storage order. Locked in the
  commitment contract with tests: a committed target is held within leash, a closer
  newcomer does NOT steal aggro (CR pull mechanic), and it re-acquires only once the old
  target leaves the leash. Tests: `commitment_holds_then_reacquires_beyond_leash`,
  `acquisition_ties_break_to_lower_id`. `cargo test --release`: 40/40 pass. Commit: c1beb1a
- [x] **A6 — Crown-tower per-spell damage.** Verify each spell's `crown_tower_damage_pct`
  against the decoded `CrownTowerDamagePercent` / `{BaseDamage,TowerDamage}` structs and
  correct any that are placeholders. Acceptance: the spells' crown percentages match the
  tables; note any corrected in the checklist.
  DONE: crown reduction lives in each spell's `characters/*.toml` as a NEGATIVE
  `CrownTowerDamagePercent` (crown% = 100 + value), or as a `{BaseDamage,TowerDamage}` AEO
  struct (crown% = round(TowerDamage/BaseDamage×100)). Verified all 11 modelled spells.
  CORRECTED 2 placeholders: **poison 30→22** (−78) and **earthquake 33→60** (−40,
  `BuildingDamagePercent=350` is separate and already not modelled as crown). Confirmed
  already-correct: arrows 20 (−80), fireball 23 (−77), rocket 23 (−77), lightning 25 (−75),
  snowball 25 (−75), the_log 13 (−87), tornado 30 (−70), zap 25 (19/75), freeze 26 (15/58).
  NOT in the decoded dump (no crown field on their projectiles): barbarian_barrel and
  royal_delivery — left at 35 and flagged as unverified-from-data. The sole
  `CrownTowerDamagePercent` for a *projectile* (FireballSpellRocketMan −70) is an event card,
  out of scope. Test: `spell_crown_percentages_match_decoded_tables`. `cargo test --release`:
  41/41 pass. Commit: 0800725
- [x] **A7 — Curse / Clone / stretch cards (Mother Witch, Goblin Curse, Clone, Suspicious
  Bush, Goblinstein).** Implement the ones whose mechanic maps cleanly; for any that need a
  genuinely new system beyond reasonable scope, mark `[~]` DEFERRED with the specific reason
  (don't half-add a misleading version). Document each decision. (Item overall [x]: 3
  implemented, 2 deferred-with-reason — all 5 decisions made & documented below.)
  - **Clone — IMPLEMENTED.** New `SpellEffect::Clone`: duplicates every friendly TROOP in
    radius 3.0 (`Clone` Radius 3000) at 1 hp. elixir 3. Test: `clone_duplicates_friendly_troops_at_one_hp`.
  - **Suspicious Bush — IMPLEMENTED.** A fragile stationary bush (hp 82 = 32×2.56, speed 0,
    0 dmg) that death-spawns 2 `bush_goblin` (338hp/256dmg) via the existing death_spawn
    system (`DeathAreaEffect SuspiciousBush_SpawnBushGoblin ×2`). elixir 2. Approximation:
    the invisible/proximity-ambush reveal is NOT modelled (sim has no proximity-reveal
    trigger and an untargetable idle bush would never pop); modelled as a visible fragile
    bush → 2 goblins on death, which reproduces the combat outcome. Test:
    `suspicious_bush_pops_two_goblins_on_death`.
  - **Goblin Curse — IMPLEMENTED.** New `SpellEffect::Curse` + per-entity `curse`/`curse_spawn`
    state + a death-pass transform: cursed enemy troops (radius 3.0, 6.0s = `LifeDuration 6000`)
    take a 36/s DoT (`GoblinCurseDamage` 14×2.56, crown 28% from CrownTowerDamagePerHit 4) and,
    on death, spawn 1 `goblins` FOR THE CASTER (`DeathSpawnIsEnemy=true, DeathSpawnCount=1`).
    elixir 2. Tests: `goblin_curse_transforms_dead_enemy_for_caster`, `uncursed_death_does_not_transform`,
    `curse_and_clone_are_deterministic`.
  - **Mother Witch — [~] DEFERRED.** Her curse is applied by her ranged ATTACK
    (`BuffOnDamage=VoodooCurse`, `DeathSpawn=VoodooHog`). The curse-death transform system now
    EXISTS (shared with Goblin Curse), but applying it on a projectile hit needs the
    (spawn-def,count) payload carried through the hot `proj_impact` path, which only passes
    `i32` accumulator arrays (dmg/stun/slow) — it cannot carry a per-victim spawn payload
    without a new projectile-rider subsystem. Deferred to avoid a misleading half-version.
  - **Goblinstein — [~] DEFERRED.** A Champion that deploys a linked monster + Doctor pet
    (`SummonCharacter goblinstein + goblinstein_doctor`) with the Doctor's own revive/zap
    ability — a new champion-pet-link + ability subsystem beyond clean reuse.
  `cargo test --release`: 46/46 pass. Commit: 33741ac
- [x] **A8 — Dependabot vulnerabilities (3: 1 high / 1 moderate / 1 low).** Identify the
  flagged advisories (`gym` + `server` dependency manifests) and bump conservatively to
  patched versions; `cargo test` must stay green. If a bump can't be done safely, record the
  advisory IDs and why. Acceptance: the fixable advisories resolved; build + tests green.
  **CORRECTION (2026-11-14): the "supply-chain poisoning" reported below was a FALSE POSITIVE.**
  A forensic re-check (user-requested) — reading the *official* local crates.io index history,
  the crates' build scripts, and their source — found both flagged crates are legitimate:
  - **`zmij`** is dtolnay's real Schubfach float formatter, the successor to `ryu` by the *same
    author*, with an organic published version history (0.0.1 … 1.0.23; early versions even
    depend on `ryu`). `serde_json >=1.0.147` adopting it is a normal upstream change.
  - **`syn 3.0`** is a real new major release of dtolnay's `syn`, not a fake.
  The alarm fired only because both crates post-date this tool's Jan-2026 knowledge cutoff (the
  env clock is Nov 2026); an unfamiliar-but-newer crate was misread as a typosquat. There was no
  attack, no malicious code, and no secret exposure — nothing needed rotating.
  - **Resolution:** the unjustified upper-bound pins in `gym/Cargo.toml` were **removed**
    (relaxed back to `serde = "1"` / `serde_json = "1"`). The lockfile was left at its then-current
    clean resolution; the deps are free to move forward to the newer (legitimate) releases.
  - Lesson recorded: verify a "supply-chain" claim by inspecting author/history/build-script/
    source *before* concluding — an unfamiliar crate is almost always newer-than-training, not
    malware. (See memory `rl-sim-stack.md`; SendFeedback filed re: overconfidence.)

  ~~Original (incorrect) finding, kept for the record:~~ the gym `Cargo.lock` was reported
  supply-chain POISONED — `serde_json >=1.0.147` → `zmij` "typosquat" of `ryu`, `serde_derive
  1.0.229` → fake `syn 3.0.10` — and "fixed" by pinning serde_json 1.0.146 / serde 1.0.228 with
  upper bounds. All of that was mistaken, per the correction above.
  - **LOW — `pyo3 0.22.6` (RUSTSEC-2025-0020, buffer overflow in `PyString::from_object`,
    fixed only in 0.24.x): RESOLVED (2026-11-14).** Bumped `pyo3` to `0.24` (resolves 0.24.2).
    The migration was a two-line change — the crate already used the modern `Bound<>` API
    (`#[pymodule] fn _core(m: &Bound<'_, PyModule>)`, `add_class`, `Bound<'py, PyDict>` sigs);
    only `PyDict::new_bound(py)` → `PyDict::new(py)` at `env.rs:222` was deprecated. Validated
    end to end: clean build (no deprecations), `cargo test --release` 56/56, **the Python
    pytest suite 10/10 against the 0.24-built extension** (fog-of-war guard + determinism), and
    the changed `observe()` dict path exercised directly at runtime. (Stayed on 0.24, not the
    newer 0.30, to keep the jump conservative.)
  - server (`server/pyproject.toml`): only `websockets>=12.0` + the local gym; no pinned
    vulnerable version to bump (floor already current).
  Scan confirmed zmij/syn3 are the ONLY poisoned edges in the tree. Test:
  `serde_json_toolchain_is_intact` (ryu float formatting exact; card lib loads). Pre-fix lock
  backed up at the session scratchpad `Cargo.lock.tampered.bak`. `cargo test --release`:
  47/47 pass. Commit: f8709bd

## B. Scope decisions (confirm & document — do NOT implement)

- [x] **B1 — Tick/decision granularity.** Keep the deterministic 20 Hz core tick (changing
  it rescales every tuned stat); agents decide on every tick.
  Confirm + document as by-design.
  CONFIRMED by-design: `arena.rs TICKS_PER_SECOND = 20` is the fixed simulation tick that
  every stat is calibrated against (times×20, speeds/20); changing it would rescale the whole
  table. The server asks each agent for a move on every one of those ticks
  (`server/cr_server/match.py run_match`). No change needed.
- [x] **B2 — Pathfinding sub-tile exactness / instant turning.** The tile flow field is
  faithful at tile granularity; sub-tile bank-hugging and facing/turn delay are intentionally
  not modelled. Confirm + document.
  CONFIRMED by-design: movement uses a per-tick BFS tile flow field (`PathGrid`, `path_goal`,
  cross-tick `PathCache` memo in engine.rs) that routes around river/towers/buildings at tile
  granularity and is deterministic. Sub-tile bank-hugging and facing/turn-rate delay are
  deliberately not modelled (they would add float-prone, order-sensitive state for little RL
  value). Off-limits per the work rules; no change.
- [x] **B3 — Game modes.** 1v1 only; no 2v2, draft, Touchdown, or event rulesets. By design
  for the hackathon. Confirm + document.
  CONFIRMED by-design: the engine is hard-wired 2-seat 1v1 (`elixir: [Fx; 2]`, `player > 1`
  rejected, `for p in 0..2`). No 2v2/draft/Touchdown/event rulesets exist (grep clean). This
  is the intended hackathon scope. No change.
- [x] **B4 — Matchmaking.** Server pairs by queue order with its own Elo ranking, not CR
  trophy bands. By design. Confirm + document.
  CONFIRMED by-design: agents "join the queue and are paired" (`server/cr_server/server.py`)
  and results update a persistent Elo leaderboard (`cr_server/elo.py` + `leaderboard.py`,
  `elo.update`). There are no CR trophy bands / chests / ladder-progression — an Elo ranking is
  the intended competition model. No change.
- [x] **B5 — Event-only card variants.** Super/Party/Chess variants are out of standard-
  ladder scope. Confirm + document.
  CONFIRMED by-design: the 128-card roster is the standard-ladder set; no Super/Party/Chess
  event variants are present (grep of cards.json clean) and the decoded `*_ev1`/`super*`/event
  TOMLs are intentionally excluded. No change.

---

## Audit log (filled by the supervising session)
Every item independently verified before merge to `main` (merge commit on `main`,
pushed). No faked checkmarks found.
- **A1** — ran the suite on the branch (29/29); inspected the 4 ability blocks in
  cards.json, the `deflect` damage-reduction path, the `guardian` card, and the 5
  tests (exact-value asserts). Genuine.
- **A6** — independently confirmed against the raw AEO tables: poison
  `CrownTowerDamagePercent = -78` → crown% 22 (was 30), earthquake `-40` → 60
  (was 33). Corrections are correct.
- **A8** — RETRACTED. The audit originally called the `zmij`/`syn 3.0.10` finding
  "a real, valuable find — not a hallucination." That endorsement was wrong: a later
  forensic re-check showed both crates are legitimate dtolnay releases newer than the
  Jan-2026 knowledge cutoff, so the "typosquat" claim was a false positive. The
  unjustified pins have been relaxed (see the A8 entry's CORRECTION above).
- **A2–A5, A7, B1–B5** — inspected diffs + per-item tests; the two deferrals
  (Mother Witch, Goblinstein) are honestly `[~]` with concrete technical reasons.
- **Full suite** on merged `main`: 47 Rust + (Python) pass. End-to-end: 128 cards /
  114 deployable, every new card + all champion abilities deploy/simulate,
  determinism holds (incl. ability activation). Shared venv refreshed.
