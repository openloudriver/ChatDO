import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import SectionHeading from "./shared/SectionHeading";
import type { RagFile } from "../types/rag";

export interface RagResponseCardProps {
  content: string;
  ragFiles: RagFile[]; // Indexed RAG files (single source of truth)
  model?: string;
  onOpenRagFile: (file: RagFile) => void;
}

// Helper to find file by index
const findFileByIndex = (ragFiles: RagFile[], index: number): RagFile | undefined =>
  ragFiles.find((f) => f.index === index);

// Parse source citations - handles both formats:
// 1. source: [n] or [n] or source: [n, m] (new format)
// 2. (Source: filename) or (Source: filename1; filename2) (old format - convert to numbers)
const parseSourceCitations = (
  text: string, 
  ragFiles: RagFile[]
): { before: string; indices: number[]; after: string } | null => {
  // First, try the new format: source: [n] or just [n]
  let match = text.match(/(?:source:\s*)?\[([0-9,\s]+)\]/i);
  if (match) {
    const before = text.slice(0, match.index);
    const after = text.slice(match.index! + match[0].length);
    const indices = match[1]
      .split(',')
      .map((s) => parseInt(s.trim(), 10))
      .filter((n) => !Number.isNaN(n) && n > 0);
    return { before, indices, after };
  }
  
  // Fallback: try old format (Source: filename) and convert to numbers
  // Handle nested parentheses by counting them
  const sourcePattern = /\(Sources?:/i;
  const sourceMatch = text.search(sourcePattern);
  if (sourceMatch === -1) return null;
  
  // Find the matching closing parenthesis, accounting for nested parens
  let parenCount = 0;
  let startIdx = sourceMatch;
  let endIdx = startIdx;
  
  for (let i = startIdx; i < text.length; i++) {
    if (text[i] === '(') parenCount++;
    if (text[i] === ')') {
      parenCount--;
      if (parenCount === 0) {
        endIdx = i + 1;
        break;
      }
    }
  }
  
  if (endIdx === startIdx) return null; // No closing paren found
  
  const before = text.slice(0, startIdx);
  const after = text.slice(endIdx);
  const fullMatch = text.slice(startIdx, endIdx);
  
  // Extract filenames from the source citation (remove the outer parentheses and "Source:" prefix)
  const sourceText = fullMatch
    .replace(/^\(Sources?:/i, "")
    .replace(/\)$/, "")
    .trim();
  
  const sourceNames = sourceText
    .split(/;|,/)
    .map((s) => s.trim())
    .filter(Boolean);
  
  // Convert filenames to indices
  const indices: number[] = [];
  for (const name of sourceNames) {
    const cleanName = name.trim().toLowerCase();
    // Try exact match first
    let file = ragFiles.find((f) => f.filename.toLowerCase() === cleanName);
    
    // If no exact match, try matching by filename without extension
    if (!file) {
      const nameWithoutExt = cleanName.replace(/\.(pdf|docx|pptx|xlsx|doc|ppt|xls)$/, '');
      file = ragFiles.find((f) => {
        const filenameWithoutExt = f.filename.toLowerCase().replace(/\.(pdf|docx|pptx|xlsx|doc|ppt|xls)$/, '');
        return filenameWithoutExt === nameWithoutExt || 
               filenameWithoutExt.includes(nameWithoutExt) ||
               nameWithoutExt.includes(filenameWithoutExt);
      });
    }
    
    // If still no match, try startsWith for longer names
    if (!file && cleanName.length >= 10) {
      file = ragFiles.find((f) => f.filename.toLowerCase().startsWith(cleanName));
    }
    
    if (file) {
      indices.push(file.index);
    }
  }
  
  if (indices.length === 0) return null;
  
  return { before, indices, after };
};

export const RagResponseCard: React.FC<RagResponseCardProps> = ({
  content,
  ragFiles,
  model,
  onOpenRagFile,
}) => {
  const cleanedContent = content.trim();
  const [hoveredFileId, setHoveredFileId] = useState<string | null>(null);
  const [tooltipPosition, setTooltipPosition] = useState<{ x: number; y: number } | null>(null);

  return (
    <div className="rounded-xl bg-[#1a1a1a] border border-[#565869] p-6 space-y-4">
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
        <div className="text-xs uppercase tracking-wide text-[#8e8ea0] font-medium">
          RAG Response
        </div>
      </div>

      {/* Content Section */}
      <div className="border-t border-[#565869] pt-4">
        <div className="prose prose-invert max-w-none text-sm text-[#ececf1] leading-relaxed">
          <ReactMarkdown
            components={{
              h1: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              h2: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              h3: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              h4: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              h5: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              h6: ({ children }) => <SectionHeading>{children}</SectionHeading>,
              ul: ({ children }) => (
                <ul className="list-disc list-inside mb-4 space-y-1 text-[#ececf1] ml-2">{children}</ul>
              ),
              ol: ({ children }) => (
                <ol className="list-decimal list-inside mb-4 space-y-1 text-[#ececf1] ml-2">{children}</ol>
              ),
              li: ({ children }) => {
                const text = React.Children.toArray(children)
                  .map((child) => (typeof child === "string" ? child : ""))
                  .join("");
                
                const parsed = parseSourceCitations(text, ragFiles);
                if (!parsed || parsed.indices.length === 0) {
                  return (
                    <li className="ml-4 text-sm text-[#ececf1] mb-1">
                      {children}
                    </li>
                  );
                }

                return (
                  <li className="ml-4 text-sm text-[#ececf1] mb-1">
                    {parsed.before}
                    {" "}
                    <span className="text-[11px] text-[#8e8ea0] italic ml-1">
                      [
                      {parsed.indices.map((num, idx) => {
                        const file = findFileByIndex(ragFiles, num);
                        if (!file) {
                          return (
                            <span key={num}>{num}{idx < parsed.indices.length - 1 ? ", " : ""}</span>
                          );
                        }
                        return (
                          <span key={file.id} className="relative inline-block">
                            <button
                              type="button"
                              onClick={() => onOpenRagFile(file)}
                              onMouseEnter={(e) => {
                                const rect = e.currentTarget.getBoundingClientRect();
                                setHoveredFileId(file.id);
                                setTooltipPosition({
                                  x: rect.left + rect.width / 2,
                                  y: rect.top - 8,
                                });
                              }}
                              onMouseLeave={() => {
                                setHoveredFileId(null);
                                setTooltipPosition(null);
                              }}
                              className="ml-1 px-1.5 py-0.5 rounded bg-[#2a2b32] text-[10px] text-[#ececf1] hover:bg-[#3a3b45] transition underline"
                            >
                              {num}{idx < parsed.indices.length - 1 ? ", " : ""}
                            </button>
                            {hoveredFileId === file.id && tooltipPosition && (
                              <div
                                className="fixed z-50 px-2 py-1 rounded bg-[#2a2b32] text-[10px] text-[#ececf1] whitespace-nowrap pointer-events-none shadow-lg border border-[#565869]"
                                style={{
                                  left: `${tooltipPosition.x}px`,
                                  top: `${tooltipPosition.y}px`,
                                  transform: 'translate(-50%, -100%)',
                                  fontStyle: 'normal',
                                }}
                              >
                                {file.filename}
                              </div>
                            )}
                          </span>
                        );
                      })}
                      ]
                    </span>
                    {parsed.after && ` ${parsed.after}`}
                  </li>
                );
              },
              strong: ({ children }) => (
                <strong className="font-semibold text-[#ececf1]">{children}</strong>
              ),
              em: ({ children }) => (
                <em className="italic text-[#ececf1]">{children}</em>
              ),
              code: ({ children, className }) => {
                // Check if this is inline code (not a code block)
                const isInline = !className;
                if (isInline) {
                  // Check if it looks like a source citation
                  const text = String(children);
                  if (text.includes('.pdf') || text.includes('.docx') || text.includes('.pptx') || text.includes('.xlsx') || text.includes(';')) {
                    return (
                      <code className="text-[#6b7280] text-xs font-normal bg-transparent px-0">
                        {children}
                      </code>
                    );
                  }
                }
                return <code className={className}>{children}</code>;
              },
              p: ({ children }) => {
                const text = React.Children.toArray(children)
                  .map((child) => (typeof child === "string" ? child : ""))
                  .join("");
                
                const parsed = parseSourceCitations(text, ragFiles);
                if (!parsed || parsed.indices.length === 0) {
                  return (
                    <p className="mb-3 text-sm leading-relaxed text-[#ececf1]">
                      {children}
                    </p>
                  );
                }

                return (
                  <p className="mb-3 text-sm leading-relaxed text-[#ececf1]">
                    {parsed.before}
                    {" "}
                    <span className="text-[11px] text-[#8e8ea0] italic ml-1">
                      [
                      {parsed.indices.map((num, idx) => {
                        const file = findFileByIndex(ragFiles, num);
                        if (!file) {
                          return (
                            <span key={num}>{num}{idx < parsed.indices.length - 1 ? ", " : ""}</span>
                          );
                        }
                        return (
                          <span key={file.id} className="relative inline-block">
                            <button
                              type="button"
                              onClick={() => onOpenRagFile(file)}
                              onMouseEnter={(e) => {
                                const rect = e.currentTarget.getBoundingClientRect();
                                setHoveredFileId(file.id);
                                setTooltipPosition({
                                  x: rect.left + rect.width / 2,
                                  y: rect.top - 8,
                                });
                              }}
                              onMouseLeave={() => {
                                setHoveredFileId(null);
                                setTooltipPosition(null);
                              }}
                              className="ml-1 px-1.5 py-0.5 rounded bg-[#2a2b32] text-[10px] text-[#ececf1] hover:bg-[#3a3b45] transition underline"
                            >
                              {num}{idx < parsed.indices.length - 1 ? ", " : ""}
                            </button>
                            {hoveredFileId === file.id && tooltipPosition && (
                              <div
                                className="fixed z-50 px-2 py-1 rounded bg-[#2a2b32] text-[10px] text-[#ececf1] whitespace-nowrap pointer-events-none shadow-lg border border-[#565869]"
                                style={{
                                  left: `${tooltipPosition.x}px`,
                                  top: `${tooltipPosition.y}px`,
                                  transform: 'translate(-50%, -100%)',
                                  fontStyle: 'normal',
                                }}
                              >
                                {file.filename}
                              </div>
                            )}
                          </span>
                        );
                      })}
                      ]
                    </span>
                    {parsed.after && ` ${parsed.after}`}
                  </p>
                );
              },
            }}
          >
            {cleanedContent}
          </ReactMarkdown>
        </div>
      </div>


      {/* Model attribution footer */}
      {model && (
        <div className="border-t border-[#565869] pt-4">
          <div className="text-xs text-[#8e8ea0] text-right">
            Model: {model}
          </div>
        </div>
      )}
    </div>
  );
};

export default RagResponseCard;

