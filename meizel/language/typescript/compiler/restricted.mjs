// The restricted TypeScript subset: the forms that leave a dependency or a name to the run instead of the source.
// A name is read through its symbol (a local `eval`, or a `window` the file declares, is not the global).
// The computed `import()` / `require()` are found with the imports, in imports.mjs.
// See meizel/docs/checker/restricted/restricted-typescript.md.
import {symbols} from './symbols.mjs';

const GLOBAL_OBJECTS = new Set(['globalThis', 'window', 'self', 'global']);
const REWRITING_CALLS = new Set([
  'Object.defineProperty', 'Object.defineProperties', 'Object.setPrototypeOf', 'Object.assign',
  'Reflect.defineProperty', 'Reflect.set', 'Reflect.setPrototypeOf', 'Reflect.deleteProperty',
]);

export function restricted(ts, context, tree, out, index) {
  const checker = context.checker;
  const {transparent, chain, reference} = symbols(ts, context, index);
  const line = node => tree.getLineAndCharacterOfPosition(node.getStart(tree)).line + 1;
  const add = (node, form, detail = '') => out.restricted.push([line(node), form, detail]);
  const isAccess = node => ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node);

  // A global of the library, named bare or behind `globalThis.` / `window.` / `self.` / `global.`.
  function globalName(node) {
    const ref = reference(node);
    if (!ref?.global) return undefined;
    if (!ref.parts.length) return ref.root.text;
    return GLOBAL_OBJECTS.has(ref.root.text) && ref.parts.length === 1 ? ref.parts[0] : undefined;
  }

  // Source text handed to the engine: the global `eval`, in any use, and the global `Function` constructor, called or built with `new`.
  function evaluation(node) {
    if (ts.isIdentifier(node) && node.text === 'eval') {
      const parent = node.parent;
      if ((ts.isPropertyAccessExpression(parent) && parent.name === node) || ts.isTypeQueryNode(parent) || ts.isTypeOfExpression(parent)) return;
      if (globalName(node) === 'eval') add(node, 'eval of source text');
    } else if (ts.isPropertyAccessExpression(node) && node.name.text === 'eval') {
      if (globalName(node) === 'eval') add(node, 'eval of source text');
    } else if (ts.isCallExpression(node) || ts.isNewExpression(node)) {
      if (globalName(node.expression) === 'Function') add(node, 'Function constructor');
    }
  }

  // A key the source states: a literal, or a type made of literals (a const, a union of names).
  function stated(node) {
    const literal = type => (type.flags & (ts.TypeFlags.StringLiteral | ts.TypeFlags.NumberLiteral)) !== 0;
    const type = checker.getTypeAtLocation(node);
    return type.isUnion() ? type.types.every(literal) : literal(type);
  }

  function globalKey(node) {
    const base = transparent(node.expression);
    if (!ts.isIdentifier(base) || !GLOBAL_OBJECTS.has(base.text) || !reference(base)?.global) return;
    const key = node.argumentExpression;
    if (key && !stated(key)) add(node, 'dynamic global key', key.getText(tree));
  }

  function declaration(node) {
    if (tree.isDeclarationFile) return;
    if (node.flags & ts.NodeFlags.GlobalAugmentation) add(node, 'declare global');
    else if (ts.isStringLiteral(node.name)) add(node, 'declare module', node.name.text);
  }

  // Whether the access chain starts at a name an `import` bound, however its keys are written.
  function importedRoot(node) {
    let current = transparent(node);
    while (current && isAccess(current)) current = transparent(current.expression);
    const symbol = current && ts.isIdentifier(current) ? checker.getSymbolAtLocation(current) : undefined;
    return Boolean(symbol && index.bindings.has(symbol));
  }

  function rewrite(node) {
    const target = ts.isBinaryExpression(node) ? node.left : ts.isDeleteExpression(node) ? node.expression : node.operand;
    const access = target && chain(target);
    if (access?.parts.some(part => part === 'prototype' || part === '__proto__') && importedRoot(target)) add(node, 'runtime rewrite of import', 'prototype');
  }

  function visit(node) {
    evaluation(node);
    if (ts.isElementAccessExpression(node)) globalKey(node);
    if (ts.isModuleDeclaration(node)) declaration(node);
    if (ts.isExportDeclaration(node) && node.moduleSpecifier && !node.exportClause) add(node, 'export *', node.moduleSpecifier.getText(tree));
    if (ts.isCallExpression(node)) {
      const ref = reference(node.expression);
      if (ref?.global && REWRITING_CALLS.has(ref.canonical) && node.arguments[0] && importedRoot(node.arguments[0])) add(node, 'runtime rewrite of import', ref.canonical);
    }
    const assigned = ts.isBinaryExpression(node) && node.operatorToken.kind >= ts.SyntaxKind.FirstAssignment && node.operatorToken.kind <= ts.SyntaxKind.LastAssignment;
    const stepped = (ts.isPrefixUnaryExpression(node) || ts.isPostfixUnaryExpression(node)) && [ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken].includes(node.operator);
    if (assigned || stepped || ts.isDeleteExpression(node)) rewrite(node);
    ts.forEachChild(node, visit);
  }
  visit(tree);
}
