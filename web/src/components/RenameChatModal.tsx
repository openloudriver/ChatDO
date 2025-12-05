import React, { useState, useEffect, useRef } from 'react';
import { useTheme } from '../contexts/ThemeContext';

type RenameChatModalProps = {
  isOpen: boolean;
  currentTitle: string;
  onClose: () => void;
  onRename: (newTitle: string) => Promise<void>;
};

const RenameChatModal: React.FC<RenameChatModalProps> = ({
  isOpen,
  currentTitle,
  onClose,
  onRename,
}) => {
  const { theme } = useTheme();
  const [newTitle, setNewTitle] = useState(currentTitle);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset form when modal opens/closes or currentTitle changes
  useEffect(() => {
    if (isOpen) {
      setNewTitle(currentTitle);
      setError(null);
      // Auto-focus input when modal opens
      setTimeout(() => {
        inputRef.current?.focus();
        inputRef.current?.select();
      }, 100);
    }
  }, [isOpen, currentTitle]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!newTitle.trim()) {
      setError('Chat title cannot be empty');
      return;
    }

    if (newTitle.trim() === currentTitle) {
      onClose();
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      await onRename(newTitle.trim());
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to rename chat. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleClose = () => {
    if (!isLoading) {
      setNewTitle(currentTitle);
      setError(null);
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg w-full max-w-md p-6 transition-colors">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-[var(--text-primary)]">Rename Chat</h2>
          <button
            onClick={handleClose}
            disabled={isLoading}
            className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-50 transition-colors"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--text-primary)] mb-2">
              Chat title
            </label>
            <input
              ref={inputRef}
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="Enter chat title"
              disabled={isLoading}
              className="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] placeholder-[var(--text-secondary)] focus:outline-none focus:border-[var(--text-secondary)] disabled:opacity-50 transition-colors"
            />
          </div>

          {error && (
            <div className="p-3 bg-red-500/20 border border-red-500/30 rounded text-sm text-red-400">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-3 pt-4">
            <button
              type="button"
              onClick={handleClose}
              disabled={isLoading}
              className="px-4 py-2 text-sm bg-[var(--border-color)] hover:bg-[var(--bg-tertiary)] disabled:opacity-50 disabled:cursor-not-allowed text-[var(--text-primary)] rounded transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading || !newTitle.trim() || newTitle.trim() === currentTitle}
              className="px-4 py-2 text-sm rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ 
                backgroundColor: 'var(--user-bubble-bg)',
                color: 'var(--user-bubble-text)'
              }}
              onMouseEnter={(e) => {
                if (!isLoading && newTitle.trim() && newTitle.trim() !== currentTitle) {
                  e.currentTarget.style.opacity = '0.9';
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.opacity = '';
              }}
            >
              {isLoading ? 'Renaming...' : 'Rename'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default RenameChatModal;

