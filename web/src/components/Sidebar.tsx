import React, { useState, useEffect } from 'react';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import type { DragEndEvent } from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { useChatStore } from '../store/chat';
import type { Conversation } from '../store/chat';

const PlusIcon = () => (
  <span className="inline-flex h-4 w-4 items-center justify-center text-xs font-bold">
    +
  </span>
);

interface SortableProjectItemProps {
  project: { id: string; name: string };
  currentProject: { id: string } | null;
  setCurrentProject: (project: { id: string; name: string }) => void;
  openMenuId: string | null;
  setOpenMenuId: (id: string | null) => void;
  handleEditProject: (id: string, name: string) => void;
  handleDeleteProject: (id: string, name: string) => void;
}

const SortableProjectItem: React.FC<SortableProjectItemProps> = ({
  project,
  currentProject,
  setCurrentProject,
  openMenuId,
  setOpenMenuId,
  handleEditProject,
  handleDeleteProject,
}) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: project.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="group relative mb-1"
      onMouseLeave={() => setOpenMenuId(null)}
    >
      <button
        {...attributes}
        {...listeners}
        onClick={(e) => {
          // Select project on click (drag won't activate if movement < 8px)
          setCurrentProject(project);
        }}
        onContextMenu={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpenMenuId(openMenuId === project.id ? null : project.id);
        }}
        className={`w-full text-left px-3 py-2 rounded-lg transition-colors cursor-grab active:cursor-grabbing ${
          currentProject?.id === project.id
            ? 'bg-[#343541] text-white'
            : 'text-[#8e8ea0] hover:bg-[#343541]'
        }`}
      >
        {project.name}
      </button>
      {openMenuId === project.id && (
        <div 
          className="absolute right-0 mt-1 w-48 bg-[#343541] border border-[#565869] rounded-lg shadow-lg z-10"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={() => {
              handleEditProject(project.id, project.name);
              setOpenMenuId(null);
            }}
            className="w-full text-left px-4 py-2 text-sm text-[#ececf1] hover:bg-[#40414f] rounded-t-lg"
          >
            Rename Project
          </button>
          <button
            onClick={() => {
              handleDeleteProject(project.id, project.name);
              setOpenMenuId(null);
            }}
            className="w-full text-left px-4 py-2 text-sm text-[#ececf1] hover:bg-[#40414f] rounded-b-lg"
          >
            Delete Project
          </button>
        </div>
      )}
    </div>
  );
};

