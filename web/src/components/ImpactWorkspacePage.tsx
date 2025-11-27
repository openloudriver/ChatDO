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
 */
import React, { useEffect, useState } from "react";
import { useChatStore } from "../store/chat";
import { fetchImpacts, updateImpact, deleteImpact } from "../utils/api";
import type { ImpactEntry } from "../types/impact";
import ChatMessages from "./ChatMessages";
import { ImpactWorkspaceChatComposer } from "./ImpactWorkspaceChatComposer";
import { ImpactCaptureModal } from "./ImpactCaptureModal";
import { ActiveBulletEditor, type BulletMode, BULLET_MODES } from "./ActiveBulletEditor";

const IMPACT_PROJECT_NAME = "Impact Workspace";

export const ImpactWorkspacePage: React.FC = () => {
  // Impact list state
  const [impacts, setImpacts] = useState<ImpactEntry[]>([]);
  const [selectedImpactIds, setSelectedImpactIds] = useState<Set<string>>(new Set());
  const [loadingImpacts, setLoadingImpacts] = useState(true);
  const [impactModalOpen, setImpactModalOpen] = useState(false);
  const [editingImpact, setEditingImpact] = useState<ImpactEntry | null>(null);
  
  // Get RAG tray state for layout adjustment
  const isRagTrayOpen = useChatStore((state) => state.isRagTrayOpen);
  
  // Bullet editor state
  const [bulletMode, setBulletMode] = useState<BulletMode>('1206_2LINE');
  const [bulletText, setBulletText] = useState('');
  
  // Get the selected impact (first selected, or null)
  const selectedImpact = impacts.find(i => selectedImpactIds.has(i.id)) || null;
  
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

  // Handle impact selection
  const toggleImpactSelection = (impactId: string) => {
    setSelectedImpactIds(prev => {
      const next = new Set(prev);
      if (next.has(impactId)) {
        next.delete(impactId);
      } else {
        next.add(impactId);
      }
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
      const deletePromises = Array.from(selectedImpactIds).map(id => deleteImpact(id));
      await Promise.all(deletePromises);
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
          <ActiveBulletEditor
            selectedImpact={selectedImpact}
            bulletMode={bulletMode}
            bulletText={bulletText}
            onChangeText={setBulletText}
          />

          {/* Middle: chat messages list */}
          <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
            <ChatMessages />
          </div>

          {/* Bottom: composer */}
          <div className="flex-shrink-0 border-t border-slate-700">
            <ImpactWorkspaceChatComposer
              selectedImpacts={impacts.filter(i => selectedImpactIds.has(i.id))}
              bulletMode={bulletMode}
              bulletText={bulletText}
            />
          </div>
        </div>
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
