import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useChatStore } from '../store/chat';

interface RagFile {
  id: string;
  chat_id: string;
  filename: string;
  mime_type: string;
  size: number;
  created_at: string;
  text_path: string | null;
  text_extracted: boolean;
  error?: string | null;
}

interface RagContextTrayProps {
  isOpen: boolean;
  onClose: () => void;
}

const getFileIcon = (mimeType: string) => {
  if (mimeType.includes('pdf')) {
    return (
      <svg className="w-5 h-5 text-red-400" fill="currentColor" viewBox="0 0 24 24">
        <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" />
      </svg>
    );
  } else if (mimeType.includes('word') || mimeType.includes('document')) {
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
  } else if (mimeType.includes('sheet') || mimeType.includes('excel')) {
    return (
      <svg className="w-5 h-5 text-green-400" fill="currentColor" viewBox="0 0 24 24">
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

export const RagContextTray: React.FC<RagContextTrayProps> = ({ isOpen, onClose }) => {
  const { currentConversation } = useChatStore();
  const [ragFiles, setRagFiles] = useState<RagFile[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [loading, setLoading] = useState(false);

  // Load RAG files when conversation changes or tray opens
  useEffect(() => {
    if (isOpen && currentConversation) {
      loadRagFiles();
    }
  }, [isOpen, currentConversation?.id]);

  const loadRagFiles = async () => {
    if (!currentConversation) return;
    
    setLoading(true);
    try {
      const response = await axios.get('http://localhost:8000/api/rag/files', {
        params: { chat_id: currentConversation.id }
      });
      const files = response.data || [];
      setRagFiles(files);
      // Update store with RAG file IDs
      const fileIds = files.filter((f: RagFile) => f.text_extracted).map((f: RagFile) => f.id);
      setRagFileIds(fileIds);
    } catch (error) {
      console.error('Failed to load RAG files:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
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
        // Update store with RAG file IDs (only ready files)
        const fileIds = updated.filter(f => f.text_extracted).map(f => f.id);
        setRagFileIds(fileIds);
        return updated;
      });
    } catch (error) {
      console.error('Failed to upload RAG file:', error);
      alert('Failed to upload file. Please try again.');
    } finally {
      setIsUploading(false);
      if (e.target) {
        e.target.value = '';
      }
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
        // Update store with remaining RAG file IDs
        const fileIds = updated.filter(f => f.text_extracted).map(f => f.id);
        setRagFileIds(fileIds);
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
      setRagFileIds([]);
    } catch (error) {
      console.error('Failed to clear RAG files:', error);
      alert('Failed to clear files. Please try again.');
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed right-0 top-0 h-full w-80 bg-[#1a1a1a] border-l border-[#565869] flex flex-col z-50">
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
          <div className="border-2 border-dashed border-[#565869] rounded-lg p-4 text-center cursor-pointer hover:border-[#19c37d] transition-colors">
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
                <p className="text-xs mt-1">PDF, DOCX, PPTX, TXT, MD</p>
              </div>
            )}
          </div>
          <input
            type="file"
            className="hidden"
            onChange={handleFileUpload}
            accept=".pdf,.doc,.docx,.pptx,.txt,.md"
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
            {ragFiles.map((file) => (
              <div
                key={file.id}
                className="bg-[#2a2a2a] rounded-lg p-3 border border-[#565869] hover:border-[#19c37d] transition-colors"
              >
                <div className="flex items-start gap-3">
                  {getFileIcon(file.mime_type)}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium text-[#ececf1] truncate">{file.filename}</p>
                      <button
                        onClick={() => handleDeleteFile(file.id)}
                        className="p-1 hover:bg-[#565869]/50 rounded transition-colors text-[#8e8ea0] hover:text-white flex-shrink-0"
                        title="Remove"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                    <div className="mt-1 flex items-center gap-2">
                      {file.text_extracted ? (
                        <span className="text-xs px-2 py-0.5 bg-green-500/20 text-green-400 rounded">Ready</span>
                      ) : file.error ? (
                        <span className="text-xs px-2 py-0.5 bg-red-500/20 text-red-400 rounded" title={file.error}>
                          Error
                        </span>
                      ) : (
                        <span className="text-xs px-2 py-0.5 bg-yellow-500/20 text-yellow-400 rounded">Indexing...</span>
                      )}
                      <span className="text-xs text-[#8e8ea0]">
                        {(file.size / 1024).toFixed(1)} KB
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            ))}
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

