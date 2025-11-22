import React, { useState, useEffect, useMemo } from 'react';
import axios from 'axios';
import { useChatStore } from '../store/chat';
import type { RagFile } from '../types/rag';

interface RagContextTrayProps {
  isOpen: boolean;
  onClose: () => void;
  onOpenRagFile?: (file: RagFile) => void; // Optional callback to open file preview
}

const getFileIcon = (mimeType: string) => {
  if (mimeType.includes('pdf')) {
    return (
      <svg className="w-5 h-5 text-red-400" fill="currentColor" viewBox="0 0 24 24">
        <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" />
      </svg>
    );
  } else if (mimeType.includes('sheet') || mimeType.includes('excel') || mimeType.includes('spreadsheet')) {
    // Check Excel BEFORE Word because Excel MIME types contain "document"
    return (
      <svg className="w-5 h-5 text-green-400" fill="currentColor" viewBox="0 0 24 24">
        <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" />
      </svg>
    );
  } else if (mimeType.includes('word') || mimeType.includes('wordprocessing')) {
    // Word documents - check for wordprocessing to avoid matching Excel
    return (
      <svg className="w-5 h-5 text-blue-400" fill="currentColor" viewBox="0 0 24 24">
        <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" />
      </svg>
    );
  } else if (mimeType.includes('presentation') || mimeType.includes('powerpoint')) {
    return (
      <svg className="w-5 h-5 text-orange-400" fill="currentColor" viewBox="0 0 24 24">
        <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" />
      </svg>
    );
  } else {
    return (
      <svg className="w-5 h-5 text-gray-400" fill="currentColor" viewBox="0 0 24 24">
        <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" />
      </svg>
    );
  }
};

