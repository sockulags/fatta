//! Business layer. Owns the rules, works on entities, and never touches SQL.

use std::collections::{BTreeMap, BTreeSet};

use conformance::{ListId, Query, TodoId};

use crate::domain::{Todo, TodoList};
use crate::dto::{CreateTodoCommand, ListDto, TodoDto};
use crate::error::{RepoError, ServiceError, ServiceResult};
use crate::mapper;
use crate::repository::TodoRepository;
use crate::row::TodoRow;

pub struct TodoService<R: TodoRepository> {
    repo: R,
}

impl<R: TodoRepository> TodoService<R> {
    pub fn new(repo: R) -> Self {
        Self { repo }
    }

    pub fn create_list(&mut self, name: &str) -> ServiceResult<ListDto> {
        let row = self.repo.create_list(name)?;
        Ok(mapper::list_to_dto(mapper::list_from_row(row)))
    }

    pub fn add(&mut self, command: CreateTodoCommand) -> ServiceResult<TodoId> {
        let title = mapper::require_title(&command.title)?;
        self.repo.find_list(command.list)?;

        if let Some(parent) = command.parent {
            let parent_row = self.repo.find_todo(parent)?;
            if parent_row.list_id != command.list.0 {
                return Err(ServiceError::Repo(RepoError::TodoNotFound(parent)));
            }
        }

        let due = command.due.map(mapper::format_date);
        let row = self.repo.insert_todo(
            command.list,
            command.parent,
            title.as_str(),
            due.as_deref(),
        )?;
        Ok(TodoId(row.id))
    }

    pub fn complete(&mut self, id: TodoId) -> ServiceResult<()> {
        let todo = self.load_one(id)?;
        let siblings = self.load_list(todo.list)?;
        let open = todo
            .descendants(&siblings)
            .into_iter()
            .filter(|d| !d.done)
            .count();
        if open > 0 {
            return Err(ServiceError::OpenChildren { todo: id, open });
        }
        self.repo.set_done(id, true)?;
        Ok(())
    }

    pub fn reopen(&mut self, id: TodoId) -> ServiceResult<()> {
        self.repo.find_todo(id)?;
        self.repo.set_done(id, false)?;
        Ok(())
    }

    pub fn tag(&mut self, id: TodoId, tag: &str) -> ServiceResult<()> {
        self.repo.find_todo(id)?;
        self.repo.insert_tag(id, tag)?;
        Ok(())
    }

    pub fn move_under(&mut self, id: TodoId, parent: Option<TodoId>) -> ServiceResult<()> {
        let todo = self.load_one(id)?;

        if let Some(new_parent) = parent {
            if new_parent == id {
                return Err(ServiceError::WouldCycle { todo: id, parent: new_parent });
            }
            let parent_row = self.repo.find_todo(new_parent)?;
            if parent_row.list_id != todo.list.0 {
                return Err(ServiceError::Repo(RepoError::TodoNotFound(new_parent)));
            }
            let siblings = self.load_list(todo.list)?;
            if todo.descendants(&siblings).iter().any(|d| d.id == new_parent) {
                return Err(ServiceError::WouldCycle { todo: id, parent: new_parent });
            }
        }

        self.repo.set_parent(id, parent)?;
        Ok(())
    }

    pub fn tree(&self, list: ListId) -> ServiceResult<Vec<TodoDto>> {
        self.repo.find_list(list)?;
        let todos = self.load_list(list)?;
        let mut roots: Vec<&Todo> = todos.iter().filter(|t| t.parent.is_none()).collect();
        roots.sort_by_key(|t| t.id);
        Ok(roots
            .into_iter()
            .map(|root| mapper::todo_to_dto(root, &todos))
            .collect())
    }

    pub fn search(&self, query: &Query) -> ServiceResult<Vec<TodoDto>> {
        if let Some(list) = query.list {
            self.repo.find_list(list)?;
        }
        let rows = match query.list {
            Some(list) => self.repo.todos_in_list(list)?,
            None => self.repo.all_todos()?,
        };
        let todos = self.to_entities(rows)?;

        let mut matched: Vec<TodoDto> = todos
            .iter()
            .filter(|todo| matches(todo, query))
            .map(|todo| mapper::todo_to_dto(todo, &[]))
            .collect();
        matched.sort_by_key(|dto| dto.id);
        Ok(matched)
    }

    pub fn find_list(&self, list: ListId) -> ServiceResult<TodoList> {
        Ok(mapper::list_from_row(self.repo.find_list(list)?))
    }

    fn load_one(&self, id: TodoId) -> ServiceResult<Todo> {
        let row = self.repo.find_todo(id)?;
        let tags = self.repo.tags_for(id)?;
        mapper::todo_from_row(row, tags)
    }

    fn load_list(&self, list: ListId) -> ServiceResult<Vec<Todo>> {
        let rows = self.repo.todos_in_list(list)?;
        self.to_entities(rows)
    }

    fn to_entities(&self, rows: Vec<TodoRow>) -> ServiceResult<Vec<Todo>> {
        let mut by_todo: BTreeMap<i64, BTreeSet<String>> = BTreeMap::new();
        for tag in self.repo.all_tags()? {
            by_todo.entry(tag.todo_id).or_default().insert(tag.tag);
        }
        rows.into_iter()
            .map(|row| {
                let tags = by_todo.get(&row.id).cloned().unwrap_or_default();
                mapper::todo_from_row(row, tags)
            })
            .collect()
    }
}

fn matches(todo: &Todo, query: &Query) -> bool {
    if let Some(done) = query.done {
        if todo.done != done {
            return false;
        }
    }
    if let Some(tag) = &query.tag {
        if !todo.tags.contains(tag) {
            return false;
        }
    }
    if let Some(before) = query.due_before {
        // An undated todo is never due.
        match todo.due {
            Some(due) if due < before => {}
            _ => return false,
        }
    }
    true
}
