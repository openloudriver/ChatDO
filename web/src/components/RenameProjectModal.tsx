import React, { useState, useEffect, useRef } from 'react';
import { useTheme } from '../contexts/ThemeContext';

type RenameProjectModalProps = {
  isOpen: boolean;
  currentName: string;
  onClose: () => void;
  onRename: (newName: string) => Promise<void>;
  isCreating?: boolean;
};

const RenameProjectModal: React.FC<RenameProjectModalProps> = ({
  isOpen,
  currentName,
  onClose,
  onRename,
  isCreating = false,
}) => {
  const { theme } = useTheme();
  const [newName, setNewName] = useState(currentName);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset form when modal opens/closes or currentName changes
  useEffect(() => {
    if (isOpen) {
      setNewName(currentName);
      setError(null);
      // Auto-focus input when modal opens
      setTimeout(() => {
        inputRef.current?.focus();
        inputRef.current?.select();
      }, 100);
    }
  }, [isOpen, currentName]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!newName.trim()) {
      setError('Project name cannot be empty');
      return;
    }

    if (newName.trim() === currentName) {
      onClose();
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      await onRename(newName.trim());
      onClose();
    } catch (err: any) {
      setError(err.message || (isCreating ? 'Failed to create project. Please try again.' : 'Failed to rename project. Please try again.'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleClose = () => {
    if (!isLoading) {
      setNewName(currentName);
      setError(null);
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg w-full max-w-md p-6 transition-colors">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-[var(--text-primary)]">
            {isCreating ? 'Create Project' : 'Rename Project'}
          </h2>
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
              Project name
            </label>
            <input
              ref={inputRef}
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Enter project name"
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
              disabled={isLoading || !newName.trim() || (!isCreating && newName.trim() === currentName)}
              className="px-4 py-2 text-sm rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ 
                backgroundColor: 'var(--user-bubble-bg)',
                color: 'var(--user-bubble-text)'
              }}
              onMouseEnter={(e) => {
                if (!isLoading && newName.trim() && (isCreating || newName.trim() !== currentName)) {
                  e.currentTarget.style.opacity = '0.9';
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.opacity = '';
              }}
            >
              {isLoading ? (isCreating ? 'Creating...' : 'Renaming...') : (isCreating ? 'Create' : 'Rename')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default RenameProjectModal;

