/**
 * Impact Workspace Page - Unified 3-pane layout
 * 
 * Architecture:
 * - Left pane: Impact list with checkboxes for selection
 * - Right pane: PDF template upload + field editors with character counters
 * - Bottom pane: Chat with GPT-5, context-aware (selected impacts + template fields)
 * 
 * Replaces:
 * - Old tabbed ImpactWorkspace (Manage/Chat tabs)
 * - Separate ImpactWorkspaceChat component
 * - Autofill vs Reference template split
 * 
 * Backend:
 * - Uses /api/impacts for impact data
 * - Uses /api/templates for template management
 * - PDF field extraction via PyPDF2 (AcroForm fields)
 * - Falls back to GPT-5 analysis if no PDF fields found
 */
import React, { useEffect, useState } from "react";
import { useChatStore } from "../store/chat";
import { fetchImpacts, listTemplates, uploadTemplate, getTemplate, deleteTemplate, type Template } from "../utils/api";
import type { ImpactEntry } from "../types/impact";
import ChatMessages from "./ChatMessages";
import { ImpactWorkspaceChatComposer } from "./ImpactWorkspaceChatComposer";

const IMPACT_PROJECT_NAME = "Impact Workspace";

export const ImpactWorkspacePage: React.FC = () => {
  // Impact list state
  const [impacts, setImpacts] = useState<ImpactEntry[]>([]);
  const [selectedImpactIds, setSelectedImpactIds] = useState<Set<string>>(new Set());
  const [loadingImpacts, setLoadingImpacts] = useState(true);
  
  // Template state
  const [templates, setTemplates] = useState<Template[]>([]);
  const [activeTemplateId, setActiveTemplateId] = useState<string | null>(null);
  const [activeTemplate, setActiveTemplate] = useState<Template | null>(null);
  const [templateFieldValues, setTemplateFieldValues] = useState<Record<string, string>>({});
  const [loadingTemplates, setLoadingTemplates] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  
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
  }, [currentProject, setCurrentProject, loadProjects, loadChats, createNewChatInProject, setCurrentConversation]);

  // Load impacts
  useEffect(() => {
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
    
    loadImpacts();
  }, []);

  // Load templates
  useEffect(() => {
    const loadTemplatesData = async () => {
      try {
        setLoadingTemplates(true);
        const data = await listTemplates();
        setTemplates(data);
      } catch (e: any) {
        console.error("Failed to load templates:", e);
      } finally {
        setLoadingTemplates(false);
      }
    };
    
    loadTemplatesData();
  }, []);

  // Load active template when ID changes
  useEffect(() => {
    if (activeTemplateId) {
      const loadActiveTemplate = async () => {
        try {
          const template = await getTemplate(activeTemplateId);
          setActiveTemplate(template);
          // Initialize field values
          const initialValues: Record<string, string> = {};
          template.fields.forEach(field => {
            const fieldId = field.id || field.field_id || "";
            initialValues[fieldId] = "";
          });
          setTemplateFieldValues(initialValues);
        } catch (e) {
          console.error("Failed to load template:", e);
          setActiveTemplate(null);
        }
      };
      loadActiveTemplate();
    } else {
      setActiveTemplate(null);
      setTemplateFieldValues({});
    }
  }, [activeTemplateId]);

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

  // Handle template upload
  const handleUploadTemplate = async (file: File) => {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setUploadError("Only PDF files are supported");
      return;
    }

    setUploading(true);
    setUploadError(null);

    try {
      const result = await uploadTemplate(file);
      await reloadTemplates();
      setActiveTemplateId(result.template_id);
    } catch (e: any) {
      setUploadError(e?.message ?? "Failed to upload template");
    } finally {
      setUploading(false);
    }
  };

  // Handle template deletion
  const handleDeleteTemplate = async () => {
    if (!activeTemplateId || !activeTemplate) return;
    
    if (!window.confirm(`Delete template "${activeTemplate.filename}"? This will remove the file and its schema from the Impact Workspace. This will not delete your captured impacts.`)) {
      return;
    }

    try {
      await deleteTemplate(activeTemplateId);
      setActiveTemplateId(null);
      setActiveTemplate(null);
      await reloadTemplates();
    } catch (e: any) {
      console.error("Failed to delete template:", e);
      alert("Failed to delete template");
    }
  };

  // Format impact preview
  const formatImpactPreview = (impact: ImpactEntry): string => {
    const parts: string[] = [];
    if (impact.actions) parts.push(impact.actions);
    if (impact.impact) parts.push(impact.impact);
    return parts.join(" - ").substring(0, 150) + (parts.join(" - ").length > 150 ? "..." : "");
  };

  const reloadTemplates = async () => {
    try {
      setLoadingTemplates(true);
      const data = await listTemplates();
      setTemplates(data);
    } catch (e: any) {
      console.error("Failed to load templates:", e);
    } finally {
      setLoadingTemplates(false);
    }
  };

  return (
    <div className="flex h-full flex-col bg-[#343541] overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 border-b border-slate-700 bg-[#343541] px-6 py-4">
        <h1 className="text-xl font-semibold text-slate-100 mb-1">Impact Workspace</h1>
        <p className="text-sm text-slate-400">
          Select impacts, upload a template, and chat with GPT-5 to draft your bullets.
        </p>
      </div>

      {/* Main content: 2-pane layout (impacts + template) */}
      <div className="flex-1 flex overflow-hidden min-h-0">
        {/* Left pane: Impact list */}
        <div className="w-80 flex flex-col border-r border-slate-700 bg-[#343541] overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700 flex-shrink-0">
            <h2 className="text-sm font-semibold text-slate-100">Captured Impacts</h2>
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

        {/* Right pane: Template */}
        <div className="flex-1 flex flex-col border-r border-slate-700 bg-[#343541] overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700 flex-shrink-0 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-100">Template</h2>
            <div className="flex items-center gap-2">
              <select
                value={activeTemplateId || ""}
                onChange={(e) => setActiveTemplateId(e.target.value || null)}
                className="rounded border border-slate-600 bg-slate-800 px-2 py-1 text-xs text-slate-100"
              >
                <option value="">-- Select template --</option>
                {templates.map((t) => (
                  <option key={t.template_id} value={t.template_id}>
                    {t.filename}
                  </option>
                ))}
              </select>
              <input
                type="file"
                accept=".pdf"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleUploadTemplate(file);
                }}
                className="hidden"
                id="template-upload"
              />
              <label
                htmlFor="template-upload"
                className="rounded border border-slate-600 bg-slate-800 px-2 py-1 text-xs text-slate-100 hover:bg-slate-700 cursor-pointer"
              >
                {uploading ? "Uploading..." : "Upload template…"}
              </label>
              {activeTemplate && (
                <button
                  onClick={handleDeleteTemplate}
                  className="rounded border border-red-500/60 bg-slate-800 px-2 py-1 text-xs text-red-300 hover:bg-red-500/10"
                >
                  Delete
                </button>
              )}
            </div>
          </div>
          
          {uploadError && (
            <div className="px-4 py-2 bg-red-500/20 border-b border-red-500/30 text-red-400 text-xs">
              {uploadError}
            </div>
          )}

          <div className="flex-1 overflow-auto p-4">
            {!activeTemplate ? (
              <div className="flex flex-col items-center justify-center h-full text-center">
                <p className="text-slate-400 mb-4">No template selected.</p>
                <label
                  htmlFor="template-upload"
                  className="rounded border border-emerald-500/60 bg-slate-800 px-4 py-2 text-sm text-emerald-300 hover:bg-emerald-500/10 cursor-pointer"
                >
                  Upload template…
                </label>
                <p className="text-xs text-slate-500 mt-2">PDFs with form fields work best.</p>
              </div>
            ) : (
              <div className="space-y-4">
                {/* PDF Preview placeholder */}
                <div className="border border-slate-700 rounded-lg p-4 bg-slate-800/50">
                  <p className="text-xs text-slate-400 mb-2">Preview not available yet.</p>
                  <p className="text-sm text-slate-300">Template: {activeTemplate.filename}</p>
                  {activeTemplate.pages && (
                    <p className="text-xs text-slate-400 mt-1">{activeTemplate.pages} page{activeTemplate.pages !== 1 ? "s" : ""}</p>
                  )}
                </div>

                {/* Field editors */}
                <div className="space-y-4">
                  {activeTemplate.fields.map((field) => {
                    const fieldId = field.id || field.field_id || "";
                    const fieldName = field.name || field.label || fieldId;
                    const maxChars = field.maxChars;
                    const currentValue = templateFieldValues[fieldId] || "";
                    const charCount = currentValue.length;
                    
                    return (
                      <div key={fieldId} className="border border-slate-700 rounded-lg p-3 bg-slate-800/50">
                        <div className="flex items-center justify-between mb-2">
                          <label className="text-sm font-medium text-slate-200">
                            {fieldName}
                            {field.page && <span className="text-xs text-slate-400 ml-2">(page {field.page})</span>}
                          </label>
                          <span className={`text-xs ${maxChars && charCount > maxChars ? "text-red-400" : "text-slate-400"}`}>
                            {maxChars ? `${charCount}/${maxChars} characters` : `${charCount} characters`}
                          </span>
                        </div>
                        {field.instructions && (
                          <p className="text-xs text-slate-400 mb-2">{field.instructions}</p>
                        )}
                        <textarea
                          value={currentValue}
                          onChange={(e) => {
                            const newValue = e.target.value;
                            if (maxChars && newValue.length > maxChars) {
                              return; // Don't allow exceeding max
                            }
                            setTemplateFieldValues(prev => ({
                              ...prev,
                              [fieldId]: newValue,
                            }));
                          }}
                          className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-100 resize-none"
                          rows={4}
                          placeholder="Enter text for this field..."
                        />
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Bottom pane: Chat */}
      <div className="h-96 flex-shrink-0 border-t border-slate-700 bg-[#343541] flex flex-col overflow-hidden">
        <div className="flex-1 overflow-hidden flex flex-col min-h-0">
          <ChatMessages />
        </div>
        <div className="flex-shrink-0 border-t border-slate-700">
          <ImpactWorkspaceChatComposer
            selectedImpacts={impacts.filter(i => selectedImpactIds.has(i.id))}
            activeTemplate={activeTemplate}
            templateFieldValues={templateFieldValues}
          />
        </div>
      </div>
    </div>
  );
};

