import React from 'react';

// Minimal markdown renderer tailored to TerraFin's `parse_sec_filing` output.
// Handles: ##/### headings, blank-line-separated paragraphs, GFM pipe tables,
// blockquote table-error fallbacks (`> [Table parse error: ...]\nRAW_MD`), and
// optional `![alt](src)` images. Anything else falls through as a plain line.
//
// Deliberately NOT a general markdown renderer — adding that would mean
// pulling in react-markdown + remark-gfm (~60KB gz) for output we fully
// control the producer of.

interface Props {
  markdown: string;
  lineIndexStart?: number; // so headings can carry stable ids for scroll-target
  lineIndexEnd?: number;
}

const H2_STYLE: React.CSSProperties = { fontSize: 16, fontWeight: 800, color: '#0f172a', margin: '18px 0 8px', lineHeight: 1.3 };
const H3_STYLE: React.CSSProperties = { fontSize: 14, fontWeight: 700, color: '#1e293b', margin: '14px 0 6px', lineHeight: 1.35 };
const H4_STYLE: React.CSSProperties = { fontSize: 13, fontWeight: 700, color: '#334155', margin: '12px 0 4px' };
const P_STYLE: React.CSSProperties = { fontSize: 13, color: '#334155', lineHeight: 1.6, margin: '0 0 8px' };
const BLOCKQUOTE_STYLE: React.CSSProperties = {
  borderLeft: '3px solid #fb923c',
  background: '#fff7ed',
  color: '#9a3412',
  padding: '8px 12px',
  fontSize: 12,
  margin: '8px 0',
  borderRadius: 4,
};
const TABLE_STYLE: React.CSSProperties = { borderCollapse: 'collapse', fontSize: 12, margin: '8px 0', width: '100%' };
const TH_STYLE: React.CSSProperties = { border: '1px solid #e2e8f0', background: '#f1f5f9', padding: '6px 8px', textAlign: 'left', fontWeight: 700 };
const TD_STYLE: React.CSSProperties = { border: '1px solid #e2e8f0', padding: '6px 8px', verticalAlign: 'top' };
const IMG_STYLE: React.CSSProperties = { maxWidth: '100%', border: '1px solid #e2e8f0', borderRadius: 4, margin: '8px 0' };
const PLACEHOLDER_STYLE: React.CSSProperties = { ...P_STYLE, color: '#94a3b8', fontStyle: 'italic' };

const HEADING_RE = /^(#{2,4})\s+(.*?)\s*$/;
const TABLE_SEPARATOR_RE = /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const IMAGE_RE = /^!\[([^\]]*)\]\(([^)]+)\)$/;

function splitTableCells(line: string): string[] {
  // Simple pipe-split. sec_parser table cells occasionally contain escaped pipes
  // or currency strings; we accept the naive split and clean leading/trailing
  // empty cells that come from wrapper pipes like "| a | b |".
  const parts = line.split('|').map((s) => s.trim());
  if (parts.length > 0 && parts[0] === '') parts.shift();
  if (parts.length > 0 && parts[parts.length - 1] === '') parts.pop();
  return parts;
}

function cleanCell(text: string): string {
  // `_modify_to_valid_md_table` uses `astype(str)` which emits literal "nan"
  // for missing values. Scrub these to empty so tables don't look broken.
  if (text === 'nan' || text === 'NaN' || text === 'None') return '';
  return text;
}

interface Block {
  kind: 'heading' | 'paragraph' | 'table' | 'blockquote' | 'image' | 'empty';
  payload: unknown;
}

