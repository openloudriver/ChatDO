import React, { useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import { useChatStore } from '../store/chat';

const ChatMessages: React.FC = () => {
  const { messages, isStreaming, streamingContent, currentConversation, currentProject, setViewMode, viewMode } = useChatStore();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when messages change or streaming updates
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, streamingContent, isStreaming]);

  const handleBack = () => {
    if (currentConversation?.trashed) {
      setViewMode('trashList');
    } else if (currentProject) {
      setViewMode('projectList');
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[#343541]">
      {/* Breadcrumb/Header */}
      {viewMode === 'chat' && (
        <div className="px-6 py-4 border-b border-[#565869] flex items-center gap-4">
          <button
            onClick={handleBack}
            className="text-[#8e8ea0] hover:text-white transition-colors flex items-center gap-2"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            <span>
              {currentConversation?.trashed 
                ? 'Back to Trash' 
                : `Back to ${currentProject?.name || 'Project'}`}
            </span>
          </button>
          {currentConversation?.trashed && (
            <span className="px-2 py-1 text-xs bg-[#ef4444] text-white rounded">In Trash</span>
          )}
          {currentConversation && !currentConversation.trashed && (
            <h2 className="text-lg font-semibold text-[#ececf1]">{currentConversation.title}</h2>
          )}
        </div>
      )}

      {/* Messages */}
      <div ref={messagesContainerRef} className="flex-1 overflow-y-auto p-4 space-y-4">
      {messages.map((message) => (
        <div
          key={message.id}
          className={`flex gap-4 ${
            message.role === 'user' ? 'justify-end' : 'justify-start'
          }`}
        >
          {message.role === 'assistant' && (
            <div className="w-8 h-8 rounded-full bg-[#19c37d] flex items-center justify-center flex-shrink-0">
              <span className="text-white text-sm font-bold">C</span>
            </div>
          )}
          
          <div
            className={`max-w-3xl rounded-lg px-4 py-3 ${
              message.role === 'user'
                ? 'bg-[#19c37d] text-white'
                : 'bg-[#444654] text-[#ececf1]'
            }`}
          >
            {message.role === 'assistant' ? (
              <div className="prose prose-invert max-w-none">
                <ReactMarkdown>{message.content}</ReactMarkdown>
              </div>
            ) : (
              <p className="whitespace-pre-wrap">{message.content}</p>
            )}
          </div>
          
          {message.role === 'user' && (
            <div className="w-8 h-8 rounded-full bg-[#5436da] flex items-center justify-center flex-shrink-0">
              <span className="text-white text-sm font-bold">U</span>
            </div>
          )}
        </div>
      ))}
      
      {isStreaming && (
        <div className="flex gap-4 justify-start">
          <div className="w-8 h-8 rounded-full bg-[#19c37d] flex items-center justify-center flex-shrink-0">
            <span className="text-white text-sm font-bold">C</span>
          </div>
          <div className="max-w-3xl rounded-lg px-4 py-3 bg-[#444654] text-[#ececf1]">
            <div className="prose prose-invert max-w-none">
              <ReactMarkdown>{streamingContent}</ReactMarkdown>
            </div>
            <span className="animate-pulse">▊</span>
          </div>
        </div>
      )}
      {/* Invisible element at the bottom to scroll to */}
      <div ref={messagesEndRef} />
      </div>
    </div>
  );
};

export default ChatMessages;

