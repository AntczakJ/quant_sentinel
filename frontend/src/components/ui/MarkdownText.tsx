/**
 * MarkdownText.tsx — Lekki renderer podstawowego markdown bez dodatkowych zależności.
 * Obsługuje: **bold**, *italic*, `code`, ### nagłówki, - listy, \n podziały linii.
 */

import { useMemo } from 'react';

interface Props {
  text: string;
  className?: string;
}

function parseInline(line: string): React.ReactNode[] {
  // Podziel po **bold**, *italic*, `code`
  const parts = line.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**'))
      {return <strong key={i} className="text-white font-semibold">{part.slice(2, -2)}</strong>;}
    if (part.startsWith('*') && part.endsWith('*'))
      {return <em key={i} className="text-gray-300 italic">{part.slice(1, -1)}</em>;}
    if (part.startsWith('`') && part.endsWith('`'))
      {return <code key={i} className="bg-dark-bg text-accent-green px-1.5 py-0.5 rounded text-xs font-mono">{part.slice(1, -1)}</code>;}
    return <span key={i}>{part}</span>;
  });
}

export function MarkdownText({ text, className = '' }: Props) {
  const nodes = useMemo(() => {
    const lines = text.split('\n');
    const result: React.ReactNode[] = [];
    let listItems: string[] = [];

    const flushList = (key: string) => {
      if (listItems.length > 0) {
        result.push(
          <ul key={key} className="space-y-1 my-1.5 pl-3">
            {listItems.map((item, i) => (
              <li key={i} className="flex gap-2 text-gray-300 text-sm">
                <span className="text-accent-green flex-shrink-0 mt-0.5">•</span>
                <span>{parseInline(item)}</span>
              </li>
            ))}
          </ul>
        );
        listItems = [];
      }
    };

    lines.forEach((line, idx) => {
      const trimmed = line.trim();

      // Pusta linia — separator
      if (!trimmed) {
        flushList(`list-${idx}`);
        result.push(<div key={`br-${idx}`} className="h-1.5" />);
        return;
      }

      // ### Heading 3
      if (trimmed.startsWith('### ')) {
        flushList(`list-${idx}`);
        result.push(
          <h3 key={idx} className="text-accent-green font-bold text-sm uppercase tracking-wide mt-3 mb-1">
            {parseInline(trimmed.slice(4))}
          </h3>
        );
        return;
      }

      // ## Heading 2
      if (trimmed.startsWith('## ')) {
        flushList(`list-${idx}`);
        result.push(
          <h2 key={idx} className="text-accent-blue font-bold text-sm uppercase tracking-wide mt-3 mb-1">
            {parseInline(trimmed.slice(3))}
          </h2>
        );
        return;
      }

      // # Heading 1
      if (trimmed.startsWith('# ')) {
        flushList(`list-${idx}`);
        result.push(
          <h1 key={idx} className="text-white font-bold text-base mt-3 mb-1">
            {parseInline(trimmed.slice(2))}
          </h1>
        );
        return;
      }

      // - List item
      if (trimmed.startsWith('- ') || trimmed.startsWith('• ')) {
        listItems.push(trimmed.slice(2));
        return;
      }

      // Zwykły akapit
      flushList(`list-${idx}`);
      result.push(
        <p key={idx} className="text-gray-300 text-sm leading-relaxed">
          {parseInline(trimmed)}
        </p>
      );
    });

    flushList('list-end');
    return result;
  }, [text]);

  return (
    <div className={`space-y-0.5 ${className}`}>
      {nodes}
    </div>
  );
}

