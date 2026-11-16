//! Python-facing environment: `cr_sim._core.Battle`.
//!
//! Minimal, dependency-free surface an RL agent drives:
//!   b = Battle()
//!   b.reset(seed, deck0, deck1)
//!   obs = b.view(player).observe()     # what that seat sees
//!   out = b.step(action0, action1)     # action = (slot, x, y) or None
//!
//! THE SEAT FRAME. Everything an agent reads or sends is in its own seat's frame,
//! in which it is always the bottom player: its towers sit at low y, it attacks
//! toward high y, entities it owns have owner 0, and crowns read (mine, theirs).
//! For the seat that is really on top, this layer mirrors the board (y -> HEIGHT
//! - y) on the way out and mirrors its actions on the way in, so one policy plays
//! either seat unchanged and never needs to know which seat it has. The engine is
//! exactly mirror-symmetric (see `seat_tests` in engine.rs), so a top-seat game
//! seen this way is indistinguishable from a bottom-seat game.
//!
//! The unmirrored board is exposed only through the `spectator_*` accessors, for
//! rendering, replays and debugging -- never as input to an agent.
//!
//! Observations are returned as plain Python tuples/lists/dicts so there are no
//! third-party deps; the optional numpy/gym adapters live in Python.
//!
//! Throughput primitives (pure speed -- they decide nothing about rewards,
//! observations or action encodings):
//!   bb   = BatchBattle(n, threads=None)    # n independent battles, stepped in parallel
//!   outs = bb.step(actions0, actions1)     # one tick each, all cores, GIL released
//!   bb[i]                                  # an ordinary `Battle` (every accessor works)

use crate::arena::{mirror_y, snap_to_tile, HEIGHT, OVERTIME_TICKS, REGULATION_TICKS, TICKS_PER_SECOND, WIDTH};
use crate::cards::Library;
use crate::engine::{Action, Engine, Outcome};
use crate::fixed::{Fx, V2};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use rayon::prelude::*;

#[pyclass]
pub struct Battle {
    eng: Engine,
}

/// A deck as passed from Python: the word "default", or a list of card names.
#[derive(FromPyObject, Clone)]
pub enum DeckArg {
    Keyword(String),
    Cards(Vec<String>),
}

/// One entity as handed to Python:
/// (owner, card, x, y, hp, max_hp, flying, is_tower, deploying, id, half_w, half_h)
type Ent = (u8, String, f64, f64, i32, i32, bool, bool, bool, u32, f64, f64);

/// An action given in `player`'s seat frame, converted to the engine's board frame.
///
/// The bottom seat's frame is the board frame. For the top seat the target is
/// first snapped to its tile *in the seat frame* and only then mirrored, so the
/// same (x, y) lands on mirror-image tiles for both seats even when it sits
/// exactly on a tile boundary (a plain mirror-then-snap would be off by one tile).
fn seat_action(player: usize, a: Option<(i32, f64, f64)>) -> Action {
    match a {
        None => Action::noop(),
        Some((slot, x, y)) => {
            // a negative slot would read as "no action" inside the engine; it is a
            // mistake, so make sure it is reported as a bad slot
            let slot = if slot < 0 { i32::MAX } else { slot };
            let (x, y) = (Fx::from_f64(x), Fx::from_f64(y));
            if player == 0 {
                return Action { slot, x, y };
            }
            let clamped = V2::new(x.max(Fx(0)).min(WIDTH), y.max(Fx(0)).min(HEIGHT));
            let tile = snap_to_tile(clamped);
            Action { slot, x: tile.x, y: mirror_y(tile.y) }
        }
    }
}

/// The board as `player` sees it: itself at the bottom, its own entities as owner
/// 0 and listed first. Both seats get the same ordering rule and tower ids, so a
/// position and its mirror image produce identical lists for the two seats.
fn seat_entities(player: usize, mut ents: Vec<Ent>) -> Vec<Ent> {
    if player == 1 {
        for e in ents.iter_mut() {
            e.0 = 1 - e.0;
            e.3 = HEIGHT.to_f64() - e.3;
            // the six towers are created first (ids 1-3 bottom seat, 4-6 top seat);
            // swap the two triples so "my king" has the same id from either seat
            if e.7 && e.9 >= 1 && e.9 <= 6 {
                e.9 = if e.9 <= 3 { e.9 + 3 } else { e.9 - 3 };
            }
        }
    }
    ents.sort_by_key(|e| (e.0, e.9)); // mine first, then theirs; oldest first within each
    ents
}

/// Outcome from `player`'s side: 0 running, 1 I won, 2 opponent won, 3 draw.
fn seat_outcome(player: usize, o: Outcome) -> i32 {
    match (o, player) {
        (Outcome::Running, _) => 0,
        (Outcome::Draw, _) => 3,
        (Outcome::Win0, 0) | (Outcome::Win1, 1) => 1,
        _ => 2,
    }
}

