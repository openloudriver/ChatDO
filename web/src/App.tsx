import React, { useEffect, useRef } from 'react';
import axios from 'axios';
import { useChatStore, type ViewMode } from './store/chat';
import { AppLayout } from './layout/AppLayout';
import ChatMessages from './components/ChatMessages';
import ChatComposer from './components/ChatComposer';
import ProjectChatList from './components/ProjectChatList';
import TrashChatList from './components/TrashChatList';
import SearchResults from './components/SearchResults';
import MemoryDashboard from './components/MemoryDashboard';
import { ImpactWorkspacePage } from './components/ImpactWorkspacePage';
import ConnectProjectModal from './components/ConnectProjectModal';

const App: React.FC = () => {
  const { 
    loadProjects, 
    viewMode, 
    currentProject, 
    loadTrashedChats,
    ensureGeneralProject,
    createNewChatInProject,
    setCurrentProject,
    setCurrentConversation,
    loadChats,
    connectProjectModal,
    closeConnectProjectModal,
    setViewMode
  } = useChatStore();
  
  // Use a ref to track if initialization has already run
  const initializedRef = useRef(false);

  useEffect(() => {
    // Only run initialization once
    if (initializedRef.current) return;
    
    // Startup sequence: restore session or create new chat
    const initializeApp = async () => {
      initializedRef.current = true;
      
      // First, restore viewMode from localStorage (before loading projects)
      const savedViewMode = localStorage.getItem('chatdo:viewMode');
      if (savedViewMode && ['projectList', 'chat', 'trashList', 'search', 'memory', 'impact'].includes(savedViewMode)) {
        setViewMode(savedViewMode as ViewMode);
        // If we're restoring to impact or memory view, skip the normal restore logic
        if (savedViewMode === 'impact' || savedViewMode === 'memory') {
          await loadProjects();
          return;
        }
      }
      
      // First, load projects (this ensures General exists)
      await loadProjects();
      
      const state = useChatStore.getState();
      
      // Try to restore last session from localStorage
      const lastProjectId = localStorage.getItem('chatdo:lastProjectId');
      const lastChatId = localStorage.getItem('chatdo:lastChatId');
      
      // Case A: Both lastProjectId and lastChatId exist - try to restore both
      if (lastProjectId && lastChatId) {
        const lastProject = state.projects.find(p => p.id === lastProjectId);
        if (lastProject) {
          // First, try to fetch the chat directly from backend to verify it exists
          try {
            const allChatsResponse = await axios.get(`http://localhost:8000/api/chats?project_id=${lastProjectId}&include_trashed=true`);
            const allChats = allChatsResponse.data;
            const chatData = allChats.find((c: any) => c.id === lastChatId);
            
            if (chatData && !chatData.trashed) {
              // Chat exists and is not trashed - restore it
              // Load chats for the project (active only for the list)
              await loadChats(lastProjectId);
              
              // Convert backend chat to Conversation format
              const state = useChatStore.getState();
              const project = state.projects.find(p => p.id === lastProjectId) || lastProject;
              const defaultTarget = project?.default_target || 'general';
              
              const conversation = {
                id: chatData.id,
                title: chatData.title,
                messages: [], // Will be loaded by setCurrentConversation
                projectId: chatData.project_id,
                targetName: defaultTarget,
                createdAt: new Date(chatData.created_at),
                trashed: false,
                trashed_at: undefined,
                thread_id: chatData.thread_id
              };
              
              setCurrentProject(lastProject);
              await setCurrentConversation(conversation);
              return;
            } else if (chatData && chatData.trashed) {
              // Chat is trashed, just show project list
              setCurrentProject(lastProject);
              await loadChats(lastProjectId);
              return;
            }
          } catch (error) {
            console.error('Failed to restore chat:', error);
            // Fall through to show project list
          }
        }
      }
      
      // Case B: Only lastProjectId exists - restore project, show chat list
      if (lastProjectId) {
        const lastProject = state.projects.find(p => p.id === lastProjectId);
        if (lastProject) {
          setCurrentProject(lastProject);
          await loadChats(lastProjectId);
          return;
        }
      }
      
      // Case C: Neither exist (or invalid) - just show General project list (don't create new chat)
      const generalProject = await ensureGeneralProject();
      setCurrentProject(generalProject);
      await loadChats(generalProject.id);
    };
    
    initializeApp();
  }, []); // Empty dependency array - only run once on mount

  useEffect(() => {
    // Load trashed chats when entering trash view
    if (viewMode === 'trashList') {
      loadTrashedChats();
    }
  }, [viewMode, loadTrashedChats]);

  // Render main content based on view mode
  const renderMainContent = () => {
    if (viewMode === 'memory') {
      return <MemoryDashboard />;
    }
    
    if (viewMode === 'impact') {
      return <ImpactWorkspacePage />;
    }
    
    if (viewMode === 'search') {
      return <SearchResults />;
    }
    
    if (viewMode === 'trashList') {
      return <TrashChatList />;
    }
    
    if (viewMode === 'projectList' && currentProject) {
      return <ProjectChatList projectId={currentProject.id} />;
    }
    
    if (viewMode === 'chat') {
  return (
    <>
          <div className="flex-1 overflow-hidden">
            <ChatMessages />
          </div>
          <ChatComposer />
        </>
      );
    }
    
    // Default: show empty state or project list if no project selected
    return (
      <div className="flex-1 flex items-center justify-center bg-[var(--bg-primary)] transition-colors">
        <div className="text-center px-4">
          <p className="text-[var(--text-secondary)] text-lg mb-2">Select a project to view its chats</p>
          <p className="text-[var(--text-secondary)] text-sm">or click the trash icon to view deleted chats</p>
        </div>
      </div>
    );
  };

  return (
    <AppLayout>
      <div className="flex-1 flex flex-col min-w-0 h-full">
        {renderMainContent()}
      </div>
      
      {/* Connect Project Modal - rendered at root level */}
      {connectProjectModal.open && connectProjectModal.projectId && connectProjectModal.projectName && (
        <>
          {console.log('Rendering ConnectProjectModal:', connectProjectModal)}
          <ConnectProjectModal
            projectId={connectProjectModal.projectId}
            projectName={connectProjectModal.projectName}
            isOpen={connectProjectModal.open}
            onClose={closeConnectProjectModal}
          />
        </>
      )}
    </AppLayout>
  );
};

export default App;
