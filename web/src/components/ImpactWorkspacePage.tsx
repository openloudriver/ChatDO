/**
 * Impact Workspace Page - Simplified 2-column layout
 * 
 * Architecture:
 * - Left column: Impact list with checkboxes for selection
 * - Right column: Active bullet editor (top) + Chat messages (middle) + Composer (bottom)
 * 
 * Features:
 * - Single active bullet editor with mode selector (1206 2-line / OPB 350 / OPB 450 / Free)
 * - Character limits: 230, 350, 450 chars based on mode
 * - RAG context tray: Lightbulb button opens right-side tray for uploading reference files
 * - Context-aware chat: Includes selected impacts, current bullet draft, and RAG files
 * - Per-impact scoping: Active Bullet, Chat messages, and RAG files are scoped to each impact
 */
import React, { useEffect, useState, useCallback, useRef } from "react";
import { useChatStore, type Message } from "../store/chat";
import { fetchImpacts, updateImpact, deleteImpact } from "../utils/api";
import type { ImpactEntry } from "../types/impact";
import type { RagFile } from "../types/rag";
import ChatMessages from "./ChatMessages";
import { ImpactWorkspaceChatComposer } from "./ImpactWorkspaceChatComposer";
import { ImpactCaptureModal } from "./ImpactCaptureModal";
import { ActiveBulletEditor, type BulletMode, BULLET_MODES } from "./ActiveBulletEditor";

const IMPACT_PROJECT_NAME = "Impact Workspace";

// Per-impact scoped state
type ImpactScopedState = {
  activeBulletText: string;
  chatMessages: Message[];
  ragFileIds: string[];
};

// localStorage key prefix for impact-scoped data
const IMPACT_STATE_PREFIX = 'chatdo:impact_state:';

// Helper functions for localStorage persistence
const loadImpactState = (impactId: string): ImpactScopedState => {
  try {
    const stored = localStorage.getItem(`${IMPACT_STATE_PREFIX}${impactId}`);
    if (stored) {
      const parsed = JSON.parse(stored);
      // Convert timestamp strings back to Date objects for messages
      if (parsed.chatMessages) {
        parsed.chatMessages = parsed.chatMessages.map((msg: any) => ({
          ...msg,
          timestamp: new Date(msg.timestamp),
        }));
      }
      return parsed;
    }
  } catch (e) {
    console.error('Failed to load impact state:', e);
  }
  return {
    activeBulletText: '',
    chatMessages: [],
    ragFileIds: [],
  };
};

const saveImpactState = (impactId: string, state: ImpactScopedState): void => {
  try {
    localStorage.setItem(`${IMPACT_STATE_PREFIX}${impactId}`, JSON.stringify(state));
  } catch (e) {
    console.error('Failed to save impact state:', e);
  }
};

const deleteImpactState = (impactId: string): void => {
  try {
    localStorage.removeItem(`${IMPACT_STATE_PREFIX}${impactId}`);
  } catch (e) {
    console.error('Failed to delete impact state:', e);
  }
};

// Simple impact-scoped RAG tray component
interface ImpactScopedRagTrayProps {
  isOpen: boolean;
  onClose: () => void;
  ragFileIds: string[];
  onRagFileIdsChange: (ragFileIds: string[]) => void;
  selectedImpactId: string;
}

