import React, { useEffect, useState } from 'react';
import { fetchProjectMemorySources, updateProjectMemorySources, fetchMemorySources } from '../utils/api';

interface Source {
  id: string;
  display_name: string;
  root_path: string;
  status: string;
}

type ConnectProjectModalProps = {
  projectId: string;
  projectName: string;
  isOpen: boolean;
  onClose: () => void;
};

const ConnectProjectModal: React.FC<ConnectProjectModalProps> = ({
  projectId,
  projectName,
  isOpen,
  onClose,
}) => {
  const [allSources, setAllSources] = useState<Source[]>([]);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    const loadData = async () => {
      setIsLoading(true);
      setError(null);
      try {
        // Load all available memory sources
        const sources = await fetchMemorySources();
        setAllSources(sources);

        // Load current project's memory sources
        const projectData = await fetchProjectMemorySources(projectId);
        setSelectedSources(projectData.memory_sources || []);
      } catch (err: any) {
        setError(err.message || 'Failed to load data');
      } finally {
        setIsLoading(false);
      }
    };

    loadData();
  }, [isOpen, projectId]);

  const handleToggleSource = (sourceId: string) => {
    setSelectedSources((prev) =>
      prev.includes(sourceId)
        ? prev.filter((id) => id !== sourceId)
        : [...prev, sourceId]
    );
  };

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);
    try {
      await updateProjectMemorySources(projectId, selectedSources);
      // Show success (could add toast here)
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to save');
    } finally {
      setIsSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg w-full max-w-2xl max-h-[80vh] flex flex-col transition-colors">
        {/* Header */}
        <div className="p-4 border-b border-[var(--border-color)] transition-colors">
          <h2 className="text-xl font-semibold text-[var(--text-primary)]">Connect project to memory</h2>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            Choose which memory sources are available to "{projectName}".
          </p>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          {isLoading ? (
            <div className="text-center py-8 text-[var(--text-secondary)]">Loading sources...</div>
          ) : error ? (
            <div className="text-center py-8 text-red-400">{error}</div>
          ) : allSources.length === 0 ? (
            <div className="text-center py-8 text-[var(--text-secondary)]">
              <p>No memory sources configured.</p>
              <p className="text-sm mt-2">Add sources in config/memory_sources.yaml</p>
            </div>
          ) : (
            <div className="space-y-2">
              {allSources.map((source) => (
                <label
                  key={source.id}
                  className="flex items-start gap-3 p-3 rounded-lg hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={selectedSources.includes(source.id)}
                    onChange={() => handleToggleSource(source.id)}
                    className="mt-1 w-4 h-4 rounded border-[var(--border-color)] bg-[var(--bg-secondary)] text-blue-500 focus:ring-blue-500 focus:ring-2 transition-colors"
                  />
                  <div className="flex-1">
                    <div className="text-[var(--text-primary)] font-medium">{source.display_name}</div>
                    <div className="text-xs text-[var(--text-secondary)] font-mono mt-1">{source.id}</div>
                    <div className="text-xs text-[var(--text-secondary)] mt-1 truncate">{source.root_path}</div>
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
            onClick={handleSave}
            disabled={isSaving || isLoading}
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
            {isSaving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConnectProjectModal;

