import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { useChatStore } from '../store/chat';
import axios from 'axios';

// Component for PPTX preview - converts to PDF for beautiful preview like PDFs!
const PPTXPreview: React.FC<{filePath: string, fileName: string}> = ({ filePath, fileName }) => {
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  useEffect(() => {
    if (!filePath) {
      setError('No file path provided');
      setLoading(false);
      return;
    }
    
    // Extract the path - filePath might be full URL or just the path
    // Server returns: uploads/project_id/conversation_id/file.pptx
    // We need: project_id/conversation_id/file.pptx for the API
    let apiPath = filePath;
    if (filePath.startsWith('http://localhost:8000/uploads/')) {
      apiPath = filePath.replace('http://localhost:8000/uploads/', '');
    } else if (filePath.startsWith('uploads/')) {
      apiPath = filePath.replace('uploads/', '');
    }
    
    // The API converts PPTX to PDF and returns it
    // We'll use it in an iframe just like PDFs
    const previewUrl = `http://localhost:8000/api/pptx-preview/${apiPath}`;
    setPdfUrl(previewUrl);
    setLoading(false);
  }, [filePath]);
  
  if (loading) {
    return (
      <div className="text-center text-[#8e8ea0] py-8">
        <div className="animate-spin h-8 w-8 border-4 border-[#19c37d] border-t-transparent rounded-full mx-auto mb-4"></div>
        <p>Converting presentation to PDF for preview...</p>
      </div>
    );
  }
  
  if (error) {
    return (
      <div className="text-[#ececf1]">
        <div className="mb-4 p-4 bg-[#40414f] rounded-lg">
          <h4 className="text-lg font-semibold mb-2">{fileName}</h4>
          <p className="text-sm text-[#8e8ea0]">{error}</p>
          <p className="text-sm text-[#8e8ea0] mt-2">The file has been uploaded and ChatDO can process its content.</p>
          {filePath && (
            <a 
              href={filePath} 
              target="_blank" 
              rel="noopener noreferrer"
              className="mt-4 inline-block px-4 py-2 bg-[#19c37d] text-white rounded hover:bg-[#15a06a] transition-colors"
            >
              Download File
            </a>
          )}
        </div>
      </div>
    );
  }
  
  // Show PDF preview in iframe (same beautiful experience as PDFs!)
  return (
    <div className="w-full h-full">
      {pdfUrl ? (
        <iframe
          src={pdfUrl}
          className="w-full h-[80vh] border border-[#565869] rounded"
          title={fileName}
          onError={() => setError('Failed to load converted PDF')}
        />
      ) : (
        <div className="text-center text-[#8e8ea0] py-8">
          <p>Preparing preview...</p>
        </div>
      )}
    </div>
  );
};

