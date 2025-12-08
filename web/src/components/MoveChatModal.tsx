import React, { useEffect, useState, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useChatStore } from '../store/chat';
import { moveChat } from '../utils/api';

interface MoveChatModalProps {
  open: boolean;
  chatId: string;
  currentProjectId: string;
  onClose: () => void;
  onMoved?: (newProjectId: string) => void;
}

const MoveChatModal: React.FC<MoveChatModalProps> = ({
  open,
  chatId,
  currentProjectId,
  onClose,
  onMoved,
}) => {
  const { projects, loadProjects } = useChatStore();
  const [selectedProjectId, setSelectedProjectId] = useState<string>(currentProjectId);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(false);

  useEffect(() => {
    if (open && !mountedRef.current) {
      mountedRef.current = true;
      // Load projects if not already loaded
      loadProjects();
      // Reset to current project when modal opens
      setSelectedProjectId(currentProjectId);
      setError(null);
    } else if (!open) {
      mountedRef.current = false;
    }
  }, [open, currentProjectId, loadProjects]);

  // Filter out trashed projects and Bullet Workspace (sandboxed environment)
  const availableProjects = projects.filter(p => !p.trashed && p.name !== "Bullet Workspace");

  const handleMove = async () => {
    if (!selectedProjectId || selectedProjectId === currentProjectId) {
      onClose();
      return;
    }

    setIsSaving(true);
    setError(null);
    try {
      await moveChat(chatId, selectedProjectId);
      if (onMoved) {
        onMoved(selectedProjectId);
      }
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to move chat');
    } finally {
      setIsSaving(false);
    }
  };

  if (!open || !mountedRef.current) return null;

  const modalContent = (
    <div 
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" 
      onClick={(e) => {
        // Close modal when clicking backdrop
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg w-full max-w-2xl max-h-[80vh] flex flex-col transition-colors">
        {/* Header */}
        <div className="p-4 border-b border-[var(--border-color)] transition-colors">
          <h2 className="text-xl font-semibold text-[var(--text-primary)]">Move chat to project</h2>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            Choose which project this chat belongs to.
          </p>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          {isLoading ? (
            <div className="text-center py-8 text-[var(--text-secondary)]">Loading projects...</div>
          ) : error ? (
            <div className="text-center py-8 text-red-400">{error}</div>
          ) : availableProjects.length === 0 ? (
            <div className="text-center py-8 text-[var(--text-secondary)]">
              <p>No projects available.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {availableProjects.map((project) => (
                <label
                  key={project.id}
                  className="flex items-start gap-3 p-3 rounded-lg hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
                >
                  <input
                    type="radio"
                    name="project"
                    value={project.id}
                    checked={selectedProjectId === project.id}
                    onChange={(e) => setSelectedProjectId(e.target.value)}
                    className="mt-1 w-4 h-4 border-[var(--border-color)] bg-[var(--bg-secondary)] text-blue-500 focus:ring-blue-500 focus:ring-2 transition-colors"
                  />
                  <div className="flex-1">
                    <div className="text-[var(--text-primary)] font-medium">{project.name}</div>
                  </div>
                </label>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-[var(--border-color)] flex justify-end gap-3 transition-colors">
          <button
            onClick={onClose}
            disabled={isSaving}
            className="px-4 py-2 text-sm bg-[var(--border-color)] hover:bg-[var(--bg-tertiary)] disabled:opacity-50 text-[var(--text-primary)] rounded transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleMove}
            disabled={isSaving || isLoading || selectedProjectId === currentProjectId}
            className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded transition-colors flex items-center gap-2"
          >
            {isSaving && (
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                  fill="none"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
            )}
            {isSaving ? 'Moving...' : 'Move'}
          </button>
        </div>
      </div>
    </div>
  );

  // Use portal to render at document body level to avoid nesting issues
  return createPortal(modalContent, document.body);
};

export default MoveChatModal;

