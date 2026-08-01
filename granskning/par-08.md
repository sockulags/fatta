# Par 08 — tokio_util

Vilken av A och B skulle vara svårast att skriva om korrekt från grunden, om du
bara hade dess signatur och kontraktsgrannskapet nedan att gå på?

Svara A eller B i granskningsarket. Titta inte i `facit.json` förrän alla par är
besvarade.

## A

```rust
fn framed<T: AsyncRead + AsyncWrite + Sized>(self, io: T) -> Framed<T, Self>
    where
        Self: Sized,
    {
        Framed::new(io, self)
    }
```

### Kontraktsgrannskap för A

```rust
A unified [`Stream`] and [`Sink`] interface to an underlying I/O object, using
the `Encoder` and `Decoder` traits to encode and decode frames.

You can create a `Framed` instance by using the [`Decoder::framed`] adapter, or
by using the `new` function seen below.

# Cancellation safety

* [`futures_util::sink::SinkExt::send`]: if send is used as the event in a
`tokio::select!` statement and some other branch completes first, then it is
guaranteed that the message was not sent, but the message itself is lost.
* [`tokio_stream::StreamExt::next`]: This method is cancel safe. The returned
future only holds onto a reference to the underlying stream, so dropping it will
never lose a value.

[`Stream`]: futures_core::Stream
[`Sink`]: futures_sink::Sink
[`AsyncRead`]: tokio::io::AsyncRead
[`Decoder::framed`]: crate::codec::Decoder::framed()
[`futures_util::sink::SinkExt::send`]: futures_util::sink::SinkExt::send
[`tokio_stream::StreamExt::next`]: https://docs.rs/tokio-stream/latest/tokio_stream/trait.StreamExt.html#method.next
pin_project! {
    /// A unified [`Stream`] and [`Sink`] interface to an underlying I/O object, using
    /// the `Encoder` and `Decoder` traits to encode and decode frames.
    ///
    /// You can create a `Framed` instance by using the [`Decoder::framed`] adapter, or
    /// by using the `new` function seen below.
    ///
    /// # Cancellation safety
    ///
    /// * [`futures_util::sink::SinkExt::send`]: if send is used as the event in a
    /// `tokio::select!` statement and some other branch completes first, then it is
    /// guaranteed that the message was not sent, but the message itself is lost.
    /// * [`tokio_stream::StreamExt::next`]: This method is cancel safe. The returned
    /// future only holds onto a reference to the underlying stream, so dropping it will
    /// never lose a value.
    ///
    /// [`Stream`]: futures_core::Stream
    /// [`Sink`]: futures_sink::Sink
    /// [`AsyncRead`]: tokio::io::AsyncRead
    /// [`Decoder::framed`]: crate::codec::Decoder::framed()
    /// [`futures_util::sink::SinkExt::send`]: futures_util::sink::SinkExt::send
    /// [`tokio_stream::StreamExt::next`]: https://docs.rs/tokio-stream/latest/tokio_stream/trait.StreamExt.html#method.next
    pub struct Framed<T, U> {
        #[pin]
        inner: FramedImpl<T, U, RWFrames>
    }
}

pin_project! {
    #[derive(Debug)]
    pub(crate) struct FramedImpl<T, U, State> {
        #[pin]
        pub(crate) inner: T,
        pub(crate) state: State,
        pub(crate) codec: U,
    }
}

pub(crate) struct RWFrames {
    pub(crate) read: ReadFrame,
    pub(crate) write: WriteFrame,
}

pub(crate) struct ReadFrame {
    pub(crate) eof: bool,
    pub(crate) is_readable: bool,
    pub(crate) buffer: BytesMut,
    pub(crate) has_errored: bool,
}

pub(crate) struct WriteFrame {
    pub(crate) buffer: BytesMut,
    pub(crate) backpressure_boundary: usize,
}
```

## B

```rust
fn ms(duration: Duration, round: Round) -> u64 {
    const NANOS_PER_MILLI: u32 = 1_000_000;
    const MILLIS_PER_SEC: u64 = 1_000;

    // Round up.
    let millis = match round {
        Round::Up => (duration.subsec_nanos() + NANOS_PER_MILLI - 1) / NANOS_PER_MILLI,
        Round::Down => duration.subsec_millis(),
    };

    duration
        .as_secs()
        .saturating_mul(MILLIS_PER_SEC)
        .saturating_add(u64::from(millis))
}
```

### Kontraktsgrannskap för B

```rust
enum Round {
    Up,
    Down,
}
```
