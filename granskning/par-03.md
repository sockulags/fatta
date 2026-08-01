# Par 03 — memchr

Vilken av A och B skulle vara svårast att skriva om korrekt från grunden, om du
bara hade dess signatur och kontraktsgrannskapet nedan att gå på?

Svara A eller B i granskningsarket. Titta inte i `facit.json` förrän alla par är
besvarade.

## A

```rust
pub unsafe fn is_equal_raw(
    mut x: *const u8,
    mut y: *const u8,
    mut n: usize,
) -> bool {
    // When we have 4 or more bytes to compare, then proceed in chunks of 4 at
    // a time using unaligned loads.
    //
    // Also, why do 4 byte loads instead of, say, 8 byte loads? The reason is
    // that this particular version of memcmp is likely to be called with tiny
    // needles. That means that if we do 8 byte loads, then a higher proportion
    // of memcmp calls will use the slower variant above. With that said, this
    // is a hypothesis and is only loosely supported by benchmarks. There's
    // likely some improvement that could be made here. The main thing here
    // though is to optimize for latency, not throughput.

    // SAFETY: The caller is responsible for ensuring the pointers we get are
    // valid and readable for at least `n` bytes. We also do unaligned loads,
    // so there's no need to ensure we're aligned. (This is justified by this
    // routine being specifically for short strings.)
    while n >= 4 {
        let vx = x.cast::<u32>().read_unaligned();
        let vy = y.cast::<u32>().read_unaligned();
        if vx != vy {
            return false;
        }
        x = x.add(4);
        y = y.add(4);
        n -= 4;
    }
    // If we don't have enough bytes to do 4-byte at a time loads, then
    // do partial loads. Note that I used to have a byte-at-a-time
    // loop here and that turned out to be quite a bit slower for the
    // memmem/pathological/defeat-simple-vector-alphabet benchmark.
    if n >= 2 {
        let vx = x.cast::<u16>().read_unaligned();
        let vy = y.cast::<u16>().read_unaligned();
        if vx != vy {
            return false;
        }
        x = x.add(2);
        y = y.add(2);
        n -= 2;
    }
    if n > 0 {
        if x.read() != y.read() {
            return false;
        }
    }
    true
}
```

### Kontraktsgrannskap för A

_Inga lokala beroenden — allt i signaturen är välkänt._

## B

```rust
pub fn find_iter<'h, 'n, N: 'n + ?Sized + AsRef<[u8]>>(
    haystack: &'h [u8],
    needle: &'n N,
) -> FindIter<'h, 'n> {
    FindIter::new(haystack, Finder::new(needle))
}
```

### Kontraktsgrannskap för B

