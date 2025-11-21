import React, { useState } from "react";

interface ArticleInfo {
  url: string;
  title: string;
  domain: string;
}

interface MultiArticleCardProps {
  articles: ArticleInfo[];
  jointSummary: string;
  keyAgreements: string[];
  keyDifferences: string[];
  whyMatters?: string;
}

const getDomain = (url: string) => {
  try {
    const u = new URL(url);
    return u.hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
};

export const MultiArticleCard: React.FC<MultiArticleCardProps> = ({
  articles,
  jointSummary,
  keyAgreements,
  keyDifferences,
  whyMatters,
}) => {
  const [copied, setCopied] = useState(false);

  const handleCopySummary = async () => {
    const copyText = [
      jointSummary && `Joint Summary:\n${jointSummary}`,
      keyAgreements && keyAgreements.length > 0 && `\n\nKey Agreements:\n${keyAgreements.map(p => `• ${p}`).join('\n')}`,
      keyDifferences && keyDifferences.length > 0 && `\n\nKey Differences:\n${keyDifferences.map(p => `• ${p}`).join('\n')}`,
      whyMatters && `\n\nWhy This Matters:\n${whyMatters}`,
    ].filter(Boolean).join('\n');

    try {
      await navigator.clipboard.writeText(copyText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error('Failed to copy:', error);
    }
  };

  return (
    <div className="rounded-xl bg-[#1a1a1a] border border-[#565869] p-6 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1">
          <div className="text-xs uppercase tracking-wide text-[#8e8ea0] font-medium mb-2">
            Multi-Article Summary
          </div>
          <div className="space-y-1">
            {articles.map((article, index) => (
              <div key={index} className="flex items-center gap-2">
                <span className="text-xs text-[#8e8ea0]">{index + 1}.</span>
                <a
                  href={article.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm text-blue-400 hover:text-blue-300 underline"
                >
                  {article.title}
                </a>
                <span className="text-xs text-[#8e8ea0]">({article.domain.toUpperCase()})</span>
              </div>
            ))}
          </div>
        </div>
        <button
          onClick={handleCopySummary}
          className="p-1.5 hover:bg-[#565869]/50 rounded transition-colors text-[#8e8ea0] hover:text-white flex-shrink-0"
          title="Copy summary"
        >
          {copied ? (
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          ) : (
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
          )}
        </button>
      </div>

      {/* Content Section */}
      <div className="border-t border-[#565869] pt-4 space-y-4">
        {/* Joint Summary */}
        {jointSummary && (
          <div>
            <h3 className="text-sm font-semibold text-[#8e8ea0] mb-2 uppercase tracking-wide">
              Joint Summary
            </h3>
            <p className="text-[#ececf1] leading-relaxed">{jointSummary}</p>
          </div>
        )}

        {/* Key Agreements */}
        {keyAgreements && keyAgreements.length > 0 && (
          <div>
            <h3 className="text-sm font-semibold text-[#8e8ea0] mb-2 uppercase tracking-wide">
              Key Agreements
            </h3>
            <ul className="list-disc list-inside space-y-1 text-[#ececf1] ml-2">
              {keyAgreements.map((point, index) => (
                <li key={index} className="text-sm">{point}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Key Differences */}
        {keyDifferences && keyDifferences.length > 0 && (
          <div>
            <h3 className="text-sm font-semibold text-[#8e8ea0] mb-2 uppercase tracking-wide">
              Key Differences
            </h3>
            <ul className="list-disc list-inside space-y-1 text-[#ececf1] ml-2">
              {keyDifferences.map((point, index) => (
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

      {/* Footer */}
      <div className="border-t border-[#565869] pt-3">
        <div className="text-xs text-[#8e8ea0] text-right">
          Model: Trafilatura + GPT-5
        </div>
      </div>
    </div>
  );
};

export default MultiArticleCard;

