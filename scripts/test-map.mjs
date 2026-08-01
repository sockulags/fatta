// Test map for TypeScript: which tests pin which function, and what do they claim?
//
//   node test-map.mjs <path to tsconfig.json> [outfile.json]
//
// Tests reach production code in three ways, and all three must be captured for the map
// to find the judges: (1) static imports whose identifiers the type checker resolves,
// (2) `const { GET } = await import('@/app/...')` — destructuring out of a dynamic
// import, where the identifier only resolves to a local binding, so the module specifier
// must be followed instead, and (3) `readFileSync('app/.../page.tsx')` — source-reading
// tests that point at the file with a string literal.
//
// Helper functions inside the test file are expanded: an it() calling mountActions()
// is attributed what mountActions touches.

import { createRequire } from "node:module";
import path from "node:path";
import fs from "node:fs";

const [, , tsconfigArg, outArg] = process.argv;
if (!tsconfigArg) {
  console.error("usage: node test-map.mjs <tsconfig.json> [outfile.json]");
  process.exit(2);
}

const tsconfigPath = path.resolve(tsconfigArg);
const projectDir = path.dirname(tsconfigPath);

function loadTypeScript() {
  for (const base of [projectDir, process.cwd()]) {
    try {
      return createRequire(path.join(base, "noop.js"))("typescript");
    } catch {
      /* next */
    }
  }
  console.error("could not find the `typescript` package in the project.");
  process.exit(3);
}

const ts = loadTypeScript();

const config = ts.getParsedCommandLineOfConfigFile(tsconfigPath, {}, {
  ...ts.sys,
  onUnRecoverableConfigFileDiagnostic(d) {
    console.error(ts.flattenDiagnosticMessageText(d.messageText, "\n"));
    process.exit(4);
  },
});

const program = ts.createProgram({
  rootNames: config.fileNames,
  options: { ...config.options, noEmit: true },
});
const checker = program.getTypeChecker();

const TEST_FILE = /\.(test|spec)\.[tj]sx?$/;
const TEST_CALLS = new Set(["it", "test"]);
const SUITE_CALLS = new Set(["describe"]);
const PATHISH = /^[\w@./(\)\[\]-]+\.(ts|tsx|js|jsx|mjs)$/;

const rel = (f) => path.relative(projectDir, f).replace(/\\/g, "/");

function isLocalProduction(fileName) {
  return !fileName.includes("node_modules/") && !TEST_FILE.test(fileName);
}

function callBase(expr) {
  if (ts.isIdentifier(expr)) return expr.text;
  if (ts.isPropertyAccessExpression(expr)) return callBase(expr.expression);
  if (ts.isCallExpression(expr)) return callBase(expr.expression);
  return null;
}

function titleOf(arg) {
  if (!arg) return "(unnamed)";
  if (ts.isStringLiteralLike(arg)) return arg.text;
  return arg.getText().slice(0, 80);
}

function declarationOf(node) {
  let symbol = checker.getSymbolAtLocation(node);
  if (!symbol) return null;
  if (symbol.flags & ts.SymbolFlags.Alias) {
    try {
      symbol = checker.getAliasedSymbol(symbol);
    } catch {
      /* keep */
    }
  }
  return (symbol.declarations || [])[0] || null;
}

/** Module specifier → production file, via the tsconfig paths resolution. */
function resolveModule(spec, fromFile) {
  const resolved = ts.resolveModuleName(spec, fromFile, config.options, ts.sys);
  const file = resolved?.resolvedModule?.resolvedFileName;
  return file && isLocalProduction(file) ? file : null;
}

/** import('spec') out of an initializer expression, through await/parentheses. */
function dynamicImportSpec(node) {
  let current = node;
  while (current && (ts.isAwaitExpression(current) || ts.isParenthesizedExpression(current))) {
    current = current.expression;
  }
  if (
    current &&
    ts.isCallExpression(current) &&
    current.expression.kind === ts.SyntaxKind.ImportKeyword &&
    current.arguments[0] &&
    ts.isStringLiteralLike(current.arguments[0])
  ) {
    return current.arguments[0].text;
  }
  return null;
}