fn outcome_code(o: Outcome) -> i32 {
    match o {
        Outcome::Running => 0,
        Outcome::Win0 => 1,
        Outcome::Win1 => 2,
        Outcome::Draw => 3,
    }
}

#[pymethods]
impl Battle {
    #[new]
    #[pyo3(signature = (cards_json=None))]
    fn new(cards_json: Option<String>) -> PyResult<Battle> {
        let lib = match cards_json {
            Some(path) => {
                let s = std::fs::read_to_string(&path)
                    .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
                Library::from_json(&s)
                    .map_err(pyo3::exceptions::PyValueError::new_err)?
            }
            None => Library::default_lib(),
        };
        Ok(Battle { eng: Engine::new(lib) })
    }

    /// Reset to tick 0. A deck is required for each player: a list of 8 card
    /// names, or the word "default" for the built-in deck. Leaving one out is an
    /// error, as it is on the competition server.
    #[pyo3(signature = (seed=0, deck0=None, deck1=None))]
    fn reset(
        &mut self,
        seed: u64,
        deck0: Option<DeckArg>,
        deck1: Option<DeckArg>,
    ) -> PyResult<()> {
        let d0 = self.deck_arg(deck0, "deck0")?;
        let d1 = self.deck_arg(deck1, "deck1")?;
        self.eng.reset(seed, Some([d0, d1]));
        Ok(())
    }

