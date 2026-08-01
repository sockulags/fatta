//! One suite, run against both implementations.
//!
//! Every check takes a freshly built backend so ordering between checks cannot hide a
//! bug. If the two implementations disagree with each other, one of them fails here.

use crate::{Date, Error, Query, Result, TodoApi, TodoId, TodoView};

/// Runs every check against backends produced by `make`.
pub fn run_all<T: TodoApi>(make: impl Fn() -> T) {
    check_add_and_read(&mut make());
    check_nesting(&mut make());
    check_completion_requires_closed_children(&mut make());
    check_completion_bottom_up(&mut make());
    check_reopen(&mut make());
    check_tags_are_a_set(&mut make());
    check_search_filters(&mut make());
    check_search_combines_filters(&mut make());
    check_move_under(&mut make());
    check_move_rejects_cycles(&mut make());
    check_lists_are_isolated(&mut make());
    check_rejects_bad_input(&mut make());
}

fn find<'a>(tree: &'a [TodoView], id: TodoId) -> Option<&'a TodoView> {
    for node in tree {
        if node.id == id {
            return Some(node);
        }
        if let Some(hit) = find(&node.children, id) {
            return Some(hit);
        }
    }
    None
}

fn titles(views: &[TodoView]) -> Vec<&str> {
    views.iter().map(|v| v.title.as_str()).collect()
}

fn unwrap<T>(what: &str, result: Result<T>) -> T {
    match result {
        Ok(value) => value,
        Err(err) => panic!("{what} failed: {err}"),
    }
}

pub fn check_add_and_read<T: TodoApi>(api: &mut T) {
    let list = unwrap("create_list", api.create_list("home"));
    let milk = unwrap("add", api.add(list, None, "buy milk", None));

    let tree = unwrap("tree", api.tree(list));

    assert_eq!(titles(&tree), ["buy milk"]);
    assert_eq!(tree[0].id, milk);
    assert!(!tree[0].done);
    assert!(tree[0].tags.is_empty());
    assert!(tree[0].children.is_empty());
}

pub fn check_nesting<T: TodoApi>(api: &mut T) {
    let list = unwrap("create_list", api.create_list("trip"));
    let pack = unwrap("add", api.add(list, None, "pack", None));
    let clothes = unwrap("add", api.add(list, Some(pack), "clothes", None));
    let socks = unwrap("add", api.add(list, Some(clothes), "socks", None));

    let tree = unwrap("tree", api.tree(list));

    assert_eq!(titles(&tree), ["pack"], "only roots at top level");
    assert_eq!(titles(&tree[0].children), ["clothes"]);
    assert_eq!(titles(&tree[0].children[0].children), ["socks"]);
    assert_eq!(tree[0].children[0].children[0].id, socks);
}

pub fn check_completion_requires_closed_children<T: TodoApi>(api: &mut T) {
    let list = unwrap("create_list", api.create_list("build"));
    let parent = unwrap("add", api.add(list, None, "ship release", None));
    let child = unwrap("add", api.add(list, Some(parent), "write changelog", None));
    let grandchild = unwrap("add", api.add(list, Some(child), "check diff", None));

    match api.complete(parent) {
        Err(Error::OpenChildren { todo, open }) => {
            assert_eq!(todo, parent);
            assert_eq!(open, 2, "both descendants are still open");
        }
        other => panic!("expected OpenChildren, got {other:?}"),
    }

    let tree = unwrap("tree", api.tree(list));
    assert!(!find(&tree, parent).unwrap().done, "must stay open");
    assert!(!find(&tree, grandchild).unwrap().done);
}

pub fn check_completion_bottom_up<T: TodoApi>(api: &mut T) {
    let list = unwrap("create_list", api.create_list("build"));
    let parent = unwrap("add", api.add(list, None, "ship release", None));
    let child = unwrap("add", api.add(list, Some(parent), "write changelog", None));

    unwrap("complete child", api.complete(child));
    unwrap("complete parent", api.complete(parent));

    let tree = unwrap("tree", api.tree(list));
    assert!(find(&tree, parent).unwrap().done);
    assert!(find(&tree, child).unwrap().done);
}

pub fn check_reopen<T: TodoApi>(api: &mut T) {
    let list = unwrap("create_list", api.create_list("home"));
    let todo = unwrap("add", api.add(list, None, "water plants", None));

    unwrap("complete", api.complete(todo));
    unwrap("reopen", api.reopen(todo));

    let tree = unwrap("tree", api.tree(list));
    assert!(!find(&tree, todo).unwrap().done);
}

pub fn check_tags_are_a_set<T: TodoApi>(api: &mut T) {
    let list = unwrap("create_list", api.create_list("work"));
    let todo = unwrap("add", api.add(list, None, "review pr", None));

    unwrap("tag", api.tag(todo, "urgent"));
    unwrap("tag", api.tag(todo, "code"));
    unwrap("tag again", api.tag(todo, "urgent"));

    let tree = unwrap("tree", api.tree(list));
    let tags: Vec<&str> = find(&tree, todo)
        .unwrap()
        .tags
        .iter()
        .map(String::as_str)
        .collect();

    assert_eq!(tags, ["code", "urgent"], "deduplicated and sorted");
}

