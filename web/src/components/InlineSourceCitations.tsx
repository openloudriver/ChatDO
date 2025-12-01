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
 * Only sources that are actually cited in the text are included in the popover navigation.
 */
export const InlineSourceCitations: React.FC<InlineSourceCitationsProps> = ({ text, sources }) => {
  if (!sources || sources.length === 0) {
    return <>{text}</>;
  }

  // Sort sources by rank first
  const sortedSources = [...sources].sort((a, b) => {
    const aRank = a.rank ?? Infinity;
    const bRank = b.rank ?? Infinity;
    return aRank - bRank;
  });

  // Pre-scan the content for citations and build a used-index set
  const citationPattern = /\[(\d+(?:\s*,\s*\d+)*)\]/g;
  const usedSourceNumbers = new Set<number>();

  let scanMatch: RegExpExecArray | null;
  // Reset regex lastIndex to ensure we scan from the beginning
  citationPattern.lastIndex = 0;
  while ((scanMatch = citationPattern.exec(text)) !== null) {
    const nums = scanMatch[1]
      .split(',')
      .map(n => parseInt(n.trim(), 10))
      .filter(n => !Number.isNaN(n) && n > 0);
    nums.forEach(n => usedSourceNumbers.add(n));
  }

  // Build a filtered, ordered usedSources array
  // Map from original 1-based source number to index in usedSources
  const usedSources: Source[] = [];
  const usedNumberToIndex = new Map<number, number>();

  // Build usedSources in order of appearance in sortedSources
  sortedSources.forEach((source, originalIndex) => {
    const oneBasedNumber = originalIndex + 1;
    if (usedSourceNumbers.has(oneBasedNumber)) {
      const usedIndex = usedSources.length;
      usedSources.push(source);
      usedNumberToIndex.set(oneBasedNumber, usedIndex);
    }
  });

  // Graceful fallback: if no sources are used, return text as-is
  if (usedSources.length === 0) {
    return <>{text}</>;
  }

  const parts: React.ReactNode[] = [];
  let lastIndex = 0;

  // Reset regex for main processing
  citationPattern.lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = citationPattern.exec(text)) !== null) {
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
      // Use the first number in the group as the primary source
      const primaryNumber = numbers[0];
      const usedIndex = usedNumberToIndex.get(primaryNumber);

      if (usedIndex !== undefined) {
        const source = usedSources[usedIndex];
        // Display the original citation numbers (e.g., "1, 4" or just "1")
        const displayText = numbers.join(', ');
        
        parts.push(
          <InlineCitation
            key={`cite-${matchStart}`}
            index={usedIndex}
            source={source}
            total={usedSources.length}
            displayText={displayText}
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

