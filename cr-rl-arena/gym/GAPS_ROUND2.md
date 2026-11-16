# Remaining-gaps round 2 — work list (2026-11-12)

The last pass (REMAINING_GAPS.md) deferred two card mechanics and left two smaller
items open. This round closes them. Same discipline as before.

## How to work this list (worker instructions)
- **Determinism is sacred.** Fixed-point Q16.16 (`src/fixed.rs`); no floats in gameplay
  state, no order-dependent `HashMap` iteration in gameplay, no wall-clock/unseeded RNG.
  Seeds replay bit-identically. Add a determinism-guard test for any new stateful mechanic.
- **Real values only**, from the decoded tables at
  `/home/clio/projects/clashroyale/client-new/data/csv_logic/` (characters/*.toml,
  area_effect_objects.toml, projectiles.toml, actions.toml, spells_*.csv). Level-11 =
  `round(base × 2.56)`; times/1000, ranges/1000, Speed/60, Mass/10. Prebuilt index +
  resolver in the session scratchpad: `game_index.json`, `resolve_stats.py` (and grep the
  raw TOMLs directly — the index is known to miss some fields, e.g. ability cooldowns).
- **One item at a time**: real change + a Rust `#[test]` that proves it + full
  `cd gym && cargo test --release` green, then tick the box here with a one-line note **and
  the implementation commit SHA**, and commit (author
  `Alex <42507764+ilumn@users.noreply.github.com>`, **no** Claude attribution footer). One
  commit per item.
- **Tick `[x]` only when the code genuinely does it** (real diff + passing test). If an item
  truly can't be done faithfully, mark `[~]` DEFERRED with the specific technical reason —
  never fake a checkmark. This is audited.
- Do NOT run `maturin develop`/`pytest` (shared venv); `cargo test --release` is your gate.
- Patterns to reuse (all already in the engine): `deploy_spawn{card,count}` (mixed deploy),
  `death_spawn{card,count}`, on-hit status accumulators in `apply_hit`/`proj_impact`, the
  champion `ability{kind,...}` + `activate_ability` + `AbilityKind` enum, `SpellEffect`/
  `apply_area_effects`. Add new optional `CardDef`/`RawCard` fields with defaults so the
  other 128 cards keep loading. Summon-only units are `deployable:false`.

---

## Items

- [x] **R1 — Mother Witch (curse-on-hit).** Internal name `WitchMother` (mana 4 Legendary;
  NOT `DarkWitch`, which is Night Witch and already in as `night_witch`). A ranged attacker
  whose hits **curse** the enemy; a cursed enemy that dies spawns a small "pig"/hog **for the
  Mother Witch's owner** (side-flips the kill). The prior pass deferred this because the curse
  must ride a projectile and spawn a unit on the victim's later death. Implement it: a
  projectile/hit that tags the victim with a `cursed_by<owner>` state, and on that unit's
  death spawn N curse-pigs for that owner. Resolve the real stats + pig unit + counts from the
  tables (WitchMother + its spawn/curse objects). Add `mother_witch` (+ the summon-only pig
  unit). Acceptance: a test where an enemy hit by Mother Witch then killed spawns the pig on
  HER side; an un-cursed death does not; determinism guard.
  DONE (`characters/witchmother.toml`, L11 = round(base×2.56)): added `mother_witch`
  (WitchMother, Legendary, 4 elixir: hp 530, dmg 133, hit 1.0s, load 0.7s, range 5.5,
  targets both, homing proj speed 6.0 = Speed/100) and the summon-only `voodoo_hog`
  (VoodooHog pig: hp 630, dmg 54, hit 1.2s, range 0.75, speed 2.0, ground, buildings-only,
  jumps river, `deployable:false`). The attack's VoodooProjectile carries the curse: on a
  troop hit (IgnoreBuildings → never a tower/building) it tags the victim via the existing
  `curse`/`curse_spawn` entity state (new `curse_on_hit` 5.0s + `curse_spawn:"voodoo_hog"`
  on the card; new `Projectile.curse_ticks`/`curse_spawn` + `curse_add`/`curse_src`
  accumulators through `step_projectiles`/`proj_impact`/`apply_damage`). The cursed unit's
  later death reuses the shared DeathSpawnIsEnemy transform (`curse_spawns.push((1-owner,…))`)
  → exactly one pig (DeathSpawnCount 1) for the Mother Witch's owner. No new stateful
  subsystem: the curse tick-down + death-spawn are the Goblin Curse path. Tests:
  `cursed_death_spawns_pig_for_mother_witch`, `uncursed_death_spawns_no_pig`,
  `voodoo_hog_is_summon_only_building_targeter`, `mother_witch_curse_is_deterministic`.
  `cargo test --release`: 51/51 pass. Commit: c5a43ae
- [x] **R2 — Goblinstein.** Internal `goblinstein` (mana 5 Champion). It deploys as **two
  linked parts** — the big melee **Monster** + the small **Doctor** that periodically zaps /
  revives. Model the champion-pet pairing (e.g. the champion's deploy also spawns its pet via
  the existing deploy-spawn/summon path), each with real stats, and wire its activated
  ability if the data defines one (else `ability` None + documented). Resolve the two parts'
  internal names + stats + the ability from the tables. Add `goblinstein` (+ the pet as a
  summon-only unit). Acceptance: deploying Goblinstein yields both parts on the owner's side;
  one-champion-per-deck still enforced; a test verifies the pairing; determinism guard. If the
  Doctor's revive/zap needs a genuinely new subsystem beyond reasonable scope, implement the
  pairing + combat faithfully and mark the specific sub-mechanic `[~]` with the reason.
  DONE (`characters/goblinstein.toml` + `spells_characters.csv`, L11 = round(base×2.56)).
  The spell row (`Champion`, mana 5, `IsAGroup`) deploys `SummonCharacter goblinstein` (×1,
  primary = the Monster) + `SummonCharacterSecond goblinstein_doctor` (×1). Added:
  - `goblinstein` (the Monster = deck-legal champion body, `champion:true`, 5 elixir): hp 2240,
    dmg 128, hit 1.5s, load 0.7s, range 1.2, mass 1.8, speed 1.0, sight 7.5, ground,
    buildings-only melee. Pairing via `deploy_spawn:{goblinstein_doctor, 1}` (existing mixed-
    deploy path → both parts spawn on the owner's side).
  - `goblinstein_doctor` (summon-only, `deployable:false`): hp 722, dmg 136 (prj 53), hit 1.8s,
    load 1.3s, range 5.5, targets both, homing proj speed 5.0 (Speed/100), `on_hit_freeze 0.5s`
    = the real `buff_goblinstein_doctor` zap-freeze (Speed & HitSpeed −100% for BuffTime 500ms).
  One-champion-per-deck unchanged (the env rule counts `is_champion`; tested that Goblinstein +
  a second champion = 2 → illegal). The Doctor's **zap is its normal ranged attack** (freeze
  projectile, tested). `[~]` DEFERRED sub-mechanic — the **tether/revive activated ability**
  (`[ABILITY.goblinstein_ability]` → `ActionGoblinsteinAbility`: a 3.5s beam tethering Doctor↔
  Monster, `TetherDamage 37` every 0.5s over `TetherWidth 2.0`, plus `DeathAreaEffectData=
  dead_goblinstein` reviving the dead Monster): a genuinely new linked-beam + revive subsystem
  with no analog in the current `AbilityKind` set (cloak/summon/dash/lanebomb/deflect/warp), and
  its numeric `ability_cooldown` is a named stat with no resolved value in the decoded tables
  (same gap as R3). Modeling it would require inventing mechanics, so the card carries no
  `ability` block; a champion with `AbilityKind::None` is handled safely (activate_ability /
  champion_status skip it). Tests: `goblinstein_deploys_monster_plus_doctor`,
  `goblinstein_is_champion_doctor_is_summon_only`, `two_champions_including_goblinstein_is_illegal`,
  `doctor_zap_freezes_the_enemy_it_hits`, `goblinstein_pairing_is_deterministic`.
  `cargo test --release`: 56/56 pass. Commit: 4579925
- [~] **R3 — Real champion ability cooldowns.** DEFERRED — the real numeric cooldowns for
  Mighty Miner / Monk / Little Prince are genuinely absent from the decoded data; kept A1's
  documented approximations (mighty_miner 3.5s, monk 12.0s, little_prince 20.0s). Where I
  looked (all under `/home/clio/projects/clashroyale/client-new/data/`):
  - `csv_logic/character_abilities.csv` — has a `Cooldown` column, but it is EMPTY for every
    real champion ability (`MightyMinerLaneSwitch`, `Deflect`, `ChampGuardianAbility`,
    `GoldenKnightChain`, `ArcherQueenRapid`, `SkeletonKing`); only the `NOTINUSEABILITY*`
    placeholder rows carry `Cooldown=11000`.
  - Each standard champion's TOML `[ABILITY.*]` block has NO inline `Cooldown = <n>` — only
    `StatsTags.Cooldown = "ability_cooldown"`, a NAMED stat reference
    (`characters/monk.toml` `[ABILITY.Deflect]`, `characters/mighty_miner.toml`
    `[ABILITY.MightyMinerLaneSwitch]`, `characters/little_prince.toml`
    `[ABILITY.ChampGuardianAbility]`). The `[STATS.*_ability]` blocks are display-only
    (`Value="ability_cooldown"`, `Unit=TIME_PRECISE`, TID, Icon) and carry no number.
  - `actions.toml` — no cooldown/recharge data at all.
  - Exhaustive grep of the WHOLE data tree (`csv_logic/`, `csv_client/`, `battle_constants.json`,
    `card_catalog.json`): ZERO numeric definitions of `ability_cooldown`; it only ever appears
    as a `StatsTags.Cooldown`/`Value` named-stat reference. `battle_constants.json` has only
    `battle_start_cooldown_ms` (the match-start countdown, unrelated). `spell_stat_types.csv`:
    no cooldown rows.
  - The ONLY champions with an inline numeric `[ABILITY.*] Cooldown` are: **Boss Bandit**
    (`boss_bandit.toml` `Cooldown = 3000` → 3.0s, already real in cards.json ✓), and
    non-standard-ladder VARIANTS/hero-forms that are out of scope per B5 (`megamonk.toml`
    `MegaMonk/MegaDeflect` 20000, `superhogrider.toml` 7000, `ronin.toml` 3500,
    `characters/hero_form/*`). `MegaMonk` shares the Monk art (`BlueExportName="Monk"`) but is a
    distinct `[CHARACTER.MegaMonk]`/`[ABILITY.MegaDeflect]` event variant — using its 20000 for
    the standard Monk would be an unfaithful inference, so it is NOT adopted.
  Conclusion: the standard champions' real cooldowns are resolved by Supercell's runtime balance
  system and are not present in the decoded logic tables, so no corrected value can be sourced.
  Boss Bandit's 3.0s and Goblinstein's deferred tether (R2) are the only data-grounded cases.
  No code change; approximations left intact. Commit: (checklist-only)
- [x] **R4 — pyo3 advisory RUSTSEC-2025-0020 (low). RESOLVED (2026-11-14, supervising session).**
  Bumped `gym/Cargo.toml` to `pyo3 = "0.24"` (resolves `pyo3 0.24.2`) and applied the single
  deprecation fix (`PyDict::new_bound(py)` → `PyDict::new(py)` at `src/env.rs:222`). Nothing else
  needed — the crate already uses the modern `Bound<'_, _>` API across `#[pyclass]`/`#[pymethods]`/
  `#[pymodule]`/`Bound<'py, PyDict>`, stable from 0.22→0.24. Stayed on 0.24 (not 0.30) to keep the
  jump conservative.
  - **This is the validation the round-2 worker could not run.** With the shared venv now usable:
    `cargo build --release` clean (no deprecations), `cargo test --release` 56/56, `maturin develop
    --release` installed the 0.24 extension, and **the Python pytest suite passed 10/10** against it
    (`tests/test_fog.py` fog-of-war guard + `tests/test_determinism.py`). The changed `observe()`
    `PyDict::new` path was also exercised directly at runtime (12-key dict, both `Battle.observe`
    and `PlayerView.observe`).
  - **Determinism:** unaffected (pyo3 is the binding layer; the fixed-point engine is pure Rust).
  - The worker's original deferral was sound at the time (it genuinely could not runtime-validate a
    2-major binding jump and could not confirm the advisory). Completed here because the venv/pytest
    were available. Commit: (see A8/R4 cleanup commit).

---

## Audit log (filled by the supervising session)
Every item independently verified before merge to `main` (pushed). No faked checkmarks.
- **R1** — ran the suite on the branch (51/51); inspected the `mother_witch`/`voodoo_hog`
  cards, the `curse_add`/`curse_src` projectile wiring, and the side-flip test (pig spawns
  for the Mother Witch's owner). Genuine; good reuse of the Goblin Curse state.
- **R2** — verified both parts (`goblinstein` champion body + summon-only
  `goblinstein_doctor`), the `deploy_spawn` pairing, the one-champion-per-deck test, and the
  Doctor's `on_hit_freeze` zap. The `[~]` tether/revive deferral is reasonable (no AbilityKind
  analog); card safely carries no `ability` block.
- **R3** — INDEPENDENTLY CONFIRMED the deferral: the `Cooldown = 20000` the worker could have
  mis-grabbed is in `megamonk.toml` (out-of-scope Super variant), NOT `monk.toml`; the real
  `[ABILITY.*]` blocks for Mighty Miner/Monk/Little Prince carry only
  `Cooldown = "ability_cooldown"` (named stat-ref, no number), and `character_abilities.csv`'s
  Cooldown column is empty for them. Only Boss Bandit has a real inline `3000` (already used).
  The data genuinely lacks these cooldowns — correct deferral.
- **R4** — now COMPLETED (2026-11-14): pyo3 bumped to 0.24.2, validated with the full pytest
  suite (10/10) against the freshly-built extension, plus 56/56 Rust tests and a direct runtime
  check of the changed `observe()` path. The round-2 deferral was well-reasoned for its context
  (no pytest access then); this session had the venv and finished it.
- **Full suite** on merged `main`: 56 Rust tests pass. End-to-end: 132 cards / 116 deployable,
  Mother Witch + Goblinstein deploy/simulate, determinism holds. Shared venv refreshed.
