import React, { useEffect, useState } from 'react';
import axios from 'axios';

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
  project_id: string | null;
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

  const fetchSources = async () => {
    try {
      const response = await axios.get('http://127.0.0.1:5858/sources');
      setSources(response.data.sources || []);
      setError(null);
      
      // Check if any source is indexing
      const hasIndexing = response.data.sources?.some(
        (s: Source) => s.status === 'indexing' || s.latest_job?.status === 'running'
      );
      setIsPolling(hasIndexing);
    } catch (err: any) {
      if (err.code === 'ECONNREFUSED' || err.message?.includes('Network Error')) {
        setError('Memory Service is offline – continuing without index status.');
      } else {
        setError(`Error loading sources: ${err.message}`);
      }
      setIsPolling(false);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchSources();
  }, []);

  useEffect(() => {
    if (!isPolling) return;

    const interval = setInterval(() => {
      fetchSources();
    }, 3000); // Poll every 3 seconds when indexing

    return () => clearInterval(interval);
  }, [isPolling]);

  const handleReindex = async (sourceId: string) => {
    try {
      await axios.post('http://127.0.0.1:5858/reindex', { source_id: sourceId });
      setIsPolling(true);
      // Refresh immediately
      setTimeout(() => fetchSources(), 500);
    } catch (err: any) {
      alert(`Failed to trigger reindex: ${err.message}`);
    }
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
      <div className="flex-1 flex items-center justify-center bg-[#343541]">
        <div className="text-[#8e8ea0]">Loading memory sources...</div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto bg-[#343541] p-6">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-2xl font-semibold text-white mb-6">Memory Dashboard</h1>

        {error && (
          <div className="mb-4 p-3 bg-yellow-500/20 border border-yellow-500/30 rounded-lg text-yellow-400 text-sm">
            {error}
          </div>
        )}

        {sources.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-[#8e8ea0] text-lg">No sources configured</p>
            <p className="text-[#8e8ea0] text-sm mt-2">
              Add sources in config/memory_sources.yaml
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {sources.map((source) => {
              const progress = source.latest_job?.files_total
                ? (source.latest_job.files_processed / source.latest_job.files_total) * 100
                : null;

              return (
                <div
                  key={source.id}
                  className="bg-[#40414f] border border-[#565869] rounded-lg p-4"
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-2">
                        <h3 className="text-lg font-medium text-white">
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
                      <p className="text-sm text-[#8e8ea0] font-mono">
                        {source.root_path}
                      </p>
                    </div>
                    <button
                      onClick={() => handleReindex(source.id)}
                      disabled={source.status === 'indexing'}
                      className="px-3 py-1.5 text-sm bg-[#565869] hover:bg-[#6e6f7f] disabled:opacity-50 disabled:cursor-not-allowed text-white rounded transition-colors"
                    >
                      Reindex
                    </button>
                  </div>

                  {source.latest_job && (
                    <div className="mb-3">
                      {source.latest_job.status === 'running' && (
                        <div>
                          <div className="flex justify-between text-sm text-[#8e8ea0] mb-1">
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
                          <div className="w-full bg-[#343541] rounded-full h-2">
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
                      <div className="text-[#8e8ea0] mb-1">Files</div>
                      <div className="text-white font-medium">
                        {source.files_indexed.toLocaleString()}
                      </div>
                    </div>
                    <div>
                      <div className="text-[#8e8ea0] mb-1">Size</div>
                      <div className="text-white font-medium">
                        {formatBytes(source.bytes_indexed)}
                      </div>
                    </div>
                    <div>
                      <div className="text-[#8e8ea0] mb-1">Last Index</div>
                      <div className="text-white font-medium">
                        {formatDate(source.last_index_completed_at)}
                      </div>
                    </div>
                    <div>
                      <div className="text-[#8e8ea0] mb-1">Project</div>
                      <div className="text-white font-medium">
                        {source.project_id || 'N/A'}
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
    </div>
  );
};

export default MemoryDashboard;