    /// What happened to the action `player` sent on the last tick: "none" (nothing
    /// sent), "ok", or why it was ignored -- "bad_slot", "not_enough_elixir",
    /// "not_your_side", "nothing_to_mirror", "ability_unavailable". An ignored
    /// action spends nothing.
    fn last_action(&self, player: usize) -> &'static str {
        self.eng.last_action[player.min(1)].as_str()
    }

    /// Check that `deck` is legal without starting a match: exactly 8 different,
    /// playable card names with at most one champion. Raises ValueError saying
    /// what is wrong; returns None if the deck is fine. `reset` applies the same
    /// rules, so the competition server calls this when an agent joins.
    fn check_deck(&self, deck: Vec<String>) -> PyResult<()> {
        self.resolve_deck(&deck).map(|_| ())
    }

    /// Advance one tick. Each action is (hand_slot, x, y) or None for no-op, and
    /// each is given in ITS OWN SEAT'S FRAME: both players place cards as if they
    /// were at the bottom (own side is y < 15), exactly as their `view(...)`
    /// shows the board. Returns the referee's outcome code: 0 running, 1 seat 0
    /// won, 2 seat 1 won, 3 draw.
    #[pyo3(signature = (action0=None, action1=None))]
    fn step(
        &mut self,
        action0: Option<(i32, f64, f64)>,
        action1: Option<(i32, f64, f64)>,
    ) -> i32 {
        let a0 = seat_action(0, action0);
        let a1 = seat_action(1, action1);
        outcome_code(self.eng.step([a0, a1]))
    }

    /// [champ] Activate `player`'s on-field champion ability. Returns True if it
    /// fired (champion deployed + active, off cooldown, enough elixir, and — for
    /// the dash — an enemy in reach); False otherwise, spending nothing.
    ///
    /// Equivalent to passing the reserved slot `cr_sim.ABILITY_SLOT` in `step`,
    /// e.g. `b.step((cr_sim.ABILITY_SLOT, 0.0, 0.0), None)`.
    fn activate_ability(&mut self, player: usize) -> bool {
        self.eng.activate_ability(player.min(1))
    }

    /// [champ] (on_field, cooldown_ticks_remaining, ability_cost) for a player's
    /// champion; (False, 0, 0) when none is deployed.
    fn champion_status(&self, player: usize) -> (bool, i32, i32) {
        self.eng.champion_status(player.min(1))
    }

    /// Return a read-only [`PlayerView`] exposing **only** what `player` may
    /// legally see under Clash Royale's hidden-information model.
    ///
    /// A competition harness should hand each agent `battle.view(me)` — never the
    /// raw `Battle`. The view lets the agent read the full board, its own
    /// hand/next-card/elixir/crowns, and the opponent's crowns + tower state, but
    /// has no accessor at all for the opponent's hand, next card, or elixir, so an
    /// agent structurally cannot peek at the opponent's hidden information. The
    /// raw `Battle` getters stay available for the trusted harness, debugging, and
    /// replay. The view is a live window: re-reading it after `step(...)` reflects
    /// the new state, and it never mutates the simulation.
    fn view(slf: &Bound<'_, Self>, player: usize) -> PlayerView {
        PlayerView {
            battle: slf.clone().unbind(),
            player: player.min(1),
        }
    }

    // ---- scalar accessors ----

    #[getter]
    fn tick(&self) -> i64 {
        self.eng.tick
    }
    fn elapsed_seconds(&self) -> f64 {
        self.eng.tick as f64 / TICKS_PER_SECOND as f64
    }
    fn outcome(&self) -> i32 {
        outcome_code(self.eng.outcome)
    }
    fn done(&self) -> bool {
        self.eng.outcome != Outcome::Running
    }
    fn phase(&self) -> &'static str {
        let t = self.eng.tick;
        if t >= REGULATION_TICKS {
            "overtime"
        } else if t >= crate::arena::DOUBLE_ELIXIR_AT {
            "double"
        } else {
            "single"
        }
    }
    fn elixir(&self, player: usize) -> f64 {
        self.eng.elixir[player.min(1)].to_f64()
    }
    fn crowns(&self) -> (i32, i32) {
        (self.eng.crowns[0], self.eng.crowns[1])
    }

    fn hand(&self, player: usize) -> Vec<String> {
        self.eng
            .hand(player.min(1))
            .iter()
            .map(|&d| self.eng.lib.defs[d].name.clone())
            .collect()
    }
    fn hand_cost(&self, player: usize) -> Vec<i32> {
        self.eng
            .hand(player.min(1))
            .iter()
            .map(|&d| self.eng.lib.defs[d].elixir)
            .collect()
    }
    fn next_card(&self, player: usize) -> String {
        self.eng.lib.defs[self.eng.next_card(player.min(1))].name.clone()
    }

    /// Per-hand-slot affordability mask (true = enough elixir to play it now).
    fn legal(&self, player: usize) -> Vec<bool> {
        let p = player.min(1);
        let e = self.eng.elixir[p].to_f64();
        self.eng
            .hand(p)
            .iter()
            .map(|&d| self.eng.lib.defs[d].elixir as f64 <= e)
            .collect()
    }

    /// SPECTATOR view of the board, unmirrored: for rendering, replays and
    /// debugging, NOT for agent input (an agent reads `view(player).entities()`,
    /// which is in its own seat frame). `owner` is the real seat and seat 1's
    /// towers are at the top. Tuples:
    /// (owner, card, x, y, hp, max_hp, flying, is_tower, deploying, id, half_w, half_h)
    /// half_w/half_h are box half-extents in tiles (0 => circle; radius via card).
    fn spectator_entities(&self) -> Vec<Ent> {
        self.eng
            .entities
            .iter()
            .map(|e| {
                let d = &self.eng.lib.defs[e.def];
                (
                    e.owner,
                    d.name.clone(),
                    e.pos.x.to_f64(),
                    e.pos.y.to_f64(),
                    e.hp,
                    e.max_hp,
                    d.flying,
                    e.is_tower,
                    e.deploy > 0,
                    e.id,
                    e.half.x.to_f64(),
                    e.half.y.to_f64(),
                )
            })
            .collect()
    }

    /// SPECTATOR view of projectiles in flight, unmirrored: (owner, x, y).
    fn spectator_projectiles(&self) -> Vec<(u8, f64, f64)> {
        self.eng
            .projectiles
            .iter()
            .map(|p| (p.owner, p.pos.x.to_f64(), p.pos.y.to_f64()))
            .collect()
    }

    /// The observation for the agent in seat `player` (same as
    /// `view(player).observe()`), in that seat's frame: the agent is always the
    /// bottom player, owner 0 is "mine", `crowns` is (mine, theirs) and `outcome`
    /// is 1 when this agent won. It deliberately does not say which seat this is.
    /// The opponent's hand, next card and elixir are not included.
    fn observe<'py>(&self, py: Python<'py>, player: usize) -> PyResult<Bound<'py, PyDict>> {
        let p = player.min(1);
        let c = self.crowns();
        let d = PyDict::new(py);
        d.set_item("tick", self.eng.tick)?;
        d.set_item("elixir", self.elixir(p))?;
        d.set_item("phase", self.phase())?;
        d.set_item("crowns", if p == 0 { c } else { (c.1, c.0) })?;
        d.set_item("hand", self.hand(p))?;
        d.set_item("hand_cost", self.hand_cost(p))?;
        d.set_item("next_card", self.next_card(p))?;
        d.set_item("legal", self.legal(p))?;
        d.set_item("last_action", self.last_action(p))?;
        d.set_item("entities", seat_entities(p, self.spectator_entities()))?;
        d.set_item("done", self.done())?;
        d.set_item("outcome", seat_outcome(p, self.eng.outcome))?;
        Ok(d)
    }

    /// Card names a deck may draw from.
    fn deployable_cards(&self) -> Vec<String> {
        self.eng
            .lib
            .deployable
            .iter()
            .map(|&d| self.eng.lib.defs[d].name.clone())
            .collect()
    }
}

