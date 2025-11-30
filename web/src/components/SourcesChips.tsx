import React, { useState, useRef, useEffect } from 'react';
import type { Source } from '../types/sources';

interface SourcesChipsProps {
  sources?: Source[];
}

// Convert number to superscript (¹ ² ³ etc.)
const toSuperscript = (num: number): string => {
  const superscripts = ['⁰', '¹', '²', '³', '⁴', '⁵', '⁶', '⁷', '⁸', '⁹'];
  return num.toString().split('').map(d => superscripts[parseInt(d)]).join('');
};

export const SourcesChips: React.FC<SourcesChipsProps> = ({ sources }) => {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const [showSourcesSheet, setShowSourcesSheet] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const chipRefs = useRef<Map<number, HTMLButtonElement>>(new Map());

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
    return null;
  }

  // Sort sources by rank (lower = more relevant)
  const sortedSources = [...sources].sort((a, b) => {
    const rankA = a.rank ?? Infinity;
    const rankB = b.rank ?? Infinity;
    return rankA - rankB;
  });

  const activeSource = activeIndex !== null ? sortedSources[activeIndex] : null;

  const handleChipHover = (index: number, e: React.MouseEvent<HTMLButtonElement>) => {
    setActiveIndex(index);
  };

  const handleChipLeave = () => {
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

  return (
    <>
      <div className="flex items-center gap-1">
        {/* Inline source chips */}
        {sortedSources.map((source, index) => (
          <button
            key={source.id}
            ref={(el) => {
              if (el) chipRefs.current.set(index, el);
            }}
            onMouseEnter={(e) => handleChipHover(index, e)}
            onMouseLeave={handleChipLeave}
            onClick={(e) => {
              e.stopPropagation();
              if (source.url) {
                window.open(source.url, '_blank', 'noopener,noreferrer');
              }
            }}
            className="text-[10px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
            title={source.title}
          >
            {toSuperscript(index + 1)}
          </button>
        ))}

        {/* Sources button - only show if there are sources */}
        {sortedSources.length > 0 && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              setShowSourcesSheet(true);
            }}
            className="text-[10px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] underline transition-colors ml-1"
          >
            Sources
          </button>
        )}

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
      </div>

      {/* Sources sheet modal */}
      {showSourcesSheet && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-[10001]"
            onClick={() => setShowSourcesSheet(false)}
          />
          <div className="fixed inset-y-0 right-0 w-full max-w-md bg-[var(--bg-primary)] border-l border-[var(--border-color)] shadow-xl z-[10002] overflow-y-auto">
            <div className="p-6">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-lg font-semibold text-[var(--text-primary)]">Sources</h2>
                <button
                  onClick={() => setShowSourcesSheet(false)}
                  className="p-1 hover:bg-[var(--bg-tertiary)] rounded transition-colors"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>

              {/* Top references (first 3) */}
              {sortedSources.length > 3 && (
                <>
                  <div className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wide mb-3">
                    Top references
                  </div>
                  <div className="space-y-3 mb-6">
                    {sortedSources.slice(0, 3).map((source, index) => (
                      <div
                        key={source.id}
                        className="p-3 border border-[var(--border-color)] rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                      >
                        <div className="flex items-start justify-between gap-2 mb-1">
                          <div className="flex-1 min-w-0">
                            {source.siteName && (
                              <div className="text-[10px] text-[var(--text-secondary)] uppercase tracking-wide mb-1">
                                {source.siteName}
                              </div>
                            )}
                            <a
                              href={source.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-sm font-semibold text-[var(--text-primary)] hover:underline line-clamp-2"
                            >
                              {source.title}
                            </a>
                            {source.publishedAt && (
                              <div className="text-[10px] text-[var(--text-secondary)] mt-1">
                                {formatDate(source.publishedAt)}
                              </div>
                            )}
                          </div>
                          <span className="text-[10px] text-[var(--text-secondary)] flex-shrink-0">
                            {toSuperscript(index + 1)}
                          </span>
                        </div>
                        {source.description && (
                          <p className="text-xs text-[var(--text-secondary)] line-clamp-2 mt-2">
                            {source.description}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}

              {/* More sources */}
              <div className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wide mb-3">
                {sortedSources.length > 3 ? 'More' : 'All sources'}
              </div>
              <div className="space-y-3">
                {sortedSources.slice(sortedSources.length > 3 ? 3 : 0).map((source, index) => (
                  <div
                    key={source.id}
                    className="p-3 border border-[var(--border-color)] rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                  >
                    <div className="flex items-start justify-between gap-2 mb-1">
                      <div className="flex-1 min-w-0">
                        {source.siteName && (
                          <div className="text-[10px] text-[var(--text-secondary)] uppercase tracking-wide mb-1">
                            {source.siteName}
                          </div>
                        )}
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm font-semibold text-[var(--text-primary)] hover:underline line-clamp-2"
                        >
                          {source.title}
                        </a>
                        {source.publishedAt && (
                          <div className="text-[10px] text-[var(--text-secondary)] mt-1">
                            {formatDate(source.publishedAt)}
                          </div>
                        )}
                      </div>
                      <span className="text-[10px] text-[var(--text-secondary)] flex-shrink-0">
                        {toSuperscript((sortedSources.length > 3 ? 3 : 0) + index + 1)}
                      </span>
                    </div>
                    {source.description && (
                      <p className="text-xs text-[var(--text-secondary)] line-clamp-2 mt-2">
                        {source.description}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
};

