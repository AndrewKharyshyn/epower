// M284: literal "\uXXXX" sequences inside JSX text / JSX string attributes are NOT escapes (JSX does not process them) and
// render verbatim. Rewrite them to the real characters, in place, using AST ranges only (no reformatting).
const fs = require('fs'); const babel = require('@babel/core');
const P = process.argv[2] || 'xtrail_summary.jsx';
let src = fs.readFileSync(P, 'utf8');
const ast = babel.parseSync(src, { sourceType: 'module', presets: ['@babel/preset-react'], filename: P });
const edits = [];
(function walk(n) {
  if (!n || typeof n.type !== 'string') return;
  if (n.type === 'JSXText' || (n.type === 'StringLiteral' && n._jsxAttr)) edits.push([n.start, n.end]);
  for (const k of Object.keys(n)) { const v = n[k]; if (k === 'loc' || k === 'leadingComments' || k === 'trailingComments') continue;
    if (Array.isArray(v)) v.forEach(walk); else if (v && typeof v.type === 'string') { if (n.type === 'JSXAttribute' && k === 'value' && v.type === 'StringLiteral') v._jsxAttr = true; walk(v); } }
})(ast.program);
edits.sort((a, b) => b[0] - a[0]);
let n = 0;
for (const [s, e] of edits) {
  const seg = src.slice(s, e); const out = seg.replace(/\\u([0-9a-fA-F]{4})/g, (_, h) => { n++; return String.fromCharCode(parseInt(h, 16)); });
  if (out !== seg) src = src.slice(0, s) + out + src.slice(e);
}
fs.writeFileSync(P, src); console.log('rewrote', n, 'escape(s) in JSX text/attributes');