/** Collects targets and assertions from an arbitrary AST subtree. */
function collect(node, sourceFile, into) {
  const record = (name, file, line) =>
    into.targets.set(`${file}#${name}`, { name, file: rel(file), line });

  const visit = (child) => {
    // (2) destructured dynamic import
    if (ts.isVariableDeclaration(child) && child.initializer) {
      const spec = dynamicImportSpec(child.initializer);
      if (spec) {
        const file = resolveModule(spec, sourceFile.fileName);
        if (file) {
          into.files.add(rel(file));
          if (ts.isObjectBindingPattern(child.name)) {
            for (const element of child.name.elements) {
              const exported = (element.propertyName || element.name).getText();
              record(exported, file, 1);
            }
          }
        }
      }
    }

    // (3) path literal pointing at a production file — a source-reading test
    if (ts.isStringLiteralLike(child) && PATHISH.test(child.text)) {
      const candidate = path.join(projectDir, child.text);
      if (fs.existsSync(candidate) && isLocalProduction(candidate)) {
        into.files.add(rel(candidate));
        into.sourceReads.add(rel(candidate));
      }
    }

    // Fabrication casts: `as any`/`as unknown` is how you construct a value the
    // production types do not allow — the fingerprint of invented states.
    if (ts.isAsExpression(child)) {
      const typeText = child.type.getText();
      if (typeText === "any" || typeText === "unknown" || typeText === "never") {
        into.casts.push({
          line: sourceFile.getLineAndCharacterOfPosition(child.getStart()).line + 1,
          text: child.getText().replace(/\s+/g, " ").slice(0, 120),
        });
      }
    }

    // (1) resolved identifiers
    if (ts.isIdentifier(child)) {
      const declaration = declarationOf(child);
      if (declaration) {
        const declFile = declaration.getSourceFile().fileName;
        if (isLocalProduction(declFile) && child.text.length >= 3) {
          record(
            child.text,
            declFile,
            declaration.getSourceFile()
              .getLineAndCharacterOfPosition(declaration.getStart()).line + 1
          );
        } else if (
          declaration.getSourceFile() === sourceFile &&
          into.helpers.has(child.text)
        ) {
          into.calledHelpers.add(child.text);
        }
      }
    }

    // assertions: the whole statement, the .toBe(...) chain carries the value
    if (ts.isCallExpression(child) && callBase(child.expression) === "expect") {
      let statement = child;
      while (
        statement.parent &&
        !ts.isExpressionStatement(statement.parent) &&
        !ts.isSourceFile(statement.parent)
      ) {
        statement = statement.parent;
      }
      const holder = ts.isExpressionStatement(statement.parent)
        ? statement.parent
        : statement;
      const line = sourceFile.getLineAndCharacterOfPosition(child.getStart()).line + 1;
      if (!into.assertions.some((a) => a.line === line)) {
        into.assertions.push({
          line,
          text: holder.getText().replace(/\s+/g, " ").slice(0, 300),
        });
      }
    }

    ts.forEachChild(child, visit);
  };
  visit(node);
}

function emptyBag(helpers) {
  return {
    targets: new Map(),
    files: new Set(),
    sourceReads: new Set(),
    casts: [],
    assertions: [],
    helpers,
    calledHelpers: new Set(),
  };
}

const tests = [];
const mocks = new Map();