impl Battle {
    fn deck_arg(&self, deck: Option<DeckArg>, which: &str) -> PyResult<Vec<usize>> {
        match deck {
            None => Err(pyo3::exceptions::PyValueError::new_err(format!(
                "{which} is required: pass a list of 8 card names, or \"default\" for the built-in deck"
            ))),
            Some(DeckArg::Keyword(k)) if k == "default" => Ok(self.eng.default_deck()),
            Some(DeckArg::Keyword(k)) => Err(pyo3::exceptions::PyValueError::new_err(format!(
                "{which}: unknown deck '{k}': pass a list of 8 card names, or \"default\""
            ))),
            Some(DeckArg::Cards(names)) => self.resolve_deck(&names),
        }
    }

    fn resolve_deck(&self, names: &[String]) -> PyResult<Vec<usize>> {
        if names.len() != 8 {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "deck must have 8 cards, got {}",
                names.len()
            )));
        }
        let mut out = Vec::with_capacity(8);
        for n in names {
            match self.eng.lib.id_of(n) {
                Some(id) => out.push(id),
                None => {
                    return Err(pyo3::exceptions::PyValueError::new_err(format!(
                        "unknown card '{n}'"
                    )))
                }
            }
        }
        // Deck-legal cards only: towers, evolved variants and summon-only units
        // (golemite, hut spawns, ...) exist in the library but are not cards.
        for (n, &id) in names.iter().zip(out.iter()) {
            if !self.eng.lib.deployable.contains(&id) {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "'{n}' is not a playable card and cannot be put in a deck"
                )));
            }
        }
        // No duplicates: a deck is 8 different cards.
        for (i, n) in names.iter().enumerate() {
            if out[..i].contains(&out[i]) {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "duplicate card '{n}': a deck must be 8 different cards"
                )));
            }
        }
        // [champ] enforce the one-champion-per-deck rule
        let champs = out.iter().filter(|&&id| self.eng.lib.defs[id].is_champion).count();
        if champs > 1 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "a deck may contain at most one champion",
            ));
        }
        Ok(out)
    }
}

type BatchActions = Option<Vec<Option<(i32, f64, f64)>>>;

/// `n` independent battles stepped together in one native call, across threads,
/// with the GIL released.
///
/// This is purely a throughput tool. Each element is an ordinary [`Battle`]
/// (`bb[i]`), so every accessor -- `view`, `observe`, `legal`,
/// `reset`, ... -- works per battle exactly as it does standalone, and a battle
/// stepped here plays out bit-identically to the same battle stepped alone.
/// Nothing about rewards, observation encoding or when to reset is decided here.
///
///   bb = BatchBattle(256)                    # threads=None: one per CPU core
///   bb.reset(range(256), deck, deck)         # one seed per battle
///   outs = bb.step(acts0, acts1)             # lists of (slot, x, y) | None
///   for i, o in enumerate(outs):
///       if o: bb[i].reset(new_seed, deck, deck)   # finished battles are left as-is
#[pyclass]
pub struct BatchBattle {
    battles: Vec<Py<Battle>>,
    pool: Option<rayon::ThreadPool>, // None => step sequentially on the caller's thread
    threads: usize,
}

impl BatchBattle {
    fn batch_actions(&self, a: BatchActions, player: usize, which: &str) -> PyResult<Vec<Action>> {
        match a {
            None => Ok(vec![Action::noop(); self.battles.len()]),
            Some(v) => {
                if v.len() != self.battles.len() {
                    return Err(pyo3::exceptions::PyValueError::new_err(format!(
                        "{which} has {} entries, expected {} (one per battle)",
                        v.len(),
                        self.battles.len()
                    )));
                }
                Ok(v.into_iter().map(|x| seat_action(player, x)).collect())
            }
        }
    }
}

#[pymethods]
impl BatchBattle {
    /// `n` battles. `threads`: None/0 = one worker per CPU core, 1 = no worker
    /// threads (step on the calling thread), N = exactly N workers.
    #[new]
    #[pyo3(signature = (n, threads=None, cards_json=None))]
    fn new(py: Python<'_>, n: usize, threads: Option<usize>, cards_json: Option<String>) -> PyResult<BatchBattle> {
        if n == 0 {
            return Err(pyo3::exceptions::PyValueError::new_err("n must be >= 1"));
        }
        let mut battles = Vec::with_capacity(n);
        for _ in 0..n {
            battles.push(Py::new(py, Battle::new(cards_json.clone())?)?);
        }
        let want = threads.unwrap_or(0);
        let pool = if want == 1 {
            None
        } else {
            Some(
                rayon::ThreadPoolBuilder::new()
                    .num_threads(want) // 0 => rayon picks the CPU count
                    .build()
                    .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?,
            )
        };
        let threads = pool.as_ref().map_or(1, |p| p.current_num_threads());
        Ok(BatchBattle { battles, pool, threads })
    }

