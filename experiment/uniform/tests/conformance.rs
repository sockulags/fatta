#[test]
fn satisfies_the_shared_contract() {
    conformance::suite::run_all(|| uniform::backend().expect("build backend"));
}