```rust
A bitset used to track whether a particular byte exists in a needle or not.

Namely, bit 'i' is set if and only if byte%64==i for any byte in the
needle. If a particular byte in the haystack is NOT in this set, then one
can conclude that it is also not in the needle, and thus, one can advance
in the haystack by needle.len() bytes.
struct ApproximateByteSet(u64);

A specialized copy-on-write byte string.

The purpose of this type is to permit usage of a "borrowed or owned
byte string" in a way that keeps std/no-std compatibility. That is, in
no-std/alloc mode, this type devolves into a simple &[u8] with no owned
variant available. We can't just use a plain Cow because Cow is not in
core.
pub struct CowBytes<'a>(Imp<'a>);

An iterator over non-overlapping substring matches.

Matches are reported by the byte offset at which they begin.

`'h` is the lifetime of the haystack while `'n` is the lifetime of the
needle.
pub struct FindIter<'h, 'n> {
    haystack: &'h [u8],
    prestate: PrefilterState,
    finder: Finder<'n>,
    pos: usize,
}

A forward substring searcher that uses the Two-Way algorithm.
pub struct Finder(TwoWay);

A forward substring searcher using the Rabin-Karp algorithm.

Note that, as a lower level API, a `Finder` does not have access to the
needle it was constructed with. For this reason, executing a search
with a `Finder` requires passing both the needle and the haystack,
where the needle is exactly equivalent to the one given to the `Finder`
at construction time. This design was chosen so that callers can have
more precise control over where and how many times a needle is stored.
For example, in cases where Rabin-Karp is just one of several possible
substring search algorithms.
pub struct Finder {
    /// The actual hash.
    hash: Hash,
    /// The factor needed to multiply a byte by in order to subtract it from
    /// the hash. It is defined to be 2^(n-1) (using wrapping exponentiation),
    /// where n is the length of the needle. This is how we "remove" a byte
    /// from the hash once the hash window rolls past it.
    hash_2pow: u32,
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

A single substring searcher fixed to a particular needle.

The purpose of this type is to permit callers to construct a substring
searcher that can be used to search haystacks without the overhead of
constructing the searcher in the first place. This is a somewhat niche
concern when it's necessary to re-use the same needle to search multiple
different haystacks with as little overhead as possible. In general, using
[`find`] is good enough, but `Finder` is useful when you can meaningfully
observe searcher construction time in a profile.

When the `std` feature is enabled, then this type has an `into_owned`
version which permits building a `Finder` that is not connected to
the lifetime of its needle.
pub struct Finder<'n> {
    needle: CowBytes<'n>,
    searcher: Searcher,
}

A Rabin-Karp hash. This might represent the hash of a needle, or the hash
of a rolling window in the haystack.
struct Hash(u32);

enum Imp<'a> {
    Borrowed(&'a [u8]),
    Owned(alloc::boxed::Box<[u8]>),
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

PrefilterState tracks state associated with the effectiveness of a
prefilter. It is used to track how many bytes, on average, are skipped by
the prefilter. If this average dips below a certain threshold over time,
then the state renders the prefilter inert and stops using it.

A prefilter state should be created for each search. (Where creating an
iterator is treated as a single search.) A prefilter state should only be
created from a `Freqy`. e.g., An inert `Freqy` will produce an inert
`PrefilterState`.
pub(crate) struct PrefilterState {
    /// The number of skips that has been executed. This is always 1 greater
    /// than the actual number of skips. The special sentinel value of 0
    /// indicates that the prefilter is inert. This is useful to avoid
    /// additional checks to determine whether the prefilter is still
    /// "effective." Once a prefilter becomes inert, it should no longer be
    /// used (according to our heuristics).
    skips: u32,
    /// The total number of bytes that have been skipped.
    skipped: u32,
}

A "meta" substring searcher.

To a first approximation, this chooses what it believes to be the "best"
substring search implemnetation based on the needle at construction time.
Then, every call to `find` will execute that particular implementation. To
a second approximation, multiple substring search algorithms may be used,
depending on the haystack. For example, for supremely short haystacks,
Rabin-Karp is typically used.

See the documentation on `Prefilter` for an explanation of the dispatching
mechanism. The quick summary is that an enum has too much overhead and
we can't use dynamic dispatch via traits because we need to work in a
core-only environment. (Dynamic dispatch works in core-only, but you
need `&dyn Trait` and we really need a `Box<dyn Trait>` here. The latter
requires `alloc`.) So instead, we use a union and an appropriately paired
free function to read from the correct field on the union and execute the
chosen substring search implementation.
pub(crate) struct Searcher {
    call: SearcherKindFn,
    kind: SearcherKind,
    rabinkarp: rabinkarp::Finder,
}

A union indicating one of several possible substring search implementations
that are in active use.

This union should only be read by one of the functions prefixed with
`searcher_kind_`. Namely, the correct function is meant to be paired with
the union by the caller, such that the function always reads from the
designated union field.
union SearcherKind {
    empty: (),
    one_byte: u8,
    two_way: twoway::Finder,
    two_way_with_prefilter: TwoWayWithPrefilter,
    #[cfg(all(target_arch = "x86_64", target_feature = "sse2"))]
    sse2: crate::arch::x86_64::sse2::packedpair::Finder,
    #[cfg(all(target_arch = "x86_64", target_feature = "sse2"))]
    avx2: crate::arch::x86_64::avx2::packedpair::Finder,
    #[cfg(all(target_arch = "wasm32", target_feature = "simd128"))]
    simd128: crate::arch::wasm32::simd128::packedpair::Finder,
    #[cfg(target_arch = "aarch64")]
    neon: crate::arch::aarch64::neon::packedpair::Finder,
}

A representation of the amount we're allowed to shift by during Two-Way
search.

When computing a critical factorization of the needle, we find the position
of the critical factorization by finding the needle's maximal (or minimal)
suffix, along with the period of that suffix. It turns out that the period
of that suffix is a lower bound on the period of the needle itself.

This lower bound is equivalent to the actual period of the needle in
some cases. To describe that case, we denote the needle as `x` where
`x = uv` and `v` is the lexicographic maximal suffix of `v`. The lower
bound given here is always the period of `v`, which is `<= period(x)`. The
case where `period(v) == period(x)` occurs when `len(u) < (len(x) / 2)` and
where `u` is a suffix of `v[0..period(v)]`.

This case is important because the search algorithm for when the
periods are equivalent is slightly different than the search algorithm
for when the periods are not equivalent. In particular, when they aren't
equivalent, we know that the period of the needle is no less than half its
length. In this case, we shift by an amount less than or equal to the
period of the needle (determined by the maximum length of the components
of the critical factorization of `x`, i.e., `max(len(u), len(v))`)..

The above two cases are represented by the variants below. Each entails
a different instantiation of the Two-Way search algorithm.

N.B. If we could find a way to compute the exact period in all cases,
then we could collapse this case analysis and simplify the algorithm. The
Two-Way paper suggests this is possible, but more reading is required to
grok why the authors didn't pursue that path.
enum Shift {
    Small { period: usize },
    Large { shift: usize },
}

An implementation of the TwoWay substring search algorithm.

This searcher supports forward and reverse search, although not
simultaneously. It runs in `O(n + m)` time and `O(1)` space, where
`n ~ len(needle)` and `m ~ len(haystack)`.

The implementation here roughly matches that which was developed by
Crochemore and Perrin in their 1991 paper "Two-way string-matching." The
changes in this implementation are 1) the use of zero-based indices, 2) a
heuristic skip table based on the last byte (borrowed from Rust's standard
library) and 3) the addition of heuristics for a fast skip loop. For (3),
callers can pass any kind of prefilter they want, but usually it's one
based on a heuristic that uses an approximate background frequency of bytes
to choose rare bytes to quickly look for candidate match positions. Note
though that currently, this prefilter functionality is not exposed directly
in the public API. (File an issue if you want it and provide a use case
please.)

The heuristic for fast skipping is automatically shut off if it's
detected to be ineffective at search time. Generally, this only occurs in
pathological cases. But this is generally necessary in order to preserve
a `O(n + m)` time bound.

The code below is fairly complex and not obviously correct at all. It's
likely necessary to read the Two-Way paper cited above in order to fully
grok this code. The essence of it is:

1. Do something to detect a "critical" position in the needle.
2. For the current position in the haystack, look if `needle[critical..]`
matches at that position.
3. If so, look if `needle[..critical]` matches.
4. If a mismatch occurs, shift the search by some amount based on the
critical position and a pre-computed shift.

This type is wrapped in the forward and reverse finders that expose
consistent forward or reverse APIs.
struct TwoWay {
    /// A small bitset used as a quick prefilter (in addition to any prefilter
    /// given by the caller). Namely, a bit `i` is set if and only if `b%64==i`
    /// for any `b == needle[i]`.
    ///
    /// When used as a prefilter, if the last byte at the current candidate
    /// position is NOT in this set, then we can skip that entire candidate
    /// position (the length of the needle). This is essentially the shift
    /// trick found in Boyer-Moore, but only applied to bytes that don't appear
    /// in the needle.
    ///
    /// N.B. This trick was inspired by something similar in std's
    /// implementation of Two-Way.
    byteset: ApproximateByteSet,
    /// A critical position in needle. Specifically, this position corresponds
    /// to beginning of either the minimal or maximal suffix in needle. (N.B.
    /// See SuffixType below for why "minimal" isn't quite the correct word
    /// here.)
    ///
    /// This is the position at which every search begins. Namely, search
    /// starts by scanning text to the right of this position, and only if
    /// there's a match does the text to the left of this position get scanned.
    critical_pos: usize,
    /// The amount we shift by in the Two-Way search algorithm. This
    /// corresponds to the "small period" and "large period" cases.
    shift: Shift,
}

A two-way substring searcher with a prefilter.
struct TwoWayWithPrefilter {
    finder: twoway::Finder,
    prestrat: Prefilter,
}
```
