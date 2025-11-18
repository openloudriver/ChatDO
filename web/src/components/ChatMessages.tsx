import React from 'react';
import ReactMarkdown from 'react-markdown';
import { useChatStore } from '../store/chat';

const ChatMessages: React.FC = () => {
  const { messages, isStreaming, streamingContent } = useChatStore();

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
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
    </div>
  );
};

export default ChatMessages;

