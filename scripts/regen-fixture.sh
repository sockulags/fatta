#!/usr/bin/env bash
# Regenerates the test fixture from the probe crate.
#
# Uses the active toolchain, which must be nightly — rustdoc JSON output is still an
# unstable interface. Set FATTA_TOOLCHAIN to pick another one, e.g.
# FATTA_TOOLCHAIN=nightly-x86_64-pc-windows-gnu.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
toolchain="${FATTA_TOOLCHAIN:-}"
cargo=(cargo)
if [ -n "$toolchain" ]; then
  cargo=(cargo "+$toolchain")
fi

if ! "${cargo[@]}" --version | grep -q nightly; then
  echo "error: the active toolchain is not nightly." >&2
  echo "       run 'rustup default nightly' or set FATTA_TOOLCHAIN." >&2
  exit 1
fi

cd "$repo/probes/cfprobe"
"${cargo[@]}" rustdoc --lib -- \
  -Zunstable-options --output-format json --document-private-items

cp target/doc/cfprobe.json "$repo/tests/fixtures/cfprobe.json"
echo "fixture updated: tests/fixtures/cfprobe.json"
