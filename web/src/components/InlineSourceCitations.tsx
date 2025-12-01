import React from 'react';
import type { Source } from '../types/sources';
import { InlineCitation } from './InlineCitation';

interface InlineSourceCitationsProps {
  text: string;
  sources?: Source[];
}

/**
 * Replace literal [1], [2], [1, 3] patterns in plain text
 * with <InlineCitation /> chips.
 *
 * For v1 we:
 *  - Sort sources by rank
 *  - Use only the first number in [1, 3] to choose the source
 */
export const InlineSourceCitations: React.FC<InlineSourceCitationsProps> = ({ text, sources }) => {
  if (!sources || sources.length === 0) {
    return <>{text}</>;
  }

  const sortedSources = [...sources].sort((a, b) => {
    const aRank = a.rank ?? Infinity;
    const bRank = b.rank ?? Infinity;
    return aRank - bRank;
  });

  const parts: React.ReactNode[] = [];
  let lastIndex = 0;

  const citationRegex = /\[(\d+(?:\s*,\s*\d+)*)\]/g;
  let match: RegExpExecArray | null;

  while ((match = citationRegex.exec(text)) !== null) {
    const matchStart = match.index;
    const matchEnd = match.index + match[0].length;

    if (matchStart > lastIndex) {
      parts.push(text.slice(lastIndex, matchStart));
    }

    const numbers = match[1]
      .split(',')
      .map(n => parseInt(n.trim(), 10))
      .filter(n => !Number.isNaN(n) && n > 0);

    if (numbers.length > 0) {
      const zeroBased = numbers[0] - 1;
      const source = sortedSources[zeroBased];

      if (source) {
        parts.push(
          <InlineCitation
            key={`cite-${matchStart}`}
            index={zeroBased}
            source={source}
            total={sortedSources.length}
          />
        );
      } else {
        // No matching source, keep raw marker
        parts.push(match[0]);
      }
    } else {
      parts.push(match[0]);
    }

    lastIndex = matchEnd;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return <>{parts}</>;
};

