//! Deterministic SplitMix64 PRNG. Every stochastic choice in the engine draws
//! from an instance of this, so an episode is a pure function of its seed.

pub struct Rng {
    state: u64,
}

impl Rng {
    pub fn new(seed: u64) -> Rng {
        Rng { state: seed }
    }

    #[inline]
    pub fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E3779B97F4A7C15);
        let mut z = self.state;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
        z ^ (z >> 31)
    }

    /// Uniform float in [0, 1).
    pub fn random(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 * (1.0 / (1u64 << 53) as f64)
    }

    /// Inclusive integer in [lo, hi].
    pub fn randint(&mut self, lo: i64, hi: i64) -> i64 {
        if hi <= lo {
            return lo;
        }
        lo + (self.next_u64() % ((hi - lo + 1) as u64)) as i64
    }

    /// In-place Fisher-Yates shuffle.
    pub fn shuffle<T>(&mut self, seq: &mut [T]) {
        let n = seq.len();
        if n < 2 {
            return;
        }
        for i in (1..n).rev() {
            let j = (self.next_u64() % ((i + 1) as u64)) as usize;
            seq.swap(i, j);
        }
    }
}
