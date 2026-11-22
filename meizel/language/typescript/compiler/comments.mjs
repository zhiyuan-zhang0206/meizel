import fs from 'node:fs';
import {ts} from './compiler.mjs';

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function compileDirectives(patterns) {
  const compiled = [];
  for (const pattern of patterns) {
    try {
      compiled.push(new RegExp(`^(?:${pattern})$`));
    } catch {
      // A pattern written for another language's syntax cannot match a JS/TS comment.
    }
  }
  return compiled;
}

function stripSlash(raw) {
  const idx = raw.indexOf('//');
  const body = idx === -1 ? raw : raw.slice(idx + 2);
  return body.startsWith(' ') ? body.slice(1) : body;
}

function mergeLineComments(items) {
  const out = [];
  let i = 0;
  while (i < items.length) {
    const first = items[i];
    if (!first.singleLine) {
      out.push({
        line: first.line,
        end_line: first.end_line,
        kind: first.kind,
        text: first.text,
        raw_text: first.raw_text,
      });
      i += 1;
      continue;
    }
    let endLine = first.end_line;
    const bodies = [stripSlash(first.raw_text)];
    const raws = [first.raw_text];
    let j = i + 1;
    while (
      j < items.length &&
      items[j].singleLine &&
      items[j].column === first.column &&
      items[j].line === endLine + 1
    ) {
      bodies.push(stripSlash(items[j].raw_text));
      raws.push(items[j].raw_text);
      endLine = items[j].end_line;
      j += 1;
    }
    out.push({
      line: first.line,
      end_line: endLine,
      kind: 'comment',
      text: bodies.join('\n').replace(/^\n+|\n+$/g, ''),
      raw_text: raws.join('\n'),
    });
    i = j;
  }
  return out;
}

function scanOne(file, text, linkPattern, directives) {
  const kind = /\.[jt]sx$/.test(file)
    ? ts.ScriptKind.TSX
    : /\.[cm]?js$/.test(file)
      ? ts.ScriptKind.JS
      : ts.ScriptKind.TS;
  const tree = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  if (tree.parseDiagnostics.length) {
    const first = tree.parseDiagnostics[0];
    const line =
      first.start !== undefined
        ? tree.getLineAndCharacterOfPosition(first.start).line + 1
        : 1;
    const message = tree.parseDiagnostics
      .map((d) => ts.flattenDiagnosticMessageText(d.messageText, ' '))
      .join('; ');
    return {blocks: [], links: [], problems: [{line, message}]};
  }

  const lineAt = (position) => tree.getLineAndCharacterOfPosition(position).line + 1;
  const spans = new Map();
  const machineComments = new Set();
  const unusedStrings = [];

  const walk = (node) => {
    for (const range of [
      ...(ts.getLeadingCommentRanges(text, node.pos) ?? []),
      ...(ts.getTrailingCommentRanges(text, node.end) ?? []),
    ]) {
      spans.set(range.pos, range);
    }
    const deprecated = node.name ? ts.getJSDocDeprecatedTag(node) : undefined;
    if (
      deprecated &&
      ts.isJSDoc(deprecated.parent) &&
      text.slice(deprecated.parent.pos, deprecated.parent.end) === '/** @deprecated */'
    ) {
      machineComments.add(deprecated.parent.pos);
    }
    if (
      ts.isExpressionStatement(node) &&
      (ts.isStringLiteral(node.expression) || ts.isNoSubstitutionTemplateLiteral(node.expression))
    ) {
      const value = node.expression.text;
      const parent = node.parent;
      const first =
        (ts.isSourceFile(parent) || ts.isBlock(parent)) && parent.statements[0] === node;
      const directive =
        ts.isStringLiteral(node.expression) &&
        first &&
        ((value === 'use client' && ts.isSourceFile(parent)) ||
          ((value === 'use strict' || value === 'use server') &&
            (ts.isSourceFile(parent) ||
              (ts.isBlock(parent) && ts.isFunctionLike(parent.parent)))));
      if (!directive) {
        unusedStrings.push(node);
      }
    }
    for (const child of node.getChildren(tree)) {
      walk(child);
    }
  };
  walk(tree);

  const links = [];
  const rawItems = [];

  const shebang = ts.getShebang(text);
  if (shebang && !/^#!\/usr\/bin\/(?:env node|node)$/.test(shebang)) {
    rawItems.push({
      singleLine: false,
      line: 1,
      end_line: 1,
      column: 0,
      kind: 'comment',
      text: shebang,
      raw_text: shebang,
    });
  }

  for (const span of [...spans.values()].sort((a, b) => a.pos - b.pos)) {
    if (machineComments.has(span.pos)) continue;
    const value = text.slice(span.pos, span.end);
    const line = lineAt(span.pos);
    const endLine = lineAt(span.end - 1);
    const isSingle = span.kind === ts.SyntaxKind.SingleLineCommentTrivia;

    if (isSingle && linkPattern) {
      const match = linkPattern.exec(value);
      if (match) {
        links.push({line, target: match[1]});
        continue;
      }
    }
    const trimmed = value.trim();
    if (directives.some((regex) => regex.test(trimmed))) {
      continue;
    }
    const column = span.pos - (text.lastIndexOf('\n', span.pos - 1) + 1);
    rawItems.push({
      singleLine: isSingle,
      line,
      end_line: endLine,
      column,
      kind: value.startsWith('/**') ? 'docstring' : 'comment',
      text: value,
      raw_text: value,
    });
  }

  const blocks = mergeLineComments(rawItems);
  for (const node of unusedStrings) {
    const start = node.getStart(tree);
    blocks.push({
      line: lineAt(start),
      end_line: lineAt(node.end - 1),
      kind: 'unused-string',
      text: node.expression.text,
      raw_text: node.getText(tree),
    });
  }
  blocks.sort((a, b) => a.line - b.line || a.end_line - b.end_line || a.kind.localeCompare(b.kind));
  return {blocks, links, problems: []};
}

const request = JSON.parse(fs.readFileSync(0, 'utf8'));
const linkPrefix = request.link_prefix || '';
const linkPattern = linkPrefix
  ? new RegExp(`^\\s*\\/\\/\\s*${escapeRegExp(linkPrefix)}\\s+(\\S+)\\s*$`)
  : null;
const directives = compileDirectives(request.inline_directives || []);
const files = {};
for (const [file, text] of Object.entries(request.sources || {})) {
  files[file] = scanOne(file, text, linkPattern, directives);
}
process.stdout.write(JSON.stringify({files}));
