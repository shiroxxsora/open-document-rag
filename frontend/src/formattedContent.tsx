import { Fragment, ReactNode } from 'react';

type Block =
  | { kind: 'paragraph'; lines: string[] }
  | { kind: 'list'; ordered: boolean; items: string[] }
  | { kind: 'heading'; level: 2 | 3 | 4; text: string }
  | { kind: 'code'; text: string };

function parseBlocks(text: string): Block[] {
  const normalized = text.replace(/\r\n/g, '\n').trim();
  if (!normalized) {
    return [];
  }

  const blocks: Block[] = [];
  const parts = normalized.split(/\n{2,}/);

  for (const part of parts) {
    const lines = part.split('\n').map((line) => line.trimEnd());
    const nonEmpty = lines.filter((line) => line.trim().length > 0);
    if (nonEmpty.length === 0) {
      continue;
    }

    if (nonEmpty.every((line) => /^```/.test(line) || line === '```')) {
      const code = nonEmpty
        .filter((line) => !/^```/.test(line))
        .join('\n')
        .replace(/^```[\w-]*\n?/, '')
        .replace(/\n?```$/, '');
      blocks.push({ kind: 'code', text: code || part });
      continue;
    }

    const headingMatch = nonEmpty[0].match(/^(#{1,4})\s+(.+)$/);
    if (headingMatch && nonEmpty.length === 1) {
      const level = Math.min(4, headingMatch[1].length) as 2 | 3 | 4;
      blocks.push({ kind: 'heading', level, text: headingMatch[2].trim() });
      continue;
    }

    if (nonEmpty.every((line) => /^[-*•]\s+/.test(line))) {
      blocks.push({
        kind: 'list',
        ordered: false,
        items: nonEmpty.map((line) => line.replace(/^[-*•]\s+/, '').trim()),
      });
      continue;
    }

    if (nonEmpty.every((line) => /^\d+[.)]\s+/.test(line))) {
      blocks.push({
        kind: 'list',
        ordered: true,
        items: nonEmpty.map((line) => line.replace(/^\d+[.)]\s+/, '').trim()),
      });
      continue;
    }

    blocks.push({ kind: 'paragraph', lines: nonEmpty });
  }

  return blocks;
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let index = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }

    const token = match[0];
    if (token.startsWith('**')) {
      nodes.push(
        <strong key={`${keyPrefix}-b-${index}`}>{token.slice(2, -2)}</strong>,
      );
    } else if (token.startsWith('`')) {
      nodes.push(<code key={`${keyPrefix}-c-${index}`}>{token.slice(1, -1)}</code>);
    } else {
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (linkMatch) {
        nodes.push(
          <a key={`${keyPrefix}-a-${index}`} href={linkMatch[2]} target="_blank" rel="noreferrer">
            {linkMatch[1]}
          </a>,
        );
      } else {
        nodes.push(token);
      }
    }

    lastIndex = match.index + token.length;
    index += 1;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes.length ? nodes : [text];
}

function renderBlock(block: Block, index: number): ReactNode {
  if (block.kind === 'heading') {
    const Tag = block.level === 2 ? 'h4' : block.level === 3 ? 'h5' : 'h6';
    return (
      <Tag key={`heading-${index}`} className="formattedHeading">
        {renderInline(block.text, `heading-${index}`)}
      </Tag>
    );
  }

  if (block.kind === 'list') {
    const ListTag = block.ordered ? 'ol' : 'ul';
    return (
      <ListTag key={`list-${index}`}>
        {block.items.map((item, itemIndex) => (
          <li key={`list-${index}-${itemIndex}`}>{renderInline(item, `list-${index}-${itemIndex}`)}</li>
        ))}
      </ListTag>
    );
  }

  if (block.kind === 'code') {
    return (
      <pre key={`code-${index}`}>
        <code>{block.text}</code>
      </pre>
    );
  }

  return (
    <p key={`paragraph-${index}`}>
      {block.lines.map((line, lineIndex) => (
        <Fragment key={`paragraph-${index}-${lineIndex}`}>
          {lineIndex > 0 ? <br /> : null}
          {renderInline(line, `paragraph-${index}-${lineIndex}`)}
        </Fragment>
      ))}
    </p>
  );
}

export function FormattedContent({ text }: { text: string }) {
  const blocks = parseBlocks(text);
  if (!blocks.length) {
    return null;
  }

  return <div className="formattedContent">{blocks.map(renderBlock)}</div>;
}
