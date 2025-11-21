import React from "react";

interface ArticleCardProps {
  url: string;
  title: string;
  siteName?: string;
  published?: string;
  summary: string;
  keyPoints: string[];
  whyMatters?: string;
}

const getDomain = (url: string) => {
  try {
    const u = new URL(url);
    return u.hostname.replace(/^www\./, "");
  } catch {
    return undefined;
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

export const ArticleCard: React.FC<ArticleCardProps> = ({
  url,
  title,
  siteName,
  published,
  summary,
  keyPoints,
  whyMatters,
}) => {
  const domain = getDomain(url);
  const faviconUrl = getFaviconUrl(url);
  const displaySiteName = siteName || domain || "Article";

  return (
    <div className="rounded-xl bg-[#1a1a1a] border border-[#565869] p-6 space-y-4">
      <div className="flex items-center gap-3">
        {faviconUrl && (
          <img
            src={faviconUrl}
            alt={displaySiteName}
            className="h-6 w-6 rounded-sm"
            onError={(e) => {
              // Hide image if favicon fails to load
              (e.target as HTMLImageElement).style.display = 'none';
            }}
          />
        )}
        <div className="flex flex-col flex-1">
          <div className="text-xs uppercase tracking-wide text-[#8e8ea0]">
            {displaySiteName}
          </div>
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            className="text-base font-semibold text-blue-400 hover:text-blue-300 underline"
          >
            {title}
          </a>
          {published && (
            <div className="text-xs text-[#8e8ea0] mt-0.5">
              Published: {published}
            </div>
          )}
        </div>
      </div>
      
      <div className="border-t border-[#565869] pt-4 space-y-4">
        {/* Summary paragraph */}
        <div>
          <p className="text-[#ececf1] leading-relaxed">{summary}</p>
        </div>
        
        {/* Key points */}
        {keyPoints && keyPoints.length > 0 && (
          <div>
            <h3 className="text-sm font-semibold text-[#8e8ea0] mb-2 uppercase tracking-wide">
              Key Points
            </h3>
            <ul className="list-disc list-inside space-y-1 text-[#ececf1] ml-2">
              {keyPoints.map((point, index) => (
                <li key={index} className="text-sm">{point}</li>
              ))}
            </ul>
          </div>
        )}
        
        {/* Why this matters */}
        {whyMatters && (
          <div>
            <h3 className="text-sm font-semibold text-[#8e8ea0] mb-2 uppercase tracking-wide">
              Why This Matters
            </h3>
            <p className="text-sm text-[#ececf1] leading-relaxed">{whyMatters}</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default ArticleCard;
