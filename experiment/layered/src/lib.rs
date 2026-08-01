//! Todo backend in the conventional layered shape.
//!
//! Handler over service over repository, with a distinct type family at each level:
//! rows for storage, entities for rules, transport objects for the boundary, and
//! mappers between them. Errors are converted upwards one layer at a time.
//!
//! This is the heterogeneous arrangement the measurement is meant to expose: each layer
//! is a different kind of thing, so understanding a leaf means understanding the chain
//! above it.

pub mod api;
pub mod domain;
pub mod dto;
pub mod error;
pub mod mapper;
pub mod repository;
pub mod row;
pub mod service;

pub use api::TodoBackend;
pub use repository::SqliteTodoRepository;

/// A ready-to-use backend over an in-memory database.
pub fn backend() -> conformance::Result<TodoBackend<SqliteTodoRepository>> {
    TodoBackend::in_memory()
}
