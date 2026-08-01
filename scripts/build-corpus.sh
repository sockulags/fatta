#!/usr/bin/env bash
# Generates rustdoc JSON for the measurement corpus. Requires nightly (see regen-fixture.sh).
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
toolchain="${FATTA_TOOLCHAIN:-}"
cargo=(cargo)
if [ -n "$toolchain" ]; then
  cargo=(cargo "+$toolchain")
fi

if ! "${cargo[@]}" --version | grep -q nightly; then
  echo "error: the active toolchain is not nightly." >&2
  exit 1
fi

cd "$repo/corpus"
# Package names exactly as on crates.io — some use underscores, others hyphens.
for pkg in semver serde_json memchr tokio-util; do
  echo "== $pkg"
  "${cargo[@]}" rustdoc -p "$pkg" -- \
    -Zunstable-options --output-format json --document-private-items
done

echo
echo "JSON in corpus/target/doc/ — sources in \$CARGO_HOME/registry/src"
ls -1 target/doc/*.json
