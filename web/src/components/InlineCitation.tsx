import React, { useState, useRef, useEffect } from 'react';
import type { Source } from '../types/sources';

interface InlineCitationProps {
  citationNumbers: number[]; // e.g. [1] or [1, 3]
  sources: Source[];
  sortedIndex: number; // The index in the sorted sources array
}

// Convert number to superscript (¹ ² ³ etc.)
const toSuperscript = (num: number): string => {
  const superscripts = ['⁰', '¹', '²', '³', '⁴', '⁵', '⁶', '⁷', '⁸', '⁹'];
  return num.toString().split('').map(d => superscripts[parseInt(d)]).join('');
};

export const InlineCitation: React.FC<InlineCitationProps> = ({ citationNumbers, sources, sortedIndex }) => {
  const [showPopover, setShowPopover] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const chipRef = useRef<HTMLSpanElement>(null);

  // Sort sources by rank
  const sortedSources = [...sources].sort((a, b) => {
    const rankA = a.rank ?? Infinity;
    const rankB = b.rank ?? Infinity;
    return rankA - rankB;
  });

  const source = sortedSources[sortedIndex];

  useEffect(() => {
    if (!showPopover) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node) &&
        chipRef.current &&
        !chipRef.current.contains(e.target as Node)
      ) {
        setShowPopover(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showPopover]);

  if (!source) return null;

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
      <span
        ref={chipRef}
        onMouseEnter={() => setShowPopover(true)}
        onMouseLeave={() => setShowPopover(false)}
        onClick={(e) => {
          e.stopPropagation();
          if (source.url) {
            window.open(source.url, '_blank', 'noopener,noreferrer');
          }
        }}
        className="text-[10px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] cursor-pointer align-super transition-colors"
        title={source.title}
      >
        {toSuperscript(sortedIndex + 1)}
      </span>

      {showPopover && (
        <div
          ref={popoverRef}
          className="fixed z-[10000] bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg shadow-lg p-3 max-w-xs pointer-events-auto"
          style={{
            top: chipRef.current?.getBoundingClientRect().top
              ? `${chipRef.current.getBoundingClientRect().top - 120}px`
              : '0px',
            left: chipRef.current?.getBoundingClientRect().left
              ? `${chipRef.current.getBoundingClientRect().left}px`
              : '0px',
          }}
          onMouseEnter={() => setShowPopover(true)}
          onMouseLeave={() => setShowPopover(false)}
        >
          {source.siteName && (
            <div className="text-[10px] text-[var(--text-secondary)] uppercase tracking-wide mb-1">
              {source.siteName}
            </div>
          )}
          <div className="text-xs font-semibold text-[var(--text-primary)] line-clamp-2 mb-2">
            {source.title}
          </div>
          {source.publishedAt && (
            <div className="text-[10px] text-[var(--text-secondary)] mb-2">
              {formatDate(source.publishedAt)}
            </div>
          )}
          {source.description && (
            <p className="text-[11px] text-[var(--text-secondary)] line-clamp-3 mb-2">
              {source.description}
            </p>
          )}
          {source.url && (
            <a
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="text-[10px] text-[var(--text-primary)] hover:underline flex items-center gap-1"
            >
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
              {extractDomain(source.url)}
            </a>
          )}
        </div>
      )}
    </>
  );
};