function parseBlocks(md: string): Block[] {
  const lines = md.split('\n');
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) {
      i++;
      continue;
    }

    // Heading
    const headingMatch = line.match(HEADING_RE);
    if (headingMatch) {
      blocks.push({ kind: 'heading', payload: { level: headingMatch[1].length, text: headingMatch[2] } });
      i++;
      continue;
    }

    // Standalone image
    const imageMatch = line.match(IMAGE_RE);
    if (imageMatch) {
      blocks.push({ kind: 'image', payload: { alt: imageMatch[1], src: imageMatch[2] } });
      i++;
      continue;
    }

    // Blockquote run (contiguous `> ` lines)
    if (line.startsWith('> ')) {
      const quote: string[] = [];
      while (i < lines.length && lines[i].startsWith('> ')) {
        quote.push(lines[i].slice(2));
        i++;
      }
      blocks.push({ kind: 'blockquote', payload: quote.join('\n') });
      continue;
    }

    // Possible pipe table: current line has `|` AND next line is a separator.
    if (line.includes('|') && i + 1 < lines.length && TABLE_SEPARATOR_RE.test(lines[i + 1])) {
      const header = splitTableCells(line);
      i += 2; // skip header + separator
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim() && lines[i].includes('|')) {
        rows.push(splitTableCells(lines[i]));
        i++;
      }
      blocks.push({ kind: 'table', payload: { header, rows } });
      continue;
    }

    // Paragraph run (contiguous non-blank, non-special lines).
    const paragraph: string[] = [line];
    i++;
    while (
      i < lines.length
      && lines[i].trim()
      && !lines[i].match(HEADING_RE)
      && !lines[i].startsWith('> ')
      && !lines[i].match(IMAGE_RE)
      && !(
        lines[i].includes('|')
        && i + 1 < lines.length
        && TABLE_SEPARATOR_RE.test(lines[i + 1])
      )
    ) {
      paragraph.push(lines[i]);
      i++;
    }
    blocks.push({ kind: 'paragraph', payload: paragraph.join(' ') });
  }
  return blocks;
}

const FilingMarkdown: React.FC<Props> = ({ markdown }) => {
  const blocks = React.useMemo(() => parseBlocks(markdown), [markdown]);

  return (
    <div>
      {blocks.map((block, idx) => {
        switch (block.kind) {
          case 'heading': {
            const { level, text } = block.payload as { level: number; text: string };
            const style = level === 2 ? H2_STYLE : level === 3 ? H3_STYLE : H4_STYLE;
            if (level === 2) return <h2 key={idx} style={style}>{text}</h2>;
            if (level === 3) return <h3 key={idx} style={style}>{text}</h3>;
            return <h4 key={idx} style={style}>{text}</h4>;
          }
          case 'paragraph': {
            return <p key={idx} style={P_STYLE}>{block.payload as string}</p>;
          }
          case 'blockquote': {
            return <blockquote key={idx} style={BLOCKQUOTE_STYLE}>{block.payload as string}</blockquote>;
          }
          case 'table': {
            const { header, rows } = block.payload as { header: string[]; rows: string[][] };
            return (
              <div key={idx} style={{ overflowX: 'auto' }}>
                <table style={TABLE_STYLE}>
                  <thead>
                    <tr>{header.map((h, hi) => (<th key={hi} style={TH_STYLE}>{cleanCell(h)}</th>))}</tr>
                  </thead>
                  <tbody>
                    {rows.map((row, ri) => (
                      <tr key={ri}>
                        {row.map((cell, ci) => (<td key={ci} style={TD_STYLE}>{cleanCell(cell)}</td>))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          }
          case 'image': {
            const { alt, src } = block.payload as { alt: string; src: string };
            // Our parser replaces data URIs with `<inline-image:...>` placeholders
            // that aren't fetchable. Render them as a visible stub instead of a
            // broken <img>.
            if (src.startsWith('<inline-image')) {
              return <div key={idx} style={PLACEHOLDER_STYLE}>[inline image: {alt || 'no alt text'}]</div>;
            }
            return <img key={idx} src={src} alt={alt} style={IMG_STYLE} />;
          }
          default:
            return null;
        }
      })}
    </div>
  );
};

export default FilingMarkdown;
