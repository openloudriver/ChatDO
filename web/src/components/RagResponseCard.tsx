import React, { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import SectionHeading from "./shared/SectionHeading";
import { AssistantCard } from "./shared/AssistantCard";
import { InlineSourceCitations } from "./InlineSourceCitations";
import type { RagFile } from "../types/rag";
import type { Source } from "../types/sources";

export interface RagResponseCardProps {
  content: string;
  ragFiles: RagFile[]; // Indexed RAG files (single source of truth)
  onOpenRagFile: (file: RagFile) => void;
}

// Convert RagFile to Source format for inline citations
const ragFileToSource = (ragFile: RagFile, onOpenFile: (file: RagFile) => void): Source => {
  return {
    id: ragFile.id,
    title: ragFile.filename,
    fileName: ragFile.filename,
    description: ragFile.mime_type ? `File type: ${ragFile.mime_type}` : undefined,
    rank: ragFile.index, // Use index as rank (1-based)
    sourceType: 'rag',
    citationPrefix: 'R', // RAG uses R prefix: [R1], [R2], [R3]
    meta: {
      ragFile: ragFile,
      onOpenFile: onOpenFile, // Store the handler in meta for later use
    },
  };
};

// Helper function to strip citations from text for empty bullet detection
function stripCitations(text: string): string {
  // Remove inline citation blocks like [1], [1, 2], [1, 2, 3]
  return text.replace(/\[\s*\d+(?:\s*,\s*\d+)*\s*\]/g, '').trim();
}

// Sanitize RAG content: remove empty bullets, normalize formatting
function sanitizeRagContent(content: string): string {
  const lines = content.split('\n');
  const sanitized: string[] = [];
  let lastWasBlank = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // Skip completely empty lines (but allow one blank line between sections)
    if (!trimmed) {
      if (!lastWasBlank && sanitized.length > 0) {
        sanitized.push('');
        lastWasBlank = true;
      }
      continue;
    }
    lastWasBlank = false;

    // Don't remove headers (ALL CAPS or ending with ":")
    const isHeader = /^[A-Z\s]+$/.test(trimmed) || trimmed.endsWith(':');
    
    // Don't remove lines with citations (e.g., "[1]", "[1, 3]")
    const hasCitations = /\[\s*\d+(?:\s*,\s*\d+)*\s*\]/.test(trimmed);

    // Remove orphan bullet lines (just "-", "–", "- ", "•", etc.)
    if (trimmed === '-' || trimmed === '–' || trimmed === '- ' || trimmed === '•' || /^-\s*$/.test(trimmed)) {
      continue;
    }

    // Remove list items that are empty after stripping citations (unless it's a header or has citations)
    if (!isHeader && !hasCitations) {
      const cleaned = stripCitations(trimmed);
      if (!cleaned) {
        continue;
      }
    }

    // Keep valid bullets as "- " (ReactMarkdown needs this format)
    // The CSS will display "• " instead of "-" via before:content
    // Only normalize if it's a malformed bullet (no space after dash)
    if (trimmed.startsWith('-') && trimmed.length > 1 && trimmed[1] !== ' ') {
      // Handle "-" followed immediately by text (no space) - normalize to "- "
      sanitized.push('- ' + trimmed.substring(1));
    } else {
      sanitized.push(line);
    }
  }

  return sanitized.join('\n');
}


