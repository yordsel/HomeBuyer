/**
 * Enhanced lightweight markdown renderer for chat messages.
 *
 * Supports: **bold**, bullet/numbered lists, ### headers,
 * [link text](url), basic table rendering, and inline address chips
 * for known property addresses.
 */
import { useMemo } from 'react';
import { AddressChip } from './AddressChip';

interface MarkdownLiteProps {
  text: string;
  /** Known property addresses — occurrences in text become clickable chips. */
  knownAddresses?: string[];
  /** Callback when an address chip is clicked. */
  onAddressClick?: (address: string) => void;
}

// ---------------------------------------------------------------------------
// Inline formatting
// ---------------------------------------------------------------------------

/**
 * Split a plain text segment on known addresses and return an array of
 * React nodes — plain text spans interleaved with AddressChip components.
 */
function splitOnAddresses(
  text: string,
  addresses: string[],
  onAddressClick: (address: string) => void,
  keyPrefix: string,
): React.ReactNode[] {
  if (addresses.length === 0) return [text];

  // Build a case-insensitive regex matching any known address.
  // Sort longest-first so "123 Main St Berkeley 94705" matches before "123 Main St".
  const sorted = [...addresses].sort((a, b) => b.length - a.length);
  const escaped = sorted.map((a) => a.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const pattern = new RegExp(`(${escaped.join('|')})`, 'gi');

  const parts = text.split(pattern);
  if (parts.length === 1) return [text];

  // Build a quick lookup for canonical casing (the address from trackedProperties)
  const canonical = new Map<string, string>();
  for (const addr of addresses) {
    canonical.set(addr.toLowerCase(), addr);
  }

  return parts.map((part, i) => {
    const canon = canonical.get(part.toLowerCase());
    if (canon) {
      return (
        <AddressChip
          key={`${keyPrefix}-addr-${i}`}
          address={canon}
          onClick={onAddressClick}
        />
      );
    }
    return part;
  });
}

/** Render **bold**, [link](url), and optionally address chips inline. */
function InlineFormat({
  text,
  addresses,
  onAddressClick,
  keyPrefix = '',
}: {
  text: string;
  addresses?: string[];
  onAddressClick?: (address: string) => void;
  keyPrefix?: string;
}) {
  // Match **bold** and [text](url) patterns
  const parts = text.split(/(\*\*.*?\*\*|\[.*?\]\(.*?\))/g);

  return (
    <>
      {parts.map((part, i) => {
        // Bold: **text**
        const boldMatch = part.match(/^\*\*(.*?)\*\*$/);
        if (boldMatch) {
          const inner = boldMatch[1];
          // Check if the bold text itself contains an address
          if (addresses?.length && onAddressClick) {
            const nodes = splitOnAddresses(inner, addresses, onAddressClick, `${keyPrefix}-b${i}`);
            if (nodes.length > 1 || typeof nodes[0] !== 'string') {
              return <strong key={i} className="font-semibold">{nodes}</strong>;
            }
          }
          return (
            <strong key={i} className="font-semibold">
              {inner}
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

        // Plain text — check for address matches
        if (addresses?.length && onAddressClick) {
          const nodes = splitOnAddresses(part, addresses, onAddressClick, `${keyPrefix}-t${i}`);
          if (nodes.length > 1 || typeof nodes[0] !== 'string') {
            return <span key={i}>{nodes}</span>;
          }
        }

        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

// ---------------------------------------------------------------------------
// Table
// ---------------------------------------------------------------------------

/** Render a markdown table from lines like "| col1 | col2 |". */
function MarkdownTable({
  lines,
  addresses,
  onAddressClick,
}: {
  lines: string[];
  addresses?: string[];
  onAddressClick?: (address: string) => void;
}) {
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
                  <InlineFormat
                    text={cell}
                    addresses={addresses}
                    onAddressClick={onAddressClick}
                    keyPrefix={`tbl-${i}-${j}`}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Block segmentation
// ---------------------------------------------------------------------------

type BlockKind = 'header' | 'list' | 'ordered_list' | 'table' | 'paragraph';

interface TextBlock {
  kind: BlockKind;
  lines: string[];
}

const RE_HEADER = /^#{1,4}\s/;
const RE_BULLET = /^\s*[-*]\s/;
const RE_ORDERED = /^\s*\d+\.\s/;
const RE_TABLE = /^\s*\|/;

function classifyLine(line: string): BlockKind {
  const trimmed = line.trim();
  if (!trimmed) return 'paragraph'; // blank lines are paragraph breaks
  if (RE_HEADER.test(trimmed)) return 'header';
  if (RE_TABLE.test(trimmed)) return 'table';
  if (RE_ORDERED.test(trimmed)) return 'ordered_list';
  if (RE_BULLET.test(trimmed)) return 'list';
  return 'paragraph';
}

/**
 * Split raw markdown text into logical blocks regardless of whether
 * the LLM used single or double newlines between structural elements.
 * Each header, contiguous list, contiguous table, or contiguous paragraph
 * becomes its own block.
 */
function segmentBlocks(text: string): TextBlock[] {
  const allLines = text.split('\n');
  const blocks: TextBlock[] = [];
  let current: TextBlock | null = null;

  for (const line of allLines) {
    const kind = classifyLine(line);
    const trimmed = line.trim();

    // Blank lines end the current block
    if (!trimmed) {
      current = null;
      continue;
    }

    // Headers always start their own block (one line each)
    if (kind === 'header') {
      blocks.push({ kind: 'header', lines: [line] });
      current = null;
      continue;
    }

    // If the kind matches the current block, append
    if (current && current.kind === kind) {
      current.lines.push(line);
      continue;
    }

    // For lists: ordered and bullet can merge into a single "list" block
    if (
      current &&
      (current.kind === 'list' || current.kind === 'ordered_list') &&
      (kind === 'list' || kind === 'ordered_list')
    ) {
      current.lines.push(line);
      continue;
    }

    // Paragraph continuation: if current is paragraph and this line is also
    // a plain paragraph line, keep merging (normal text wrapping)
    if (current && current.kind === 'paragraph' && kind === 'paragraph') {
      current.lines.push(line);
      continue;
    }

    // Otherwise start a new block
    current = { kind, lines: [line] };
    blocks.push(current);
  }

  return blocks;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function MarkdownLite({ text, knownAddresses, onAddressClick }: MarkdownLiteProps) {
  // Memoize filtered address list (only addresses that actually appear in the text)
  const addresses = useMemo(() => {
    if (!knownAddresses?.length || !onAddressClick) return undefined;
    const lower = text.toLowerCase();
    return knownAddresses.filter((a) => lower.includes(a.toLowerCase()));
  }, [text, knownAddresses, onAddressClick]);

  const blocks = useMemo(() => segmentBlocks(text), [text]);

  return (
    <div className="space-y-2">
      {blocks.map((block, i) => {
        // Header
        if (block.kind === 'header') {
          const headerContent = block.lines[0].replace(/^#{1,4}\s+/, '');
          return (
            <h4 key={i} className="font-semibold text-sm text-gray-900 mt-3 first:mt-0">
              <InlineFormat
                text={headerContent}
                addresses={addresses}
                onAddressClick={onAddressClick}
                keyPrefix={`h-${i}`}
              />
            </h4>
          );
        }

        // Table
        if (block.kind === 'table' && block.lines.length >= 2) {
          return (
            <MarkdownTable
              key={i}
              lines={block.lines}
              addresses={addresses}
              onAddressClick={onAddressClick}
            />
          );
        }

        // List (bullet or ordered)
        if (block.kind === 'list' || block.kind === 'ordered_list') {
          // Determine if all items are numbered → use <ol>
          const allOrdered = block.lines.every((l) => RE_ORDERED.test(l));

          const items = block.lines
            .filter((l) => l.trim())
            .map((l) =>
              l.replace(/^\s*[-*]\s*/, '').replace(/^\s*\d+\.\s*/, ''),
            );

          if (allOrdered) {
            return (
              <ol key={i} className="list-decimal list-inside space-y-1">
                {items.map((item, j) => (
                  <li key={j} className="text-sm">
                    <InlineFormat
                      text={item}
                      addresses={addresses}
                      onAddressClick={onAddressClick}
                      keyPrefix={`li-${i}-${j}`}
                    />
                  </li>
                ))}
              </ol>
            );
          }

          return (
            <ul key={i} className="list-disc list-inside space-y-1">
              {items.map((item, j) => (
                <li key={j} className="text-sm">
                  <InlineFormat
                    text={item}
                    addresses={addresses}
                    onAddressClick={onAddressClick}
                    keyPrefix={`li-${i}-${j}`}
                  />
                </li>
              ))}
            </ul>
          );
        }

        // Regular paragraph — join lines with space
        return (
          <p key={i} className="text-sm">
            <InlineFormat
              text={block.lines.join(' ')}
              addresses={addresses}
              onAddressClick={onAddressClick}
              keyPrefix={`p-${i}`}
            />
          </p>
        );
      })}
    </div>
  );
}
