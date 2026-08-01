# Par 10 — semver

Vilken av A och B skulle vara svårast att skriva om korrekt från grunden, om du
bara hade dess signatur och kontraktsgrannskapet nedan att gå på?

Svara A eller B i granskningsarket. Titta inte i `facit.json` förrän alla par är
besvarade.

## A

```rust
unsafe fn decode_len(ptr: *const u8) -> NonZeroUsize {
    // SAFETY: There is at least one byte of varint followed by at least 9 bytes
    // of string content, which is at least 10 bytes total for the allocation,
    // so reading the first two is no problem.
    let [first, second] = unsafe { ptr.cast::<[u8; 2]>().read() };
    if second < 0x80 {
        // SAFETY: the length of this heap allocated string has been encoded as
        // one base-128 digit, so the length is at least 9 and at most 127. It
        // cannot be zero.
        unsafe { NonZeroUsize::new_unchecked((first & 0x7f) as usize) }
    } else {
        return unsafe { decode_len_cold(ptr) };

        // Identifiers 128 bytes or longer. This is not exercised by any crate
        // version currently published to crates.io.
        #[cold]
        #[inline(never)]
        unsafe fn decode_len_cold(mut ptr: *const u8) -> NonZeroUsize {
            let mut len = 0;
            let mut shift = 0;
            loop {
                // SAFETY: varint continues while there are bytes having the
                // most significant bit set, i.e. until we start hitting the
                // ASCII string content with msb unset.
                let byte = unsafe { *ptr };
                if byte < 0x80 {
                    // SAFETY: the string length is known to be 128 bytes or
                    // longer.
                    return unsafe { NonZeroUsize::new_unchecked(len) };
                }
                // SAFETY: still in bounds of the same allocation.
                ptr = unsafe { ptr.add(1) };
                len += ((byte & 0x7f) as usize) << shift;
                shift += 7;
            }
        }
    }
}
```

### Kontraktsgrannskap för A

_Inga lokala beroenden — allt i signaturen är välkänt._

## B

```rust
fn bytes_for_varint(len: NonZeroUsize) -> usize {
    let usize_bits = mem::size_of::<usize>() * 8;
    let len_bits = usize_bits - len.leading_zeros() as usize;
    (len_bits + 6) / 7
}
```

### Kontraktsgrannskap för B

_Inga lokala beroenden — allt i signaturen är välkänt._
