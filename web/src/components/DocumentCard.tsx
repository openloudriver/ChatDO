import React, { useState } from "react";

interface DocumentCardProps {
  fileName: string;
  fileType?: string;
  filePath?: string;
  summary: string;
  keyPoints: string[];
  whyMatters?: string;
  estimatedReadTimeMinutes?: number;
  wordCount?: number;
  pageCount?: number;
}

const getFileIcon = (fileName: string) => {
  const ext = fileName.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'pdf':
      return (
        <svg className="w-6 h-6 text-red-400" fill="currentColor" viewBox="0 0 24 24">
          <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" />
        </svg>
      );
    case 'doc':
    case 'docx':
      return (
        <svg className="w-6 h-6 text-blue-400" fill="currentColor" viewBox="0 0 24 24">
          <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" />
        </svg>
      );
    case 'txt':
    case 'md':
      return (
        <svg className="w-6 h-6 text-gray-400" fill="currentColor" viewBox="0 0 24 24">
          <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" />
        </svg>
      );
    default:
      return (
        <svg className="w-6 h-6 text-gray-400" fill="currentColor" viewBox="0 0 24 24">
          <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" />
        </svg>
      );
  }
};

const estimateReadTime = (summary: string, keyPoints: string[], whyMatters?: string, wordCount?: number): number => {
  if (wordCount) {
    return Math.max(1, Math.ceil(wordCount / 200));
  }
  const allText = `${summary} ${keyPoints.join(' ')} ${whyMatters || ''}`;
  const words = allText.split(/\s+/).filter(w => w.length > 0).length;
  return Math.max(1, Math.ceil(words / 200));
};

export const DocumentCard: React.FC<DocumentCardProps> = ({
  fileName,
  fileType,
  filePath,
  summary,
  keyPoints,
  whyMatters,
  estimatedReadTimeMinutes,
  wordCount,
  pageCount,
}) => {
  const [copied, setCopied] = useState(false);
  const readTime = estimatedReadTimeMinutes || estimateReadTime(summary, keyPoints, whyMatters, wordCount);

  const handleCopySummary = async () => {
    const copyText = [
      summary && `Summary:\n${summary}`,
      keyPoints && keyPoints.length > 0 && `\n\nKey Points:\n${keyPoints.map(p => `• ${p}`).join('\n')}`,
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
      {/* Header Row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 flex-1 min-w-0">
          {getFileIcon(fileName)}
          <div className="text-xs uppercase tracking-wide text-[#8e8ea0] font-medium">
            Document
          </div>
        </div>
        {/* Copy Summary Button */}
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

      {/* Document Title */}
      <div>
        <div className="text-base font-semibold text-[#ececf1]">
          {fileName}
        </div>
        {fileType && (
          <div className="text-xs text-[#8e8ea0] mt-0.5">
            {fileType.toUpperCase()}
          </div>
        )}
      </div>

      {/* Subheader: Read time and metadata */}
      <div className="text-xs text-[#8e8ea0] flex items-center gap-2">
        <span>{readTime} min read</span>
        {pageCount && (
          <>
            <span>•</span>
            <span>{pageCount} page{pageCount !== 1 ? 's' : ''}</span>
          </>
        )}
        {wordCount && (
          <>
            <span>•</span>
            <span>{wordCount.toLocaleString()} words</span>
          </>
        )}
      </div>
      
      {/* Content Section */}
      <div className="border-t border-[#565869] pt-4 space-y-4">
        {/* Summary */}
        {summary && (
          <div>
            <h3 className="text-sm font-semibold text-[#8e8ea0] mb-2 uppercase tracking-wide">
              Summary
            </h3>
            <p className="text-[#ececf1] leading-relaxed">{summary}</p>
          </div>
        )}
        
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

      {/* Footer: Model attribution */}
      <div className="border-t border-[#565869] pt-3">
        <div className="text-xs text-[#8e8ea0] text-right">
          Model: GPT-5
        </div>
      </div>
    </div>
  );
};

export default DocumentCard;

