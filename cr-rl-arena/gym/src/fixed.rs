//! Q16.16 fixed-point arithmetic.
//!
//! Every spatial/temporal quantity in the engine is an `Fx`. Using fixed-point
//! integers (not floats) guarantees that `a + b`, `a * b`, distances and square
//! roots evaluate identically on x86, ARM, and WASM — which is what lets a
//! replay recorded on a student's laptop be re-simulated bit-for-bit on the
//! competition server.

pub const FRAC_BITS: u32 = 16;
pub const ONE: i64 = 1 << FRAC_BITS; // 65536

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug, Default)]
pub struct Fx(pub i64); // raw Q16.16 value

impl Fx {
    #[inline]
    pub const fn from_raw(r: i64) -> Fx {
        Fx(r)
    }
    #[inline]
    pub const fn from_int(i: i64) -> Fx {
        Fx(i << FRAC_BITS)
    }
    /// Build from a decimal like 1.5 at *construction time only* (config load).
    /// Rounds to nearest raw unit. Never used inside the tick loop.
    pub fn from_f64(v: f64) -> Fx {
        Fx((v * ONE as f64).round() as i64)
    }
    #[inline]
    pub fn to_f64(self) -> f64 {
        self.0 as f64 / ONE as f64
    }
    #[inline]
    pub fn to_int_floor(self) -> i64 {
        self.0 >> FRAC_BITS
    }

    #[inline]
    pub fn mul(self, o: Fx) -> Fx {
        // widen to i128 to avoid overflow, then scale back. Division (truncate toward
        // zero), NOT an arithmetic shift (floor): a shift rounds negative products
        // away from zero, so anything moving in -y/-x covered ~1 ulp more per multiply
        // than its mirror image and player 1's units out-walked player 0's. Truncation
        // matches `div`/`divi` and makes mul sign-symmetric: (-a)*b == -(a*b).
        Fx(((self.0 as i128 * o.0 as i128) / (1i128 << FRAC_BITS)) as i64)
    }
    #[inline]
    pub fn div(self, o: Fx) -> Fx {
        Fx((((self.0 as i128) << FRAC_BITS) / o.0 as i128) as i64)
    }
    /// Multiply by a plain integer scalar (exact, cheap).
    #[inline]
    pub fn muli(self, i: i64) -> Fx {
        Fx(self.0 * i)
    }
    #[inline]
    pub fn divi(self, i: i64) -> Fx {
        Fx(self.0 / i)
    }

    #[inline]
    pub fn abs(self) -> Fx {
        Fx(self.0.abs())
    }

    /// Square root of a non-negative value. Returns 0 for negatives.
    pub fn sqrt(self) -> Fx {
        if self.0 <= 0 {
            return Fx(0);
        }
        // r = isqrt(x << FRAC_BITS)  (see fixed.rs module docs for derivation)
        let v = (self.0 as u128) << FRAC_BITS;
        Fx(isqrt_u128(v) as i64)
    }
}

impl std::ops::Add for Fx {
    type Output = Fx;
    #[inline]
    fn add(self, o: Fx) -> Fx {
        Fx(self.0 + o.0)
    }
}
impl std::ops::Sub for Fx {
    type Output = Fx;
    #[inline]
    fn sub(self, o: Fx) -> Fx {
        Fx(self.0 - o.0)
    }
}
impl std::ops::Neg for Fx {
    type Output = Fx;
    #[inline]
    fn neg(self) -> Fx {
        Fx(-self.0)
    }
}
impl std::ops::AddAssign for Fx {
    #[inline]
    fn add_assign(&mut self, o: Fx) {
        self.0 += o.0;
    }
}

/// Integer square root (floor) over u128 via Newton's method.
pub fn isqrt_u128(n: u128) -> u128 {
    if n == 0 {
        return 0;
    }
    // initial guess: 2^(ceil(bits/2))
    let bits = 128 - n.leading_zeros();
    let mut x = 1u128 << ((bits + 1) / 2);
    loop {
        let y = (x + n / x) >> 1;
        if y >= x {
            return x;
        }
        x = y;
    }
}

/// Fixed-point 2D vector helper used throughout the engine.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub struct V2 {
    pub x: Fx,
    pub y: Fx,
}

impl V2 {
    pub const fn new(x: Fx, y: Fx) -> V2 {
        V2 { x, y }
    }
    #[inline]
    pub fn sub(self, o: V2) -> V2 {
        V2::new(self.x - o.x, self.y - o.y)
    }
    #[inline]
    pub fn add(self, o: V2) -> V2 {
        V2::new(self.x + o.x, self.y + o.y)
    }
    /// Squared length (cheap; use for range comparisons — avoids a sqrt).
    #[inline]
    pub fn len_sq(self) -> Fx {
        self.x.mul(self.x) + self.y.mul(self.y)
    }
    pub fn len(self) -> Fx {
        self.len_sq().sqrt()
    }
    /// Unit-ish direction scaled by `step`. Returns zero vector if len ~ 0.
    pub fn step_toward(self, step: Fx) -> V2 {
        let l = self.len();
        if l.0 <= 0 {
            return V2::default();
        }
        V2::new(self.x.mul(step).div(l), self.y.mul(step).div(l))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sqrt_two() {
        let r = Fx::from_int(2).sqrt().to_f64();
        assert!((r - 1.41421356).abs() < 1e-3, "sqrt2={r}");
    }

    #[test]
    fn mul_div_roundtrip() {
        let a = Fx::from_f64(3.25);
        let b = Fx::from_f64(1.5);
        assert!((a.mul(b).to_f64() - 4.875).abs() < 1e-3);
        assert!((a.div(b).to_f64() - 2.1666).abs() < 1e-3);
    }

    #[test]
    fn step_toward_len() {
        let d = V2::new(Fx::from_int(3), Fx::from_int(4)); // len 5
        let s = d.step_toward(Fx::from_f64(1.0));
        let l = s.len().to_f64();
        assert!((l - 1.0).abs() < 1e-2, "stepped len={l}");
    }
}
