// Quick sanity harness for parseBlocks without React. Run with:
//   node src/TerraFin/interface/frontend/src/stock/components/FilingMarkdown.test.helper.mjs
// Mirrors the block-parsing logic of FilingMarkdown.tsx.

const HEADING_RE = /^(#{2,4})\s+(.*?)\s*$/;
const TABLE_SEPARATOR_RE = /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const IMAGE_RE = /^!\[([^\]]*)\]\(([^)]+)\)$/;

function splitTableCells(line) {
  const parts = line.split('|').map((s) => s.trim());
  if (parts.length > 0 && parts[0] === '') parts.shift();
  if (parts.length > 0 && parts[parts.length - 1] === '') parts.pop();
  return parts;
}

function parseBlocks(md) {
  const lines = md.split('\n');
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const h = line.match(HEADING_RE);
    if (h) { blocks.push({ kind: 'heading', level: h[1].length, text: h[2] }); i++; continue; }
    const img = line.match(IMAGE_RE);
    if (img) { blocks.push({ kind: 'image', alt: img[1], src: img[2] }); i++; continue; }
    if (line.startsWith('> ')) {
      const quote = [];
      while (i < lines.length && lines[i].startsWith('> ')) { quote.push(lines[i].slice(2)); i++; }
      blocks.push({ kind: 'blockquote', text: quote.join('\n') }); continue;
    }
    if (line.includes('|') && i + 1 < lines.length && TABLE_SEPARATOR_RE.test(lines[i + 1])) {
      const header = splitTableCells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim() && lines[i].includes('|')) {
        rows.push(splitTableCells(lines[i])); i++;
      }
      blocks.push({ kind: 'table', header, rows }); continue;
    }
    const paragraph = [line]; i++;
    while (
      i < lines.length && lines[i].trim()
      && !lines[i].match(HEADING_RE)
      && !lines[i].startsWith('> ')
      && !lines[i].match(IMAGE_RE)
      && !(lines[i].includes('|') && i + 1 < lines.length && TABLE_SEPARATOR_RE.test(lines[i + 1]))
    ) { paragraph.push(lines[i]); i++; }
    blocks.push({ kind: 'paragraph', text: paragraph.join(' ') });
  }
  return blocks;
}

function assertEq(actual, expected, msg) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) { console.error(`FAIL: ${msg}\n  expected: ${e}\n  actual:   ${a}`); process.exit(1); }
  console.log(`ok: ${msg}`);
}

// --- Real edge cases flagged by the devil's advocate ---

// 1. Blockquote table-error fallback (from parser.py:122).
const withFallback = `## PART I

### Item 1

Intro text.

> [Table parse error: ragged rows; raw markdown follows]
> | Col A | Col B |
> | 1 | 2 |

After the table.`;
const blocks1 = parseBlocks(withFallback);
assertEq(
  blocks1.map((b) => b.kind),
  ['heading', 'heading', 'paragraph', 'blockquote', 'paragraph'],
  'blockquote fallback recognized, paragraphs around it intact',
);

// 2. nan cells in a table (from astype(str) on NaN).
const withNan = `| Metric | Q1 | Q2 |
| --- | --- | --- |
| Revenue | 100 | 120 |
| Other | nan | nan |`;
const blocks2 = parseBlocks(withNan);
assertEq(blocks2.length, 1, 'nan-bearing table is still one table block');
assertEq(blocks2[0].kind, 'table', 'nan-bearing block kind is table');
assertEq(blocks2[0].rows[1], ['Other', 'nan', 'nan'], 'nan survives the parse (cleaned at render)');

// 3. Inline-image placeholder (from our data-URI replacement).
const withPlaceholder = `![Company logo](<inline-image:image/png>)`;
const blocks3 = parseBlocks(withPlaceholder);
assertEq(blocks3.length, 1, 'inline-image is one block');
assertEq(blocks3[0], { kind: 'image', alt: 'Company logo', src: '<inline-image:image/png>' }, 'placeholder src preserved');

// 4. Paragraph with mid-text dollar signs and percent (won't be mistaken for a table).
const withDollars = `Revenue grew 12.3% to $48.5B, driven by services.`;
const blocks4 = parseBlocks(withDollars);
assertEq(blocks4.map((b) => b.kind), ['paragraph'], 'currency/percent paragraph stays paragraph');

// 5. Line with pipes but no separator below — NOT a table.
const withPipesNoSep = `Contact us at sales | support | marketing for details.

More text.`;
const blocks5 = parseBlocks(withPipesNoSep);
assertEq(blocks5.map((b) => b.kind), ['paragraph', 'paragraph'], 'pipes without separator is paragraph, not table');

// 6. Heading levels.
const headings = `## Two\n### Three\n#### Four`;
const blocks6 = parseBlocks(headings);
assertEq(blocks6.map((b) => b.level), [2, 3, 4], 'h2/h3/h4 levels preserved');

console.log('\nAll FilingMarkdown edge-case checks passed.');
