import React, { useEffect, useState } from 'react';
import { useChatStore } from '../store/chat';
import type { Conversation } from '../store/chat';
import ConfirmDialog from './ConfirmDialog';

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

// Get preview snippet from conversation (show last user message, not assistant)
const getPreview = (conversation: Conversation): string => {
  if (conversation.messages && conversation.messages.length > 0) {
    // Find the last user message (go backwards through messages)
    for (let i = conversation.messages.length - 1; i >= 0; i--) {
      const msg = conversation.messages[i];
      if (msg.role === 'user') {
        const content = msg.content;
        // Strip markdown and get first 100 chars
        const plainText = content.replace(/[#*`_~\[\]()]/g, '').trim();
        return plainText.length > 100 ? plainText.substring(0, 100) + '...' : plainText;
      }
    }
    // If no user message found, show last message anyway
    const lastMessage = conversation.messages[conversation.messages.length - 1];
    const content = lastMessage.content;
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
    deleteChat,
    createNewChatInProject
  } = useChatStore();

  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);
  const [selectedChats, setSelectedChats] = useState<Set<string>>(new Set());
  const [deleteConfirm, setDeleteConfirm] = useState<{ open: boolean; chatId: string | null; chatTitle: string | null; isBulk: boolean }>({
    open: false,
    chatId: null,
    chatTitle: null,
    isBulk: false,
  });

  const handleNewChat = async () => {
    if (!currentProject) return;
    
    try {
      const newConversation = await createNewChatInProject(currentProject.id);
      await setCurrentConversation(newConversation);
    } catch (error) {
      console.error('Failed to create conversation:', error);
      alert('Failed to create conversation. Please try again.');
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
    setDeleteConfirm({
      open: true,
      chatId,
      chatTitle,
      isBulk: false,
    });
  };

  const confirmDeleteChat = async () => {
    if (!deleteConfirm.chatId) return;
    
    try {
      await deleteChat(deleteConfirm.chatId);
      setDeleteConfirm({ open: false, chatId: null, chatTitle: null, isBulk: false });
    } catch (error) {
      console.error('Failed to delete chat:', error);
      alert('Failed to delete chat. Please try again.');
      setDeleteConfirm({ open: false, chatId: null, chatTitle: null, isBulk: false });
    }
  };

  const handleToggleSelect = (chatId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedChats(prev => {
      const next = new Set(prev);
      if (next.has(chatId)) {
        next.delete(chatId);
      } else {
        next.add(chatId);
      }
      return next;
    });
  };

  const handleBulkDelete = () => {
    if (selectedChats.size === 0) return;
    
    const count = selectedChats.size;
    setDeleteConfirm({
      open: true,
      chatId: null,
      chatTitle: `${count} chat${count > 1 ? 's' : ''}`,
      isBulk: true,
    });
  };

  const confirmBulkDelete = async () => {
    if (selectedChats.size === 0) return;

    try {
      // Delete all selected chats
      const deletePromises = Array.from(selectedChats).map(chatId => deleteChat(chatId));
      await Promise.all(deletePromises);
      setSelectedChats(new Set());
      setDeleteConfirm({ open: false, chatId: null, chatTitle: null, isBulk: false });
    } catch (error) {
      console.error('Failed to delete chats:', error);
      alert('Failed to delete some chats. Please try again.');
      setDeleteConfirm({ open: false, chatId: null, chatTitle: null, isBulk: false });
    }
  };

  const handleSelectAll = () => {
    if (selectedChats.size === projectChats.length) {
      // Deselect all
      setSelectedChats(new Set());
    } else {
      // Select all
      setSelectedChats(new Set(projectChats.map(c => c.id)));
    }
  };

  // Filter conversations for this project
  const projectChats = conversations.filter(c => c.projectId === projectId);

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--bg-primary)] transition-colors">
        {/* Header */}
        <div className="px-6 py-4 border-b border-[var(--border-color)] transition-colors">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold text-[var(--text-primary)]">
              {currentProject?.name || 'Project'}
            </h2>
            <div className="flex items-center gap-2">
              {selectedChats.size > 0 && (
                <>
                  <button
                    onClick={handleBulkDelete}
                    className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-sm font-medium transition-colors"
                  >
                    Delete ({selectedChats.size})
                  </button>
                  <button
                    onClick={() => setSelectedChats(new Set())}
                    className="px-4 py-2 bg-[var(--border-color)] hover:bg-[var(--bg-tertiary)] text-[var(--text-primary)] rounded-lg text-sm font-medium transition-colors"
                  >
                    Cancel
                  </button>
                </>
              )}
              <button
                onClick={handleNewChat}
                className="px-4 py-2 bg-[#19c37d] hover:bg-[#16a86b] text-white rounded-lg text-sm font-medium transition-colors"
              >
                New Chat
              </button>
            </div>
        </div>
      </div>

      {/* Chat List */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {projectChats.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-[var(--text-secondary)] text-sm">No chats yet. Start a new conversation!</p>
          </div>
        ) : (
          <div className="space-y-2">
            {projectChats.length > 0 && (
              <div className="mb-2 pb-2 border-b border-[var(--border-color)] transition-colors">
                <button
                  onClick={handleSelectAll}
                  className="text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
                >
                  {selectedChats.size === projectChats.length ? 'Deselect All' : 'Select All'}
                </button>
              </div>
            )}
            {projectChats.map((chat) => {
              const isSelected = currentConversation?.id === chat.id;
              const isChecked = selectedChats.has(chat.id);
              const updatedDate = chat.trashed_at ? new Date(chat.trashed_at) : chat.createdAt;
              
              return (
                <div key={chat.id} className="relative group">
                  <div
                    className={`flex items-center gap-3 p-4 rounded-lg transition-colors ${
                      isSelected
                        ? 'bg-[var(--assistant-bubble-bg)] border border-[var(--border-color)]'
                        : 'bg-[var(--bg-tertiary)] hover:bg-[var(--assistant-bubble-bg)] border border-transparent'
                    } ${isChecked ? 'ring-2 ring-[#19c37d]' : ''}`}
                  >
                    {/* Checkbox */}
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() => {}}
                      onClick={(e) => handleToggleSelect(chat.id, e)}
                      className="w-4 h-4 text-[#19c37d] bg-[var(--bg-primary)] border-[var(--border-color)] rounded focus:ring-[#19c37d] focus:ring-2 cursor-pointer flex-shrink-0 transition-colors"
                    />
                    
                    {/* Chat content */}
                    <button
                      onClick={() => {
                        if (!isChecked) {
                          setCurrentConversation(chat).catch(err => console.error('Failed to load conversation:', err));
                        }
                      }}
                      onContextMenu={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setMenuPosition({ x: e.clientX, y: e.clientY });
                        setOpenMenuId(openMenuId === chat.id ? null : chat.id);
                      }}
                      className="flex-1 text-left"
                    >
                      <div className="flex items-start justify-between mb-2">
                        <h3 className={`font-medium ${isSelected ? 'text-[var(--text-primary)]' : 'text-[var(--text-primary)]'}`}>
                          {chat.title}
                        </h3>
                        <span className="text-xs text-[var(--text-secondary)] ml-4 flex-shrink-0">
                          {formatDate(updatedDate)}
                        </span>
                      </div>
                      <p className="text-sm text-[var(--text-secondary)] line-clamp-2">
                        {getPreview(chat)}
                      </p>
                    </button>
                  </div>
                  {openMenuId === chat.id && menuPosition && (
                    <div 
                      className="fixed w-48 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg shadow-lg z-50 transition-colors"
                      style={{
                        left: `${menuPosition.x}px`,
                        top: `${menuPosition.y}px`,
                      }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <button
                        onClick={() => handleRenameChat(chat.id, chat.title)}
                        className="w-full text-left px-4 py-2 text-sm text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] rounded-t-lg transition-colors"
                      >
                        Rename Chat
                      </button>
                      <button
                        onClick={() => handleDeleteChat(chat.id, chat.title)}
                        className="w-full text-left px-4 py-2 text-sm text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] rounded-b-lg transition-colors"
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

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        open={deleteConfirm.open}
        title={deleteConfirm.isBulk ? 'Delete chats' : 'Delete chat'}
        message={
          deleteConfirm.isBulk
            ? `Delete ${deleteConfirm.chatTitle}? They will move to Trash and be permanently removed after 30 days.`
            : `Delete "${deleteConfirm.chatTitle}"? It will move to Trash and be permanently removed after 30 days.`
        }
        confirmLabel="OK"
        cancelLabel="Cancel"
        onConfirm={deleteConfirm.isBulk ? confirmBulkDelete : confirmDeleteChat}
        onCancel={() => setDeleteConfirm({ open: false, chatId: null, chatTitle: null, isBulk: false })}
      />
    </div>
  );
};

export default ProjectChatList;

