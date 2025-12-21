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
  
  const { currentConversation, currentProject, addMessage, renameChat, setSummarizingArticle, setConversationSummarizing, setCurrentConversation, loadChats, allConversations } = useChatStore();

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
    setSummarizingArticle(true); // Also set shared state for backward compatibility
    if (currentConversation) {
      setConversationSummarizing(currentConversation.id, true); // Set per-conversation state
    }
    try {
      // Auto-name chat based on first message if it's still "New Chat"
      // Check BEFORE adding the user message, since addMessage will increase the length
      const isFirstMessage = currentConversation?.title === 'New Chat' && 
                            currentConversation?.messages.length === 0;
      
      // Add user message to show what we're summarizing
      addMessage({
        role: 'user',
        content: `Summarize: ${source.url}`,
      });
      
      // Auto-rename chat if this is the first message
      if (isFirstMessage && currentConversation) {
        // Generate title from URL (extract domain or use URL)
        let autoTitle = source.url.trim();
        try {
          const urlObj = new URL(source.url);
          autoTitle = urlObj.hostname.replace('www.', '');
          // If hostname is too long, use a shortened version
          if (autoTitle.length > 50) {
            autoTitle = autoTitle.substring(0, 47) + '...';
          }
        } catch {
          // If URL parsing fails, use the URL itself (truncated)
          autoTitle = source.url.length > 50 ? source.url.substring(0, 47) + '...' : source.url;
        }
        
        // Only auto-rename if we got a meaningful title
        if (autoTitle.length > 0) {
          try {
            console.log('[Auto-label] Renaming chat from "New Chat" to:', autoTitle);
            await renameChat(currentConversation.id, autoTitle);
            console.log('[Auto-label] Successfully renamed chat');
          } catch (error) {
            console.error('Failed to auto-name chat:', error);
            // Don't block sending the message if auto-naming fails
          }
        }
      }
      
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
      setSummarizingArticle(false); // Clear shared state for backward compatibility
      if (currentConversation) {
        setConversationSummarizing(currentConversation.id, false); // Clear per-conversation state
      }
    }
  };

  // Only show summarize button for non-RAG sources with URLs
  const showSummarizeButton = source.url && !source.meta?.ragFile && !source.fileName;

  // Handle Memory source clicks (navigate to chat or show file)
  const handleMemorySourceClick = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const kind = source.meta?.kind; // "chat" or "file"
    const chatId = source.meta?.chat_id;
    const filePath = source.meta?.file_path;
    const fileId = source.meta?.file_id;
    const messageUuid = source.meta?.message_uuid; // Stable UUID for deep-linking (chat/facts only)

    // Navigation based on kind
    if (kind === "chat" && chatId) {
      // Try to find the conversation in loaded chats
      let targetConversation = allConversations.find(c => c.id === chatId);
      
      // If not found, try loading all chats
      if (!targetConversation) {
        try {
          await loadChats();
          targetConversation = useChatStore.getState().allConversations.find(c => c.id === chatId);
        } catch (error) {
          console.error('Failed to load chats:', error);
        }
      }

      if (targetConversation) {
        await setCurrentConversation(targetConversation);
        setOpen(false);
        
        // Deep-link to specific message using message_uuid
        if (messageUuid) {
          try {
            const { navigateToMessage } = await import('../utils/messageDeepLink');
            // Wait for conversation to load and messages to render
            // Use a longer delay and retry logic to handle async message loading
            const attemptNavigation = async (attempt: number = 1, maxAttempts: number = 5) => {
              try {
                // Find the messages container for better observation
                const messagesContainer = document.querySelector('[class*="overflow-y-auto"]') as HTMLElement;
                
                await navigateToMessage(messageUuid, {
                  updateUrl: true,
                  timeout: 10000, // Increased timeout to 10 seconds
                  container: messagesContainer, // Pass container for better observation
                });
                console.log(`[DEEP-LINK] Successfully navigated to message ${messageUuid}`);
              } catch (error) {
                if (attempt < maxAttempts) {
                  // Retry after a longer delay
                  console.log(`[DEEP-LINK] Attempt ${attempt} failed, retrying in ${attempt * 200}ms...`);
                  setTimeout(() => attemptNavigation(attempt + 1, maxAttempts), attempt * 200);
                } else {
                  console.warn(`[DEEP-LINK] Failed to navigate to message ${messageUuid} after ${maxAttempts} attempts:`, error);
                  // Fallback: scroll to bottom if specific message not found
                  const messagesContainer = document.querySelector('[class*="overflow-y-auto"]') as HTMLElement;
                  if (messagesContainer) {
                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                  }
                }
              }
            };
            
            // Start navigation after initial delay to allow conversation to load
            setTimeout(() => attemptNavigation(), 500);
          } catch (error) {
            console.error('[DEEP-LINK] Failed to import navigateToMessage:', error);
          }
        }
      } else {
        console.warn(`Chat ${chatId} not found`);
        // Could show a toast/notification here
      }
    } else if (kind === "file" && (filePath || fileId)) {
      // For file sources, open file viewer or navigate to file route
      console.log('Memory file source:', filePath || fileId);
      // TODO: Implement file viewer navigation
      // For now, copy path to clipboard as fallback
      if (filePath) {
        try {
          await navigator.clipboard.writeText(filePath);
          console.log('File path copied to clipboard:', filePath);
        } catch (error) {
          console.error('Failed to copy file path:', error);
        }
      }
    } else {
      console.warn(`Unknown source kind or missing required fields: kind=${kind}, chatId=${chatId}, filePath=${filePath}, fileId=${fileId}`);
    }
  };

  // Check if this is a Memory source with clickable content
  const isMemorySource = source.sourceType === 'memory';
  const hasMemoryClickAction = isMemorySource && (source.meta?.chat_id || source.meta?.file_path);

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
          // Handle Memory sources (navigate to chat or show file)
          if (hasMemoryClickAction) {
            handleMemorySourceClick(e);
          } else if (source.meta?.onOpenFile && source.meta?.ragFile) {
            // Handle RAG files (stored in meta.onOpenFile)
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
          className="fixed z-[10000] w-80 rounded-lg border border-[var(--border-color)] bg-[var(--bg-primary)] p-3 shadow-lg"
          style={{
            top: chipRef.current
              ? chipRef.current.getBoundingClientRect().top - 5
              : 0,
            left: chipRef.current
              ? chipRef.current.getBoundingClientRect().left - 280 // Shift left by 280px (width of pop-out) to show full box
              : 0,
            transform: 'translateY(-100%)', // Position above the citation
          }}
          onMouseEnter={handlePopoverMouseEnter}
          onMouseLeave={handlePopoverMouseLeave}
        >
          {(source.siteName || source.fileName || source.sourceType) && (
            <div className="mb-1 text-[10px] uppercase tracking-wide text-[var(--text-secondary)]">
              {source.siteName || 
               (source.fileName ? 'RAG File' : '') ||
               (source.sourceType === 'memory' ? 'Memory' : '') ||
               (source.sourceType === 'rag' ? 'RAG Document' : '') ||
               (source.sourceType === 'web' ? 'Web Source' : '')}
            </div>
          )}
          <div 
            className={`mb-1 line-clamp-2 text-xs font-semibold text-[var(--text-primary)] ${
              hasMemoryClickAction
                ? 'cursor-pointer hover:underline'
                : source.meta?.onOpenFile && source.meta?.ragFile 
                ? 'cursor-pointer hover:underline' 
                : source.url
                ? 'cursor-pointer hover:underline'
                : ''
            }`}
            onClick={e => {
              e.stopPropagation();
              // Handle Memory sources (navigate to chat or show file)
              if (hasMemoryClickAction) {
                handleMemorySourceClick(e);
              } else if (source.meta?.onOpenFile && source.meta?.ragFile) {
                // Handle RAG files (stored in meta.onOpenFile)
                source.meta.onOpenFile(source.meta.ragFile);
              } else if (source.url) {
                window.open(source.url, '_blank', 'noopener,noreferrer');
              }
            }}
          >
            {source.title || 'Untitled Source'}
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
          {/* Show Memory-specific metadata */}
          {isMemorySource && source.meta?.file_path && (
            <div className="mb-1 text-[10px] text-[var(--text-secondary)] font-mono">
              📄 {source.meta.file_path}
            </div>
          )}
          {isMemorySource && source.meta?.chat_id && (
            <div className="mb-1 text-[10px] text-[var(--text-secondary)]">
              💬 Chat: {source.meta.chat_id.substring(0, 8)}...
            </div>
          )}
          {isMemorySource && source.meta?.role && (
            <div className="mb-1 text-[10px] text-[var(--text-secondary)]">
              {source.meta.role === 'user' ? '👤 User message' : '🤖 Assistant message'}
            </div>
          )}
          {(source.description || (source.sourceType === 'memory' && !source.meta?.content)) && (
            <p className="mb-2 line-clamp-3 text-[11px] text-[var(--text-secondary)]">
              {source.description || 
               (source.sourceType === 'memory' ? 'This information comes from your project memory, which includes past conversations and indexed files.' : '')}
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
                title={isSummarizing ? "Summarizing..." : "Summarize URL"}
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

