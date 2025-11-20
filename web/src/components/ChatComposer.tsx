import React, { useState, useRef, useEffect } from 'react';
import { useChatStore } from '../store/chat';
import axios from 'axios';

const ChatComposer: React.FC = () => {
  const [input, setInput] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [uploadedFiles, setUploadedFiles] = useState<Array<{name: string, path: string, mimeType: string, base64?: string, extractedText?: string | null}>>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [previewFile, setPreviewFile] = useState<{name: string, data: string, type: 'image' | 'pdf' | 'other', mimeType: string} | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const dropZoneRef = useRef<HTMLDivElement>(null);
  
  // Auto-resize textarea based on content
  const adjustTextareaHeight = () => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      const scrollHeight = textareaRef.current.scrollHeight;
      // Max height: ~12 lines (about 300px), min height: 44px
      const maxHeight = 300;
      const minHeight = 44;
      const newHeight = Math.min(Math.max(scrollHeight, minHeight), maxHeight);
      textareaRef.current.style.height = `${newHeight}px`;
    }
  };
  
  useEffect(() => {
    adjustTextareaHeight();
  }, [input]);
  
  const {
    currentProject,
    currentConversation,
    addMessage,
    setLoading,
    setStreaming,
    updateStreamingContent,
    clearStreaming,
    renameChat,
    editMessage,
    removeMessagesAfter
  } = useChatStore();

  const handleSend = async () => {
    if ((!input.trim() && uploadedFiles.length === 0) || !currentProject || !currentConversation) return;

    const userMessage = input.trim();
    const isEditing = !!editingMessageId;
    const messageIdToEdit = editingMessageId;
    const filesToSend = [...uploadedFiles]; // Capture files before clearing
    
    // Build message with file information - automatically include extracted text like ChatGPT
    let messageWithFiles = userMessage;
    if (filesToSend.length > 0) {
      const fileParts = filesToSend.map(file => {
        if (file.base64) {
          // For images, just send the path - don't include base64 to avoid payload size issues
          // The image is already uploaded, ChatDO can reference it by path if needed
          return `[Image: ${file.name}]\n[File path: ${file.path}]`;
        } else {
          // For documents, include extracted text if available (like ChatGPT)
          // Also include path for preview functionality
          // Format it so ChatDO understands to process automatically
          if (file.extractedText) {
            // Include extracted text directly - ChatDO should process it automatically
            // Include path in a way that ChatDO won't mention but we can use for preview
            return `[File: ${file.name}]\n[File path: ${file.path}]\n[MIME type: ${file.mimeType}]\n\n${file.extractedText}`;
          } else {
            // No extracted text available - include path for preview
            return `[File: ${file.name}]\n[File path: ${file.path}]\n[MIME type: ${file.mimeType}]`;
          }
        }
      });
      
      // Combine user message with file info
      if (userMessage) {
        messageWithFiles = `${userMessage}\n\n${fileParts.join('\n\n')}`;
      } else {
        // No user message - just send file content (ChatDO will process it automatically)
        messageWithFiles = fileParts.join('\n\n');
      }
    }
    
    // If we're editing a message, update it and remove messages after
    if (isEditing && messageIdToEdit) {
      editMessage(messageIdToEdit, messageWithFiles);
      removeMessagesAfter(messageIdToEdit);
      setEditingMessageId(null);
      // Don't add a new message - the existing one is updated
    } else {
      // Add user message (only if not editing)
      addMessage({ role: 'user', content: messageWithFiles });
    }
    
    setInput('');
    setUploadedFiles([]); // Clear uploaded files after sending
    
    // Auto-name chat based on first message if it's still "New Chat"
    const isFirstMessage = currentConversation.title === 'New Chat' && 
                          currentConversation.messages.length === 0;
    
    if (isFirstMessage && !isEditing) {
      // Generate title from first message (truncate to 50 chars, clean up)
      let autoTitle = userMessage
        .replace(/[#*`_~\[\]()]/g, '') // Remove markdown
        .replace(/\n/g, ' ') // Replace newlines with spaces
        .trim();
      
      // Truncate to 50 characters
      if (autoTitle.length > 50) {
        autoTitle = autoTitle.substring(0, 47) + '...';
      }
      
      // Only auto-rename if we got a meaningful title
      if (autoTitle.length > 0) {
        try {
          await renameChat(currentConversation.id, autoTitle);
        } catch (error) {
          console.error('Failed to auto-name chat:', error);
          // Don't block sending the message if auto-naming fails
        }
      }
    }
    
    setLoading(true);
    
    // Build message with file information (using captured files)
    let messageToSend = messageWithFiles;
    
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
          message: messageToSend
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
        fallbackToRest(messageToSend);
      };
      
    } catch (error) {
      console.error('WebSocket connection failed, using REST:', error);
      fallbackToRest(messageToSend);
    }
  };

  const fallbackToRest = async (message: string) => {
    if (!currentProject || !currentConversation) return;
    
    try {
      // Message already includes file info, use as-is
      const messageToSend = message;
      
      const response = await axios.post('http://localhost:8000/api/chat', {
        project_id: currentProject.id,
        conversation_id: currentConversation.id,
        target_name: currentConversation.targetName,
        message: messageToSend
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

  const processFile = async (file: File) => {
    if (!currentProject || !currentConversation) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    formData.append('project_id', currentProject.id);
    formData.append('conversation_id', currentConversation.id);

    try {
      const response = await axios.post('http://localhost:8000/api/upload', formData);
      console.log('File uploaded:', response.data);
      console.log('Extracted text available:', !!response.data.extracted_text);
      
      // For images, read as base64 to include in message
      let base64: string | undefined;
      if (file.type.startsWith('image/')) {
        base64 = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => {
            const result = reader.result as string;
            resolve(result);
          };
          reader.onerror = reject;
          reader.readAsDataURL(file);
        });
      }
      
      const fileInfo = {
        name: file.name,
        path: response.data.path,
        mimeType: response.data.mime_type || file.type,
        base64,
        extractedText: response.data.extracted_text || null
      };
      
      if (!fileInfo.extractedText && !fileInfo.base64) {
        console.warn('No extracted text or base64 for file:', file.name, 'MIME type:', fileInfo.mimeType);
      }
      
      setUploadedFiles(prev => [...prev, fileInfo]);
      // Don't send a message automatically - wait for user to click Send
    } catch (error) {
      console.error('File upload failed:', error);
      alert('Failed to upload file. Please try again.');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await processFile(file);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    
    const files = Array.from(e.dataTransfer.files);
    for (const file of files) {
      await processFile(file);
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

  // Listen for edit-message event (triggered when clicking edit on a message)
  useEffect(() => {
    const handleEditMessage = (event: CustomEvent) => {
        if (event.detail?.messageId && event.detail?.content) {
        setEditingMessageId(event.detail.messageId);
        setInput(event.detail.content);
        // Focus the textarea and adjust height
        setTimeout(() => {
          if (textareaRef.current) {
            textareaRef.current.focus();
            textareaRef.current.select();
            adjustTextareaHeight();
          }
        }, 0);
      }
    };

    window.addEventListener('edit-message', handleEditMessage as EventListener);
    return () => {
      window.removeEventListener('edit-message', handleEditMessage as EventListener);
    };
  }, []);

  // Listen for resend-message event (triggered when editing a message)
  useEffect(() => {
    const handleResendMessage = async (event: CustomEvent) => {
      if (event.detail?.content && currentProject && currentConversation) {
        const userMessage = event.detail.content;
        addMessage({ role: 'user', content: userMessage });
        setLoading(true);
        
        // Send the message via WebSocket or REST
        try {
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
              addMessage({ role: 'assistant', content: streamedContent });
              clearStreaming();
              ws.close();
            } else if (data.type === 'error') {
              console.error('WebSocket error:', data.content);
              clearStreaming();
              ws.close();
              addMessage({ 
                role: 'assistant', 
                content: `Error: ${data.content}` 
              });
              setLoading(false);
            }
          };
          
            ws.onerror = async () => {
              clearStreaming();
              ws.close();
              // Fallback to REST API
              try {
                const response = await axios.post('http://localhost:8000/api/chat', {
                  project_id: currentProject.id,
                  conversation_id: currentConversation.id,
                  target_name: currentConversation.targetName,
                  message: userMessage
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
        } catch (error) {
          console.error('WebSocket connection failed, using REST:', error);
          // Fallback to REST API
          try {
            const response = await axios.post('http://localhost:8000/api/chat', {
              project_id: currentProject.id,
              conversation_id: currentConversation.id,
              target_name: currentConversation.targetName,
              message: userMessage
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
        }
      }
    };

    window.addEventListener('resend-message', handleResendMessage as EventListener);
    return () => {
      window.removeEventListener('resend-message', handleResendMessage as EventListener);
    };
  }, [currentProject, currentConversation, addMessage, setLoading, setStreaming, updateStreamingContent, clearStreaming]);

  const handleCancelEdit = () => {
    setEditingMessageId(null);
    setInput('');
  };

  return (
    <div 
      ref={dropZoneRef}
      className={`border-t border-[#565869] p-4 bg-[#343541] ${isDragging ? 'bg-[#40414f] border-[#19c37d] border-2' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="max-w-4xl mx-auto">
        {editingMessageId && (
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm text-[#8e8ea0]">Editing message</span>
            <button
              onClick={handleCancelEdit}
              className="p-1 hover:bg-[#565869] rounded transition-colors text-[#8e8ea0] hover:text-white"
              title="Cancel editing"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        )}
        {uploadedFiles.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {uploadedFiles.map((file, idx) => (
              <div key={idx} className="relative group">
                {file.base64 ? (
                  // Image preview - clickable
                  <div className="relative cursor-pointer" onClick={() => setPreviewFile({name: file.name, data: file.base64!, type: 'image', mimeType: file.mimeType})}>
                    <img 
                      src={file.base64} 
                      alt={file.name}
                      className="max-w-[200px] max-h-[200px] rounded-lg border border-[#565869] object-cover hover:border-[#19c37d] transition-colors"
                    />
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setUploadedFiles(prev => prev.filter((_, i) => i !== idx));
                      }}
                      className="absolute -top-2 -right-2 w-6 h-6 bg-red-600 hover:bg-red-700 rounded-full flex items-center justify-center transition-colors opacity-0 group-hover:opacity-100 z-10"
                      title="Remove file"
                    >
                      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                    <div className="absolute bottom-0 left-0 right-0 bg-black/70 text-white text-xs px-2 py-1 rounded-b-lg truncate">
                      {file.name}
                    </div>
                  </div>
                ) : (
                  // Document preview (PDF, etc.) - clickable
                  <div 
                    className="relative bg-[#40414f] border border-[#565869] rounded-lg p-3 min-w-[200px] max-w-[300px] cursor-pointer hover:border-[#19c37d] transition-colors"
                    onClick={() => {
                      // Construct preview path - server returns path relative to project root (includes 'uploads/')
                      // Format: uploads/project_id/conversation_id/filename
                      // Endpoint expects path after /uploads/, so strip the prefix
                      let previewPath = '';
                      if (file.path) {
                        // Strip 'uploads/' prefix if present
                        const cleanPath = file.path.startsWith('uploads/') ? file.path.substring(8) : file.path;
                        previewPath = `http://localhost:8000/uploads/${cleanPath}`;
                      }
                      
                      const fileName = file.name.toLowerCase();
                      if (file.mimeType === 'application/pdf' || fileName.endsWith('.pdf')) {
                        setPreviewFile({name: file.name, data: previewPath, type: 'pdf', mimeType: file.mimeType});
                      } else if (fileName.endsWith('.pptx') || fileName.endsWith('.ppt')) {
                        setPreviewFile({name: file.name, data: previewPath, type: 'pptx', mimeType: file.mimeType});
                      } else if (fileName.endsWith('.xlsx') || fileName.endsWith('.xls')) {
                        // Convert path for Excel preview API
                        let cleanPath = previewPath.replace('http://localhost:8000/uploads/', '');
                        if (cleanPath.startsWith('uploads/')) {
                          cleanPath = cleanPath.substring(8);
                        }
                        setPreviewFile({name: file.name, data: `http://localhost:8000/api/xlsx-preview/${cleanPath}`, type: 'xlsx', mimeType: file.mimeType});
                      } else if (fileName.endsWith('.docx') || fileName.endsWith('.doc')) {
                        // Convert path for Word preview API
                        let cleanPath = previewPath.replace('http://localhost:8000/uploads/', '');
                        if (cleanPath.startsWith('uploads/')) {
                          cleanPath = cleanPath.substring(8);
                        }
                        setPreviewFile({name: file.name, data: `http://localhost:8000/api/docx-preview/${cleanPath}`, type: 'docx', mimeType: file.mimeType});
                      } else {
                        setPreviewFile({name: file.name, data: previewPath, type: 'other', mimeType: file.mimeType});
                      }
                    }}
                  >
                    <div className="flex items-start gap-3">
                      <div className="flex-shrink-0">
                        {file.mimeType === 'application/pdf' ? (
                          <svg className="w-10 h-10 text-red-500" fill="currentColor" viewBox="0 0 24 24">
                            <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" />
                          </svg>
                        ) : file.mimeType?.includes('word') || file.mimeType?.includes('document') ? (
                          <svg className="w-10 h-10 text-blue-500" fill="currentColor" viewBox="0 0 24 24">
                            <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" />
                          </svg>
                        ) : (
                          <svg className="w-10 h-10 text-[#8e8ea0]" fill="currentColor" viewBox="0 0 24 24">
                            <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" />
                          </svg>
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-white truncate">{file.name}</p>
                        <p className="text-xs text-[#8e8ea0] mt-1">
                          {(() => {
                            // Get file extension from filename
                            const ext = file.name.split('.').pop()?.toUpperCase() || '';
                            // Map common extensions to clean names (fallback to extension itself)
                            const extMap: Record<string, string> = {
                              'PDF': 'PDF',
                              'DOC': 'DOC',
                              'DOCX': 'DOCX',
                              'PPT': 'PPT',
                              'PPTX': 'PPTX',
                              'XLS': 'XLS',
                              'XLSX': 'XLSX',
                              'TXT': 'TXT',
                              'PNG': 'PNG',
                              'JPG': 'JPG',
                              'JPEG': 'JPEG',
                              'GIF': 'GIF',
                              'SVG': 'SVG',
                              'WEBP': 'WEBP',
                              'ZIP': 'ZIP',
                              'RAR': 'RAR',
                              '7Z': '7Z',
                              'CSV': 'CSV',
                              'JSON': 'JSON',
                              'XML': 'XML',
                              'HTML': 'HTML',
                              'MP4': 'MP4',
                              'MP3': 'MP3',
                              'MOV': 'MOV',
                              'AVI': 'AVI'
                            };
                            // If extension is in map, use it; otherwise use the extension itself; fallback to 'FILE'
                            return extMap[ext] || ext || 'FILE';
                          })()}
                        </p>
                      </div>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setUploadedFiles(prev => prev.filter((_, i) => i !== idx));
                        }}
                        className="flex-shrink-0 w-6 h-6 bg-red-600 hover:bg-red-700 rounded-full flex items-center justify-center transition-colors opacity-0 group-hover:opacity-100 z-10"
                        title="Remove file"
                      >
                        <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        {isDragging && (
          <div className="mb-2 text-center text-[#19c37d] text-sm">
            Drop files here to upload
          </div>
        )}
        <div className="flex gap-2 items-end">
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                adjustTextareaHeight();
              }}
              onKeyPress={handleKeyPress}
              placeholder={editingMessageId ? "Edit your message..." : "Message ChatDO..."}
              className="w-full p-3 pr-20 bg-[#40414f] text-white rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-[#19c37d] overflow-y-auto"
              style={{ minHeight: '44px', maxHeight: '300px', height: '44px' }}
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
          disabled={(!input.trim() && uploadedFiles.length === 0) || !currentProject || !currentConversation || isUploading}
          className="h-[44px] px-4 py-2 bg-[#19c37d] text-white rounded-lg hover:bg-[#15a06a] disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex-shrink-0"
        >
          {editingMessageId ? 'Save & send' : 'Send'}
        </button>
        </div>
      </div>
      
      {/* File Preview Modal */}
      {previewFile && (
        <div 
          className="fixed inset-0 bg-black/80 z-[9999] flex items-center justify-center p-4"
          onClick={() => setPreviewFile(null)}
        >
          <div 
            className="bg-[#343541] rounded-lg max-w-4xl max-h-[90vh] w-full overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-4 border-b border-[#565869]">
              <h3 className="text-lg font-semibold text-white truncate">{previewFile.name}</h3>
              <button
                onClick={() => setPreviewFile(null)}
                className="p-2 hover:bg-[#565869] rounded transition-colors text-[#8e8ea0] hover:text-white"
                title="Close preview"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="flex-1 overflow-auto p-4">
              {previewFile.type === 'image' ? (
                <img 
                  src={previewFile.data} 
                  alt={previewFile.name}
                  className="max-w-full max-h-full mx-auto object-contain"
                />
              ) : previewFile.type === 'pdf' ? (
                <iframe
                  src={previewFile.data}
                  className="w-full h-[80vh] border border-[#565869] rounded"
                  title={previewFile.name}
                />
              ) : previewFile.type === 'xlsx' ? (
                <iframe
                  src={previewFile.data}
                  className="w-full h-[80vh] border border-[#565869] rounded"
                  title={previewFile.name}
                />
              ) : previewFile.type === 'docx' ? (
                <iframe
                  src={previewFile.data}
                  className="w-full h-[80vh] border border-[#565869] rounded"
                  title={previewFile.name}
                />
              ) : (
                <div className="text-center text-[#8e8ea0] py-8">
                  <p>Preview not available for this file type.</p>
                  <p className="text-sm mt-2">File: {previewFile.name}</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ChatComposer;

