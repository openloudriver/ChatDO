import React from "react";
import SectionHeading from "./shared/SectionHeading";

interface ArticleCardProps {
  url: string;
  title: string;
  siteName?: string;
  published?: string;
  lastUpdated?: string;
  summary: string;
  keyPoints: string[];
  whyMatters?: string;
  estimatedReadTimeMinutes?: number;
  wordCount?: number;
  model?: string;
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

const estimateReadTime = (summary: string, keyPoints: string[], whyMatters?: string, wordCount?: number): number => {
  if (wordCount) {
    // Average reading speed: 200 words per minute
    return Math.max(1, Math.ceil(wordCount / 200));
  }
  
  // Estimate from content
  const allText = `${summary} ${keyPoints.join(' ')} ${whyMatters || ''}`;
  const words = allText.split(/\s+/).filter(w => w.length > 0).length;
  return Math.max(1, Math.ceil(words / 200));
};

export const ArticleCard: React.FC<ArticleCardProps> = ({
  url,
  title,
  siteName,
  published,
  lastUpdated,
  summary,
  keyPoints,
  whyMatters,
  estimatedReadTimeMinutes,
  wordCount,
  model,
}) => {
  const domain = getDomain(url);
  const faviconUrl = getFaviconUrl(url);
  const displaySiteName = (siteName || domain || "Article").toUpperCase();
  const readTime = estimatedReadTimeMinutes || estimateReadTime(summary, keyPoints, whyMatters, wordCount);

  return (
    <div className="rounded-xl bg-[#1a1a1a] border border-[#565869] p-6 space-y-4">
      {/* Header Row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 flex-1 min-w-0">
          {faviconUrl && (
            <img
              src={faviconUrl}
              alt={displaySiteName}
              className="h-5 w-5 rounded-sm flex-shrink-0"
              onError={(e) => {
                // Silently hide favicon on error to prevent console errors
                (e.target as HTMLImageElement).style.display = 'none';
              }}
              onLoad={(e) => {
                // Suppress 410 errors by catching them silently
                const img = e.target as HTMLImageElement;
                if (img.naturalWidth === 0 || img.naturalHeight === 0) {
                  img.style.display = 'none';
                }
              }}
            />
          )}
          <div className="text-xs uppercase tracking-wide text-[#8e8ea0] font-medium">
            {displaySiteName}
          </div>
        </div>
      </div>

      {/* Article Title */}
      <div>
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className="text-base font-semibold text-blue-400 hover:text-blue-300 underline block"
        >
          {title}
        </a>
      </div>

      {/* Subheader: Read time and last updated */}
      <div className="text-xs text-[#8e8ea0] flex items-center gap-2">
        <span>{readTime} min read</span>
        {lastUpdated && (
          <>
            <span>•</span>
            <span>Last updated: {lastUpdated}</span>
          </>
        )}
        {published && !lastUpdated && (
          <>
            <span>•</span>
            <span>Published: {published}</span>
          </>
        )}
      </div>
      
      {/* Content Section */}
      <div className="border-t border-[#565869] pt-4 space-y-4">
        {/* Summary */}
        {summary && (
          <div>
            <SectionHeading>SUMMARY</SectionHeading>
            <p className="text-sm text-[#ececf1] leading-relaxed">{summary}</p>
          </div>
        )}
        
        {/* Key points */}
        {keyPoints && keyPoints.length > 0 && (
          <div>
            <SectionHeading>KEY POINTS</SectionHeading>
            <ul className="list-disc list-inside space-y-1 text-[#ececf1] ml-2">
              {keyPoints.map((point, index) => (
                <li key={index} className="text-sm text-[#ececf1] leading-relaxed">{point}</li>
              ))}
            </ul>
          </div>
        )}
        
        {/* Why this matters */}
        {whyMatters && (
          <div>
            <SectionHeading>WHY THIS MATTERS</SectionHeading>
            <p className="text-sm text-[#ececf1] leading-relaxed">{whyMatters}</p>
          </div>
        )}
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

export default ArticleCard;
