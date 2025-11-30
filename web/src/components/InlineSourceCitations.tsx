import React, { useState, useRef, useEffect } from 'react';
import type { Source } from '../types/sources';

interface InlineSourceCitationsProps {
  content: string;
  sources?: Source[];
}

// Convert number to superscript (¹ ² ³ etc.)
const toSuperscript = (num: number): string => {
  const superscripts = ['⁰', '¹', '²', '³', '⁴', '⁵', '⁶', '⁷', '⁸', '⁹'];
  return num.toString().split('').map(d => superscripts[parseInt(d)]).join('');
};

// Render text with inline source citations
function renderTextWithInlineSources(
  text: string,
  sources: Source[],
  onSourceHover: (index: number, e: React.MouseEvent) => void,
  onSourceLeave: () => void,
  chipRefs: React.MutableRefObject<Map<number, HTMLSpanElement>>
): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  
  // Sort sources by rank
  const sortedSources = [...sources].sort((a, b) => {
    const rankA = a.rank ?? Infinity;
    const rankB = b.rank ?? Infinity;
    return rankA - rankB;
  });
  
  // Create a map of source indices to their sorted position
  const sourceIndexMap = new Map<number, number>();
  sortedSources.forEach((source, sortedIndex) => {
    const originalIndex = source.rank ?? sortedIndex;
    sourceIndexMap.set(originalIndex, sortedIndex);
  });
  
  // Pattern to match citations like [1], [2], [1, 2, 3] at the end of sentences
  // Match citations that appear after text (not at start of line) and before punctuation or end of line
  const citationPattern = /\[(\d+(?:\s*,\s*\d+)*)\]/g;
  let match: RegExpExecArray | null;
  
  while ((match = citationPattern.exec(text)) !== null) {
    const matchStart = match.index;
    const matchEnd = match.index + match[0].length;
    
    // Plain text before the citation
    if (matchStart > lastIndex) {
      parts.push(text.slice(lastIndex, matchStart));
    }
    
    // Parse citation numbers
    const numbers = match[1]
      .split(',')
      .map((n) => parseInt(n.trim(), 10))
      .filter((n) => !Number.isNaN(n) && n > 0)
      .map((n) => sourceIndexMap.get(n - 1)) // Convert to 0-based and map to sorted index
      .filter((n) => n !== undefined) as number[];
    
    if (numbers.length > 0) {
      // Use the first number for display, but show all on hover
      const displayIndex = numbers[0];
      const citationKey = `cite-${matchStart}-${match[0]}`;
      
      parts.push(
        <span
          key={citationKey}
          ref={(el) => {
            if (el) chipRefs.current.set(displayIndex, el);
          }}
          onMouseEnter={(e) => onSourceHover(displayIndex, e)}
          onMouseLeave={onSourceLeave}
          className="text-[10px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] cursor-pointer align-super"
          title={numbers.map(i => sortedSources[i]?.title).filter(Boolean).join(', ')}
        >
          {numbers.map(i => toSuperscript(i + 1)).join('')}
        </span>
      );
    } else {
      // If citation doesn't match any source, just show the original [n] text
      parts.push(match[0]);
    }
    
    lastIndex = matchEnd;
  }
  
  // Remaining text after the last match
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  
  return parts.length > 0 ? parts : [text];
}

