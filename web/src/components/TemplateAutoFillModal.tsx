import React, { useState, useEffect } from "react";
import { autofillTemplate, getLatestAutofill, type Template, type AutofillResponse } from "../utils/api";
import { fetchImpacts, type ImpactEntry } from "../utils/api";

interface TemplateAutoFillModalProps {
  open: boolean;
  onClose: () => void;
  template: Template | null;
  onAutofilled?: (response: AutofillResponse) => void;
}

export const TemplateAutoFillModal: React.FC<TemplateAutoFillModalProps> = ({
  open,
  onClose,
  template,
  onAutofilled,
}) => {
  const [impacts, setImpacts] = useState<ImpactEntry[]>([]);
  const [loadingImpacts, setLoadingImpacts] = useState(true);
  const [fieldAssignments, setFieldAssignments] = useState<Record<string, string>>({});
  const [autofilling, setAutofilling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autofillResult, setAutofillResult] = useState<AutofillResponse | null>(null);

  useEffect(() => {
    if (open && template) {
      loadImpacts();
      // Reset state
      setFieldAssignments({});
      setAutofillResult(null);
      setError(null);
    }
  }, [open, template]);

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

  const handleAutofill = async () => {
    if (!template) return;

    // Check that all fields have assignments
    const unassignedFields = template.fields.filter(
      (f) => !fieldAssignments[f.field_id]
    );
    if (unassignedFields.length > 0) {
      setError(`Please assign impacts to all fields. Missing: ${unassignedFields.map(f => f.label).join(", ")}`);
      return;
    }

    setAutofilling(true);
    setError(null);

    try {
      const result = await autofillTemplate(template.template_id, fieldAssignments);
      setAutofillResult(result);
      onAutofilled?.(result);
    } catch (e: any) {
      setError(e?.message ?? "Failed to autofill template");
    } finally {
      setAutofilling(false);
    }
  };

  const handleDownload = () => {
    if (!autofillResult) return;

    const blob = new Blob([autofillResult.output_text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${template?.filename || "autofilled"}_${new Date().toISOString().split("T")[0]}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  if (!open || !template) return null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-2xl rounded-lg bg-slate-900 p-6 shadow-xl border border-slate-700 max-h-[90vh] overflow-y-auto">
        <h2 className="mb-4 text-lg font-semibold text-slate-100">
          Auto-fill Template: {template.filename}
        </h2>

        {error && (
          <div className="mb-4 p-3 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 text-sm">
            {error}
          </div>
        )}

        {autofillResult ? (
          <div className="space-y-4">
            <div className="p-4 bg-green-500/20 border border-green-500/30 rounded-lg">
              <p className="text-green-400 text-sm font-semibold mb-2">
                ✓ Template autofilled successfully!
              </p>
              <p className="text-slate-300 text-xs">
                Output saved to: {autofillResult.output_path}
              </p>
            </div>

            <div className="border border-slate-700 rounded-lg p-4 bg-slate-800">
              <h3 className="text-sm font-semibold text-slate-200 mb-2">Preview:</h3>
              <pre className="text-xs text-slate-300 whitespace-pre-wrap max-h-64 overflow-y-auto">
                {autofillResult.output_text}
              </pre>
            </div>

            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="rounded px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"
                onClick={onClose}
              >
                Close
              </button>
              <button
                type="button"
                className="rounded px-3 py-2 text-sm font-semibold bg-emerald-500 text-slate-900 hover:bg-emerald-400"
                onClick={handleDownload}
              >
                Download
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {loadingImpacts ? (
              <div className="text-sm text-slate-400">Loading impacts...</div>
            ) : (
              <>
                <div className="text-sm text-slate-300 mb-4">
                  Assign captured impacts to each template field:
                </div>

                <div className="space-y-3">
                  {template.fields.map((field) => (
                    <div key={field.field_id} className="border border-slate-700 rounded-lg p-3 bg-slate-800">
                      <label className="block text-xs font-semibold text-slate-200 mb-1">
                        {field.label}
                      </label>
                      {field.instructions && (
                        <p className="text-xs text-slate-400 mb-2">{field.instructions}</p>
                      )}
                      <select
                        className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                        value={fieldAssignments[field.field_id] || ""}
                        onChange={(e) =>
                          setFieldAssignments({
                            ...fieldAssignments,
                            [field.field_id]: e.target.value,
                          })
                        }
                      >
                        <option value="">-- Select impact --</option>
                        {impacts.map((impact) => (
                          <option key={impact.id} value={impact.id}>
                            {impact.title || "(untitled)"} - {impact.date || "No date"}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>

                <div className="flex justify-end gap-2 pt-4 border-t border-slate-700">
                  <button
                    type="button"
                    className="rounded px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"
                    onClick={onClose}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    disabled={autofilling}
                    className={`rounded px-3 py-2 text-sm font-semibold ${
                      autofilling
                        ? "bg-slate-700 text-slate-400 cursor-not-allowed"
                        : "bg-emerald-500 text-slate-900 hover:bg-emerald-400"
                    }`}
                    onClick={handleAutofill}
                  >
                    {autofilling ? "Auto-filling..." : "Auto-fill"}
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

