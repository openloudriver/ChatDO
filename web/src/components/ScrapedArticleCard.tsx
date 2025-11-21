import React from "react";
import ReactMarkdown from "react-markdown";

interface ScrapedArticleCardProps {
  title: string;
  sourceUrl?: string;
  outlet?: string;
  published?: string;
  bodyMarkdown: string;
}

const getDomain = (url?: string) => {
  if (!url) return undefined;
  try {
    const u = new URL(url);
    return u.hostname.replace(/^www\./, "");
  } catch {
    return undefined;
  }
};

const getFaviconUrl = (url?: string) => {
  if (!url) return undefined;
  try {
    const u = new URL(url);
    return `${u.protocol}//${u.hostname}/favicon.ico`;
  } catch {
    return undefined;
  }
};

export const ScrapedArticleCard: React.FC<ScrapedArticleCardProps> = ({
  title,
  sourceUrl,
  outlet,
  published,
  bodyMarkdown,
}) => {
  const domain = getDomain(sourceUrl);
  const faviconUrl = getFaviconUrl(sourceUrl);

  return (
    <div className="rounded-xl bg-[#1a1a1a] border border-[#565869] p-6 space-y-4">
      <div className="flex items-center gap-3">
        {faviconUrl && (
          <img
            src={faviconUrl}
            alt={domain ?? "Site favicon"}
            className="h-6 w-6 rounded-sm"
            onError={(e) => {
              // Hide image if favicon fails to load
              (e.target as HTMLImageElement).style.display = 'none';
            }}
          />
        )}
        <div className="flex flex-col flex-1">
          <div className="text-xs uppercase tracking-wide text-[#8e8ea0]">
            {outlet || domain || "Scraped article"}
          </div>
          {sourceUrl ? (
            <a
              href={sourceUrl}
              target="_blank"
              rel="noreferrer"
              className="text-base font-semibold text-blue-400 hover:text-blue-300 underline"
            >
              {title || "Untitled article"}
            </a>
          ) : (
            <div className="text-base font-semibold text-[#ececf1]">
              {title || "Untitled article"}
            </div>
          )}
          {published && (
            <div className="text-xs text-[#8e8ea0] mt-0.5">
              Published: {published}
            </div>
          )}
        </div>
      </div>
      <div className="border-t border-[#565869] pt-4">
        <div className="prose prose-invert prose-sm max-w-none">
          <ReactMarkdown
            components={{
              h2: ({ children }) => <h2 className="text-2xl font-bold mb-4 text-[#ececf1] border-b border-[#565869] pb-2">{children}</h2>,
              h3: ({ children }) => <h3 className="text-xl font-semibold mt-6 mb-3 text-[#ececf1]">{children}</h3>,
              p: ({ children }) => <p className="mb-3 text-[#ececf1] leading-relaxed">{children}</p>,
              ul: ({ children }) => <ul className="list-disc list-inside mb-4 space-y-2 text-[#ececf1] ml-4">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal list-inside mb-4 space-y-2 text-[#ececf1] ml-4">{children}</ol>,
              li: ({ children }) => <li className="text-[#ececf1] mb-1">{children}</li>,
              strong: ({ children }) => <strong className="font-semibold text-[#ececf1]">{children}</strong>,
              em: ({ children }) => <em className="italic text-[#ececf1]">{children}</em>,
              hr: () => <hr className="my-6 border-[#565869]" />,
              a: ({ href, children }) => (
                <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300 underline">
                  {children}
                </a>
              ),
            }}
          >
            {bodyMarkdown}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
};

export default ScrapedArticleCard;

