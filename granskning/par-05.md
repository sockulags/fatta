# Par 05 — semver

Vilken av A och B skulle vara svårast att skriva om korrekt från grunden, om du
bara hade dess signatur och kontraktsgrannskapet nedan att gå på?

Svara A eller B i granskningsarket. Titta inte i `facit.json` förrän alla par är
besvarade.

## A

```rust
fn matches_impl(cmp: &Comparator, ver: &Version) -> bool {
    match cmp.op {
        Op::Exact | Op::Wildcard => matches_exact(cmp, ver),
        Op::Greater => matches_greater(cmp, ver),
        Op::GreaterEq => matches_exact(cmp, ver) || matches_greater(cmp, ver),
        Op::Less => matches_less(cmp, ver),
        Op::LessEq => matches_exact(cmp, ver) || matches_less(cmp, ver),
        Op::Tilde => matches_tilde(cmp, ver),
        Op::Caret => matches_caret(cmp, ver),
    }
}
```

### Kontraktsgrannskap för A

```rust
Optional build metadata identifier. This comes after `+` in a SemVer
version, as in `0.8.1+zstd.1.5.0`.

# Examples

Some real world build metadata idioms drawn from crates.io:

- **[libgit2-sys]** <code>0.12.20+<b>1.1.0</b></code> &mdash; for this
  crate, the build metadata indicates the version of the C libgit2 library
  that the Rust crate is built against.

- **[mashup]** <code>0.1.13+<b>deprecated</b></code> &mdash; just the word
  "deprecated" for a crate that has been superseded by another. Eventually
  people will take notice of this in Cargo's build output where it lists the
  crates being compiled.

- **[google-bigquery2]** <code>2.0.4+<b>20210327</b></code> &mdash; this
  library is automatically generated from an official API schema, and the
  build metadata indicates the date on which that schema was last captured.

- **[fbthrift-git]** <code>0.0.6+<b>c7fcc0e</b></code> &mdash; this crate is
  published from snapshots of a big company monorepo. In monorepo
  development, there is no concept of versions, and all downstream code is
  just updated atomically in the same commit that breaking changes to a
  library are landed. Therefore for crates.io purposes, every published
  version must be assumed to be incompatible with the previous. The build
  metadata provides the source control hash of the snapshotted code.

[libgit2-sys]: https://crates.io/crates/libgit2-sys
[mashup]: https://crates.io/crates/mashup
[google-bigquery2]: https://crates.io/crates/google-bigquery2
[fbthrift-git]: https://crates.io/crates/fbthrift-git

# Syntax

Build metadata is a series of dot separated identifiers immediately
following the patch or pre-release version. Identifiers must comprise only
ASCII alphanumerics and hyphens: `0-9`, `A-Z`, `a-z`, `-`. Identifiers must
not be empty. Leading zeros *are* allowed, unlike any other place in the
SemVer grammar.

# Total ordering

Build metadata is ignored in evaluating `VersionReq`; it plays no role in
whether a `Version` matches any one of the comparison operators.

However for comparing build metadatas among one another, they do have a
total order which is determined by lexicographic ordering of dot-separated
components. Identifiers consisting of only digits are compared numerically.
Otherwise, identifiers are compared in ASCII sort order. Any numeric
identifier is always less than any non-numeric identifier.

Example:&ensp;`demo`&ensp;&lt;&ensp;`demo.85`&ensp;&lt;&ensp;`demo.90`&ensp;&lt;&ensp;`demo.090`&ensp;&lt;&ensp;`demo.200`&ensp;&lt;&ensp;`demo.1a0`&ensp;&lt;&ensp;`demo.a`&ensp;&lt;&ensp;`memo`
pub struct BuildMetadata {
    identifier: Identifier,
}

A pair of comparison operator and partial version, such as `>=1.2`. Forms
one piece of a VersionReq.
pub struct Comparator {
    pub op: Op,
    pub major: u64,
    pub minor: Option<u64>,
    /// Patch is only allowed if minor is Some.
    pub patch: Option<u64>,
    /// Non-empty pre-release is only allowed if patch is Some.
    pub pre: Prerelease,
}

pub(crate) struct Identifier {
    head: NonNull<u8>,
    tail: [u8; TAIL_BYTES],
}

SemVer comparison operator: `=`, `>`, `>=`, `<`, `<=`, `~`, `^`, `*`.

# Op::Exact
- &ensp;**`=I.J.K`**&emsp;&mdash;&emsp;exactly the version I.J.K
- &ensp;**`=I.J`**&emsp;&mdash;&emsp;equivalent to `>=I.J.0, <I.(J+1).0`
- &ensp;**`=I`**&emsp;&mdash;&emsp;equivalent to `>=I.0.0, <(I+1).0.0`

# Op::Greater
- &ensp;**`>I.J.K`**
- &ensp;**`>I.J`**&emsp;&mdash;&emsp;equivalent to `>=I.(J+1).0`
- &ensp;**`>I`**&emsp;&mdash;&emsp;equivalent to `>=(I+1).0.0`

# Op::GreaterEq
- &ensp;**`>=I.J.K`**
- &ensp;**`>=I.J`**&emsp;&mdash;&emsp;equivalent to `>=I.J.0`
- &ensp;**`>=I`**&emsp;&mdash;&emsp;equivalent to `>=I.0.0`

# Op::Less
- &ensp;**`<I.J.K`**
- &ensp;**`<I.J`**&emsp;&mdash;&emsp;equivalent to `<I.J.0`
- &ensp;**`<I`**&emsp;&mdash;&emsp;equivalent to `<I.0.0`

# Op::LessEq
- &ensp;**`<=I.J.K`**
- &ensp;**`<=I.J`**&emsp;&mdash;&emsp;equivalent to `<I.(J+1).0`
- &ensp;**`<=I`**&emsp;&mdash;&emsp;equivalent to `<(I+1).0.0`

# Op::Tilde&emsp;("patch" updates)
*Tilde requirements allow the **patch** part of the semver version (the third number) to increase.*
- &ensp;**`~I.J.K`**&emsp;&mdash;&emsp;equivalent to `>=I.J.K, <I.(J+1).0`
- &ensp;**`~I.J`**&emsp;&mdash;&emsp;equivalent to `=I.J`
- &ensp;**`~I`**&emsp;&mdash;&emsp;equivalent to `=I`

# Op::Caret&emsp;("compatible" updates)
*Caret requirements allow parts that are **right of the first nonzero** part of the semver version to increase.*
- &ensp;**`^I.J.K`**&ensp;(for I\>0)&emsp;&mdash;&emsp;equivalent to `>=I.J.K, <(I+1).0.0`
- &ensp;**`^0.J.K`**&ensp;(for J\>0)&emsp;&mdash;&emsp;equivalent to `>=0.J.K, <0.(J+1).0`
- &ensp;**`^0.0.K`**&emsp;&mdash;&emsp;equivalent to `=0.0.K`
- &ensp;**`^I.J`**&ensp;(for I\>0 or J\>0)&emsp;&mdash;&emsp;equivalent to `^I.J.0`
- &ensp;**`^0.0`**&emsp;&mdash;&emsp;equivalent to `=0.0`
- &ensp;**`^I`**&emsp;&mdash;&emsp;equivalent to `=I`

# Op::Wildcard
- &ensp;**`I.J.*`**&emsp;&mdash;&emsp;equivalent to `=I.J`
- &ensp;**`I.*`**&ensp;or&ensp;**`I.*.*`**&emsp;&mdash;&emsp;equivalent to `=I`
pub enum Op {
    Exact,
    Greater,
    GreaterEq,
    Less,
    LessEq,
    Tilde,
    Caret,
    Wildcard,
}

Optional pre-release identifier on a version string. This comes after `-` in
a SemVer version, like `1.0.0-alpha.1`

# Examples

Some real world pre-release idioms drawn from crates.io:

- **[mio]** <code>0.7.0-<b>alpha.1</b></code> &mdash; the most common style
  for numbering pre-releases.

- **[pest]** <code>1.0.0-<b>beta.8</b></code>,&ensp;<code>1.0.0-<b>rc.0</b></code>
  &mdash; this crate makes a distinction between betas and release
  candidates.

- **[sassers]** <code>0.11.0-<b>shitshow</b></code> &mdash; ???.

- **[atomic-utils]** <code>0.0.0-<b>reserved</b></code> &mdash; a squatted
  crate name.

[mio]: https://crates.io/crates/mio
[pest]: https://crates.io/crates/pest
[atomic-utils]: https://crates.io/crates/atomic-utils
[sassers]: https://crates.io/crates/sassers

*Tip:* Be aware that if you are planning to number your own pre-releases,
you should prefer to separate the numeric part from any non-numeric
identifiers by using a dot in between. That is, prefer pre-releases
`alpha.1`, `alpha.2`, etc rather than `alpha1`, `alpha2` etc. The SemVer
spec's rule for pre-release precedence has special treatment of numeric
components in the pre-release string, but only if there are no non-digit
characters in the same dot-separated component. So you'd have `alpha.2` &lt;
`alpha.11` as intended, but `alpha11` &lt; `alpha2`.

# Syntax

Pre-release strings are a series of dot separated identifiers immediately
following the patch version. Identifiers must comprise only ASCII
alphanumerics and hyphens: `0-9`, `A-Z`, `a-z`, `-`. Identifiers must not be
empty. Numeric identifiers must not include leading zeros.

# Total ordering

Pre-releases have a total order defined by the SemVer spec. It uses
lexicographic ordering of dot-separated components. Identifiers consisting
of only digits are compared numerically. Otherwise, identifiers are compared
in ASCII sort order. Any numeric identifier is always less than any
non-numeric identifier.

Example:&ensp;`alpha`&ensp;&lt;&ensp;`alpha.85`&ensp;&lt;&ensp;`alpha.90`&ensp;&lt;&ensp;`alpha.200`&ensp;&lt;&ensp;`alpha.0a`&ensp;&lt;&ensp;`alpha.1a0`&ensp;&lt;&ensp;`alpha.a`&ensp;&lt;&ensp;`beta`
pub struct Prerelease {
    identifier: Identifier,
}

**SemVer version** as defined by <https://semver.org>.

# Syntax

- The major, minor, and patch numbers may be any integer 0 through u64::MAX.
  When representing a SemVer version as a string, each number is written as
  a base 10 integer. For example, `1.0.119`.

- Leading zeros are forbidden in those positions. For example `1.01.00` is
  invalid as a SemVer version.

- The pre-release identifier, if present, must conform to the syntax
  documented for [`Prerelease`].

- The build metadata, if present, must conform to the syntax documented for
  [`BuildMetadata`].

- Whitespace is not allowed anywhere in the version.

# Total ordering

Given any two SemVer versions, one is less than, greater than, or equal to
the other. Versions may be compared against one another using Rust's usual
comparison operators.

- The major, minor, and patch number are compared numerically from left to
  right, lexicographically ordered as a 3-tuple of integers. So for example
  version `1.5.0` is less than version `1.19.0`, despite the fact that
  "1.19.0" &lt; "1.5.0" as ASCIIbetically compared strings and 1.19 &lt; 1.5
  as real numbers.

- When major, minor, and patch are equal, a pre-release version is
  considered less than the ordinary release:&ensp;version `1.0.0-alpha.1` is
  less than version `1.0.0`.

- Two pre-releases of the same major, minor, patch are compared by
  lexicographic ordering of dot-separated components of the pre-release
  string.

  - Identifiers consisting of only digits are compared
    numerically:&ensp;`1.0.0-pre.8` is less than `1.0.0-pre.12`.

  - Identifiers that contain a letter or hyphen are compared in ASCII sort
    order:&ensp;`1.0.0-pre12` is less than `1.0.0-pre8`.

  - Any numeric identifier is always less than any non-numeric
    identifier:&ensp;`1.0.0-pre.1` is less than `1.0.0-pre.x`.

Example:&ensp;`1.0.0-alpha`&ensp;&lt;&ensp;`1.0.0-alpha.1`&ensp;&lt;&ensp;`1.0.0-alpha.beta`&ensp;&lt;&ensp;`1.0.0-beta`&ensp;&lt;&ensp;`1.0.0-beta.2`&ensp;&lt;&ensp;`1.0.0-beta.11`&ensp;&lt;&ensp;`1.0.0-rc.1`&ensp;&lt;&ensp;`1.0.0`
pub struct Version {
    pub major: u64,
    pub minor: u64,
    pub patch: u64,
    pub pre: Prerelease,
    pub build: BuildMetadata,
}
```