const ImpactScopedRagTray: React.FC<ImpactScopedRagTrayProps> = ({
  isOpen,
  onClose,
  ragFileIds,
  onRagFileIdsChange,
  selectedImpactId,
}) => {
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileUpload = async (file: File) => {
    if (!file) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    // For now, we'll use a placeholder conversation ID
    // TODO: Create a proper impact-scoped RAG endpoint
    formData.append('chat_id', `impact_${selectedImpactId}`);

    try {
      const response = await fetch('http://localhost:8000/api/rag/files', {
        method: 'POST',
        body: formData,
      });
      
      if (!response.ok) throw new Error('Upload failed');
      const data = await response.json();
      
      // Add the new file ID to the impact's RAG file IDs
      if (data.id) {
        onRagFileIdsChange([...ragFileIds, data.id]);
      }
    } catch (error) {
      console.error('Failed to upload RAG file:', error);
    } finally {
      setIsUploading(false);
    }
  };

  const handleRemoveFile = (fileId: string) => {
    onRagFileIdsChange(ragFileIds.filter(id => id !== fileId));
  };

  if (!isOpen) return null;

  return (
    <div className="fixed right-0 top-0 h-full w-80 bg-[#343541] border-l border-slate-700 z-50 flex flex-col shadow-2xl">
      <div className="flex items-center justify-between p-4 border-b border-slate-700">
        <h3 className="text-sm font-semibold text-slate-100">Context Files</h3>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-white"
          aria-label="Close tray"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
      
      <div className="flex-1 overflow-y-auto p-4">
        <div
          className="border-2 border-dashed border-slate-600 rounded-lg p-6 text-center cursor-pointer hover:border-slate-500 transition-colors"
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              if (e.target.files) {
                Array.from(e.target.files).forEach(handleFileUpload);
              }
            }}
          />
          <p className="text-sm text-slate-300">
            {isUploading ? 'Uploading...' : 'Drop files here or click to upload'}
          </p>
        </div>
        
        {ragFileIds.length > 0 && (
          <div className="mt-4 space-y-2">
            {ragFileIds.map((fileId) => (
              <div key={fileId} className="flex items-center justify-between p-2 bg-slate-800 rounded">
                <span className="text-xs text-slate-300 truncate">{fileId}</span>
                <button
                  onClick={() => handleRemoveFile(fileId)}
                  className="text-red-400 hover:text-red-300 text-xs"
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export const ImpactWorkspacePage: React.FC = () => {
  // Impact list state
  const [impacts, setImpacts] = useState<ImpactEntry[]>([]);
  const [selectedImpactIds, setSelectedImpactIds] = useState<Set<string>>(new Set());
  const [loadingImpacts, setLoadingImpacts] = useState(true);
  const [impactModalOpen, setImpactModalOpen] = useState(false);
  const [editingImpact, setEditingImpact] = useState<ImpactEntry | null>(null);
  
  // Per-impact scoped state
  const [impactState, setImpactState] = useState<Record<string, ImpactScopedState>>({});
  
  // Get RAG tray state for layout adjustment
  const [isRagTrayOpen, setIsRagTrayOpen] = useState(false);
  
  // Bullet editor state
  const [bulletMode, setBulletMode] = useState<BulletMode>('1206_2LINE');
  
  // Get the selected impact (first selected, or null)
  const selectedImpactId = selectedImpactIds.size > 0 ? Array.from(selectedImpactIds)[0] : null;
  const selectedImpact = selectedImpactId ? impacts.find(i => i.id === selectedImpactId) || null : null;
  const selectedState = selectedImpactId ? impactState[selectedImpactId] : null;
  
  // Debounce timer for backend saves
  const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  
  // Cleanup timeout on unmount or impact change
  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
    };
  }, [selectedImpactId]);
  
  // Initialize impact state when an impact is selected for the first time
  useEffect(() => {
    if (selectedImpactId && !impactState[selectedImpactId]) {
      // Load from localStorage or initialize empty
      const loadedState = loadImpactState(selectedImpactId);
      // Also load activeBullet from the impact's backend data
      if (selectedImpact?.activeBullet) {
        loadedState.activeBulletText = selectedImpact.activeBullet;
      }
      setImpactState(prev => ({
        ...prev,
        [selectedImpactId]: loadedState,
      }));
    }
  }, [selectedImpactId, selectedImpact?.activeBullet]);
  
  // Sync impact state with backend activeBullet when impact changes (not on every state change)
  useEffect(() => {
    if (selectedImpactId && selectedImpact && impactState[selectedImpactId]) {
      const currentState = impactState[selectedImpactId];
      // If backend has activeBullet but state doesn't, sync it
      // Only sync when the impact selection changes, not when state changes
      if (selectedImpact.activeBullet && currentState.activeBulletText !== selectedImpact.activeBullet) {
        setImpactState(prev => ({
          ...prev,
          [selectedImpactId]: {
            ...prev[selectedImpactId],
            activeBulletText: selectedImpact.activeBullet!,
          },
        }));
        // Also save to localStorage
        const updatedState = {
          ...currentState,
          activeBulletText: selectedImpact.activeBullet!,
        };
        saveImpactState(selectedImpactId, updatedState);
      }
    }
    // Only run when selected impact changes, not when impactState changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedImpactId, selectedImpact?.activeBullet]);
  
  // Handle active bullet text changes - update the impact
  const handleActiveBulletChange = async (newText: string) => {
    if (!selectedImpactId) return;
    
    const previousState = impactState[selectedImpactId];
    
    // Update impact-scoped state immediately (for responsive UI)
    const newState: ImpactScopedState = {
      ...(previousState || { activeBulletText: '', chatMessages: [], ragFileIds: [] }),
      activeBulletText: newText,
    };
    setImpactState(prev => ({
      ...prev,
      [selectedImpactId]: newState,
    }));
    saveImpactState(selectedImpactId, newState);
    
    // Debounce backend save to avoid cursor jumping
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }
    
    saveTimeoutRef.current = setTimeout(async () => {
      const valueToSave = newText.trim() === '' ? null : newText;
      try {
        // Persist to backend (for activeBullet field)
        const updated = await updateImpact(selectedImpactId, { activeBullet: valueToSave });
        
        // Update impacts list with backend response
        if (updated) {
          setImpacts(prev => prev.map(impact => 
            impact.id === selectedImpactId 
              ? { ...impact, activeBullet: updated.activeBullet ?? null }
              : impact
          ));
        }
      } catch (error) {
        console.error('Failed to update activeBullet:', error);
        // Revert state on error
        if (previousState) {
          setImpactState(prev => ({
            ...prev,
            [selectedImpactId]: previousState,
          }));
          saveImpactState(selectedImpactId, previousState);
        }
      }
    }, 500); // Wait 500ms after user stops typing
  };
  
  // Handle chat messages change
  const handleMessagesChange = useCallback((newMessages: Message[]) => {
    if (!selectedImpactId) return;
    
    const currentState = impactState[selectedImpactId] || { activeBulletText: '', chatMessages: [], ragFileIds: [] };
    const newState: ImpactScopedState = {
      ...currentState,
      chatMessages: newMessages,
    };
    setImpactState(prev => ({
      ...prev,
      [selectedImpactId]: newState,
    }));
    saveImpactState(selectedImpactId, newState);
  }, [selectedImpactId, impactState]);
  
  // Handle RAG file IDs change
  const handleRagFileIdsChange = useCallback((newRagFileIds: string[]) => {
    if (!selectedImpactId) return;
    
    const currentState = impactState[selectedImpactId] || { activeBulletText: '', chatMessages: [], ragFileIds: [] };
    const newState: ImpactScopedState = {
      ...currentState,
      ragFileIds: newRagFileIds,
    };
    setImpactState(prev => ({
      ...prev,
      [selectedImpactId]: newState,
    }));
    saveImpactState(selectedImpactId, newState);
  }, [selectedImpactId, impactState]);
  
  // Chat state
  const {
    currentProject,
    currentConversation,
    setCurrentProject,
    setCurrentConversation,
    createNewChatInProject,
    loadProjects,
    loadChats,
    setViewMode,
    viewMode,
  } = useChatStore();

  // Ensure we're in impact view mode
  useEffect(() => {
    if (viewMode !== "impact") {
      setViewMode("impact");
    }
  }, [viewMode, setViewMode]);

  // Ensure Impact Workspace project exists and is selected
  useEffect(() => {
    const ensureImpactProject = async () => {
      try {
        await loadProjects();
        const state = useChatStore.getState();
        
        let impactProject = state.projects.find(p => p.name === IMPACT_PROJECT_NAME);
        
        if (!impactProject) {
          try {
            const response = await fetch("http://localhost:8000/api/projects", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                name: IMPACT_PROJECT_NAME,
                default_target: "general",
              }),
            });
            
            if (response.ok) {
              await loadProjects();
              const updatedState = useChatStore.getState();
              impactProject = updatedState.projects.find(p => p.name === IMPACT_PROJECT_NAME);
            }
          } catch (e) {
            console.error("Error creating Impact Workspace project:", e);
          }
        }
        
        if (impactProject && currentProject?.id !== impactProject.id) {
          setCurrentProject(impactProject);
          // Immediately set viewMode back to 'impact' since setCurrentProject changes it to 'projectList'
          setViewMode("impact");
          await loadChats(impactProject.id);
          
          const state = useChatStore.getState();
          if (state.conversations.length === 0) {
            const newConversation = await createNewChatInProject(impactProject.id);
            await setCurrentConversation(newConversation);
          } else {
            const firstConversation = state.conversations[0];
            if (firstConversation) {
              await setCurrentConversation(firstConversation);
            } else {
              const newConversation = await createNewChatInProject(impactProject.id);
              await setCurrentConversation(newConversation);
            }
          }
          // Ensure viewMode stays as 'impact' after conversation is set
          setViewMode("impact");
        }
      } catch (e) {
        console.error("Error ensuring impact project:", e);
      }
    };
    
    ensureImpactProject();
  }, [currentProject, setCurrentProject, loadProjects, loadChats, createNewChatInProject, setCurrentConversation, setViewMode]);

  // Load impacts
  const loadImpacts = async () => {
    try {
      setLoadingImpacts(true);
      const data = await fetchImpacts();
      setImpacts(data);
      
      // Preserve selected impact IDs after reload
      // The selectedImpact will be recalculated from the new data
    } catch (e: any) {
      console.error("Failed to load impacts:", e);
    } finally {
      setLoadingImpacts(false);
    }
  };

  useEffect(() => {
    loadImpacts();
  }, []);

  // Listen for impact saves from anywhere (sidebar modal or workspace modal)
  useEffect(() => {
    const handleImpactSaved = () => {
      // Small delay to ensure backend has processed the save
      setTimeout(() => {
        loadImpacts();
      }, 100);
    };
    
    window.addEventListener('impactSaved', handleImpactSaved);
    return () => {
      window.removeEventListener('impactSaved', handleImpactSaved);
    };
  }, []);

  // Handle impact selection - only allow one impact selected at a time
  const toggleImpactSelection = (impactId: string) => {
    setSelectedImpactIds(prev => {
      const next = new Set<string>();
      if (!prev.has(impactId)) {
        // Selecting this impact (deselect others)
        next.add(impactId);
      }
      // If already selected, deselect it (empty set)
      return next;
    });
  };

  // Handle editing selected impact (must have exactly one selected)
  const handleEditSelected = () => {
    if (selectedImpactIds.size !== 1) return;
    const impactId = Array.from(selectedImpactIds)[0];
    const impact = impacts.find(i => i.id === impactId);
    if (impact) {
      setEditingImpact(impact);
      setImpactModalOpen(true);
    }
  };

  // Handle deleting selected impacts
  const handleDeleteSelected = async () => {
    if (selectedImpactIds.size === 0) return;
    if (!confirm(`Delete ${selectedImpactIds.size} impact${selectedImpactIds.size > 1 ? 's' : ''}?`)) return;
    
    try {
      const idsToDelete = Array.from(selectedImpactIds);
      const deletePromises = idsToDelete.map(id => deleteImpact(id));
      await Promise.all(deletePromises);
      
      // Clean up impact-scoped state for deleted impacts
      idsToDelete.forEach(id => {
        deleteImpactState(id);
        setImpactState(prev => {
          const copy = { ...prev };
          delete copy[id];
          return copy;
        });
      });
      
      setSelectedImpactIds(new Set());
      loadImpacts();
      // Dispatch event so other components know impacts were deleted
      window.dispatchEvent(new CustomEvent('impactDeleted'));
    } catch (e: any) {
      console.error("Failed to delete impacts:", e);
      alert(`Failed to delete impacts: ${e?.message ?? 'Unknown error'}`);
    }
  };

  // Format impact preview
  const formatImpactPreview = (impact: ImpactEntry): string => {
    const parts: string[] = [];
    if (impact.actions) parts.push(impact.actions);
    if (impact.impact) parts.push(impact.impact);
    return parts.join(" - ").substring(0, 150) + (parts.join(" - ").length > 150 ? "..." : "");
  };

  return (
    <div className="flex h-full flex-col bg-[#343541] overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 border-b border-slate-700 bg-[#343541] px-6 py-4">
        <div className="flex items-center justify-between gap-4">
          <h1 className="text-xl font-semibold text-slate-100">Impact Workspace</h1>
          {/* Mode toggle (small segmented buttons) */}
          <div className="flex gap-1 flex-wrap">
            {BULLET_MODES.map((mode) => (
              <button
                key={mode.id}
                type="button"
                onClick={() => setBulletMode(mode.id)}
                className={`px-2 py-1 rounded-full border text-[11px] transition-colors ${
                  bulletMode === mode.id
                    ? 'bg-emerald-500 text-white border-emerald-500'
                    : 'bg-slate-800 text-slate-300 border-slate-600 hover:bg-slate-700'
                }`}
                title={mode.description}
              >
                {mode.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Main content: 2-column layout (impacts + bullet editor/chat) */}
      <div className="flex-1 flex overflow-hidden min-h-0">
        {/* Left pane: Impact list */}
        <div className="w-80 flex flex-col border-r border-slate-700 bg-[#343541] overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700 flex-shrink-0 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-100">Captured Impacts</h2>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => {
                  setEditingImpact(null);
                  setImpactModalOpen(true);
                }}
                className="rounded border border-emerald-500/60 bg-slate-800 px-2 py-1 text-xs text-emerald-300 hover:bg-emerald-500/10"
                title="Add new impact"
              >
                Add
              </button>
              <button
                onClick={handleEditSelected}
                disabled={selectedImpactIds.size !== 1}
                className="rounded border border-slate-600 bg-slate-800 px-2 py-1 text-xs text-slate-300 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed"
                title="Edit selected impact"
              >
                Edit
              </button>
              <button
                onClick={handleDeleteSelected}
                disabled={selectedImpactIds.size === 0}
                className="rounded border border-red-500/60 bg-slate-800 px-2 py-1 text-xs text-red-400 hover:bg-red-500/10 disabled:opacity-40 disabled:cursor-not-allowed"
                title="Delete selected impacts"
              >
                Delete
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-auto">
            {loadingImpacts ? (
              <div className="p-4 text-xs text-slate-400">Loading impacts...</div>
            ) : impacts.length === 0 ? (
              <div className="p-4 text-xs text-slate-400">
                No impacts captured yet. Use the Impact button in the bottom-left to add one.
              </div>
            ) : (
              impacts.map((impact) => (
                <div
                  key={impact.id}
                  className="border-b border-slate-700 px-4 py-3 hover:bg-slate-800/50 transition-colors"
                >
                  <div className="flex items-start gap-2">
                    <input
                      type="checkbox"
                      checked={selectedImpactIds.has(impact.id)}
                      onChange={() => toggleImpactSelection(impact.id)}
                      className="mt-1 flex-shrink-0"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-sm text-slate-200 mb-1">
                        {impact.title || "(untitled impact)"}
                      </div>
                      {impact.date && (
                        <div className="text-[10px] text-slate-400 mb-1">
                          {new Date(impact.date).toLocaleDateString()}
                        </div>
                      )}
                      {impact.context && (
                        <div className="text-[10px] text-slate-400 mb-1">
                          {impact.context}
                        </div>
                      )}
                      <div className="text-[11px] text-slate-300 line-clamp-2">
                        {formatImpactPreview(impact)}
                      </div>
                      {impact.tags && impact.tags.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-2">
                          {impact.tags.map((tag) => (
                            <span
                              key={tag}
                              className="px-1.5 py-0.5 rounded text-[10px] bg-slate-700 text-slate-300"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Right column: Bullet editor + Chat */}
        <div className={`flex-1 flex flex-col overflow-hidden min-h-0 transition-all duration-300 ${isRagTrayOpen ? 'mr-80' : ''}`}>
          {/* Top: Active bullet editor */}
          {selectedImpactId && selectedState ? (
            <ActiveBulletEditor
              selectedImpact={selectedImpact}
              bulletMode={bulletMode}
              bulletText={selectedState.activeBulletText}
              onChangeText={handleActiveBulletChange}
            />
          ) : (
            <div className="px-6 py-8 border-b border-slate-700 bg-[#343541]">
              <div className="text-sm text-white/70">
                No impact selected — select one on the left to ground the bullet.
              </div>
            </div>
          )}

          {/* Middle: chat messages list */}
          <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
            {selectedImpactId && selectedState ? (
              <ChatMessages
                impactScopedMessages={selectedState.chatMessages}
                onMessagesChange={handleMessagesChange}
                selectedImpactId={selectedImpactId}
                bulletMode={bulletMode}
              />
            ) : (
              <div className="flex-1 flex items-center justify-center">
                <div className="text-sm text-white/60">
                  Select an impact to start drafting bullets.
                </div>
              </div>
            )}
          </div>

          {/* Bottom: composer */}
          <div className="flex-shrink-0 border-t border-slate-700">
            {selectedImpactId && selectedState ? (
              <ImpactWorkspaceChatComposer
                selectedImpacts={selectedImpact ? [selectedImpact] : []}
                bulletMode={bulletMode}
                bulletText={selectedState.activeBulletText}
                ragFileIds={selectedState.ragFileIds}
                onRagFileIdsChange={handleRagFileIdsChange}
                onMessageSent={(message) => {
                  // Add new message to impact-scoped messages
                  handleMessagesChange([...selectedState.chatMessages, message]);
                }}
                onToggleRagTray={() => setIsRagTrayOpen(!isRagTrayOpen)}
                isRagTrayOpen={isRagTrayOpen}
              />
            ) : (
              <div className="px-6 py-4 text-sm text-white/50">
                Select an impact to start chatting.
              </div>
            )}
          </div>
        </div>
        
        {/* RAG Context Tray - Impact-scoped */}
        {selectedImpactId && selectedState && (
          <ImpactScopedRagTray
            isOpen={isRagTrayOpen}
            onClose={() => setIsRagTrayOpen(false)}
            ragFileIds={selectedState.ragFileIds}
            onRagFileIdsChange={handleRagFileIdsChange}
            selectedImpactId={selectedImpactId}
          />
        )}
      </div>

      {/* Impact Capture Modal */}
      <ImpactCaptureModal
        open={impactModalOpen}
        onClose={() => {
          setImpactModalOpen(false);
          setEditingImpact(null);
        }}
        initialImpact={editingImpact}
        onSaved={(entry) => {
          setEditingImpact(null);
          setSelectedImpactIds(new Set());
          loadImpacts();
        }}
      />
    </div>
  );
};
