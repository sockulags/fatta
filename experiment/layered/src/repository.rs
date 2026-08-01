//! Storage layer. Speaks SQL and rows, and knows nothing about business rules.

use std::collections::BTreeSet;

use conformance::{ListId, TodoId};
use rusqlite::{params, Connection, OptionalExtension};

use crate::error::{RepoError, RepoResult};
use crate::row::{ListRow, TagRow, TodoRow};

const SCHEMA: &str = "
create table lists (
    id   integer primary key,
    name text not null
);
create table todos (
    id        integer primary key,
    list_id   integer not null references lists(id),
    parent_id integer references todos(id),
    title     text    not null,
    done      integer not null default 0,
    due       text
);
create table tags (
    todo_id integer not null references todos(id),
    tag     text    not null,
    primary key (todo_id, tag)
);
";

pub trait TodoRepository {
    fn create_list(&mut self, name: &str) -> RepoResult<ListRow>;
    fn find_list(&self, id: ListId) -> RepoResult<ListRow>;
    fn insert_todo(
        &mut self,
        list: ListId,
        parent: Option<TodoId>,
        title: &str,
        due: Option<&str>,
    ) -> RepoResult<TodoRow>;
    fn find_todo(&self, id: TodoId) -> RepoResult<TodoRow>;
    fn todos_in_list(&self, list: ListId) -> RepoResult<Vec<TodoRow>>;
    fn all_todos(&self) -> RepoResult<Vec<TodoRow>>;
    fn set_done(&mut self, id: TodoId, done: bool) -> RepoResult<()>;
    fn set_parent(&mut self, id: TodoId, parent: Option<TodoId>) -> RepoResult<()>;
    fn insert_tag(&mut self, id: TodoId, tag: &str) -> RepoResult<()>;
    fn tags_for(&self, id: TodoId) -> RepoResult<BTreeSet<String>>;
    fn all_tags(&self) -> RepoResult<Vec<TagRow>>;
}

pub struct SqliteTodoRepository {
    conn: Connection,
}

impl SqliteTodoRepository {
    pub fn in_memory() -> RepoResult<Self> {
        let conn = Connection::open_in_memory()?;
        conn.execute_batch(SCHEMA)?;
        Ok(Self { conn })
    }

    fn read_todo(row: &rusqlite::Row<'_>) -> rusqlite::Result<TodoRow> {
        Ok(TodoRow {
            id: row.get(0)?,
            list_id: row.get(1)?,
            parent_id: row.get(2)?,
            title: row.get(3)?,
            done: row.get(4)?,
            due: row.get(5)?,
        })
    }
}

const TODO_COLUMNS: &str = "id, list_id, parent_id, title, done, due";

impl TodoRepository for SqliteTodoRepository {
    fn create_list(&mut self, name: &str) -> RepoResult<ListRow> {
        self.conn
            .execute("insert into lists (name) values (?1)", params![name])?;
        Ok(ListRow {
            id: self.conn.last_insert_rowid(),
            name: name.to_owned(),
        })
    }

    fn find_list(&self, id: ListId) -> RepoResult<ListRow> {
        self.conn
            .query_row(
                "select id, name from lists where id = ?1",
                params![id.0],
                |row| {
                    Ok(ListRow {
                        id: row.get(0)?,
                        name: row.get(1)?,
                    })
                },
            )
            .optional()?
            .ok_or(RepoError::ListNotFound(id))
    }

    fn insert_todo(
        &mut self,
        list: ListId,
        parent: Option<TodoId>,
        title: &str,
        due: Option<&str>,
    ) -> RepoResult<TodoRow> {
        self.conn.execute(
            "insert into todos (list_id, parent_id, title, done, due) values (?1, ?2, ?3, 0, ?4)",
            params![list.0, parent.map(|p| p.0), title, due],
        )?;
        let id = self.conn.last_insert_rowid();
        self.find_todo(TodoId(id))
    }

    fn find_todo(&self, id: TodoId) -> RepoResult<TodoRow> {
        self.conn
            .query_row(
                &format!("select {TODO_COLUMNS} from todos where id = ?1"),
                params![id.0],
                Self::read_todo,
            )
            .optional()?
            .ok_or(RepoError::TodoNotFound(id))
    }

    fn todos_in_list(&self, list: ListId) -> RepoResult<Vec<TodoRow>> {
        let mut stmt = self.conn.prepare(&format!(
            "select {TODO_COLUMNS} from todos where list_id = ?1 order by id"
        ))?;
        let rows = stmt.query_map(params![list.0], Self::read_todo)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    fn all_todos(&self) -> RepoResult<Vec<TodoRow>> {
        let mut stmt = self
            .conn
            .prepare(&format!("select {TODO_COLUMNS} from todos order by id"))?;
        let rows = stmt.query_map([], Self::read_todo)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    fn set_done(&mut self, id: TodoId, done: bool) -> RepoResult<()> {
        let changed = self.conn.execute(
            "update todos set done = ?2 where id = ?1",
            params![id.0, i64::from(done)],
        )?;
        if changed == 0 {
            return Err(RepoError::TodoNotFound(id));
        }
        Ok(())
    }

    fn set_parent(&mut self, id: TodoId, parent: Option<TodoId>) -> RepoResult<()> {
        let changed = self.conn.execute(
            "update todos set parent_id = ?2 where id = ?1",
            params![id.0, parent.map(|p| p.0)],
        )?;
        if changed == 0 {
            return Err(RepoError::TodoNotFound(id));
        }
        Ok(())
    }

    fn insert_tag(&mut self, id: TodoId, tag: &str) -> RepoResult<()> {
        self.conn.execute(
            "insert or ignore into tags (todo_id, tag) values (?1, ?2)",
            params![id.0, tag],
        )?;
        Ok(())
    }

    fn tags_for(&self, id: TodoId) -> RepoResult<BTreeSet<String>> {
        let mut stmt = self
            .conn
            .prepare("select tag from tags where todo_id = ?1 order by tag")?;
        let rows = stmt.query_map(params![id.0], |row| row.get::<_, String>(0))?;
        Ok(rows.collect::<rusqlite::Result<BTreeSet<_>>>()?)
    }

    fn all_tags(&self) -> RepoResult<Vec<TagRow>> {
        let mut stmt = self.conn.prepare("select todo_id, tag from tags")?;
        let rows = stmt.query_map([], |row| {
            Ok(TagRow {
                todo_id: row.get(0)?,
                tag: row.get(1)?,
            })
        })?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }
}
