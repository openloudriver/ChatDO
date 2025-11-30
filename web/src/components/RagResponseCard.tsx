import React, { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import SectionHeading from "./shared/SectionHeading";
import { AssistantCard } from "./shared/AssistantCard";
import type { RagFile } from "../types/rag";

export interface RagResponseCardProps {
  content: string;
  ragFiles: RagFile[]; // Indexed RAG files (single source of truth)
  onOpenRagFile: (file: RagFile) => void;
}

// Build lookup map: index -> RagFile
const buildRagFilesByIndex = (ragFiles: RagFile[]): Record<number, RagFile> => {
  const map: Record<number, RagFile> = {};
  ragFiles.forEach((file) => {
    if (file.index) {
      map[file.index] = file;
    }
  });
  return map;
};

// Convert number to superscript (¹, ², ³, etc.)
const toSuperscript = (num: number): string => {
  const superscripts = ['⁰', '¹', '²', '³', '⁴', '⁵', '⁶', '⁷', '⁸', '⁹'];
  return num.toString().split('').map(d => superscripts[parseInt(d)]).join('');
};

// CitationChip component for inline citations like [1] or [1, 3] - ChatGPT style with superscript numbers
type CitationChipProps = {
  indices: number[]; // e.g. [1] or [1, 3]
  ragFilesByIndex: Record<number, RagFile>;
  onOpenFile: (file: RagFile) => void;
};

const CitationChip: React.FC<CitationChipProps> = ({
  indices,
  ragFilesByIndex,
  onOpenFile,
}) => {
  if (!indices.length) return null;

  // Pick the first index as the file we open on click
  const primaryIndex = indices[0];
  const primaryFile = ragFilesByIndex[primaryIndex];

  // Tooltip: join all file names we have for the indices
  const tooltipText = indices
    .map((i) => ragFilesByIndex[i]?.filename || `Source ${i}`)
    .join(", ");

  // Display citation numbers as superscript (e.g., ¹²³)
  const citationNumbers = indices.map(i => toSuperscript(i)).join('');

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (primaryFile) {
      onOpenFile(primaryFile);
    }
  };

  return (
    <sup
      onClick={handleClick}
      className="text-[10px] text-[var(--text-secondary)] align-super ml-0.5 cursor-pointer hover:text-[var(--text-primary)] transition-colors"
      title={tooltipText}
    >
      {citationNumbers}
    </sup>
  );
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

// Render text with citations replaced by CitationChip components
function renderTextWithCitations(
  text: string,
  ragFilesByIndex: Record<number, RagFile>,
  onOpenFile: (file: RagFile) => void,
): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  // Create a new regex instance for each call to avoid state issues
  const regex = /\[(\d+(?:\s*,\s*\d+)*)\]/g;

  while ((match = regex.exec(text)) !== null) {
    const matchStart = match.index;

    // Plain text before the citation
    if (matchStart > lastIndex) {
      const beforeText = text.slice(lastIndex, matchStart);
      parts.push(beforeText);
    }

    // Parse citation numbers and filter out invalid ones (hallucinated citations)
    const numbers = match[1]
      .split(",")
      .map((n) => parseInt(n.trim(), 10))
      .filter((n) => !Number.isNaN(n) && n > 0)
      .filter((n) => ragFilesByIndex[n] !== undefined); // Only include citations that exist

    if (numbers.length > 0) {
      parts.push(
        <CitationChip
          key={`cit-${matchStart}-${match[0]}`}
          indices={numbers}
          ragFilesByIndex={ragFilesByIndex}
          onOpenFile={onOpenFile}
        />
      );
    } else {
      // If all citations are invalid, don't render anything (silently ignore hallucinated citations)
      // This prevents showing broken citations like [6] when there are only 5 files
    }

    lastIndex = regex.lastIndex;
  }

  // Remaining text after the last match
  if (lastIndex < text.length) {
    let remainingText = text.slice(lastIndex);
    
    // If period is immediately after the last citation, move it before the citation
    if (remainingText.trim().startsWith('.')) {
      // Find the last text part (not a React element) and add period to it
      for (let i = parts.length - 1; i >= 0; i--) {
        if (typeof parts[i] === 'string') {
          const textPart = parts[i] as string;
          // Only add period if it doesn't already end with one
          if (!textPart.trim().endsWith('.')) {
            parts[i] = textPart.trim() + '.';
          }
          // Remove the period from remaining text
          remainingText = remainingText.trim().substring(1).trim();
          break;
        }
      }
    }
    
    if (remainingText.trim()) {
      parts.push(remainingText);
    }
  }

  return parts;
}

export const RagResponseCard: React.FC<RagResponseCardProps> = ({
  content,
  ragFiles,
  onOpenRagFile,
}) => {
  // Build lookup map: index -> RagFile (single source of truth)
  const ragFilesByIndex = useMemo(() => buildRagFilesByIndex(ragFiles), [ragFiles]);
  
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
        <div className="prose max-w-none text-sm text-[var(--text-primary)] leading-relaxed">
          <ReactMarkdown
            components={{
              h1: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              h2: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              h3: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              h4: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              h5: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              h6: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              ul: ({ children }) => (
                <ul className="list-none mb-4 space-y-1 text-[var(--text-primary)] ml-2">{children}</ul>
              ),
              ol: ({ children }) => (
                <ol className="list-none mb-4 space-y-1 text-[var(--text-primary)] ml-2">{children}</ol>
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
                
                // Check if text contains citations (use fresh regex to avoid state issues)
                const hasCitations = /\[(\d+(?:\s*,\s*\d+)*)\]/g.test(text);
                if (!hasCitations) {
                  return (
                    <li className="ml-4 text-sm text-[var(--text-primary)] mb-1 before:content-['•'] before:mr-2">
                      {children}
                    </li>
                  );
                }

                // Render with citations
                const rendered = renderTextWithCitations(text, ragFilesByIndex, onOpenRagFile);

                return (
                  <li className="ml-4 text-sm text-[var(--text-primary)] mb-1 before:content-['•'] before:mr-2">
                    {rendered}
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
                const text = childrenArray
                  .map((child) => (typeof child === "string" ? child : ""))
                  .join("");
                
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
                
                // Check if text contains citations (use fresh regex to avoid state issues)
                const hasCitations = /\[(\d+(?:\s*,\s*\d+)*)\]/g.test(text);
                
                if (!hasCitations) {
                  return (
                    <p className="mb-3 text-sm leading-relaxed text-[var(--text-primary)]">
                      {isSubSectionHeading && <span className="mr-2">-</span>}
                      {children}
                    </p>
                  );
                }

                // Render with citations
                const rendered = renderTextWithCitations(text, ragFilesByIndex, onOpenRagFile);

                return (
                  <p className="mb-3 text-sm leading-relaxed text-[var(--text-primary)]">
                    {isSubSectionHeading && <span className="mr-2">-</span>}
                    {rendered}
                  </p>
                );
              },
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

