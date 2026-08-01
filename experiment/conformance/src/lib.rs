//! The contract both implementations must satisfy, and the suite that checks it.
//!
//! Everything shared lives here so the two implementations differ only in how they
//! organise the work behind this surface. Both pay the same cost for these types when
//! measured, which keeps the comparison about structure.

use std::collections::BTreeSet;
use std::fmt;

pub mod suite;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ListId(pub i64);

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct TodoId(pub i64);

/// Deliberately dependency-free. Field order gives the correct chronological ordering
/// for free through the derived comparison.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Date {
    pub year: i32,
    pub month: u8,
    pub day: u8,
}

impl Date {
    pub fn new(year: i32, month: u8, day: u8) -> Self {
        Self { year, month, day }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TodoView {
    pub id: TodoId,
    pub title: String,
    pub done: bool,
    pub due: Option<Date>,
    pub tags: BTreeSet<String>,
    pub children: Vec<TodoView>,
}

/// Filters combine with AND. An empty query matches every todo in every list.
#[derive(Debug, Clone, Default)]
pub struct Query {
    pub list: Option<ListId>,
    pub tag: Option<String>,
    pub done: Option<bool>,
    pub due_before: Option<Date>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error {
    NoSuchList(ListId),
    NoSuchTodo(TodoId),
    /// A todo may not be completed while any descendant is still open.
    OpenChildren { todo: TodoId, open: usize },
    /// Moving a todo under its own descendant would create a cycle.
    WouldCycle { todo: TodoId, parent: TodoId },
    EmptyTitle,
    Storage(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::NoSuchList(id) => write!(f, "no such list: {}", id.0),
            Error::NoSuchTodo(id) => write!(f, "no such todo: {}", id.0),
            Error::OpenChildren { todo, open } => {
                write!(f, "todo {} still has {} open descendants", todo.0, open)
            }
            Error::WouldCycle { todo, parent } => {
                write!(f, "todo {} cannot be moved under {}", todo.0, parent.0)
            }
            Error::EmptyTitle => write!(f, "title must not be empty"),
            Error::Storage(msg) => write!(f, "storage failure: {msg}"),
        }
    }
}

impl std::error::Error for Error {}

pub type Result<T> = std::result::Result<T, Error>;

/// What a todo backend must be able to do.
///
/// The nesting is what makes this worth measuring: subtasks are todos, arbitrarily
/// deep, and the completion rule has to hold across the whole subtree.
pub trait TodoApi {
    fn create_list(&mut self, name: &str) -> Result<ListId>;

    /// Adds a todo to a list, optionally under an existing todo in that same list.
    fn add(
        &mut self,
        list: ListId,
        parent: Option<TodoId>,
        title: &str,
        due: Option<Date>,
    ) -> Result<TodoId>;

    /// Fails with [`Error::OpenChildren`] if any descendant is still open.
    fn complete(&mut self, todo: TodoId) -> Result<()>;

    fn reopen(&mut self, todo: TodoId) -> Result<()>;

    fn tag(&mut self, todo: TodoId, tag: &str) -> Result<()>;

    /// Reparents a todo within its list. Rejects cycles.
    fn move_under(&mut self, todo: TodoId, parent: Option<TodoId>) -> Result<()>;

    /// The full tree of a list, roots first, each with its descendants nested.
    fn tree(&self, list: ListId) -> Result<Vec<TodoView>>;

    /// Matching todos as a flat list, without their children, ordered by id.
    fn search(&self, query: &Query) -> Result<Vec<TodoView>>;
}
