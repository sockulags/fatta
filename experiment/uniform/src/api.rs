//! The contract, satisfied by walking nodes.
//!
//! Every operation is the same shape: load the tree, find a node, recurse. There is no
//! layer to cross and no second representation to convert into.

use conformance::{Date, Error, ListId, Query, Result, TodoApi, TodoId, TodoView};

use crate::node::{self, Node, DONE, DUE, LIST, NAME, TAG, TITLE, TODO};
use crate::store::Store;

pub struct TodoNodes {
    store: Store,
}

impl TodoNodes {
    pub fn in_memory() -> Result<Self> {
        Ok(Self {
            store: Store::in_memory()?,
        })
    }

    fn roots(&self) -> Result<Vec<Node>> {
        self.store.load()
    }

    fn list_node(roots: &[Node], list: ListId) -> Result<&Node> {
        roots
            .iter()
            .find(|node| node.id == list.0 && node.is(LIST))
            .ok_or(Error::NoSuchList(list))
    }

    /// The todo itself, plus the list root it sits under.
    fn locate(roots: &[Node], todo: TodoId) -> Result<(&Node, &Node)> {
        for root in roots {
            if let Some(found) = root.find(todo.0) {
                if found.is(TODO) {
                    return Ok((found, root));
                }
            }
        }
        Err(Error::NoSuchTodo(todo))
    }
}

fn parse_date(raw: Option<&str>) -> Option<Date> {
    let mut parts = raw?.split('-');
    let year = parts.next()?.parse().ok()?;
    let month = parts.next()?.parse().ok()?;
    let day = parts.next()?.parse().ok()?;
    if parts.next().is_some() {
        return None;
    }
    Some(Date { year, month, day })
}

fn format_date(date: Date) -> String {
    format!("{:04}-{:02}-{:02}", date.year, date.month, date.day)
}

fn to_view(node: &Node) -> TodoView {
    TodoView {
        id: TodoId(node.id),
        title: node.attrs.text(TITLE).to_owned(),
        done: node.attrs.flag(DONE),
        due: parse_date(node.attrs.first(DUE)),
        tags: node.attrs.all(TAG).map(str::to_owned).collect(),
        children: node.children.iter().map(to_view).collect(),
    }
}

fn to_flat_view(node: &Node) -> TodoView {
    TodoView {
        children: Vec::new(),
        ..to_view(node)
    }
}

fn matches(node: &Node, query: &Query) -> bool {
    if let Some(done) = query.done {
        if node.attrs.flag(DONE) != done {
            return false;
        }
    }
    if let Some(tag) = &query.tag {
        if !node.attrs.all(TAG).any(|t| t == tag) {
            return false;
        }
    }
    if let Some(before) = query.due_before {
        // An undated todo is never due.
        match parse_date(node.attrs.first(DUE)) {
            Some(due) if due < before => {}
            _ => return false,
        }
    }
    true
}

impl TodoApi for TodoNodes {
    fn create_list(&mut self, name: &str) -> Result<ListId> {
        let id = self.store.insert(LIST, None)?;
        self.store.set_attr(id, NAME, name)?;
        Ok(ListId(id))
    }

    fn add(
        &mut self,
        list: ListId,
        parent: Option<TodoId>,
        title: &str,
        due: Option<Date>,
    ) -> Result<TodoId> {
        let title = title.trim();
        if title.is_empty() {
            return Err(Error::EmptyTitle);
        }

        let roots = self.roots()?;
        let list_node = Self::list_node(&roots, list)?;
        let under = match parent {
            None => list_node.id,
            Some(parent) => match list_node.find(parent.0) {
                Some(found) if found.is(TODO) => found.id,
                _ => return Err(Error::NoSuchTodo(parent)),
            },
        };

        let id = self.store.insert(TODO, Some(under))?;
        self.store.set_attr(id, TITLE, title)?;
        self.store.set_attr(id, DONE, "0")?;
        if let Some(due) = due {
            self.store.set_attr(id, DUE, &format_date(due))?;
        }
        Ok(TodoId(id))
    }

    fn complete(&mut self, todo: TodoId) -> Result<()> {
        let roots = self.roots()?;
        let (node, _) = Self::locate(&roots, todo)?;

        let open = node
            .descendants()
            .into_iter()
            .filter(|child| !child.attrs.flag(DONE))
            .count();
        if open > 0 {
            return Err(Error::OpenChildren { todo, open });
        }

        self.store.set_attr(todo.0, DONE, "1")
    }

    fn reopen(&mut self, todo: TodoId) -> Result<()> {
        let roots = self.roots()?;
        Self::locate(&roots, todo)?;
        self.store.set_attr(todo.0, DONE, "0")
    }

    fn tag(&mut self, todo: TodoId, tag: &str) -> Result<()> {
        let roots = self.roots()?;
        Self::locate(&roots, todo)?;
        self.store.add_attr(todo.0, TAG, tag)
    }

    fn move_under(&mut self, todo: TodoId, parent: Option<TodoId>) -> Result<()> {
        let roots = self.roots()?;
        let (node, list) = Self::locate(&roots, todo)?;

        let under = match parent {
            None => list.id,
            Some(parent) => {
                if parent == todo || node.find(parent.0).is_some() {
                    return Err(Error::WouldCycle { todo, parent });
                }
                match list.find(parent.0) {
                    Some(found) if found.is(TODO) => found.id,
                    _ => return Err(Error::NoSuchTodo(parent)),
                }
            }
        };

        self.store.set_parent(todo.0, Some(under))
    }

    fn tree(&self, list: ListId) -> Result<Vec<TodoView>> {
        let roots = self.roots()?;
        let list_node = Self::list_node(&roots, list)?;
        Ok(list_node.children.iter().map(to_view).collect())
    }

    fn search(&self, query: &Query) -> Result<Vec<TodoView>> {
        let roots = self.roots()?;
        let searched: Vec<&Node> = match query.list {
            Some(list) => Self::list_node(&roots, list)?.descendants(),
            None => roots.iter().flat_map(node::Node::descendants).collect(),
        };

        let mut found: Vec<TodoView> = searched
            .into_iter()
            .filter(|node| node.is(TODO) && matches(node, query))
            .map(to_flat_view)
            .collect();
        found.sort_by_key(|view| view.id);
        Ok(found)
    }
}