export const RagContextTray: React.FC<RagContextTrayProps> = ({ isOpen, onClose, onOpenRagFile }) => {
  const { currentConversation, setRagFileIds } = useChatStore();
  const [ragFiles, setRagFiles] = useState<RagFile[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [loading, setLoading] = useState(false);

  // Load RAG files when tray opens (they're already loaded when conversation changes)
  useEffect(() => {
    if (isOpen && currentConversation) {
      loadRagFiles();
    }
  }, [isOpen, currentConversation?.id]);
  
  // Fix React warning: wrap setRagFileIds in useEffect to avoid setState during render
  useEffect(() => {
    if (currentConversation) {
      const fileIds = ragFiles.filter((f: RagFile) => f.text_extracted).map((f: RagFile) => f.id);
      setRagFileIds(fileIds);
    } else {
      setRagFileIds([]);
    }
  }, [ragFiles, currentConversation?.id, setRagFileIds]);

  const loadRagFiles = async () => {
    if (!currentConversation) return;
    
    setLoading(true);
    try {
      const response = await axios.get('http://localhost:8000/api/rag/files', {
        params: { chat_id: currentConversation.id }
      });
      const files = response.data || [];
      // Sort by created_at to ensure consistent ordering (matches ChatMessages)
      const sortedFiles = files.sort((a: RagFile, b: RagFile) => 
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      );
      setRagFiles(sortedFiles as RagFile[]);
      // RAG file IDs will be updated by the useEffect hook above
    } catch (error) {
      console.error('Failed to load RAG files:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (file: File) => {
    if (!file || !currentConversation) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    formData.append('chat_id', currentConversation.id);

    try {
      const response = await axios.post('http://localhost:8000/api/rag/files', formData);
      const newFile = response.data;
      setRagFiles(prev => {
        const updated = [...prev, newFile];
        // RAG file IDs will be updated by the useEffect hook
        return updated;
      });
    } catch (error) {
      console.error('Failed to upload RAG file:', error);
      alert('Failed to upload file. Please try again.');
    } finally {
      setIsUploading(false);
    }
  };

  const handleFileInputChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      await handleFileUpload(file);
    }
    if (e.target) {
      e.target.value = '';
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    const files = Array.from(e.dataTransfer.files);
    for (const file of files) {
      await handleFileUpload(file);
    }
  };

  const handleDeleteFile = async (fileId: string) => {
    if (!currentConversation) return;
    
    try {
      await axios.delete(`http://localhost:8000/api/rag/files/${fileId}`, {
        params: { chat_id: currentConversation.id }
      });
      setRagFiles(prev => {
        const updated = prev.filter(f => f.id !== fileId);
        // RAG file IDs will be updated by the useEffect hook
        return updated;
      });
    } catch (error) {
      console.error('Failed to delete RAG file:', error);
      alert('Failed to delete file. Please try again.');
    }
  };

  const handleClearAll = async () => {
    if (!currentConversation || !confirm('Clear all context files for this chat?')) return;
    
    try {
      await Promise.all(ragFiles.map(file => 
        axios.delete(`http://localhost:8000/api/rag/files/${file.id}`, {
          params: { chat_id: currentConversation.id }
        })
      ));
      setRagFiles([]);
      // RAG file IDs will be updated by the useEffect hook (to empty array)
    } catch (error) {
      console.error('Failed to clear RAG files:', error);
      alert('Failed to clear files. Please try again.');
    }
  };

  if (!isOpen) return null;

  return (
    <div 
      className="fixed right-0 top-0 h-full w-80 bg-[#1a1a1a] border-l border-[#565869] flex flex-col z-40"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Header */}
      <div className="p-4 border-b border-[#565869] flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-[#ececf1]">Context Files</h2>
          <p className="text-xs text-[#8e8ea0] mt-1">
            Files here are used as reference for ChatDO's answers in this chat.
          </p>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 hover:bg-[#565869]/50 rounded transition-colors text-[#8e8ea0] hover:text-white"
          title="Close"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Upload Area */}
      <div className="p-4 border-b border-[#565869]">
        <label className="block">
          <div 
            className="border-2 border-dashed border-[#565869] rounded-lg p-4 text-center cursor-pointer hover:border-[#19c37d] transition-colors"
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            {isUploading ? (
              <div className="flex items-center justify-center gap-2 text-[#8e8ea0]">
                <div className="animate-spin h-4 w-4 border-2 border-[#19c37d] border-t-transparent rounded-full"></div>
                <span className="text-sm">Uploading...</span>
              </div>
            ) : (
              <div className="text-[#8e8ea0]">
                <svg className="w-8 h-8 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                <p className="text-sm font-medium">Drop files here or click to upload</p>
                <p className="text-xs mt-1">PDF, DOCX, PPTX, XLSX, TXT, MD</p>
              </div>
            )}
          </div>
          <input
            type="file"
            className="hidden"
            onChange={handleFileInputChange}
            accept=".pdf,.doc,.docx,.pptx,.xlsx,.xls,.txt,.md"
            disabled={isUploading || !currentConversation}
          />
        </label>
      </div>

      {/* File List */}
      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="text-center text-[#8e8ea0] py-8">
            <div className="animate-spin h-6 w-6 border-2 border-[#19c37d] border-t-transparent rounded-full mx-auto mb-2"></div>
            <p className="text-sm">Loading files...</p>
          </div>
        ) : ragFiles.length === 0 ? (
          <div className="text-center text-[#8e8ea0] py-8">
            <p className="text-sm">No context files yet.</p>
            <p className="text-xs mt-1">Upload files to use them as reference.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {(() => {
              // Compute indexed files (same logic as ChatMessages)
              const readyFiles = ragFiles.filter(f => f.text_extracted);
              const ragFilesWithIndex = readyFiles.map((file, i) => ({
                ...file,
                index: i + 1, // 1-based index
              }));
              
              return ragFilesWithIndex.map((file) => (
                <button
                  key={file.id}
                  type="button"
                  onClick={() => onOpenRagFile?.(file)}
                  className="w-full bg-[#2a2a2a] rounded-lg p-3 border border-[#565869] hover:border-[#19c37d] transition-colors text-left"
                >
                  <div className="flex items-start gap-3">
                    {getFileIcon(file.mime_type)}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-xs font-semibold text-[#19c37d] flex-shrink-0">
                            {file.index}.
                          </span>
                          <p className="text-sm font-medium text-[#ececf1] truncate">{file.filename}</p>
                        </div>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteFile(file.id);
                          }}
                          className="p-1 hover:bg-[#565869]/50 rounded transition-colors text-[#8e8ea0] hover:text-white flex-shrink-0"
                          title="Remove"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </div>
                      <div className="mt-1 flex items-center gap-2">
                        <span className="text-xs px-2 py-0.5 bg-green-500/20 text-green-400 rounded">Ready</span>
                        <span className="text-xs text-[#8e8ea0]">
                          {(file.size / 1024).toFixed(1)} KB
                        </span>
                      </div>
                    </div>
                  </div>
                </button>
              ));
            })()}
          </div>
        )}
      </div>

      {/* Footer */}
      {ragFiles.length > 0 && (
        <div className="p-4 border-t border-[#565869]">
          <button
            onClick={handleClearAll}
            className="w-full px-4 py-2 text-sm text-[#8e8ea0] hover:text-white hover:bg-[#565869]/50 rounded transition-colors"
          >
            Clear all
          </button>
        </div>
      )}
    </div>
  );
};

export default RagContextTray;

