//! Storage shapes. These mirror the tables, not the domain.

#[derive(Debug, Clone)]
pub struct ListRow {
    pub id: i64,
    pub name: String,
}

#[derive(Debug, Clone)]
pub struct TodoRow {
    pub id: i64,
    pub list_id: i64,
    pub parent_id: Option<i64>,
    pub title: String,
    /// SQLite has no boolean type, so this is 0 or 1.
    pub done: i64,
    /// ISO-8601, which sorts chronologically as text.
    pub due: Option<String>,
}

#[derive(Debug, Clone)]
pub struct TagRow {
    pub todo_id: i64,
    pub tag: String,
}
