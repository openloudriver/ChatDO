import React from "react";
import ReactMarkdown from "react-markdown";
import SectionHeading from "./shared/SectionHeading";

interface RagResponseCardProps {
  content: string;
  sources?: string[];
  model?: string;
}

// Extract sources from content (look for "Sources:" patterns)
const extractSources = (content: string): string[] => {
  const sources: string[] = [];
  const sourcePatterns = [
    /\(Sources?:?\s*([^)]+)\)/gi,
    /Sources?:?\s*([^\n]+)/gi,
  ];
  
  for (const pattern of sourcePatterns) {
    const matches = content.matchAll(pattern);
    for (const match of matches) {
      const sourceList = match[1]
        .split(/[;,]/)
        .map(s => s.trim())
        .filter(s => s.length > 0);
      sources.push(...sourceList);
    }
  }
  
  // Remove duplicates and return
  return Array.from(new Set(sources));
};

// Clean content - we'll keep source citations but style them differently
const cleanContent = (content: string): string => {
  // Don't remove sources - we'll style them in the markdown renderer
  return content.trim();
};

export const RagResponseCard: React.FC<RagResponseCardProps> = ({
  content,
  sources,
  model,
}) => {
  // Extract sources from content if not provided
  const extractedSources = sources || extractSources(content);
  const cleanedContent = cleanContent(content);

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
              li: ({ children }) => (
                <li className="ml-4 text-[#ececf1]">{children}</li>
              ),
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
              // Style parenthetical source citations
              p: ({ children }) => {
                // Convert children to string to check for source citations
                const childrenArray = React.Children.toArray(children);
                const hasSourceCitation = childrenArray.some(child => {
                  const text = typeof child === 'string' ? child : String(child);
                  return text.match(/\(References?:?\s*[^)]+\)|\(Sources?:?\s*[^)]+\)/gi);
                });
                
                if (hasSourceCitation) {
                  return (
                    <p className="mb-3 text-[#ececf1] leading-relaxed">
                      {React.Children.map(children, (child, idx) => {
                        if (typeof child === 'string') {
                          // Split text and style source citations
                          const parts = child.split(/(\(References?:?\s*[^)]+\)|\(Sources?:?\s*[^)]+\))/gi);
                          return (
                            <React.Fragment key={idx}>
                              {parts.map((part, i) => {
                                if (part.match(/\(References?:?\s*[^)]+\)|\(Sources?:?\s*[^)]+\)/gi)) {
                                  return (
                                    <span key={i} className="text-[#6b7280] text-xs italic">
                                      {part}
                                    </span>
                                  );
                                }
                                return <React.Fragment key={i}>{part}</React.Fragment>;
                              })}
                            </React.Fragment>
                          );
                        }
                        return child;
                      })}
                    </p>
                  );
                }
                return <p className="mb-3 text-[#ececf1] leading-relaxed">{children}</p>;
              },
            }}
          >
            {cleanedContent}
          </ReactMarkdown>
        </div>
      </div>

      {/* Sources Section */}
      {extractedSources.length > 0 && (
        <div className="border-t border-[#565869] pt-4">
          <SectionHeading>SOURCES</SectionHeading>
          <div className="flex flex-wrap gap-2">
            {extractedSources.map((source, index) => (
              <span
                key={index}
                className="px-3 py-1.5 bg-[#40414f] text-[#ececf1] rounded-md text-xs font-medium"
              >
                {source}
              </span>
            ))}
          </div>
        </div>
      )}

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

