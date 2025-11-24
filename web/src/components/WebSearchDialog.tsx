import React, { useState, useEffect, useRef } from "react";

interface WebSearchDialogProps {
  isOpen: boolean;
  initialQuery?: string;
  onClose: () => void;
  onSubmit: (query: string) => void;
}

const WebSearchDialog: React.FC<WebSearchDialogProps> = ({
  isOpen,
  initialQuery = "",
  onClose,
  onSubmit,
}) => {
  const [query, setQuery] = useState(initialQuery);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset form and focus input when dialog opens
  useEffect(() => {
    if (isOpen) {
      setQuery(initialQuery);
      // Focus input after a short delay to ensure dialog is rendered
      setTimeout(() => {
        inputRef.current?.focus();
      }, 100);
    }
  }, [isOpen, initialQuery]);

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    onSubmit(query.trim());
    onClose();
  };

  const handleCancel = () => {
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-md rounded-xl bg-[#202123] border border-[#565869] p-4 shadow-xl">
        <h2 className="text-sm font-medium text-[#ececf1] mb-2">
          Search the web:
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full rounded-lg bg-[#343541] border border-[#565869] px-3 py-2 text-sm text-[#ececf1] outline-none focus:ring-1 focus:ring-[#10a37f]"
            placeholder="Enter your search query..."
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
                disabled={!query.trim()}
                className="px-3 py-1 rounded-lg text-xs text-white bg-[#10a37f] hover:bg-[#19c37d] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Search
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};

export default WebSearchDialog;

