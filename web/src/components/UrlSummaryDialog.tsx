import React, { useState, useEffect } from "react";

interface UrlSummaryDialogProps {
  isOpen: boolean;
  initialUrl?: string;
  onClose: () => void;
  onSubmit: (url: string) => void;
}

const UrlSummaryDialog: React.FC<UrlSummaryDialogProps> = ({
  isOpen,
  initialUrl = "",
  onClose,
  onSubmit,
}) => {
  const [url, setUrl] = useState(initialUrl);

  // Reset form when dialog opens/closes
  useEffect(() => {
    if (isOpen) {
      setUrl(initialUrl);
    }
  }, [isOpen, initialUrl]);

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;
    onSubmit(url.trim());
    onClose();
  };

  const handleCancel = () => {
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-md rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)] p-4 shadow-xl transition-colors">
        <h2 className="text-sm font-medium text-[var(--text-primary)] mb-2">
          Enter URL to summarize (web page or video):
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <input
            autoFocus
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="w-full rounded-lg bg-[var(--bg-primary)] border border-[var(--border-color)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none transition-colors"
            style={{ 
              boxShadow: '0 0 0 1px var(--user-bubble-bg)'
            } as React.CSSProperties}
            onFocus={(e) => {
              e.currentTarget.style.boxShadow = '0 0 0 1px var(--user-bubble-bg)';
            }}
            onBlur={(e) => {
              e.currentTarget.style.boxShadow = '';
            }}
            placeholder="https://example.com or https://www.youtube.com/..."
          />

          <div className="flex items-center justify-end mt-2">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleCancel}
                className="px-3 py-1 rounded-lg text-xs text-[var(--text-primary)] bg-transparent border border-[var(--border-color)] hover:bg-[var(--bg-primary)] transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-3 py-1 rounded-lg text-xs text-[var(--user-bubble-text)] transition-colors"
                style={{ backgroundColor: 'var(--user-bubble-bg)' }}
                onMouseEnter={(e) => {
                  const bg = getComputedStyle(document.documentElement).getPropertyValue('--user-bubble-bg').trim();
                  e.currentTarget.style.opacity = '0.9';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.opacity = '1';
                }}
              >
                OK
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};

export default UrlSummaryDialog;

