#!/usr/bin/env bash
# Genererar rustdoc-JSON för mätkorpusen. Kräver nightly (se regen-fixture.sh).
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
toolchain="${FATTA_TOOLCHAIN:-}"
cargo=(cargo)
if [ -n "$toolchain" ]; then
  cargo=(cargo "+$toolchain")
fi

if ! "${cargo[@]}" --version | grep -q nightly; then
  echo "fel: aktiv toolchain är inte nightly." >&2
  exit 1
fi

cd "$repo/corpus"
# Paketnamn exakt som på crates.io — vissa har understreck, andra bindestreck.
for pkg in semver serde_json memchr tokio-util; do
  echo "== $pkg"
  "${cargo[@]}" rustdoc -p "$pkg" -- \
    -Zunstable-options --output-format json --document-private-items
done

echo
echo "JSON i corpus/target/doc/ — källor i \$CARGO_HOME/registry/src"
ls -1 target/doc/*.json
