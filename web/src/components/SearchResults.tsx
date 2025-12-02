import React from 'react';
import { useChatStore } from '../store/chat';
import type { Conversation } from '../store/chat';

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

// Get preview snippet from conversation
const getPreview = (conversation: Conversation): string => {
  if (conversation.messages && conversation.messages.length > 0) {
    const lastMessage = conversation.messages[conversation.messages.length - 1];
    const content = lastMessage.content;
    const plainText = content.replace(/[#*`_~\[\]()]/g, '').trim();
    return plainText.length > 100 ? plainText.substring(0, 100) + '...' : plainText;
  }
  return 'No messages yet';
};

const SearchResults: React.FC = () => {
  const {
    searchResults,
    searchQuery,
    currentConversation,
    setCurrentConversation,
    projects
  } = useChatStore();

  // Get Bullet Workspace project IDs to filter them out
  const bulletWorkspaceProjectIds = new Set(
    projects.filter(p => p.name === "Bullet Workspace").map(p => p.id)
  );

  // Filter out Bullet Workspace chats from search results
  const filteredResults = searchResults.filter(chat => 
    !chat.projectId || !bulletWorkspaceProjectIds.has(chat.projectId)
  );

  // Group results by project
  const resultsByProject = filteredResults.reduce((acc, chat) => {
    const projectId = chat.projectId || 'unknown';
    if (!acc[projectId]) {
      acc[projectId] = [];
    }
    acc[projectId].push(chat);
    return acc;
  }, {} as Record<string, Conversation[]>);

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--bg-primary)] transition-colors">
      {/* Header */}
      <div className="px-6 py-4 border-b border-[var(--border-color)] transition-colors">
        <h2 className="text-xl font-semibold text-[var(--text-primary)]">
          Search Results
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mt-1">
          {filteredResults.length} result{filteredResults.length !== 1 ? 's' : ''} for "{searchQuery}"
        </p>
      </div>

      {/* Results List */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {filteredResults.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-[var(--text-secondary)] text-sm">No results found</p>
          </div>
        ) : (
          <div className="space-y-6">
            {Object.entries(resultsByProject).map(([projectId, chats]) => {
              const project = projects.find(p => p.id === projectId);
              return (
                <div key={projectId} className="space-y-2">
                  {project && (
                    <h3 className="text-sm font-semibold text-[var(--text-secondary)] uppercase mb-2">
                      {project.name}
                    </h3>
                  )}
                  {chats.map((chat) => {
                    const isSelected = currentConversation?.id === chat.id;
                    return (
                      <button
                        key={chat.id}
                        onClick={() => {
                          setCurrentConversation(chat).catch(err => 
                            console.error('Failed to load conversation:', err)
                          );
                        }}
                        className={`w-full text-left p-4 rounded-lg transition-colors ${
                          isSelected
                            ? 'bg-[var(--assistant-bubble-bg)] border border-[var(--border-color)]'
                            : 'bg-[var(--bg-tertiary)] hover:bg-[var(--assistant-bubble-bg)] border border-transparent'
                        }`}
                      >
                        <div className="flex items-start justify-between mb-2">
                          <h3 className={`font-medium ${isSelected ? 'text-[var(--text-primary)]' : 'text-[var(--text-primary)]'}`}>
                            {chat.title}
                          </h3>
                          <span className="text-xs text-[var(--text-secondary)] ml-4 flex-shrink-0">
                            {formatDate(chat.createdAt)}
                          </span>
                        </div>
                        <p className="text-sm text-[var(--text-secondary)] line-clamp-2">
                          {getPreview(chat)}
                        </p>
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export default SearchResults;