    /// Reset every battle to tick 0. `seeds` has one seed per battle; the decks
    /// (required, as in `Battle.reset`: card names or "default") are shared by all. To reset
    /// a single battle -- e.g. one that just finished -- call `bb[i].reset(...)`.
    #[pyo3(signature = (seeds, deck0=None, deck1=None))]
    fn reset(
        &self,
        py: Python<'_>,
        seeds: Vec<u64>,
        deck0: Option<DeckArg>,
        deck1: Option<DeckArg>,
    ) -> PyResult<()> {
        if seeds.len() != self.battles.len() {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "seeds has {} entries, expected {} (one per battle)",
                seeds.len(),
                self.battles.len()
            )));
        }
        for (b, seed) in self.battles.iter().zip(seeds) {
            b.bind(py).try_borrow_mut()?.reset(seed, deck0.clone(), deck1.clone())?;
        }
        Ok(())
    }

    /// Advance every battle by one tick, exactly as `Battle.step` would: battle
    /// `i` gets `actions0[i]` / `actions1[i]`, each in its own seat's frame.
    /// Either list may be None (all no-ops). Battles that have already finished are left untouched. Returns one
    /// outcome code per battle. Runs on the worker threads with the GIL released;
    /// results do not depend on the thread count.
    #[pyo3(signature = (actions0=None, actions1=None))]
    fn step(
        &self,
        py: Python<'_>,
        actions0: BatchActions,
        actions1: BatchActions,
    ) -> PyResult<Vec<i32>> {
        let a0 = self.batch_actions(actions0, 0, "actions0")?;
        let a1 = self.batch_actions(actions1, 1, "actions1")?;
        // Exclusive borrows of every battle for the duration of the call; the
        // engines are then plain `&mut` data, safe to hand to other threads.
        let mut guards: Vec<PyRefMut<'_, Battle>> = Vec::with_capacity(self.battles.len());
        for b in &self.battles {
            guards.push(b.bind(py).try_borrow_mut()?);
        }
        let mut work: Vec<(&mut Engine, Action, Action)> = guards
            .iter_mut()
            .zip(a0.into_iter().zip(a1))
            .map(|(g, (x, y))| (&mut g.eng, x, y))
            .collect();
        let pool = self.pool.as_ref();
        let outs: Vec<Outcome> = py.allow_threads(|| match pool {
            Some(p) => p.install(|| {
                work.par_iter_mut().map(|(e, x, y)| e.step([*x, *y])).collect()
            }),
            None => work.iter_mut().map(|(e, x, y)| e.step([*x, *y])).collect(),
        });
        Ok(outs.into_iter().map(outcome_code).collect())
    }

    /// Number of worker threads `step` uses (1 = the calling thread only).
    #[getter]
    fn threads(&self) -> usize {
        self.threads
    }

    fn __len__(&self) -> usize {
        self.battles.len()
    }

    /// Battle `i` as an ordinary `Battle` (negative indices count from the end).
    fn __getitem__(&self, py: Python<'_>, i: isize) -> PyResult<Py<Battle>> {
        let n = self.battles.len() as isize;
        let j = if i < 0 { i + n } else { i };
        if j < 0 || j >= n {
            return Err(pyo3::exceptions::PyIndexError::new_err("battle index out of range"));
        }
        Ok(self.battles[j as usize].clone_ref(py))
    }

    /// All battles, in order, as a list of `Battle` objects.
    fn battles(&self, py: Python<'_>) -> Vec<Py<Battle>> {
        self.battles.iter().map(|b| b.clone_ref(py)).collect()
    }

    // ---- bulk raw state (one call instead of n) ----

    /// Outcome code per battle (0 running, 1 player0 win, 2 player1 win, 3 draw).
    fn outcomes(&self, py: Python<'_>) -> Vec<i32> {
        self.battles.iter().map(|b| b.bind(py).borrow().outcome()).collect()
    }
    /// Whether each battle has finished.
    fn done(&self, py: Python<'_>) -> Vec<bool> {
        self.battles.iter().map(|b| b.bind(py).borrow().done()).collect()
    }
    /// Current tick of each battle.
    fn ticks(&self, py: Python<'_>) -> Vec<i64> {
        self.battles.iter().map(|b| b.bind(py).borrow().tick()).collect()
    }
    /// (player0_crowns, player1_crowns) per battle.
    fn crowns(&self, py: Python<'_>) -> Vec<(i32, i32)> {
        self.battles.iter().map(|b| b.bind(py).borrow().crowns()).collect()
    }
    /// `Battle.spectator_entities()` for every battle (unmirrored; not agent input).
    fn spectator_entities(&self, py: Python<'_>) -> Vec<Vec<Ent>> {
        self.battles.iter().map(|b| b.bind(py).borrow().spectator_entities()).collect()
    }

    fn __repr__(&self) -> String {
        format!("BatchBattle(n={}, threads={})", self.battles.len(), self.threads)
    }
}

