import React from 'react';
import { useChatStore } from '../store/chat';
import type { Conversation } from '../store/chat';

const Sidebar: React.FC = () => {
  const {
    projects,
    currentProject,
    conversations,
    currentConversation,
    setCurrentProject,
    setCurrentConversation,
    addConversation
  } = useChatStore();

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
      
      const newConversation: Conversation = {
        id: conversationId,
        title: 'New Chat',
        messages: [],
        projectId: currentProject.id,
        targetName: currentProject.default_target,
        createdAt: new Date()
      };
      
      addConversation(newConversation);
      setCurrentConversation(newConversation);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  return (
    <div className="w-64 bg-[#202123] h-screen flex flex-col text-white">
      {/* New Chat Button */}
      <button
        onClick={handleNewChat}
        className="m-2 p-3 border border-[#565869] rounded-lg hover:bg-[#343541] transition-colors flex items-center gap-2"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
        </svg>
        New Chat
      </button>

      {/* Projects List */}
      <div className="px-2 mb-4">
        <div className="text-xs text-[#8e8ea0] uppercase mb-2 px-2">Projects</div>
        {projects.map((project) => (
          <button
            key={project.id}
            onClick={() => setCurrentProject(project)}
            className={`w-full text-left px-3 py-2 rounded-lg mb-1 transition-colors ${
              currentProject?.id === project.id
                ? 'bg-[#343541] text-white'
                : 'text-[#8e8ea0] hover:bg-[#343541]'
            }`}
          >
            {project.name}
          </button>
        ))}
      </div>

      {/* Conversations List */}
      <div className="flex-1 overflow-y-auto px-2">
        <div className="text-xs text-[#8e8ea0] uppercase mb-2 px-2">Conversations</div>
        {conversations
          .filter(c => c.projectId === currentProject?.id)
          .map((conversation) => (
            <button
              key={conversation.id}
              onClick={() => setCurrentConversation(conversation)}
              className={`w-full text-left px-3 py-2 rounded-lg mb-1 transition-colors ${
                currentConversation?.id === conversation.id
                  ? 'bg-[#343541] text-white'
                  : 'text-[#8e8ea0] hover:bg-[#343541]'
              }`}
            >
              {conversation.title}
            </button>
          ))}
      </div>
    </div>
  );
};

export default Sidebar;

