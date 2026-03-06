/**
 * Enhanced lightweight markdown renderer for chat messages.
 *
 * Supports: **bold**, bullet/numbered lists, ### headers,
 * [link text](url), and basic table rendering.
 */

/** Render **bold** and [link](url) inline. */
function InlineFormat({ text }: { text: string }) {
  // Match **bold** and [text](url) patterns
  const parts = text.split(/(\*\*.*?\*\*|\[.*?\]\(.*?\))/g);

  return (
    <>
      {parts.map((part, i) => {
        // Bold: **text**
        const boldMatch = part.match(/^\*\*(.*?)\*\*$/);
        if (boldMatch) {
          return (
            <strong key={i} className="font-semibold">
              {boldMatch[1]}
            </strong>
          );
        }

        // Link: [text](url)
        const linkMatch = part.match(/^\[(.*?)\]\((.*?)\)$/);
        if (linkMatch) {
          return (
            <a
              key={i}
              href={linkMatch[2]}
              target="_blank"
              rel="noopener noreferrer"
              className="text-indigo-600 hover:text-indigo-800 underline"
            >
              {linkMatch[1]}
            </a>
          );
        }

        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

/** Render a markdown table from lines like "| col1 | col2 |". */
function MarkdownTable({ lines }: { lines: string[] }) {
  // Parse header and rows
  const rows = lines
    .filter((l) => l.trim() && !/^[\s|:-]+$/.test(l)) // Skip separator lines
    .map((l) =>
      l
        .split('|')
        .map((cell) => cell.trim())
        .filter(Boolean),
    );

  if (rows.length === 0) return null;

  const [header, ...body] = rows;

  return (
    <div className="overflow-x-auto my-2">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-gray-200 bg-gray-50">
            {header.map((cell, i) => (
              <th
                key={i}
                className="text-left px-2 py-1.5 font-semibold text-gray-700"
              >
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, i) => (
            <tr key={i} className="border-b border-gray-100">
              {row.map((cell, j) => (
                <td key={j} className="px-2 py-1 text-gray-600">
                  <InlineFormat text={cell} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MarkdownLite({ text }: { text: string }) {
  const paragraphs = text.split('\n\n');

  return (
    <div className="space-y-2">
      {paragraphs.map((para, i) => {
        const lines = para.split('\n');

        // Header: ### text
        if (lines.length === 1 && /^#{1,4}\s/.test(lines[0])) {
          const content = lines[0].replace(/^#{1,4}\s+/, '');
          return (
            <h4 key={i} className="font-semibold text-sm text-gray-900 mt-2">
              <InlineFormat text={content} />
            </h4>
          );
        }

        // Table: lines starting with |
        const isTable = lines.every(
          (l) => l.trim().startsWith('|') || l.trim() === '',
        );
        if (isTable && lines.filter((l) => l.trim().startsWith('|')).length >= 2) {
          return <MarkdownTable key={i} lines={lines} />;
        }

        // List: bullet or numbered
        const isList = lines.every(
          (l) => /^\s*[-*]\s/.test(l) || /^\s*\d+\.\s/.test(l) || l.trim() === '',
        );

        if (isList) {
          return (
            <ul key={i} className="list-disc list-inside space-y-0.5">
              {lines
                .filter((l) => l.trim())
                .map((l, j) => (
                  <li key={j} className="text-sm">
                    <InlineFormat
                      text={l
                        .replace(/^\s*[-*]\s*/, '')
                        .replace(/^\s*\d+\.\s*/, '')}
                    />
                  </li>
                ))}
            </ul>
          );
        }

        // Regular paragraph
        return (
          <p key={i} className="text-sm">
            <InlineFormat text={para.replace(/\n/g, ' ')} />
          </p>
        );
      })}
    </div>
  );
}
