import React, { useState, useRef } from 'react';
import { useChatStore } from '../store/chat';
import axios from 'axios';

const ChatComposer: React.FC = () => {
  const [input, setInput] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  
  const {
    currentProject,
    currentConversation,
    addMessage,
    setLoading,
    setStreaming,
    updateStreamingContent,
    clearStreaming
  } = useChatStore();

  const handleSend = async () => {
    if (!input.trim() || !currentProject || !currentConversation) return;

    const userMessage = input.trim();
    setInput('');
    
    // Add user message
    addMessage({ role: 'user', content: userMessage });
    
    setLoading(true);
    
    try {
      // Try WebSocket streaming first
      const ws = new WebSocket('ws://localhost:8000/api/chat/stream');
      let streamedContent = '';
      
      ws.onopen = () => {
        setStreaming(true);
        ws.send(JSON.stringify({
          project_id: currentProject.id,
          conversation_id: currentConversation.id,
          target_name: currentConversation.targetName,
          message: userMessage
        }));
      };
      
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.type === 'chunk') {
          streamedContent += data.content;
          updateStreamingContent(streamedContent);
        } else if (data.type === 'done') {
          // Add final message
          addMessage({ role: 'assistant', content: streamedContent });
          clearStreaming();
          ws.close();
        } else if (data.type === 'error') {
          console.error('WebSocket error:', data.content);
          clearStreaming();
          ws.close();
          // Show the actual error message
          addMessage({ 
            role: 'assistant', 
            content: `Error: ${data.content}` 
          });
          setLoading(false);
        }
      };
      
      ws.onerror = () => {
        clearStreaming();
        ws.close();
        // Fallback to REST API
        fallbackToRest(userMessage);
      };
      
    } catch (error) {
      console.error('WebSocket connection failed, using REST:', error);
      fallbackToRest(userMessage);
    }
  };

  const fallbackToRest = async (message: string) => {
    if (!currentProject || !currentConversation) return;
    
    try {
      const response = await axios.post('http://localhost:8000/api/chat', {
        project_id: currentProject.id,
        conversation_id: currentConversation.id,
        target_name: currentConversation.targetName,
        message: message
      });
      
      addMessage({ role: 'assistant', content: response.data.reply });
    } catch (error: any) {
      console.error('Failed to send message:', error);
      const errorMessage = error?.response?.data?.detail || error?.message || 'Sorry, I encountered an error. Please try again.';
      addMessage({ 
        role: 'assistant', 
        content: `Error: ${errorMessage}` 
      });
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !currentProject || !currentConversation) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    formData.append('project_id', currentProject.id);
    formData.append('conversation_id', currentConversation.id);

    try {
      const response = await axios.post('http://localhost:8000/api/upload', formData);
      console.log('File uploaded:', response.data);
      // Add a message about the uploaded file
      addMessage({
        role: 'user',
        content: `[File uploaded: ${file.name}]`
      });
    } catch (error) {
      console.error('File upload failed:', error);
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleUrlScrape = async () => {
    const url = prompt('Enter URL to scrape:');
    if (!url || !currentProject || !currentConversation) return;

    try {
      const response = await axios.post('http://localhost:8000/api/url', null, {
        params: {
          project_id: currentProject.id,
          conversation_id: currentConversation.id,
          url: url
        }
      });
      console.log('URL scraped:', response.data);
      addMessage({
        role: 'user',
        content: `[URL scraped: ${url}]`
      });
    } catch (error) {
      console.error('URL scraping failed:', error);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="border-t border-[#565869] p-4 bg-[#343541]">
      <div className="max-w-3xl mx-auto flex gap-2">
        <div className="flex-1 relative">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Message ChatDO..."
            className="w-full p-3 pr-20 bg-[#40414f] text-white rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-[#19c37d]"
            rows={1}
            style={{ minHeight: '44px', maxHeight: '200px' }}
          />
          <div className="absolute right-2 bottom-2 flex gap-1">
            <button
              onClick={() => fileInputRef.current?.click()}
              className="p-2 hover:bg-[#565869] rounded transition-colors"
              title="Upload file"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
              </svg>
            </button>
            <button
              onClick={handleUrlScrape}
              className="p-2 hover:bg-[#565869] rounded transition-colors"
              title="Scrape URL"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
            </button>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            onChange={handleFileUpload}
          />
        </div>
        <button
          onClick={handleSend}
          disabled={!input.trim() || !currentProject || !currentConversation || isUploading}
          className="px-4 py-2 bg-[#19c37d] text-white rounded-lg hover:bg-[#15a06a] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          Send
        </button>
      </div>
    </div>
  );
};

export default ChatComposer;