/// Clamp a player index to a valid seat (0 or 1).
#[inline]
fn view_player(player: usize) -> usize {
    player.min(1)
}

/// The opposing seat for a (clamped) player index.
#[inline]
fn view_opponent(player: usize) -> usize {
    1 - player.min(1)
}

/// A read-only, per-player window onto a [`Battle`] that enforces Clash Royale's
/// hidden-information model at the API boundary.
///
/// Everything here is in this player's SEAT FRAME (see the module docs): the
/// player is always at the bottom, owns the entities marked owner 0, and reads
/// crowns as (mine, theirs). The same code therefore plays either seat.
///
/// What this player **may** see (and this view exposes):
///   * the full board — every deployed unit, tower, and projectile of *both*
///     sides is public (`entities`, `towers`, `projectiles`),
///   * its own hand, next card, elixir, crown count, and champion status,
///   * the opponent's crown count and tower HP/state (via the public board),
///   * the fog-of-war `observe()` observation and the `legal()` action mask.
///
/// What it **cannot** see: there is deliberately no accessor for the opponent's
/// hand, next card, or elixir. The per-player getters (`elixir`, `hand`,
/// `hand_cost`, `next_card`, `legal`, `champion_status`) take **no player
/// argument** — they always report this view's own seat — so an agent handed
/// `battle.view(me)` structurally cannot read the opponent's private state, and
/// the view exposes no mutators (`step`/`reset`/`activate_ability`) either.
///
/// The raw `Battle` getters remain for the trusted harness, debugging, and
/// replay. The view is a live window onto the same `Battle`, so re-reading it
/// after `Battle.step(...)` reflects the new tick; it never mutates the sim.
#[pyclass]
pub struct PlayerView {
    battle: Py<Battle>,
    player: usize,
}

#[pymethods]
impl PlayerView {
    /// The real seat this view belongs to (0 or 1). For the harness that created
    /// the view; nothing an agent reads through the view depends on it.
    #[getter]
    fn player(&self) -> usize {
        self.player
    }

    /// The opponent's seat (0 or 1).
    #[getter]
    fn opponent(&self) -> usize {
        view_opponent(self.player)
    }

    // ---- public match state (both players see these) ----

