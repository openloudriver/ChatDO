import React, { useState, useMemo } from 'react';
import { useChatStore } from '../store/chat';
import type { DiscoveryHit, DiscoveryResponse } from '../api/discovery';
import { navigateToMessage } from '../utils/messageDeepLink';
import axios from 'axios';

type DomainTab = 'all' | 'facts' | 'index' | 'files';

// Helper to format date
const formatDate = (date: Date | string): string => {
  const d = typeof date === 'string' ? new Date(date) : date;
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  
  if (diffDays === 0) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return `${diffDays} days ago`;
  if (diffDays < 30) {
    const weeks = Math.floor(diffDays / 7);
    return `${weeks} week${weeks > 1 ? 's' : ''} ago`;
  }
  
  const month = d.toLocaleDateString('en-US', { month: 'short' });
  const day = d.getDate();
  return `${month} ${day}`;
};

// Get domain badge color
const getDomainBadgeColor = (domain: string): string => {
  switch (domain) {
    case 'facts':
      return 'bg-blue-500/20 text-blue-600';
    case 'index':
      return 'bg-purple-500/20 text-purple-600';
    case 'files':
      return 'bg-green-500/20 text-green-600';
    default:
      return 'bg-gray-500/20 text-gray-600';
  }
};

// Get domain display name
const getDomainName = (domain: string): string => {
  switch (domain) {
    case 'facts':
      return 'Facts';
    case 'index':
      return 'Index';
    case 'files':
      return 'Files';
    default:
      return domain;
  }
};

