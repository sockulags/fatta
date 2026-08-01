//! Transport shapes. What crosses the boundary in and out of the service.

use conformance::{Date, ListId, TodoId};

#[derive(Debug, Clone)]
pub struct CreateTodoCommand {
    pub list: ListId,
    pub parent: Option<TodoId>,
    pub title: String,
    pub due: Option<Date>,
}

#[derive(Debug, Clone)]
pub struct TodoDto {
    pub id: TodoId,
    pub title: String,
    pub done: bool,
    pub due: Option<Date>,
    pub tags: Vec<String>,
    pub children: Vec<TodoDto>,
}

#[derive(Debug, Clone)]
pub struct ListDto {
    pub id: ListId,
    pub name: String,
}
