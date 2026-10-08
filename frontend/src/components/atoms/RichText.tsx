import type { ReactNode } from 'react';

/**
 * The model answers in light markdown: **bold**, `- ` / `* ` / `1. ` lists,
 * `| a | b |` tables, and line breaks. Render just those as React elements - never as HTML - so model
 * output can't inject markup, and everything else stays plain text.
 */
function inline(text: string, keyPrefix: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) =>
    part.startsWith('**') && part.endsWith('**') && part.length > 4 ? (
      <strong key={`${keyPrefix}-${index}`}>{part.slice(2, -2)}</strong>
    ) : (
      part
    ),
  );
}

const LIST_ITEM = /^\s*(?:[-*•]|\d+[.)])\s+/;
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_RULE = /^\s*\|?[\s:|-]+\|?\s*$/;

const cells = (row: string) => row.trim().replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim());

export default function RichText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  let table: string[] = [];

  const flushTable = () => {
    if (!table.length) return;
    const [head, ...body] = table.filter((row) => !TABLE_RULE.test(row)).map(cells);
    table = [];
    if (!head) return;
    const key = blocks.length;
    blocks.push(
      <div className="rich-table-wrap" key={`table-${key}`}>
        <table className="rich-table">
          <thead>
            <tr>
              {head.map((cell, index) => (
                <th key={index}>{inline(cell, `th-${key}-${index}`)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, index) => (
                  <td key={index}>{inline(cell, `td-${key}-${rowIndex}-${index}`)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>,
    );
    table = [];
  };

  const flushList = () => {
    if (list.length) {
      const items = list;
      blocks.push(
        <ul key={`list-${blocks.length}`}>
          {items.map((item, index) => (
            <li key={index}>{inline(item, `li-${blocks.length}-${index}`)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };

  text.split('\n').forEach((line, index) => {
    if (TABLE_ROW.test(line)) {
      flushList();
      table.push(line);
      return;
    }
    flushTable();
    if (LIST_ITEM.test(line)) {
      list.push(line.replace(LIST_ITEM, ''));
      return;
    }
    flushList();
    if (line.trim()) {
      blocks.push(<p key={`p-${index}`}>{inline(line, `p-${index}`)}</p>);
    }
  });
  flushList();
  flushTable();

  return <div className="rich-text">{blocks}</div>;
}
