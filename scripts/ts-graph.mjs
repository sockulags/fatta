// TypeScript frontend: emits the same graph the rustdoc frontend builds.
//
//   node ts-graph.mjs <path to tsconfig.json> [outfile.json]
//
// `typescript` is loaded from the project under analysis, so no version needs to be
// installed here. Contracts are extracted as real source text, just like on the Rust
// side — it is the text a reader actually faces.

import { createRequire } from "node:module";
import path from "node:path";
import fs from "node:fs";

const [, , tsconfigArg, outArg] = process.argv;
if (!tsconfigArg) {
  console.error("usage: node ts-graph.mjs <tsconfig.json> [outfile.json]");
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
  console.error(
    "could not find the `typescript` package. Run in a project that has it installed."
  );
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

/** Stable id: file plus position. */
function idOf(node) {
  const file = node.getSourceFile();
  return `${path.relative(projectDir, file.fileName).replace(/\\/g, "/")}#${node.pos}`;
}

/** Which package a declaration comes from, or null for local code. */
function originOf(node) {
  const file = node.getSourceFile().fileName;
  if (program.isSourceFileDefaultLibrary(node.getSourceFile())) return "lib";
  const marker = file.lastIndexOf("node_modules/");
  if (marker === -1) return null;
  const rest = file.slice(marker + "node_modules/".length).split("/");
  return rest[0].startsWith("@") ? `${rest[0]}/${rest[1]}` : rest[0];
}

const DECLARATION = new Set([
  ts.SyntaxKind.FunctionDeclaration,
  ts.SyntaxKind.MethodDeclaration,
  ts.SyntaxKind.MethodSignature,
  ts.SyntaxKind.ClassDeclaration,
  ts.SyntaxKind.InterfaceDeclaration,
  ts.SyntaxKind.TypeAliasDeclaration,
  ts.SyntaxKind.EnumDeclaration,
  ts.SyntaxKind.PropertySignature,
  ts.SyntaxKind.PropertyDeclaration,
  ts.SyntaxKind.EnumMember,
]);

// Function expressions bound to a module constant are functions like any other.
const CALLABLE = new Set([
  ts.SyntaxKind.ArrowFunction,
  ts.SyntaxKind.FunctionExpression,
  ts.SyntaxKind.VariableDeclaration,
]);

/** A module constant counts as a dependency; a local variable in a body does not. */
function isModuleConstant(decl) {
  if (!ts.isVariableDeclaration(decl)) return false;
  const statement = decl.parent && decl.parent.parent;
  return !!statement && ts.isVariableStatement(statement) &&
    ts.isSourceFile(statement.parent);
}

/** The declaration an expression refers to, alias resolved. */
function targetOf(node) {
  let symbol = checker.getSymbolAtLocation(node);
  if (!symbol) return null;
  if (symbol.flags & ts.SymbolFlags.Alias) {
    try {
      symbol = checker.getAliasedSymbol(symbol);
    } catch {
      /* keep the original */
    }
  }
  const declarations = symbol.declarations || [];
  const direct = declarations.find((d) => DECLARATION.has(d.kind));
  if (direct) return direct;
  const constant = declarations.find(isModuleConstant);
  if (constant && constant.initializer &&
      (ts.isArrowFunction(constant.initializer) ||
       ts.isFunctionExpression(constant.initializer))) {
    return constant.initializer;
  }
  return constant || null;
}

/** What a body calls, constructs or renders.
 *
 * JSX tags count: `<BlockView />` is a dependency as much as a call is, and in React it
 * is the most common form. */
function callsIn(node, into) {
  if (!node.body) return;
  const self = node;
  const visit = (child) => {
    if (ts.isIdentifier(child) || ts.isPropertyAccessExpression(child)) {
      const name = ts.isPropertyAccessExpression(child) ? child.name : child;
      const found = targetOf(name);
      if (found && found !== self) into.add(found);
    }
    ts.forEachChild(child, visit);
  };
  ts.forEachChild(node.body, visit);
}

/** All declarations a type expression touches. */
function refsIn(node, into) {
  if (!node) return;
  const visit = (child) => {
    if (ts.isTypeReferenceNode(child)) {
      const found = targetOf(
        ts.isQualifiedName(child.typeName) ? child.typeName.right : child.typeName
      );
      if (found) into.add(found);
    } else if (ts.isExpressionWithTypeArguments(child)) {
      const found = targetOf(child.expression);
      if (found) into.add(found);
    }
    ts.forEachChild(child, visit);
  };
  visit(node);
}

/** The signature as text: everything up to the body. */
function signatureText(node) {
  const full = node.getText();
  if (node.body) {
    const offset = node.body.getStart() - node.getStart();
    return full.slice(0, offset).trimEnd();
  }
  return full;
}

/** A type's header: everything up to the first brace. */
function headerText(node) {
  const full = node.getText();
  const brace = full.indexOf("{");
  return brace === -1 ? full : full.slice(0, brace).trimEnd();
}

function docOf(node) {
  const parts = ts.getJSDocCommentsAndTags(node) || [];
  return parts
    .map((p) => (typeof p.comment === "string" ? p.comment : ""))
    .filter(Boolean)
    .join("\n");
}

function isFunctionLike(node) {
  return (
    ts.isFunctionDeclaration(node) ||
    ts.isMethodDeclaration(node) ||
    ts.isMethodSignature(node) ||
    ts.isArrowFunction(node) ||
    ts.isFunctionExpression(node)
  );
}

function memberNodes(node) {
  if (ts.isInterfaceDeclaration(node) || ts.isClassDeclaration(node)) {
    return node.members.filter(
      (m) =>
        ts.isPropertySignature(m) ||
        ts.isPropertyDeclaration(m) ||
        ts.isMethodSignature(m) ||
        ts.isMethodDeclaration(m)
    );
  }
  if (ts.isEnumDeclaration(node)) return [...node.members];
  if (ts.isTypeAliasDeclaration(node) && ts.isTypeLiteralNode(node.type)) {
    return node.type.members.filter((m) => ts.isPropertySignature(m));
  }
  return [];
}

const items = new Map();

function record(node, owner) {
  const id = idOf(node);
  if (items.has(id)) return id;

  const file = node.getSourceFile();
  const line =
    file.getLineAndCharacterOfPosition(node.getStart()).line + 1;
  const external = originOf(node);
  const doc = docOf(node);
  const base = {
    id,
    name: node.name ? node.name.getText() : "(anonymous)",
    external,
    file: path.relative(projectDir, file.fileName).replace(/\\/g, "/"),
    line,
  };
  items.set(id, base); // placed early so cycles cannot loop

  const refs = new Set();

  if (isFunctionLike(node)) {
    for (const parameter of node.parameters || []) refsIn(parameter.type, refs);
    refsIn(node.type, refs);
    const calls = new Set();
    if (!external) callsIn(node, calls);
    Object.assign(base, {
      kind: "function",
      contract: [doc, signatureText(node)].filter(Boolean).join("\n"),
      body: external ? "" : node.getText(),
      refs: [...refs].map((d) => record(d)),
      calls: [...calls].map((d) => record(d)),
      owner: owner ? [record(owner)] : [],
      members: [],
    });
  } else if (
    ts.isPropertySignature(node) ||
    ts.isPropertyDeclaration(node) ||
    ts.isEnumMember(node)
  ) {
    refsIn(node.type, refs);
    Object.assign(base, {
      kind: "member",
      contract: node.getText(),
      body: "",
      refs: [...refs].map((d) => record(d)),
      owner: [],
      members: [],
    });
  } else {
    // interface, class, type alias, enum
    const members = memberNodes(node).map((m) =>
      isFunctionLike(m) ? record(m, node) : record(m)
    );
    if (ts.isTypeAliasDeclaration(node) && !ts.isTypeLiteralNode(node.type)) {
      refsIn(node.type, refs);
    }
    for (const clause of node.heritageClauses || []) refsIn(clause, refs);
    Object.assign(base, {
      kind: "type",
      contract: [doc, headerText(node)].filter(Boolean).join("\n"),
      body: "",
      refs: [...refs].map((d) => record(d)),
      owner: [],
      members,
    });
  }
  return id;
}

for (const file of program.getSourceFiles()) {
  if (program.isSourceFileDefaultLibrary(file)) continue;
  if (file.fileName.includes("node_modules/")) continue;
  ts.forEachChild(file, function walk(node) {
    if (DECLARATION.has(node.kind)) record(node);
    // Arrow functions bound to a constant count as functions.
    if (ts.isVariableStatement(node)) {
      for (const decl of node.declarationList.declarations) {
        if (
          decl.initializer &&
          (ts.isArrowFunction(decl.initializer) ||
            ts.isFunctionExpression(decl.initializer))
        ) {
          const fn = decl.initializer;
          const id = record(fn);
          const entry = items.get(id);
          if (entry) entry.name = decl.name.getText();
        }
      }
    }
    ts.forEachChild(node, walk);
  });
}

const graph = {
  format: "fatta-graph/1",
  name: path.basename(projectDir),
  items: Object.fromEntries(items),
};

const out = outArg ? path.resolve(outArg) : null;
const text = JSON.stringify(graph);
if (out) {
  fs.writeFileSync(out, text, "utf8");
  console.error(`wrote ${items.size} items to ${out}`);
} else {
  process.stdout.write(text);
}
