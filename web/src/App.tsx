import React, { useEffect } from 'react';
import { useChatStore } from './store/chat';
import Sidebar from './components/Sidebar';
import ChatMessages from './components/ChatMessages';
import ChatComposer from './components/ChatComposer';
import axios from 'axios';

const App: React.FC = () => {
  const { setProjects, setCurrentProject, projects } = useChatStore();

  useEffect(() => {
    // Load projects on mount
    const loadProjects = async () => {
      try {
        const response = await axios.get('http://localhost:8000/api/projects');
        const loadedProjects = response.data;
        setProjects(loadedProjects);
        
        // Set first project as default
        if (loadedProjects.length > 0) {
          setCurrentProject(loadedProjects[0]);
        }
      } catch (error) {
        console.error('Failed to load projects:', error);
      }
    };
    
    loadProjects();
  }, [setProjects, setCurrentProject]);

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
