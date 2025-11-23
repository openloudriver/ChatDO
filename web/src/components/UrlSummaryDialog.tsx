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
      <div className="w-full max-w-md rounded-xl bg-[#202123] border border-[#565869] p-4 shadow-xl">
        <h2 className="text-sm font-medium text-[#ececf1] mb-2">
          Enter URL to summarize (web page or video):
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <input
            autoFocus
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="w-full rounded-lg bg-[#343541] border border-[#565869] px-3 py-2 text-sm text-[#ececf1] outline-none focus:ring-1 focus:ring-[#10a37f]"
            placeholder="https://example.com or https://www.youtube.com/..."
          />

          <div className="flex items-center justify-end mt-2">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleCancel}
                className="px-3 py-1 rounded-lg text-xs text-[#ececf1] bg-transparent border border-[#565869] hover:bg-[#343541]"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-3 py-1 rounded-lg text-xs text-white bg-[#10a37f] hover:bg-[#19c37d]"
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

