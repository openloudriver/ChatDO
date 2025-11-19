import React, { useEffect } from 'react';
import { useChatStore } from './store/chat';
import Sidebar from './components/Sidebar';
import ChatMessages from './components/ChatMessages';
import ChatComposer from './components/ChatComposer';
import ProjectChatList from './components/ProjectChatList';
import TrashChatList from './components/TrashChatList';

const App: React.FC = () => {
  const { loadProjects, viewMode, currentProject, loadTrashedChats } = useChatStore();

  useEffect(() => {
    // Load projects on mount
    loadProjects();
  }, [loadProjects]);

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
