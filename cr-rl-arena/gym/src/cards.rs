//! Card/tower definitions: load JSON, resolve to fixed-point + tick units once.

use crate::arena::TICKS_PER_SECOND;
use crate::fixed::Fx;
use serde::Deserialize;

pub const DEFAULT_CARDS_JSON: &str = include_str!("../data/cards.json");

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum CardType {
    Troop,
    Building,
    Spell,
    Tower,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Targets {
    Ground,
    Air,
    Both,
}

/// Lingering or applied spell effect, beyond instant damage.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum SpellEffect {
    None,
    Poison,  // damage-over-time zone (enemies)
    Rage,    // speed/attack buff zone (allies)
    Heal,    // heal-over-time zone (allies)
    Freeze,  // area freeze (enemies, duration)
    Slow,    // area slow (enemies, duration)
    Tornado, // [kb] pull enemies toward center over a duration + small damage-over-time
    Spawn,   // [edep] periodically summon units over a radius (Graveyard)
    Clone,   // [curse] duplicate friendly troops in radius at 1 hp (Clone spell)
    Curse,   // [curse] curse enemies in radius: DoT + on-death transform into a unit for the caster
}

impl SpellEffect {
    fn parse(s: &str) -> SpellEffect {
        match s {
            "poison" => SpellEffect::Poison,
            "rage" => SpellEffect::Rage,
            "heal" => SpellEffect::Heal,
            "freeze" => SpellEffect::Freeze,
            "slow" => SpellEffect::Slow,
            "tornado" => SpellEffect::Tornado, // [kb]
            "spawn" => SpellEffect::Spawn, // [edep]
            "clone" => SpellEffect::Clone, // [curse]
            "curse" => SpellEffect::Curse, // [curse]
            _ => SpellEffect::None,
        }
    }
}

/// [champ] A champion's activatable ability, reusing existing engine systems.
///   Cloak    — self becomes untargetable + gains a rage (attack/move) boost.
///   Summon   — spawns N of a unit (e.g. skeletons/guardian) around the champion.
///   Dash     — teleports toward the nearest enemy, damaging a line of enemies.
///   LaneBomb — Mighty Miner: switch to the mirror lane and drop an area
///              bomb (damage + knockback) at the vacated spot.
///   Deflect  — Monk: a timed self damage-reduction window (projectile deflect).
///   Warp     — Boss Bandit: warp a fixed distance toward the enemy side and
///              turn briefly untargetable/invisible.
///   Revive   — Goblinstein: the paired Doctor channels a beam that brings the
///              fallen Monster back to the field. The Doctor is the actor, so the
///              ability works even though the champion (Monster) is dead.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum AbilityKind {
    None,
    Cloak,
    Summon,
    Dash,
    LaneBomb,
    Deflect,
    Warp,
    Revive,
}

impl AbilityKind {
    fn parse(s: &str) -> AbilityKind {
        match s {
            "cloak" => AbilityKind::Cloak,
            "summon" => AbilityKind::Summon,
            "dash" => AbilityKind::Dash,
            "lanebomb" => AbilityKind::LaneBomb,
            "deflect" => AbilityKind::Deflect,
            "warp" => AbilityKind::Warp,
            "revive" => AbilityKind::Revive,
            _ => AbilityKind::None,
        }
    }
}

