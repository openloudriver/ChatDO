import React, { useEffect, useState } from 'react';
import axios from 'axios';
import AddMemoryModal from './AddMemoryModal';
import ConfirmDeleteMemoryModal from './ConfirmDeleteMemoryModal';

interface Source {
  id: string;
  display_name: string;
  root_path: string;
  status: 'idle' | 'indexing' | 'error' | 'disabled';
  files_indexed: number;
  bytes_indexed: number;
  last_index_started_at: string | null;
  last_index_completed_at: string | null;
  last_error: string | null;
  project_id: string | null;  // Legacy field, kept for backward compatibility
  connected_projects?: string[];  // New: list of project names this source is connected to
  latest_job: {
    id: number;
    status: string;
    files_total: number | null;
    files_processed: number;
    bytes_processed: number;
    started_at: string;
    completed_at: string | null;
    error: string | null;
  } | null;
}

const MemoryDashboard: React.FC = () => {
  const [sources, setSources] = useState<Source[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{
    sourceId: string;
    displayName: string;
  } | null>(null);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);

  const fetchSources = async () => {
    try {
      const response = await axios.get('http://127.0.0.1:5858/sources', {
        timeout: 30000, // 30 second timeout (indexing can be slow)
      });
      setSources(response.data.sources || []);
      setError(null);
      
      // Check if any source is indexing
      const hasIndexing = response.data.sources?.some(
        (s: Source) => s.status === 'indexing' || s.latest_job?.status === 'running'
      );
      setIsPolling(hasIndexing);
    } catch (err: any) {
      console.error('Error fetching memory sources:', err);
      if (err.code === 'ECONNREFUSED' || err.message?.includes('Network Error') || err.code === 'ECONNABORTED') {
        setError('Memory Service is offline – continuing without index status.');
      } else {
        setError(`Error loading sources: ${err.message || 'Unknown error'}`);
      }
      setIsPolling(false);
      setSources([]); // Clear sources on error
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchSources();
  }, []);

  useEffect(() => {
    // Always poll - either for indexing progress or to detect when service comes back online
    const pollInterval = isPolling ? 3000 : 5000; // Poll every 3 seconds when indexing, 5 seconds when idle/offline
    
    const interval = setInterval(() => {
      fetchSources();
    }, pollInterval);

    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPolling]);

  const handleReindex = async (sourceId: string) => {
    try {
      await axios.post('http://127.0.0.1:5858/reindex', { source_id: sourceId }, {
        timeout: 10000, // 10 second timeout for reindex trigger
      });
      setIsPolling(true);
      // Refresh immediately
      setTimeout(() => fetchSources(), 500);
    } catch (err: any) {
      console.error('Error triggering reindex:', err);
      alert(`Failed to trigger reindex: ${err.message || 'Unknown error'}`);
    }
  };

  const handleDeleteClick = (sourceId: string, displayName: string) => {
    setDeleteTarget({
      sourceId,
      displayName,
    });
    setDeleteModalOpen(true);
  };


  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
  };

  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return 'Never';
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  const getStatusColor = (status: string): string => {
    switch (status) {
      case 'idle':
        return 'bg-green-500/20 text-green-400 border-green-500/30';
      case 'indexing':
        return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
      case 'error':
        return 'bg-red-500/20 text-red-400 border-red-500/30';
      case 'disabled':
        return 'bg-gray-500/20 text-gray-400 border-gray-500/30';
      default:
        return 'bg-gray-500/20 text-gray-400 border-gray-500/30';
    }
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center bg-[var(--bg-primary)] transition-colors">
        <div className="text-[var(--text-secondary)]">Loading memory sources...</div>
      </div>
    );
  }

  const loadSources = () => {
    fetchSources();
  };

  return (
    <div className="flex-1 overflow-y-auto bg-[var(--bg-primary)] p-6 transition-colors">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-semibold text-[var(--text-primary)]">Memory Dashboard</h1>
          <button
            onClick={() => setIsAddModalOpen(true)}
            className="px-3 py-1.5 text-sm bg-[var(--border-color)] hover:bg-[var(--bg-tertiary)] text-[var(--text-primary)] rounded transition-colors"
          >
            Add memory…
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-yellow-500/20 border border-yellow-500/30 rounded-lg text-yellow-400 text-sm">
            {error}
          </div>
        )}

        {sources.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-[var(--text-secondary)] text-lg">No sources configured</p>
            <p className="text-[var(--text-secondary)] text-sm mt-2">
              Add sources in config/memory_sources.yaml
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {sources.map((source) => {
              // Progress should be based on files_processed vs files_total, but cap at 100%
              // If files_processed > files_total, it means we found more files than expected
              const progress = source.latest_job?.files_total && source.latest_job.files_total > 0
                ? Math.min(100, (source.latest_job.files_processed / source.latest_job.files_total) * 100)
                : null;

              return (
                <div
                  key={source.id}
                  className="bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-4 transition-colors"
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-2">
                        <h3 className="text-lg font-medium text-[var(--text-primary)]">
                          {source.display_name}
                        </h3>
                        <span
                          className={`px-2 py-1 text-xs font-medium rounded border ${getStatusColor(
                            source.status
                          )}`}
                        >
                          {source.status}
                        </span>
                      </div>
                      <p className="text-sm text-[var(--text-secondary)] font-mono">
                        {source.root_path}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleReindex(source.id)}
                        disabled={source.status === 'indexing'}
                        className="px-3 py-1.5 text-sm bg-[var(--border-color)] hover:bg-[var(--bg-tertiary)] disabled:opacity-50 disabled:cursor-not-allowed text-[var(--text-primary)] rounded transition-colors"
                      >
                        Reindex
                      </button>
                      <button
                        onClick={() => handleDeleteClick(source.id, source.display_name)}
                        disabled={source.status === 'indexing'}
                        className="px-3 py-1.5 text-sm bg-red-600 hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded transition-colors"
                      >
                        Delete
                      </button>
                    </div>
                  </div>

                  {source.latest_job && (
                    <div className="mb-3">
                      {source.latest_job.status === 'running' && (
                        <div>
                          <div className="flex justify-between text-sm text-[var(--text-secondary)] mb-1">
                            <span>
                              Processing {source.latest_job.files_processed}
                              {source.latest_job.files_total
                                ? ` / ${source.latest_job.files_total}`
                                : ''}{' '}
                              files
                            </span>
                            {progress !== null && (
                              <span>{Math.round(progress)}%</span>
                            )}
                          </div>
                          <div className="w-full bg-[var(--bg-primary)] rounded-full h-2 transition-colors">
                            <div
                              className={`h-2 rounded-full transition-all ${
                                progress !== null
                                  ? 'bg-blue-500'
                                  : 'bg-blue-500 animate-pulse'
                              }`}
                              style={{
                                width:
                                  progress !== null
                                    ? `${progress}%`
                                    : '50%',
                              }}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                      <div className="text-[var(--text-secondary)] mb-1">Files</div>
                      <div className="text-[var(--text-primary)] font-medium">
                        {source.files_indexed.toLocaleString()}
                      </div>
                    </div>
                    <div>
                      <div className="text-[var(--text-secondary)] mb-1">Size</div>
                      <div className="text-white font-medium">
                        {formatBytes(source.bytes_indexed)}
                      </div>
                    </div>
                    <div>
                      <div className="text-[var(--text-secondary)] mb-1">Last Index</div>
                      <div className="text-white font-medium">
                        {formatDate(source.last_index_completed_at)}
                      </div>
                    </div>
                    <div>
                      <div className="text-[var(--text-secondary)] mb-1">Connected Projects</div>
                      <div className="text-white font-medium">
                        {source.connected_projects && source.connected_projects.length > 0
                          ? source.connected_projects.join(', ')
                          : source.project_id === 'scratch' 
                            ? 'None (scratch)' 
                            : 'None'}
                      </div>
                    </div>
                  </div>

                  {source.last_error && (
                    <div className="mt-3 p-2 bg-red-500/10 border border-red-500/30 rounded text-sm text-red-400">
                      <div className="font-medium mb-1">Last Error:</div>
                      <div className="text-xs font-mono truncate" title={source.last_error}>
                        {source.last_error}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <AddMemoryModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onAdded={fetchSources}
      />

      <ConfirmDeleteMemoryModal
        open={deleteModalOpen}
        sourceId={deleteTarget?.sourceId ?? null}
        displayName={deleteTarget?.displayName ?? null}
        onClose={() => {
          setDeleteModalOpen(false);
          setDeleteTarget(null);
        }}
        onDeleted={() => {
          // After a successful delete, refresh the source list
          fetchSources();
        }}
      />
    </div>
  );
};

export default MemoryDashboard;

