#!/usr/bin/env bash
# Regenererar testfixturen ur sondkretsen.
#
# Använder den aktiva toolchainen, som måste vara nightly — rustdocs JSON-utdata är
# fortfarande ett instabilt gränssnitt. Sätt FATTA_TOOLCHAIN för att välja en annan,
# till exempel FATTA_TOOLCHAIN=nightly-x86_64-pc-windows-gnu.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
toolchain="${FATTA_TOOLCHAIN:-}"
cargo=(cargo)
if [ -n "$toolchain" ]; then
  cargo=(cargo "+$toolchain")
fi

if ! "${cargo[@]}" --version | grep -q nightly; then
  echo "fel: aktiv toolchain är inte nightly." >&2
  echo "     kör 'rustup default nightly' eller sätt FATTA_TOOLCHAIN." >&2
  exit 1
fi

cd "$repo/probes/cfprobe"
"${cargo[@]}" rustdoc --lib -- \
  -Zunstable-options --output-format json --document-private-items

cp target/doc/cfprobe.json "$repo/tests/fixtures/cfprobe.json"
echo "fixturen uppdaterad: tests/fixtures/cfprobe.json"
