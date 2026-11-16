//! Arena geometry and match timing, in fixed-point tiles.
//!
//! Layout (player 0 = bottom, rows 0..14; player 1 = top, rows 17..31):
//!
//!   18 columns x 32 rows of 1x1 tiles.
//!   River:      rows 15-16 (y in [15,17)), crossable only on the bridges.
//!   Bridges:    3 tiles wide, directly in front of the princess towers, so
//!               each lane runs straight bridge -> princess tower.
//!   King tower: 4x4 tiles, cols 7-10, rows 1-4  (center 9, 3).
//!   Princess:   3x3 tiles, cols 2-4 and 13-15, rows 5-7 (centers 3.5/14.5, 6.5).
//!   Player 1's towers are the mirror image (y -> 32 - y).
//!
//! Towers are axis-aligned boxes for collision, range and splash. Range is
//! measured from the attacker's center to the target's hitbox surface.
//! Values to double-check against your decoded arena data: the king tower's
//! row offset and the bridge width.

use crate::fixed::{Fx, V2, ONE};

pub const TICKS_PER_SECOND: i64 = 20;

pub const COLS: i64 = 18;
pub const ROWS: i64 = 32;
pub const WIDTH: Fx = Fx::from_int(COLS);
pub const HEIGHT: Fx = Fx::from_int(ROWS);

// River occupies rows 15 and 16.
pub const RIVER_Y: Fx = Fx::from_int(16);
pub const RIVER_HALF: Fx = Fx::from_int(1);

// Bridges, in line with the princess towers.
pub const BRIDGE_L: Fx = Fx::from_raw(7 * ONE / 2); // 3.5  (cols 2-4)
pub const BRIDGE_R: Fx = Fx::from_raw(29 * ONE / 2); // 14.5 (cols 13-15)
pub const BRIDGE_HALF: Fx = Fx::from_raw(3 * ONE / 2); // 1.5

// Tower footprints (half-extents).
pub const KING_HALF: Fx = Fx::from_int(2); // 4x4
pub const PRINCESS_HALF: Fx = Fx::from_raw(3 * ONE / 2); // 3x3

// Deploy zones. Player 0 owns y < 15; player 1 owns y >= 17.
pub const P0_DEPLOY_MAX_Y: Fx = Fx::from_int(15);
pub const P1_DEPLOY_MIN_Y: Fx = Fx::from_int(17);
// After an enemy princess tower falls, its lane's half of the enemy side opens
// up to the back edge of that tower (p0: y in [17,27); p1: y in [5,15)).
pub const POCKET_FAR_Y_P0: Fx = Fx::from_int(27);
pub const POCKET_FAR_Y_P1: Fx = Fx::from_int(5);

// Match timing (seconds -> ticks).
pub const REGULATION_TICKS: i64 = 180 * TICKS_PER_SECOND;
pub const OVERTIME_TICKS: i64 = 120 * TICKS_PER_SECOND;
pub const DOUBLE_ELIXIR_AT: i64 = 120 * TICKS_PER_SECOND; // 2x in the last 60s

pub const START_ELIXIR: i64 = 5;
pub const MAX_ELIXIR: i64 = 10;

// 1 elixir per 2.8s (1x), 1.4s (2x), 2.8/3 s (3x).
pub fn elixir_per_tick_1x() -> Fx {
    Fx::from_int(1).div(Fx::from_int(28 * TICKS_PER_SECOND / 10))
}
pub fn elixir_per_tick_2x() -> Fx {
    Fx::from_int(1).div(Fx::from_int(14 * TICKS_PER_SECOND / 10))
}
pub fn elixir_per_tick_3x() -> Fx {
    elixir_per_tick_1x().muli(3)
}

pub const DEPLOY_TICKS: i32 = TICKS_PER_SECOND as i32; // 1.0s deploy time

/// Side of the river: 0 = bottom (player 0), 1 = top.
#[inline]
pub fn side(y: Fx) -> u8 {
    if y < RIVER_Y {
        0
    } else {
        1
    }
}

#[inline]
pub fn same_side(a: Fx, b: Fx) -> bool {
    side(a) == side(b)
}

/// x of the nearest bridge.
#[inline]
pub fn nearest_bridge_x(x: Fx) -> Fx {
    if (x - BRIDGE_L).abs() <= (x - BRIDGE_R).abs() {
        BRIDGE_L
    } else {
        BRIDGE_R
    }
}

/// Lane of an x coordinate: 0 = left (x < 9), 1 = right.
#[inline]
pub fn lane_of(x: Fx) -> u8 {
    if x < WIDTH.divi(2) {
        0
    } else {
        1
    }
}

/// Tower layout for player 0: (center, half-extent, is_king). Mirror y for p1.
pub fn tower_layout_p0() -> [(V2, Fx, bool); 3] {
    let king = V2::new(Fx::from_int(9), Fx::from_int(3));
    let pl = V2::new(BRIDGE_L, Fx::from_raw(13 * ONE / 2)); // (3.5, 6.5)
    let pr = V2::new(BRIDGE_R, Fx::from_raw(13 * ONE / 2)); // (14.5, 6.5)
    [(king, KING_HALF, true), (pl, PRINCESS_HALF, false), (pr, PRINCESS_HALF, false)]
}

#[inline]
pub fn mirror_y(y: Fx) -> Fx {
    HEIGHT - y
}

/// Snap a position to the center of the tile containing it (clamped to the arena).
pub fn snap_to_tile(p: V2) -> V2 {
    let cx = p.x.to_int_floor().clamp(0, COLS - 1);
    let cy = p.y.to_int_floor().clamp(0, ROWS - 1);
    let half = Fx::from_raw(ONE / 2);
    V2::new(Fx::from_int(cx) + half, Fx::from_int(cy) + half)
}
