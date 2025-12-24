import React, { useEffect, useState } from 'react';
import { useChatStore } from '../store/chat';
import type { Conversation, Project } from '../store/chat';
import ConfirmDialog from './ConfirmDialog';
import axios from 'axios';

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

const Library: React.FC = () => {
  const {
    currentConversation,
    setCurrentConversation,
    projects,
    restoreChat,
    purgeChat,
    purgeAllTrashedChats,
    loadTrashedChats,
    trashedChats
  } = useChatStore();

  const [activeTab, setActiveTab] = useState<'archived' | 'trash'>('trash');
  const [archivedChats, setArchivedChats] = useState<Conversation[]>([]);
  const [archivedProjects, setArchivedProjects] = useState<Project[]>([]);
  const [purgeConfirm, setPurgeConfirm] = useState<{ open: boolean; chatId: string | null; isBulk: boolean }>({
    open: false,
    chatId: null,
    isBulk: false,
  });

  // Load archived chats and projects
  const loadArchived = async () => {
    try {
      const [chatsResponse, projectsResponse] = await Promise.all([
        axios.get('http://localhost:8000/api/chats/archived'),
        axios.get('http://localhost:8000/api/projects/archived')
      ]);

      const state = useChatStore.getState();
      
      // Convert chats to Conversation format
      const archivedChatsList: Conversation[] = chatsResponse.data.map((chat: any) => {
        const project = state.projects.find((p: Project) => p.id === chat.project_id);
        const defaultTarget = project?.default_target || 'general';
        return {
          id: chat.id,
          title: chat.title,
          messages: [],
          projectId: chat.project_id,
          targetName: defaultTarget,
          createdAt: new Date(chat.created_at),
          updatedAt: chat.updated_at,
          trashed: false,
          trashed_at: undefined,
          archived: true,
          archived_at: chat.archived_at,
          thread_id: chat.thread_id
        };
      });

      // Convert projects to Project format
      const archivedProjectsList: Project[] = projectsResponse.data.map((project: any) => ({
        id: project.id,
        name: project.name,
        default_target: project.default_target,
        sort_index: project.sort_index,
        trashed: false,
        trashed_at: undefined,
        archived: true,
        archived_at: project.archived_at
      }));

      setArchivedChats(archivedChatsList);
      setArchivedProjects(archivedProjectsList);
    } catch (error) {
      console.error('Failed to load archived items:', error);
    }
  };

  // Load data when component mounts or tab changes
  useEffect(() => {
    if (activeTab === 'archived') {
      loadArchived();
    } else {
      loadTrashedChats();
    }
  }, [activeTab, loadTrashedChats]);

  const handleUnarchiveChat = async (e: React.MouseEvent, chatId: string) => {
    e.stopPropagation();
    try {
      await axios.post(`http://localhost:8000/api/chats/${chatId}/unarchive`);
      await loadArchived();
    } catch (error) {
      console.error('Failed to unarchive chat:', error);
    }
  };

  const handleUnarchiveProject = async (e: React.MouseEvent, projectId: string) => {
    e.stopPropagation();
    try {
      await axios.post(`http://localhost:8000/api/projects/${projectId}/unarchive`);
      await loadArchived();
    } catch (error) {
      console.error('Failed to unarchive project:', error);
    }
  };

  const handleDeleteFromArchive = async (e: React.MouseEvent, chatId: string) => {
    e.stopPropagation();
    try {
      await axios.delete(`http://localhost:8000/api/chats/${chatId}`);
      await loadArchived();
    } catch (error) {
      console.error('Failed to delete chat from archive:', error);
    }
  };

  const handleDeleteProjectFromArchive = async (e: React.MouseEvent, projectId: string) => {
    e.stopPropagation();
    try {
      await axios.delete(`http://localhost:8000/api/projects/${projectId}`);
      await loadArchived();
    } catch (error) {
      console.error('Failed to delete project from archive:', error);
    }
  };

  const handleRestore = async (e: React.MouseEvent, chatId: string) => {
    e.stopPropagation();
    try {
      await restoreChat(chatId);
    } catch (error) {
      console.error('Failed to restore chat:', error);
    }
  };

  const handlePurge = (e: React.MouseEvent, chatId: string) => {
    e.stopPropagation();
    setPurgeConfirm({
      open: true,
      chatId,
      isBulk: false,
    });
  };

  const confirmPurge = async () => {
    if (!purgeConfirm.chatId) return;
    
    try {
      await purgeChat(purgeConfirm.chatId);
      setPurgeConfirm({ open: false, chatId: null, isBulk: false });
    } catch (error) {
      console.error('Failed to purge chat:', error);
      alert('Failed to delete chat. Please try again.');
      setPurgeConfirm({ open: false, chatId: null, isBulk: false });
    }
  };

  const handlePurgeAll = () => {
    const count = trashedChats.length;
    if (count === 0) return;
    
    setPurgeConfirm({
      open: true,
      chatId: null,
      isBulk: true,
    });
  };

  const confirmPurgeAll = async () => {
    try {
      await purgeAllTrashedChats();
      setPurgeConfirm({ open: false, chatId: null, isBulk: false });
    } catch (error) {
      console.error('Failed to purge all chats:', error);
      alert('Failed to delete all chats. Please try again.');
      setPurgeConfirm({ open: false, chatId: null, isBulk: false });
    }
  };

  // Get Bullet Workspace project IDs to filter them out
  const bulletWorkspaceProjectIds = new Set(
    projects.filter(p => p.name === "Bullet Workspace").map(p => p.id)
  );

  // Filter out Bullet Workspace chats from trash
  const filteredTrashedChats = trashedChats.filter(chat => 
    !chat.projectId || !bulletWorkspaceProjectIds.has(chat.projectId)
  );

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--bg-primary)] transition-colors">
      {/* Header with Tabs */}
      <div className="px-6 py-4 border-b border-[var(--border-color)] transition-colors">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-xl font-semibold text-[var(--text-primary)]">Library</h2>
            <p className="text-sm text-[var(--text-secondary)] mt-1">
              {activeTab === 'archived' 
                ? 'Archived items are hidden from default lists but remain searchable'
                : 'Deleted chats are kept for 30 days'}
            </p>
          </div>
          {activeTab === 'trash' && filteredTrashedChats.length > 0 && (
            <button
              onClick={handlePurgeAll}
              className="px-4 py-2 bg-[#ef4444] hover:bg-[#dc2626] text-white rounded-lg text-sm font-medium transition-colors"
            >
              Delete All
            </button>
          )}
        </div>

        {/* Tabs */}
        <div className="flex gap-2 border-b border-[var(--border-color)]">
          <button
            onClick={() => setActiveTab('trash')}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === 'trash'
                ? 'text-[var(--text-primary)] border-b-2 border-[var(--user-bubble-bg)]'
                : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
          >
            Trash
          </button>
          <button
            onClick={() => setActiveTab('archived')}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === 'archived'
                ? 'text-[var(--text-primary)] border-b-2 border-[var(--user-bubble-bg)]'
                : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
          >
            Archived
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {activeTab === 'archived' ? (
          <>
            {/* Archived Projects */}
            {archivedProjects.length > 0 && (
              <div className="mb-6">
                <h3 className="text-sm font-semibold text-[var(--text-secondary)] uppercase mb-3">Projects</h3>
                <div className="space-y-2">
                  {archivedProjects.map((project) => (
                    <div
                      key={project.id}
                      className="w-full p-4 rounded-lg bg-[var(--bg-tertiary)] hover:bg-[var(--assistant-bubble-bg)] border border-transparent transition-colors"
                    >
                      <div className="flex items-start justify-between mb-2">
                        <div className="flex items-center gap-2 flex-1">
                          <h3 className="font-medium text-[var(--text-primary)]">
                            {project.name}
                          </h3>
                          <span className="text-xs px-2 py-0.5 rounded bg-yellow-500/20 text-yellow-600 font-medium">
                            Archived
                          </span>
                        </div>
                        <span className="text-xs text-[var(--text-secondary)] ml-4 flex-shrink-0">
                          {project.archived_at ? formatDate(project.archived_at) : ''}
                        </span>
                      </div>
                      
                      {/* Actions */}
                      <div className="flex gap-2 mt-3 pt-3 border-t border-[var(--border-color)]">
                        <button
                          onClick={(e) => handleUnarchiveProject(e, project.id)}
                          className="px-3 py-1.5 text-sm bg-[#19c37d] hover:bg-[#16a86b] text-white rounded transition-colors"
                        >
                          Restore
                        </button>
                        <button
                          onClick={(e) => handleDeleteProjectFromArchive(e, project.id)}
                          className="px-3 py-1.5 text-sm bg-[#ef4444] hover:bg-[#dc2626] text-white rounded transition-colors"
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Archived Chats */}
            {archivedChats.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold text-[var(--text-secondary)] uppercase mb-3">Chats</h3>
                <div className="space-y-2">
                  {archivedChats.map((chat) => {
                    const isSelected = currentConversation?.id === chat.id;
                    const project = projects.find(p => p.id === chat.projectId);
                    const updatedDate = chat.archived_at ? new Date(chat.archived_at) : chat.createdAt;
                    
                    return (
                      <div
                        key={chat.id}
                        className={`w-full p-4 rounded-lg transition-colors ${
                          isSelected
                            ? 'bg-[var(--assistant-bubble-bg)] border border-[var(--border-color)]'
                            : 'bg-[var(--bg-tertiary)] hover:bg-[var(--assistant-bubble-bg)] border border-transparent'
                        }`}
                      >
                        <button
                          onClick={() => {
                            setCurrentConversation(chat).catch(err => console.error('Failed to load conversation:', err));
                          }}
                          className="w-full text-left"
                        >
                          <div className="flex items-start justify-between mb-2">
                            <div className="flex items-center gap-2 flex-1">
                              <h3 className={`font-medium ${isSelected ? 'text-[var(--text-primary)]' : 'text-[var(--text-primary)]'}`}>
                                {chat.title}
                              </h3>
                              <span className="text-xs px-2 py-0.5 rounded bg-yellow-500/20 text-yellow-600 font-medium">
                                Archived
                              </span>
                            </div>
                            <span className="text-xs text-[var(--text-secondary)] ml-4 flex-shrink-0">
                              {formatDate(updatedDate)}
                            </span>
                          </div>
                          {project && (
                            <p className="text-xs text-[var(--text-secondary)] mt-1">
                              From: {project.name}
                            </p>
                          )}
                          <p className="text-sm text-[var(--text-secondary)] line-clamp-2 mt-2">
                            {getPreview(chat)}
                          </p>
                        </button>
                        
                        {/* Actions */}
                        <div className="flex gap-2 mt-3 pt-3 border-t border-[var(--border-color)]">
                          <button
                            onClick={(e) => handleUnarchiveChat(e, chat.id)}
                            className="px-3 py-1.5 text-sm bg-[#19c37d] hover:bg-[#16a86b] text-white rounded transition-colors"
                          >
                            Restore
                          </button>
                          <button
                            onClick={(e) => handleDeleteFromArchive(e, chat.id)}
                            className="px-3 py-1.5 text-sm bg-[#ef4444] hover:bg-[#dc2626] text-white rounded transition-colors"
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {archivedProjects.length === 0 && archivedChats.length === 0 && (
              <div className="text-center py-12">
                <p className="text-[var(--text-secondary)] text-sm">Archive is empty</p>
              </div>
            )}
          </>
        ) : (
          <>
            {/* Trash Tab - reuse TrashChatList logic */}
            {filteredTrashedChats.length === 0 ? (
              <div className="text-center py-12">
                <p className="text-[var(--text-secondary)] text-sm">Trash is empty</p>
              </div>
            ) : (
              <div className="space-y-2">
                {filteredTrashedChats.map((chat) => {
                  const isSelected = currentConversation?.id === chat.id;
                  const project = projects.find(p => p.id === chat.projectId);
                  const updatedDate = chat.trashed_at ? new Date(chat.trashed_at) : chat.createdAt;
                  
                  return (
                    <div
                      key={chat.id}
                      className={`w-full p-4 rounded-lg transition-colors ${
                        isSelected
                          ? 'bg-[var(--assistant-bubble-bg)] border border-[var(--border-color)]'
                          : 'bg-[var(--bg-tertiary)] hover:bg-[var(--assistant-bubble-bg)] border border-transparent'
                      }`}
                    >
                      <button
                        onClick={() => {
                          setCurrentConversation(chat).catch(err => console.error('Failed to load conversation:', err));
                        }}
                        className="w-full text-left"
                      >
                        <div className="flex items-start justify-between mb-2">
                          <div className="flex items-center gap-2 flex-1">
                            <h3 className={`font-medium ${isSelected ? 'text-[var(--text-primary)]' : 'text-[var(--text-primary)]'}`}>
                              {chat.title}
                            </h3>
                            <span className="text-xs px-2 py-0.5 rounded bg-red-500/20 text-red-600 font-medium">
                              Trash
                            </span>
                          </div>
                          <span className="text-xs text-[var(--text-secondary)] ml-4 flex-shrink-0">
                            {formatDate(updatedDate)}
                          </span>
                        </div>
                        {project && (
                          <p className="text-xs text-[var(--text-secondary)] mt-1">
                            From: {project.name}
                          </p>
                        )}
                        <p className="text-sm text-[var(--text-secondary)] line-clamp-2 mt-2">
                          {getPreview(chat)}
                        </p>
                      </button>
                      
                      {/* Actions */}
                      <div className="flex gap-2 mt-3 pt-3 border-t border-[var(--border-color)]">
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
          </>
        )}
      </div>

      {/* Purge Confirmation Dialog */}
      <ConfirmDialog
        open={purgeConfirm.open}
        title={purgeConfirm.isBulk ? 'Delete all chats permanently' : 'Delete chat permanently'}
        message={
          purgeConfirm.isBulk
            ? `Are you sure you want to permanently delete all ${filteredTrashedChats.length} chat${filteredTrashedChats.length > 1 ? 's' : ''} in Trash? This cannot be undone.`
            : 'Are you sure you want to permanently delete this chat? This cannot be undone.'
        }
        confirmLabel="OK"
        cancelLabel="Cancel"
        onConfirm={purgeConfirm.isBulk ? confirmPurgeAll : confirmPurge}
        onCancel={() => setPurgeConfirm({ open: false, chatId: null, isBulk: false })}
      />
    </div>
  );
};

export default Library;

