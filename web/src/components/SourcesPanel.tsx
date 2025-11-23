import React, { useState } from 'react';
import type { Source, SourceKind } from '../types/sources';

interface SourcesPanelProps {
  sources: Source[];
  onInsertReference?: (source: Source) => void;
  onOpenSource?: (source: Source) => void;
}

const getSourceIcon = (kind: SourceKind) => {
  switch (kind) {
    case 'url':
      return (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
        </svg>
      );
    case 'file':
      return (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      );
    case 'text':
      return (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" />
        </svg>
      );
    case 'note':
      return (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
        </svg>
      );
  }
};

export const SourcesPanel: React.FC<SourcesPanelProps> = ({
  sources,
  onInsertReference,
  onOpenSource,
}) => {
  const [expandedSourceId, setExpandedSourceId] = useState<string | null>(null);

  const handleSourceClick = (source: Source) => {
    if (source.url) {
      window.open(source.url, '_blank', 'noopener,noreferrer');
    } else if (onOpenSource) {
      onOpenSource(source);
    }
  };

  if (sources.length === 0) {
    return (
      <div className="p-4 text-center text-[#8e8ea0] text-sm">
        No sources yet. Sources will appear here when you summarize URLs or upload files.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {sources.map((source) => (
        <div
          key={source.id}
          className="p-3 bg-[#1a1a1a] border border-[#565869] rounded-lg hover:bg-[#252525] transition-colors"
        >
          <div className="flex items-start gap-3">
            <div className="text-[#8e8ea0] flex-shrink-0 mt-0.5">
              {getSourceIcon(source.kind)}
            </div>
            <div className="flex-1 min-w-0">
              <div
                className="font-medium text-[#ececf1] cursor-pointer hover:text-white transition-colors"
                onClick={() => handleSourceClick(source)}
                title={source.url || source.fileName || 'Click to open'}
              >
                {source.title}
              </div>
              {source.description && (
                <div className="text-sm text-[#8e8ea0] mt-1 line-clamp-2">
                  {source.description}
                </div>
              )}
              <div className="flex items-center gap-2 mt-2">
                {source.url && (
                  <span className="text-xs text-[#8e8ea0] truncate">
                    {new URL(source.url).hostname.replace(/^www\./, '')}
                  </span>
                )}
                {source.fileName && (
                  <span className="text-xs text-[#8e8ea0] truncate">
                    {source.fileName}
                  </span>
                )}
                {onInsertReference && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onInsertReference(source);
                    }}
                    className="text-xs text-blue-400 hover:text-blue-300 transition-colors ml-auto"
                    title="Insert reference into composer"
                  >
                    Insert reference
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
};

export default SourcesPanel;

