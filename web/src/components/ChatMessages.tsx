import React, { useEffect, useRef, useState, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useChatStore, type Message } from '../store/chat';
import axios from 'axios';
import ArticleCard from './ArticleCard';
import DocumentCard from './DocumentCard';
import RagResponseCard from './RagResponseCard';
import { AssistantCard } from './shared/AssistantCard';
import { InlineSourceCitations } from './InlineSourceCitations';
import type { RagFile } from '../types/rag';
import type { Source } from '../types/sources';
import { useTheme } from '../contexts/ThemeContext';

/**
 * Format timestamp for display: "13 Dec 2025 · 18:43"
 * Uses local timezone, no seconds, human-readable format.
 */
function formatResponseTimestamp(date: Date): string {
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const day = date.getDate();
  const month = months[date.getMonth()];
  const year = date.getFullYear();
  const hours = date.getHours().toString().padStart(2, '0');
  const minutes = date.getMinutes().toString().padStart(2, '0');
  return `${day} ${month} ${year} · ${hours}:${minutes}`;
}

// Extract bullet options from message content

const extractBulletOptionsFromMessage = (content: string): string[] => {
  const bullets: string[] = [];
  const lines = content.split('\n');
  let inCodeBlock = false;
  let currentBullet = '';
  let codeBlockBullets: string[] = [];
  
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    
    // Track code block state
    if (trimmed.startsWith('```')) {
      if (inCodeBlock) {
        // End of code block - save current bullet if exists
        if (currentBullet.trim()) {
          codeBlockBullets.push(currentBullet.trim());
          currentBullet = '';
        }
        // If we found bullets in code block, use those
        if (codeBlockBullets.length > 0) {
          bullets.push(...codeBlockBullets);
          codeBlockBullets = [];
        }
      } else {
        // Start of code block
        codeBlockBullets = [];
      }
      inCodeBlock = !inCodeBlock;
      continue;
    }
    
    // Inside code block - collect bullet text
    if (inCodeBlock) {
      if (trimmed) {
        // Check if this looks like a new bullet (starts with number, Option label, or bullet char)
        const numberedMatch = trimmed.match(/^(\d+)[.)]\s*(.+)$/);
        const optionMatch = trimmed.match(/^Option\s+[ABC\d]+[:\-]?\s*(.+)$/i);
        const bulletCharMatch = trimmed.match(/^[•\-\*]\s*(.+)$/);
        
        if (numberedMatch || optionMatch || bulletCharMatch) {
          // Save previous bullet
          if (currentBullet.trim()) {
            codeBlockBullets.push(currentBullet.trim());
          }
          // Start new bullet
          currentBullet = numberedMatch ? numberedMatch[2] : 
                         optionMatch ? optionMatch[1] : 
                         bulletCharMatch![1];
        } else if (currentBullet) {
          // Continuation of current bullet
          currentBullet += ' ' + trimmed;
        } else {
          // First line in code block - start new bullet
          currentBullet = trimmed;
        }
      } else if (currentBullet.trim()) {
        // Empty line in code block - end of current bullet
        codeBlockBullets.push(currentBullet.trim());
        currentBullet = '';
      }
      continue;
    }
    
    // Outside code block - check for bullet patterns
    // Look for numbered bullets (1., 2., 3., etc.) or Option labels
    const numberedMatch = trimmed.match(/^(\d+)[.)]\s*(.+)$/);
    const optionMatch = trimmed.match(/^Option\s+[ABC\d]+[:\-]?\s*(.+)$/i);
    
    if (numberedMatch || optionMatch) {
      if (currentBullet.trim()) {
        bullets.push(currentBullet.trim());
      }
      currentBullet = numberedMatch ? numberedMatch[2] : optionMatch![1];
      continue;
    }
    
    // Check if line starts with bullet character
    if (trimmed.match(/^[•\-\*]\s*(.+)$/)) {
      if (currentBullet.trim()) {
        bullets.push(currentBullet.trim());
      }
      currentBullet = trimmed.replace(/^[•\-\*]\s*/, '');
      continue;
    }
    
    // Check for "Option A:", "Option B:", etc. headings followed by content
    const optionHeadingMatch = trimmed.match(/^###\s+Option\s+([ABC\d])/i);
    if (optionHeadingMatch) {
      if (currentBullet.trim()) {
        bullets.push(currentBullet.trim());
      }
      currentBullet = '';
      // Next non-empty line should be the bullet content
      continue;
    }
    
    // If we have a current bullet and this line looks like continuation
    if (currentBullet && trimmed && !trimmed.match(/^(Tip|💡|Options?|###)/i)) {
      currentBullet += ' ' + trimmed;
    } else if (currentBullet.trim()) {
      // End of bullet
      bullets.push(currentBullet.trim());
      currentBullet = '';
    }
  }
  
  // Add last bullet if exists
  if (currentBullet.trim()) {
    bullets.push(currentBullet.trim());
  }
  
  // Clean up bullets - remove markdown formatting, extra whitespace
  return bullets
    .filter(b => b.length > 0)
    .map(b => b.replace(/^\*\s*/, '').replace(/^-\s*/, '').trim())
    .filter(b => b.length > 0);
};

// Shared utility: Preprocess content to fix numbered lists that all start with "1."
// This ensures proper sequential numbering even when the model outputs "1." for each item
// Export it so other components can use it too
export function fixNumberedLists(content: string): string {
  const lines = content.split('\n');
  const fixed: string[] = [];
  let listCounter = 0; // Will be set to 1 on first list item
  let consecutiveBlankLines = 0;
  const maxBlankLinesInList = 1; // Allow one blank line within a list

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    
    // Check if this is a numbered list item (starts with number followed by period/dot or parenthesis)
    const listItemMatch = trimmed.match(/^(\d+)[.)]\s+(.+)$/);
    
    if (listItemMatch) {
      const itemNumber = parseInt(listItemMatch[1], 10);
      const itemContent = listItemMatch[2];
      
      // If this is the first item in a sequence (number is 1) or we're continuing a list
      if (itemNumber === 1 && listCounter === 0) {
        // Starting a new list
        listCounter = 1;
      } else if (itemNumber === 1 && listCounter > 0 && consecutiveBlankLines <= maxBlankLinesInList) {
        // Continuing the same list (item marked as 1 but we're already counting)
        listCounter++;
      } else if (itemNumber > 1 && listCounter > 0) {
        // Explicit numbering that's higher than our counter - use it
        listCounter = itemNumber;
      } else if (itemNumber > 1 && listCounter === 0) {
        // Starting a new list with explicit numbering > 1
        listCounter = itemNumber;
      } else {
        // Shouldn't happen, but increment counter
        listCounter++;
      }
      
      // Preserve original indentation
      const indent = line.match(/^(\s*)/)?.[1] || '';
      fixed.push(`${indent}${listCounter}. ${itemContent}`);
      consecutiveBlankLines = 0;
    } else if (trimmed === '') {
      // Blank line
      consecutiveBlankLines++;
      fixed.push(line);
      
      // If too many blank lines, reset the list counter (new list will start)
      if (consecutiveBlankLines > maxBlankLinesInList) {
        listCounter = 0;
      }
    } else {
      // Non-list line - reset list state
      listCounter = 0;
      consecutiveBlankLines = 0;
      fixed.push(line);
    }
  }

  return fixed.join('\n');
}