for (const file of program.getSourceFiles()) {
  if (!TEST_FILE.test(file.fileName) || file.fileName.includes("node_modules/")) continue;
  const testFile = rel(file.fileName);

  // Pre-pass: helper functions in the test file and what they themselves touch.
  const helperNames = new Set();
  const helperNodes = new Map();
  const scanHelpers = (node) => {
    if (ts.isFunctionDeclaration(node) && node.name) {
      helperNames.add(node.name.text);
      helperNodes.set(node.name.text, node);
    }
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer &&
        (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer))) {
      helperNames.add(node.name.text);
      helperNodes.set(node.name.text, node.initializer);
    }
    ts.forEachChild(node, scanHelpers);
  };
  ts.forEachChild(file, scanHelpers);

  const helperBags = new Map();
  for (const [name, node] of helperNodes) {
    const bag = emptyBag(helperNames);
    collect(node, file, bag);
    helperBags.set(name, bag);
  }
  // fixpoint: helpers calling helpers
  let changed = true;
  while (changed) {
    changed = false;
    for (const bag of helperBags.values()) {
      for (const called of bag.calledHelpers) {
        const other = helperBags.get(called);
        if (!other) continue;
        for (const [key, value] of other.targets) {
          if (!bag.targets.has(key)) { bag.targets.set(key, value); changed = true; }
        }
        for (const f of other.files) {
          if (!bag.files.has(f)) { bag.files.add(f); changed = true; }
        }
      }
    }
  }

  // Static imports of production modules apply to every test in the file. Weaker
  // evidence than a direct call, but it captures indirection: the test imports one
  // function and the judge fells the internal helper it calls.
  const fileImports = new Set();
  for (const statement of file.statements) {
    if (ts.isImportDeclaration(statement) && ts.isStringLiteralLike(statement.moduleSpecifier)) {
      const resolved = resolveModule(statement.moduleSpecifier.text, file.fileName);
      if (resolved) fileImports.add(rel(resolved));
    }
  }

  const suiteStack = [];
  const visit = (node) => {
    if (ts.isCallExpression(node)) {
      const base = callBase(node.expression);

      if (
        ts.isPropertyAccessExpression(node.expression) &&
        node.expression.name.text === "mock" &&
        node.arguments[0] &&
        ts.isStringLiteralLike(node.arguments[0])
      ) {
        if (!mocks.has(testFile)) mocks.set(testFile, []);
        mocks.get(testFile).push(node.arguments[0].text);
      }

      if (base && SUITE_CALLS.has(base) && node.arguments.length >= 2) {
        suiteStack.push(titleOf(node.arguments[0]));
        ts.forEachChild(node.arguments[1], visit);
        suiteStack.pop();
        return;
      }

      if (base && TEST_CALLS.has(base) && node.arguments.length >= 2) {
        const bag = emptyBag(helperNames);
        collect(node.arguments[node.arguments.length - 1], file, bag);
        for (const called of bag.calledHelpers) {
          const helper = helperBags.get(called);
          if (!helper) continue;
          for (const [key, value] of helper.targets) bag.targets.set(key, value);
          for (const f of helper.files) bag.files.add(f);
        }
        tests.push({
          file: testFile,
          suite: suiteStack.join(" › "),
          name: titleOf(node.arguments[0]),
          line: file.getLineAndCharacterOfPosition(node.getStart()).line + 1,
          targets: [...bag.targets.values()],
          file_targets: [...new Set([...bag.files, ...fileImports])],
          source_reads: [...bag.sourceReads],
          casts: bag.casts,
          expect_errors: (node.getFullText().match(/@ts-expect-error|@ts-ignore/g) || []).length,
          assertions: bag.assertions,
        });
        return;
      }
    }
    ts.forEachChild(node, visit);
  };
  ts.forEachChild(file, visit);
}

const out = {
  format: "fatta-testmap/1",
  project: path.basename(projectDir),
  tests,
  mocks: Object.fromEntries(mocks),
};

const target = outArg ? path.resolve(outArg) : null;
if (target) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, JSON.stringify(out), "utf8");
  console.error(
    `wrote ${tests.length} tests from ${new Set(tests.map((t) => t.file)).size} files to ${target}`
  );
} else {
  process.stdout.write(JSON.stringify(out));
}
