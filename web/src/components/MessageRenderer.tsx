import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

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
  return (
    <div className="max-w-full text-gray-100 leading-relaxed text-sm sm:text-[15px]">
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
            <p className="my-2 text-gray-200 whitespace-pre-wrap">{children}</p>
          ),
          ul: ({ children }) => (
            <ul className="list-disc ml-5 my-2 space-y-1">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal ml-5 my-2 space-y-1">{children}</ol>
          ),
          li: ({ children }) => <li className="leading-snug">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-4 border-slate-500 pl-3 ml-1 my-3 italic text-slate-200">
              {children}
            </blockquote>
          ),
          code: ({ className, children, ...props }) => {
            const isInline = !className;
            return isInline ? (
              <code className="bg-slate-800/80 px-1 py-0.5 rounded text-xs sm:text-[13px] font-mono" {...props}>
                {children}
              </code>
            ) : (
              <code className="font-mono text-xs sm:text-[13px]" {...props}>
                {children}
              </code>
            );
          },
          pre: ({ children }) => (
            <pre className="bg-slate-900/90 border border-slate-800 rounded-lg p-3 my-3 overflow-x-auto text-xs sm:text-[13px]">
              {children}
            </pre>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-gray-100">
              {children}
            </strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

