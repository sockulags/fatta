//! The one structure. Everything in this backend is a node.
//!
//! A node has a kind, a parent, a bag of attributes and children of the same type. Depth
//! is free: the child of a node is a node, so a rule learned once applies at any level.

use std::collections::{BTreeMap, BTreeSet};

pub const LIST: &str = "list";
pub const TODO: &str = "todo";

pub const TITLE: &str = "title";
pub const NAME: &str = "name";
pub const DONE: &str = "done";
pub const DUE: &str = "due";
pub const TAG: &str = "tag";

/// Attributes as a set of key/value pairs.
///
/// A key may appear more than once, which is how multi-valued attributes such as tags
/// work without needing a second shape.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Attrs {
    pairs: BTreeSet<(String, String)>,
}

impl Attrs {
    pub fn insert(&mut self, key: &str, value: &str) {
        self.pairs.insert((key.to_owned(), value.to_owned()));
    }

    /// Replaces every value under `key`.
    pub fn set(&mut self, key: &str, value: &str) {
        self.pairs.retain(|(k, _)| k != key);
        self.insert(key, value);
    }

    pub fn all<'a>(&'a self, key: &'a str) -> impl Iterator<Item = &'a str> {
        self.pairs
            .iter()
            .filter(move |(k, _)| k == key)
            .map(|(_, v)| v.as_str())
    }

    /// Deliberately not written as `self.all(key).next()`: that would tie the returned
    /// reference to the key's lifetime rather than to the node's.
    pub fn first(&self, key: &str) -> Option<&str> {
        self.pairs
            .iter()
            .find(|(k, _)| k == key)
            .map(|(_, value)| value.as_str())
    }

    pub fn text(&self, key: &str) -> &str {
        self.first(key).unwrap_or_default()
    }

    pub fn flag(&self, key: &str) -> bool {
        self.first(key) == Some("1")
    }

    pub fn is_empty(&self) -> bool {
        self.pairs.is_empty()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Node {
    pub id: i64,
    pub kind: String,
    pub parent: Option<i64>,
    pub attrs: Attrs,
    pub children: Vec<Node>,
}

impl Node {
    pub fn is(&self, kind: &str) -> bool {
        self.kind == kind
    }

    /// The node with `id` anywhere in this subtree, including the root itself.
    pub fn find(&self, id: i64) -> Option<&Node> {
        if self.id == id {
            return Some(self);
        }
        self.children.iter().find_map(|child| child.find(id))
    }

    /// Every node below this one, in depth-first order.
    pub fn descendants(&self) -> Vec<&Node> {
        let mut out = Vec::new();
        for child in &self.children {
            out.push(child);
            out.extend(child.descendants());
        }
        out
    }

    /// This node and everything below it.
    pub fn subtree(&self) -> Vec<&Node> {
        let mut out = vec![self];
        out.extend(self.descendants());
        out
    }
}

/// Assembles flat rows into rooted trees, children ordered by id.
///
/// Grouping by parent first means the order rows arrive in does not matter — a node may
/// legitimately sit under one with a higher id after being moved.
pub fn build(flat: Vec<Node>) -> Vec<Node> {
    let mut by_parent: BTreeMap<Option<i64>, Vec<Node>> = BTreeMap::new();
    for node in flat {
        by_parent.entry(node.parent).or_default().push(node);
    }
    take_children(&mut by_parent, None)
}

fn take_children(
    by_parent: &mut BTreeMap<Option<i64>, Vec<Node>>,
    parent: Option<i64>,
) -> Vec<Node> {
    let mut nodes = by_parent.remove(&parent).unwrap_or_default();
    nodes.sort_by_key(|node| node.id);
    for node in &mut nodes {
        node.children = take_children(by_parent, Some(node.id));
    }
    nodes
}
