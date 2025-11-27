import React, { useEffect, useState } from "react";
import {
  fetchImpacts,
  updateImpact,
  fetchImpactTemplates,
  uploadImpactTemplate,
  deleteImpactTemplate,
  listTemplates,
  uploadTemplate,
  type Template,
  type AutofillResponse,
} from "../utils/api";
import type { ImpactEntry, ImpactTemplate } from "../types/impact";
import { TemplateAutoFillModal } from "./TemplateAutoFillModal";

const ImpactWorkspace: React.FC = () => {
  const [impacts, setImpacts] = useState<ImpactEntry[]>([]);
  const [templates, setTemplates] = useState<ImpactTemplate[]>([]);
  const [autofillTemplates, setAutofillTemplates] = useState<Template[]>([]);
  const [loadingImpacts, setLoadingImpacts] = useState(true);
  const [loadingTemplates, setLoadingTemplates] = useState(true);
  const [loadingAutofillTemplates, setLoadingAutofillTemplates] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [autofillModalOpen, setAutofillModalOpen] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);

  // template upload state
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadName, setUploadName] = useState("");
  const [uploadDescription, setUploadDescription] = useState("");
  const [uploadTags, setUploadTags] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  useEffect(() => {
    const loadImpacts = async () => {
      try {
        setLoadingImpacts(true);
        const data = await fetchImpacts();
        setImpacts(data);
      } catch (e: any) {
        setError(e?.message ?? "Failed to load impacts");
      } finally {
        setLoadingImpacts(false);
      }
    };

    const loadTemplates = async () => {
      try {
        setLoadingTemplates(true);
        const data = await fetchImpactTemplates();
        setTemplates(data);
      } catch (e: any) {
        setError(e?.message ?? "Failed to load templates");
      } finally {
        setLoadingTemplates(false);
      }
    };

    const loadAutofillTemplates = async () => {
      try {
        setLoadingAutofillTemplates(true);
        const data = await listTemplates();
        setAutofillTemplates(data);
      } catch (e: any) {
        setError(e?.message ?? "Failed to load autofill templates");
      } finally {
        setLoadingAutofillTemplates(false);
      }
    };

    loadImpacts();
    loadTemplates();
    loadAutofillTemplates();
  }, []);

  const handleFieldChange = (id: string, field: keyof ImpactEntry, value: string) => {
    setImpacts(prev =>
      prev.map(item => (item.id === id ? { ...item, [field]: value } : item)),
    );
  };

  const handleSaveRow = async (entry: ImpactEntry) => {
    setSavingId(entry.id);
    setError(null);
    try {
      await updateImpact(entry.id, {
        title: entry.title,
        date: entry.date,
        context: entry.context,
        actions: entry.actions,
        impact: entry.impact,
        metrics: entry.metrics,
        notes: entry.notes,
        tags: entry.tags,
      });
    } catch (e: any) {
      setError(e?.message ?? "Failed to save impact");
    } finally {
      setSavingId(null);
    }
  };

  const reloadTemplates = async () => {
    try {
      setLoadingTemplates(true);
      const data = await fetchImpactTemplates();
      setTemplates(data);
    } catch (e: any) {
      setError(e?.message ?? "Failed to load templates");
    } finally {
      setLoadingTemplates(false);
    }
  };

  const handleUploadTemplate = async () => {
    if (!uploadFile || !uploadName.trim()) {
      setUploadError("Template name and file are required");
      return;
    }

    setUploading(true);
    setUploadError(null);

    try {
      await uploadImpactTemplate({
        file: uploadFile,
        name: uploadName.trim(),
        description: uploadDescription.trim() || undefined,
        tags: uploadTags.trim() || undefined,
      });
      setUploadOpen(false);
      setUploadName("");
      setUploadDescription("");
      setUploadTags("");
      setUploadFile(null);
      await reloadTemplates();
    } catch (e: any) {
      setUploadError(e?.message ?? "Failed to upload template");
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteTemplate = async (id: string) => {
    if (!window.confirm("Delete this template? This cannot be undone.")) return;

    try {
      await deleteImpactTemplate(id);
      setTemplates(prev => prev.filter(t => t.id !== id));
    } catch (e: any) {
      setError(e?.message ?? "Failed to delete template");
    }
  };

  return (
    <div className="flex h-full flex-col gap-6 p-6 text-slate-100 overflow-auto bg-[#343541]">
      <div>
        <h1 className="text-xl font-semibold mb-2">Impact Workspace</h1>
        <p className="text-sm text-slate-400">
          Quick captures land here. Templates are uploadable and model-agnostic, so we can reuse
          this workspace for DAF 1206s, OPBs, BAH reports, and Northstead write-ups.
        </p>
      </div>

      {/* Autofill Templates section */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-300">
            Autofill Templates
          </h2>
          <button
            type="button"
            className="rounded border border-slate-600 bg-slate-900 px-3 py-1.5 text-xs hover:bg-slate-800"
            onClick={async () => {
              const input = document.createElement("input");
              input.type = "file";
              input.accept = ".pdf,.docx,.doc,.xlsx,.xls,.pptx,.ppt,.txt,.md";
              input.onchange = async (e) => {
                const file = (e.target as HTMLInputElement).files?.[0];
                if (file) {
                  try {
                    setError(null);
                    await uploadTemplate(file);
                    // Reload templates
                    const data = await listTemplates();
                    setAutofillTemplates(data);
                  } catch (e: any) {
                    setError(e?.message ?? "Failed to upload template");
                  }
                }
              };
              input.click();
            }}
          >
            Upload template…
          </button>
        </div>
        {loadingAutofillTemplates && (
          <div className="text-sm text-slate-400">Loading templates…</div>
        )}
        {!loadingAutofillTemplates && autofillTemplates.length === 0 && (
          <div className="text-sm text-slate-400">
            No templates uploaded yet. Use "Upload template…" to add PDF/DOCX/XLSX/etc. templates for autofilling.
          </div>
        )}
        <div className="space-y-2">
          {autofillTemplates.map((tpl) => (
            <div
              key={tpl.template_id}
              className="flex items-center justify-between rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
            >
              <div className="flex flex-col">
                <span className="font-medium">{tpl.filename}</span>
                <span className="text-xs text-slate-400">
                  {tpl.fields.length} field{tpl.fields.length !== 1 ? "s" : ""} identified
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="rounded border border-emerald-500/60 bg-slate-900 px-2 py-1 text-xs text-emerald-300 hover:bg-emerald-500/10"
                  onClick={() => {
                    setSelectedTemplate(tpl);
                    setAutofillModalOpen(true);
                  }}
                >
                  Auto-fill…
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Impact Templates section (for reference forms) */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-300">
            Reference Templates
          </h2>
          <button
            type="button"
            className="rounded border border-slate-600 bg-slate-900 px-3 py-1.5 text-xs hover:bg-slate-800"
            onClick={() => setUploadOpen(true)}
          >
            Upload template…
          </button>
        </div>
        {loadingTemplates && (
          <div className="text-sm text-slate-400">Loading templates…</div>
        )}
        {!loadingTemplates && templates.length === 0 && (
          <div className="text-sm text-slate-400">
            No templates uploaded yet. Use "Upload template…" to add 1206/OPB/BAH/other forms.
          </div>
        )}
        <div className="space-y-2">
          {templates.map(tpl => (
            <div
              key={tpl.id}
              className="flex items-center justify-between rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
            >
              <div className="flex flex-col">
                <span className="font-medium">{tpl.name}</span>
                <span className="text-xs text-slate-400">
                  {tpl.description || tpl.file_name}
                </span>
                {tpl.tags && tpl.tags.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {tpl.tags.map(tag => (
                      <span
                        key={tag}
                        className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-300"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-2">
                <a
                  href={`http://localhost:8000/api/impact-templates/${tpl.id}/file`}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded border border-slate-600 bg-slate-900 px-2 py-1 text-xs hover:bg-slate-800"
                >
                  Open
                </a>
                <button
                  type="button"
                  className="rounded border border-red-500/60 bg-slate-900 px-2 py-1 text-xs text-red-300 hover:bg-red-500/10"
                  onClick={() => handleDeleteTemplate(tpl.id)}
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>

        {/* Upload template modal */}
        {uploadOpen && (
          <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40">
            <div className="w-full max-w-md rounded-lg bg-slate-900 p-6 shadow-xl border border-slate-700">
              <h2 className="mb-4 text-lg font-semibold text-slate-100">
                Upload Impact Template
              </h2>
              <div className="space-y-3 text-sm text-slate-100">
                <div>
                  <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
                    Template name
                  </label>
                  <input
                    className="w-full rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
                    value={uploadName}
                    onChange={e => setUploadName(e.target.value)}
                    placeholder="ex: DAF 1206 Blank v1, EPB/OPB Workbench, Northstead Quarterly"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
                    Description (optional)
                  </label>
                  <input
                    className="w-full rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
                    value={uploadDescription}
                    onChange={e => setUploadDescription(e.target.value)}
                    placeholder="Short note about how this template is used"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
                    Tags (optional, comma-separated)
                  </label>
                  <input
                    className="w-full rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
                    value={uploadTags}
                    onChange={e => setUploadTags(e.target.value)}
                    placeholder="ex: AF, 1206, OPB, Northstead"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
                    File
                  </label>
                  <input
                    type="file"
                    className="w-full text-xs text-slate-300"
                    onChange={e => setUploadFile(e.target.files?.[0] ?? null)}
                  />
                </div>
                {uploadError && (
                  <div className="text-xs text-red-400">{uploadError}</div>
                )}
              </div>
              <div className="mt-6 flex justify-end gap-2">
                <button
                  type="button"
                  className="rounded px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"
                  onClick={() => {
                    setUploadOpen(false);
                    setUploadError(null);
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={uploading}
                  className={`rounded px-3 py-2 text-sm font-semibold ${
                    uploading
                      ? "bg-slate-700 text-slate-400 cursor-wait"
                      : "bg-emerald-500 text-slate-900 hover:bg-emerald-400"
                  }`}
                  onClick={handleUploadTemplate}
                >
                  {uploading ? "Uploading…" : "Upload"}
                </button>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Impacts section */}
      <section className="flex-1 overflow-auto">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-300">
          Captured Impacts
        </h2>
        {loadingImpacts && (
          <div className="text-sm text-slate-400">Loading impacts…</div>
        )}
        {error && <div className="text-sm text-red-400 mb-2">{error}</div>}
        {!loadingImpacts && impacts.length === 0 && (
          <div className="text-sm text-slate-400">
            No impacts captured yet. Use the Impact button in the bottom-left to add one.
          </div>
        )}
        <div className="space-y-4">
          {impacts.map(entry => (
            <div
              key={entry.id}
              className="rounded-lg border border-slate-700 bg-slate-900 p-4 text-sm"
            >
              <div className="mb-2 flex gap-3">
                <input
                  className="flex-1 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-sm"
                  value={entry.title}
                  onChange={e => handleFieldChange(entry.id, "title", e.target.value)}
                />
                <input
                  type="date"
                  className="w-40 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-sm"
                  value={entry.date ?? ""}
                  onChange={e => handleFieldChange(entry.id, "date", e.target.value)}
                />
              </div>
              <div className="mb-2">
                <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
                  Context
                </label>
                <input
                  className="w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 text-sm"
                  value={entry.context ?? ""}
                  onChange={e => handleFieldChange(entry.id, "context", e.target.value)}
                />
              </div>
              <div className="mb-2 grid gap-2 md:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
                    Actions
                  </label>
                  <textarea
                    className="h-20 w-full resize-none rounded border border-slate-700 bg-slate-800 px-2 py-1 text-sm"
                    value={entry.actions}
                    onChange={e => handleFieldChange(entry.id, "actions", e.target.value)}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
                    Impact / result
                  </label>
                  <textarea
                    className="h-20 w-full resize-none rounded border border-slate-700 bg-slate-800 px-2 py-1 text-sm"
                    value={entry.impact ?? ""}
                    onChange={e => handleFieldChange(entry.id, "impact", e.target.value)}
                  />
                </div>
              </div>
              <div className="mb-2 grid gap-2 md:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
                    Numbers / scope
                  </label>
                  <input
                    className="w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 text-sm"
                    value={entry.metrics ?? ""}
                    onChange={e => handleFieldChange(entry.id, "metrics", e.target.value)}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
                    Notes
                  </label>
                  <textarea
                    className="h-16 w-full resize-none rounded border border-slate-700 bg-slate-800 px-2 py-1 text-sm"
                    value={entry.notes ?? ""}
                    onChange={e => handleFieldChange(entry.id, "notes", e.target.value)}
                  />
                </div>
              </div>
              <div className="flex items-center justify-between">
                <div className="text-xs text-slate-500">
                  Last updated: {new Date(entry.updated_at).toLocaleString()}
                </div>
                <button
                  type="button"
                  className="rounded px-3 py-1 text-xs font-semibold bg-emerald-500 text-slate-900 hover:bg-emerald-400 disabled:bg-slate-700 disabled:text-slate-400"
                  disabled={savingId === entry.id}
                  onClick={() => handleSaveRow(entry)}
                >
                  {savingId === entry.id ? "Saving…" : "Save"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Template AutoFill Modal */}
      <TemplateAutoFillModal
        open={autofillModalOpen}
        onClose={() => {
          setAutofillModalOpen(false);
          setSelectedTemplate(null);
        }}
        template={selectedTemplate}
        onAutofilled={(response) => {
          // Optionally reload templates or show success message
          console.log("Template autofilled:", response);
        }}
      />
    </div>
  );
};

export default ImpactWorkspace;