const ChatMessages: React.FC = () => {
  const { 
    messages, 
    isStreaming, 
    streamingContent, 
    isLoading,
    currentConversation, 
    currentProject, 
    setViewMode, 
    viewMode, 
    renameChat,
    deleteMessage
  } = useChatStore();
  
  const [previewFile, setPreviewFile] = useState<{name: string, data: string, type: 'image' | 'pdf' | 'pptx' | 'other', mimeType: string} | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [editTitleValue, setEditTitleValue] = useState('');
  const titleInputRef = useRef<HTMLInputElement>(null);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);

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

  const handleTitleClick = () => {
    if (currentConversation && !currentConversation.trashed) {
      setEditTitleValue(currentConversation.title);
      setIsEditingTitle(true);
    }
  };

  const handleTitleSave = async () => {
    if (!currentConversation || currentConversation.trashed) return;
    
    const newTitle = editTitleValue.trim();
    if (newTitle && newTitle !== currentConversation.title) {
      try {
        await renameChat(currentConversation.id, newTitle);
      } catch (error) {
        console.error('Failed to rename chat:', error);
        alert('Failed to rename chat. Please try again.');
      }
    }
    setIsEditingTitle(false);
  };

  const handleTitleCancel = () => {
    setIsEditingTitle(false);
    setEditTitleValue('');
  };

  const handleTitleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleTitleSave();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      handleTitleCancel();
    }
  };

  // Focus input when editing starts
  useEffect(() => {
    if (isEditingTitle && titleInputRef.current) {
      titleInputRef.current.focus();
      titleInputRef.current.select();
    }
  }, [isEditingTitle]);

  const handleCopyMessage = async (content: string, messageId: string) => {
    try {
      // Strip markdown for plain text copy
      const plainText = content.replace(/[#*`_~\[\]()]/g, '').trim();
      await navigator.clipboard.writeText(plainText);
      
      // Show feedback
      setCopiedMessageId(messageId);
      setTimeout(() => {
        setCopiedMessageId(null);
      }, 2000);
    } catch (error) {
      console.error('Failed to copy message:', error);
      // Fallback for older browsers
      const textArea = document.createElement('textarea');
      textArea.value = content.replace(/[#*`_~\[\]()]/g, '').trim();
      document.body.appendChild(textArea);
      textArea.select();
      document.execCommand('copy');
      document.body.removeChild(textArea);
      
      // Show feedback
      setCopiedMessageId(messageId);
      setTimeout(() => {
        setCopiedMessageId(null);
      }, 2000);
    }
  };

  const handleEditMessage = (messageId: string, currentContent: string) => {
    // Dispatch event to ChatComposer to populate input
    window.dispatchEvent(new CustomEvent('edit-message', { 
      detail: { messageId, content: currentContent } 
    }));
  };

  const handleDeleteMessage = (messageId: string) => {
    if (window.confirm('Delete this message and all messages after it?')) {
      deleteMessage(messageId);
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
            <>
              {isEditingTitle ? (
                <input
                  ref={titleInputRef}
                  type="text"
                  value={editTitleValue}
                  onChange={(e) => setEditTitleValue(e.target.value)}
                  onBlur={handleTitleSave}
                  onKeyDown={handleTitleKeyDown}
                  className="text-lg font-semibold text-[#ececf1] bg-[#40414f] border border-[#565869] rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-[#19c37d] min-w-[200px] max-w-[400px]"
                  onClick={(e) => e.stopPropagation()}
                />
              ) : (
                <h2 
                  className="text-lg font-semibold text-[#ececf1] cursor-pointer hover:text-white transition-colors"
                  onClick={handleTitleClick}
                  title="Click to edit chat name"
                >
                  {currentConversation.title}
                </h2>
              )}
            </>
          )}
        </div>
      )}

      {/* Messages */}
      <div ref={messagesContainerRef} className="flex-1 overflow-y-auto p-4 space-y-4">
      {messages.map((message) => {
        const isCopied = copiedMessageId === message.id;
        
        return (
          <div
            key={message.id}
            className={`group flex gap-4 ${
              message.role === 'user' ? 'justify-end' : 'justify-start'
            }`}
          >
            {message.role === 'assistant' && (
              <div className="w-8 h-8 rounded-full bg-[#19c37d] flex items-center justify-center flex-shrink-0">
                <span className="text-white text-sm font-bold">C</span>
              </div>
            )}
            
            <div className="flex flex-col">
              <>
                {/* Display images outside the message bubble for user messages */}
                {message.role === 'user' && (() => {
                  const imagePatternOld = /\[Image: ([^\]]+)\]\n(data:image\/[^;]+;base64[^\n]*)\n\[File path: ([^\]]+)\]/g;
                  const imagePatternNew = /\[Image: ([^\]]+)\]\n\[File path: ([^\]]+)\]/g;
                  const imageMatchesOld = [...message.content.matchAll(imagePatternOld)];
                  const imageMatchesNew = [...message.content.matchAll(imagePatternNew)];
                  
                  if (imageMatchesOld.length > 0 || imageMatchesNew.length > 0) {
                    return (
                      <div className="mb-2 space-y-2 flex flex-col items-end">
                        {imageMatchesOld.map((match, idx) => {
                          const cleanPath = match[3].startsWith('uploads/') ? match[3].substring(8) : match[3];
                          const imageSrc = match[2] || `http://localhost:8000/uploads/${cleanPath}`;
                          return (
                            <div 
                              key={idx} 
                              className="inline-block rounded-lg overflow-hidden border border-white/20 cursor-pointer hover:border-[#19c37d] transition-colors max-w-[20%] bg-transparent"
                              onClick={() => setPreviewFile({name: match[1], data: imageSrc, type: 'image', mimeType: ''})}
                              title="Click to view full size"
                            >
                              <img 
                                src={imageSrc}
                                alt={match[1]}
                                className="w-full h-auto object-contain"
                                loading="lazy"
                              />
                              <div className="px-2 py-1 bg-black/30 text-xs truncate text-white">
                                {match[1]}
                              </div>
                            </div>
                          );
                        })}
                        {imageMatchesNew.map((match, idx) => {
                          const cleanPath = match[2].startsWith('uploads/') ? match[2].substring(8) : match[2];
                          const imageSrc = `http://localhost:8000/uploads/${cleanPath}`;
                          return (
                            <div 
                              key={`new-${idx}`} 
                              className="inline-block rounded-lg overflow-hidden border border-white/20 cursor-pointer hover:border-[#19c37d] transition-colors max-w-[20%] bg-transparent"
                              onClick={() => setPreviewFile({name: match[1], data: imageSrc, type: 'image', mimeType: ''})}
                              title="Click to view full size"
                            >
                              <img 
                                src={imageSrc}
                                alt={match[1]}
                                className="w-full h-auto object-contain"
                                loading="lazy"
                              />
                              <div className="px-2 py-1 bg-black/30 text-xs truncate text-white">
                                {match[1]}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    );
                  }
                  return null;
                })()}
                {(() => {
                  // Parse content first to determine if we should show the bubble
                  const imagePatternOld = /\[Image: ([^\]]+)\]\n(data:image\/[^;]+;base64[^\n]*)\n\[File path: ([^\]]+)\]/g;
                  const imagePatternNew = /\[Image: ([^\]]+)\]\n\[File path: ([^\]]+)\]/g;
                  const docPatternOld = /\[File: ([^\]]+)\]\n\[File path: ([^\]]+)\]\n\[MIME type: ([^\]]+)\]/g;
                  const docPatternNew = /\[File: ([^\]]+)\]\n\n([\s\S]*?)(?=\n\n\[File: |\n\n\[Image: |$|$)/g;
                  
                  let content = message.content;
                  const files: Array<{name: string, type: 'image' | 'doc', data?: string, path: string, mimeType?: string}> = [];
                  
                  // Extract images
                  const imageMatchesOld = [...message.content.matchAll(imagePatternOld)];
                  imageMatchesOld.forEach(match => {
                    if (!files.some(f => f.name === match[1] && f.type === 'image')) {
                      files.push({
                        name: match[1],
                        type: 'image',
                        data: match[2],
                        path: match[3]
                      });
                      content = content.replace(match[0], '');
                    }
                  });
                  
                  const imageMatchesNew = [...message.content.matchAll(imagePatternNew)];
                  imageMatchesNew.forEach(match => {
                    if (!files.some(f => f.name === match[1] && f.type === 'image')) {
                      files.push({
                        name: match[1],
                        type: 'image',
                        data: undefined,
                        path: match[2]
                      });
                      content = content.replace(match[0], '');
                    }
                  });
                  
                  // Extract documents
                  const docPatternNewWithPath = /\[File: ([^\]]+)\]\n\[File path: ([^\]]+)\]\n\[MIME type: ([^\]]+)\](?:\n\n([\s\S]*?))?(?=\n\n\[File: |\n\n\[Image: |$|$)/g;
                  const docMatchesNewWithPath = [...message.content.matchAll(docPatternNewWithPath)];
                  docMatchesNewWithPath.forEach(match => {
                    files.push({
                      name: match[1],
                      type: 'doc',
                      path: match[2],
                      mimeType: match[3]
                    });
                    const escapedName = match[1].replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                    const fileSectionPattern = new RegExp(
                      `\\[File: ${escapedName}\\]\\n\\[File path: [^\\]]+\\]\\n\\[MIME type: [^\\]]+\\](?:\\n\\n[\\s\\S]*?)?(?=\\n\\n\\[File: |\\n\\n\\[Image: |$)`,
                      'g'
                    );
                    content = content.replace(fileSectionPattern, '');
                  });
                  
                  const docMatchesNew = [...message.content.matchAll(docPatternNew)];
                  docMatchesNew.forEach(match => {
                    if (!files.some(f => f.name === match[1])) {
                      const fileName = match[1];
                      let mimeType = '';
                      if (fileName.toLowerCase().endsWith('.pdf')) {
                        mimeType = 'application/pdf';
                      } else if (fileName.toLowerCase().endsWith('.pptx') || fileName.toLowerCase().endsWith('.ppt')) {
                        mimeType = 'application/vnd.openxmlformats-officedocument.presentationml.presentation';
                      } else if (fileName.toLowerCase().endsWith('.docx') || fileName.toLowerCase().endsWith('.doc')) {
                        mimeType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
                      }
                      
                      files.push({
                        name: match[1],
                        type: 'doc',
                        path: '',
                        mimeType: mimeType
                      });
                      const escapedName = match[1].replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                      const fileSectionPattern = new RegExp(
                        `\\[File: ${escapedName}\\]\\n\\n[\\s\\S]*?(?=\\n\\n\\[File: |\\n\\n\\[Image: |$)`,
                        'g'
                      );
                      content = content.replace(fileSectionPattern, '');
                    }
                  });
                  
                  const docMatchesOld = [...message.content.matchAll(docPatternOld)];
                  docMatchesOld.forEach(match => {
                    if (!files.some(f => f.name === match[1])) {
                      files.push({
                        name: match[1],
                        type: 'doc',
                        path: match[2],
                        mimeType: match[3]
                      });
                      const fileSectionPattern = new RegExp(
                        `\\[File: ${match[1].replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\]\\n\\[File path: [^\\]]+\\]\\n\\[MIME type: [^\\]]+\\](\\n\\n--- File Content ---[\\s\\S]*?--- End File Content ---)?`,
                        'g'
                      );
                      content = content.replace(fileSectionPattern, '');
                    }
                  });
                  
                  content = content.replace(/\[File uploaded: [^\]]+\]/g, '');
                  content = content.replace(/\[File path: [^\]]+\]/g, '');
                  content = content.trim();
                  
                  const filesToShow = message.role === 'user' ? files.filter(f => f.type !== 'image') : files;
                  const hasContent = content.trim().length > 0 || filesToShow.length > 0;
                  
                  if (!hasContent) {
                    return null;
                  }
                  
                  return (
                    <div
                      className={`max-w-3xl rounded-lg px-4 py-3 ${
                        message.role === 'user'
                          ? 'bg-[#19c37d] text-white'
                          : 'bg-[#444654] text-[#ececf1]'
                      }`}
                    >
                      {/* Display files (documents, or all files for assistant) inside the message bubble */}
                      {filesToShow.length > 0 && (
                        <div className={`mb-3 space-y-2 ${message.role === 'user' ? '' : ''}`}>
                          {filesToShow.map((file, idx) => (
                            file.type === 'image' ? (
                              <div 
                                key={idx} 
                                className="inline-block rounded-lg overflow-hidden border border-white/20 cursor-pointer hover:border-[#19c37d] transition-colors max-w-[25%] bg-transparent"
                                onClick={() => {
                                  // Use file path to load image if base64 not available
                                  let imageSrc = file.data;
                                  if (!imageSrc && file.path) {
                                    const cleanPath = file.path.startsWith('uploads/') ? file.path.substring(8) : file.path;
                                    imageSrc = `http://localhost:8000/uploads/${cleanPath}`;
                                  }
                                  if (imageSrc) {
                                    setPreviewFile({name: file.name, data: imageSrc, type: 'image', mimeType: file.mimeType || ''});
                                  }
                                }}
                                title="Click to view full size"
                              >
                                {file.data ? (
                                  <img 
                                    src={file.data} 
                                    alt={file.name}
                                    className="w-full h-auto object-contain"
                                    loading="lazy"
                                  />
                                ) : file.path ? (
                                  <img 
                                    src={`http://localhost:8000/uploads/${file.path.startsWith('uploads/') ? file.path.substring(8) : file.path}`}
                                    alt={file.name}
                                    className="w-full h-auto object-contain"
                                    loading="lazy"
                                  />
                                ) : null}
                                <div className="px-2 py-1 bg-black/30 text-xs truncate text-white">
                                  {file.name}
                                </div>
                              </div>
                            ) : (
                              <div 
                                key={idx} 
                                className="flex items-center gap-3 p-3 bg-black/20 rounded border border-white/20 cursor-pointer hover:border-[#19c37d] transition-colors"
                                onClick={() => {
                                  // Get path from file object
                                  const filePath = file.path || '';
                                  const fileName = file.name.toLowerCase();
                                  
                                  // The path from server is relative to project root (includes 'uploads/')
                                  // Server returns: uploads/project_id/conversation_id/filename
                                  // Endpoint expects: /uploads/project_id/conversation_id/filename
                                  // But endpoint adds 'uploads/' itself, so we need to strip it
                                  let previewPath = '';
                                  if (filePath) {
                                    // Strip 'uploads/' prefix if present
                                    const cleanPath = filePath.startsWith('uploads/') ? filePath.substring(8) : filePath;
                                    previewPath = `http://localhost:8000/uploads/${cleanPath}`;
                                  }
                                  
                                  if (file.mimeType === 'application/pdf' || fileName.endsWith('.pdf')) {
                                    setPreviewFile({name: file.name, data: previewPath, type: 'pdf', mimeType: file.mimeType || 'application/pdf'});
                                  } else if (fileName.endsWith('.pptx') || fileName.endsWith('.ppt')) {
                                    setPreviewFile({name: file.name, data: previewPath, type: 'pptx', mimeType: file.mimeType || 'application/vnd.openxmlformats-officedocument.presentationml.presentation'});
                                  } else if (fileName.endsWith('.xlsx') || fileName.endsWith('.xls')) {
                                    // Convert path for Excel preview API
                                    // previewPath is already http://localhost:8000/uploads/... so strip that prefix
                                    let cleanPath = previewPath.replace('http://localhost:8000/uploads/', '');
                                    // If it still has uploads/ prefix, strip it
                                    if (cleanPath.startsWith('uploads/')) {
                                      cleanPath = cleanPath.substring(8);
                                    }
                                    setPreviewFile({name: file.name, data: `http://localhost:8000/api/xlsx-preview/${cleanPath}`, type: 'xlsx', mimeType: file.mimeType || 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
                                  } else if (fileName.endsWith('.docx') || fileName.endsWith('.doc')) {
                                    // Convert path for Word preview API
                                    let cleanPath = previewPath.replace('http://localhost:8000/uploads/', '');
                                    if (cleanPath.startsWith('uploads/')) {
                                      cleanPath = cleanPath.substring(8);
                                    }
                                    setPreviewFile({name: file.name, data: `http://localhost:8000/api/docx-preview/${cleanPath}`, type: 'docx', mimeType: file.mimeType || 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'});
                                  } else {
                                    setPreviewFile({name: file.name, data: previewPath, type: 'other', mimeType: file.mimeType || ''});
                                  }
                                }}
                              >
                                <div className="flex-shrink-0">
                                  {file.mimeType === 'application/pdf' ? (
                                    <svg className="w-10 h-10 text-red-300" fill="currentColor" viewBox="0 0 24 24">
                                      <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" />
                                    </svg>
                                  ) : (
                                    <svg className="w-10 h-10 text-white/70" fill="currentColor" viewBox="0 0 24 24">
                                      <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" />
                                    </svg>
                                  )}
                                </div>
                                <div className="flex-1 min-w-0">
                                  <p className="text-sm font-medium truncate">{file.name}</p>
                                  <p className="text-xs opacity-75 mt-1">
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
                              </div>
                            )
                          ))}
                        </div>
                      )}
                      
                      {/* Display text content if any */}
                      {content && (
                        message.role === 'assistant' ? (
                          <div className="prose prose-invert max-w-none">
                            <ReactMarkdown>{content}</ReactMarkdown>
                          </div>
                        ) : (
                          <p className="whitespace-pre-wrap">{content}</p>
                        )
                      )}
                    </div>
                  );
                })()}
                {/* Action buttons - positioned below message */}
                <div className={`flex gap-2 mt-1 ${
                  message.role === 'user' ? 'justify-end' : 'justify-start'
                } opacity-0 group-hover:opacity-100 transition-opacity`}>
                {message.role === 'user' ? (
                  <>
                    <button
                      onClick={() => handleCopyMessage(message.content, message.id)}
                      className="p-1.5 hover:bg-[#565869]/50 rounded transition-colors text-[#8e8ea0] hover:text-white flex items-center gap-1"
                      title="Copy message"
                    >
                      {isCopied ? (
                        <>
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                          </svg>
                          <span className="text-xs">Copied!</span>
                        </>
                      ) : (
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                        </svg>
                      )}
                    </button>
                    <button
                      onClick={() => handleEditMessage(message.id, message.content)}
                      className="p-1.5 hover:bg-[#565869]/50 rounded transition-colors text-[#8e8ea0] hover:text-white"
                      title="Edit message"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                      </svg>
                    </button>
                    <button
                      onClick={() => handleDeleteMessage(message.id)}
                      className="p-1.5 hover:bg-[#565869]/50 rounded transition-colors text-[#8e8ea0] hover:text-white"
                      title="Delete message"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => handleCopyMessage(message.content, message.id)}
                    className="p-1.5 hover:bg-[#565869]/50 rounded transition-colors text-[#8e8ea0] hover:text-white flex items-center gap-1"
                    title="Copy message"
                  >
                    {isCopied ? (
                      <>
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                        </svg>
                        <span className="text-xs">Copied!</span>
                      </>
                    ) : (
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                      </svg>
                    )}
                  </button>
                )}
                </div>
              </>
            </div>
            
            {message.role === 'user' && (
              <div className="w-8 h-8 rounded-full bg-[#5436da] flex items-center justify-center flex-shrink-0">
                <span className="text-white text-sm font-bold">U</span>
              </div>
            )}
          </div>
        );
      })}
      
      {/* Streaming content */}
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
              ) : previewFile.type === 'pptx' ? (
                <PPTXPreview filePath={previewFile.data} fileName={previewFile.name} />
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
                  {previewFile.data && (
                    <a 
                      href={previewFile.data} 
                      target="_blank" 
                      rel="noopener noreferrer"
                      className="mt-4 inline-block px-4 py-2 bg-[#19c37d] text-white rounded hover:bg-[#15a06a] transition-colors"
                    >
                      Download File
                    </a>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ChatMessages;

