# Par 07 — memchr

Vilken av A och B skulle vara svårast att skriva om korrekt från grunden, om du
bara hade dess signatur och kontraktsgrannskapet nedan att gå på?

Svara A eller B i granskningsarket. Titta inte i `facit.json` förrän alla par är
besvarade.

## A

```rust
pub unsafe fn find_raw(
        &self,
        start: *const u8,
        end: *const u8,
    ) -> Option<*const u8> {
        if start >= end {
            return None;
        }
        if end.distance(start) < __m128i::BYTES {
            // SAFETY: We require the caller to pass valid start/end pointers.
            return generic::fwd_byte_by_byte(start, end, |b| {
                b == self.0.needle1()
                    || b == self.0.needle2()
                    || b == self.0.needle3()
            });
        }
        // SAFETY: Building a `Three` means it's safe to call 'sse2' routines.
        // Also, we've checked that our haystack is big enough to run on the
        // vector routine. Pointer validity is caller's responsibility.
        //
        // Note that we could call `self.0.find_raw` directly here. But that
        // means we'd have to annotate this routine with `target_feature`.
        // Which is fine, because this routine is `unsafe` anyway and the
        // `target_feature` obligation is met by virtue of building a `Three`.
        // The real problem is that a routine with a `target_feature`
        // annotation generally can't be inlined into caller code unless the
        // caller code has the same target feature annotations. Which is maybe
        // okay for SSE2, but we do the same thing for AVX2 where caller code
        // probably usually doesn't have AVX2 enabled. That means that this
        // routine can be inlined which will handle some of the short-haystack
        // cases above without touching the architecture specific code.
        self.find_raw_impl(start, end)
    }
```

### Kontraktsgrannskap för A

_Inga lokala beroenden — allt i signaturen är välkänt._

## B

```rust
unsafe fn prefilter_kind_avx2(
    strat: &Prefilter,
    haystack: &[u8],
) -> Option<usize> {
    let finder = &strat.kind.avx2;
    if haystack.len() < finder.min_haystack_len() {
        strat.find_simple(haystack)
    } else {
        finder.find_prefilter(haystack)
    }
}
```

### Kontraktsgrannskap för B

```rust
An architecture independent "packed pair" finder.

This finder picks two bytes that it believes have high predictive power for
indicating an overall match of a needle. At search time, it reports offsets
where the needle could match based on whether the pair of bytes it chose
match.

This is architecture independent because it utilizes `memchr` to find the
occurrence of one of the bytes in the pair, and then checks whether the
second byte matches. If it does, in the case of [`Finder::find_prefilter`],
the location at which the needle could match is returned.

It is generally preferred to use architecture specific routines for a
"packed pair" prefilter, but this can be a useful fallback when the
architecture independent routines are unavailable.
pub struct Finder {
    pair: Pair,
    byte1: u8,
    byte2: u8,
}

A "packed pair" finder that uses 128-bit vector operations.

This finder picks two bytes that it believes have high predictive power
for indicating an overall match of a needle. Depending on whether
`Finder::find` or `Finder::find_prefilter` is used, it reports offsets
where the needle matches or could match. In the prefilter case, candidates
are reported whenever the [`Pair`] of bytes given matches.
pub struct Finder(packedpair::Finder<__m128i>);

A generic architecture dependent "packed pair" finder.

This finder picks two bytes that it believes have high predictive power
for indicating an overall match of a needle. Depending on whether
`Finder::find` or `Finder::find_prefilter` is used, it reports offsets
where the needle matches or could match. In the prefilter case, candidates
are reported whenever the [`Pair`] of bytes given matches.

This is architecture dependent because it uses specific vector operations
to look for occurrences of the pair of bytes.

This type is not meant to be exported and is instead meant to be used as
the implementation for architecture specific facades. Why? Because it's a
bit of a quirky API that requires `inline(always)` annotations. And pretty
much everything has safety obligations due (at least) to the caller needing
to inline calls into routines marked with
`#[target_feature(enable = "...")]`.
pub(crate) struct Finder<V> {
    pair: Pair,
    v1: V,
    v2: V,
    min_haystack_len: usize,
}

