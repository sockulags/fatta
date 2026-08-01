//! Storage. Two tables, both about nodes: one for the nodes, one for their attributes.
//!
//! Attributes are rows rather than columns, so adding a new kind of thing never means
//! changing the schema. That is the same trade the structure makes above: the shape stays
//! uniform, and the meaning moves out of the schema and into the data.

use conformance::{Error, Result};
use rusqlite::{params, Connection};

use crate::node::{Attrs, Node};

const SCHEMA: &str = "
create table nodes (
    id     integer primary key,
    kind   text not null,
    parent integer references nodes(id)
);
create table attrs (
    node_id integer not null references nodes(id),
    key     text    not null,
    value   text    not null,
    primary key (node_id, key, value)
);
";

fn storage(err: rusqlite::Error) -> Error {
    Error::Storage(err.to_string())
}

pub struct Store {
    conn: Connection,
}

impl Store {
    pub fn in_memory() -> Result<Self> {
        let conn = Connection::open_in_memory().map_err(storage)?;
        conn.execute_batch(SCHEMA).map_err(storage)?;
        Ok(Self { conn })
    }

    pub fn insert(&mut self, kind: &str, parent: Option<i64>) -> Result<i64> {
        self.conn
            .execute(
                "insert into nodes (kind, parent) values (?1, ?2)",
                params![kind, parent],
            )
            .map_err(storage)?;
        Ok(self.conn.last_insert_rowid())
    }

    /// Adds a value under `key`, keeping any already there.
    pub fn add_attr(&mut self, id: i64, key: &str, value: &str) -> Result<()> {
        self.conn
            .execute(
                "insert or ignore into attrs (node_id, key, value) values (?1, ?2, ?3)",
                params![id, key, value],
            )
            .map_err(storage)?;
        Ok(())
    }

    /// Replaces every value under `key`.
    pub fn set_attr(&mut self, id: i64, key: &str, value: &str) -> Result<()> {
        self.conn
            .execute(
                "delete from attrs where node_id = ?1 and key = ?2",
                params![id, key],
            )
            .map_err(storage)?;
        self.add_attr(id, key, value)
    }

    pub fn set_parent(&mut self, id: i64, parent: Option<i64>) -> Result<()> {
        self.conn
            .execute(
                "update nodes set parent = ?2 where id = ?1",
                params![id, parent],
            )
            .map_err(storage)?;
        Ok(())
    }

    /// Every node, assembled into trees.
    pub fn load(&self) -> Result<Vec<Node>> {
        let mut stmt = self
            .conn
            .prepare("select id, kind, parent from nodes order by id")
            .map_err(storage)?;
        let rows = stmt
            .query_map([], |row| {
                Ok(Node {
                    id: row.get(0)?,
                    kind: row.get(1)?,
                    parent: row.get(2)?,
                    attrs: Attrs::default(),
                    children: Vec::new(),
                })
            })
            .map_err(storage)?;
        let mut flat: Vec<Node> = rows
            .collect::<rusqlite::Result<Vec<_>>>()
            .map_err(storage)?;

        let mut attrs = self
            .conn
            .prepare("select node_id, key, value from attrs order by node_id, key, value")
            .map_err(storage)?;
        let pairs = attrs
            .query_map([], |row| {
                Ok((
                    row.get::<_, i64>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                ))
            })
            .map_err(storage)?;
        for pair in pairs {
            let (node_id, key, value) = pair.map_err(storage)?;
            if let Some(node) = flat.iter_mut().find(|n| n.id == node_id) {
                node.attrs.insert(&key, &value);
            }
        }

        Ok(crate::node::build(flat))
    }
}
