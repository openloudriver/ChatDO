import React from "react";
import { AssistantCard } from "./shared/AssistantCard";

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
    case 'xls':
    case 'xlsx':
      return (
        <svg className="w-6 h-6 text-green-400" fill="currentColor" viewBox="0 0 24 24">
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
  const readTime = estimatedReadTimeMinutes || estimateReadTime(summary, keyPoints, whyMatters, wordCount);

  return (
    <AssistantCard>
      {/* Header Row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 flex-1 min-w-0">
          {getFileIcon(fileName)}
          <div className="text-xs uppercase tracking-wide text-[#8e8ea0] font-medium">
            Document
          </div>
        </div>
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
            <h3 className="text-base font-semibold text-[#8e8ea0] mb-2 uppercase tracking-wide">
              Summary
            </h3>
            <p className="text-sm text-[#ececf1] leading-relaxed">{summary}</p>
          </div>
        )}
        
        {/* Key points */}
        {keyPoints && keyPoints.length > 0 && (
          <div>
            <h3 className="text-base font-semibold text-[#8e8ea0] mb-2 uppercase tracking-wide">
              Key Points
            </h3>
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
            <h3 className="text-base font-semibold text-[#8e8ea0] mb-2 uppercase tracking-wide">
              Why This Matters
            </h3>
            <p className="text-sm text-[#ececf1] leading-relaxed">{whyMatters}</p>
          </div>
        )}
      </div>
    </AssistantCard>
  );
};

export default DocumentCard;

