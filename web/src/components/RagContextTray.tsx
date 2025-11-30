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
  const { 
    currentConversation, 
    ragFileIds, 
    setRagFileIds, 
    setRagFilesForConversation,
    ragFilesByConversationId 
  } = useChatStore();
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  // Get RAG files from store (conversation-scoped) - use direct selector for reactivity
  const ragFiles = React.useMemo(() => {
    if (!currentConversation?.id) return [];
    return ragFilesByConversationId[currentConversation.id] || [];
  }, [currentConversation?.id, ragFilesByConversationId]);
  
  // Update ragFileIds when ragFiles change - ensure it matches backend order
  useEffect(() => {
    if (currentConversation && ragFiles.length > 0) {
      // Sort by created_at to match backend order, then filter for text_extracted
      const sortedFiles = [...ragFiles].sort((a, b) => 
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      );
      const fileIds = sortedFiles.filter((f: RagFile) => f.text_extracted).map((f: RagFile) => f.id);
      setRagFileIds(fileIds);
    } else {
      setRagFileIds([]);
    }
  }, [ragFiles, currentConversation?.id, setRagFileIds]);

  const handleFileUpload = async (file: File) => {
    if (!file || !currentConversation) {
      console.error('[RAG] Cannot upload: missing file or conversation');
      return;
    }

    console.log('[RAG] Starting upload for file:', file.name, 'to chat:', currentConversation.id);
    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    formData.append('chat_id', currentConversation.id);

    try {
      const response = await axios.post('http://localhost:8000/api/rag/files', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      console.log('[RAG] Upload response:', response.data);
      
      // Reload from backend to ensure consistency (handles async text extraction)
      // This ensures we get the latest state including text_extracted status
      const ragResponse = await axios.get('http://localhost:8000/api/rag/files', {
        params: { chat_id: currentConversation.id }
      });
      const allFiles: RagFile[] = ragResponse.data || [];
      // Sort by created_at to match backend order
      const sortedFiles = allFiles.sort((a, b) => 
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      );
      console.log('[RAG] Reloaded files from backend:', sortedFiles.length);
      
      // Update store - this will trigger re-render
      setRagFilesForConversation(currentConversation.id, sortedFiles);
      
      // Force update ragFileIds immediately
      const fileIds = sortedFiles.filter((f) => f.text_extracted).map((f) => f.id);
      setRagFileIds(fileIds);
      
      console.log('[RAG] Updated store with', sortedFiles.length, 'files,', fileIds.length, 'ready');
    } catch (error: any) {
      console.error('[RAG] Failed to upload RAG file:', error);
      console.error('[RAG] Error details:', error.response?.data || error.message);
      const errorMsg = error.response?.data?.detail || error.message || 'Unknown error';
      alert(`Failed to upload file: ${errorMsg}`);
    } finally {
      setIsUploading(false);
    }
  };

  const handleFileInputChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      console.log('[RAG] File input changed:', files.length, 'files');
      // Upload files sequentially
      for (let i = 0; i < files.length; i++) {
        await handleFileUpload(files[i]);
      }
    }
    if (e.target) {
      e.target.value = '';
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    // Add visual feedback
    if (e.currentTarget === e.target || (e.currentTarget as HTMLElement).contains(e.target as Node)) {
      (e.currentTarget as HTMLElement).classList.add('border-[#19c37d]');
    }
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    // Remove visual feedback
    if (e.currentTarget === e.target || (e.currentTarget as HTMLElement).contains(e.target as Node)) {
      (e.currentTarget as HTMLElement).classList.remove('border-[#19c37d]');
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    // Remove visual feedback
    (e.currentTarget as HTMLElement).classList.remove('border-[#19c37d]');
    
    const files = Array.from(e.dataTransfer.files);
    console.log('[RAG] Dropped files:', files.length, 'files:', files.map(f => f.name));
    
    if (!currentConversation) {
      console.error('[RAG] Cannot drop files: no current conversation');
      alert('Please select a conversation first.');
      return;
    }
    
    // Upload files sequentially to avoid race conditions
    for (const file of files) {
      console.log('[RAG] Processing file:', file.name);
      await handleFileUpload(file);
    }
    
    console.log('[RAG] Finished processing all dropped files');
  };

  const handleDeleteFile = async (fileId: string) => {
    if (!currentConversation) {
      console.error('[RAG] No current conversation');
      return;
    }
    
    console.log('[RAG] Deleting file:', fileId, 'for chat:', currentConversation.id);
    
    try {
      const response = await axios.delete(`http://localhost:8000/api/rag/files/${fileId}`, {
        params: { chat_id: currentConversation.id }
      });
      console.log('[RAG] Delete response:', response.data);
      
      // Reload from backend to ensure consistency
      const ragResponse = await axios.get('http://localhost:8000/api/rag/files', {
        params: { chat_id: currentConversation.id }
      });
      const remainingFiles: RagFile[] = ragResponse.data || [];
      // Sort by created_at to match backend order
      const sortedFiles = remainingFiles.sort((a, b) => 
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      );
      
      // Update store - this will trigger re-render
      setRagFilesForConversation(currentConversation.id, sortedFiles);
      
      // Force update ragFileIds immediately
      const fileIds = sortedFiles.filter((f) => f.text_extracted).map((f) => f.id);
      setRagFileIds(fileIds);
      
      console.log('[RAG] Files after delete:', sortedFiles.length, 'remaining,', fileIds.length, 'ready');
    } catch (error: any) {
      console.error('[RAG] Failed to delete file:', error);
      console.error('[RAG] Error details:', error.response?.data || error.message);
      alert(`Failed to delete file: ${error.response?.data?.detail || error.message}`);
    }
  };

  const handleClearAll = async () => {
    if (!currentConversation || !confirm('Clear all context files for this chat?')) return;
    
    try {
      // Delete files one by one, handling individual failures gracefully
      const deletePromises = ragFiles.map(async (file) => {
        try {
          await axios.delete(`http://localhost:8000/api/rag/files/${file.id}`, {
            params: { chat_id: currentConversation.id }
          });
          return { success: true, fileId: file.id };
        } catch (error) {
          console.error(`Failed to delete file ${file.filename}:`, error);
          return { success: false, fileId: file.id, error };
        }
      });
      
      const results = await Promise.all(deletePromises);
      const failed = results.filter(r => !r.success);
      
      if (failed.length > 0) {
        console.warn(`Failed to delete ${failed.length} file(s) out of ${ragFiles.length}`);
        // Still clear the store - the backend will have deleted what it could
      }
      
      // Clear in store regardless (backend has already updated)
      setRagFilesForConversation(currentConversation.id, []);
      
      // Reload from backend to ensure consistency
      try {
        const response = await axios.get('http://localhost:8000/api/rag/files', {
          params: { chat_id: currentConversation.id }
        });
        const remainingFiles: RagFile[] = response.data || [];
        const sortedFiles = remainingFiles.sort((a, b) => 
          new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
        );
        setRagFilesForConversation(currentConversation.id, sortedFiles);
        
        // Force update ragFileIds immediately
        const fileIds = sortedFiles.filter((f) => f.text_extracted).map((f) => f.id);
        setRagFileIds(fileIds);
      } catch (error) {
        console.error('Failed to reload RAG files after clear:', error);
        // Store is already cleared, so this is fine
        setRagFileIds([]);
      }
    } catch (error) {
      console.error('Failed to clear RAG files:', error);
      alert('Failed to clear files. Please try again.');
    }
  };

  if (!isOpen) return null;

  return (
    <div 
      className="rag-tray fixed right-0 top-0 h-full w-80 bg-[var(--bg-secondary)] border-l border-[var(--border-color)] flex flex-col z-50 pointer-events-auto transition-colors"
      data-rag-tray="true"
    >
      {/* Header */}
      <div className="p-4 border-b border-[var(--border-color)] flex items-center justify-between transition-colors">
        <div>
          <h2 className="text-lg font-semibold text-[var(--text-primary)]">Context Files</h2>
          <p className="text-xs text-[var(--text-secondary)] mt-1">
            Files here are used as reference for ChatDO's answers in this chat.
          </p>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 hover:bg-[var(--border-color)]/50 rounded transition-colors text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          title="Close"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Upload Area */}
      <div className="p-4 border-b border-[var(--border-color)] transition-colors">
        <label className="block">
          <div 
            className="border-2 border-dashed border-[var(--border-color)] rounded-lg p-4 text-center cursor-pointer hover:border-[#19c37d] transition-colors"
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => {
              if (fileInputRef.current && !isUploading && currentConversation) {
                fileInputRef.current.click();
              }
            }}
          >
            {isUploading ? (
              <div className="flex items-center justify-center gap-2 text-[var(--text-secondary)]">
                <div className="animate-spin h-4 w-4 border-2 border-[#19c37d] border-t-transparent rounded-full"></div>
                <span className="text-sm">Uploading...</span>
              </div>
            ) : (
              <div className="text-[var(--text-secondary)]">
                <svg className="w-8 h-8 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                <p className="text-sm font-medium">Drop files here or click to upload</p>
                <p className="text-xs mt-1">PDF, DOCX, PPTX, XLSX, TXT, MD</p>
              </div>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            onChange={handleFileInputChange}
            accept=".pdf,.doc,.docx,.pptx,.xlsx,.xls,.txt,.md"
            multiple
            disabled={isUploading || !currentConversation}
          />
        </label>
      </div>

      {/* File List */}
      <div className="flex-1 overflow-y-auto p-4">
        {ragFiles.length === 0 ? (
          <div className="text-center text-[var(--text-secondary)] py-8">
            <p className="text-sm">No context files yet.</p>
            <p className="text-xs mt-1">Upload files to use them as reference.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {(() => {
              // Compute indexed files - MUST match ChatMessages logic (use ragFileIds order!)
              if (!ragFileIds || ragFileIds.length === 0) return [];
              
              // Create a lookup map for fast access
              const filesById = new Map(ragFiles.map(f => [f.id, f]));
              
              // Build indexed files in the SAME ORDER as ragFileIds (matches backend)
              const indexed: RagFile[] = [];
              ragFileIds.forEach((fileId) => {
                const file = filesById.get(fileId);
                if (file && file.text_extracted) {
                  indexed.push({
                    ...file,
                    index: indexed.length + 1, // 1-based index, only counting ready files
                  });
                }
              });
              
              return indexed.map((file) => (
                <div
                  key={file.id}
                  className="w-full bg-[#2a2a2a] rounded-lg p-3 border border-[#565869] hover:border-[#19c37d] transition-colors"
                >
                  <div className="flex items-start gap-3">
                    {getFileIcon(file.mime_type)}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <button
                          type="button"
                          onClick={() => onOpenRagFile?.(file)}
                          className="flex items-center gap-2 min-w-0 flex-1 text-left hover:opacity-80 transition-opacity"
                        >
                          <span className="text-xs font-semibold text-[#19c37d] flex-shrink-0">
                            {file.index}.
                          </span>
                          <p className="text-sm font-medium text-[#ececf1] truncate">{file.filename}</p>
                        </button>
                        <button
                          type="button"
                          onClick={async (e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            console.log('[RAG] Delete button clicked for file:', file.id, 'for chat:', currentConversation?.id);
                            await handleDeleteFile(file.id);
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
                </div>
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