impl Targets {
    fn parse(s: &str) -> Targets {
        match s {
            "air" => Targets::Air,
            "both" => Targets::Both,
            _ => Targets::Ground,
        }
    }
    /// Can an attacker with `self` hit a (flying?) victim?
    #[inline]
    pub fn can_hit(self, victim_flying: bool) -> bool {
        match self {
            Targets::Both => true,
            Targets::Air => victim_flying,
            Targets::Ground => !victim_flying,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Charge {
    pub min_distance: Fx,
    pub speed_mult: Fx,
    pub damage_mult: i32, // integer multiplier (2x)
}

/// Fully resolved, hot-loop-ready card definition.
#[derive(Clone, Debug)]
pub struct CardDef {
    pub name: String,
    pub ctype: CardType,
    pub elixir: i32,
    pub hp: i32,
    pub damage: i32,
    pub hit_ticks: i32,
    pub load_ticks: i32, // delay from entering range to the FIRST hit landing
    pub range: Fx,
    pub sight: Fx,
    pub radius: Fx,
    pub mass: Fx,  // push weight: heavier bodies move less in a collision
    pub speed: Fx, // tiles per tick
    pub targets: Targets,
    pub count: i32,
    pub flying: bool,
    pub splash: Fx,
    pub proj_speed: Fx, // tiles per tick, 0 = instant
    pub buildings_only: bool,
    pub invisible: bool, // [inv] permanently invisible (Royal Ghost); untargetable unless revealed
    pub jumps_river: bool,
    pub lifetime_ticks: i32, // -1 = infinite
    pub spell_radius: Fx,
    pub crown_pct: i32,
    pub stun_ticks: i32,
    // [kb] knockback & pull
    pub knockback: Fx,   // [kb] push distance (tiles) this card's attack/spell impact applies
    pub roll_range: Fx,  // [kb] travel distance (tiles) of a rolling-line projectile (0 = not rolling)
    // [shot] Hunter shotgun pellets: effective shot damage = per-hit x pellets-that-connect,
    // which is `pellets` point-blank and falls to 1 at max range. 1 = ordinary single shot.
    pub pellets: i32,
    // [shot] Firecracker self-recoil (tiles) applied to the shooter each time it fires.
    pub recoil: Fx,
    // [heal] Battle Healer aura: heal `power` hp to friendly troops (incl. self) within
    // `heal_aura_radius` every `heal_aura_interval` ticks. power 0 = no aura.
    pub heal_aura_power: i32,
    pub heal_aura_radius: Fx,
    pub heal_aura_interval: i32,
    pub charge: Option<Charge>,
    // [charge] Dash / jump (leap) variants: Bandit dash, Mega Knight jump.
    pub dash_min: Fx,            // target must be at least this far to trigger a leap
    pub dash_max: Fx,            // ...and at most this far
    pub dash_speed: Fx,          // tiles per tick while leaping (0 = no dash)
    pub dash_invuln: bool,       // untargetable/invulnerable mid-leap (Bandit)
    pub dash_damage_mult: i32,   // single-target strike multiplier on arrival (Bandit 2x)
    pub dash_cooldown_ticks: i32,// ticks between leaps (Mega Knight periodic jump)
    pub land_damage: i32,        // area damage dealt on deploy AND on leap landing (Mega Knight)
    pub land_radius: Fx,         // radius of that landing/deploy area damage
    // [charge] On-hit melee riders (Ram Rider snare, Battle Ram knockback + deploy-on-connect)
    pub snare_ticks: i32,        // apply this many ticks of snare (reuses slow) to the hit target
    pub knockback_tiles: Fx,     // push the hit target back this far
    pub dies_on_hit: bool,       // self-destruct on landing a hit (Battle Ram -> death-spawn)
    // [charge] On-death area effect (Lumberjack drops a Rage zone)
    pub death_effect: SpellEffect,
    pub death_effect_ticks: i32,
    pub death_effect_radius: Fx,
    pub death_effect_power: i32,
    pub crown_value: i32, // towers: crowns awarded when destroyed
    pub starts_dormant: bool,
    pub deployable: bool,  // false = summoned only (golemite, hut spawns), not deck-legal
    pub deploy_anywhere: bool, // [edep] placeable on either side (Miner, Goblin Drill)
    pub deploy_ticks: i32, // time from placement to becoming active
    pub shield: i32,       // starting shield hp absorbed before body hp
    // spawner building: periodically produces `spawn_count` of `spawn_name`
    pub spawn_count: i32,
    pub spawn_interval_ticks: i32,
    pub spawn_name: Option<String>,
    pub spawn_id: Option<usize>,
    // on death, spawn `death_count` of `death_name` at this unit's position
    pub death_count: i32,
    pub death_name: Option<String>,
    pub death_id: Option<usize>,
    // [mix] on DEPLOY, also spawn `deploy_spawn_count` of `deploy_spawn_name` beside the
    // primary cluster -- for mixed-composition cards (Goblin Gang, Rascals). Linked name->id.
    pub deploy_spawn_count: i32,
    pub deploy_spawn_name: Option<String>,
    pub deploy_spawn_id: Option<usize>,
    // [curse] Goblin Curse / Mother Witch: the unit a cursed enemy becomes (for the
    // caster/attacker) when it dies.
    pub curse_spawn_name: Option<String>,
    pub curse_spawn_id: Option<usize>,
    // [curse] Mother Witch VoodooCurse: this unit's ATTACK curses the victim for this
    // many ticks (0 = no on-hit curse). On the cursed victim's later death it spawns
    // one `curse_spawn` unit for this unit's owner (DeathSpawnIsEnemy). 0 for all
    // other cards -> only the curse-on-hit carrier (Mother Witch) applies it.
    pub curse_ticks: i32,
    // [rev] revive-on-death: when this unit dies from lifetime expiry, hatch one
    // `revive_name`/`revive_as` at `revive_hp_pct`% of that card's hp, exactly once
    // (used by the Phoenix egg -> reborn Phoenix). Linked name->id in the post-load pass.
    pub revive_name: Option<String>,
    pub revive_as: Option<usize>,
    pub revive_hp_pct: i32,
    // [edep] on-death area burst damage (Goblin Drill)
    pub death_damage: i32,
    pub death_radius: Fx,
    // spell lingering/applied effect
    pub effect: SpellEffect,
    pub effect_ticks: i32,    // duration
    pub effect_interval: i32, // ticks between DoT/heal applications
    pub effect_power: i32,    // damage or heal per application
    // [proj] --- projectile-behavior extensions ---
    pub commit_ground: bool,      // [proj] lobbed/non-homing: shot flies to a fixed point (dodgeable)
    pub chain_count: i32,         // [proj] extra enemies a hit arcs to (Electro Wizard/Spirit)
    pub chain_radius: Fx,         // [proj] max chain jump distance
    pub pierce: bool,             // [proj] shot pierces every enemy along a line (Magic Archer)
    pub line_range: Fx,           // [proj] distance a pierce shot travels, per leg
    pub boomerang: bool,          // [proj] pierce shot flies out then returns (Executioner)
    pub on_hit_slow_ticks: i32,   // [proj] a landed troop hit slows the victim (Ice Wizard)
    pub on_hit_freeze_ticks: i32, // [proj] a landed troop hit stuns/freezes the victim (Ice Spirit, Electro)
    pub spell_max_targets: i32,   // [proj] spell strikes only the K highest-HP enemies (Lightning)
    // [evo] evolution link: a base card charges by being cycled `evo_cycles`
    // times; the next play then spawns `evolved_id`'s def and resets the count.
    // (Evo Royal Giant's knockback shots reuse the shared [kb] `knockback` field above.)
    pub evolved_name: Option<String>, // [evo]
    pub evolved_id: Option<usize>,    // [evo]
    pub evo_cycles: i32,              // [evo] cycles to charge (0 = not an evolution)
    // [ramp] ramp-up / charge-shot / siege fields
    pub ramp_damage: Vec<i32>,   // per-stage per-hit damage while locked on ONE target (empty = no ramp)
    pub ramp_stage_ticks: i32,   // ticks of continuous lock before advancing one ramp stage
    pub charge_shot_ticks: i32,  // reload/charge time for a charge-shot weapon (Sparky); 0 = normal
    pub min_range: Fx,           // dead zone: cannot target/hit anything closer than this (Mortar); 0 = none
    pub prefers_buildings: bool, // soft building/tower target priority on acquisition (X-Bow)
    // [rfl] Reflect (Electro Giant): when hit by an attacker inside reflect_radius,
    // zap it back for reflect_damage + reflect_stun_ticks stun, at most once per
    // reflect_interval_ticks. All default 0 => no reflect.
    pub reflect_damage: i32,
    pub reflect_radius: Fx,
    pub reflect_stun_ticks: i32,
    pub reflect_interval_ticks: i32,
    // [rfl] Pull (Fisherman): on each landed hit, hook pulls the target toward this
    // unit by pull_tiles (or pulls this unit toward the target when it's a
    // building/tower). Default 0 => no pull.
    pub pull_tiles: Fx,
    // [eco] economy building (Elixir Collector/Pump): periodically grants its
    // owner elixir instead of spawning a unit. 0 = not an elixir producer.
    pub elixir_per_pulse: i32,
    pub elixir_pulse_ticks: i32,
    // [eco] kamikaze: lands its (splash + stun) hit once on contact, then dies
    // (Fire/Ice/Electro Spirit, Wall Breakers).
    pub suicide: bool,
    // [eco] Mirror: on play, replays the owner's LAST-deployed card at +1 elixir.
    pub is_mirror: bool,
    // [champ] champion troop + activatable ability spec
    pub is_champion: bool,
    pub ability: AbilityKind,
    pub ability_cost: i32,            // elixir to activate
    pub ability_cooldown_ticks: i32, // reuse delay after activation
    pub ability_duration_ticks: i32, // Cloak: untargetable/boost duration
    pub ability_damage: i32,         // Dash: damage per enemy in the line
    pub ability_count: i32,          // Summon: number of units spawned
    pub ability_radius: Fx,          // Dash: line hit radius / Summon: spread / LaneBomb: blast radius
    pub ability_range: Fx,           // Dash: max dash reach / Warp: warp distance (tiles)
    pub ability_knockback: Fx,       // LaneBomb: push distance applied to enemies in the blast
    pub ability_reduction: i32,      // Deflect: % incoming-damage reduction while active (0-100)
    pub ability_spawn_name: Option<String>, // Summon: unit to spawn
    pub ability_spawn_id: Option<usize>,
    // [M2] explicit homing override; None = engine default (splash => commit-to-ground).
    pub homing: Option<bool>,
}

// ---- raw JSON shapes ----

#[derive(Deserialize, Default)]
struct RawCharge {
    min_distance: f64,
    speed_mult: f64,
    damage_mult: f64,
}

// [charge] Dash / jump config block.
#[derive(Deserialize, Default)]
struct RawDash {
    min: f64,
    max: f64,
    speed: f64,             // tiles per second
    invuln: Option<bool>,
    damage_mult: Option<f64>,
    cooldown: Option<f64>,  // seconds between leaps
    land_damage: Option<i64>,
    land_radius: Option<f64>,
}

// [charge] On-death area effect (Lumberjack Rage).
#[derive(Deserialize, Default)]
struct RawDeathArea {
    effect: String,
    radius: Option<f64>,
    duration: Option<f64>,  // seconds
    power: Option<i64>,
}

#[derive(Deserialize, Default)]
struct RawSpawn {
    card: String,
    count: Option<i64>,
    interval: Option<f64>,
}

// [heal] Battle Healer continuous heal aura: heals friendly troops (incl. self)
// within `radius` by `power` hp every `interval` seconds while alive.
#[derive(Deserialize, Default)]
struct RawHealAura {
    power: Option<i64>,
    radius: Option<f64>,
    interval: Option<f64>, // seconds between heal pulses
}

#[derive(Deserialize, Default)]
struct RawDeath {
    card: String,
    count: Option<i64>,
}

// [rev] revive spec: hatch `card` at `hp_pct`% hp on lifetime-expiry death (one-shot).
#[derive(Deserialize, Default)]
struct RawRevive {
    card: String,
    hp_pct: Option<i64>,
}

// [champ] raw champion ability spec
#[derive(Deserialize, Default)]
struct RawAbility {
    kind: String,
    cost: Option<i64>,
    cooldown: Option<f64>, // seconds
    duration: Option<f64>, // seconds (Cloak)
    damage: Option<i64>,   // Dash
    count: Option<i64>,    // Summon
    summon: Option<String>,// Summon unit name
    range: Option<f64>,    // Dash reach / Warp distance (tiles)
    radius: Option<f64>,   // Dash line radius / Summon spread / LaneBomb blast radius (tiles)
    knockback: Option<f64>,// LaneBomb pushback distance (tiles)
    reduction: Option<i64>,// Deflect % damage reduction (0-100)
}

#[derive(Deserialize, Default)]
struct RawCard {
    elixir: Option<i64>,
    #[serde(rename = "type")]
    ctype: Option<String>,
    hp: Option<i64>,
    damage: Option<i64>,
    hit_speed: Option<f64>,
    load_time: Option<f64>,
    range: Option<f64>,
    sight: Option<f64>,
    speed: Option<f64>,
    collision_radius: Option<f64>,
    mass: Option<f64>,
    targets: Option<String>,
    count: Option<i64>,
    flying: Option<bool>,
    splash_radius: Option<f64>,
    projectile_speed: Option<f64>,
    target_buildings_only: Option<bool>,
    invisible: Option<bool>, // [inv]
    jumps_river: Option<bool>,
    lifetime: Option<f64>,
    radius: Option<f64>,
    crown_tower_damage_pct: Option<i64>,
    stun: Option<f64>,
    knockback: Option<f64>,   // [kb] push distance in tiles
    pierce: Option<bool>,     // [kb] rolling-pierce attack/spell
    roll_range: Option<f64>,  // [kb] rolling-line travel distance in tiles
    // [shot] Hunter shotgun: number of pellets fired per shot; effective damage
    // scales with how many connect (all at point-blank, few at max range).
    pellets: Option<i64>,
    // [shot] Firecracker: self-recoil distance (tiles) the shooter jumps backward on firing.
    recoil: Option<f64>,
    // [heal] Battle Healer continuous heal aura.
    heal_aura: Option<RawHealAura>,
    charge: Option<RawCharge>,
    // [charge] new mechanic inputs (all optional -> existing cards still load)
    // (melee knockback reuses the shared [kb] `knockback` JSON key above)
    dash: Option<RawDash>,
    snare: Option<f64>,       // seconds of snare applied on hit
    dies_on_hit: Option<bool>,
    death_area: Option<RawDeathArea>,
    starts_dormant: Option<bool>,
    deploy_time: Option<f64>,
    shield: Option<i64>,
    spawn: Option<RawSpawn>,
    death_spawn: Option<RawDeath>,
    deploy_spawn: Option<RawSpawn>, // [mix] secondary units spawned on deploy (reuses card/count)
    curse_spawn: Option<String>,    // [curse] unit a cursed enemy becomes on death (Goblin Curse / Mother Witch)
    curse_on_hit: Option<f64>,      // [curse] Mother Witch: seconds of curse applied by this unit's attack
    revive: Option<RawRevive>, // [rev]
    death_damage: Option<i64>,  // [edep]
    death_radius: Option<f64>,  // [edep]
    effect: Option<String>,
    effect_duration: Option<f64>,
    effect_interval: Option<f64>,
    effect_power: Option<i64>,
    deployable: Option<bool>,
    // [proj] projectile-behavior extensions (all optional; defaults keep old cards intact)
    commit_ground: Option<bool>,
    // [M2] explicit per-card homing override (real CR `Homing` flag). When present
    // it wins; when absent the engine's splash-based default applies (single-target
    // "tracking" shots home; splash/area shots commit to a ground point = dodgeable).
    homing: Option<bool>,
    chain_count: Option<i64>,
    chain_radius: Option<f64>,
    line_range: Option<f64>,
    boomerang: Option<bool>,
    on_hit_slow: Option<f64>,   // seconds
    on_hit_freeze: Option<f64>, // seconds
    spell_max_targets: Option<i64>,
    evolved: Option<String>, // [evo] name of this card's evolved variant
    evo_cycles: Option<i64>, // [evo] cycles required to charge the evolution
    // [ramp] ramp-up / charge-shot / siege fields
    ramp_damage: Option<Vec<i64>>, // per-stage per-hit damage (Inferno)
    ramp_stage_time: Option<f64>,  // seconds per ramp stage
    charge_time: Option<f64>,      // seconds to charge a charge-shot (Sparky)
    min_range: Option<f64>,        // dead-zone min range in tiles (Mortar)
    prefers_buildings: Option<bool>, // building/tower target priority (X-Bow)
    // [rfl] reflect (Electro Giant)
    reflect_damage: Option<i64>,
    reflect_radius: Option<f64>,
    reflect_stun: Option<f64>,     // seconds
    reflect_interval: Option<f64>, // seconds
    // [rfl] pull (Fisherman)
    pull_distance: Option<f64>,    // tiles
    deploy_anywhere: Option<bool>, // [edep]
    // [eco] economy building: elixir granted per pulse, and seconds between pulses
    elixir_per_pulse: Option<i64>,
    elixir_pulse_interval: Option<f64>,
    // [eco] kamikaze unit: one on-contact hit, then die
    suicide: Option<bool>,
    // [eco] Mirror card marker
    mirror: Option<bool>,
    // [champ]
    champion: Option<bool>,
    ability: Option<RawAbility>,
}

#[derive(Deserialize)]
struct RawFile {
    cards: std::collections::BTreeMap<String, RawCard>,
    towers: std::collections::BTreeMap<String, RawCard>,
}

fn secs_to_ticks(s: f64) -> i32 {
    ((s * TICKS_PER_SECOND as f64).round() as i32).max(0)
}

fn per_tick(tiles_per_sec: f64) -> Fx {
    Fx::from_f64(tiles_per_sec / TICKS_PER_SECOND as f64)
}

fn resolve(name: &str, r: &RawCard, forced: Option<CardType>) -> CardDef {
    let ctype = forced.unwrap_or_else(|| match r.ctype.as_deref() {
        Some("spell") => CardType::Spell,
        Some("building") => CardType::Building,
        _ => CardType::Troop,
    });
    let charge = r.charge.as_ref().map(|c| Charge {
        min_distance: Fx::from_f64(c.min_distance),
        speed_mult: Fx::from_f64(c.speed_mult),
        damage_mult: c.damage_mult.round() as i32,
    });
    let lifetime = r.lifetime.unwrap_or(0.0);
    // [charge] resolve dash / jump block (tiles/s -> tiles/tick, s -> ticks)
    let dash = r.dash.as_ref();
    let dash_speed = dash.map(|c| per_tick(c.speed)).unwrap_or(Fx(0));
    let dash_min = dash.map(|c| Fx::from_f64(c.min)).unwrap_or(Fx(0));
    let dash_max = dash.map(|c| Fx::from_f64(c.max)).unwrap_or(Fx(0));
    let dash_invuln = dash.and_then(|c| c.invuln).unwrap_or(false);
    let dash_damage_mult = dash.and_then(|c| c.damage_mult).map(|m| m.round() as i32).unwrap_or(1).max(1);
    let dash_cooldown_ticks = dash.and_then(|c| c.cooldown).map(secs_to_ticks).unwrap_or(0);
    let land_damage = dash.and_then(|c| c.land_damage).unwrap_or(0) as i32;
    let land_radius = Fx::from_f64(dash.and_then(|c| c.land_radius).unwrap_or(0.0));
    // [charge] death-area effect (Lumberjack Rage drop)
    let da = r.death_area.as_ref();
    let death_effect = da.map(|a| SpellEffect::parse(&a.effect)).unwrap_or(SpellEffect::None);
    let death_effect_ticks = da.and_then(|a| a.duration).map(secs_to_ticks).unwrap_or(0);
    let death_effect_radius = Fx::from_f64(da.and_then(|a| a.radius).unwrap_or(0.0));
    let death_effect_power = da.and_then(|a| a.power).unwrap_or(0) as i32;
    // [champ] resolve the ability spec (seconds -> ticks; names linked later)
    let (ab_kind, ab_cost, ab_cd, ab_dur, ab_dmg, ab_count, ab_radius, ab_range, ab_spawn) =
        match r.ability.as_ref() {
            Some(a) => (
                AbilityKind::parse(&a.kind),
                a.cost.unwrap_or(0) as i32,
                a.cooldown.map(secs_to_ticks).unwrap_or(0),
                a.duration.map(secs_to_ticks).unwrap_or(0),
                a.damage.unwrap_or(0) as i32,
                a.count.unwrap_or(1).max(1) as i32,
                Fx::from_f64(a.radius.unwrap_or(1.0)),
                Fx::from_f64(a.range.unwrap_or(0.0)),
                a.summon.clone(),
            ),
            None => (AbilityKind::None, 0, 0, 0, 0, 1, Fx::from_f64(1.0), Fx(0), None),
        };
    // [champ] extra ability params (LaneBomb knockback, Deflect reduction); 0 by default
    let ab_knockback = Fx::from_f64(r.ability.as_ref().and_then(|a| a.knockback).unwrap_or(0.0));
    let ab_reduction = r.ability.as_ref().and_then(|a| a.reduction).unwrap_or(0).clamp(0, 100) as i32;
    CardDef {
        name: name.to_string(),
        ctype,
        elixir: r.elixir.unwrap_or(0) as i32,
        hp: r.hp.unwrap_or(0) as i32,
        damage: r.damage.unwrap_or(0) as i32,
        hit_ticks: r.hit_speed.map(secs_to_ticks).unwrap_or(0).max(1),
        load_ticks: r
            .load_time
            .map(secs_to_ticks)
            .unwrap_or(TICKS_PER_SECOND as i32 / 5)
            .max(1),
        range: Fx::from_f64(r.range.unwrap_or(0.0)),
        sight: Fx::from_f64(r.sight.unwrap_or(5.5)),
        radius: Fx::from_f64(r.collision_radius.unwrap_or(0.5)),
        mass: Fx::from_f64(r.mass.unwrap_or_else(|| r.collision_radius.unwrap_or(0.5))),
        speed: per_tick(r.speed.unwrap_or(0.0)),
        targets: Targets::parse(r.targets.as_deref().unwrap_or("ground")),
        count: r.count.unwrap_or(1).max(1) as i32,
        flying: r.flying.unwrap_or(false),
        splash: Fx::from_f64(r.splash_radius.unwrap_or(0.0)),
        proj_speed: per_tick(r.projectile_speed.unwrap_or(0.0)),
        buildings_only: r.target_buildings_only.unwrap_or(false),
        invisible: r.invisible.unwrap_or(false), // [inv]
        jumps_river: r.jumps_river.unwrap_or(false),
        lifetime_ticks: if lifetime > 0.0 { secs_to_ticks(lifetime) } else { -1 },
        spell_radius: Fx::from_f64(r.radius.unwrap_or(0.0)),
        crown_pct: r.crown_tower_damage_pct.unwrap_or(100) as i32,
        stun_ticks: r.stun.map(secs_to_ticks).unwrap_or(0),
        knockback: Fx::from_f64(r.knockback.unwrap_or(0.0)), // [kb]
        pierce: r.pierce.unwrap_or(false),                   // [kb]
        roll_range: Fx::from_f64(r.roll_range.unwrap_or(0.0)), // [kb]
        pellets: r.pellets.unwrap_or(1).max(1) as i32,         // [shot]
        recoil: Fx::from_f64(r.recoil.unwrap_or(0.0)),         // [shot]
        // [heal] Battle Healer aura (default power 0 => every other card unaffected)
        heal_aura_power: r.heal_aura.as_ref().and_then(|h| h.power).unwrap_or(0) as i32,
        heal_aura_radius: Fx::from_f64(r.heal_aura.as_ref().and_then(|h| h.radius).unwrap_or(0.0)),
        heal_aura_interval: r
            .heal_aura
            .as_ref()
            .and_then(|h| h.interval)
            .map(secs_to_ticks)
            .unwrap_or(TICKS_PER_SECOND as i32 / 4),
        charge,
        // [charge] new mechanic fields
        dash_min,
        dash_max,
        dash_speed,
        dash_invuln,
        dash_damage_mult,
        dash_cooldown_ticks,
        land_damage,
        land_radius,
        snare_ticks: r.snare.map(secs_to_ticks).unwrap_or(0),
        knockback_tiles: Fx::from_f64(r.knockback.unwrap_or(0.0)),
        dies_on_hit: r.dies_on_hit.unwrap_or(false),
        death_effect,
        death_effect_ticks,
        death_effect_radius,
        death_effect_power,
        crown_value: 0,
        starts_dormant: r.starts_dormant.unwrap_or(false),
        deployable: r.deployable.unwrap_or(true),
        deploy_anywhere: r.deploy_anywhere.unwrap_or(false), // [edep]
        // [M4] per-card deploy time; cards with no `deploy_time` fall back to the
        // engine's named flat constant (1.0s) rather than a bare magic number.
        deploy_ticks: r.deploy_time.map(secs_to_ticks).unwrap_or(crate::arena::DEPLOY_TICKS),
        shield: r.shield.unwrap_or(0) as i32,
        spawn_count: r.spawn.as_ref().and_then(|s| s.count).unwrap_or(1) as i32,
        spawn_interval_ticks: r
            .spawn
            .as_ref()
            .and_then(|s| s.interval)
            .map(secs_to_ticks)
            .unwrap_or(0),
        spawn_name: r.spawn.as_ref().map(|s| s.card.clone()),
        spawn_id: None,
        death_count: r.death_spawn.as_ref().and_then(|s| s.count).unwrap_or(1) as i32,
        death_name: r.death_spawn.as_ref().map(|s| s.card.clone()),
        death_id: None,
        // [mix] secondary deploy-spawn (mixed-composition cards)
        deploy_spawn_count: r.deploy_spawn.as_ref().and_then(|s| s.count).unwrap_or(1).max(1) as i32,
        deploy_spawn_name: r.deploy_spawn.as_ref().map(|s| s.card.clone()),
        deploy_spawn_id: None,
        // [curse] curse transform target (linked name->id in the post-load pass)
        curse_spawn_name: r.curse_spawn.clone(),
        curse_spawn_id: None,
        // [curse] Mother Witch on-hit curse duration (seconds -> ticks)
        curse_ticks: r.curse_on_hit.map(secs_to_ticks).unwrap_or(0),
        // [rev] revive spec (resolved to id in the post-load linking pass below)
        revive_name: r.revive.as_ref().map(|s| s.card.clone()),
        revive_as: None,
        revive_hp_pct: r.revive.as_ref().and_then(|s| s.hp_pct).unwrap_or(100) as i32,
        death_damage: r.death_damage.unwrap_or(0) as i32, // [edep]
        death_radius: Fx::from_f64(r.death_radius.unwrap_or(0.0)), // [edep]
        effect: r.effect.as_deref().map(SpellEffect::parse).unwrap_or(SpellEffect::None),
        effect_ticks: r.effect_duration.map(secs_to_ticks).unwrap_or(0),
        effect_interval: r.effect_interval.map(secs_to_ticks).unwrap_or(TICKS_PER_SECOND as i32),
        effect_power: r.effect_power.unwrap_or(0) as i32,
        // [proj] projectile-behavior extensions
        commit_ground: r.commit_ground.unwrap_or(false),
        chain_count: r.chain_count.unwrap_or(0).max(0) as i32,
        chain_radius: Fx::from_f64(r.chain_radius.unwrap_or(3.0)),
        line_range: Fx::from_f64(r.line_range.unwrap_or(0.0)),
        boomerang: r.boomerang.unwrap_or(false),
        on_hit_slow_ticks: r.on_hit_slow.map(secs_to_ticks).unwrap_or(0),
        on_hit_freeze_ticks: r.on_hit_freeze.map(secs_to_ticks).unwrap_or(0),
        spell_max_targets: r.spell_max_targets.unwrap_or(0).max(0) as i32,
        evolved_name: r.evolved.clone(), // [evo]
        evolved_id: None,                // [evo] linked after all names are indexed
        evo_cycles: r.evo_cycles.unwrap_or(0) as i32, // [evo]
        // [ramp] ramp-up / charge-shot / siege fields
        ramp_damage: r
            .ramp_damage
            .as_ref()
            .map(|v| v.iter().map(|&x| x as i32).collect())
            .unwrap_or_default(),
        ramp_stage_ticks: r.ramp_stage_time.map(secs_to_ticks).unwrap_or(0),
        charge_shot_ticks: r.charge_time.map(secs_to_ticks).unwrap_or(0),
        min_range: Fx::from_f64(r.min_range.unwrap_or(0.0)),
        prefers_buildings: r.prefers_buildings.unwrap_or(false),
        // [rfl] reflect: default 0 (no reflect) so every existing card loads unchanged.
        reflect_damage: r.reflect_damage.unwrap_or(0) as i32,
        reflect_radius: Fx::from_f64(r.reflect_radius.unwrap_or(0.0)),
        reflect_stun_ticks: r.reflect_stun.map(secs_to_ticks).unwrap_or(0),
        // default a half-second pulse interval when a reflecter omits it.
        reflect_interval_ticks: r
            .reflect_interval
            .map(secs_to_ticks)
            .unwrap_or(TICKS_PER_SECOND as i32 / 2),
        // [rfl] pull: default 0 (no pull).
        pull_tiles: Fx::from_f64(r.pull_distance.unwrap_or(0.0)),
        // [eco] economy + suicide + mirror fields (default 0/false => unchanged behavior)
        elixir_per_pulse: r.elixir_per_pulse.unwrap_or(0) as i32,
        elixir_pulse_ticks: r.elixir_pulse_interval.map(secs_to_ticks).unwrap_or(0),
        suicide: r.suicide.unwrap_or(false),
        is_mirror: r.mirror.unwrap_or(false),
        // [champ]
        is_champion: r.champion.unwrap_or(false),
        ability: ab_kind,
        ability_cost: ab_cost,
        ability_cooldown_ticks: ab_cd,
        ability_duration_ticks: ab_dur,
        ability_damage: ab_dmg,
        ability_count: ab_count,
        ability_radius: ab_radius,
        ability_range: ab_range,
        ability_knockback: ab_knockback,
        ability_reduction: ab_reduction,
        ability_spawn_name: ab_spawn,
        ability_spawn_id: None,
        homing: r.homing, // [M2]
    }
}

/// Resolved library: deployable cards plus the two tower defs, in one table.
#[derive(Clone)]
pub struct Library {
    pub defs: Vec<CardDef>,          // index = def id
    pub index: std::collections::HashMap<String, usize>,
    pub deployable: Vec<usize>,      // def ids a player may put in a deck
    pub princess_tower: usize,
    pub king_tower: usize,
}

impl Library {
    pub fn from_json(s: &str) -> Result<Library, String> {
        let raw: RawFile = serde_json::from_str(s).map_err(|e| e.to_string())?;
        let mut defs = Vec::new();
        let mut index = std::collections::HashMap::new();
        let mut deployable = Vec::new();
        for (name, rc) in &raw.cards {
            let id = defs.len();
            let def = resolve(name, rc, None);
            let is_deployable = def.deployable;
            defs.push(def);
            index.insert(name.clone(), id);
            if is_deployable {
                deployable.push(id);
            }
        }
        let mut princess_tower = usize::MAX;
        let mut king_tower = usize::MAX;
        for (name, rc) in &raw.towers {
            let id = defs.len();
            let mut d = resolve(name, rc, Some(CardType::Tower));
            d.crown_value = if name == "king_tower" { 3 } else { 1 };
            if name == "king_tower" {
                king_tower = id;
            } else if name == "princess_tower" {
                princess_tower = id;
            }
            defs.push(d);
            index.insert(name.clone(), id);
        }
        if princess_tower == usize::MAX || king_tower == usize::MAX {
            return Err("cards.json towers must define princess_tower and king_tower".into());
        }
        // Link inter-card references now that every name is in the index.
        for i in 0..defs.len() {
            if let Some(n) = defs[i].spawn_name.clone() {
                defs[i].spawn_id = index.get(&n).copied();
            }
            if let Some(n) = defs[i].death_name.clone() {
                defs[i].death_id = index.get(&n).copied();
            }
            // [mix] link the secondary deploy-spawn (Goblin Gang / Rascals)
            if let Some(n) = defs[i].deploy_spawn_name.clone() {
                defs[i].deploy_spawn_id = index.get(&n).copied();
            }
            // [curse] link the curse-transform target (Goblin Curse -> goblin)
            if let Some(n) = defs[i].curse_spawn_name.clone() {
                defs[i].curse_spawn_id = index.get(&n).copied();
            }
            // [evo] resolve the evolved-variant name to its def id
            if let Some(n) = defs[i].evolved_name.clone() {
                defs[i].evolved_id = index.get(&n).copied();
            }
            // [rev] link revive target the same way (name -> id)
            if let Some(n) = defs[i].revive_name.clone() {
                defs[i].revive_as = index.get(&n).copied();
            }
            // [champ] link the champion summon target
            if let Some(n) = defs[i].ability_spawn_name.clone() {
                defs[i].ability_spawn_id = index.get(&n).copied();
            }
        }
        Ok(Library { defs, index, deployable, princess_tower, king_tower })
    }

    pub fn default_lib() -> Library {
        Library::from_json(DEFAULT_CARDS_JSON).expect("bundled cards.json is valid")
    }

    pub fn id_of(&self, name: &str) -> Option<usize> {
        self.index.get(name).copied()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bundled_loads() {
        let lib = Library::default_lib();
        assert!(lib.deployable.len() >= 15, "cards {}", lib.deployable.len());
        assert!(lib.id_of("knight").is_some());
        let k = &lib.defs[lib.id_of("knight").unwrap()];
        assert_eq!(k.elixir, 3);
        assert!(k.hit_ticks > 0);
        // king tower resolved with 3 crowns
        assert_eq!(lib.defs[lib.king_tower].crown_value, 3);
    }
}
