import React, { useState, useEffect, useMemo } from 'react';
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
import { ImpactCaptureModal } from './ImpactCaptureModal';
import { useTheme } from '../contexts/ThemeContext';

const NewProjectIcon = () => (
  <svg
    className="w-5 h-5 flex-shrink-0"
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
  >
    {/* Folder icon */}
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={2}
      d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
    />
    {/* Plus sign overlay */}
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={2.5}
      d="M15 12h-3m0 0H9m3 0v-3m0 3v3"
      className="opacity-90"
    />
  </svg>
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
  const { theme } = useTheme();
  const sidebarTextColor = theme === 'dark' ? '#ffffff' : '#000000';
  
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
        className={`w-full text-left px-3 py-2 rounded-lg transition-colors cursor-grab active:cursor-grabbing flex items-center gap-2 ${
          currentProject?.id === project.id
            ? 'bg-[var(--bg-primary)]'
            : 'hover:bg-[var(--bg-primary)]'
        }`}
        style={{ color: sidebarTextColor }}
      >
        <svg
          className="w-4 h-4 flex-shrink-0"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
          />
        </svg>
        <span className="truncate">{project.name}</span>
      </button>
      {openMenuId === project.id && (
        <div 
          className="absolute right-0 mt-1 w-48 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg shadow-lg z-50 transition-colors"
          onClick={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <button
            onClick={() => {
              handleEditProject(project.id, project.name);
              setOpenMenuId(null);
            }}
            className="w-full text-left px-4 py-2 text-sm hover:bg-[var(--bg-tertiary)] rounded-t-lg transition-colors"
            style={{ color: sidebarTextColor }}
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
            className="w-full text-left px-4 py-2 text-sm hover:bg-[var(--bg-tertiary)] transition-colors"
            style={{ color: sidebarTextColor }}
          >
            Connect Project
          </button>
          <button
            onClick={() => {
              handleDeleteProject(project.id, project.name);
              setOpenMenuId(null);
            }}
            className="w-full text-left px-4 py-2 text-sm hover:bg-[var(--bg-tertiary)] rounded-b-lg transition-colors"
            style={{ color: sidebarTextColor }}
          >
            Delete Project
          </button>
        </div>
      )}
    </div>
  );
};