export const RagResponseCard: React.FC<RagResponseCardProps> = ({
  content,
  ragFiles,
  onOpenRagFile,
}) => {
  // Convert ragFiles to Source[] format for inline citations
  const sources = useMemo(() => {
    return ragFiles
      .filter(file => file.index) // Only include files with valid indices
      .map(file => ragFileToSource(file, onOpenRagFile))
      .sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity)); // Sort by rank (index)
  }, [ragFiles, onOpenRagFile]);

  const hasSources = sources.length > 0;

  // Pre-process the entire content to build a shared usedSources array
  // Citations are numbered sequentially based on their first appearance in the text
  const sharedUsedSources = React.useMemo(() => {
    if (!hasSources) return null;

    // Pre-scan the entire content for citations in order of appearance
    // Support [R1], [R2], [R1, R3] patterns for RAG
    const citationPattern = /\[([RMW]?\d+(?:\s*,\s*[RMW]?\d+)*)\]/g;
    const firstAppearanceOrder: string[] = []; // Track citation keys (e.g., "R1", "R2")
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

    // Build usedSources array in order of first appearance in text
    const usedSources: Source[] = [];
    const usedNumberToIndex = new Map<string, number>();

    // Process citations in order of first appearance
    firstAppearanceOrder.forEach((citationKey) => {
      // For RAG, citations should be [R1], [R2], etc.
      // Match by extracting the number and finding source with matching rank
      const number = parseInt(citationKey.replace(/^[RMW]/, ''), 10);
      const source = sources.find(s => s.rank === number);
      if (source) {
        const sequentialIndex = usedSources.length; // Sequential index (0, 1, 2, ...)
        usedSources.push(source);
        usedNumberToIndex.set(citationKey, sequentialIndex);
      }
    });

    return { usedSources, usedNumberToIndex: usedNumberToIndex as Map<string, number> | Map<number, number> };
  }, [content, sources, hasSources]);

  // Helper to process children for citations
  const processChildrenForCitations = (children: React.ReactNode): React.ReactNode => {
    if (!hasSources || !sharedUsedSources) {
      return children;
    }

    // Only process simple string/number children - don't process already-rendered React elements
    // Support [R1], [M1], [W1], [1] patterns
    const citationPattern = /\[([RMW]?\d+(?:\s*,\s*[RMW]?\d+)*)\]/;
    
    if (typeof children === 'string') {
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

    // If it's an array, only process string/number elements
    if (Array.isArray(children)) {
      return children.map((child, idx) => {
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
        return child;
      });
    }

    return children;
  };
  
  // Sanitize content: remove empty bullets, normalize formatting
  const cleanedContent = useMemo(() => {
    return sanitizeRagContent(content.trim());
  }, [content]);

  return (
    <AssistantCard>
      {/* Header */}
      <div className="flex items-center gap-2">
        <div className="h-8 w-8 rounded bg-[#19c37d] flex items-center justify-center">
          <svg
            className="h-5 w-5 text-white"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
            />
          </svg>
        </div>
        <div className="text-xs uppercase tracking-wide text-[var(--text-secondary)] font-medium">
          RAG Response
        </div>
      </div>

      {/* Content Section */}
      <div className="border-t border-[var(--border-color)] pt-4 transition-colors">
        <div className="prose max-w-[720px] mx-auto text-[0.95rem] leading-relaxed space-y-4">
          <ReactMarkdown
            components={{
              h1: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              h2: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              h3: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              h4: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              h5: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              h6: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              ul: ({ children }) => (
                <ul className="list-disc ml-6 space-y-1 my-2 text-[var(--text-primary)]">{children}</ul>
              ),
              ol: ({ children }) => (
                <ol className="list-decimal ml-6 space-y-1 my-2 text-[var(--text-primary)]">{children}</ol>
              ),
              li: ({ children }) => {
                const text = React.Children.toArray(children)
                  .map((child) => (typeof child === "string" ? child : ""))
                  .join("");
                
                // Strip citations to check if bullet has any visible content
                const cleanedText = stripCitations(text);
                
                // Don't render empty bullets (e.g., just "-" or just "[1, 3]")
                if (!cleanedText) {
                  return null;
                }
                
                return (
                  <li className="leading-relaxed">
                    {processChildrenForCitations(children)}
                  </li>
                );
              },
              strong: ({ children }) => (
                <strong className="font-semibold text-[var(--text-primary)]">{children}</strong>
              ),
              em: ({ children }) => (
                <em className="italic text-[var(--text-primary)]">{children}</em>
              ),
              code: ({ children, className }) => {
                // Check if this is inline code (not a code block)
                const isInline = !className;
                if (isInline) {
                  // Check if it looks like a source citation
                  const text = String(children);
                  if (text.includes('.pdf') || text.includes('.docx') || text.includes('.pptx') || text.includes('.xlsx') || text.includes(';')) {
                    return (
                      <code className="text-[var(--text-secondary)] text-xs font-normal bg-transparent px-0">
                        {children}
                      </code>
                    );
                  }
                }
                return <code className={className}>{children}</code>;
              },
              p: ({ children }) => {
                const childrenArray = React.Children.toArray(children);
                
                // Check if this paragraph is a sub-section heading:
                // 1. Entire paragraph is a strong element, OR
                // 2. First child is a strong element
                let isSubSectionHeading = false;
                if (childrenArray.length === 1) {
                  const onlyChild = childrenArray[0];
                  if (React.isValidElement(onlyChild) && onlyChild.type === 'strong') {
                    isSubSectionHeading = true;
                  }
                } else {
                  const firstChild = childrenArray[0];
                  if (React.isValidElement(firstChild) && firstChild.type === 'strong') {
                    isSubSectionHeading = true;
                  }
                }
                
                return (
                  <p className="my-2 text-[var(--text-primary)] leading-relaxed">
                    {isSubSectionHeading && <span className="mr-2">-</span>}
                    {processChildrenForCitations(children)}
                  </p>
                );
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
            }}
          >
            {cleanedContent}
          </ReactMarkdown>
        </div>
      </div>
    </AssistantCard>
  );
};

export default RagResponseCard;

