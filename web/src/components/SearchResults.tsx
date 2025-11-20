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

  // Group results by project
  const resultsByProject = searchResults.reduce((acc, chat) => {
    const projectId = chat.projectId || 'unknown';
    if (!acc[projectId]) {
      acc[projectId] = [];
    }
    acc[projectId].push(chat);
    return acc;
  }, {} as Record<string, Conversation[]>);

  return (
    <div className="flex-1 flex flex-col h-full bg-[#343541]">
      {/* Header */}
      <div className="px-6 py-4 border-b border-[#565869]">
        <h2 className="text-xl font-semibold text-[#ececf1]">
          Search Results
        </h2>
        <p className="text-sm text-[#8e8ea0] mt-1">
          {searchResults.length} result{searchResults.length !== 1 ? 's' : ''} for "{searchQuery}"
        </p>
      </div>

      {/* Results List */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {searchResults.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-[#8e8ea0] text-sm">No results found</p>
          </div>
        ) : (
          <div className="space-y-6">
            {Object.entries(resultsByProject).map(([projectId, chats]) => {
              const project = projects.find(p => p.id === projectId);
              return (
                <div key={projectId} className="space-y-2">
                  {project && (
                    <h3 className="text-sm font-semibold text-[#8e8ea0] uppercase mb-2">
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
                            ? 'bg-[#444654] border border-[#565869]'
                            : 'bg-[#40414f] hover:bg-[#444654] border border-transparent'
                        }`}
                      >
                        <div className="flex items-start justify-between mb-2">
                          <h3 className={`font-medium ${isSelected ? 'text-white' : 'text-[#ececf1]'}`}>
                            {chat.title}
                          </h3>
                          <span className="text-xs text-[#8e8ea0] ml-4 flex-shrink-0">
                            {formatDate(chat.createdAt)}
                          </span>
                        </div>
                        <p className="text-sm text-[#8e8ea0] line-clamp-2">
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