const Sidebar: React.FC = () => {
  const { theme } = useTheme();
  const {
    projects,
    currentProject,
    allConversations,
    setCurrentProject,
    setCurrentConversation,
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
  const [impactModalOpen, setImpactModalOpen] = useState(false);
  const { openConnectProjectModal } = useChatStore();

  // Compute recent chats (last 3 across all projects)
  const recentChats = useMemo(() => {
    if (!allConversations || allConversations.length === 0) return [];

    // Get Bullet Workspace project IDs to filter them out
    const bulletWorkspaceProjectIds = new Set(
      projects.filter(p => p.name === "Bullet Workspace").map(p => p.id)
    );

    // Filter to only chats that actually have a projectId, are not trashed, and are not from Bullet Workspace
    const valid = allConversations.filter((c) => 
      !!c.projectId && 
      !c.trashed && 
      !bulletWorkspaceProjectIds.has(c.projectId)
    );

    // Sort by updatedAt (desc), falling back to createdAt if updatedAt is missing
    const sorted = [...valid].sort((a, b) => {
      const aTime = a.updatedAt ?? a.createdAt?.toISOString() ?? '';
      const bTime = b.updatedAt ?? b.createdAt?.toISOString() ?? '';
      // Newest first
      return (bTime || '').localeCompare(aTime || '');
    });

    // Deduplicate by id and take only the top 3
    const unique: typeof sorted = [];
    for (const c of sorted) {
      if (!c.id) continue;
      if (unique.find((u) => u.id === c.id)) continue;
      unique.push(c);
      if (unique.length >= 3) break;
    }

    return unique;
  }, [allConversations, projects]);

  // Load chats when project changes
  useEffect(() => {
    if (currentProject) {
      loadChats(currentProject.id);
    }
  }, [currentProject, loadChats]);

  // Load all chats on mount to populate recentChats across all projects
  useEffect(() => {
    // Load all chats (no project filter) to get conversations from all projects for recentChats
    loadChats();
  }, [loadChats]);

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

  const sidebarTextColor = theme === 'dark' ? '#ffffff' : '#000000';
  
  return (
    <div 
      className="h-full bg-[var(--bg-secondary)] flex flex-col overflow-hidden transition-colors"
      style={{ color: sidebarTextColor }}
    >
      {/* Search Field */}
      <div className="p-2 flex-shrink-0">
        <div className="relative">
          <svg
            className="absolute left-2 top-1/2 transform -translate-y-1/2 w-4 h-4"
            style={{ color: sidebarTextColor }}
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
            className="w-full pl-8 pr-3 py-2 text-sm bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-md focus:outline-none transition-colors"
            style={{ 
              color: sidebarTextColor,
              '--tw-placeholder-color': sidebarTextColor
            } as React.CSSProperties & { '--tw-placeholder-color': string }}
            onFocus={(e) => {
              e.currentTarget.style.borderColor = sidebarTextColor;
            }}
            onBlur={(e) => {
              e.currentTarget.style.borderColor = '';
            }}
          />
        </div>
      </div>

      {/* Projects List */}
      <div className="px-2 mb-4 flex-1 overflow-y-auto">
        {/* Recent Chats Section */}
        {recentChats.length > 0 && (
          <div className="mb-3">
            <div className="px-2 pt-1 pb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
              Recent
            </div>
            <div className="space-y-1">
              {recentChats.map((chat) => {
                const project = projects.find((p) => p.id === chat.projectId);
                const title =
                  chat.title && chat.title.trim().length > 0
                    ? chat.title
                    : 'Untitled chat';

                return (
                  <button
                    key={chat.id}
                    type="button"
                    onClick={() => {
                      // When I click a recent chat:
                      // 1) make sure the correct project is selected
                      // 2) switch to chat view mode
                      // 3) open that conversation
                      if (project && setCurrentProject) {
                        setCurrentProject(project);
                      }
                      setViewMode('chat');
                      if (setCurrentConversation) {
                        setCurrentConversation(chat);
                      }
                    }}
                    className="w-full text-left px-2 py-1.5 rounded-md hover:bg-[var(--bg-tertiary)] transition-colors"
                    style={{ color: sidebarTextColor }}
                  >
                    <div className="truncate text-[13px] text-[var(--text-primary)]">
                      {title}
                    </div>
                    {project && (
                      <div className="truncate text-[11px] text-[var(--text-secondary)]">
                        in {project.name}
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        )}
        <div className="flex items-center justify-between mb-2 px-2">
          <div className="text-xs uppercase" style={{ color: sidebarTextColor }}>Projects</div>
          <button
            type="button"
            onClick={handleNewProject}
            className="rounded-md p-1 hover:bg-[var(--bg-primary)] transition-colors"
            style={{ color: sidebarTextColor }}
            aria-label="New project"
          >
            <NewProjectIcon />
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
            {filteredProjects
              .filter((project: Project) => project.name !== "Bullet Workspace") // Filter out Bullet Workspace from projects list
              .map((project: Project) => (
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
      <div className="px-2 py-2 border-t border-[var(--border-color)] flex items-center justify-between flex-shrink-0 bg-[var(--bg-secondary)] transition-colors">
        <div className="flex-1 min-w-0">
          <AiSpendIndicator />
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setImpactModalOpen(true)}
            className="p-2 rounded transition-colors flex-shrink-0 hover:bg-[var(--bg-primary)]"
            style={{ color: sidebarTextColor }}
            title="Bullets"
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
                d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z"
              />
            </svg>
          </button>
          <button
            onClick={() => {
              setViewMode('memory');
              setCurrentProject(null);
            }}
            className={`p-2 rounded transition-colors flex-shrink-0 ${
              viewMode === 'memory'
                ? 'bg-[var(--bg-primary)]'
                : 'hover:bg-[var(--bg-primary)]'
            }`}
            style={{ color: sidebarTextColor }}
            title="Memory Dashboard"
          >
            <svg
              className="w-5 h-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              {/* Database/Server icon - represents memory storage */}
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"
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
              ? 'bg-[var(--bg-primary)]'
              : 'hover:bg-[var(--bg-primary)]'
          }`}
          style={{ color: sidebarTextColor }}
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
      <ImpactCaptureModal
        open={impactModalOpen}
        onClose={() => setImpactModalOpen(false)}
        onOpenWorkspace={() => {
          setViewMode('impact');
          setCurrentProject(null);
        }}
        onSaved={async (entry) => {
          // If we're in impact view, the ImpactWorkspacePage will handle reloading
          // Otherwise, navigate to bullet workspace which will trigger a reload
          if (viewMode !== 'impact') {
            setViewMode('impact');
            setCurrentProject(null);
            // Give it a moment for the component to mount, then it will reload
          }
        }}
      />
    </div>
  );
};

export default Sidebar;

