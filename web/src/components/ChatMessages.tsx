import React, { useEffect, useRef, useState, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import { useChatStore, type Message } from '../store/chat';
import axios from 'axios';
import ArticleCard from './ArticleCard';
import DocumentCard from './DocumentCard';
import RagResponseCard from './RagResponseCard';
import { MessageRenderer } from './MessageRenderer';
import type { RagFile } from '../types/rag';

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
          className="w-full h-full border border-[#565869] rounded"
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
    deleteMessage,
    isSummarizingArticle,
    setSummarizingArticle,
    isRagTrayOpen,
    ragFileIds, // Get ragFileIds to match backend order
    getRagFilesForConversation, // Get conversation-scoped RAG files
  } = useChatStore();
  
  // Track which articles are being summarized or have been summarized
  const [articleStates, setArticleStates] = useState<Record<string, 'idle' | 'summarizing' | 'summarized'>>({});
  
  const [previewFile, setPreviewFile] = useState<{name: string, data: string, type: 'image' | 'pdf' | 'pptx' | 'xlsx' | 'docx' | 'video' | 'other', mimeType: string} | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [editTitleValue, setEditTitleValue] = useState('');
  const titleInputRef = useRef<HTMLInputElement>(null);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const previewModalRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  
  // Get RAG files from store (conversation-scoped)
  const ragFiles: RagFile[] = useMemo(() => {
    return getRagFilesForConversation(currentConversation?.id || null);
  }, [currentConversation?.id, getRagFilesForConversation]);

  // Compute indexed RAG files once - this is the single source of truth
  // CRITICAL: Use ragFileIds order to match backend numbering (not created_at order!)
  // Only files with text_extracted get numbered (1-based)
  const ragFilesWithIndex = useMemo(() => {
    if (!ragFileIds || ragFileIds.length === 0) return [];
    
    // Create a lookup map for fast access
    const filesById = new Map<string, RagFile>(ragFiles.map((f: RagFile) => [f.id, f]));
    
    // Build indexed files in the SAME ORDER as ragFileIds (matches backend)
    const indexed: RagFile[] = [];
    ragFileIds.forEach((fileId: string) => {
      const file = filesById.get(fileId);
      if (file && file.text_extracted) {
        indexed.push({
          ...file,
          index: indexed.length + 1, // 1-based index, only counting ready files
        } as RagFile);
      }
    });
    
    return indexed;
  }, [ragFiles, ragFileIds]);

  // Handler to open RAG file in preview - accepts file object
  const handleOpenRagFile = async (file: RagFile) => {
    if (!file) {
      console.error('[RAG] File not provided');
      return;
    }

    console.log('[RAG] Opening file:', file.filename, 'path:', file.path, 'text_path:', file.text_path);

    // Use stored path if available
    let previewPath = '';
    let apiPath = '';
    
    if (file.path) {
      // path format from backend: uploads/rag/chat_id/uuid.ext
      // For direct file access: http://localhost:8000/uploads/rag/chat_id/uuid.ext
      // For API endpoints: rag/chat_id/uuid.ext (without uploads/ prefix)
      if (file.path.startsWith('uploads/')) {
        apiPath = file.path.substring(8); // Remove "uploads/" prefix
        previewPath = `http://localhost:8000/${file.path}`;
      } else {
        apiPath = file.path;
        previewPath = `http://localhost:8000/uploads/${file.path}`;
      }
    } else if (file.text_path) {
      // Fallback: find original file by querying the backend
      // text_path format: uploads/rag/chat_id/uuid.txt
      // We need to find the original file in the same directory
      try {
        // Query backend to find the original file
        const response = await axios.get(`http://localhost:8000/api/rag/find-original`, {
          params: {
            text_path: file.text_path,
            mime_type: file.mime_type
          }
        });
        
        if (response.data && response.data.path) {
          const foundPath = response.data.path;
          if (foundPath.startsWith('uploads/')) {
            apiPath = foundPath.substring(8);
            previewPath = `http://localhost:8000/${foundPath}`;
          } else {
            apiPath = foundPath;
            previewPath = `http://localhost:8000/uploads/${foundPath}`;
          }
        } else {
          console.error('[RAG] Could not find original file for:', file.filename);
          alert(`Unable to open file: ${file.filename}. The file may have been moved or deleted.`);
          return;
        }
      } catch (error) {
        console.error('[RAG] Error finding original file:', error);
        alert(`Unable to open file: ${file.filename}. Please try re-uploading the file.`);
        return;
      }
    } else {
      console.error('[RAG] No path or text_path available for file:', file.filename);
      alert(`Unable to open file: ${file.filename}. File path information is missing.`);
      return;
    }

    console.log('[RAG] Preview path:', previewPath, 'API path:', apiPath);

    const mimeType = file.mime_type;

    if (mimeType === 'application/pdf') {
      setPreviewFile({ name: file.filename, data: previewPath, type: 'pdf', mimeType });
    } else if (mimeType.includes('presentation') || mimeType.includes('powerpoint')) {
      // URL encode the path segments to handle special characters
      const encodedPath = apiPath.split('/').map(segment => encodeURIComponent(segment)).join('/');
      setPreviewFile({ name: file.filename, data: `http://localhost:8000/api/pptx-preview/${encodedPath}`, type: 'pptx', mimeType });
    } else if (mimeType.includes('spreadsheet') || mimeType.includes('excel') || mimeType.includes('sheet')) {
      // URL encode the path segments to handle special characters
      const encodedPath = apiPath.split('/').map(segment => encodeURIComponent(segment)).join('/');
      setPreviewFile({ name: file.filename, data: `http://localhost:8000/api/xlsx-preview/${encodedPath}`, type: 'xlsx', mimeType });
    } else if (mimeType.includes('word') || mimeType.includes('wordprocessing')) {
      // URL encode the path segments to handle special characters
      const encodedPath = apiPath.split('/').map(segment => encodeURIComponent(segment)).join('/');
      setPreviewFile({ name: file.filename, data: `http://localhost:8000/api/docx-preview/${encodedPath}`, type: 'docx', mimeType });
    } else {
      setPreviewFile({ name: file.filename, data: previewPath, type: 'other', mimeType });
    }
  };
  
  
  // Auto-scroll to bottom when messages change
  useEffect(() => {
    if (messagesEndRef.current && !isStreaming) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isStreaming]);

  // Separate effect for streaming content - debounced to prevent vibrating
  useEffect(() => {
    if (isStreaming && messagesEndRef.current) {
      // Use instant scroll (no smooth) and debounce to prevent jumping
      const timeoutId = setTimeout(() => {
        if (messagesEndRef.current) {
          messagesEndRef.current.scrollIntoView({ behavior: 'auto', block: 'end' });
        }
      }, 150); // Debounce to every 150ms during streaming
      return () => clearTimeout(timeoutId);
    }
  }, [streamingContent, isStreaming]);

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

  // Fullscreen functionality
  const toggleFullscreen = async () => {
    if (!previewModalRef.current) return;

    try {
      if (!document.fullscreenElement) {
        await previewModalRef.current.requestFullscreen();
        setIsFullscreen(true);
      } else {
        await document.exitFullscreen();
        setIsFullscreen(false);
      }
    } catch (error) {
      console.error('Error toggling fullscreen:', error);
    }
  };

  // Listen for fullscreen changes
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
    };
  }, []);

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

  const handleCopyMessage = async (content: string, messageId: string, messageData?: any) => {
    try {
      let textContent = content;
      
      // If this is an article_card, format it nicely
      if (messageData && messageData.url) {
        const copyText = [
          messageData.title && `${messageData.title}\n${messageData.url}\n`,
          messageData.summary && `Summary:\n${messageData.summary}`,
          messageData.keyPoints && messageData.keyPoints.length > 0 && `\n\nKey Points:\n${messageData.keyPoints.map((p: string) => `• ${p}`).join('\n')}`,
          messageData.whyMatters && `\n\nWhy This Matters:\n${messageData.whyMatters}`,
        ].filter(Boolean).join('\n');
        textContent = copyText;
      } else {
        // Strip markdown for plain text copy
        textContent = content.replace(/[#*`_~\[\]()]/g, '').trim();
      }
      
      await navigator.clipboard.writeText(textContent);
      
      // Show feedback
      setCopiedMessageId(messageId);
      setTimeout(() => {
        setCopiedMessageId(null);
      }, 2000);
    } catch (error) {
      console.error('Failed to copy message:', error);
      // Fallback for older browsers
      let textContent = content;
      if (messageData && messageData.url) {
        const copyText = [
          messageData.title && `${messageData.title}\n${messageData.url}\n`,
          messageData.summary && `Summary:\n${messageData.summary}`,
          messageData.keyPoints && messageData.keyPoints.length > 0 && `\n\nKey Points:\n${messageData.keyPoints.map((p: string) => `• ${p}`).join('\n')}`,
          messageData.whyMatters && `\n\nWhy This Matters:\n${messageData.whyMatters}`,
        ].filter(Boolean).join('\n');
        textContent = copyText;
      } else {
        textContent = content.replace(/[#*`_~\[\]()]/g, '').trim();
      }
      const textArea = document.createElement('textarea');
      textArea.value = textContent;
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

      {/* Main Content Area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Messages */}
        <div ref={messagesContainerRef} className={`flex-1 overflow-y-auto p-4 space-y-4 transition-all duration-300 ${isRagTrayOpen ? 'mr-80' : ''}`}>
          {messages.map((message: Message) => {
        const isCopied = copiedMessageId === message.id;
        
        const isAssistant = message.role === 'assistant';
        const isUser = message.role === 'user';
        
        // Parse content and files (needed for both assistant and user messages)
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
        const hasContent = content.trim().length > 0 || filesToShow.length > 0 || message.type === 'web_search_results' || message.type === 'article_card' || message.type === 'document_card' || message.type === 'rag_response';
        
        if (!hasContent) {
          return null;
        }
        
        return (
          <div
            key={message.id}
            className={`w-full flex group ${
              isAssistant ? 'chat-assistant' : ''
            } ${isUser ? 'chat-user' : ''}`}
          >
            {/* Avatar column */}
            <div className="mr-3 flex-shrink-0">
              {isAssistant ? (
                <div className="h-7 w-7 flex items-center justify-center rounded-full bg-emerald-500 text-xs font-semibold text-white">
                  C
                </div>
              ) : (
                <div className="h-7 w-7 flex items-center justify-center rounded-full bg-sky-500 text-xs font-semibold text-white">
                  U
                </div>
              )}
            </div>
            
            {/* Bubble */}
            <div className="flex-1 min-w-0">
              {isAssistant ? (
                <div className="assistant-bubble">
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
                  return (
                    <div>
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
                                  } else if (fileName.endsWith('.mp4') || fileName.endsWith('.mov') || fileName.endsWith('.avi') || fileName.endsWith('.webm') || fileName.endsWith('.mkv') || file.mimeType?.startsWith('video/')) {
                                    // Video files - use HTML5 video player
                                    setPreviewFile({name: file.name, data: previewPath, type: 'video', mimeType: file.mimeType || 'video/mp4'});
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
                      
                      {/* Display web_search_results if message type is web_search_results */}
                      {message.type === 'web_search_results' && message.data && (
                        <div className="space-y-4">
                          <div className="font-semibold text-lg mb-3 text-center">
                            Top Results
                          </div>
                          <div className="space-y-3">
                            {message.data.results?.map((result: { title: string; url: string; snippet: string }, index: number) => {
                              const articleState = articleStates[result.url] || 'idle';
                              // Brave Search button only shows spinner for its own article state
                              const isSummarizing = articleState === 'summarizing';
                              const isSummarized = articleState === 'summarized';
                              
                              // Extract domain from URL
                              const getDomain = (url: string) => {
                                try {
                                  const u = new URL(url);
                                  return u.hostname.replace(/^www\./, "");
                                } catch {
                                  return url;
                                }
                              };
                              
                              const getFaviconUrl = (url: string) => {
                                try {
                                  const u = new URL(url);
                                  return `${u.protocol}//${u.hostname}/favicon.ico`;
                                } catch {
                                  return undefined;
                                }
                              };
                              
                              const domain = getDomain(result.url);
                              const faviconUrl = getFaviconUrl(result.url);
                              
                              return (
                                <div key={index} className={index > 0 ? "pt-3 border-t border-[#565869]/30" : ""}>
                                  {/* Domain + Favicon */}
                                  <div className="flex items-center gap-2 mb-1">
                                    {faviconUrl && (
                                      <img
                                        src={faviconUrl}
                                        alt={domain}
                                        className="h-4 w-4 rounded-sm"
                                        onError={(e) => {
                                          (e.target as HTMLImageElement).style.display = 'none';
                                        }}
                                      />
                                    )}
                                    <span className="text-xs text-[#8e8ea0]">{domain}</span>
                                  </div>
                                  
                                  {/* Title + Summarize Button */}
                                  <div className="flex items-center gap-2 mb-1">
                                    <a
                                      href={result.url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="text-blue-400 hover:text-blue-300 font-semibold flex-1"
                                    >
                                      {result.title}
                                    </a>
                                    <button
                                      onClick={async () => {
                                        if (!currentProject || !currentConversation || isSummarizing || isSummarized) return;
                                        setArticleStates(prev => ({ ...prev, [result.url]: 'summarizing' }));
                                        setSummarizingArticle(true);
                                        try {
                                          const { setLoading: setStoreLoading, addMessage: addStoreMessage } = useChatStore.getState();
                                          setStoreLoading(true);
                                          
                                          // Add user message
                                          addStoreMessage({
                                            role: 'user',
                                            content: `Summarize: ${result.url}`,
                                          });
                                          
                                          const response = await axios.post('http://localhost:8000/api/article/summary', {
                                            url: result.url,
                                            conversation_id: currentConversation.id,
                                            project_id: currentProject.id,
                                          });
                                          if (response.data.message_type === 'article_card' && response.data.message_data) {
                                            addStoreMessage({
                                              role: 'assistant',
                                              content: '',
                                              type: 'article_card',
                                              data: response.data.message_data,
                                              model: response.data.model || 'Trafilatura + GPT-5',
                                              provider: response.data.provider || 'trafilatura-gpt5',
                                            });
                                            setArticleStates(prev => ({ ...prev, [result.url]: 'summarized' }));
                                          }
                                          setStoreLoading(false);
                                        } catch (error: any) {
                                          console.error('Error summarizing article:', error);
                                          const { addMessage: addStoreMessage, setLoading: setStoreLoading } = useChatStore.getState();
                                          addStoreMessage({
                                            role: 'assistant',
                                            content: `Error: ${error.response?.data?.detail || error.message || 'Could not summarize URL.'}`,
                                          });
                                          setStoreLoading(false);
                                          setArticleStates(prev => ({ ...prev, [result.url]: 'idle' }));
                                        } finally {
                                          setSummarizingArticle(false);
                                        }
                                      }}
                                      disabled={isSummarizing || isSummarized}
                                      className={`p-1.5 rounded transition-colors flex-shrink-0 ${
                                        isSummarized 
                                          ? 'text-green-400 cursor-default' 
                                          : isSummarizing
                                          ? 'text-blue-400 cursor-wait'
                                          : 'text-[#8e8ea0] hover:text-white hover:bg-[#565869]'
                                      }`}
                                      title={isSummarized ? "Summary created" : isSummarizing ? "Summarizing..." : "Summarize this URL"}
                                    >
                                      {isSummarizing ? (
                                        <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                        </svg>
                                      ) : isSummarized ? (
                                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                        </svg>
                                      ) : (
                                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                        </svg>
                                      )}
                                    </button>
                                  </div>
                                  
                                  {/* Snippet */}
                                  <div className="text-sm text-[#8e8ea0] line-clamp-2">
                                    {result.snippet}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                          
                          {/* Footer */}
                          <div className="border-t border-[#565869] pt-3 mt-4">
                            <div className="text-xs text-[#8e8ea0] text-right">
                              Model: Brave Search
                            </div>
                          </div>
                          
                          {message.data.summary && (
                            <div className="mt-6 pt-6 border-t border-[#565869]">
                              <div className="font-semibold text-lg mb-4 text-center">Summary</div>
                              <div className="prose prose-invert prose-sm max-w-none">
                                <ReactMarkdown
                                  components={{
                                    p: ({ children }) => <p className="mb-3 text-[#ececf1] leading-relaxed">{children}</p>,
                                    ul: ({ children }) => <ul className="list-disc list-inside mb-4 space-y-2 text-[#ececf1]">{children}</ul>,
                                    ol: ({ children }) => <ol className="list-decimal list-inside mb-4 space-y-2 text-[#ececf1]">{children}</ol>,
                                    li: ({ children }) => <li className="ml-4 text-[#ececf1]">{children}</li>,
                                    strong: ({ children }) => <strong className="font-semibold text-[#ececf1]">{children}</strong>,
                                    em: ({ children }) => <em className="italic text-[#ececf1]">{children}</em>,
                                  }}
                                >
                                  {message.data.summary}
                                </ReactMarkdown>
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                      
                      {/* Display document_card if message type is document_card */}
                      {message.type === 'document_card' && message.data && (
                        <DocumentCard
                          fileName={(message.data as any).fileName || 'Document'}
                          fileType={(message.data as any).fileType}
                          filePath={(message.data as any).filePath}
                          summary={(message.data as any).summary || ''}
                          keyPoints={(message.data as any).keyPoints || []}
                          whyMatters={(message.data as any).whyMatters}
                          estimatedReadTimeMinutes={(message.data as any).estimatedReadTimeMinutes}
                          wordCount={(message.data as any).wordCount}
                          pageCount={(message.data as any).pageCount}
                        />
                      )}
                      
                      {/* Display article_card if message type is article_card */}
                      {message.type === 'article_card' && message.data && (
                        <ArticleCard
                          url={(message.data as any).url || ''}
                          title={(message.data as any).title || 'Untitled'}
                          siteName={(message.data as any).siteName}
                          published={(message.data as any).published}
                          summary={(message.data as any).summary || ''}
                          keyPoints={(message.data as any).keyPoints || []}
                          whyMatters={(message.data as any).whyMatters}
                          model={message.model}
                        />
                      )}
                      
                      {/* Display rag_response if message type is rag_response */}
                      {message.type === 'rag_response' && (
                        <RagResponseCard
                          content={message.data?.content || message.content || ''}
                          ragFiles={ragFilesWithIndex}
                          model={message.model}
                          onOpenRagFile={handleOpenRagFile}
                        />
                      )}
                      
                      {/* Display text content if any (and not structured message types) */}
                      {content && message.type !== 'web_search_results' && message.type !== 'article_card' && message.type !== 'document_card' && message.type !== 'rag_response' && (
                        <MessageRenderer content={content} />
                      )}
                      
                      {/* Display sources if web search was used (for normal chat messages) */}
                      {message.role === 'assistant' && 
                       message.type !== 'web_search_results' && 
                       message.type !== 'article_card' && 
                       message.type !== 'document_card' && 
                       message.type !== 'rag_response' &&
                       message.meta?.usedWebSearch && 
                       message.meta?.webResultsPreview && 
                       message.meta.webResultsPreview.length > 0 && (
                        <div className="assistant-sources mt-4 pt-3 border-t border-white/10">
                          <div className="assistant-sources-label">
                            SOURCES
                          </div>
                          <ul className="assistant-sources-list">
                            {message.meta.webResultsPreview.map((result: any, idx: number) => {
                              const articleState = articleStates[result.url] || 'idle';
                              const isSummarizing = articleState === 'summarizing';
                              const isSummarized = articleState === 'summarized';
                              
                              return (
                                <li key={idx} className="flex items-center gap-2">
                                  <a 
                                    href={result.url} 
                                    target="_blank" 
                                    rel="noreferrer"
                                    className="assistant-source-link flex-1 truncate"
                                  >
                                    {result.title || result.url}
                                  </a>
                                  <button
                                    onClick={async () => {
                                      if (!currentProject || !currentConversation || isSummarizing || isSummarized) return;
                                      setArticleStates(prev => ({ ...prev, [result.url]: 'summarizing' }));
                                      setSummarizingArticle(true);
                                      try {
                                        const { setLoading: setStoreLoading, addMessage: addStoreMessage } = useChatStore.getState();
                                        setStoreLoading(true);
                                        
                                        // Add user message
                                        addStoreMessage({
                                          role: 'user',
                                          content: `Summarize: ${result.url}`,
                                        });
                                        
                                        const response = await axios.post('http://localhost:8000/api/article/summary', {
                                          url: result.url,
                                          conversation_id: currentConversation.id,
                                          project_id: currentProject.id,
                                        });
                                        if (response.data.message_type === 'article_card' && response.data.message_data) {
                                          addStoreMessage({
                                            role: 'assistant',
                                            content: '',
                                            type: 'article_card',
                                            data: response.data.message_data,
                                            model: response.data.model || 'Trafilatura + GPT-5',
                                            provider: response.data.provider || 'trafilatura-gpt5',
                                          });
                                          setArticleStates(prev => ({ ...prev, [result.url]: 'summarized' }));
                                        }
                                        setStoreLoading(false);
                                      } catch (error: any) {
                                        console.error('Error summarizing article:', error);
                                        const { addMessage: addStoreMessage, setLoading: setStoreLoading } = useChatStore.getState();
                                        addStoreMessage({
                                          role: 'assistant',
                                          content: `Error: ${error.response?.data?.detail || error.message || 'Could not summarize URL.'}`,
                                        });
                                        setStoreLoading(false);
                                        setArticleStates(prev => ({ ...prev, [result.url]: 'idle' }));
                                      } finally {
                                        setSummarizingArticle(false);
                                      }
                                    }}
                                    disabled={isSummarizing || isSummarized}
                                    className={`p-1.5 rounded transition-colors flex-shrink-0 ${
                                      isSummarized 
                                        ? 'text-green-400 cursor-default' 
                                        : isSummarizing
                                        ? 'text-blue-400 cursor-wait'
                                        : 'text-[#8e8ea0] hover:text-white hover:bg-[#565869]'
                                    }`}
                                    title={isSummarized ? "Summary created" : isSummarizing ? "Summarizing..." : "Summarize this URL"}
                                  >
                                    {isSummarizing ? (
                                      <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                      </svg>
                                    ) : isSummarized ? (
                                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                      </svg>
                                    ) : (
                                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                      </svg>
                                    )}
                                  </button>
                                </li>
                              );
                            })}
                          </ul>
                        </div>
                       )}
                      
                      {/* Display model attribution for assistant messages (only once, at the end) */}
                      {/* Don't show for article_card, document_card, rag_response, or web_search_results as they handle their own model display */}
                      {message.role === 'assistant' && message.model && 
                       message.type !== 'article_card' && 
                       message.type !== 'document_card' && 
                       message.type !== 'rag_response' &&
                       message.type !== 'web_search_results' && (
                        <div className="text-xs text-[#8e8ea0] mt-2 text-right">
                          Model: {message.model}
                        </div>
                      )}
                    </div>
                  );
                })()}
                  </>
                </div>
              ) : (
                <div className="user-bubble">
                  {content && (
                    <p className="whitespace-pre-wrap">{content}</p>
                  )}
                </div>
              )}
            </div>
            
            {/* Action buttons - positioned below message */}
            <div className={`flex gap-2 mt-1 ml-10 ${
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
                    onClick={() => handleCopyMessage(message.content, message.id, message.data)}
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
          </div>
        );
      })}
      
      {/* Streaming content */}
      {isStreaming && (
        <div className="w-full flex chat-assistant">
          <div className="mr-3 flex-shrink-0">
            <div className="h-7 w-7 flex items-center justify-center rounded-full bg-emerald-500 text-xs font-semibold text-white">
              C
            </div>
          </div>
          <div className="flex-1 min-w-0">
            <div className="assistant-bubble">
              <MessageRenderer content={streamingContent} />
              <span className="animate-pulse">▊</span>
            </div>
          </div>
          </div>
          )}
          {/* Invisible element at the bottom to scroll to */}
          <div ref={messagesEndRef} />
        </div>
      </div>
      
      {/* File Preview Modal */}
      {previewFile && (
        <div 
          className="fixed inset-0 bg-black/80 z-[9999] flex items-center justify-center p-4"
          onClick={() => setPreviewFile(null)}
        >
          <div 
            ref={previewModalRef}
            className={`bg-[#343541] rounded-lg max-w-4xl max-h-[90vh] w-full overflow-hidden flex flex-col ${isFullscreen ? '!max-w-none !max-h-none !rounded-none !h-screen !w-screen' : ''}`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-4 border-b border-[#565869]">
              <h3 className="text-lg font-semibold text-white truncate">{previewFile.name}</h3>
              <div className="flex items-center gap-2">
                <button
                  onClick={toggleFullscreen}
                  className="p-2 hover:bg-[#565869] rounded transition-colors text-[#8e8ea0] hover:text-white"
                  title={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
                >
                  {isFullscreen ? (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12M4 8h4m-4 4h4m-4 4h4m8-8v4m0 4v4m0-8h4m-4 0h4" />
                    </svg>
                  ) : (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
                    </svg>
                  )}
                </button>
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
            </div>
            <div className={`flex-1 overflow-auto p-4 ${isFullscreen ? '!h-[calc(100vh-80px)]' : ''}`}>
              {previewFile.type === 'image' ? (
                <img 
                  src={previewFile.data} 
                  alt={previewFile.name}
                  className={`max-w-full mx-auto object-contain ${isFullscreen ? 'max-h-[calc(100vh-80px)]' : 'max-h-full'}`}
                />
              ) : previewFile.type === 'pdf' ? (
                <iframe
                  src={previewFile.data}
                  className={`w-full border border-[#565869] rounded ${isFullscreen ? 'h-[calc(100vh-80px)]' : 'h-[80vh]'}`}
                  title={previewFile.name}
                />
              ) : previewFile.type === 'pptx' ? (
                <iframe
                  src={previewFile.data}
                  className={`w-full border border-[#565869] rounded ${isFullscreen ? 'h-[calc(100vh-80px)]' : 'h-[80vh]'}`}
                  title={previewFile.name}
                />
              ) : previewFile.type === 'xlsx' ? (
                <iframe
                  src={previewFile.data}
                  className={`w-full border border-[#565869] rounded ${isFullscreen ? 'h-[calc(100vh-80px)]' : 'h-[80vh]'}`}
                  title={previewFile.name}
                />
              ) : previewFile.type === 'docx' ? (
                <iframe
                  src={previewFile.data}
                  className={`w-full border border-[#565869] rounded ${isFullscreen ? 'h-[calc(100vh-80px)]' : 'h-[80vh]'}`}
                  title={previewFile.name}
                />
              ) : previewFile.type === 'video' ? (
                <video
                  src={previewFile.data}
                  controls
                  className={`w-full mx-auto object-contain ${isFullscreen ? 'max-h-[calc(100vh-80px)]' : 'max-h-[80vh]'}`}
                  style={isFullscreen ? { maxHeight: 'calc(100vh - 80px)' } : { maxHeight: '80vh' }}
                >
                  Your browser does not support the video tag.
                </video>
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


