import React, { useEffect } from 'react';
import { useChatStore } from './store/chat';
import Sidebar from './components/Sidebar';
import ChatMessages from './components/ChatMessages';
import ChatComposer from './components/ChatComposer';
import ProjectChatList from './components/ProjectChatList';
import TrashChatList from './components/TrashChatList';

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
    loadChats
  } = useChatStore();

  useEffect(() => {
    // Startup sequence: restore session or create new chat
    const initializeApp = async () => {
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
          // Load chats for that project
          await loadChats(lastProjectId);
          const updatedState = useChatStore.getState();
          const lastChat = updatedState.conversations.find(c => c.id === lastChatId);
          
          if (lastChat) {
            // Both valid - restore session
            setCurrentProject(lastProject);
            await setCurrentConversation(lastChat);
            return;
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
      
      // Case C: Neither exist (or invalid) - create new chat in General
      const generalProject = await ensureGeneralProject();
      setCurrentProject(generalProject);
      const newConversation = await createNewChatInProject(generalProject.id);
      await setCurrentConversation(newConversation);
    };
    
    initializeApp();
  }, [loadProjects, ensureGeneralProject, createNewChatInProject, setCurrentProject, setCurrentConversation, loadChats]);

  useEffect(() => {
    // Load trashed chats when entering trash view
    if (viewMode === 'trashList') {
      loadTrashedChats();
    }
  }, [viewMode, loadTrashedChats]);

  // Render main content based on view mode
  const renderMainContent = () => {
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
      <div className="flex-1 flex items-center justify-center bg-[#343541]">
        <div className="text-center px-4">
          <p className="text-[#8e8ea0] text-lg mb-2">Select a project to view its chats</p>
          <p className="text-[#8e8ea0] text-sm">or click the trash icon to view deleted chats</p>
        </div>
      </div>
    );
  };

  return (
    <div className="flex h-screen bg-[#343541] text-[#ececf1]">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        {renderMainContent()}
      </div>
    </div>
  );
};

export default App;