pub fn check_search_filters<T: TodoApi>(api: &mut T) {
    let list = unwrap("create_list", api.create_list("work"));
    let soon = unwrap("add", api.add(list, None, "soon", Some(Date::new(2026, 1, 5))));
    let later = unwrap("add", api.add(list, None, "later", Some(Date::new(2026, 9, 9))));
    let undated = unwrap("add", api.add(list, None, "undated", None));
    unwrap("tag", api.tag(soon, "urgent"));
    unwrap("complete", api.complete(undated));

    let by_tag = unwrap("search", api.search(&Query { tag: Some("urgent".into()), ..Default::default() }));
    assert_eq!(titles(&by_tag), ["soon"]);

    let open = unwrap("search", api.search(&Query { done: Some(false), ..Default::default() }));
    assert_eq!(titles(&open), ["soon", "later"], "ordered by id");

    let done = unwrap("search", api.search(&Query { done: Some(true), ..Default::default() }));
    assert_eq!(titles(&done), ["undated"]);

    let due = unwrap(
        "search",
        api.search(&Query { due_before: Some(Date::new(2026, 6, 1)), ..Default::default() }),
    );
    assert_eq!(titles(&due), ["soon"], "undated todos are not due");
    assert!(find(&due, later).is_none());

    let all = unwrap("search", api.search(&Query::default()));
    assert_eq!(all.len(), 3);
    assert!(all.iter().all(|v| v.children.is_empty()), "search is flat");
}

pub fn check_search_combines_filters<T: TodoApi>(api: &mut T) {
    let list = unwrap("create_list", api.create_list("work"));
    let hit = unwrap("add", api.add(list, None, "hit", Some(Date::new(2026, 1, 1))));
    let wrong_tag = unwrap("add", api.add(list, None, "wrong tag", Some(Date::new(2026, 1, 1))));
    let wrong_date = unwrap("add", api.add(list, None, "wrong date", Some(Date::new(2027, 1, 1))));
    unwrap("tag", api.tag(hit, "now"));
    unwrap("tag", api.tag(wrong_date, "now"));
    let _ = wrong_tag;

    let found = unwrap(
        "search",
        api.search(&Query {
            list: Some(list),
            tag: Some("now".into()),
            done: Some(false),
            due_before: Some(Date::new(2026, 6, 1)),
        }),
    );

    assert_eq!(titles(&found), ["hit"], "all filters must hold at once");
}

pub fn check_move_under<T: TodoApi>(api: &mut T) {
    let list = unwrap("create_list", api.create_list("trip"));
    let pack = unwrap("add", api.add(list, None, "pack", None));
    let socks = unwrap("add", api.add(list, None, "socks", None));

    unwrap("move_under", api.move_under(socks, Some(pack)));

    let tree = unwrap("tree", api.tree(list));
    assert_eq!(titles(&tree), ["pack"]);
    assert_eq!(titles(&tree[0].children), ["socks"]);

    unwrap("move to root", api.move_under(socks, None));
    let tree = unwrap("tree", api.tree(list));
    assert_eq!(titles(&tree), ["pack", "socks"]);
}

pub fn check_move_rejects_cycles<T: TodoApi>(api: &mut T) {
    let list = unwrap("create_list", api.create_list("trip"));
    let pack = unwrap("add", api.add(list, None, "pack", None));
    let clothes = unwrap("add", api.add(list, Some(pack), "clothes", None));

    match api.move_under(pack, Some(clothes)) {
        Err(Error::WouldCycle { todo, parent }) => {
            assert_eq!((todo, parent), (pack, clothes));
        }
        other => panic!("expected WouldCycle, got {other:?}"),
    }

    match api.move_under(pack, Some(pack)) {
        Err(Error::WouldCycle { .. }) => {}
        other => panic!("a todo may not be its own parent, got {other:?}"),
    }

    let tree = unwrap("tree", api.tree(list));
    assert_eq!(titles(&tree), ["pack"], "structure unchanged after refusal");
}

pub fn check_lists_are_isolated<T: TodoApi>(api: &mut T) {
    let home = unwrap("create_list", api.create_list("home"));
    let work = unwrap("create_list", api.create_list("work"));
    unwrap("add", api.add(home, None, "dishes", None));
    unwrap("add", api.add(work, None, "standup", None));

    assert_eq!(titles(&unwrap("tree", api.tree(home))), ["dishes"]);
    assert_eq!(titles(&unwrap("tree", api.tree(work))), ["standup"]);

    let scoped = unwrap("search", api.search(&Query { list: Some(work), ..Default::default() }));
    assert_eq!(titles(&scoped), ["standup"]);
}

pub fn check_rejects_bad_input<T: TodoApi>(api: &mut T) {
    let list = unwrap("create_list", api.create_list("home"));
    let missing_list = crate::ListId(9_999);
    let missing_todo = TodoId(9_999);

    assert_eq!(api.add(list, None, "", None), Err(Error::EmptyTitle));
    assert_eq!(api.add(list, None, "   ", None), Err(Error::EmptyTitle));
    assert_eq!(
        api.add(missing_list, None, "x", None),
        Err(Error::NoSuchList(missing_list))
    );
    assert_eq!(
        api.add(list, Some(missing_todo), "x", None),
        Err(Error::NoSuchTodo(missing_todo))
    );
    assert_eq!(api.complete(missing_todo), Err(Error::NoSuchTodo(missing_todo)));
    assert_eq!(api.tag(missing_todo, "x"), Err(Error::NoSuchTodo(missing_todo)));
    assert!(matches!(api.tree(missing_list), Err(Error::NoSuchList(_))));
}
