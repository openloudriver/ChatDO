import React, { useEffect } from 'react';
import { useChatStore } from './store/chat';
import Sidebar from './components/Sidebar';
import ChatMessages from './components/ChatMessages';
import ChatComposer from './components/ChatComposer';

const App: React.FC = () => {
  const { loadProjects } = useChatStore();

  useEffect(() => {
    // Load projects on mount
    loadProjects();
  }, [loadProjects]);

  return (
    <div className="flex h-screen bg-[#343541] text-[#ececf1]">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <div className="flex-1 overflow-hidden">
          <ChatMessages />
        </div>
        <ChatComposer />
      </div>
    </div>
  );
};

export default App;
