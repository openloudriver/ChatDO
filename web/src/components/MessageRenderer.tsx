import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { fixNumberedLists } from "./ChatMessages";

type MessageRendererProps = {
  content: string;
};

/**
 * Renders assistant/user messages with nice Markdown formatting:
 * - Headings
 * - Bullet/numbered lists
 * - Blockquotes
 * - Code + code blocks
 *
 * This is for "normal" ChatDO messages and does NOT affect
 * the special summary cards for URLs.
 */
export function MessageRenderer({ content }: MessageRendererProps) {
  // Fix numbered lists before rendering
  const processedContent = fixNumberedLists(content);
  
  return (
    <div className="prose max-w-none">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="text-2xl sm:text-3xl font-bold mt-4 mb-3">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-xl sm:text-2xl font-semibold mt-4 mb-2">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-lg sm:text-xl font-semibold mt-3 mb-2">
              {children}
            </h3>
          ),
          p: ({ children }) => (
            <p className="my-2 text-[var(--text-primary)] whitespace-pre-wrap">{children}</p>
          ),
          ul: ({ children }) => (
            <ul className="list-disc ml-5 my-2 space-y-1">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal ml-5 my-2 space-y-1">{children}</ol>
          ),
          li: ({ children }) => <li className="leading-snug">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-4 border-[var(--border-color)] pl-3 ml-1 my-3 italic text-[var(--text-primary)] transition-colors">
              {children}
            </blockquote>
          ),
          code: ({ className, children, ...props }) => {
            const isInline = !className;
            return isInline ? (
              <code className="bg-[var(--code-bg)] px-1 py-0.5 rounded text-xs sm:text-[13px] font-mono text-[var(--code-text)] transition-colors" {...props}>
                {children}
              </code>
            ) : (
              <code className="font-mono text-xs sm:text-[13px]" {...props}>
                {children}
              </code>
            );
          },
          pre: ({ children }) => (
            <pre className="bg-[var(--code-bg)] border border-[var(--border-color)] rounded-lg p-3 my-3 overflow-x-auto text-xs sm:text-[13px] text-[var(--code-text)] transition-colors">
              {children}
            </pre>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-[var(--text-primary)]">
              {children}
            </strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
        }}
      >
        {processedContent}
      </ReactMarkdown>
    </div>
  );
}

