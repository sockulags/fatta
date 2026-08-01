# Par 12 — memchr

Vilken av A och B skulle vara svårast att skriva om korrekt från grunden, om du
bara hade dess signatur och kontraktsgrannskapet nedan att gå på?

Svara A eller B i granskningsarket. Titta inte i `facit.json` förrän alla par är
besvarade.

## A

```rust
pub fn is_suffix(haystack: &[u8], needle: &[u8]) -> bool {
    needle.len() <= haystack.len()
        && is_equal(&haystack[haystack.len() - needle.len()..], needle)
}
```

### Kontraktsgrannskap för A

_Inga lokala beroenden — allt i signaturen är välkänt._

## B

```rust
fn do_packed_search(needle: &[u8]) -> bool {
    /// The minimum length of a needle required for this algorithm. The minimum
    /// is 2 since a length of 1 should just use memchr and a length of 0 isn't
    /// a case handled by this searcher.
    const MIN_LEN: usize = 2;

    /// The maximum length of a needle required for this algorithm.
    ///
    /// In reality, there is no hard max here. The code below can handle any
    /// length needle. (Perhaps that suggests there are missing optimizations.)
    /// Instead, this is a heuristic and a bound guaranteeing our linear time
    /// complexity.
    ///
    /// It is a heuristic because when a candidate match is found, memcmp is
    /// run. For very large needles with lots of false positives, memcmp can
    /// make the code run quite slow.
    ///
    /// It is a bound because the worst case behavior with memcmp is
    /// multiplicative in the size of the needle and haystack, and we want
    /// to keep that additive. This bound ensures we still meet that bound
    /// theoretically, since it's just a constant. We aren't acting in bad
    /// faith here, memcmp on tiny needles is so fast that even in pathological
    /// cases (see pathological vector benchmarks), this is still just as fast
    /// or faster in practice.
    ///
    /// This specific number was chosen by tweaking a bit and running
    /// benchmarks. The rare-medium-needle, for example, gets about 5% faster
    /// by using this algorithm instead of a prefilter-accelerated Two-Way.
    /// There's also a theoretical desire to keep this number reasonably
    /// low, to mitigate the impact of pathological cases. I did try 64, and
    /// some benchmarks got a little better, and others (particularly the
    /// pathological ones), got a lot worse. So... 32 it is?
    const MAX_LEN: usize = 32;
    MIN_LEN <= needle.len() && needle.len() <= MAX_LEN
}
```

### Kontraktsgrannskap för B

_Inga lokala beroenden — allt i signaturen är välkänt._
