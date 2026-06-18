import { useState } from 'react';
import { ChatResponse } from '../api';
import { FormattedContent } from '../formattedContent';

type Props = {
  chat: ChatResponse | null;
  question: string;
};

export function SourcesPanel({ chat, question }: Props) {
  const [open, setOpen] = useState<Record<string, boolean>>({});

  if (!chat?.matches.length) {
    return null;
  }

  const terms = question
    .toLowerCase()
    .split(/\s+/)
    .filter((t) => t.length > 2);

  return (
    <section className="panel sources">
      <h2>Sources</h2>
      {chat.matches.map((match, index) => {
        const key = `${match.document_id}-${match.chunk_index}`;
        const isOpen = open[key] ?? index < 3;
        return (
          <article key={key} className="source">
            <header>
              <strong>{match.document_name}</strong>
              <span>
                score {match.score.toFixed(2)}
                {match.source_page ? `, page ${match.source_page}` : ''}
              </span>
              <button type="button" className="secondary inlineBtn" onClick={() => setOpen((s) => ({ ...s, [key]: !isOpen }))}>
                {isOpen ? 'Hide' : 'Show'}
              </button>
            </header>
            {isOpen ? (
              <div className="sourceBody">
                <FormattedContent text={highlightTerms(match.content, terms)} />
              </div>
            ) : null}
          </article>
        );
      })}
    </section>
  );
}

function highlightTerms(text: string, terms: string[]): string {
  if (!terms.length) {
    return text;
  }
  let result = text;
  for (const term of terms) {
    const re = new RegExp(`(${escapeRegExp(term)})`, 'gi');
    result = result.replace(re, '**$1**');
  }
  return result;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
