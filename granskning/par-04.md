# Par 04 — tokio_util

Vilken av A och B skulle vara svårast att skriva om korrekt från grunden, om du
bara hade dess signatur och kontraktsgrannskapet nedan att gå på?

Svara A eller B i granskningsarket. Titta inte i `facit.json` förrän alla par är
besvarade.

## A

```rust
pub fn poll_read_buf<T: AsyncRead + ?Sized, B: BufMut>(
    io: Pin<&mut T>,
    cx: &mut Context<'_>,
    buf: &mut B,
) -> Poll<io::Result<usize>> {
    if !buf.has_remaining_mut() {
        return Poll::Ready(Ok(0));
    }

    let n = {
        let dst = buf.chunk_mut();

        // Safety: `chunk_mut()` returns a `&mut UninitSlice`, and `UninitSlice` is a
        // transparent wrapper around `[MaybeUninit<u8>]`.
        let dst = unsafe { dst.as_uninit_slice_mut() };
        let mut buf = ReadBuf::uninit(dst);
        let ptr = buf.filled().as_ptr();
        ready!(io.poll_read(cx, &mut buf)?);

        // Ensure the pointer does not change from under us
        assert_eq!(ptr, buf.filled().as_ptr());
        buf.filled().len()
    };

    // Safety: This is guaranteed to be the number of initialized (and read)
    // bytes due to the invariants provided by `ReadBuf::filled`.
    unsafe {
        buf.advance_mut(n);
    }

    Poll::Ready(Ok(n))
}
```

### Kontraktsgrannskap för A

_Inga lokala beroenden — allt i signaturen är välkänt._

## B

```rust
pub fn track_future<F: Future>(&self, future: F) -> TrackedFuture<F> {
        TrackedFuture {
            future,
            token: self.token(),
        }
    }
```

### Kontraktsgrannskap för B

```rust
A task tracker used for waiting until tasks exit.

This is usually used together with [`CancellationToken`] to implement [graceful shutdown]. The
`CancellationToken` is used to signal to tasks that they should shut down, and the
`TaskTracker` is used to wait for them to finish shutting down.

The `TaskTracker` will also keep track of a `closed` boolean. This is used to handle the case
where the `TaskTracker` is empty, but we don't want to shut down yet. This means that the
[`wait`] method will wait until *both* of the following happen at the same time:

 * The `TaskTracker` must be closed using the [`close`] method.
 * The `TaskTracker` must be empty, that is, all tasks that it is tracking must have exited.

When a call to [`wait`] returns, it is guaranteed that all tracked tasks have exited and that
the destructor of the future has finished running. However, there might be a short amount of
time where [`JoinHandle::is_finished`] returns false.

# Comparison to `JoinSet`

The main Tokio crate has a similar collection known as [`JoinSet`]. The `JoinSet` type has a
lot more features than `TaskTracker`, so `TaskTracker` should only be used when one of its
unique features is required:

 1. When tasks exit, a `TaskTracker` will allow the task to immediately free its memory.
 2. By not closing the `TaskTracker`, [`wait`] will be prevented from returning even if
    the `TaskTracker` is empty.
 3. A `TaskTracker` does not require mutable access to insert tasks.
 4. A `TaskTracker` can be cloned to share it with many tasks.

The first point is the most important one. A [`JoinSet`] keeps track of the return value of
every inserted task. This means that if the caller keeps inserting tasks and never calls
[`join_next`], then their return values will keep building up and consuming memory, _even if_
most of the tasks have already exited. This can cause the process to run out of memory. With a
`TaskTracker`, this does not happen. Once tasks exit, they are immediately removed from the
`TaskTracker`.

Note that unlike [`JoinSet`], dropping a `TaskTracker` does not abort the tasks.

# Examples

For more examples, please see the topic page on [graceful shutdown].

## Spawn tasks and wait for them to exit

This is a simple example. For this case, [`JoinSet`] should probably be used instead.

```
use tokio_util::task::TaskTracker;

# #[tokio::main(flavor = "current_thread")]
# async fn main() {
let tracker = TaskTracker::new();

for i in 0..10 {
    tracker.spawn(async move {
        println!("Task {} is running!", i);
    });
}
// Once we spawned everything, we close the tracker.
tracker.close();

// Wait for everything to finish.
tracker.wait().await;

println!("This is printed after all of the tasks.");
# }
```

## Wait for tasks to exit

This example shows the intended use-case of `TaskTracker`. It is used together with
[`CancellationToken`] to implement graceful shutdown.
```
use tokio_util::sync::CancellationToken;
use tokio_util::task::TaskTracker;
use tokio_util::time::FutureExt;

use tokio::time::{self, Duration};

async fn background_task(num: u64) {
    for i in 0..10 {
        time::sleep(Duration::from_millis(100*num)).await;
        println!("Background task {} in iteration {}.", num, i);
    }
}

#[tokio::main]
# async fn _hidden() {}
# #[tokio::main(flavor = "current_thread", start_paused = true)]
async fn main() {
    let tracker = TaskTracker::new();
    let token = CancellationToken::new();

    for i in 0..10 {
        let token = token.clone();
        tracker.spawn(async move {
            // Use a `with_cancellation_token_owned` to kill the background task
            // if the token is cancelled.
            match background_task(i)
                .with_cancellation_token_owned(token)
                .await
            {
                Some(()) => println!("Task {} exiting normally.", i),
                None => {
                    // Do some cleanup before we really exit.
                    time::sleep(Duration::from_millis(50)).await;
                    println!("Task {} finished cleanup.", i);
                }
            }
        });
    }

    // Spawn a background task that will send the shutdown signal.
    {
        let tracker = tracker.clone();
        tokio::spawn(async move {
            // Normally you would use something like ctrl-c instead of
            // sleeping.
            time::sleep(Duration::from_secs(2)).await;
            tracker.close();
            token.cancel();
        });
    }

    // Wait for all tasks to exit.
    tracker.wait().await;

    println!("All tasks have exited now.");
}
```

[`CancellationToken`]: crate::sync::CancellationToken
[`JoinHandle::is_finished`]: tokio::task::JoinHandle::is_finished
[`JoinSet`]: tokio::task::JoinSet
[`close`]: Self::close
[`join_next`]: tokio::task::JoinSet::join_next
[`wait`]: Self::wait
[graceful shutdown]: https://tokio.rs/tokio/topics/shutdown
pub struct TaskTracker {
    inner: Arc<TaskTrackerInner>,
}

struct TaskTrackerInner {
    /// Keeps track of the state.
    ///
    /// The lowest bit is whether the task tracker is closed.
    ///
    /// The rest of the bits count the number of tracked tasks.
    state: AtomicUsize,
    /// Used to notify when the last task exits.
    on_last_exit: Notify,
}

Represents a task tracked by a [`TaskTracker`].
pub struct TaskTrackerToken {
    task_tracker: TaskTracker,
}

A future that is tracked as a task by a [`TaskTracker`].

The associated [`TaskTracker`] cannot complete until this future is dropped.

This future is returned by [`TaskTracker::track_future`].
pin_project! {
    /// A future that is tracked as a task by a [`TaskTracker`].
    ///
    /// The associated [`TaskTracker`] cannot complete until this future is dropped.
    ///
    /// This future is returned by [`TaskTracker::track_future`].
    #[must_use = "futures do nothing unless polled"]
    pub struct TrackedFuture<F> {
        #[pin]
        future: F,
        token: TaskTrackerToken,
    }
}
```
