//! Sondkrets med känt facit.
//!
//! Innehåller ett medvetet par: en kort funktion med stort fotavtryck och en längre
//! funktion med litet. Radantal rankar dem i motsatt ordning mot CF, vilket är precis
//! den inversion måttet finns för att fånga.

use serde::Serialize;

/// Var i pipelinen ett fel uppstod.
#[derive(Debug, Serialize)]
pub enum Stage {
    Parse,
    Resolve,
    Emit,
}

/// Justerbara gränser för analysen.
#[derive(Debug, Serialize)]
pub struct Limits {
    pub max_depth: u32,
    pub max_items: usize,
}

/// Hela körningens konfiguration.
#[derive(Debug, Serialize)]
pub struct Config {
    pub name: String,
    pub limits: Limits,
    pub stage: Stage,
}

impl Config {
    /// Metod i ett impl-block. Sådana saknas i rustdocs `paths` och är därför lätta att
    /// tappa bort — i riktig kod är de merparten av alla funktioner.
    pub fn depth(&self) -> u32 {
        self.limits.max_depth
    }
}

/// Rapport från en körning.
#[derive(Debug, Serialize)]
pub struct Report {
    pub visited: usize,
    pub skipped: Vec<String>,
}

/// Kort kropp, stort fotavtryck: signaturen drar in Config -> Limits -> Stage och Report.
pub fn run(cfg: &Config) -> Result<Report, String> {
    if cfg.limits.max_depth == 0 {
        return Err(format!("{} har djup 0", cfg.name));
    }
    Ok(Report { visited: cfg.limits.max_items, skipped: Vec::new() })
}

/// Bred post. En anropare rör typiskt ett par fält, aldrig alla.
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

/// Öppnar den breda posten men läser bara ett fält.
pub fn peek(wide: &Wide) -> u32 {
    wide.alpha
}

/// Skickar den breda posten vidare utan att öppna den alls.
pub fn forward(wide: Wide) -> Wide {
    wide
}

/// Längre kropp, inget fotavtryck: allt i signaturen är std och kostar därför noll.
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
