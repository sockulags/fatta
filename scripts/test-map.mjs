// Testkarta för TypeScript: vilka tester spikar vilken funktion, och vad hävdar de?
//
//   node test-map.mjs <sökväg till tsconfig.json> [utfil.json]
//
// Tester når produktionskod på tre sätt, och alla tre måste fångas för att kartan ska
// hitta domarna: (1) statiska importer vars identifierare löses av typcheckaren,
// (2) `const { GET } = await import('@/app/...')` — destrukturering ur dynamisk import,
// där identifieraren bara löser till en lokal bindning, så modulspecifieraren måste
// följas i stället, och (3) `readFileSync('app/.../page.tsx')` — källästande tester
// som pekar ut filen med en stränglitteral.
//
// Hjälpfunktioner i testfilen expanderas: ett it() som anropar mountActions() ska
// tillskrivas det mountActions rör.

import { createRequire } from "node:module";
import path from "node:path";
import fs from "node:fs";

const [, , tsconfigArg, outArg] = process.argv;
if (!tsconfigArg) {
  console.error("användning: node test-map.mjs <tsconfig.json> [utfil.json]");
  process.exit(2);
}

const tsconfigPath = path.resolve(tsconfigArg);
const projectDir = path.dirname(tsconfigPath);

function loadTypeScript() {
  for (const base of [projectDir, process.cwd()]) {
    try {
      return createRequire(path.join(base, "noop.js"))("typescript");
    } catch {
      /* nästa */
    }
  }
  console.error("hittade inte paketet `typescript` i projektet.");
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
  if (!arg) return "(namnlös)";
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
      /* behåll */
    }
  }
  return (symbol.declarations || [])[0] || null;
}

/** Modulspecifierare → produktionsfil, via tsconfig:ens paths-upplösning. */
function resolveModule(spec, fromFile) {
  const resolved = ts.resolveModuleName(spec, fromFile, config.options, ts.sys);
  const file = resolved?.resolvedModule?.resolvedFileName;
  return file && isLocalProduction(file) ? file : null;
}

/** import('spec') ur ett initialiseringsuttryck, genom await/parenteser. */
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

/** Samlar mål och assertions ur ett godtyckligt AST-subträd. */
function collect(node, sourceFile, into) {
  const record = (name, file, line) =>
    into.targets.set(`${file}#${name}`, { name, file: rel(file), line });

  const visit = (child) => {
    // (2) destrukturerad dynamisk import
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

    // (3) sökvägsliteral till en produktionsfil
    if (ts.isStringLiteralLike(child) && PATHISH.test(child.text)) {
      const candidate = path.join(projectDir, child.text);
      if (fs.existsSync(candidate) && isLocalProduction(candidate)) {
        into.files.add(rel(candidate));
      }
    }

    // (1) upplösta identifierare
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

    // assertions: hela satsen, kedjan .toBe(...) bär värdet
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

  // Förpass: hjälpfunktioner i testfilen och vad de själva rör.
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
  // fixpunkt: hjälpare som anropar hjälpare
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

  // Statiska importer av produktionsmoduler gäller varje test i filen. Det är ett
  // svagare belägg än ett direkt anrop, men det fångar indirektion: testet importerar
  // buildAtsParsePreview och domaren fäller den interna readiness den anropar.
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
    `skrev ${tests.length} tester ur ${new Set(tests.map((t) => t.file)).size} filer till ${target}`
  );
} else {
  process.stdout.write(JSON.stringify(out));
}
