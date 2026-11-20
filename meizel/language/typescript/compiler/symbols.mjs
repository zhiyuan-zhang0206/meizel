// What a name in a source file refers to: an import, a local declaration, or a global of the library.
// See meizel/docs/checker/typescript.md.
export function symbols(ts, context, index) {
  const checker = context.checker;
  const transparent = node => {
    while (node && (ts.isParenthesizedExpression(node) || ts.isAsExpression(node) || ts.isTypeAssertionExpression(node) || ts.isSatisfiesExpression(node) || ts.isNonNullExpression(node))) node = node.expression;
    return node;
  };
  function chain(node) {
    node = transparent(node);
    const parts = [];
    while (node && (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node))) {
      const name = ts.isPropertyAccessExpression(node) ? node.name.text : node.argumentExpression && (ts.isStringLiteralLike(node.argumentExpression) || ts.isNumericLiteral(node.argumentExpression)) ? node.argumentExpression.text : undefined;
      if (name === undefined) return undefined;
      parts.unshift(name);
      node = transparent(node.expression);
    }
    return {root: node, parts};
  }
  function reference(node) {
    const access = chain(node);
    if (!access || !ts.isIdentifier(access.root)) return undefined;
    const symbol = checker.getSymbolAtLocation(access.root);
    const binding = symbol && index.bindings.get(symbol);
    if (binding) {
      const members = [binding.member === 'default' ? '' : binding.member, ...access.parts].filter(Boolean);
      const knownTool = ['vitest', '@jest/globals'].includes(binding.spec);
      const canonical = knownTool ? members.join('.') : binding.spec === 'react' ? members.join('.') : [binding.spec.replace(/^node:/, ''), ...members].join('.');
      return {...access, binding, canonical, global: false};
    }
    if (symbol?.declarations?.some(declaration => !declaration.getSourceFile().isDeclarationFile)) return {...access, local: true};
    return {...access, canonical: [access.root.text, ...access.parts].join('.'), global: true};
  }
  return {transparent, chain, reference};
}
