import React, { useEffect, useState } from 'react';
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

interface ProjectChatListProps {
  projectId: string;
}

const ProjectChatList: React.FC<ProjectChatListProps> = ({ projectId }) => {
  const {
    conversations,
    currentConversation,
    setCurrentConversation,
    currentProject,
    addConversation,
    loadChats,
    renameChat,
    deleteChat
  } = useChatStore();

  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);

  const handleNewChat = async () => {
    if (!currentProject) return;
    
    try {
      const response = await fetch('http://localhost:8000/api/new_conversation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: currentProject.id })
      });
      
      const data = await response.json();
      const conversationId = data.conversation_id;
      
      // Reload chats to get the new one from backend
      await loadChats(currentProject.id);
      
      // Find and select the new conversation
      setTimeout(() => {
        const state = useChatStore.getState();
        const newConversation = state.conversations.find(c => c.id === conversationId);
        if (newConversation) {
          setCurrentConversation(newConversation);
        }
      }, 100);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  // Load chats when component mounts or projectId changes
  useEffect(() => {
    loadChats(projectId);
  }, [projectId, loadChats]);

  // Close context menus when clicking outside
  useEffect(() => {
    const handleClickOutside = () => {
      setOpenMenuId(null);
      setMenuPosition(null);
    };

    if (openMenuId) {
      document.addEventListener('click', handleClickOutside);
      return () => {
        document.removeEventListener('click', handleClickOutside);
      };
    }
  }, [openMenuId]);

  const handleRenameChat = async (chatId: string, currentTitle: string) => {
    setOpenMenuId(null);
    setMenuPosition(null);
    const newTitle = window.prompt('Rename chat:', currentTitle);
    if (!newTitle || newTitle.trim() === currentTitle) return;
    try {
      await renameChat(chatId, newTitle.trim());
    } catch (error) {
      console.error('Failed to rename chat:', error);
      alert('Failed to rename chat. Please try again.');
    }
  };

  const handleDeleteChat = async (chatId: string, chatTitle: string) => {
    setOpenMenuId(null);
    setMenuPosition(null);
    const confirmed = window.confirm(
      `Delete "${chatTitle}"? It will move to Trash and be permanently removed after 30 days.`
    );
    if (!confirmed) return;
    try {
      await deleteChat(chatId);
    } catch (error) {
      console.error('Failed to delete chat:', error);
      alert('Failed to delete chat. Please try again.');
    }
  };

  // Filter conversations for this project
  const projectChats = conversations.filter(c => c.projectId === projectId);

  return (
    <div className="flex-1 flex flex-col h-full bg-[#343541]">
      {/* Header */}
      <div className="px-6 py-4 border-b border-[#565869]">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-[#ececf1]">
            {currentProject?.name || 'Project'} Chats
          </h2>
          <button
            onClick={handleNewChat}
            className="px-4 py-2 bg-[#19c37d] hover:bg-[#16a86b] text-white rounded-lg text-sm font-medium transition-colors"
          >
            New Chat
          </button>
        </div>
      </div>

      {/* Chat List */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {projectChats.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-[#8e8ea0] text-sm">No chats yet. Start a new conversation!</p>
          </div>
        ) : (
          <div className="space-y-2">
            {projectChats.map((chat) => {
              const isSelected = currentConversation?.id === chat.id;
              const updatedDate = chat.trashed_at ? new Date(chat.trashed_at) : chat.createdAt;
              
              return (
                <div key={chat.id} className="relative group">
                  <button
                    onClick={() => setCurrentConversation(chat)}
                    onContextMenu={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setMenuPosition({ x: e.clientX, y: e.clientY });
                      setOpenMenuId(openMenuId === chat.id ? null : chat.id);
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
                        {formatDate(updatedDate)}
                      </span>
                    </div>
                    <p className="text-sm text-[#8e8ea0] line-clamp-2">
                      {getPreview(chat)}
                    </p>
                  </button>
                  {openMenuId === chat.id && menuPosition && (
                    <div 
                      className="fixed w-48 bg-[#343541] border border-[#565869] rounded-lg shadow-lg z-50"
                      style={{
                        left: `${menuPosition.x}px`,
                        top: `${menuPosition.y}px`,
                      }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <button
                        onClick={() => handleRenameChat(chat.id, chat.title)}
                        className="w-full text-left px-4 py-2 text-sm text-[#ececf1] hover:bg-[#40414f] rounded-t-lg"
                      >
                        Rename Chat
                      </button>
                      <button
                        onClick={() => handleDeleteChat(chat.id, chat.title)}
                        className="w-full text-left px-4 py-2 text-sm text-[#ececf1] hover:bg-[#40414f] rounded-b-lg"
                      >
                        Delete Chat
                      </button>
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

export default ProjectChatList;

