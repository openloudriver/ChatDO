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
import { useChatStore, type Project } from '../store/chat';
import { AiSpendIndicator } from './AiSpendIndicator';
import ConnectProjectModal from './ConnectProjectModal';

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
  handleConnectProject: (id: string, name: string) => void;
  handleDeleteProject: (id: string, name: string) => void;
  setViewMode: (mode: 'projectList' | 'chat' | 'trashList' | 'memory') => void;
}

const SortableProjectItem: React.FC<SortableProjectItemProps> = ({
  project,
  currentProject,
  setCurrentProject,
  openMenuId,
  setOpenMenuId,
  handleEditProject,
  handleConnectProject,
  handleDeleteProject,
  setViewMode,
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
        onClick={() => {
          // Select project on click (drag won't activate if movement < 8px)
          setCurrentProject(project);
          setViewMode('projectList');
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
          className="absolute right-0 mt-1 w-48 bg-[#343541] border border-[#565869] rounded-lg shadow-lg z-50"
          onClick={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
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
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              console.log('Connect Project clicked for:', project.id, project.name);
              handleConnectProject(project.id, project.name);
              setOpenMenuId(null);
            }}
            className="w-full text-left px-4 py-2 text-sm text-[#ececf1] hover:bg-[#40414f]"
          >
            Connect Project
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
    setCurrentProject,
    createProject,
    renameProject,
    deleteProject,
    reorderProjects,
    loadChats,
    setViewMode,
    viewMode,
    searchChats,
    setSearchQuery,
    searchQuery
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
  const { openConnectProjectModal } = useChatStore();

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


  // Handle search input with debounce
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      if (searchQuery.trim()) {
        searchChats(searchQuery);
      }
      // If search is cleared, setSearchQuery will handle clearing the view
    }, 300); // 300ms debounce
    
    return () => clearTimeout(timeoutId);
  }, [searchQuery, searchChats]);
  
  // Filter projects based on search query (only if not in search mode)
  const filteredProjects = projects;

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

  const handleConnectProject = (projectId: string, projectName: string) => {
    openConnectProjectModal(projectId, projectName);
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



  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    
    if (!over || active.id === over.id) {
      return;
    }
    
    // Use the full projects list (not filtered) for reordering
    const oldIndex = projects.findIndex((p: Project) => p.id === active.id);
    const newIndex = projects.findIndex((p: Project) => p.id === over.id);
    
    if (oldIndex !== -1 && newIndex !== -1) {
      const reordered = arrayMove(projects, oldIndex, newIndex) as Project[];
      const orderedIds = reordered.map((p: Project) => p.id);
      reorderProjects(orderedIds);
    }
  };

  return (
    <div className="w-64 bg-[#202123] h-screen flex flex-col text-white overflow-hidden">
      {/* Search Field */}
      <div className="p-2 flex-shrink-0">
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
            onFocus={() => {
              // If search is active, ensure we're in search mode
              if (searchQuery.trim()) {
                setViewMode('search');
              }
            }}
            className="w-full pl-8 pr-3 py-2 text-sm bg-[#343541] border border-[#565869] rounded-md text-[#ececf1] placeholder-[#8e8ea0] focus:outline-none focus:border-[#8e8ea0] transition-colors"
          />
        </div>
      </div>

      {/* Projects List */}
      <div className="px-2 mb-4 flex-1 overflow-y-auto">
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
            items={filteredProjects.map((p: Project) => p.id)}
            strategy={verticalListSortingStrategy}
          >
            {filteredProjects.map((project: Project) => (
              <SortableProjectItem
                key={project.id}
                project={project}
                currentProject={currentProject}
                setCurrentProject={setCurrentProject}
                openMenuId={openMenuId}
                setOpenMenuId={setOpenMenuId}
                handleEditProject={handleEditProject}
                handleConnectProject={handleConnectProject}
                handleDeleteProject={handleDeleteProject}
                setViewMode={setViewMode}
              />
            ))}
          </SortableContext>
        </DndContext>
      </div>

      {/* Chats section removed - chats are now shown in main area via ProjectChatList */}

      {/* Bottom Status Bar - AI Spend Indicator, Memory, and Trash Button */}
      <div className="px-2 py-2 border-t border-[#565869] flex items-center justify-between flex-shrink-0 bg-[#202123]">
        <div className="flex-1 min-w-0">
          <AiSpendIndicator />
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => {
              setViewMode('memory');
              setCurrentProject(null);
            }}
            className={`p-2 rounded transition-colors flex-shrink-0 ${
              viewMode === 'memory'
                ? 'bg-[#343541] text-white'
                : 'text-[#8e8ea0] hover:bg-[#343541] hover:text-white'
            }`}
            title="Memory Dashboard"
          >
            <svg
              className="w-5 h-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
          </button>
          <button
            onClick={() => {
              setViewMode('trashList');
              setCurrentProject(null);
            }}
            className={`p-2 rounded transition-colors flex-shrink-0 ${
              viewMode === 'trashList'
                ? 'bg-[#343541] text-white'
                : 'text-[#8e8ea0] hover:bg-[#343541] hover:text-white'
            }`}
            title="Trash"
          >
            <svg
              className="w-5 h-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
              />
            </svg>
          </button>
        </div>
      </div>
      
      {/* Connect Project Modal - rendered via portal in App.tsx */}
    </div>
  );
};

export default Sidebar;

