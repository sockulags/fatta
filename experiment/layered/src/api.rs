//! The outermost layer: adapts the service to the shared contract.

use conformance::{Date, Error, ListId, Query, Result, TodoApi, TodoId, TodoView};

use crate::dto::CreateTodoCommand;
use crate::mapper;
use crate::repository::{SqliteTodoRepository, TodoRepository};
use crate::service::TodoService;

pub struct TodoBackend<R: TodoRepository> {
    service: TodoService<R>,
}

impl TodoBackend<SqliteTodoRepository> {
    pub fn in_memory() -> Result<Self> {
        let repo = SqliteTodoRepository::in_memory()
            .map_err(|err| Error::Storage(format!("{err:?}")))?;
        Ok(Self {
            service: TodoService::new(repo),
        })
    }
}

impl<R: TodoRepository> TodoApi for TodoBackend<R> {
    fn create_list(&mut self, name: &str) -> Result<ListId> {
        Ok(self.service.create_list(name)?.id)
    }

    fn add(
        &mut self,
        list: ListId,
        parent: Option<TodoId>,
        title: &str,
        due: Option<Date>,
    ) -> Result<TodoId> {
        Ok(self.service.add(CreateTodoCommand {
            list,
            parent,
            title: title.to_owned(),
            due,
        })?)
    }

    fn complete(&mut self, todo: TodoId) -> Result<()> {
        Ok(self.service.complete(todo)?)
    }

    fn reopen(&mut self, todo: TodoId) -> Result<()> {
        Ok(self.service.reopen(todo)?)
    }

    fn tag(&mut self, todo: TodoId, tag: &str) -> Result<()> {
        Ok(self.service.tag(todo, tag)?)
    }

    fn move_under(&mut self, todo: TodoId, parent: Option<TodoId>) -> Result<()> {
        Ok(self.service.move_under(todo, parent)?)
    }

    fn tree(&self, list: ListId) -> Result<Vec<TodoView>> {
        Ok(self
            .service
            .tree(list)?
            .into_iter()
            .map(mapper::dto_to_view)
            .collect())
    }

    fn search(&self, query: &Query) -> Result<Vec<TodoView>> {
        Ok(self
            .service
            .search(query)?
            .into_iter()
            .map(mapper::dto_to_view)
            .collect())
    }
}