A "packed pair" finder that uses 256-bit vector operations.

This finder picks two bytes that it believes have high predictive power
for indicating an overall match of a needle. Depending on whether
`Finder::find` or `Finder::find_prefilter` is used, it reports offsets
where the needle matches or could match. In the prefilter case, candidates
are reported whenever the [`Pair`] of bytes given matches.
pub struct Finder {
    sse2: packedpair::Finder<__m128i>,
    avx2: packedpair::Finder<__m256i>,
}

A pair of byte offsets into a needle to use as a predicate.

This pair is used as a predicate to quickly filter out positions in a
haystack in which a needle cannot match. In some cases, this pair can even
be used in vector algorithms such that the vector algorithm only switches
over to scalar code once this pair has been found.

A pair of offsets can be used in both substring search implementations and
in prefilters. The former will report matches of a needle in a haystack
where as the latter will only report possible matches of a needle.

The offsets are limited each to a maximum of 255 to keep memory usage low.
Moreover, it's rarely advantageous to create a predicate using offsets
greater than 255 anyway.

The only guarantee enforced on the pair of offsets is that they are not
equivalent. It is not necessarily the case that `index1 < index2` for
example. By convention, `index1` corresponds to the byte in the needle
that is believed to be most the predictive. Note also that because of the
requirement that the indices be both valid for the needle used to build
the pair and not equal, it follows that a pair can only be constructed for
needles with length at least 2.
pub struct Pair {
    index1: u8,
    index2: u8,
}

The implementation of a prefilter.

This type encapsulates dispatch to one of several possible choices for a
prefilter. Generally speaking, all prefilters have the same approximate
algorithm: they choose a couple of bytes from the needle that are believed
to be rare, use a fast vector algorithm to look for those bytes and return
positions as candidates for some substring search algorithm (currently only
Two-Way) to confirm as a match or not.

The differences between the algorithms are actually at the vector
implementation level. Namely, we need different routines based on both
which target architecture we're on and what CPU features are supported.

The straight-forwardly obvious approach here is to use an enum, and make
`Prefilter::find` do case analysis to determine which algorithm was
selected and invoke it. However, I've observed that this leads to poor
codegen in some cases, especially in latency sensitive benchmarks. That is,
this approach comes with overhead that I wasn't able to eliminate.

The second obvious approach is to use dynamic dispatch with traits. Doing
that in this context where `Prefilter` owns the selection generally
requires heap allocation, and this code is designed to run in core-only
environments.

So we settle on using a union (that's `PrefilterKind`) and a function
pointer (that's `PrefilterKindFn`). We select the right function pointer
based on which field in the union we set, and that function in turn
knows which field of the union to access. The downside of this approach
is that it forces us to think about safety, but the upside is that
there are some nice latency improvements to benchmarks. (Especially the
`memmem/sliceslice/short` benchmark.)

In cases where we've selected a vector algorithm and the haystack given
is too short, we fallback to the scalar version of `memchr` on the
`rarest_byte`. (The scalar version of `memchr` is still better than a naive
byte-at-a-time loop because it will read in `usize`-sized chunks at a
time.)
struct Prefilter {
    call: PrefilterKindFn,
    kind: PrefilterKind,
    rarest_byte: u8,
    rarest_offset: u8,
}

A union indicating one of several possible prefilters that are in active
use.

This union should only be read by one of the functions prefixed with
`prefilter_kind_`. Namely, the correct function is meant to be paired with
the union by the caller, such that the function always reads from the
designated union field.
union PrefilterKind {
    fallback: crate::arch::all::packedpair::Finder,
    #[cfg(all(target_arch = "x86_64", target_feature = "sse2"))]
    sse2: crate::arch::x86_64::sse2::packedpair::Finder,
    #[cfg(all(target_arch = "x86_64", target_feature = "sse2"))]
    avx2: crate::arch::x86_64::avx2::packedpair::Finder,
    #[cfg(all(target_arch = "wasm32", target_feature = "simd128"))]
    simd128: crate::arch::wasm32::simd128::packedpair::Finder,
    #[cfg(target_arch = "aarch64")]
    neon: crate::arch::aarch64::neon::packedpair::Finder,
}
```
