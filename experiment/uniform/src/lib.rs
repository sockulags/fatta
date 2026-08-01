//! Todo backend built from a single uniform structure.
//!
//! There is one kind of thing here: a node with a kind, attributes and children of the
//! same type. Lists are nodes, todos are nodes, subtasks are nodes. Depth costs nothing
//! conceptually, because the rule learned at one level is the rule at every level.
//!
//! The price is visible in `store.rs`: with attributes as data rather than columns, the
//! schema stops carrying meaning and the compiler stops checking it.

pub mod api;
pub mod node;
pub mod store;

pub use api::TodoNodes;

/// A ready-to-use backend over an in-memory database.
pub fn backend() -> conformance::Result<TodoNodes> {
    TodoNodes::in_memory()
}