const Sidebar: React.FC = () => {
  const {
    projects,
    currentProject,
    conversations,
    trashedChats,
    currentConversation,
    setCurrentProject,
    setCurrentConversation,
    addConversation,
    createProject,
    renameProject,
    deleteProject,
    reorderProjects,
    loadChats,
    renameChat,
    deleteChat,
    restoreChat,
    purgeChat
  } = useChatStore();
  
  // DnD sensors - configure activation distance so clicks still work
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8, // Require 8px of movement before drag starts
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );
  
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [openChatMenuId, setOpenChatMenuId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  // Load chats when project changes
  useEffect(() => {
    if (currentProject) {
      loadChats(currentProject.id);
    }
  }, [currentProject, loadChats]);

  // Close context menus when clicking outside
  useEffect(() => {
    const handleClickOutside = () => {
      setOpenMenuId(null);
      setOpenChatMenuId(null);
    };

    if (openMenuId || openChatMenuId) {
      document.addEventListener('click', handleClickOutside);
      return () => {
        document.removeEventListener('click', handleClickOutside);
      };
    }
  }, [openMenuId, openChatMenuId]);

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
      // Use a small delay to ensure state has updated
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

  // Filter projects and conversations based on search query
  const q = searchQuery.trim().toLowerCase();
  const filteredProjects = q
    ? projects.filter(p => p.name.toLowerCase().includes(q))
    : projects;
  const filteredConversations = q
    ? conversations.filter(c =>
        (c.title ?? "").toLowerCase().includes(q)
      )
    : conversations;
  const filteredTrashedChats = q
    ? trashedChats.filter(c =>
        (c.title ?? "").toLowerCase().includes(q)
      )
    : trashedChats;

  const handleNewProject = async () => {
    const name = window.prompt('New project name?');
    if (!name) return;
    try {
      await createProject(name.trim());
    } catch (error) {
      console.error('Failed to create project:', error);
      alert('Failed to create project. Please try again.');
    }
  };

  const handleEditProject = async (projectId: string, currentName: string) => {
    setOpenMenuId(null);
    const newName = window.prompt('New project name?', currentName);
    if (!newName || newName.trim() === currentName) return;
    try {
      await renameProject(projectId, newName.trim());
    } catch (error) {
      console.error('Failed to rename project:', error);
      alert('Failed to rename project. Please try again.');
    }
  };

  const handleDeleteProject = async (projectId: string, projectName: string) => {
    setOpenMenuId(null);
    const confirmed = window.confirm(`Delete "${projectName}"? This will remove it from the sidebar.`);
    if (!confirmed) return;
    try {
      await deleteProject(projectId);
    } catch (error) {
      console.error('Failed to delete project:', error);
      alert('Failed to delete project. Please try again.');
    }
  };

  const handleRenameChat = async (chatId: string, currentTitle: string) => {
    setOpenChatMenuId(null);
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
    setOpenChatMenuId(null);
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

  const handleRestoreChat = async (chatId: string) => {
    setOpenChatMenuId(null);
    try {
      await restoreChat(chatId);
    } catch (error) {
      console.error('Failed to restore chat:', error);
      alert('Failed to restore chat. Please try again.');
    }
  };

  const handlePurgeChat = async (chatId: string, chatTitle: string) => {
    setOpenChatMenuId(null);
    const confirmed = window.confirm(
      `Permanently delete "${chatTitle}" and its history? This cannot be undone.`
    );
    if (!confirmed) return;
    try {
      await purgeChat(chatId);
    } catch (error) {
      console.error('Failed to purge chat:', error);
      alert('Failed to permanently delete chat. Please try again.');
    }
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    
    if (!over || active.id === over.id) {
      return;
    }
    
    // Use the full projects list (not filtered) for reordering
    const oldIndex = projects.findIndex((p) => p.id === active.id);
    const newIndex = projects.findIndex((p) => p.id === over.id);
    
    if (oldIndex !== -1 && newIndex !== -1) {
      const reordered = arrayMove(projects, oldIndex, newIndex);
      const orderedIds = reordered.map((p) => p.id);
      reorderProjects(orderedIds);
    }
  };

  return (
    <div className="w-64 bg-[#202123] h-screen flex flex-col text-white">
      {/* Search Field */}
      <div className="p-2">
        <div className="relative">
          <svg
            className="absolute left-2 top-1/2 transform -translate-y-1/2 w-4 h-4 text-[#8e8ea0]"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
          <input
            type="text"
            placeholder="Search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-8 pr-3 py-2 text-sm bg-[#343541] border border-[#565869] rounded-md text-[#ececf1] placeholder-[#8e8ea0] focus:outline-none focus:border-[#8e8ea0] transition-colors"
          />
        </div>
      </div>

      {/* Projects List */}
      <div className="px-2 mb-4">
        <div className="flex items-center justify-between mb-2 px-2">
          <div className="text-xs text-[#8e8ea0] uppercase">Projects</div>
          <button
            type="button"
            onClick={handleNewProject}
            className="rounded-md p-1 text-[#8e8ea0] hover:bg-[#343541] hover:text-white transition-colors"
            aria-label="New project"
          >
            <PlusIcon />
          </button>
        </div>
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContext
            items={filteredProjects.map((p) => p.id)}
            strategy={verticalListSortingStrategy}
          >
            {filteredProjects.map((project) => (
              <SortableProjectItem
                key={project.id}
                project={project}
                currentProject={currentProject}
                setCurrentProject={setCurrentProject}
                openMenuId={openMenuId}
                setOpenMenuId={setOpenMenuId}
                handleEditProject={handleEditProject}
                handleDeleteProject={handleDeleteProject}
              />
            ))}
          </SortableContext>
        </DndContext>
      </div>

      {/* Chats List */}
      <div className="flex-1 overflow-y-auto px-2">
        <div className="flex items-center justify-between mb-2 px-2">
          <div className="text-xs text-[#8e8ea0] uppercase">Chats</div>
          <button
            type="button"
            onClick={handleNewChat}
            className="rounded-md p-1 text-[#8e8ea0] hover:bg-[#343541] hover:text-white transition-colors"
            aria-label="New chat"
          >
            <PlusIcon />
          </button>
        </div>
        {filteredConversations
          .filter(c => c.projectId === currentProject?.id)
          .map((conversation) => (
            <div
              key={conversation.id}
              className="group relative mb-1"
              onMouseLeave={() => setOpenChatMenuId(null)}
            >
              <button
                onClick={() => setCurrentConversation(conversation)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setOpenChatMenuId(openChatMenuId === conversation.id ? null : conversation.id);
                }}
                className={`w-full text-left px-3 py-2 rounded-lg transition-colors ${
                  currentConversation?.id === conversation.id
                    ? 'bg-[#343541] text-white'
                    : 'text-[#8e8ea0] hover:bg-[#343541]'
                }`}
              >
                {conversation.title}
              </button>
              {openChatMenuId === conversation.id && (
                <div 
                  className="absolute right-0 mt-1 w-48 bg-[#343541] border border-[#565869] rounded-lg shadow-lg z-10"
                  onClick={(e) => e.stopPropagation()}
                >
                  <button
                    onClick={() => {
                      handleRenameChat(conversation.id, conversation.title);
                      setOpenChatMenuId(null);
                    }}
                    className="w-full text-left px-4 py-2 text-sm text-[#ececf1] hover:bg-[#40414f] rounded-t-lg"
                  >
                    Rename Chat
                  </button>
                  <button
                    onClick={() => {
                      handleDeleteChat(conversation.id, conversation.title);
                      setOpenChatMenuId(null);
                    }}
                    className="w-full text-left px-4 py-2 text-sm text-[#ececf1] hover:bg-[#40414f] rounded-b-lg"
                  >
                    Delete Chat
                  </button>
                </div>
              )}
            </div>
          ))}
        
        {/* Trash Section */}
        {filteredTrashedChats.length > 0 && filteredTrashedChats.some(c => c.projectId === currentProject?.id) && (
          <div className="mt-4">
            <div className="text-xs text-[#8e8ea0] uppercase mb-2 px-2">Trash</div>
            {filteredTrashedChats
              .filter(c => c.projectId === currentProject?.id)
              .map((chat) => (
                <div
                  key={chat.id}
                  className="group relative mb-1"
                  onMouseLeave={() => setOpenChatMenuId(null)}
                >
                  <button
                    onClick={() => setCurrentConversation(chat)}
                    onContextMenu={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setOpenChatMenuId(openChatMenuId === chat.id ? null : chat.id);
                    }}
                    className={`w-full text-left px-3 py-2 rounded-lg transition-colors text-[#6b7280] hover:bg-[#343541] ${
                      currentConversation?.id === chat.id
                        ? 'bg-[#343541] text-[#9ca3af]'
                        : ''
                    }`}
                  >
                    {chat.title}
                  </button>
                  {openChatMenuId === chat.id && (
                    <div 
                      className="absolute right-0 mt-1 w-48 bg-[#343541] border border-[#565869] rounded-lg shadow-lg z-10"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <button
                        onClick={() => {
                          handleRestoreChat(chat.id);
                          setOpenChatMenuId(null);
                        }}
                        className="w-full text-left px-4 py-2 text-sm text-[#ececf1] hover:bg-[#40414f] rounded-t-lg"
                      >
                        Restore Chat
                      </button>
                      <button
                        onClick={() => {
                          handlePurgeChat(chat.id, chat.title);
                          setOpenChatMenuId(null);
                        }}
                        className="w-full text-left px-4 py-2 text-sm text-[#ececf1] hover:bg-[#40414f] rounded-b-lg"
                      >
                        Delete Now
                      </button>
                    </div>
                  )}
                </div>
              ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default Sidebar;

