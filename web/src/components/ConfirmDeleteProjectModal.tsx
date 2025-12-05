import React, { useState, useEffect } from 'react';
import { useTheme } from '../contexts/ThemeContext';

type ConfirmDeleteProjectModalProps = {
  isOpen: boolean;
  projectName: string;
  onClose: () => void;
  onConfirm: () => Promise<void>;
};

const ConfirmDeleteProjectModal: React.FC<ConfirmDeleteProjectModalProps> = ({
  isOpen,
  projectName,
  onClose,
  onConfirm,
}) => {
  const { theme } = useTheme();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      setError(null);
      setIsLoading(false);
    }
  }, [isOpen]);

  const handleConfirm = async () => {
    setIsLoading(true);
    setError(null);

    try {
      await onConfirm();
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to delete project. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleClose = () => {
    if (!isLoading) {
      setError(null);
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg w-full max-w-md p-6 transition-colors">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-[var(--text-primary)]">Delete Project</h2>
          <button
            onClick={handleClose}
            disabled={isLoading}
            className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-50 transition-colors"
          >
            ✕
          </button>
        </div>

        <div className="space-y-4">
          <p className="text-sm text-[var(--text-secondary)]">
            Delete <span className="font-semibold text-[var(--text-primary)]">"{projectName}"</span>? This will remove it from the sidebar.
          </p>

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
              type="button"
              onClick={handleConfirm}
              disabled={isLoading}
              className="px-4 py-2 text-sm rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed bg-red-600 hover:bg-red-700 text-white"
            >
              {isLoading ? 'Deleting...' : 'Delete'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ConfirmDeleteProjectModal;

