import React from 'react';
import type { Source } from '../types/sources';
import { InlineCitation } from './InlineCitation';

interface InlineSourceCitationsProps {
  text: string;
  sources?: Source[];
  /** Pre-computed used sources array (shared across all fragments) */
  sharedUsedSources?: Source[];
  /** Pre-computed mapping from 1-based source number to index in sharedUsedSources */
  sharedUsedNumberToIndex?: Map<number, number>;
}

/**
 * Replace literal [1], [2], [1, 3] patterns in plain text
 * with <InlineCitation /> chips.
 *
 * Only sources that are actually cited in the text are included in the popover navigation.
 * If sharedUsedSources is provided, use that instead of computing from this fragment.
 */
export const InlineSourceCitations: React.FC<InlineSourceCitationsProps> = ({ 
  text, 
  sources, 
  sharedUsedSources, 
  sharedUsedNumberToIndex 
}) => {
  if (!sources || sources.length === 0) {
    return <>{text}</>;
  }

  // Define citationPattern outside the if/else so it's always available
  const citationPattern = /\[(\d+(?:\s*,\s*\d+)*)\]/g;

  // Use shared usedSources if provided (for consistent totals across fragments)
  let usedSources: Source[];
  let usedNumberToIndex: Map<number, number>;

  if (sharedUsedSources && sharedUsedNumberToIndex) {
    // Use the pre-computed shared arrays
    usedSources = sharedUsedSources;
    usedNumberToIndex = sharedUsedNumberToIndex;
  } else {
    // Fallback: compute from this fragment only (old behavior)
    // Sort sources by rank first
    const sortedSources = [...sources].sort((a, b) => {
      const aRank = a.rank ?? Infinity;
      const bRank = b.rank ?? Infinity;
      return aRank - bRank;
    });

    // Pre-scan the content for citations and build a used-index set
    const usedSourceNumbers = new Set<number>();

    let scanMatch: RegExpExecArray | null;
    citationPattern.lastIndex = 0;
    while ((scanMatch = citationPattern.exec(text)) !== null) {
      const nums = scanMatch[1]
        .split(',')
        .map(n => parseInt(n.trim(), 10))
        .filter(n => !Number.isNaN(n) && n > 0);
      nums.forEach(n => usedSourceNumbers.add(n));
    }

    // Build a filtered, ordered usedSources array
    usedSources = [];
    usedNumberToIndex = new Map<number, number>();

    // Build usedSources in order of appearance in sortedSources
    sortedSources.forEach((source, originalIndex) => {
      const oneBasedNumber = originalIndex + 1;
      if (usedSourceNumbers.has(oneBasedNumber)) {
        const usedIndex = usedSources.length;
        usedSources.push(source);
        usedNumberToIndex.set(oneBasedNumber, usedIndex);
      }
    });
  }

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
      // Map original citation numbers to their used indices
      const usedIndices = numbers
        .map(n => usedNumberToIndex.get(n))
        .filter((idx): idx is number => idx !== undefined)
        .sort((a, b) => a - b); // Sort to ensure consistent ordering

      if (usedIndices.length > 0) {
        // Use the first valid index as the primary source for the popover
        const primaryUsedIndex = usedIndices[0];
        const source = usedSources[primaryUsedIndex];
        
        // Display renumbered citations (1-based from usedSources array)
        // e.g., if original was [2, 5] and they map to usedIndices [0, 1], show "1, 2"
        const displayText = usedIndices.map(idx => idx + 1).join(', ');
        
        parts.push(
          <InlineCitation
            key={`cite-${matchStart}`}
            index={primaryUsedIndex}
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

