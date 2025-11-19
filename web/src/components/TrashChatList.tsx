import React, { useEffect } from 'react';
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
  
  // Format as "Nov 18" or "Dec 5"
  const month = d.toLocaleDateString('en-US', { month: 'short' });
  const day = d.getDate();
  return `${month} ${day}`;
};

// Get preview snippet from conversation
const getPreview = (conversation: Conversation): string => {
  if (conversation.messages && conversation.messages.length > 0) {
    const lastMessage = conversation.messages[conversation.messages.length - 1];
    const content = lastMessage.content;
    // Strip markdown and get first 100 chars
    const plainText = content.replace(/[#*`_~\[\]()]/g, '').trim();
    return plainText.length > 100 ? plainText.substring(0, 100) + '...' : plainText;
  }
  return 'No messages yet';
};

const TrashChatList: React.FC = () => {
  const {
    trashedChats,
    currentConversation,
    setCurrentConversation,
    projects,
    restoreChat,
    purgeChat,
    loadTrashedChats
  } = useChatStore();

  // Load trashed chats when component mounts
  useEffect(() => {
    loadTrashedChats();
  }, [loadTrashedChats]);

  const handleRestore = async (e: React.MouseEvent, chatId: string) => {
    e.stopPropagation();
    try {
      await restoreChat(chatId);
    } catch (error) {
      console.error('Failed to restore chat:', error);
    }
  };

  const handlePurge = async (e: React.MouseEvent, chatId: string) => {
    e.stopPropagation();
    if (window.confirm('Are you sure you want to permanently delete this chat? This cannot be undone.')) {
      try {
        await purgeChat(chatId);
      } catch (error) {
        console.error('Failed to purge chat:', error);
      }
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[#343541]">
      {/* Header */}
      <div className="px-6 py-4 border-b border-[#565869]">
        <h2 className="text-xl font-semibold text-[#ececf1]">Trash</h2>
        <p className="text-sm text-[#8e8ea0] mt-1">Deleted chats are kept for 30 days</p>
      </div>

      {/* Chat List */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {trashedChats.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-[#8e8ea0] text-sm">Trash is empty</p>
          </div>
        ) : (
          <div className="space-y-2">
            {trashedChats.map((chat) => {
              const isSelected = currentConversation?.id === chat.id;
              const project = projects.find(p => p.id === chat.projectId);
              const updatedDate = chat.trashed_at ? new Date(chat.trashed_at) : chat.createdAt;
              
              return (
                <div
                  key={chat.id}
                  className={`w-full p-4 rounded-lg transition-colors ${
                    isSelected
                      ? 'bg-[#444654] border border-[#565869]'
                      : 'bg-[#40414f] hover:bg-[#444654] border border-transparent'
                  }`}
                >
                  <button
                    onClick={() => setCurrentConversation(chat)}
                    className="w-full text-left"
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex-1">
                        <h3 className={`font-medium ${isSelected ? 'text-white' : 'text-[#ececf1]'}`}>
                          {chat.title}
                        </h3>
                        {project && (
                          <p className="text-xs text-[#8e8ea0] mt-1">
                            From: {project.name}
                          </p>
                        )}
                      </div>
                      <span className="text-xs text-[#8e8ea0] ml-4 flex-shrink-0">
                        {formatDate(updatedDate)}
                      </span>
                    </div>
                    <p className="text-sm text-[#8e8ea0] line-clamp-2">
                      {getPreview(chat)}
                    </p>
                  </button>
                  
                  {/* Actions */}
                  <div className="flex gap-2 mt-3 pt-3 border-t border-[#565869]">
                    <button
                      onClick={(e) => handleRestore(e, chat.id)}
                      className="px-3 py-1.5 text-sm bg-[#19c37d] hover:bg-[#16a86b] text-white rounded transition-colors"
                    >
                      Restore
                    </button>
                    <button
                      onClick={(e) => handlePurge(e, chat.id)}
                      className="px-3 py-1.5 text-sm bg-[#ef4444] hover:bg-[#dc2626] text-white rounded transition-colors"
                    >
                      Delete Permanently
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export default TrashChatList;

