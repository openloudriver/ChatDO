import React, { useState, useRef, useEffect } from 'react';
import { addMemorySource } from '../utils/api';
import { useTheme } from '../contexts/ThemeContext';

type AddMemoryModalProps = {
  isOpen: boolean;
  onClose: () => void;
  onAdded: () => void; // callback to refresh the dashboard
};

const AddMemoryModal: React.FC<AddMemoryModalProps> = ({
  isOpen,
  onClose,
  onAdded,
}) => {
  const { theme } = useTheme();
  const [rootPath, setRootPath] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const folderPathInputRef = useRef<HTMLInputElement>(null);

  // Auto-focus the folder path input when modal opens
  useEffect(() => {
    if (isOpen && folderPathInputRef.current) {
      // Small delay to ensure modal is fully rendered
      setTimeout(() => {
        folderPathInputRef.current?.focus();
      }, 100);
    }
  }, [isOpen]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!rootPath.trim()) {
      setError('Folder path is required');
      return;
    }

    setIsLoading(true);
    setError(null);
    setSuccess(false);

    try {
      await addMemorySource({
        rootPath: rootPath.trim(),
        displayName: displayName.trim() || undefined,
      });
      
      setSuccess(true);
      // Refresh dashboard after a brief delay
      setTimeout(() => {
        onAdded();
        onClose();
        // Reset form
        setRootPath('');
        setDisplayName('');
        setSuccess(false);
      }, 1000);
    } catch (err: any) {
      setError(err.message || 'Failed to add memory source');
    } finally {
      setIsLoading(false);
    }
  };

  const handleClose = () => {
    if (!isLoading) {
      setRootPath('');
      setDisplayName('');
      setError(null);
      setSuccess(false);
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg w-full max-w-lg p-6 transition-colors">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-[var(--text-primary)]">Add memory source</h2>
          <button
            onClick={handleClose}
            disabled={isLoading}
            className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-50 transition-colors"
          >
            ✕
          </button>
        </div>

        <p className="text-sm text-[var(--text-secondary)] mb-4">
          Paste a folder path and I'll index it. Example: /Volumes/iCPWeeaPWBXs/Downloads
        </p>
        <p className="text-xs text-[#8e8ea0] mb-4">
          You can connect it to a project later via right-click → "Connect project…"
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--text-primary)] mb-2">
              Folder path <span className="text-red-400">*</span>
            </label>
            <input
              ref={folderPathInputRef}
              type="text"
              value={rootPath}
              onChange={(e) => setRootPath(e.target.value)}
              placeholder="/path/to/folder"
              disabled={isLoading}
              className="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] placeholder-[var(--text-secondary)] focus:outline-none focus:border-[var(--text-secondary)] disabled:opacity-50 transition-colors"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--text-primary)] mb-2">
              Display name <span className="text-[var(--text-secondary)] text-xs">(optional)</span>
            </label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Downloads"
              disabled={isLoading}
              className="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] placeholder-[var(--text-secondary)] focus:outline-none focus:border-[var(--text-secondary)] disabled:opacity-50 transition-colors"
            />
          </div>

          {error && (
            <div className="p-3 bg-red-500/20 border border-red-500/30 rounded text-sm text-red-400">
              {error}
            </div>
          )}

          {success && (
            <div className="p-3 bg-green-500/20 border border-green-500/30 rounded text-sm text-green-400">
              Indexing started… The new source will appear on the dashboard shortly.
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
              disabled={isLoading || !rootPath.trim()}
              className="px-4 py-2 text-sm rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ 
                backgroundColor: 'var(--user-bubble-bg)',
                color: 'var(--user-bubble-text)'
              }}
              onMouseEnter={(e) => {
                if (!isLoading && rootPath.trim()) {
                  e.currentTarget.style.opacity = '0.9';
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.opacity = '';
              }}
            >
              {isLoading ? 'Adding...' : 'Add'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default AddMemoryModal;

