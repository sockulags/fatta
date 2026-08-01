//! Domain entities and value objects. No storage concerns, no transport concerns.

use std::collections::BTreeSet;

use conformance::{Date, ListId, TodoId};

use crate::error::{ServiceError, ServiceResult};

/// A title that is known to be non-empty.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Title(String);

impl Title {
    pub fn parse(raw: &str) -> ServiceResult<Self> {
        let trimmed = raw.trim();
        if trimmed.is_empty() {
            return Err(ServiceError::InvalidTitle);
        }
        Ok(Title(trimmed.to_owned()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone)]
pub struct TodoList {
    pub id: ListId,
    pub name: String,
}

#[derive(Debug, Clone)]
pub struct Todo {
    pub id: TodoId,
    pub list: ListId,
    pub parent: Option<TodoId>,
    pub title: Title,
    pub done: bool,
    pub due: Option<Date>,
    pub tags: BTreeSet<String>,
}

impl Todo {
    /// Descendants of `self` within `all`, at any depth.
    pub fn descendants<'a>(&self, all: &'a [Todo]) -> Vec<&'a Todo> {
        let mut found = Vec::new();
        let mut frontier = vec![self.id];
        while let Some(current) = frontier.pop() {
            for todo in all.iter().filter(|t| t.parent == Some(current)) {
                frontier.push(todo.id);
                found.push(todo);
            }
        }
        found
    }
}
