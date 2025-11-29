import React from "react";
import SectionHeading from "./shared/SectionHeading";
import { AssistantCard } from "./shared/AssistantCard";
import { formatPublishedDate } from "../utils/formatDate";

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
  const formattedDate = formatPublishedDate(published);

  return (
    <AssistantCard
      footer={model ? `Model: ${model}` : undefined}
    >
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
          <div className="text-xs uppercase tracking-[0.5px] text-white/45 font-medium">
            {displaySiteName}
          </div>
        </div>
      </div>

      {/* Article Title */}
      <div className="mt-2">
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className="text-lg font-semibold text-[#4EA1FF] hover:underline cursor-pointer block leading-[1.4] max-sm:text-base"
        >
          {title}
        </a>
      </div>

      {/* Subheader: Read time and last updated */}
      <div className="text-[13px] text-white/45 flex items-center gap-3">
        {formattedDate && (
          <>
            <span>Published: {formattedDate}</span>
            <span>•</span>
          </>
        )}
        <span>{readTime} min read</span>
        {lastUpdated && (
          <>
            <span>•</span>
            <span>Last updated: {lastUpdated}</span>
          </>
        )}
      </div>
      
      {/* Content Section */}
      <div className="space-y-8">
        {/* Summary */}
        {summary && (
          <div>
            <SectionHeading>SUMMARY</SectionHeading>
            <p className="text-[15px] text-white/82 leading-[1.65]">{summary}</p>
          </div>
        )}
        
        {/* Key points */}
        {keyPoints && keyPoints.length > 0 && (
          <div>
            <SectionHeading>KEY POINTS</SectionHeading>
            <ul className="list-disc ml-4 mt-2 mb-5 space-y-[6px]">
              {keyPoints.map((point, index) => (
                <li key={index} className="text-[15px] text-white/82 leading-[1.65]">{point}</li>
              ))}
            </ul>
          </div>
        )}
        
        {/* Why this matters */}
        {whyMatters && (
          <div>
            <SectionHeading>WHY THIS MATTERS</SectionHeading>
            <p className="text-[15px] text-white/82 leading-[1.65]">{whyMatters}</p>
          </div>
        )}
      </div>
    </AssistantCard>
  );
};

export default ArticleCard;
