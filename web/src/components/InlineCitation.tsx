import React, { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import axios from 'axios';
import { useChatStore } from '../store/chat';
import type { Source } from '../types/sources';

interface InlineCitationProps {
  /** 0-based index into the used sources array */
  index: number;
  source: Source;
  /** Total number of used sources (for x/y display) */
  total: number;
  /** Optional display text (e.g., "1, 4" for multi-citation) */
  displayText?: string;
}

export const InlineCitation: React.FC<InlineCitationProps> = ({ index, source, total, displayText }) => {
  const [open, setOpen] = useState(false);
  const [isSummarizing, setIsSummarizing] = useState(false);
  const chipRef = useRef<HTMLSpanElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const closeTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  
  const { currentConversation, currentProject, addMessage } = useChatStore();

  // Clear timeout on unmount
  useEffect(() => {
    return () => {
      if (closeTimeoutRef.current) {
        clearTimeout(closeTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!open) return;

    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        popoverRef.current &&
        !popoverRef.current.contains(target) &&
        chipRef.current &&
        !chipRef.current.contains(target)
      ) {
        setOpen(false);
      }
    };

    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const handleMouseEnter = () => {
    // Clear any pending close timeout
    if (closeTimeoutRef.current) {
      clearTimeout(closeTimeoutRef.current);
      closeTimeoutRef.current = null;
    }
    setOpen(true);
  };

  const handleMouseLeave = () => {
    // Add a small delay before closing to allow mouse to move to popover
    closeTimeoutRef.current = setTimeout(() => {
      setOpen(false);
      closeTimeoutRef.current = null;
    }, 150);
  };

  const handlePopoverMouseEnter = () => {
    // Clear any pending close timeout when mouse enters popover
    if (closeTimeoutRef.current) {
      clearTimeout(closeTimeoutRef.current);
      closeTimeoutRef.current = null;
    }
    setOpen(true);
  };

  const handlePopoverMouseLeave = () => {
    // Close when mouse leaves popover
    setOpen(false);
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

  const handleSummarizeUrl = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!source.url || !currentProject || !currentConversation || isSummarizing) return;
    
    setIsSummarizing(true);
    try {
      // Add user message to show what we're summarizing
      addMessage({
        role: 'user',
        content: `Summarize: ${source.url}`,
      });
      
      // Call the article summary endpoint
      const response = await axios.post('http://localhost:8000/api/article/summary', {
        url: source.url.trim(),
        conversation_id: currentConversation.id,
        project_id: currentProject.id,
      });
      
      if (response.data.message_type === 'article_card' && response.data.message_data) {
        addMessage({
          role: 'assistant',
          content: '',
          type: 'article_card',
          data: response.data.message_data,
          model: response.data.model_label || response.data.model || 'Trafilatura + GPT-5',
          provider: response.data.provider || 'trafilatura-gpt5',
        });
      } else {
        // Fallback to error message
        addMessage({
          role: 'assistant',
          content: 'Error: Could not summarize URL. Please try again.',
        });
      }
      
      // Close the popover after summarizing
      setOpen(false);
    } catch (error: any) {
      console.error('Error summarizing article:', error);
      addMessage({
        role: 'assistant',
        content: `Error: ${error.response?.data?.detail || error.message || 'Could not summarize URL. Please try again.'}`,
      });
    } finally {
      setIsSummarizing(false);
    }
  };

  // Only show summarize button for non-RAG sources with URLs
  const showSummarizeButton = source.url && !source.meta?.ragFile && !source.fileName;

  return (
    <>
      <span
        ref={chipRef}
        className="
          text-[12px]
          font-medium
          text-[var(--text-secondary)]
          hover:text-[var(--text-primary)]
          cursor-pointer
          align-super
          leading-none
          px-[1px]
        "
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        onClick={e => {
          e.stopPropagation();
          // Handle RAG files (stored in meta.onOpenFile)
          if (source.meta?.onOpenFile && source.meta?.ragFile) {
            source.meta.onOpenFile(source.meta.ragFile);
          } else if (source.url) {
            window.open(source.url, '_blank', 'noopener,noreferrer');
          }
        }}
        title={source.title}
      >
        {displayText ?? (index + 1).toString()}
      </span>

      {open && typeof document !== 'undefined' && createPortal(
        <div
          ref={popoverRef}
          className="fixed z-[10000] max-w-xs rounded-lg border border-[var(--border-color)] bg-[var(--bg-primary)] p-3 shadow-lg"
          style={{
            top: chipRef.current
              ? chipRef.current.getBoundingClientRect().top - 5
              : 0,
            left: chipRef.current
              ? chipRef.current.getBoundingClientRect().left
              : 0,
            transform: 'translateY(-100%)', // Position above the citation
          }}
          onMouseEnter={handlePopoverMouseEnter}
          onMouseLeave={handlePopoverMouseLeave}
        >
          {(source.siteName || source.fileName) && (
            <div className="mb-1 text-[10px] uppercase tracking-wide text-[var(--text-secondary)]">
              {source.siteName || (source.fileName ? 'RAG File' : '')}
            </div>
          )}
          <div 
            className={`mb-1 line-clamp-2 text-xs font-semibold text-[var(--text-primary)] ${
              source.meta?.onOpenFile && source.meta?.ragFile 
                ? 'cursor-pointer hover:underline' 
                : ''
            }`}
            onClick={e => {
              e.stopPropagation();
              // Handle RAG files (stored in meta.onOpenFile)
              if (source.meta?.onOpenFile && source.meta?.ragFile) {
                source.meta.onOpenFile(source.meta.ragFile);
              }
            }}
          >
            {source.title}
          </div>
          {source.fileName && source.fileName !== source.title && (
            <div className="mb-1 text-[10px] text-[var(--text-secondary)]">
              {source.fileName}
            </div>
          )}
          {source.publishedAt && (
            <div className="mb-1 text-[10px] text-[var(--text-secondary)]">
              {formatDate(source.publishedAt)}
            </div>
          )}
          {source.description && (
            <p className="mb-2 line-clamp-3 text-[11px] text-[var(--text-secondary)]">
              {source.description}
            </p>
          )}
          {source.url && (
            <a
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={e => e.stopPropagation()}
              className="flex items-center gap-1 text-[10px] text-[var(--text-primary)] hover:underline mb-2"
            >
              <svg
                className="h-3 w-3"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"
                />
              </svg>
              {extractDomain(source.url)}
            </a>
          )}
          <div className="mt-2 flex items-center gap-2">
            <div className="text-[10px] text-[var(--text-secondary)]">
              {index + 1}/{total}
            </div>
            {showSummarizeButton && (
              <button
                onClick={handleSummarizeUrl}
                disabled={isSummarizing || !currentProject || !currentConversation}
                className={`p-1.5 rounded transition-colors flex-shrink-0 ${
                  isSummarizing
                    ? 'text-blue-400 cursor-wait'
                    : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--border-color)]'
                }`}
                title={isSummarizing ? "Summarizing..." : "Summarize this URL"}
              >
                {isSummarizing ? (
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                ) : (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                )}
              </button>
            )}
          </div>
        </div>,
        document.body
      )}
    </>
  );
};