// Component to render GPT messages with proper markdown formatting
const GPTMessageRenderer: React.FC<{ content: string; sources?: Source[] }> = ({ content, sources }) => {
  const hasSources = sources && sources.length > 0;
  
  // Fix numbered lists before rendering
  const processedContent = React.useMemo(() => fixNumberedLists(content), [content]);

  // Pre-process the entire content to build a shared usedSources array
  // This ensures all citation chips show the correct total (e.g., "1/2", "2/2")
  // Citations are numbered sequentially based on their first appearance in the text
  const sharedUsedSources = React.useMemo(() => {
    if (!hasSources) return null;

    // Sort sources by rank first (for consistent source ordering)
    const sortedSources = [...sources].sort((a, b) => {
      const aRank = a.rank ?? Infinity;
      const bRank = b.rank ?? Infinity;
      return aRank - bRank;
    });

    // Pre-scan the entire content for citations in order of appearance
    // Support [1], [R1], [M1], [W1] patterns
    const citationPattern = /\[([RMW]?\d+(?:\s*,\s*[RMW]?\d+)*)\]/g;
    const firstAppearanceOrder: string[] = []; // Track citation keys (e.g., "1", "R1", "M2")
    const seenCitations = new Set<string>();

    let scanMatch: RegExpExecArray | null;
    citationPattern.lastIndex = 0;
    while ((scanMatch = citationPattern.exec(content)) !== null) {
      const citationStrs = scanMatch[1].split(',').map(s => s.trim());
      
      citationStrs.forEach(citationStr => {
        // Parse citation: extract prefix and number
        const trimmed = citationStr.trim();
        let prefix: 'R' | 'M' | 'W' | null = null;
        let number: number;
        
        if (trimmed.startsWith('R')) {
          prefix = 'R';
          number = parseInt(trimmed.substring(1), 10);
        } else if (trimmed.startsWith('M')) {
          prefix = 'M';
          number = parseInt(trimmed.substring(1), 10);
        } else if (trimmed.startsWith('W')) {
          prefix = 'W';
          number = parseInt(trimmed.substring(1), 10);
        } else {
          number = parseInt(trimmed, 10);
        }
        
        if (!Number.isNaN(number) && number > 0) {
          const citationKey = prefix ? `${prefix}${number}` : String(number);
          if (!seenCitations.has(citationKey)) {
            seenCitations.add(citationKey);
            firstAppearanceOrder.push(citationKey);
          }
        }
      });
    }

    // Group sources by type
    const webSources: Source[] = [];
    const ragSources: Source[] = [];
    const memorySources: Source[] = [];

    sortedSources.forEach(source => {
      const prefix = source.citationPrefix ?? (source.sourceType === 'rag' ? 'R' : source.sourceType === 'memory' ? 'M' : null);
      if (prefix === 'R') {
        ragSources.push(source);
      } else if (prefix === 'M') {
        memorySources.push(source);
      } else {
        webSources.push(source);
      }
    });

    // Build citation to source mapping
    const citationToSource = new Map<string, Source>();
    webSources.forEach((source, idx) => {
      citationToSource.set(String(idx + 1), source);
    });
    ragSources.forEach((source, idx) => {
      citationToSource.set(`R${idx + 1}`, source);
    });
    memorySources.forEach((source, idx) => {
      citationToSource.set(`M${idx + 1}`, source);
    });

    // Build usedSources array in order of first appearance
    const usedSources: Source[] = [];
    const usedNumberToIndex = new Map<string, number>();

    firstAppearanceOrder.forEach((citationKey) => {
      const source = citationToSource.get(citationKey);
      if (source) {
        const sequentialIndex = usedSources.length;
        usedSources.push(source);
        usedNumberToIndex.set(citationKey, sequentialIndex);
      }
    });

    return { usedSources, usedNumberToIndex: usedNumberToIndex as Map<string, number> | Map<number, number> };
  }, [content, sources, hasSources]);

  // Helper to process children for citations
  // Only processes string/number children to avoid invalid HTML nesting
  const processChildrenForCitations = (children: React.ReactNode): React.ReactNode => {
    if (!hasSources || !sharedUsedSources) {
      return children;
    }

    // Only process simple string/number children - don't process already-rendered React elements
    // This prevents invalid HTML nesting (e.g., div inside p)
    // Support [1], [R1], [M1], [W1] patterns
    const citationPattern = /\[([RMW]?\d+(?:\s*,\s*[RMW]?\d+)*)\]/;
    
    if (typeof children === 'string') {
      // Only process if there are citations in the text
      if (citationPattern.test(children)) {
        return <InlineSourceCitations text={children} sources={sources} sharedUsedSources={sharedUsedSources.usedSources} sharedUsedNumberToIndex={sharedUsedSources.usedNumberToIndex} />;
      }
      return children;
    }

    if (typeof children === 'number') {
      const text = String(children);
      if (citationPattern.test(text)) {
        return <InlineSourceCitations text={text} sources={sources} sharedUsedSources={sharedUsedSources.usedSources} sharedUsedNumberToIndex={sharedUsedSources.usedNumberToIndex} />;
      }
      return children;
    }

    // If it's an array, only process string/number elements, leave React elements untouched
    if (Array.isArray(children)) {
      return children.map((child, idx) => {
        // Only process primitive types - React elements are already rendered correctly
        if (typeof child === 'string') {
          if (citationPattern.test(child)) {
            return <InlineSourceCitations key={idx} text={child} sources={sources} sharedUsedSources={sharedUsedSources.usedSources} sharedUsedNumberToIndex={sharedUsedSources.usedNumberToIndex} />;
          }
          return child;
        }
        if (typeof child === 'number') {
          const text = String(child);
          if (citationPattern.test(text)) {
            return <InlineSourceCitations key={idx} text={text} sources={sources} sharedUsedSources={sharedUsedSources.usedSources} sharedUsedNumberToIndex={sharedUsedSources.usedNumberToIndex} />;
          }
          return child;
        }
        // For React elements, return as-is to avoid nesting issues
        return child;
      });
    }

    // For React elements, return as-is (don't process - they're already rendered)
    return children;
  };

  // Default markdown rendering (always use markdown, even with sources)
  return (
    <AssistantCard>
      <div className="prose max-w-[720px] mx-auto text-[0.95rem] leading-relaxed space-y-4">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            h1: ({ children }) => <h1 className="text-2xl font-bold mt-6 mb-4 text-[var(--text-primary)]">{processChildrenForCitations(children)}</h1>,
            h2: ({ children }) => <h2 className="text-xl font-semibold mt-5 mb-3 text-[var(--text-primary)]">{processChildrenForCitations(children)}</h2>,
            h3: ({ children }) => <h3 className="text-lg font-semibold mt-4 mb-2 text-[var(--text-primary)]">{processChildrenForCitations(children)}</h3>,
            h4: ({ children }) => <h4 className="text-base font-semibold mt-3 mb-2 text-[var(--text-primary)]">{processChildrenForCitations(children)}</h4>,
            p: ({ children }) => {
              // Extract text content from children to avoid nesting issues
              // ReactMarkdown may pass React elements, so we need to be careful
              const processed = processChildrenForCitations(children);
              return <p className="my-2 text-[var(--text-primary)] leading-relaxed">{processed}</p>;
            },
            ul: ({ children }) => <ul className="list-disc ml-6 space-y-1 my-2 text-[var(--text-primary)]">{children}</ul>,
            ol: ({ children }) => <ol className="list-decimal ml-6 space-y-1 my-2 text-[var(--text-primary)]">{children}</ol>,
            li: ({ children }) => {
              return <li className="leading-relaxed">{processChildrenForCitations(children)}</li>;
            },
            table: ({ children }) => (
              <div className="overflow-x-auto my-4">
                <table className="w-full border-collapse table-fixed">
                  {children}
                </table>
              </div>
            ),
            thead: ({ children }) => <thead className="bg-[var(--bg-primary)]">{children}</thead>,
            tbody: ({ children }) => <tbody>{children}</tbody>,
            tr: ({ children }) => <tr className="border-b border-[var(--border-color)]">{children}</tr>,
            th: ({ children }) => (
              <th className="border-b border-[var(--border-color)] px-3 py-2 font-medium text-left text-[var(--text-primary)]">
                {children}
              </th>
            ),
            td: ({ children }) => (
              <td className="border-b border-[var(--border-color)] px-3 py-2 align-top text-[var(--text-primary)]">
                {processChildrenForCitations(children)}
              </td>
            ),
            code: ({ className, children, ...props }) => {
              const isInline = !className;
              return isInline ? (
                <code className="bg-[var(--code-bg)] rounded px-1.5 py-0.5 font-mono text-[0.85em] text-[var(--text-primary)]" {...props}>
                  {children}
                </code>
              ) : (
                <code className="font-mono text-sm" {...props}>
                  {children}
                </code>
              );
            },
            pre: ({ children }) => (
              <pre className="bg-[var(--code-bg)] rounded-lg p-3 font-mono text-sm overflow-x-auto my-3 text-[var(--text-primary)]">
                {children}
              </pre>
            ),
            blockquote: ({ children }) => (
              <blockquote className="border-l-4 border-[var(--border-color)] pl-4 ml-1 my-3 italic text-[var(--text-primary)]">
                {children}
              </blockquote>
            ),
            strong: ({ children }) => <strong className="font-semibold text-[var(--text-primary)]">{children}</strong>,
            em: ({ children }) => <em className="italic text-[var(--text-primary)]">{children}</em>,
          }}
        >
          {processedContent}
        </ReactMarkdown>
      </div>
    </AssistantCard>
  );
};