// File viewer modal component
const FileViewerModal: React.FC<{
  isOpen: boolean;
  onClose: () => void;
  filePath: string;
  fileId?: string;
}> = ({ isOpen, onClose, filePath, fileId }) => {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  React.useEffect(() => {
    if (isOpen && filePath) {
      setLoading(true);
      setError(null);
      // Try to fetch file content from backend
      fetch(`http://localhost:8000/api/files/content?path=${encodeURIComponent(filePath)}`)
        .then(res => {
          if (!res.ok) throw new Error('Failed to load file');
          return res.text();
        })
        .then(text => {
          setContent(text);
          setLoading(false);
        })
        .catch(err => {
          setError(err.message || 'Failed to load file content');
          setLoading(false);
        });
    }
  }, [isOpen, filePath]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div 
        className="w-full max-w-4xl max-h-[80vh] rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)] shadow-xl transition-colors flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-[var(--border-color)] flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[var(--text-primary)] truncate">
            {filePath}
          </h2>
          <button
            onClick={onClose}
            className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            ✕
          </button>
        </div>
        <div className="flex-1 overflow-auto p-6">
          {loading && (
            <div className="text-center py-8 text-[var(--text-secondary)]">
              Loading file content...
            </div>
          )}
          {error && (
            <div className="text-center py-8 text-red-500">
              {error}
            </div>
          )}
          {content && (
            <pre className="text-sm text-[var(--text-primary)] whitespace-pre-wrap font-mono">
              {content}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
};

const SearchResults: React.FC = () => {
  const {
    discoveryResults,
    discoveryLoading,
    searchQuery,
    currentProject,
    setCurrentConversation,
    setViewMode,
    projects
  } = useChatStore();

  const [activeTab, setActiveTab] = useState<DomainTab>('all');
  const [fileViewer, setFileViewer] = useState<{ isOpen: boolean; filePath: string; fileId?: string }>({
    isOpen: false,
    filePath: '',
  });

  // Group hits by domain
  const groupedHits = useMemo(() => {
    if (!discoveryResults) return { facts: [], index: [], files: [] };
    
    const grouped: Record<string, DiscoveryHit[]> = {
      facts: [],
      index: [],
      files: [],
    };
    
    discoveryResults.hits.forEach(hit => {
      if (hit.domain in grouped) {
        grouped[hit.domain].push(hit);
      }
    });
    
    return grouped;
  }, [discoveryResults]);

  // Get hits for current tab
  const displayHits = useMemo(() => {
    if (!discoveryResults) return [];
    
    if (activeTab === 'all') {
      // Merge all hits, sorted by rank (if available) or score
      return [...discoveryResults.hits].sort((a, b) => {
        if (a.rank !== undefined && b.rank !== undefined) {
          return a.rank - b.rank;
        }
        if (a.score !== undefined && b.score !== undefined) {
          return b.score - a.score;
        }
        return 0;
      });
    }
    
    return groupedHits[activeTab] || [];
  }, [discoveryResults, activeTab, groupedHits]);

  // Handle click on a hit
  const handleHitClick = async (hit: DiscoveryHit) => {
    const source = hit.sources[0]; // Use first source for navigation
    
    if (!source) return;
    
    if (source.kind === 'chat_message' && source.source_message_uuid) {
      // Navigate to chat message
      try {
        // First, we need to load the chat if we have chat_id
        if (source.source_chat_id) {
          const chatResponse = await axios.get(`http://localhost:8000/api/chats/${source.source_chat_id}`);
          const chat = chatResponse.data;
          
          // Find the project
          const project = projects.find(p => p.id === chat.project_id);
          if (project) {
            // Set current project and conversation
            const { setCurrentProject } = useChatStore.getState();
            setCurrentProject(project);
            
            // Load conversation
            await setCurrentConversation({
              id: chat.id,
              title: chat.title,
              messages: [],
              projectId: chat.project_id,
              targetName: project.default_target || 'general',
              createdAt: new Date(chat.created_at),
              updatedAt: chat.updated_at,
              trashed: chat.trashed || false,
              trashed_at: chat.trashed_at,
              archived: chat.archived || false,
              archived_at: chat.archived_at,
              thread_id: chat.thread_id,
            });
            
            // Switch to chat view
            setViewMode('chat');
            
            // Wait a bit for messages to load, then navigate to message
            setTimeout(() => {
              navigateToMessage(source.source_message_uuid!, {
                updateUrl: true,
                timeout: 10000,
              }).catch(err => {
                console.error('Failed to navigate to message:', err);
              });
            }, 500);
          }
        } else {
          // Fallback: just try to navigate (might work if chat is already loaded)
          navigateToMessage(source.source_message_uuid, {
            updateUrl: true,
            timeout: 10000,
          }).catch(err => {
            console.error('Failed to navigate to message:', err);
          });
        }
      } catch (error) {
        console.error('Failed to navigate to chat message:', error);
      }
    } else if (source.kind === 'file' && (source.source_file_path || source.source_file_id)) {
      // Open file viewer
      setFileViewer({
        isOpen: true,
        filePath: source.source_file_path || source.source_file_id || '',
        fileId: source.source_file_id,
      });
    }
  };

  // Get domain counts
  const domainCounts = useMemo(() => {
    if (!discoveryResults) return { facts: 0, index: 0, files: 0 };
    return {
      facts: groupedHits.facts.length,
      index: groupedHits.index.length,
      files: groupedHits.files.length,
    };
  }, [discoveryResults, groupedHits]);

  // Check for degraded status
  const degradedDomains = useMemo(() => {
    if (!discoveryResults || !discoveryResults.degraded) return [];
    return Object.keys(discoveryResults.degraded);
  }, [discoveryResults]);

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--bg-primary)] transition-colors">
      {/* Header */}
      <div className="px-6 py-4 border-b border-[var(--border-color)] transition-colors">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-xl font-semibold text-[var(--text-primary)]">
            Search Results
          </h2>
          {degradedDomains.length > 0 && (
            <div className="flex items-center gap-2">
              {degradedDomains.map(domain => (
                <span
                  key={domain}
                  className="text-xs px-2 py-1 rounded bg-yellow-500/20 text-yellow-600"
                  title={discoveryResults?.degraded[domain] || 'Degraded'}
                >
                  {getDomainName(domain)} degraded
                </span>
              ))}
            </div>
          )}
        </div>
        <p className="text-sm text-[var(--text-secondary)]">
          {discoveryLoading ? (
            'Searching...'
          ) : discoveryResults ? (
            `${discoveryResults.hits.length} result${discoveryResults.hits.length !== 1 ? 's' : ''} for "${searchQuery}"`
          ) : (
            `No results for "${searchQuery}"`
          )}
        </p>
      </div>

      {/* Domain Tabs */}
      {discoveryResults && (
        <div className="px-6 py-2 border-b border-[var(--border-color)] flex gap-2">
          <button
            onClick={() => setActiveTab('all')}
            className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
              activeTab === 'all'
                ? 'bg-[var(--user-bubble-bg)] text-white'
                : 'bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]'
            }`}
          >
            All ({discoveryResults.hits.length})
          </button>
          <button
            onClick={() => setActiveTab('facts')}
            className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
              activeTab === 'facts'
                ? 'bg-[var(--user-bubble-bg)] text-white'
                : 'bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]'
            }`}
          >
            Facts ({domainCounts.facts})
          </button>
          <button
            onClick={() => setActiveTab('index')}
            className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
              activeTab === 'index'
                ? 'bg-[var(--user-bubble-bg)] text-white'
                : 'bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]'
            }`}
          >
            Index ({domainCounts.index})
          </button>
          <button
            onClick={() => setActiveTab('files')}
            className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
              activeTab === 'files'
                ? 'bg-[var(--user-bubble-bg)] text-white'
                : 'bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]'
            }`}
          >
            Files ({domainCounts.files})
          </button>
        </div>
      )}

      {/* Results List */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {discoveryLoading ? (
          <div className="text-center py-12">
            <p className="text-[var(--text-secondary)] text-sm">Searching...</p>
          </div>
        ) : !discoveryResults || displayHits.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-[var(--text-secondary)] text-sm">No results found</p>
          </div>
        ) : (
          <div className="space-y-3">
            {displayHits.map((hit) => {
              const source = hit.sources[0];
              const domainBadgeColor = getDomainBadgeColor(hit.domain);
              
              return (
                <button
                  key={hit.id}
                  onClick={() => handleHitClick(hit)}
                  className="w-full text-left p-4 rounded-lg bg-[var(--bg-tertiary)] hover:bg-[var(--assistant-bubble-bg)] border border-transparent hover:border-[var(--border-color)] transition-colors"
                >
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      {hit.title && (
                        <h3 className="font-medium text-[var(--text-primary)] truncate">
                          {hit.title}
                        </h3>
                      )}
                      <span className={`text-xs px-2 py-0.5 rounded ${domainBadgeColor} font-medium flex-shrink-0`}>
                        {getDomainName(hit.domain)}
                      </span>
                      {hit.score !== undefined && (
                        <span className="text-xs text-[var(--text-secondary)] flex-shrink-0">
                          {(hit.score * 100).toFixed(0)}%
                        </span>
                      )}
                    </div>
                    {source?.created_at && (
                      <span className="text-xs text-[var(--text-secondary)] ml-4 flex-shrink-0">
                        {formatDate(source.created_at)}
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-[var(--text-secondary)] line-clamp-3 mb-1">
                    {hit.text}
                  </p>
                  {source?.snippet && (
                    <p className="text-xs text-[var(--text-secondary)] italic line-clamp-1">
                      {source.snippet}
                    </p>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* File Viewer Modal */}
      <FileViewerModal
        isOpen={fileViewer.isOpen}
        onClose={() => setFileViewer({ isOpen: false, filePath: '' })}
        filePath={fileViewer.filePath}
        fileId={fileViewer.fileId}
      />
    </div>
  );
};

export default SearchResults;