## B

```rust
fn numeric_identifier(input: &str, pos: Position) -> Result<(u64, &str), Error> {
    let mut len = 0;
    let mut value = 0u64;

    while let Some(&digit) = input.as_bytes().get(len) {
        if digit < b'0' || digit > b'9' {
            break;
        }
        if value == 0 && len > 0 {
            return Err(Error::new(ErrorKind::LeadingZero(pos)));
        }
        match value
            .checked_mul(10)
            .and_then(|value| value.checked_add((digit - b'0') as u64))
        {
            Some(sum) => value = sum,
            None => return Err(Error::new(ErrorKind::Overflow(pos))),
        }
        len += 1;
    }

    if len > 0 {
        Ok((value, &input[len..]))
    } else if let Some(unexpected) = input[len..].chars().next() {
        Err(Error::new(ErrorKind::UnexpectedChar(pos, unexpected)))
    } else {
        Err(Error::new(ErrorKind::UnexpectedEnd(pos)))
    }
}
```

### Kontraktsgrannskap för B

```rust
Error parsing a SemVer version or version requirement.

# Example

```
use semver::Version;

fn main() {
    let err = Version::parse("1.q.r").unwrap_err();

    // "unexpected character 'q' while parsing minor version number"
    eprintln!("{}", err);
}
```
pub struct Error {
    pub(crate) kind: ErrorKind,
}

pub(crate) enum ErrorKind {
    Empty,
    UnexpectedEnd(Position),
    UnexpectedChar(Position, char),
    UnexpectedCharAfter(Position, char),
    ExpectedCommaFound(Position, char),
    LeadingZero(Position),
    Overflow(Position),
    EmptySegment(Position),
    IllegalCharacter(Position),
    WildcardNotTheOnlyComparator(char),
    UnexpectedAfterWildcard,
    ExcessiveComparators,
}

pub(crate) enum Position {
    Major,
    Minor,
    Patch,
    Pre,
    Build,
}
```