    #[getter]
    fn tick(&self, py: Python<'_>) -> i64 {
        self.battle.borrow(py).tick()
    }
    fn elapsed_seconds(&self, py: Python<'_>) -> f64 {
        self.battle.borrow(py).elapsed_seconds()
    }
    fn phase(&self, py: Python<'_>) -> &'static str {
        self.battle.borrow(py).phase()
    }
    /// Outcome from this player's side: 0 running, 1 I won, 2 opponent won, 3 draw.
    fn outcome(&self, py: Python<'_>) -> i32 {
        seat_outcome(self.player, self.battle.borrow(py).eng.outcome)
    }
    /// "win", "loss" or "draw" for this player; None while the match is running.
    fn result(&self, py: Python<'_>) -> Option<&'static str> {
        match self.outcome(py) {
            0 => None,
            1 => Some("win"),
            2 => Some("loss"),
            _ => Some("draw"),
        }
    }
    fn done(&self, py: Python<'_>) -> bool {
        self.battle.borrow(py).done()
    }

    /// (my_crowns, opponent_crowns). The crown score is public to both sides.
    fn crowns(&self, py: Python<'_>) -> (i32, i32) {
        (self.my_crowns(py), self.opponent_crowns(py))
    }
    /// This player's own crown count.
    fn my_crowns(&self, py: Python<'_>) -> i32 {
        let c = self.battle.borrow(py).crowns();
        if self.player == 0 { c.0 } else { c.1 }
    }
    /// The opponent's crown count (public).
    fn opponent_crowns(&self, py: Python<'_>) -> i32 {
        let c = self.battle.borrow(py).crowns();
        if self.player == 0 { c.1 } else { c.0 }
    }

    /// Full board — every deployed unit and tower of *both* sides (public), in
    /// this player's seat frame: owner 0 is mine, and my side is the bottom. Mine
    /// are listed first. Tuples:
    /// (owner, card, x, y, hp, max_hp, flying, is_tower, deploying, id, half_w, half_h)
    fn entities(&self, py: Python<'_>) -> Vec<Ent> {
        seat_entities(self.player, self.battle.borrow(py).spectator_entities())
    }

    /// The tower subset of `entities()` (both sides' crown/king towers are
    /// public, including their HP) — convenience for reading tower state.
    fn towers(&self, py: Python<'_>) -> Vec<Ent> {
        self.entities(py)
            .into_iter()
            .filter(|e| e.7) // e.7 == is_tower
            .collect()
    }

    /// Projectiles in flight for both sides (public), in this player's seat
    /// frame: (owner, x, y) with owner 0 mine.
    fn projectiles(&self, py: Python<'_>) -> Vec<(u8, f64, f64)> {
        let mut v = self.battle.borrow(py).spectator_projectiles();
        if self.player == 1 {
            for p in v.iter_mut() {
                p.0 = 1 - p.0;
                p.2 = HEIGHT.to_f64() - p.2;
            }
        }
        v
    }

    // ---- private: this player's OWN state only (never the opponent's) ----

    /// This player's own elixir. The opponent's elixir is hidden — there is no
    /// accessor for it, and this getter takes no player argument.
    fn elixir(&self, py: Python<'_>) -> f64 {
        self.battle.borrow(py).elixir(self.player)
    }
    /// This player's own hand (4 card names).
    fn hand(&self, py: Python<'_>) -> Vec<String> {
        self.battle.borrow(py).hand(self.player)
    }
    /// Elixir cost of each card in this player's own hand.
    fn hand_cost(&self, py: Python<'_>) -> Vec<i32> {
        self.battle.borrow(py).hand_cost(self.player)
    }
    /// This player's own next card.
    fn next_card(&self, py: Python<'_>) -> String {
        self.battle.borrow(py).next_card(self.player)
    }
    /// This player's own champion status: (on_field, cooldown_ticks, cost). The
    /// opponent's ability cooldown is hidden.
    fn champion_status(&self, py: Python<'_>) -> (bool, i32, i32) {
        self.battle.borrow(py).champion_status(self.player)
    }
    /// Per-hand-slot affordability mask for this player. It only says whether the
    /// card can be paid for, not where it may be placed.
    fn legal(&self, py: Python<'_>) -> Vec<bool> {
        self.battle.borrow(py).legal(self.player)
    }
    /// What happened to this player's action on the last tick: "none", "ok", or
    /// the reason it was ignored (see `Battle.last_action`).
    fn last_action(&self, py: Python<'_>) -> &'static str {
        self.battle.borrow(py).last_action(self.player)
    }

    /// The observation dict for this player (identical to
    /// `Battle.observe(player)`): own hand/next/elixir + the full board in this
    /// player's seat frame, with the opponent's private state omitted. This is
    /// exactly what the competition server sends an agent.
    fn observe<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        self.battle.borrow(py).observe(py, self.player)
    }

    fn __repr__(&self) -> String {
        format!("PlayerView(player={})", self.player)
    }
}

#[cfg(test)]
mod view_tests {
    use super::{seat_action, seat_entities, seat_outcome, view_opponent, view_player, Ent};
    use crate::arena::HEIGHT;
    use crate::cards::Library;
    use crate::engine::{Engine, Outcome};

    fn ents(eng: &Engine) -> Vec<Ent> {
        eng.entities
            .iter()
            .map(|e| {
                (e.owner, eng.lib.defs[e.def].name.clone(), e.pos.x.to_f64(), e.pos.y.to_f64(),
                 e.hp, e.max_hp, eng.lib.defs[e.def].flying, e.is_tower, e.deploy > 0, e.id,
                 e.half.x.to_f64(), e.half.y.to_f64())
            })
            .collect()
    }

    /// The property the seat frame exists for: when both seats are dealt the same
    /// hand and send the SAME seat-frame actions, each sees exactly what the other
    /// sees, every tick, whole match. So an agent cannot tell which seat it has,
    /// and whatever works from one seat works identically from the other.
    #[test]
    fn both_seats_see_the_same_game_when_they_play_the_same_moves() {
        // includes points on tile boundaries and outside the arena (snapping/clamping)
        let spots = [(5.5, 9.5), (12.0, 14.0), (3.0, 0.0), (17.99, 6.25), (9.0, 14.999), (-2.0, 40.0), (8.5, 20.5)];
        let mut eng = Engine::new(Library::default_lib());
        eng.reset(7, None); // both seats get the default deck...
        eng.queue[1] = eng.queue[0].clone(); // ...and here the same hand order too
        let mut deployed = false;
        for t in 0..4000usize {
            let a = if t % 37 == 0 { Some(((t / 37 % 4) as i32, spots[t / 37 % spots.len()].0, spots[t / 37 % spots.len()].1)) } else { None };
            eng.step([seat_action(0, a), seat_action(1, a)]);
            let (v0, v1) = (seat_entities(0, ents(&eng)), seat_entities(1, ents(&eng)));
            // unit ids are handed out in creation order, which alternates between the
            // seats for same-tick deploys; everything else must be identical
            let strip = |v: &[Ent]| v.iter().map(|e| (e.0, e.1.clone(), e.2.to_bits(), e.3.to_bits(), e.4, e.5, e.6, e.7, e.8, if e.7 { e.9 } else { 0 }, e.10.to_bits(), e.11.to_bits())).collect::<Vec<_>>();
            let (mut s0, mut s1) = (strip(&v0), strip(&v1));
            s0.sort_by(|a, b| a.partial_cmp(b).unwrap());
            s1.sort_by(|a, b| a.partial_cmp(b).unwrap());
            assert!(s0 == s1, "the two seats saw different boards at tick {t}");
            assert_eq!(eng.elixir[0].0, eng.elixir[1].0, "elixir differs at tick {t}");
            assert_eq!(seat_outcome(0, eng.outcome), seat_outcome(1, eng.outcome));
            deployed |= eng.entities.iter().any(|e| !e.is_tower);
            if eng.outcome != Outcome::Running {
                break;
            }
        }
        assert!(deployed, "the scripted actions must actually deploy units");
    }

    #[test]
    fn seat_frame_puts_me_at_the_bottom_as_owner_zero() {
        let mut eng = Engine::new(Library::default_lib());
        eng.reset(1, None);
        let (v0, v1) = (seat_entities(0, ents(&eng)), seat_entities(1, ents(&eng)));
        assert_eq!(v0, v1, "at kick-off both seats see the identical board");
        for v in [&v0, &v1] {
            assert!(v[..3].iter().all(|e| e.0 == 0 && e.3 < HEIGHT.to_f64() / 2.0), "mine: first, owner 0, bottom half");
            assert!(v[3..].iter().all(|e| e.0 == 1 && e.3 > HEIGHT.to_f64() / 2.0));
            assert_eq!(v.iter().map(|e| e.9).collect::<Vec<_>>(), vec![1, 2, 3, 4, 5, 6]);
        }
    }

    #[test]
    fn outcome_is_reported_from_each_seat() {
        assert_eq!((seat_outcome(0, Outcome::Win0), seat_outcome(1, Outcome::Win0)), (1, 2));
        assert_eq!((seat_outcome(0, Outcome::Win1), seat_outcome(1, Outcome::Win1)), (2, 1));
        assert_eq!((seat_outcome(0, Outcome::Draw), seat_outcome(1, Outcome::Draw)), (3, 3));
        assert_eq!((seat_outcome(0, Outcome::Running), seat_outcome(1, Outcome::Running)), (0, 0));
    }

    #[test]
    fn seat_clamps_to_valid_range() {
        assert_eq!(view_player(0), 0);
        assert_eq!(view_player(1), 1);
        // out-of-range seats clamp to seat 1, matching the Battle getters.
        assert_eq!(view_player(2), 1);
        assert_eq!(view_player(usize::MAX), 1);
    }

    #[test]
    fn opponent_is_the_other_seat() {
        assert_eq!(view_opponent(0), 1);
        assert_eq!(view_opponent(1), 0);
        assert_eq!(view_opponent(2), 0); // clamped first
        // a view's own seat and its opponent are always distinct
        for p in 0..2usize {
            assert_ne!(view_player(p), view_opponent(p));
        }
    }
}

/// Register the arena dimensions on the module so Python/viewer can read them.
pub fn register_constants(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("WIDTH", WIDTH.to_f64())?;
    m.add("HEIGHT", HEIGHT.to_f64())?;
    m.add("TICKS_PER_SECOND", TICKS_PER_SECOND)?;
    m.add("REGULATION_TICKS", REGULATION_TICKS)?;
    m.add("OVERTIME_TICKS", OVERTIME_TICKS)?;
    m.add("ABILITY_SLOT", crate::engine::ABILITY_SLOT)?; // [champ]
    m.add("RIVER_Y", crate::arena::RIVER_Y.to_f64())?;
    m.add("RIVER_HALF", crate::arena::RIVER_HALF.to_f64())?;
    m.add("BRIDGE_HALF", crate::arena::BRIDGE_HALF.to_f64())?;
    m.add(
        "BRIDGES",
        vec![crate::arena::BRIDGE_L.to_f64(), crate::arena::BRIDGE_R.to_f64()],
    )?;
    let _ = V2::default();
    Ok(())
}
