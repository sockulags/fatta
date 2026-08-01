//! Conversions between the three shapes: rows, entities and transport objects.

use std::collections::BTreeSet;

use conformance::{Date, ListId, TodoId, TodoView};

use crate::domain::{Title, Todo, TodoList};
use crate::dto::{ListDto, TodoDto};
use crate::error::{ServiceError, ServiceResult};
use crate::row::{ListRow, TodoRow};

pub fn parse_date(raw: &str) -> Option<Date> {
    let mut parts = raw.split('-');
    let year = parts.next()?.parse().ok()?;
    let month = parts.next()?.parse().ok()?;
    let day = parts.next()?.parse().ok()?;
    if parts.next().is_some() {
        return None;
    }
    Some(Date { year, month, day })
}

pub fn format_date(date: Date) -> String {
    format!("{:04}-{:02}-{:02}", date.year, date.month, date.day)
}

pub fn list_from_row(row: ListRow) -> TodoList {
    TodoList {
        id: ListId(row.id),
        name: row.name,
    }
}

pub fn todo_from_row(row: TodoRow, tags: BTreeSet<String>) -> ServiceResult<Todo> {
    Ok(Todo {
        id: TodoId(row.id),
        list: ListId(row.list_id),
        parent: row.parent_id.map(TodoId),
        title: Title::parse(&row.title)?,
        done: row.done != 0,
        due: row.due.as_deref().and_then(parse_date),
        tags,
    })
}

pub fn list_to_dto(list: TodoList) -> ListDto {
    ListDto {
        id: list.id,
        name: list.name,
    }
}

/// Builds the transport tree rooted at `todo` from a flat entity set.
pub fn todo_to_dto(todo: &Todo, all: &[Todo]) -> TodoDto {
    let mut children: Vec<&Todo> = all.iter().filter(|t| t.parent == Some(todo.id)).collect();
    children.sort_by_key(|t| t.id);
    TodoDto {
        id: todo.id,
        title: todo.title.as_str().to_owned(),
        done: todo.done,
        due: todo.due,
        tags: todo.tags.iter().cloned().collect(),
        children: children.iter().map(|c| todo_to_dto(c, all)).collect(),
    }
}

pub fn dto_to_view(dto: TodoDto) -> TodoView {
    TodoView {
        id: dto.id,
        title: dto.title,
        done: dto.done,
        due: dto.due,
        tags: dto.tags.into_iter().collect(),
        children: dto.children.into_iter().map(dto_to_view).collect(),
    }
}

pub fn require_title(raw: &str) -> ServiceResult<Title> {
    Title::parse(raw).map_err(|_: ServiceError| ServiceError::InvalidTitle)
}
