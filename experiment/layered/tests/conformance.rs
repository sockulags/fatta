#[test]
fn satisfies_the_shared_contract() {
    conformance::suite::run_all(|| layered::backend().expect("build backend"));
}
