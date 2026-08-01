//! Probe crate with a known answer key.
//!
//! Contains a deliberate pair: a short function with a large footprint and a longer
//! function with a small one. Line count ranks them in the opposite order from CF,
//! which is exactly the inversion the metric exists to catch.

use serde::Serialize;

/// Where in the pipeline an error occurred.
#[derive(Debug, Serialize)]
pub enum Stage {
    Parse,
    Resolve,
    Emit,
}

/// Tunable limits for the analysis.
#[derive(Debug, Serialize)]
pub struct Limits {
    pub max_depth: u32,
    pub max_items: usize,
}

/// The whole run's configuration.
#[derive(Debug, Serialize)]
pub struct Config {
    pub name: String,
    pub limits: Limits,
    pub stage: Stage,
}

impl Config {
    /// A method in an impl block. These are absent from rustdoc's `paths` and thus easy
    /// to lose — in real code they are the majority of all functions.
    pub fn depth(&self) -> u32 {
        self.limits.max_depth
    }
}

/// A report from one run.
#[derive(Debug, Serialize)]
pub struct Report {
    pub visited: usize,
    pub skipped: Vec<String>,
}

/// Short body, large footprint: the signature pulls in Config -> Limits -> Stage and Report.
pub fn run(cfg: &Config) -> Result<Report, String> {
    if cfg.limits.max_depth == 0 {
        return Err(format!("{} har djup 0", cfg.name));
    }
    Ok(Report { visited: cfg.limits.max_items, skipped: Vec::new() })
}

/// A wide record. A caller typically touches a couple of fields, never all of them.
#[derive(Debug, Serialize)]
pub struct Wide {
    pub alpha: u32,
    pub beta: u32,
    pub gamma: u32,
    pub delta: u32,
    pub epsilon: String,
    pub zeta: String,
    pub eta: Vec<String>,
    pub theta: Option<Limits>,
    pub iota: bool,
    pub kappa: u64,
}

/// Opens the wide record but reads only one field.
pub fn peek(wide: &Wide) -> u32 {
    wide.alpha
}

/// Forwards the wide record without opening it at all.
pub fn forward(wide: Wide) -> Wide {
    wide
}

/// Longer body, no footprint: everything in the signature is std and thus costs zero.
pub fn checksum(bytes: &[u8]) -> u64 {
    if bytes.is_empty() {
        return 0;
    }
    let mut acc: u64 = 1469598103934665603;
    for (i, b) in bytes.iter().enumerate() {
        acc ^= *b as u64;
        acc = acc.wrapping_mul(1099511628211);
        if i % 64 == 63 {
            acc = acc.rotate_left(7);
        }
    }
    acc ^ (bytes.len() as u64)
}