// Component to render bullet options with cards
const OptionsRenderer: React.FC<{ content: string; bulletMode?: '1206_2LINE' | 'OPB_350' | 'OPB_450' | 'FREE'; sources?: Source[] }> = ({ content, bulletMode, sources }) => {
  const [bulletOptions, setBulletOptions] = useState<string[]>([]);
  const [hasOptions, setHasOptions] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  useEffect(() => {
    // Only show bullet options card inside the Bullet Workspace
    // where bulletMode is explicitly one of the constrained modes.
    if (!bulletMode || bulletMode === 'FREE') {
      setBulletOptions([]);
      setHasOptions(false);
      return;
    }

    // Try to detect bullet-style Award/OPB responses
    // Check for explicit "Option" labels, numbered bullets, or specific phrases
    const hasExplicitPattern =
      content.match(/Options?|bullet options?/i) ||
      content.match(/Option\s+[ABC\d]/i) ||
      content.match(/^\d+[.)]\s+/m) ||
      content.match(/Acted\s+Dir|Assumed\s+DAF|Led\s+DAF/i) ||
      content.match(/ops—?0\s+outages?|0\s+cuts/i);

    // Also check for multiple bullet points (lines starting with "- ") - this indicates bullet options
    // even without explicit "Option" labels
    const bulletLines = content.split('\n').filter(line => {
      const trimmed = line.trim();
      return trimmed.match(/^[-•*]\s+/);
    });
    const hasMultipleBullets = bulletLines.length >= 2;

    // Extract bullets if we have explicit patterns OR multiple bullet points
    if (hasExplicitPattern || hasMultipleBullets) {
      let extracted = extractBulletOptionsFromMessage(content);
      
      // For Award (215) bullets and when we detect multiple bullets, ensure each option starts with "- "
      // This preserves the bullet format that users expect in the Bullet Workspace
      // Note: bulletMode is guaranteed to not be 'FREE' at this point (checked above)
      if (bulletMode === '1206_2LINE' || hasMultipleBullets) {
        extracted = extracted.map(bullet => {
          const trimmed = bullet.trim();
          // If it doesn't start with "- ", add it
          if (!trimmed.startsWith('- ')) {
            return `- ${trimmed}`;
          }
          return trimmed;
        });
      }
      
      if (extracted.length > 0) {
        setBulletOptions(extracted.slice(0, 3)); // Only first 3 options
        setHasOptions(true);
        return;
      }
    }

    setBulletOptions([]);
    setHasOptions(false);
  }, [content, bulletMode]);

  const labels = ['A', 'B', 'C'];

  // If we didn't detect structured bullet options, use GPTMessageRenderer for proper formatting
  if (!hasOptions || bulletOptions.length === 0) {
    return <GPTMessageRenderer content={content} sources={sources} />;
  }

  // Otherwise, render only the clean bullet options card (no extra intro text or tips)
  return (
    <div className="prose max-w-none">
      <div className="mt-1">
        <div className="text-sm font-semibold text-[var(--text-primary)] mb-3">
          ✍️ Bullet options
        </div>
        <div className="space-y-3">
          {bulletOptions.map((text, index) => {
            const charCount = text.length;
            const label = labels[index] ?? String(index + 1);

            return (
              <div
                key={index}
                className="rounded-lg bg-slate-800/80 border border-slate-700 p-3"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-slate-300">
                    {`Option ${label} — ${charCount} chars`}
                  </span>
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(text);
                        setCopiedIndex(index);
                        setTimeout(() => setCopiedIndex(null), 1500);
                      } catch (err) {
                        console.error('Failed to copy option text:', err);
                      }
                    }}
                    className="p-1.5 hover:bg-[var(--border-color)]/50 rounded transition-colors text-[var(--text-secondary)] hover:text-[var(--text-primary)] flex items-center justify-center"
                    title={`Copy ${label} bullet`}
                    aria-label={`Copy ${label} bullet`}
                  >
                    {copiedIndex === index ? (
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                    ) : (
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                      </svg>
                    )}
                  </button>
                </div>
                <pre
                  className="bullet-option text-xs text-slate-200 leading-snug m-0 p-0"
                  style={{
                    whiteSpace: 'normal',
                    overflowWrap: 'break-word',
                    wordBreak: 'break-word',
                    overflowX: 'hidden',
                    fontFamily:
                      'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
                  }}
                >
                  {text}
                </pre>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

interface ChatMessagesProps {
  impactScopedMessages?: Message[];
  onMessagesChange?: (messages: Message[]) => void;
  selectedImpactId?: string | null;
  bulletMode?: '1206_2LINE' | 'OPB_350' | 'OPB_450' | 'FREE';
}

const ChatMessages: React.FC<ChatMessagesProps> = ({ 
  impactScopedMessages,
  // onMessagesChange and selectedImpactId are reserved for future use
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  onMessagesChange: _onMessagesChange,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  selectedImpactId: _selectedImpactId,
  bulletMode,
}) => {
  const { 
    messages: storeMessages, 
    isStreaming, 
    streamingContent, 
    currentConversation, 
    currentProject, 
    setViewMode, 
    viewMode, 
    renameChat,
    deleteMessage,
    setSummarizingArticle,
    isRagTrayOpen,
    ragFileIds, // Get ragFileIds to match backend order
    ragFilesByConversationId, // Get the actual store value reactively
  } = useChatStore();
  
  const { theme } = useTheme();
  
  // Use impact-scoped messages if provided, otherwise use store messages
  const messages = impactScopedMessages ?? storeMessages;
  
  // Track which articles are being summarized or have been summarized
  const [articleStates, setArticleStates] = useState<Record<string, 'idle' | 'summarizing' | 'summarized'>>({});
  
  const [previewFile, setPreviewFile] = useState<{name: string, data: string, type: 'image' | 'pdf' | 'pptx' | 'xlsx' | 'docx' | 'video' | 'other', mimeType: string} | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [editTitleValue, setEditTitleValue] = useState('');
  const titleInputRef = useRef<HTMLInputElement>(null);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const previewModalRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const previousConversationIdRef = useRef<string | null>(null);
  const hasScrolledToBottomRef = useRef(false);
  const lastUserMessageIdRef = useRef<string | null>(null);
  const userMessageRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  
  // Helper function to format model names for display
  const formatModelName = (model: string): string => {
    // Map old labels to new labels for backward compatibility
    if (model === "Web + GPT-5") {
      return "Brave + GPT-5";
    }
    if (model === "Web + Memory + GPT-5") {
      return "Brave + Memory + GPT-5";
    }
    if (model === "Brave Search") {
      return "Brave";
    }
    if (model.startsWith('gpt-5')) {
      return 'GPT-5';
    }
    return model;
  };

  // Check if RAG was used in a message
  const hasRagSources = (message: Message): boolean => {
    // Check if message type is rag_response
    if (message.type === 'rag_response') {
      return true;
    }
    // Check if message has RAG sources
    if (message.sources && message.sources.some((s: Source) => s.sourceType === 'rag' || s.citationPrefix === 'R')) {
      return true;
    }
    // Check if content has RAG citations [R1], [R2], etc.
    if (message.content && /\[R\d+/.test(message.content)) {
      return true;
    }
    return false;
  };

  
  // Get RAG files from store (conversation-scoped) - reactively subscribe to store changes
  const ragFiles = useMemo(() => {
    if (!currentConversation?.id) return [];
    return ragFilesByConversationId[currentConversation.id] || [];
  }, [currentConversation?.id, ragFilesByConversationId]);

  // Compute indexed RAG files once - this is the single source of truth
  // CRITICAL: Use ragFileIds order to match backend numbering (not created_at order!)
  // Only files with text_extracted get numbered (1-based)
  const ragFilesWithIndex = useMemo(() => {
    if (!ragFileIds || ragFileIds.length === 0) return [];
    
    // Create a lookup map for fast access
    const filesById = new Map<string, RagFile>(ragFiles.map((f: RagFile) => [f.id, f]));
    
    // Build indexed files in the SAME ORDER as ragFileIds (matches backend)
    const indexed: RagFile[] = [];
    ragFileIds.forEach((fileId: string, _idx: number) => {
      const file = filesById.get(fileId);
      if (file && file.text_extracted) {
        indexed.push({
          ...file,
          index: indexed.length + 1, // 1-based index, only counting ready files
        });
      }
    });
    
    return indexed;
  }, [ragFiles, ragFileIds]);

  // Handler to open RAG file in preview - accepts file object
  const handleOpenRagFile = async (file: RagFile) => {
    if (!file) {
      console.error('[RAG] File not provided');
      return;
    }

    console.log('[RAG] Opening file:', file.filename, 'path:', file.path, 'text_path:', file.text_path);

    // Use stored path if available
    let previewPath = '';
    let apiPath = '';
    
    if (file.path) {
      // path format from backend: uploads/rag/chat_id/uuid.ext
      // For direct file access: http://localhost:8000/uploads/rag/chat_id/uuid.ext
      // For API endpoints: rag/chat_id/uuid.ext (without uploads/ prefix)
      if (file.path.startsWith('uploads/')) {
        apiPath = file.path.substring(8); // Remove "uploads/" prefix
        previewPath = `http://localhost:8000/${file.path}`;
      } else {
        apiPath = file.path;
        previewPath = `http://localhost:8000/uploads/${file.path}`;
      }
    } else if (file.text_path) {
      // Fallback: find original file by querying the backend
      // text_path format: uploads/rag/chat_id/uuid.txt
      // We need to find the original file in the same directory
      try {
        // Query backend to find the original file
        const response = await axios.get(`http://localhost:8000/api/rag/find-original`, {
          params: {
            text_path: file.text_path,
            mime_type: file.mime_type
          }
        });
        
        if (response.data && response.data.path) {
          const foundPath = response.data.path;
          if (foundPath.startsWith('uploads/')) {
            apiPath = foundPath.substring(8);
            previewPath = `http://localhost:8000/${foundPath}`;
          } else {
            apiPath = foundPath;
            previewPath = `http://localhost:8000/uploads/${foundPath}`;
          }
        } else {
          console.error('[RAG] Could not find original file for:', file.filename);
          alert(`Unable to open file: ${file.filename}. The file may have been moved or deleted.`);
          return;
        }
      } catch (error) {
        console.error('[RAG] Error finding original file:', error);
        alert(`Unable to open file: ${file.filename}. Please try re-uploading the file.`);
        return;
      }
    } else {
      console.error('[RAG] No path or text_path available for file:', file.filename);
      alert(`Unable to open file: ${file.filename}. File path information is missing.`);
      return;
    }

    console.log('[RAG] Preview path:', previewPath, 'API path:', apiPath);

    const mimeType = file.mime_type;

    // Reset fullscreen state when opening a new file
    setIsFullscreen(false);

    if (mimeType === 'application/pdf') {
      setPreviewFile({ name: file.filename, data: previewPath, type: 'pdf', mimeType });
    } else if (mimeType.includes('presentation') || mimeType.includes('powerpoint')) {
      // URL encode the path segments to handle special characters
      const encodedPath = apiPath.split('/').map(segment => encodeURIComponent(segment)).join('/');
      setPreviewFile({ name: file.filename, data: `http://localhost:8000/api/pptx-preview/${encodedPath}`, type: 'pptx', mimeType });
    } else if (mimeType.includes('spreadsheet') || mimeType.includes('excel') || mimeType.includes('sheet')) {
      // URL encode the path segments to handle special characters
      const encodedPath = apiPath.split('/').map(segment => encodeURIComponent(segment)).join('/');
      setPreviewFile({ name: file.filename, data: `http://localhost:8000/api/xlsx-preview/${encodedPath}`, type: 'xlsx', mimeType });
    } else if (mimeType.includes('word') || mimeType.includes('wordprocessing')) {
      // URL encode the path segments to handle special characters
      const encodedPath = apiPath.split('/').map(segment => encodeURIComponent(segment)).join('/');
      setPreviewFile({ name: file.filename, data: `http://localhost:8000/api/docx-preview/${encodedPath}`, type: 'docx', mimeType });
    } else {
      setPreviewFile({ name: file.filename, data: previewPath, type: 'other', mimeType });
    }
  };
  
  
  // Track conversation changes to detect initial load
  useEffect(() => {
    const currentId = currentConversation?.id || null;
    if (currentId !== previousConversationIdRef.current) {
      // Conversation changed - reset scroll flag and tracking refs
      hasScrolledToBottomRef.current = false;
      previousConversationIdRef.current = currentId;
      lastUserMessageIdRef.current = null;
      previousMessagesLengthRef.current = 0;
      previousLastMessageRoleRef.current = null;
      
      // Check if URL has a hash fragment for deep-linking
      const hash = window.location.hash;
      if (hash && hash.startsWith('#message-')) {
        // Extract message ID from hash
        const messageId = hash.replace('#message-', '');
        console.log(`[DEEP-LINK] URL hash detected: ${hash}, messageId: ${messageId}`);
        
        // Wait for messages to load, then navigate
        const navigateToHashMessage = async (attempt: number = 1, maxAttempts: number = 5) => {
          try {
            const { navigateToMessage } = await import('../utils/messageDeepLink');
            const messagesContainer = messagesContainerRef.current;
            
            if (!messagesContainer) {
              throw new Error('Messages container not found');
            }
            
            await navigateToMessage(messageId, {
              updateUrl: true,
              timeout: 10000,
              container: messagesContainer,
            });
            console.log(`[DEEP-LINK] Successfully navigated to message from URL hash: ${messageId}`);
          } catch (error) {
            if (attempt < maxAttempts) {
              // Retry after a delay
              console.log(`[DEEP-LINK] Attempt ${attempt} failed for URL hash ${messageId}, retrying in ${attempt * 200}ms...`);
              setTimeout(() => navigateToHashMessage(attempt + 1, maxAttempts), attempt * 200);
            } else {
              console.warn(`[DEEP-LINK] Failed to navigate to message from URL hash ${messageId} after ${maxAttempts} attempts:`, error);
              // Fallback: scroll to bottom
              if (messagesContainerRef.current) {
                messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight;
              }
            }
          }
        };
        
        // Wait a bit for messages to render, then start navigation
        setTimeout(() => navigateToHashMessage(), 500);
      } else {
        // No hash - scroll to bottom on conversation change (no animation)
        // Use requestAnimationFrame to ensure DOM is ready
        requestAnimationFrame(() => {
          if (messagesContainerRef.current) {
            messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight;
          }
        });
      }
    }
  }, [currentConversation?.id]);

  // Track last user message and detect when a new user message or assistant response arrives
  const previousMessagesLengthRef = useRef(0);
  const previousLastMessageRoleRef = useRef<'user' | 'assistant' | null>(null);
  
  useEffect(() => {
    if (messages.length > 0) {
      const lastMessage = messages[messages.length - 1];
      const lastMessageRole = lastMessage.role;
      const messagesLength = messages.length;
      
      // Skip aggressive scroll behavior for web_search_results messages to avoid layout shifts
      const isWebSearchResults = lastMessage.type === 'web_search_results';
      
      // Find the last user message
      for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].role === 'user') {
          const userMessageId = messages[i].id;
          // If this is a new user message (different from last tracked), update ref and scroll to it
          if (userMessageId !== lastUserMessageIdRef.current) {
            lastUserMessageIdRef.current = userMessageId;
            
            // Only scroll aggressively if it's NOT a web_search_results message
            // For web_search_results, let it render naturally without forcing scroll
            if (!isWebSearchResults) {
              // Scroll to show the new user question (so user can see it and thinking indicator)
              // Use multiple requestAnimationFrame calls and setTimeout to ensure DOM is fully updated
              requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                  setTimeout(() => {
                    const userMessageElement = userMessageRefs.current.get(userMessageId);
                    const container = messagesContainerRef.current;
                    if (userMessageElement && container) {
                      // Calculate exact scroll position to put user message at top
                      const containerRect = container.getBoundingClientRect();
                      const elementRect = userMessageElement.getBoundingClientRect();
                      const scrollTop = container.scrollTop;
                      const elementTopRelativeToContainer = elementRect.top - containerRect.top + scrollTop;
                      // Scroll so user message is at the very top
                      container.scrollTop = elementTopRelativeToContainer;
                    }
                  }, 50);
                });
              });
            }
          }
          break;
        }
      }
      
      // Update tracking refs
      previousMessagesLengthRef.current = messagesLength;
      previousLastMessageRoleRef.current = lastMessageRole;
    }
  }, [messages]);

  // Auto-scroll to user's question when assistant responds (not to bottom)
  useEffect(() => {
    if (!isStreaming && messages.length > 0) {
      const isInitialLoad = !hasScrolledToBottomRef.current;
      const lastMessage = messages[messages.length - 1];
      const isNewAssistantResponse = 
        lastMessage.role === 'assistant' &&
        previousLastMessageRoleRef.current === 'user';
      
      // Skip aggressive scroll for web_search_results to avoid layout shifts
      const isWebSearchResults = lastMessage.type === 'web_search_results';
      
      if (isInitialLoad) {
        // For initial load, scroll to bottom (showing latest messages)
        requestAnimationFrame(() => {
          if (messagesContainerRef.current) {
            messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight;
            hasScrolledToBottomRef.current = true;
          }
        });
      } else if (isNewAssistantResponse && lastUserMessageIdRef.current && !isWebSearchResults) {
        // For new assistant responses (but NOT web_search_results), scroll to the user's question at the top
        // This allows reading from the top of the response
        requestAnimationFrame(() => {
          const userMessageElement = userMessageRefs.current.get(lastUserMessageIdRef.current!);
          const container = messagesContainerRef.current;
          if (userMessageElement && container) {
            // Use scrollIntoView with start alignment to position at top
            // Then adjust slightly to account for any container padding
            userMessageElement.scrollIntoView({ behavior: 'smooth', block: 'start', inline: 'nearest' });
            // Small delay to ensure scrollIntoView completes, then fine-tune
            setTimeout(() => {
              const containerRect = container.getBoundingClientRect();
              const elementRect = userMessageElement.getBoundingClientRect();
              const offset = elementRect.top - containerRect.top;
              if (offset > 0) {
                container.scrollTop -= offset;
              }
            }, 100);
          }
        });
      } else if (isWebSearchResults) {
        // For web_search_results, just smoothly scroll to show the results without aggressive positioning
        // This prevents the rapid shift up/down
        requestAnimationFrame(() => {
          if (messagesContainerRef.current) {
            // Smooth scroll to bottom to show the new web search results
            messagesContainerRef.current.scrollTo({ 
              top: messagesContainerRef.current.scrollHeight, 
              behavior: 'smooth' 
            });
          }
        });
      }
    }
  }, [messages, isStreaming]);

  // Scroll to user's question when streaming starts (thinking indicator appears)
  useEffect(() => {
    if (isStreaming && lastUserMessageIdRef.current) {
      // When streaming starts, immediately scroll to show user's question and thinking indicator
      const scrollToQuestion = () => {
        const userMessageElement = userMessageRefs.current.get(lastUserMessageIdRef.current!);
        const container = messagesContainerRef.current;
        if (userMessageElement && container) {
          // Calculate exact position to put user message at top
          const containerRect = container.getBoundingClientRect();
          const elementRect = userMessageElement.getBoundingClientRect();
          const scrollTop = container.scrollTop;
          const elementTopRelativeToContainer = elementRect.top - containerRect.top + scrollTop;
          // Scroll so user message is at the very top
          container.scrollTop = elementTopRelativeToContainer;
        }
      };
      
      // Try multiple times to ensure it works
      requestAnimationFrame(() => {
        scrollToQuestion();
        requestAnimationFrame(() => {
          scrollToQuestion();
          setTimeout(() => scrollToQuestion(), 50);
          setTimeout(() => scrollToQuestion(), 200);
        });
      });
    }
  }, [isStreaming]);

  // Keep user's question visible during streaming (thinking indicator) and when response completes
  useEffect(() => {
    if (isStreaming && lastUserMessageIdRef.current) {
      // During streaming (thinking indicator), keep user's question visible at the top
      // This ensures user can see their question and the thinking indicator
      const timeoutId = setTimeout(() => {
        const userMessageElement = userMessageRefs.current.get(lastUserMessageIdRef.current!);
        const container = messagesContainerRef.current;
        if (userMessageElement && container) {
          // Scroll to user's question at the top so thinking indicator is visible below it
          userMessageElement.scrollIntoView({ behavior: 'auto', block: 'start', inline: 'nearest' });
          // Fine-tune position to ensure it's at the very top
          const containerRect = container.getBoundingClientRect();
          const elementRect = userMessageElement.getBoundingClientRect();
          const offset = elementRect.top - containerRect.top;
          if (offset > 0) {
            container.scrollTop -= offset;
          }
        }
      }, 100); // Check periodically during streaming to keep question visible
      return () => clearTimeout(timeoutId);
    } else if (!isStreaming && messages.length > 0 && lastUserMessageIdRef.current) {
      // When streaming finishes, ensure user's question is still visible at the top
      const lastMessage = messages[messages.length - 1];
      const isWebSearchResults = lastMessage?.type === 'web_search_results';
      
      if (lastMessage && lastMessage.role === 'assistant' && previousLastMessageRoleRef.current === 'user' && !isWebSearchResults) {
        // New assistant response just finished (but NOT web_search_results) - scroll to user's question at the top
        requestAnimationFrame(() => {
          const userMessageElement = userMessageRefs.current.get(lastUserMessageIdRef.current!);
          const container = messagesContainerRef.current;
          if (userMessageElement && container) {
            // Use scrollIntoView with start alignment
            userMessageElement.scrollIntoView({ behavior: 'smooth', block: 'start', inline: 'nearest' });
            // Small delay to ensure scrollIntoView completes, then fine-tune
            setTimeout(() => {
              const containerRect = container.getBoundingClientRect();
              const elementRect = userMessageElement.getBoundingClientRect();
              const offset = elementRect.top - containerRect.top;
              if (offset > 0) {
                container.scrollTop -= offset;
              }
            }, 100);
          }
        });
      }
    }
  }, [streamingContent, isStreaming, messages]);

  const handleBack = () => {
    if (currentConversation?.trashed) {
      setViewMode('trashList');
    } else if (currentProject) {
      setViewMode('projectList');
    }
  };

  const handleTitleClick = () => {
    if (currentConversation && !currentConversation.trashed) {
      setEditTitleValue(currentConversation.title);
      setIsEditingTitle(true);
    }
  };

  const handleTitleSave = async () => {
    if (!currentConversation || currentConversation.trashed) return;
    
    const newTitle = editTitleValue.trim();
    if (newTitle && newTitle !== currentConversation.title) {
      try {
        await renameChat(currentConversation.id, newTitle);
      } catch (error) {
        console.error('Failed to rename chat:', error);
        alert('Failed to rename chat. Please try again.');
      }
    }
    setIsEditingTitle(false);
  };

  const handleTitleCancel = () => {
    setIsEditingTitle(false);
    setEditTitleValue('');
  };

  // Fullscreen functionality - use CSS-based fullscreen (like ChatComposer) instead of browser API
  // This avoids conflicts with browser fullscreen and is more reliable
  const toggleFullscreen = (e?: React.MouseEvent) => {
    // Prevent event propagation to avoid triggering browser fullscreen
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }

    // Simply toggle the CSS-based fullscreen state
    // This uses CSS classes to make the modal fullscreen, not the browser API
    setIsFullscreen(prev => !prev);
  };

  // No longer need to listen for browser fullscreen changes since we're using CSS-based fullscreen
  // The isFullscreen state is managed directly by toggleFullscreen

  const handleTitleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleTitleSave();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      handleTitleCancel();
    }
  };

  // Focus input when editing starts
  useEffect(() => {
    if (isEditingTitle && titleInputRef.current) {
      titleInputRef.current.focus();
      titleInputRef.current.select();
    }
  }, [isEditingTitle]);

  const handleCopyMessage = async (content: string, messageId: string, messageData?: any) => {
    try {
      let textContent = content;
      
      // If this is an article_card, format it nicely
      if (messageData && messageData.url) {
        const copyText = [
          messageData.title && `${messageData.title}\n${messageData.url}\n`,
          messageData.summary && `Summary:\n${messageData.summary}`,
          messageData.keyPoints && messageData.keyPoints.length > 0 && `\n\nKey Points:\n${messageData.keyPoints.map((p: string) => `• ${p}`).join('\n')}`,
          messageData.whyMatters && `\n\nWhy This Matters:\n${messageData.whyMatters}`,
        ].filter(Boolean).join('\n');
        textContent = copyText;
      } else {
        // Strip markdown for plain text copy
        textContent = content.replace(/[#*`_~\[\]()]/g, '').trim();
      }
      
      await navigator.clipboard.writeText(textContent);
      
      // Show feedback
      setCopiedMessageId(messageId);
      setTimeout(() => {
        setCopiedMessageId(null);
      }, 2000);
    } catch (error) {
      console.error('Failed to copy message:', error);
      // Fallback for older browsers
      let textContent = content;
      if (messageData && messageData.url) {
        const copyText = [
          messageData.title && `${messageData.title}\n${messageData.url}\n`,
          messageData.summary && `Summary:\n${messageData.summary}`,
          messageData.keyPoints && messageData.keyPoints.length > 0 && `\n\nKey Points:\n${messageData.keyPoints.map((p: string) => `• ${p}`).join('\n')}`,
          messageData.whyMatters && `\n\nWhy This Matters:\n${messageData.whyMatters}`,
        ].filter(Boolean).join('\n');
        textContent = copyText;
      } else {
        textContent = content.replace(/[#*`_~\[\]()]/g, '').trim();
      }
      const textArea = document.createElement('textarea');
      textArea.value = textContent;
      document.body.appendChild(textArea);
      textArea.select();
      document.execCommand('copy');
      document.body.removeChild(textArea);
      
      // Show feedback
      setCopiedMessageId(messageId);
      setTimeout(() => {
        setCopiedMessageId(null);
      }, 2000);
    }
  };

  const handleEditMessage = (messageId: string, currentContent: string) => {
    // Dispatch event to ChatComposer to populate input
    window.dispatchEvent(new CustomEvent('edit-message', { 
      detail: { messageId, content: currentContent } 
    }));
  };

  const handleDeleteMessage = (messageId: string) => {
    if (window.confirm('Delete this message and all messages after it?')) {
      deleteMessage(messageId);
    }
  };

  return (
    <div 
      className="flex-1 flex flex-col h-full transition-colors"
      style={{ 
        backgroundColor: theme === 'dark' ? 'var(--bg-mid)' : 'var(--bg-primary)'
      }}
    >
      {/* Breadcrumb/Header - only show in chat view mode, not in bullet workspace */}
      {viewMode === 'chat' && (
        <div className="px-6 py-4 border-b border-[var(--border-color)] flex items-center gap-4 transition-colors">
          <button
            onClick={handleBack}
            className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors flex items-center gap-2"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            <span>
              {currentConversation?.trashed 
                ? 'Back to Trash' 
                : `Back to ${currentProject?.name || 'Project'}`}
            </span>
          </button>
          {currentConversation?.trashed && (
            <span className="px-2 py-1 text-xs bg-[#ef4444] text-white rounded">In Trash</span>
          )}
          {currentConversation && !currentConversation.trashed && (
            <>
              {isEditingTitle ? (
                <input
                  ref={titleInputRef}
                  type="text"
                  value={editTitleValue}
                  onChange={(e) => setEditTitleValue(e.target.value)}
                  onBlur={handleTitleSave}
                  onKeyDown={handleTitleKeyDown}
                  className="text-lg font-semibold text-[var(--text-primary)] bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-[#19c37d] min-w-[200px] max-w-[400px] transition-colors"
                  onClick={(e) => e.stopPropagation()}
                />
              ) : (
                <h2 
                  className="text-lg font-semibold text-[var(--text-primary)] cursor-pointer hover:text-[var(--text-primary)] transition-colors"
                  onClick={handleTitleClick}
                  title="Click to edit chat name"
                >
                  {currentConversation.title}
                </h2>
              )}
            </>
          )}
        </div>
      )}

      {/* Main Content Area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Messages */}
        <div ref={messagesContainerRef} className={`flex-1 overflow-y-auto transition-all duration-300 ${isRagTrayOpen ? 'mr-80' : ''}`}>
          <div className="max-w-[1000px] mx-auto px-0 py-4 space-y-4">
      {messages.map((message: Message) => {
        const isCopied = copiedMessageId === message.id;
        
        return (
          <div
            key={message.id}
            id={message.uuid ? `message-${message.uuid}` : `message-${message.id}`}
            ref={(el) => {
              if (el && message.role === 'user') {
                userMessageRefs.current.set(message.id, el);
                // If this is the last user message, scroll to it immediately
                // BUT skip if the next message is web_search_results to avoid layout shifts
                if (message.id === lastUserMessageIdRef.current) {
                  // Check if the next message after this user message is web_search_results
                  const messageIndex = messages.findIndex(m => m.id === message.id);
                  const nextMessage = messageIndex >= 0 && messageIndex < messages.length - 1 
                    ? messages[messageIndex + 1] 
                    : null;
                  const isNextWebSearchResults = nextMessage?.type === 'web_search_results';
                  
                  // Only do aggressive scroll if next message is NOT web_search_results
                  if (!isNextWebSearchResults) {
                    const scrollToThis = () => {
                      const container = messagesContainerRef.current;
                      if (container && el) {
                        const containerRect = container.getBoundingClientRect();
                        const elementRect = el.getBoundingClientRect();
                        const scrollTop = container.scrollTop;
                        const elementTopRelativeToContainer = elementRect.top - containerRect.top + scrollTop;
                        container.scrollTop = elementTopRelativeToContainer;
                      }
                    };
                    // Try multiple times to ensure it works
                    requestAnimationFrame(() => {
                      scrollToThis();
                      requestAnimationFrame(() => {
                        scrollToThis();
                        setTimeout(() => scrollToThis(), 50);
                        setTimeout(() => scrollToThis(), 200);
                      });
                    });
                  }
                }
              } else if (message.role === 'user') {
                userMessageRefs.current.delete(message.id);
              }
            }}
            className="group relative mb-3"
          >
            {/* Assistant: Avatar floats outside left edge */}
            {message.role === 'assistant' && (
              <div className="absolute top-1 w-8 h-8 rounded-full bg-[var(--assistant-avatar-bg)] flex items-center justify-center transition-colors" style={{ left: 'calc(-2.5rem + 6px)' }}>
                <span className="text-sm font-bold" style={{ color: 'var(--assistant-avatar-text)' }}>C</span>
              </div>
            )}
            
            {/* User: Avatar floats outside right edge */}
            {message.role === 'user' && (
              <div className="absolute top-1 w-8 h-8 rounded-full bg-[var(--user-bubble-bg)] flex items-center justify-center transition-colors" style={{ right: 'calc(-2.5rem - 6px)' }}>
                <span className="text-sm font-bold" style={{ color: 'var(--user-bubble-text)' }}>U</span>
              </div>
            )}
            
            {/* Bubble content container */}
            <div className="flex flex-col w-full">
              <>
                {/* Display images outside the message bubble for user messages */}
                {message.role === 'user' && (() => {
                  const imagePatternOld = /\[Image: ([^\]]+)\]\n(data:image\/[^;]+;base64[^\n]*)\n\[File path: ([^\]]+)\]/g;
                  const imagePatternNew = /\[Image: ([^\]]+)\]\n\[File path: ([^\]]+)\]/g;
                  const imageMatchesOld = [...message.content.matchAll(imagePatternOld)];
                  const imageMatchesNew = [...message.content.matchAll(imagePatternNew)];
                  
                  if (imageMatchesOld.length > 0 || imageMatchesNew.length > 0) {
                    return (
                      <div className="mb-2 space-y-2 flex flex-col items-end">
                        {imageMatchesOld.map((match, idx) => {
                          const cleanPath = match[3].startsWith('uploads/') ? match[3].substring(8) : match[3];
                          const imageSrc = match[2] || `http://localhost:8000/uploads/${cleanPath}`;
                          return (
                            <div 
                              key={idx} 
                              className="inline-block rounded-lg overflow-hidden border border-white/20 cursor-pointer hover:border-[#19c37d] transition-colors max-w-[20%] bg-transparent"
                              onClick={() => setPreviewFile({name: match[1], data: imageSrc, type: 'image', mimeType: ''})}
                              title="Click to view full size"
                            >
                              <img 
                                src={imageSrc}
                                alt={match[1]}
                                className="w-full h-auto object-contain"
                                loading="lazy"
                              />
                              <div className="px-2 py-1 bg-black/30 text-xs truncate text-white">
                                {match[1]}
                              </div>
                            </div>
                          );
                        })}
                        {imageMatchesNew.map((match, idx) => {
                          const cleanPath = match[2].startsWith('uploads/') ? match[2].substring(8) : match[2];
                          const imageSrc = `http://localhost:8000/uploads/${cleanPath}`;
                          return (
                            <div 
                              key={`new-${idx}`} 
                              className="inline-block rounded-lg overflow-hidden border border-white/20 cursor-pointer hover:border-[#19c37d] transition-colors max-w-[20%] bg-transparent"
                              onClick={() => setPreviewFile({name: match[1], data: imageSrc, type: 'image', mimeType: ''})}
                              title="Click to view full size"
                            >
                              <img 
                                src={imageSrc}
                                alt={match[1]}
                                className="w-full h-auto object-contain"
                                loading="lazy"
                              />
                              <div className="px-2 py-1 bg-black/30 text-xs truncate text-white">
                                {match[1]}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    );
                  }
                  return null;
                })()}
                {(() => {
                  // Parse content first to determine if we should show the bubble
                  const imagePatternOld = /\[Image: ([^\]]+)\]\n(data:image\/[^;]+;base64[^\n]*)\n\[File path: ([^\]]+)\]/g;
                  const imagePatternNew = /\[Image: ([^\]]+)\]\n\[File path: ([^\]]+)\]/g;
                  const docPatternOld = /\[File: ([^\]]+)\]\n\[File path: ([^\]]+)\]\n\[MIME type: ([^\]]+)\]/g;
                  const docPatternNew = /\[File: ([^\]]+)\]\n\n([\s\S]*?)(?=\n\n\[File: |\n\n\[Image: |$|$)/g;
                  
                  let content = message.content;
                  const files: Array<{name: string, type: 'image' | 'doc', data?: string, path: string, mimeType?: string}> = [];
                  
                  // Extract images
                  const imageMatchesOld = [...message.content.matchAll(imagePatternOld)];
                  imageMatchesOld.forEach(match => {
                    if (!files.some(f => f.name === match[1] && f.type === 'image')) {
                      files.push({
                        name: match[1],
                        type: 'image',
                        data: match[2],
                        path: match[3]
                      });
                      content = content.replace(match[0], '');
                    }
                  });
                  
                  const imageMatchesNew = [...message.content.matchAll(imagePatternNew)];
                  imageMatchesNew.forEach(match => {
                    if (!files.some(f => f.name === match[1] && f.type === 'image')) {
                      files.push({
                        name: match[1],
                        type: 'image',
                        data: undefined,
                        path: match[2]
                      });
                      content = content.replace(match[0], '');
                    }
                  });
                  
                  // Extract documents
                  const docPatternNewWithPath = /\[File: ([^\]]+)\]\n\[File path: ([^\]]+)\]\n\[MIME type: ([^\]]+)\](?:\n\n([\s\S]*?))?(?=\n\n\[File: |\n\n\[Image: |$|$)/g;
                  const docMatchesNewWithPath = [...message.content.matchAll(docPatternNewWithPath)];
                  docMatchesNewWithPath.forEach(match => {
                    files.push({
                      name: match[1],
                      type: 'doc',
                      path: match[2],
                      mimeType: match[3]
                    });
                    const escapedName = match[1].replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                    const fileSectionPattern = new RegExp(
                      `\\[File: ${escapedName}\\]\\n\\[File path: [^\\]]+\\]\\n\\[MIME type: [^\\]]+\\](?:\\n\\n[\\s\\S]*?)?(?=\\n\\n\\[File: |\\n\\n\\[Image: |$)`,
                      'g'
                    );
                    content = content.replace(fileSectionPattern, '');
                  });
                  
                  const docMatchesNew = [...message.content.matchAll(docPatternNew)];
                  docMatchesNew.forEach(match => {
                    if (!files.some(f => f.name === match[1])) {
                      const fileName = match[1];
                      let mimeType = '';
                      if (fileName.toLowerCase().endsWith('.pdf')) {
                        mimeType = 'application/pdf';
                      } else if (fileName.toLowerCase().endsWith('.pptx') || fileName.toLowerCase().endsWith('.ppt')) {
                        mimeType = 'application/vnd.openxmlformats-officedocument.presentationml.presentation';
                      } else if (fileName.toLowerCase().endsWith('.docx') || fileName.toLowerCase().endsWith('.doc')) {
                        mimeType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
                      }
                      
                      files.push({
                        name: match[1],
                        type: 'doc',
                        path: '',
                        mimeType: mimeType
                      });
                      const escapedName = match[1].replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                      const fileSectionPattern = new RegExp(
                        `\\[File: ${escapedName}\\]\\n\\n[\\s\\S]*?(?=\\n\\n\\[File: |\\n\\n\\[Image: |$)`,
                        'g'
                      );
                      content = content.replace(fileSectionPattern, '');
                    }
                  });
                  
                  const docMatchesOld = [...message.content.matchAll(docPatternOld)];
                  docMatchesOld.forEach(match => {
                    if (!files.some(f => f.name === match[1])) {
                      files.push({
                        name: match[1],
                        type: 'doc',
                        path: match[2],
                        mimeType: match[3]
                      });
                      const fileSectionPattern = new RegExp(
                        `\\[File: ${match[1].replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\]\\n\\[File path: [^\\]]+\\]\\n\\[MIME type: [^\\]]+\\](\\n\\n--- File Content ---[\\s\\S]*?--- End File Content ---)?`,
                        'g'
                      );
                      content = content.replace(fileSectionPattern, '');
                    }
                  });
                  
                  content = content.replace(/\[File uploaded: [^\]]+\]/g, '');
                  content = content.replace(/\[File path: [^\]]+\]/g, '');
                  content = content.trim();
                  
                  const filesToShow = message.role === 'user' ? files.filter(f => f.type !== 'image') : files;
                  // For web_search_results, always show (has structured data)
                  const hasContent = content.trim().length > 0 || filesToShow.length > 0 || message.type === 'web_search_results' || message.type === 'article_card' || message.type === 'document_card' || message.type === 'rag_response';
                  
                  if (!hasContent) {
                    return null;
                  }
                  
                  return (
                    <div
                      className={`rounded-lg px-4 py-3 box-border transition-colors ${
                        message.role === 'user'
                          ? 'bg-[var(--user-bubble-bg)] max-w-[70%] ml-auto mr-[-6px] break-words'
                          : 'bg-[var(--assistant-bubble-bg)] text-[var(--text-primary)] w-full ml-[6px]'
                      }`}
                      style={message.role === 'user' ? { color: 'var(--user-bubble-text)', wordBreak: 'break-word', overflowWrap: 'anywhere' } : undefined}
                    >
                      {/* Display files (documents, or all files for assistant) inside the message bubble */}
                      {filesToShow.length > 0 && (
                        <div className={`mb-3 space-y-2 ${message.role === 'user' ? '' : ''}`}>
                          {filesToShow.map((file, idx) => (
                            file.type === 'image' ? (
                              <div 
                                key={idx} 
                                className="inline-block rounded-lg overflow-hidden border border-white/20 cursor-pointer hover:border-[#19c37d] transition-colors max-w-[25%] bg-transparent"
                                onClick={() => {
                                  // Use file path to load image if base64 not available
                                  let imageSrc = file.data;
                                  if (!imageSrc && file.path) {
                                    const cleanPath = file.path.startsWith('uploads/') ? file.path.substring(8) : file.path;
                                    imageSrc = `http://localhost:8000/uploads/${cleanPath}`;
                                  }
                                  if (imageSrc) {
                                    setPreviewFile({name: file.name, data: imageSrc, type: 'image', mimeType: file.mimeType || ''});
                                  }
                                }}
                                title="Click to view full size"
                              >
                                {file.data ? (
                                  <img 
                                    src={file.data} 
                                    alt={file.name}
                                    className="w-full h-auto object-contain"
                                    loading="lazy"
                                  />
                                ) : file.path ? (
                                  <img 
                                    src={`http://localhost:8000/uploads/${file.path.startsWith('uploads/') ? file.path.substring(8) : file.path}`}
                                    alt={file.name}
                                    className="w-full h-auto object-contain"
                                    loading="lazy"
                                  />
                                ) : null}
                                <div className="px-2 py-1 bg-black/30 text-xs truncate text-white">
                                  {file.name}
                                </div>
                              </div>
                            ) : (
                              <div 
                                key={idx} 
                                className="flex items-center gap-3 p-3 bg-black/20 rounded border border-white/20 cursor-pointer hover:border-[#19c37d] transition-colors"
                                onClick={() => {
                                  // Get path from file object
                                  const filePath = file.path || '';
                                  const fileName = file.name.toLowerCase();
                                  
                                  // The path from server is relative to project root (includes 'uploads/')
                                  // Server returns: uploads/project_id/conversation_id/filename
                                  // Endpoint expects: /uploads/project_id/conversation_id/filename
                                  // But endpoint adds 'uploads/' itself, so we need to strip it
                                  let previewPath = '';
                                  if (filePath) {
                                    // Strip 'uploads/' prefix if present
                                    const cleanPath = filePath.startsWith('uploads/') ? filePath.substring(8) : filePath;
                                    previewPath = `http://localhost:8000/uploads/${cleanPath}`;
                                  }
                                  
                                  if (file.mimeType === 'application/pdf' || fileName.endsWith('.pdf')) {
                                    setPreviewFile({name: file.name, data: previewPath, type: 'pdf', mimeType: file.mimeType || 'application/pdf'});
                                  } else if (fileName.endsWith('.pptx') || fileName.endsWith('.ppt')) {
                                    setPreviewFile({name: file.name, data: previewPath, type: 'pptx', mimeType: file.mimeType || 'application/vnd.openxmlformats-officedocument.presentationml.presentation'});
                                  } else if (fileName.endsWith('.xlsx') || fileName.endsWith('.xls')) {
                                    // Convert path for Excel preview API
                                    // previewPath is already http://localhost:8000/uploads/... so strip that prefix
                                    let cleanPath = previewPath.replace('http://localhost:8000/uploads/', '');
                                    // If it still has uploads/ prefix, strip it
                                    if (cleanPath.startsWith('uploads/')) {
                                      cleanPath = cleanPath.substring(8);
                                    }
                                    setPreviewFile({name: file.name, data: `http://localhost:8000/api/xlsx-preview/${cleanPath}`, type: 'xlsx', mimeType: file.mimeType || 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
                                  } else if (fileName.endsWith('.docx') || fileName.endsWith('.doc')) {
                                    // Convert path for Word preview API
                                    let cleanPath = previewPath.replace('http://localhost:8000/uploads/', '');
                                    if (cleanPath.startsWith('uploads/')) {
                                      cleanPath = cleanPath.substring(8);
                                    }
                                    setPreviewFile({name: file.name, data: `http://localhost:8000/api/docx-preview/${cleanPath}`, type: 'docx', mimeType: file.mimeType || 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'});
                                  } else if (fileName.endsWith('.mp4') || fileName.endsWith('.mov') || fileName.endsWith('.avi') || fileName.endsWith('.webm') || fileName.endsWith('.mkv') || file.mimeType?.startsWith('video/')) {
                                    // Video files - use HTML5 video player
                                    setPreviewFile({name: file.name, data: previewPath, type: 'video', mimeType: file.mimeType || 'video/mp4'});
                                  } else {
                                    setPreviewFile({name: file.name, data: previewPath, type: 'other', mimeType: file.mimeType || ''});
                                  }
                                }}
                              >
                                <div className="flex-shrink-0">
                                  {file.mimeType === 'application/pdf' ? (
                                    <svg className="w-10 h-10 text-red-300" fill="currentColor" viewBox="0 0 24 24">
                                      <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" />
                                    </svg>
                                  ) : (
                                    <svg className="w-10 h-10 text-white/70" fill="currentColor" viewBox="0 0 24 24">
                                      <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" />
                                    </svg>
                                  )}
                                </div>
                                <div className="flex-1 min-w-0">
                                  <p className="text-sm font-medium truncate">{file.name}</p>
                                  <p className="text-xs opacity-75 mt-1">
                                    {(() => {
                                      // Get file extension from filename
                                      const ext = file.name.split('.').pop()?.toUpperCase() || '';
                                      // Map common extensions to clean names (fallback to extension itself)
                                      const extMap: Record<string, string> = {
                                        'PDF': 'PDF',
                                        'DOC': 'DOC',
                                        'DOCX': 'DOCX',
                                        'PPT': 'PPT',
                                        'PPTX': 'PPTX',
                                        'XLS': 'XLS',
                                        'XLSX': 'XLSX',
                                        'TXT': 'TXT',
                                        'PNG': 'PNG',
                                        'JPG': 'JPG',
                                        'JPEG': 'JPEG',
                                        'GIF': 'GIF',
                                        'SVG': 'SVG',
                                        'WEBP': 'WEBP',
                                        'ZIP': 'ZIP',
                                        'RAR': 'RAR',
                                        '7Z': '7Z',
                                        'CSV': 'CSV',
                                        'JSON': 'JSON',
                                        'XML': 'XML',
                                        'HTML': 'HTML',
                                        'MP4': 'MP4',
                                        'MP3': 'MP3',
                                        'MOV': 'MOV',
                                        'AVI': 'AVI'
                                      };
                                      // If extension is in map, use it; otherwise use the extension itself; fallback to 'FILE'
                                      return extMap[ext] || ext || 'FILE';
                                    })()}
                                  </p>
                                </div>
                              </div>
                            )
                          ))}
                        </div>
                      )}
                      
                      {/* Display web_search_results if message type is web_search_results */}
                      {message.type === 'web_search_results' && message.data && (
                        <AssistantCard>
                          {/* Brave Summary section - show first if present */}
                          {message.data.summary && (
                            <div className="mb-4">
                              <div className="font-semibold text-sm mb-2 text-[var(--text-secondary)]">
                                Summary
                              </div>
                              {typeof message.data.summary === 'string' ? (
                                <div className="text-sm text-[var(--text-primary)] leading-relaxed whitespace-pre-wrap">
                                  {message.data.summary}
                                </div>
                              ) : (
                                (() => {
                                  const summaryObj = message.data.summary as { text: string; citations?: Array<{ title: string; url: string; domain: string }> } | null;
                                  if (summaryObj && summaryObj.text) {
                                    return (
                                      <div>
                                        <div className="text-sm text-[var(--text-primary)] leading-relaxed whitespace-pre-wrap">
                                          {summaryObj.text}
                                        </div>
                                        {summaryObj.citations && summaryObj.citations.length > 0 && (
                                          <div className="mt-3 pt-3 border-t border-[var(--border-color)]/30">
                                            <div className="text-xs text-[var(--text-secondary)] mb-2">Sources:</div>
                                            <div className="space-y-1">
                                              {summaryObj.citations.map((citation: { title: string; url: string; domain: string }, idx: number) => (
                                                <a
                                                  key={idx}
                                                  href={citation.url}
                                                  target="_blank"
                                                  rel="noopener noreferrer"
                                                  className="block text-xs text-blue-400 hover:text-blue-300 hover:underline"
                                                >
                                                  {citation.domain} - {citation.title}
                                                </a>
                                              ))}
                                            </div>
                                          </div>
                                        )}
                                      </div>
                                    );
                                  }
                                  return null;
                                })()
                              )}
                            </div>
                          )}
                          
                          <div className="font-semibold text-lg mb-3 text-center">
                            Top Results
                          </div>
                          <div className="space-y-3">
                            {message.data.results?.map((result: { title: string; url: string; snippet: string; published_at?: string; age?: string; page_age?: string }, index: number) => {
                              const articleState = articleStates[result.url] || 'idle';
                              // Brave Search button only shows spinner for its own article state
                              const isSummarizing = articleState === 'summarizing';
                              const isSummarized = articleState === 'summarized';
                              
                              // Extract domain from URL
                              const getDomain = (url: string) => {
                                try {
                                  const u = new URL(url);
                                  return u.hostname.replace(/^www\./, "");
                                } catch {
                                  return url;
                                }
                              };
                              
                              const getFaviconUrl = (url: string) => {
                                try {
                                  const u = new URL(url);
                                  return `${u.protocol}//${u.hostname}/favicon.ico`;
                                } catch {
                                  return undefined;
                                }
                              };
                              
                              const domain = getDomain(result.url);
                              const faviconUrl = getFaviconUrl(result.url);
                              
                              // Format date label from available date fields
                              const formatDateLabel = (): string | null => {
                                // Prefer published_at (ISO date string)
                                if (result.published_at) {
                                  try {
                                    const date = new Date(result.published_at);
                                    if (!isNaN(date.getTime())) {
                                      return date.toLocaleDateString('en-US', { 
                                        year: 'numeric', 
                                        month: 'short', 
                                        day: 'numeric' 
                                      });
                                    }
                                  } catch {
                                    // If date parsing fails, try to use as-is
                                    return result.published_at;
                                  }
                                }
                                
                                // Try page_age (ISO date string like "2024-08-16T17:41:12")
                                if (result.page_age) {
                                  try {
                                    const date = new Date(result.page_age);
                                    if (!isNaN(date.getTime())) {
                                      return date.toLocaleDateString('en-US', { 
                                        year: 'numeric', 
                                        month: 'short', 
                                        day: 'numeric' 
                                      });
                                    }
                                  } catch {
                                    // If date parsing fails, try to use as-is
                                    return result.page_age;
                                  }
                                }
                                
                                // Fall back to age (relative time like "2h ago", "3d ago", "August 16, 2024")
                                if (result.age) {
                                  return result.age;
                                }
                                
                                return null;
                              };
                              
                              const dateLabel = formatDateLabel();
                              
                              return (
                                <div key={index} className={index > 0 ? "pt-3 border-t border-[var(--border-color)]/30" : ""}>
                                  {/* Domain + Favicon + Date */}
                                  <div className="flex items-center gap-2 mb-1">
                                    {faviconUrl && (
                                      <img
                                        src={faviconUrl}
                                        alt={domain}
                                        className="h-4 w-4 rounded-sm"
                                        onError={(e) => {
                                          (e.target as HTMLImageElement).style.display = 'none';
                                        }}
                                      />
                                    )}
                                    <span className="text-xs text-[var(--text-secondary)]">
                                      {domain}
                                      {dateLabel && (
                                        <>
                                          <span className="mx-1">·</span>
                                          <span>{dateLabel}</span>
                                        </>
                                      )}
                                    </span>
                                  </div>
                                  
                                  {/* Title + Summarize Button */}
                                  <div className="flex items-center gap-2 mb-1">
                                    <a
                                      href={result.url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="text-blue-400 hover:text-blue-300 font-semibold flex-1"
                                    >
                                      {result.title}
                                    </a>
                                    <button
                                      onClick={async () => {
                                        if (!currentProject || !currentConversation || isSummarizing || isSummarized) return;
                                        
                                        // Auto-name chat based on first message if it's still "New Chat"
                                        // Check BEFORE adding the user message, since addMessage will increase the length
                                        const isFirstMessage = currentConversation.title === 'New Chat' && 
                                                              currentConversation.messages.length === 0;
                                        
                                        setArticleStates(prev => ({ ...prev, [result.url]: 'summarizing' }));
                                        setSummarizingArticle(true);
                                        try {
                                          const { setLoading: setStoreLoading, addMessage: addStoreMessage, renameChat: renameChatStore } = useChatStore.getState();
                                          setStoreLoading(true);
                                          
                                          // Add user message
                                          addStoreMessage({
                                            role: 'user',
                                            content: `Summarize: ${result.url}`,
                                          });
                                          
                                          // Auto-rename chat if this is the first message
                                          if (isFirstMessage) {
                                            // Generate title from URL (extract domain or use URL)
                                            let autoTitle = result.url.trim();
                                            try {
                                              const urlObj = new URL(result.url);
                                              autoTitle = urlObj.hostname.replace('www.', '');
                                              // If hostname is too long, use a shortened version
                                              if (autoTitle.length > 50) {
                                                autoTitle = autoTitle.substring(0, 47) + '...';
                                              }
                                            } catch {
                                              // If URL parsing fails, use the URL itself (truncated)
                                              autoTitle = result.url.length > 50 ? result.url.substring(0, 47) + '...' : result.url;
                                            }
                                            
                                            // Only auto-rename if we got a meaningful title
                                            if (autoTitle.length > 0) {
                                              try {
                                                console.log('[Auto-label] Renaming chat from "New Chat" to:', autoTitle);
                                                await renameChatStore(currentConversation.id, autoTitle);
                                                console.log('[Auto-label] Successfully renamed chat');
                                              } catch (error) {
                                                console.error('Failed to auto-name chat:', error);
                                                // Don't block sending the message if auto-naming fails
                                              }
                                            }
                                          }
                                          
                                          const response = await axios.post('http://localhost:8000/api/article/summary', {
                                            url: result.url,
                                            conversation_id: currentConversation.id,
                                            project_id: currentProject.id,
                                          });
                                          if (response.data.message_type === 'article_card' && response.data.message_data) {
                                            addStoreMessage({
                                              role: 'assistant',
                                              content: '',
                                              type: 'article_card',
                                              data: response.data.message_data,
                                              model: response.data.model || 'Trafilatura + GPT-5',
                                              provider: response.data.provider || 'trafilatura-gpt5',
                                            });
                                            setArticleStates(prev => ({ ...prev, [result.url]: 'summarized' }));
                                          }
                                          setStoreLoading(false);
                                        } catch (error: any) {
                                          console.error('Error summarizing article:', error);
                                          const { addMessage: addStoreMessage, setLoading: setStoreLoading } = useChatStore.getState();
                                          addStoreMessage({
                                            role: 'assistant',
                                            content: `Error: ${error.response?.data?.detail || error.message || 'Could not summarize URL.'}`,
                                          });
                                          setStoreLoading(false);
                                          setArticleStates(prev => ({ ...prev, [result.url]: 'idle' }));
                                        } finally {
                                          setSummarizingArticle(false);
                                        }
                                      }}
                                      disabled={isSummarizing || isSummarized}
                                      className={`p-1.5 rounded transition-colors flex-shrink-0 ${
                                        isSummarized 
                                          ? 'text-green-400 cursor-default' 
                                          : isSummarizing
                                          ? 'text-blue-400 cursor-wait'
                                          : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--border-color)]'
                                      }`}
                                      title={isSummarized ? "Summary created" : isSummarizing ? "Summarizing..." : "Summarize URL"}
                                    >
                                      {isSummarizing ? (
                                        <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                        </svg>
                                      ) : isSummarized ? (
                                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                        </svg>
                                      ) : (
                                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                        </svg>
                                      )}
                                    </button>
                                  </div>
                                  
                                  {/* Snippet */}
                                  <div className="text-sm text-[var(--text-secondary)] line-clamp-2">
                                    {result.snippet}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </AssistantCard>
                      )}
                      
                      {/* Display document_card if message type is document_card */}
                      {message.type === 'document_card' && message.data && (
                        <DocumentCard
                          fileName={message.data.fileName || 'Document'}
                          fileType={message.data.fileType}
                          filePath={message.data.filePath}
                          summary={typeof message.data.summary === 'string' ? message.data.summary : (message.data.summary?.text || '')}
                          keyPoints={message.data.keyPoints || []}
                          whyMatters={message.data.whyMatters}
                          estimatedReadTimeMinutes={message.data.estimatedReadTimeMinutes}
                          wordCount={message.data.wordCount}
                          pageCount={message.data.pageCount}
                        />
                      )}
                      
                      {/* Display article_card if message type is article_card */}
                      {message.type === 'article_card' && message.data && (
                        <ArticleCard
                          url={message.data.url || ''}
                          title={message.data.title || 'Untitled'}
                          siteName={message.data.siteName}
                          published={message.data.published}
                          summary={typeof message.data.summary === 'string' ? message.data.summary : (message.data.summary?.text || '')}
                          keyPoints={message.data.keyPoints || []}
                          whyMatters={message.data.whyMatters}
                        />
                      )}
                      
                      {/* Display rag_response if message type is rag_response */}
                      {message.type === 'rag_response' && (
                        <RagResponseCard
                          content={message.data?.content || message.content || ''}
                          ragFiles={ragFilesWithIndex}
                          onOpenRagFile={handleOpenRagFile}
                        />
                      )}
                      
                      {/* Display text content if any (and not structured message types) */}
                      {content && message.type !== 'web_search_results' && message.type !== 'article_card' && message.type !== 'document_card' && message.type !== 'rag_response' && (
                        message.role === 'assistant' ? (
                          <OptionsRenderer content={content} bulletMode={bulletMode} sources={message.sources} />
                        ) : (
                          <p className="whitespace-pre-wrap break-words" style={{ color: 'var(--user-bubble-text)', overflowWrap: 'anywhere', wordBreak: 'break-word' }}>{content}</p>
                        )
                      )}
                      
                      {/* Timestamp and Model tag for all assistant messages */}
                      {message.role === 'assistant' && 
                       message.type !== 'document_card' && (
                        <div className="flex justify-between items-center mt-2 text-xs text-[var(--text-secondary)] leading-tight">
                          {/* Timestamp on the left */}
                          <div 
                            className="text-[var(--text-secondary)]"
                            title={message.timestamp.toISOString()}
                          >
                            {formatResponseTimestamp(message.timestamp)}
                          </div>
                          {/* Model label on the right */}
                          <div>
                            {message.model_label ? (
                              // Use model_label from backend if available (most accurate)
                              // Backend now returns format without "Model: " prefix
                              <div>{message.model_label.startsWith('Model: ') ? message.model_label : `Model: ${message.model_label}`}</div>
                            ) : message.type === 'web_search_results' ? (
                              <div>Model: Brave</div>
                            ) : (() => {
                              const ragUsed = hasRagSources(message);
                              const baseModel = message.model ? formatModelName(message.model) : null;
                              
                              if (ragUsed && baseModel) {
                                return <div>Model: RAG + {baseModel}</div>;
                              } else if (ragUsed) {
                                return <div>Model: RAG</div>;
                              } else if (baseModel) {
                                return <div>Model: {baseModel}</div>;
                              }
                              return null;
                            })()}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })()}
                {/* Action buttons - positioned below message */}
                <div className={`flex gap-2 mt-1 ${
                  message.role === 'user' ? 'justify-end' : 'justify-start'
                } opacity-0 group-hover:opacity-100 transition-opacity`}>
                {message.role === 'user' ? (
                  <>
                    <button
                      onClick={() => handleCopyMessage(message.content, message.id)}
                      className="p-1.5 hover:bg-[var(--border-color)]/50 rounded transition-colors text-[var(--text-secondary)] hover:text-[var(--text-primary)] flex items-center gap-1"
                      title="Copy message"
                    >
                      {isCopied ? (
                        <>
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                          </svg>
                          <span className="text-xs">Copied!</span>
                        </>
                      ) : (
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                        </svg>
                      )}
                    </button>
                    <button
                      onClick={() => handleEditMessage(message.id, message.content)}
                      className="p-1.5 hover:bg-[var(--border-color)]/50 rounded transition-colors text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                      title="Edit message"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                      </svg>
                    </button>
                    <button
                      onClick={() => handleDeleteMessage(message.id)}
                      className="p-1.5 hover:bg-[var(--border-color)]/50 rounded transition-colors text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                      title="Delete message"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => handleCopyMessage(message.content, message.id, message.data)}
                    className="p-1.5 hover:bg-[#565869]/50 rounded transition-colors text-[#8e8ea0] hover:text-white flex items-center gap-1"
                    title="Copy message"
                  >
                    {isCopied ? (
                      <>
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                        </svg>
                        <span className="text-xs">Copied!</span>
                      </>
                    ) : (
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                      </svg>
                    )}
                  </button>
                )}
                </div>
              </>
            </div>
          </div>
        );
      })}
      
      {/* Streaming content */}
      {isStreaming && (
        <div className="group relative mb-3">
          {/* Assistant: Avatar floats outside left edge */}
          <div className="absolute top-1 w-8 h-8 rounded-full bg-[var(--assistant-avatar-bg)] flex items-center justify-center transition-colors" style={{ left: 'calc(-2.5rem + 6px)' }}>
            <span className="text-sm font-bold" style={{ color: 'var(--assistant-avatar-text)' }}>C</span>
          </div>
          {/* Always show thinking indicator (three dots) during streaming - don't show partial content */}
          {/* This prevents cards from appearing/disappearing during streaming */}
          <div className="inline-flex flex-col">
            <div className="rounded-lg px-4 py-3 box-border bg-[var(--assistant-bubble-bg)] text-[var(--text-primary)] ml-[6px] transition-colors">
              <div className="flex items-center gap-2 text-[var(--text-secondary)]">
                <div className="flex gap-1">
                  <div className="w-2 h-2 rounded-full bg-[var(--text-secondary)] animate-pulse" style={{ animationDelay: '0ms' }}></div>
                  <div className="w-2 h-2 rounded-full bg-[var(--text-secondary)] animate-pulse" style={{ animationDelay: '150ms' }}></div>
                  <div className="w-2 h-2 rounded-full bg-[var(--text-secondary)] animate-pulse" style={{ animationDelay: '300ms' }}></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
          {/* Invisible element at the bottom to scroll to */}
      <div ref={messagesEndRef} />
          </div>
        </div>
        
      </div>
      
      {/* File Preview Modal */}
      {previewFile && (
        <div 
          className="fixed inset-0 bg-black/80 z-[9999] flex items-center justify-center p-4"
          onClick={() => {
            setPreviewFile(null);
            // Reset fullscreen state when closing
            setIsFullscreen(false);
          }}
        >
          <div 
            ref={previewModalRef}
            className={`bg-[var(--bg-primary)] rounded-lg max-w-4xl max-h-[90vh] w-full overflow-hidden flex flex-col transition-colors ${isFullscreen ? '!max-w-none !max-h-none !rounded-none !h-screen !w-screen' : ''}`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-4 border-b border-[var(--border-color)] transition-colors">
              <h3 className="text-lg font-semibold text-white truncate">{previewFile.name}</h3>
              <div className="flex items-center gap-2">
                <button
                  onClick={(e) => toggleFullscreen(e)}
                  className="p-2 hover:bg-[var(--border-color)] rounded transition-colors text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                  title={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
                  type="button"
                >
                  {isFullscreen ? (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12M4 8h4m-4 4h4m-4 4h4m8-8v4m0 4v4m0-8h4m-4 0h4" />
                    </svg>
                  ) : (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
                    </svg>
                  )}
                </button>
                <button
                  onClick={() => setPreviewFile(null)}
                  className="p-2 hover:bg-[var(--border-color)] rounded transition-colors text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                  title="Close preview"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>
            <div className={`flex-1 overflow-auto p-4 ${isFullscreen ? '!h-[calc(100vh-80px)]' : ''}`}>
              {previewFile.type === 'image' ? (
                <img 
                  src={previewFile.data} 
                  alt={previewFile.name}
                  className={`max-w-full mx-auto object-contain ${isFullscreen ? 'max-h-[calc(100vh-80px)]' : 'max-h-full'}`}
                />
              ) : previewFile.type === 'pdf' ? (
                <iframe
                  src={previewFile.data}
                  className={`w-full border border-[var(--border-color)] rounded transition-colors ${isFullscreen ? 'h-[calc(100vh-80px)]' : 'h-[80vh]'}`}
                  title={previewFile.name}
                />
              ) : previewFile.type === 'pptx' ? (
                <iframe
                  src={previewFile.data}
                  className={`w-full border border-[var(--border-color)] rounded transition-colors ${isFullscreen ? 'h-[calc(100vh-80px)]' : 'h-[80vh]'}`}
                  title={previewFile.name}
                />
              ) : previewFile.type === 'xlsx' ? (
                <iframe
                  src={previewFile.data}
                  className={`w-full border border-[var(--border-color)] rounded transition-colors ${isFullscreen ? 'h-[calc(100vh-80px)]' : 'h-[80vh]'}`}
                  title={previewFile.name}
                />
              ) : previewFile.type === 'docx' ? (
                <iframe
                  src={previewFile.data}
                  className={`w-full border border-[var(--border-color)] rounded transition-colors ${isFullscreen ? 'h-[calc(100vh-80px)]' : 'h-[80vh]'}`}
                  title={previewFile.name}
                />
              ) : previewFile.type === 'video' ? (
                <video
                  src={previewFile.data}
                  controls
                  className={`w-full mx-auto object-contain ${isFullscreen ? 'max-h-[calc(100vh-80px)]' : 'max-h-[80vh]'}`}
                  style={isFullscreen ? { maxHeight: 'calc(100vh - 80px)' } : { maxHeight: '80vh' }}
                >
                  Your browser does not support the video tag.
                </video>
              ) : (
                <div className="text-center text-[var(--text-secondary)] py-8">
                  <p>Preview not available for this file type.</p>
                  <p className="text-sm mt-2">File: {previewFile.name}</p>
                  {previewFile.data && (
                    <a 
                      href={previewFile.data} 
                      target="_blank" 
                      rel="noopener noreferrer"
                      className="mt-4 inline-block px-4 py-2 bg-[var(--user-bubble-bg)] text-[var(--user-bubble-text)] rounded hover:opacity-90 transition-colors"
                    >
                      Download File
                    </a>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ChatMessages;


