"""The cleanup queue: tests pinning states production cannot produce.

True unreachability is undecidable, but fabricated cases leave fingerprints — to build a
state production never builds, the test must break out of something:

- **the type system**: `as any`/`as unknown` or `@ts-expect-error` in the test
- **the entry path**: directly calling an internal function production only reaches
  through validating entry points
- **reality**: source-reading tests that regex the production file and therefore fail on
  every refactor, even behavior-preserving ones
- **the contract level**: long literals pinned on internal functions — copy tests broken
  by every string change

The output is a review queue with evidence per line, not a verdict: every signal has
legitimate exceptions (partial fixtures, deliberate isolation, intentional copy contracts
at entry points).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .graph import Graph
from .testmap import TestCase, TestMap

# expect(x).toBe('long literal') — the copy test's shape. Short literals ('COMPLETED')
# are usually deliberate contracts; length is what separates status code from copy.
_LITERAL_PIN = re.compile(r"\.(toBe|toEqual|toContain|toMatch)\(\s*['\"](.{15,}?)['\"]")

WEIGHTS = {"fabricated": 3, "below_waterline": 1, "source_reader": 3, "literal_pin": 2}


@dataclass
class Finding:
    test: TestCase
    reasons: list[str] = field(default_factory=list)
    score: int = 0

    def add(self, kind: str, detail: str) -> None:
        self.reasons.append(f"[{kind}] {detail}")
        self.score += WEIGHTS.get(kind, 1)


def internal_symbols(graph: Graph) -> set[tuple[str, str]]:
    """(file, name) for functions with production callers — i.e. not entry points.

    A test calling one directly bypasses the path production takes to get there,
    including any validation on the way. Not wrong in itself, but it is where impossible
    cases arise."""
    called: set[str] = set()
    for item in graph.items.values():
        if item.external is None:
            called.update(item.calls)
    return {
        (graph.items[i].file.replace("\\", "/"), graph.items[i].name)
        for i in called
        if i in graph.items and graph.items[i].external is None
    }


def analyze(tm: TestMap, graph: Graph | None = None) -> list[Finding]:
    internals = internal_symbols(graph) if graph is not None else set()
    findings: list[Finding] = []

    for test in tm.tests:
        finding = Finding(test=test)
        has_prod_targets = bool(test.targets)

        if test.casts and has_prod_targets:
            first = test.casts[0]
            finding.add(
                "fabricated",
                f"{len(test.casts)} type cast(s), e.g. L{first['line']}: {first['text']}",
            )
        if test.expect_errors and has_prod_targets:
            finding.add("fabricated", f"{test.expect_errors} @ts-expect-error/@ts-ignore")

        for read in test.source_reads:
            finding.add("source_reader", f"reads the source of {read}")

        direct_internals = [
            t for t in test.targets
            if (t["file"].replace("\\", "/"), t["name"]) in internals
        ]

        pins = [
            (a["line"], m.group(2)[:60])
            for a in test.assertions
            if (m := _LITERAL_PIN.search(a["text"]))
        ]
        if pins and direct_internals:
            line, literal = pins[0]
            finding.add(
                "literal_pin",
                f"{len(pins)} literal pin(s) on an internal function, e.g. L{line}: '{literal}'",
            )

        # The waterline is context, not accusation: unit-testing internals is normal.
        # It is only added once another signal has fired — then it says *where* the
        # fabricated state arose: below the validation layer.
        if finding.reasons and direct_internals:
            names = ", ".join(sorted({t["name"] for t in direct_internals})[:4])
            finding.add("below_waterline", f"directly calls internals: {names}")

        if finding.reasons:
            findings.append(finding)

    return sorted(findings, key=lambda f: -f.score)


def render(findings: list[Finding], limit: int = 25) -> str:
    if not findings:
        return "No fabrication signals found."
    by_kind: dict[str, int] = {}
    for finding in findings:
        for reason in finding.reasons:
            kind = reason.split("]")[0].lstrip("[")
            by_kind[kind] = by_kind.get(kind, 0) + 1
    lines = [
        f"{len(findings)} tests flagged (by signal strength, strongest first).",
        "Categories: "
        + ", ".join(f"{k}: {v}" for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1])),
        "",
    ]
    for finding in findings[:limit]:
        test = finding.test
        title = f"{test.suite} › {test.name}" if test.suite else test.name
        lines.append(f"## [{finding.score}p] {title}")
        lines.append(f"   {test.file}:{test.line}")
        for reason in finding.reasons:
            lines.append(f"   {reason}")
        lines.append("")
    if len(findings) > limit:
        lines.append(f"… {len(findings) - limit} more. Run with --limit 0 for all.")
    return "\n".join(lines)


# -- historiken -----------------------------------------------------------------


SEP = chr(1)  # %x01 in the git format string


@dataclass(frozen=True)
class Churn:
    total: int
    """Commits that touched the test file."""
    test_only: int
    """Commits that touched the test file without touching any of its production
    target files.

    This is the pure maintenance cost: the test needed fixing although the behavior it
    claims to protect did not change."""


def parse_git_log(text: str) -> list[set[str]]:
    """`git log --name-only --pretty=format:%x01%H` → one file set per commit."""
    commits: list[set[str]] = []
    for block in text.split(SEP):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if lines:
            commits.append({l.replace("\\", "/") for l in lines[1:]})
    return commits


def measure_churn(tm: TestMap, repo: Path) -> dict[str, Churn]:
    """Test file → churn, from the repo's actual history.

    `repo` may be a package directory in a monorepo: git log paths are always relative to
    the repo root, so the map's package-relative paths are prefixed via `--show-prefix`."""
    result = subprocess.run(
        ["git", "log", "--name-only", "--pretty=format:%x01%H"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return {}
    commits = parse_git_log(result.stdout or "")
    prefix_result = subprocess.run(
        ["git", "rev-parse", "--show-prefix"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    prefix = (prefix_result.stdout or "").strip().replace("\\", "/") if prefix_result.returncode == 0 else ""
    if prefix:
        commits = [
            {f[len(prefix):] for f in commit if f.startswith(prefix)}
            for commit in commits
        ]

    targets_by_file: dict[str, set[str]] = {}
    for test in tm.tests:
        bucket = targets_by_file.setdefault(test.file, set())
        bucket.update(t["file"].replace("\\", "/") for t in test.targets)
        bucket.update(f.replace("\\", "/") for f in test.file_targets)

    churn: dict[str, Churn] = {}
    for test_file, targets in targets_by_file.items():
        touched = [c for c in commits if test_file in c]
        if not touched:
            continue
        # The creation commit is excluded: everything is new there, nothing was "fixed".
        alone = sum(1 for c in touched[:-1] if not (c & targets))
        churn[test_file] = Churn(total=len(touched), test_only=alone)
    return churn


def render_churn(churn: dict[str, Churn], findings: list[Finding], limit: int = 12) -> str:
    """The history section: test files that have demonstrably cost maintenance.

    The intersection is the point — a file with high test-only churn AND fabrication
    signals is the strongest deletion candidate: it has cost fixes while behavior did not
    change, and it pins states production does not produce."""
    rows = [(f, c) for f, c in churn.items() if c.test_only >= 2]
    if not rows:
        return "No test file has been repeatedly fixed without its targets changing."
    flagged_files = {finding.test.file for finding in findings}
    rows.sort(key=lambda fc: -fc[1].test_only)
    lines = [
        "Test files fixed without their production targets changing (test-only churn >= 2):",
        "",
        f"{'alone':>6}{'total':>8}   file",
    ]
    for file, c in rows[:limit]:
        marker = "  ⚠ also has fabrication signals" if file in flagged_files else ""
        lines.append(f"{c.test_only:>6}{c.total:>8}   {file}{marker}")
    if len(rows) > limit:
        lines.append(f"… {len(rows) - limit} more")
    return "\n".join(lines)
