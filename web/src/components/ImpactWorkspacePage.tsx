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
import { fetchImpacts, uploadTemplate, getTemplate, updateImpact, deleteImpact, test1206Fit, uploadImpactSupportingDoc, deleteImpactSupportingDoc, type Template } from "../utils/api";
import type { ImpactEntry } from "../types/impact";
import ChatMessages from "./ChatMessages";
import { ImpactWorkspaceChatComposer } from "./ImpactWorkspaceChatComposer";
import { ImpactCaptureModal } from "./ImpactCaptureModal";

const IMPACT_PROJECT_NAME = "Impact Workspace";

// OPB Template sections configuration
const OPB_SECTIONS = [
  { key: 'dutyDescription', label: 'Duty Description', max: 450 },
  { key: 'executingTheMission', label: 'Executing the Mission', max: 350 },
  { key: 'leadingPeople', label: 'Leading People', max: 350 },
  { key: 'managingResources', label: 'Managing Resources', max: 350 },
  { key: 'improvingTheUnit', label: 'Improving the Unit', max: 350 },
  { key: 'higherLevelReviewer', label: 'Higher Level Reviewer Assessment', max: 250 },
] as const;

const FORM_1206_SOFT_MAX = 230;

export const ImpactWorkspacePage: React.FC = () => {
  // Impact list state
  const [impacts, setImpacts] = useState<ImpactEntry[]>([]);
  const [selectedImpactIds, setSelectedImpactIds] = useState<Set<string>>(new Set());
  const [loadingImpacts, setLoadingImpacts] = useState(true);
  const [impactModalOpen, setImpactModalOpen] = useState(false);
  const [editingImpact, setEditingImpact] = useState<ImpactEntry | null>(null);
  
  // Template state - single active template only
  const [activeTemplate, setActiveTemplate] = useState<Template | null>(null);
  const [templateFieldValues, setTemplateFieldValues] = useState<Record<string, string>>({});
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  
  // Template mode state (OPB, 1206, none)
  type TemplateMode = 'none' | 'opb' | '1206';
  const [templateMode, setTemplateMode] = useState<TemplateMode>('none');
  const [opbTemplate, setOpbTemplate] = useState<Record<string, string>>({});
  const [form1206Text, setForm1206Text] = useState('');
  const [testing1206, setTesting1206] = useState(false);
  
  // Supporting docs state
  type SupportingDoc = { id: string; name: string };
  const [supportingDocs, setSupportingDocs] = useState<SupportingDoc[]>([]);
  
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

  // Initialize field values when template is set
  useEffect(() => {
    if (activeTemplate) {
      const initialValues: Record<string, string> = {};
      activeTemplate.fields.forEach(field => {
        const fieldId = field.id || field.field_id || "";
        initialValues[fieldId] = "";
      });
      setTemplateFieldValues(initialValues);
    } else {
      setTemplateFieldValues({});
    }
  }, [activeTemplate]);

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
      console.log("Template upload result:", result);
      // Load the uploaded template as the active template
      const template = await getTemplate(result.template_id);
      console.log("Loaded template:", template);
      setActiveTemplate(template);
      setUploadError(null);
    } catch (e: any) {
      console.error("Template upload error:", e);
      setUploadError(e?.message ?? "Failed to upload template");
    } finally {
      setUploading(false);
    }
  };

  // Handle drag and drop
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

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const files = Array.from(e.dataTransfer.files);
    const pdfFile = files.find(f => f.name.toLowerCase().endsWith('.pdf'));
    
    if (pdfFile) {
      handleUploadTemplate(pdfFile);
    } else if (files.length > 0) {
      setUploadError("Only PDF files are supported");
    }
  };

  // Handle clearing the active template
  const handleClearTemplate = () => {
    setActiveTemplate(null);
    setTemplateFieldValues({});
    setUploadError(null);
  };

  // Handle 1206 fit test
  const handleTest1206Fit = async () => {
    if (!form1206Text.trim()) return;
    setTesting1206(true);
    try {
      const res = await test1206Fit(form1206Text);
      if (res.fits) {
        alert('Looks good: this should fit in the 1206 box.');
      } else {
        alert(res.reason || 'This may not fit in the 1206 box.');
      }
    } catch (err: any) {
      console.error('Error testing 1206 fit:', err);
      alert('Error testing 1206 fit.');
    } finally {
      setTesting1206(false);
    }
  };

  // Handle supporting doc upload
  const handleUploadSupportingDocClick = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.onchange = async () => {
      if (!input.files) return;
      for (const file of Array.from(input.files)) {
        try {
          const doc = await uploadImpactSupportingDoc(file);
          setSupportingDocs((prev) => [...prev, doc]);
        } catch (err: any) {
          console.error(`Failed to upload ${file.name}:`, err);
          alert(`Failed to upload ${file.name}: ${err?.message || 'Unknown error'}`);
        }
      }
    };
    input.click();
  };

  // Handle supporting doc removal
  const handleRemoveSupportingDoc = async (id: string) => {
    try {
      await deleteImpactSupportingDoc(id);
      setSupportingDocs((prev) => prev.filter((d) => d.id !== id));
    } catch (err: any) {
      console.error('Failed to remove supporting doc:', err);
      alert('Failed to remove supporting doc.');
    }
  };

  // Format impact preview
  const formatImpactPreview = (impact: ImpactEntry): string => {
    const parts: string[] = [];
    if (impact.actions) parts.push(impact.actions);
    if (impact.impact) parts.push(impact.impact);
    return parts.join(" - ").substring(0, 150) + (parts.join(" - ").length > 150 ? "..." : "");
  };

  // Format file size for display
  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + " " + sizes[i];
  };

  // Format relative time
  const formatRelativeTime = (dateString: string): string => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return "just now";
    if (diffMins < 60) return `${diffMins} minute${diffMins !== 1 ? "s" : ""} ago`;
    if (diffHours < 24) return `${diffHours} hour${diffHours !== 1 ? "s" : ""} ago`;
    if (diffDays < 7) return `${diffDays} day${diffDays !== 1 ? "s" : ""} ago`;
    return date.toLocaleDateString();
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

        {/* Right pane: Template */}
        <div className="flex-1 flex flex-col border-r border-slate-700 bg-[#343541] overflow-hidden">
          {/* Template header with mode selector */}
          <div className="px-4 py-3 border-b border-slate-700 flex-shrink-0 flex items-center justify-between">
            <div className="flex-1">
              <div className="flex items-center justify-between mb-2">
                <h2 className="text-sm font-semibold text-slate-100">Template</h2>
                <div className="flex items-center gap-2">
                  <label className="text-xs text-slate-400">Mode:</label>
                  <select
                    value={templateMode}
                    onChange={(e) => setTemplateMode(e.target.value as TemplateMode)}
                    className="text-xs bg-slate-800 border border-slate-600 rounded px-2 py-1 text-slate-200"
                  >
                    <option value="none">None</option>
                    <option value="opb">OPB (Performance Report)</option>
                    <option value="1206">1206 (Award Package)</option>
                  </select>
                </div>
              </div>
              {activeTemplate && (
                <div className="text-xs text-slate-400">
                  Reference PDF: {activeTemplate.filename} • Uploaded {formatRelativeTime(activeTemplate.created_at)}
                </div>
              )}
            </div>
            {activeTemplate && (
              <button
                onClick={handleClearTemplate}
                className="ml-2 rounded border border-slate-600 bg-slate-800 px-2 py-1 text-xs text-slate-300 hover:bg-slate-700"
              >
                Clear PDF
              </button>
            )}
          </div>
          
          {uploadError && (
            <div className="px-4 py-2 bg-red-500/20 border-b border-red-500/30 text-red-400 text-xs">
              {uploadError}
            </div>
          )}

          <div className="flex-1 overflow-auto p-4">
            {/* Reference PDF Upload Section */}
            <div className="mb-4">
              <div className="text-xs font-semibold text-slate-300 mb-2">Reference PDF</div>
              {!activeTemplate ? (
                <div
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  className={`flex flex-col items-center justify-center py-8 text-center border-2 border-dashed rounded-lg transition-colors ${
                    isDragging
                      ? "border-emerald-500 bg-emerald-500/10"
                      : "border-slate-700 hover:border-slate-600"
                  }`}
                >
                  <p className="text-slate-400 mb-2 text-sm">No reference PDF uploaded.</p>
                  <p className="text-xs text-slate-500 mb-4">Drag and drop a PDF here, or click "Upload PDF..." to start.</p>
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
                    className="rounded border border-emerald-500/60 bg-slate-800 px-4 py-2 text-sm text-emerald-300 hover:bg-emerald-500/10 cursor-pointer"
                  >
                    Upload PDF…
                  </label>
                  <p className="text-xs text-slate-500 mt-2">Reference PDF template. ChatDO will use the OPB/1206 fields below for character limits. The PDF is for your visual reference only.</p>
                </div>
              ) : (
                <div className="border border-slate-700 rounded-lg p-3 bg-slate-800/50">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm text-slate-300">{activeTemplate.filename}</p>
                      {activeTemplate.pages && (
                        <p className="text-xs text-slate-400 mt-1">{activeTemplate.pages} page{activeTemplate.pages !== 1 ? "s" : ""}</p>
                      )}
                    </div>
                    <button
                      onClick={handleClearTemplate}
                      className="rounded border border-slate-600 bg-slate-800 px-2 py-1 text-xs text-slate-300 hover:bg-slate-700"
                    >
                      Remove
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Template Mode Content */}
            {templateMode === 'opb' ? (
              <div className="space-y-4">
                <div className="text-xs font-semibold text-slate-300 mb-3">OPB Template Sections</div>
                {OPB_SECTIONS.map((section) => {
                  const value = opbTemplate[section.key] ?? '';
                  const count = value.length;
                  const over = count > section.max;
                  const remaining = section.max - count;

                  return (
                    <div key={section.key} className="mb-3">
                      <div className="flex justify-between items-center mb-1">
                        <label className="text-xs font-medium text-slate-200">{section.label}</label>
                        <span className={`text-[10px] ${over ? 'text-red-400' : 'text-slate-400'}`}>
                          {over
                            ? `${-remaining} over limit (${count}/${section.max})`
                            : `${remaining} remaining (${count}/${section.max})`}
                        </span>
                      </div>
                      <textarea
                        className={`w-full resize-none rounded bg-slate-800 px-3 py-2 text-xs border ${
                          over ? 'border-red-500' : 'border-slate-700'
                        } text-slate-200`}
                        rows={3}
                        value={value}
                        onChange={(e) =>
                          setOpbTemplate((prev) => ({ ...prev, [section.key]: e.target.value }))
                        }
                      />
                    </div>
                  );
                })}
              </div>
            ) : templateMode === '1206' ? (
              <div className="space-y-4">
                <div className="text-xs font-semibold text-slate-300 mb-3">1206 Bullet</div>
                <div className="space-y-2">
                  <div className="flex justify-between items-center">
                    <label className="text-xs font-medium text-slate-200">1206 Bullet (2-line max)</label>
                    {(() => {
                      const count = form1206Text.length;
                      const remaining = FORM_1206_SOFT_MAX - count;
                      const over = count > FORM_1206_SOFT_MAX;
                      return (
                        <span className={`text-[10px] ${over ? 'text-red-400' : 'text-slate-400'}`}>
                          {over
                            ? `${-remaining} over soft limit (${count}/${FORM_1206_SOFT_MAX})`
                            : `${remaining} remaining (${count}/${FORM_1206_SOFT_MAX})`}
                        </span>
                      );
                    })()}
                  </div>
                  <textarea
                    className={`w-full resize-none rounded bg-slate-800 px-3 py-2 text-xs border ${
                      form1206Text.length > FORM_1206_SOFT_MAX ? 'border-red-500' : 'border-slate-700'
                    } text-slate-200`}
                    rows={4}
                    value={form1206Text}
                    onChange={(e) => setForm1206Text(e.target.value)}
                  />
                  <div className="flex justify-end gap-2">
                    <button
                      type="button"
                      onClick={handleTest1206Fit}
                      disabled={testing1206 || !form1206Text.trim()}
                      className="text-xs px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {testing1206 ? 'Testing...' : 'Test fit in PDF'}
                    </button>
                  </div>
                </div>
              </div>
            ) : null}

            {/* Supporting Docs Panel */}
            <div className="mt-6 border-t border-slate-700 pt-4">
              <div className="flex justify-between items-center mb-2">
                <div className="text-xs font-semibold text-slate-300">Supporting docs</div>
                <button
                  type="button"
                  className="text-[11px] px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-200"
                  onClick={handleUploadSupportingDocClick}
                >
                  Upload…
                </button>
              </div>

              {supportingDocs.length === 0 ? (
                <div className="text-[11px] text-slate-400">
                  No supporting docs added yet. Upload PDFs, Word docs, slides, or spreadsheets you
                  want ChatDO to reference while drafting bullets.
                </div>
              ) : (
                <ul className="space-y-1 max-h-32 overflow-auto text-[11px]">
                  {supportingDocs.map((doc) => (
                    <li key={doc.id} className="flex items-center justify-between gap-2">
                      <span className="truncate text-slate-300">{doc.name}</span>
                      <button
                        type="button"
                        className="text-[10px] text-slate-400 hover:text-red-400"
                        onClick={() => handleRemoveSupportingDoc(doc.id)}
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Legacy PDF template field editors (keep for backward compatibility) */}
            {activeTemplate && activeTemplate.fields && activeTemplate.fields.length > 0 && (
              <div className="mt-6 border-t border-slate-700 pt-4">
                <div className="text-xs font-semibold text-slate-300 mb-3">PDF Template Fields</div>
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
                          {maxChars && (
                            <span className={`text-xs ${charCount > maxChars ? "text-red-400" : "text-slate-400"}`}>
                              {charCount}/{maxChars} characters
                            </span>
                          )}
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
                            setTemplateFieldValues((prev) => ({
                              ...prev,
                              [fieldId]: newValue,
                            }));
                          }}
                          className="w-full rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 resize-none"
                          rows={3}
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
            templateMode={templateMode}
            opbTemplate={opbTemplate}
            form1206Text={form1206Text}
            supportingDocIds={supportingDocs.map(d => d.id)}
          />
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
          // Reload impacts after saving
          setEditingImpact(null);
          setSelectedImpactIds(new Set());
          loadImpacts();
        }}
      />
    </div>
  );
};

