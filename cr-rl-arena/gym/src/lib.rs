//! cr-sim: deterministic fixed-point Clash-Royale-style battle simulator.
//!
//! The crate is usable three ways from one source of truth:
//!   * as a Rust library (`rlib`) embedded in the competition server,
//!   * as a native Python extension (`cdylib`) via PyO3/maturin for RL agents,
//!   * standalone for replay/trace generation.
//!
//! All gameplay math is fixed-point integer arithmetic (see `fixed`), so a
//! match is bit-identical on every platform given the same seed and actions.

use pyo3::prelude::*;

mod arena;
mod cards;
mod engine;
mod entity;
mod env;
mod fixed;
mod rng;

use env::{BatchBattle, Battle, PlayerView};

/// Trivial smoke-test class to validate the build/import pipeline.
/// Replaced by the real `Env` as the engine lands.
#[pyclass]
struct BuildCheck {
    ticks: u32,
}

#[pymethods]
impl BuildCheck {
    #[new]
    fn new() -> Self {
        BuildCheck { ticks: 0 }
    }
    fn reset(&mut self) {
        self.ticks = 0;
    }
    fn step(&mut self) -> u32 {
        self.ticks += 1;
        self.ticks
    }
    /// Prove fixed-point math is wired up: isqrt(2.0) in Q16.16 ~ 1.4142.
    #[staticmethod]
    fn fixed_selftest() -> f64 {
        let two = fixed::Fx::from_int(2);
        two.sqrt().to_f64()
    }
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<BuildCheck>()?;
    m.add_class::<Battle>()?;
    m.add_class::<PlayerView>()?;
    m.add_class::<BatchBattle>()?;
    env::register_constants(m)?;
    m.add("__doc__", "cr-sim native core (fixed-point deterministic engine)")?;
    Ok(())
}
