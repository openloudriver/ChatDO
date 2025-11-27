import React, { useState } from "react";
import { createImpact } from "../utils/api";
import type { ImpactCreatePayload } from "../utils/api";
import type { ImpactEntry } from "../types/impact";

interface ImpactCaptureModalProps {
  open: boolean;
  onClose: () => void;
  onSaved?: (entry: ImpactEntry) => void;
  onOpenWorkspace?: () => void;
}

export const ImpactCaptureModal: React.FC<ImpactCaptureModalProps> = ({
  open,
  onClose,
  onSaved,
  onOpenWorkspace,
}) => {
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [context, setContext] = useState("");
  const [actions, setActions] = useState("");
  const [impact, setImpact] = useState("");
  const [metrics, setMetrics] = useState("");
  const [tags, setTags] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const canSave =
    title.trim().length > 0 || actions.trim().length > 0 || impact.trim().length > 0;

  const reset = () => {
    setTitle("");
    setDate("");
    setContext("");
    setActions("");
    setImpact("");
    setMetrics("");
    setTags("");
    setNotes("");
    setError(null);
  };

  const handleSave = async () => {
    if (!canSave || saving) return;

    setSaving(true);
    setError(null);

    try {
      const payload: ImpactCreatePayload = {
        title: title.trim() || "(untitled)",
        date: date || undefined,
        context: context.trim() || undefined,
        actions: actions.trim() || "(no explicit actions provided)",
        impact: impact.trim() || undefined,
        metrics: metrics.trim() || undefined,
        tags: tags
          .split(",")
          .map(t => t.trim())
          .filter(Boolean),
        notes: notes.trim() || undefined,
      };

      const entry = await createImpact(payload);
      onSaved?.(entry);
      onClose();
      reset();
    } catch (e: any) {
      setError(e?.message ?? "Failed to save impact");
    } finally {
      setSaving(false);
    }
  };

  const handleWorkspace = () => {
    if (onOpenWorkspace) onOpenWorkspace();
    onClose();
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-xl rounded-lg bg-slate-900 p-6 shadow-xl border border-slate-700">
        <h2 className="mb-4 text-lg font-semibold text-slate-100">Quick Impact Capture</h2>
        <div className="space-y-3 text-sm text-slate-100">
          <input
            className="w-full rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
            placeholder="Short title (e.g., 'Led Joint Cloud brief to MAJCOMs')"
            value={title}
            onChange={e => setTitle(e.target.value)}
          />
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
                Date
              </label>
              <input
                type="date"
                className="w-full rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
                value={date}
                onChange={e => setDate(e.target.value)}
              />
            </div>
            <div className="flex-[2]">
              <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
                Context (where / who / mission)
              </label>
              <input
                className="w-full rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
                placeholder="ex: AFRL / Joint Cloud / MAJCOM commanders"
                value={context}
                onChange={e => setContext(e.target.value)}
              />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
              What did you do? (Actions)
            </label>
            <textarea
              className="h-16 w-full resize-none rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
              placeholder="Quickly jot what you actually did, in your own words…"
              value={actions}
              onChange={e => setActions(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
              Why did it matter? (Impact / result)
            </label>
            <textarea
              className="h-16 w-full resize-none rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
              placeholder="Who benefited? What changed? What did you unlock/prevent/save?"
              value={impact}
              onChange={e => setImpact(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
              Numbers / scope (optional)
            </label>
            <input
              className="w-full rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
              placeholder="ex: 8 MAJCOMs / $27M portfolio / 1200 Airmen / 3 yr roadmap"
              value={metrics}
              onChange={e => setMetrics(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
              Tags (optional, comma-separated)
            </label>
            <input
              className="w-full rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
              placeholder="ex: AF, Northstead, PrivacyPay"
              value={tags}
              onChange={e => setTags(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
              Notes (optional)
            </label>
            <textarea
              className="h-16 w-full resize-none rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
              placeholder="Any extra details we might want later for narratives/1206s…"
              value={notes}
              onChange={e => setNotes(e.target.value)}
            />
          </div>
          {error && <div className="text-xs text-red-400">{error}</div>}
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            className="rounded px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="button"
            className="rounded px-3 py-2 text-sm text-slate-200 hover:bg-slate-800 border border-slate-600"
            onClick={handleWorkspace}
          >
            Workspace
          </button>
          <button
            type="button"
            disabled={!canSave || saving}
            className={`rounded px-3 py-2 text-sm font-semibold ${
              canSave && !saving
                ? "bg-emerald-500 text-slate-900 hover:bg-emerald-400"
                : "bg-slate-700 text-slate-400 cursor-not-allowed"
            }`}
            onClick={handleSave}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
};

