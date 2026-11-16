//! Runtime entities: troops, buildings, and towers on the field.
//! Projectiles are tracked separately in the engine (see engine.rs).

use crate::fixed::{Fx, V2};

#[derive(Clone)]
pub struct Entity {
    pub id: u32,
    pub owner: u8,      // 0 or 1
    pub def: usize,     // index into Library.defs
    pub pos: V2,
    pub half: V2,       // box half-extents for towers; zero => circle hitbox (radius from def)
    pub hp: i32,
    pub max_hp: i32,
    pub target: Option<u32>,
    pub cooldown: i32,  // ticks until able to attack again
    pub deploy: i32,    // ticks until active (0 = active)
    pub lifetime: i32,  // ticks remaining (-1 = infinite)
    pub stun: i32,      // ticks of stun/freeze remaining (can't move or attack)
    pub slow: i32,      // ticks slowed (reduced move + attack speed)
    pub rage: i32,      // ticks raged (increased move + attack speed)
    pub shield_hp: i32, // absorbs damage before hp (Dark Prince, Guards, Recruits)
    pub reveal: i32,    // [inv] ticks an invisible unit stays targetable after attacking (0 = hidden)
    pub spawn_timer: i32, // ticks until this spawner building produces units
    pub reflect_cd: i32,// [rfl] ticks until this unit may emit a reflect pulse again (Electro Giant)
    pub ability_cd: i32,  // [champ] ticks until champion ability usable again (0 = ready)
    pub cloak: i32,       // [champ] ticks of untargetability remaining (Cloak ability)
    pub deflect: i32,     // [champ] ticks of damage-reduction remaining (Monk Deflect ability)
    pub curse: i32,       // [curse] ticks of curse remaining (Goblin Curse): on death, transform
    pub curse_spawn: i32, // [curse] def id to spawn FOR THE OPPONENT on a cursed death (-1 = none)
    pub charge_dist: Fx,// distance moved toward target unobstructed (prince)
    pub dash: i32,      // [charge] ticks remaining in current leap (0 = not leaping)
    pub dash_cd: i32,   // [charge] ticks until the next leap is allowed
    pub ramp_timer: i32,  // [ramp] ticks locked+attacking the same ramp target (Inferno); resets on retarget/stun
    pub ramp_target: u32, // [ramp] id currently being ramped on (0 = none)
    pub charge_shot: i32, // [ramp] accumulated charge toward a charge-shot (Sparky); reset by stun
    pub is_tower: bool,
    pub is_king: bool,
    pub activated: bool,// king tower: starts dormant until activated
    pub engaged: bool,  // in attack range of its target last tick (drives wind-up)
    pub revived: bool,  // [rev] a reborn unit (Phoenix): suppresses its own death-spawn & revive (one-shot)
    pub hatch: bool,    // [rev] died via lifetime expiry this tick -> eligible to hatch its revive
    pub dead: bool,
}

impl Entity {
    #[inline]
    pub fn active(&self) -> bool {
        self.deploy <= 0 && !self.dead
    }
    #[inline]
    pub fn alive(&self) -> bool {
        !self.dead && self.hp > 0
    }
}

/// An in-flight projectile (ranged attack or spell delivery).
///
/// Behavior is data-driven by the fields below; everything added for the
/// projectile-behavior mechanics (chain / pierce / commit-to-ground / on-hit
/// slow / top-K) defaults to the plain "homing single-or-splash shot" so that
/// existing call sites keep their old meaning via `..Default::default()`.
#[derive(Clone, Default)]
pub struct Projectile {
    pub owner: u8,
    pub pos: V2,
    pub target: Option<u32>, // homing target; None = fixed-point ground strike
    pub aim: V2,             // fallback impact point if target dies
    pub speed: Fx,           // tiles per tick
    pub damage: i32,
    pub splash: Fx,          // 0 = single target
    pub crown_pct: i32,
    pub stun_ticks: i32,
    pub hits_flying: bool,
    pub hits_ground: bool,
    pub dead: bool,
    // [curse] Mother Witch VoodooProjectile: on hit, curse the victim for `curse_ticks`
    // and remember which unit (`curse_spawn` def id) it becomes for the attacker on its
    // later death. Only meaningful when curse_ticks > 0 (default 0 = no curse).
    pub curse_ticks: i32,
    pub curse_spawn: i32,
    // [proj] --- projectile-behavior extensions ---
    pub homing: bool,        // [proj] true: track the target entity each tick; false: fly to fixed `aim` (dodgeable)
    pub slow_ticks: i32,     // [proj] on-hit slow applied to victims (Ice Wizard)
    pub chain_count: i32,    // [proj] extra enemies the hit arcs to (Electro Wizard/Spirit)
    pub chain_radius: Fx,    // [proj] max jump distance per chain link
    pub top_k: i32,          // [proj] >0: strike the K highest-HP enemies in `splash` (Lightning)
    pub pierce: bool,        // [proj]/[kb] shared: pierce/roll through enemies instead of stopping at first
    pub line_range: Fx,      // [proj] distance a pierce shot travels before dying (per leg)
    pub boomerang: bool,     // [proj] pierce shot reverses at line_range and returns (Executioner)
    pub vel: V2,             // [proj] per-tick straight-line velocity for pierce shots
    pub traveled: Fx,        // [proj] distance covered on the current pierce leg
    pub return_leg: bool,    // [proj] pierce shot is on its return leg
    pub hit_ids: Vec<u32>,   // [proj]/[kb] shared: entities already struck on this pierce/roll leg
    // [kb] knockback & rolling-pierce (Log, Bowler boulder, Fireball, Rocket, Snowball)
    pub knockback: Fx,        // [kb] push distance in tiles applied to each enemy hit (0 = none)
    pub roll_dir: V2,         // [kb] unit travel direction for a rolling-line projectile ((0,0) = normal)
    pub roll_remaining: Fx,   // [kb] tiles of line travel left; >0 marks an active rolling projectile
}