export const InlineSourceCitations: React.FC<InlineSourceCitationsProps> = ({ content, sources }) => {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const chipRefs = useRef<Map<number, HTMLSpanElement>>(new Map());

  // Close popover when clicking outside
  useEffect(() => {
    if (activeIndex === null) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node) &&
        chipRefs.current.get(activeIndex) &&
        !chipRefs.current.get(activeIndex)?.contains(e.target as Node)
      ) {
        setActiveIndex(null);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [activeIndex]);

  if (!sources || sources.length === 0) {
    return <>{content}</>;
  }

  // Sort sources by rank
  const sortedSources = [...sources].sort((a, b) => {
    const rankA = a.rank ?? Infinity;
    const rankB = b.rank ?? Infinity;
    return rankA - rankB;
  });

  const activeSource = activeIndex !== null ? sortedSources[activeIndex] : null;

  const handleSourceHover = (index: number, e: React.MouseEvent) => {
    setActiveIndex(index);
  };

  const handleSourceLeave = () => {
    // Don't close immediately - let the popover handle it
  };

  const handlePrevSource = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (activeIndex === null) return;
    setActiveIndex(activeIndex > 0 ? activeIndex - 1 : sortedSources.length - 1);
  };

  const handleNextSource = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (activeIndex === null) return;
    setActiveIndex((activeIndex + 1) % sortedSources.length);
  };

  const extractDomain = (url?: string): string => {
    if (!url) return '';
    try {
      const u = new URL(url);
      return u.hostname.replace(/^www\./, '');
    } catch {
      return url;
    }
  };

  const formatDate = (date?: string | Date): string => {
    if (!date) return '';
    try {
      const d = typeof date === 'string' ? new Date(date) : date;
      return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
    } catch {
      return '';
    }
  };

  const renderedContent = renderTextWithInlineSources(
    content,
    sortedSources,
    handleSourceHover,
    handleSourceLeave,
    chipRefs
  );

  return (
    <>
      <span>{renderedContent}</span>

      {/* Hover popover */}
      {activeSource && activeIndex !== null && (
        <div
          ref={popoverRef}
          className="fixed z-[10000] bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg shadow-lg p-3 max-w-xs pointer-events-auto"
          style={{
            top: chipRefs.current.get(activeIndex)?.getBoundingClientRect().top
              ? `${chipRefs.current.get(activeIndex)!.getBoundingClientRect().top - 120}px`
              : '0px',
            left: chipRefs.current.get(activeIndex)?.getBoundingClientRect().left
              ? `${chipRefs.current.get(activeIndex)!.getBoundingClientRect().left}px`
              : '0px',
          }}
          onMouseEnter={() => setActiveIndex(activeIndex)}
          onMouseLeave={() => setActiveIndex(null)}
        >
          <div className="flex items-start justify-between gap-2 mb-2">
            <div className="flex-1 min-w-0">
              {activeSource.siteName && (
                <div className="text-[10px] text-[var(--text-secondary)] uppercase tracking-wide mb-1">
                  {activeSource.siteName}
                </div>
              )}
              <div className="text-xs font-semibold text-[var(--text-primary)] line-clamp-2">
                {activeSource.title}
              </div>
              {activeSource.publishedAt && (
                <div className="text-[10px] text-[var(--text-secondary)] mt-1">
                  {formatDate(activeSource.publishedAt)}
                </div>
              )}
            </div>
            {sortedSources.length > 1 && (
              <div className="flex items-center gap-1 flex-shrink-0">
                <button
                  onClick={handlePrevSource}
                  className="p-1 hover:bg-[var(--bg-tertiary)] rounded transition-colors"
                  title="Previous source"
                >
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                </button>
                <span className="text-[10px] text-[var(--text-secondary)]">
                  {activeIndex + 1}/{sortedSources.length}
                </span>
                <button
                  onClick={handleNextSource}
                  className="p-1 hover:bg-[var(--bg-tertiary)] rounded transition-colors"
                  title="Next source"
                >
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                </button>
              </div>
            )}
          </div>
          {activeSource.description && (
            <p className="text-[11px] text-[var(--text-secondary)] line-clamp-3 mb-2">
              {activeSource.description}
            </p>
          )}
          {activeSource.url && (
            <a
              href={activeSource.url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="text-[10px] text-[var(--text-primary)] hover:underline flex items-center gap-1"
            >
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
              {extractDomain(activeSource.url)}
            </a>
          )}
        </div>
      )}
    </>
  );
};

