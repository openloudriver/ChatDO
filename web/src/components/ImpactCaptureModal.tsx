import React, { useState, useEffect } from "react";
import { createImpact, updateImpact } from "../utils/api";
import type { ImpactCreatePayload } from "../utils/api";
import type { ImpactEntry } from "../types/impact";

interface ImpactCaptureModalProps {
  open: boolean;
  onClose: () => void;
  onSaved?: (entry: ImpactEntry) => void;
  onOpenWorkspace?: (entry?: ImpactEntry) => void;
  initialImpact?: ImpactEntry | null;
}

export const ImpactCaptureModal: React.FC<ImpactCaptureModalProps> = ({
  open,
  onClose,
  onSaved,
  onOpenWorkspace,
  initialImpact,
}) => {
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [actions, setActions] = useState("");
  const [impact, setImpact] = useState("");
  const [metrics, setMetrics] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Populate fields when editing
  useEffect(() => {
    if (open && initialImpact) {
      setTitle(initialImpact.title || "");
      setDate(initialImpact.date ? new Date(initialImpact.date).toISOString().split('T')[0] : "");
      setActions(initialImpact.actions || "");
      setImpact(initialImpact.impact || "");
      setMetrics(initialImpact.metrics || "");
      setNotes(initialImpact.notes || "");
    } else if (open && !initialImpact) {
      // Reset for new impact
      reset();
    }
  }, [open, initialImpact]);

  if (!open) return null;

  const canSave =
    title.trim().length > 0 || actions.trim().length > 0 || impact.trim().length > 0;

  const reset = () => {
    setTitle("");
    setDate("");
    setActions("");
    setImpact("");
    setMetrics("");
    setNotes("");
    setError(null);
  };

  const handleSave = async () => {
    if (!canSave || saving) return;

    setSaving(true);
    setError(null);

    try {
      // Validate and convert date format if provided
      let dateValue: string | null = null;
      if (date && date.trim()) {
        const trimmedDate = date.trim();
        let dateStr = trimmedDate;
        
        // Check if it's in MM/DD/YYYY format and convert to YYYY-MM-DD
        const mmddyyyyMatch = trimmedDate.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
        if (mmddyyyyMatch) {
          const [, month, day, year] = mmddyyyyMatch;
          dateStr = `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`;
        }
        
        // Validate the date format (should be YYYY-MM-DD)
        if (!dateStr.match(/^\d{4}-\d{2}-\d{2}$/)) {
          setError("Invalid date format. Please use YYYY-MM-DD or MM/DD/YYYY format.");
          setSaving(false);
          return;
        }
        
        // Validate the date is actually valid
        const dateObj = new Date(dateStr + 'T00:00:00'); // Add time to avoid timezone issues
        if (isNaN(dateObj.getTime())) {
          setError("Invalid date. Please enter a valid date.");
          setSaving(false);
          return;
        }
        
        // Use the validated YYYY-MM-DD format
        dateValue = dateStr;
      }

      const payload: ImpactCreatePayload = {
        title: title.trim() || "(untitled)",
        date: dateValue || null, // Explicitly set to null if empty
        context: null,
        actions: actions.trim() || "(no explicit actions provided)",
        impact: impact.trim() || null,
        metrics: metrics.trim() || null,
        tags: [],
        notes: notes.trim() || null,
      };

      let entry: ImpactEntry;
      if (initialImpact) {
        // Update existing impact
        entry = await updateImpact(initialImpact.id, payload);
      } else {
        // Create new impact
        entry = await createImpact(payload);
        // Dispatch custom event so ImpactWorkspacePage can reload impacts
        window.dispatchEvent(new CustomEvent('impactSaved', { detail: entry }));
      }
      
      onSaved?.(entry);
      onClose();
      reset();
    } catch (e: any) {
      console.error("Error creating impact:", e);
      setError(e?.message ?? "Failed to save impact");
    } finally {
      setSaving(false);
    }
  };

  const handleWorkspace = () => {
    if (onOpenWorkspace) onOpenWorkspace();
    onClose();
  };

  const handleAdd = async () => {
    if (saving) return;

    setSaving(true);
    setError(null);

    try {
      // Create a minimal impact with just the title (or default)
      const payload: ImpactCreatePayload = {
        title: title.trim() || "New Bullet",
        date: null,
        context: null,
        actions: actions.trim() || "",
        impact: impact.trim() || null,
        metrics: metrics.trim() || null,
        tags: [],
        notes: notes.trim() || null,
      };

      const entry = await createImpact(payload);
      
      // Dispatch custom event so ImpactWorkspacePage can reload impacts
      window.dispatchEvent(new CustomEvent('impactSaved', { detail: entry }));
      
      // Call onSaved callback with the new entry
      onSaved?.(entry);
      
      // Open workspace for this new impact
      if (onOpenWorkspace) {
        onOpenWorkspace(entry);
      }
      
      onClose();
      reset();
    } catch (e: any) {
      console.error("Error creating impact:", e);
      setError(e?.message ?? "Failed to create impact");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-xl rounded-lg bg-[var(--bg-primary)] p-6 shadow-xl border border-[var(--border-color)] transition-colors">
        <h2 className="mb-4 text-lg font-semibold text-[var(--text-primary)]">Bullet</h2>
        <div className="space-y-3 text-sm text-[var(--text-primary)]">
          <input
            className="w-full rounded border border-[var(--border-color)] bg-[var(--bg-tertiary)] px-3 py-2 text-sm text-[var(--text-primary)] transition-colors"
            placeholder="Short title (e.g., 'Led Joint Cloud brief to MAJCOMs')"
            value={title}
            onChange={e => setTitle(e.target.value)}
          />
          <div className="w-1/2">
            <label className="mb-1 block text-xs uppercase tracking-wide text-[var(--text-secondary)]">
              Date
            </label>
            <input
              type="date"
              className="w-full rounded border border-[var(--border-color)] bg-[var(--bg-tertiary)] px-3 py-2 text-sm text-[var(--text-primary)] transition-colors"
              value={date}
              onChange={e => {
                const value = e.target.value;
                // HTML5 date input returns YYYY-MM-DD format
                setDate(value);
              }}
              onBlur={e => {
                // If user typed MM/DD/YYYY manually, convert it
                const value = e.target.value;
                if (value && !value.match(/^\d{4}-\d{2}-\d{2}$/)) {
                  const mmddyyyyMatch = value.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
                  if (mmddyyyyMatch) {
                    const [, month, day, year] = mmddyyyyMatch;
                    const converted = `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`;
                    setDate(converted);
                  }
                }
              }}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wide text-[var(--text-secondary)]">
              What did you do? (Actions)
            </label>
            <textarea
              className="h-16 w-full resize-none rounded border border-[var(--border-color)] bg-[var(--bg-tertiary)] px-3 py-2 text-sm text-[var(--text-primary)] transition-colors"
              placeholder="Quickly jot what you actually did, in your own words…"
              value={actions}
              onChange={e => setActions(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wide text-[var(--text-secondary)]">
              Why did it matter? (Impact / result)
            </label>
            <textarea
              className="h-16 w-full resize-none rounded border border-[var(--border-color)] bg-[var(--bg-tertiary)] px-3 py-2 text-sm text-[var(--text-primary)] transition-colors"
              placeholder="Who benefited? What changed? What did you unlock/prevent/save?"
              value={impact}
              onChange={e => setImpact(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wide text-[var(--text-secondary)]">
              Numbers / scope (optional)
            </label>
            <input
              className="w-full rounded border border-[var(--border-color)] bg-[var(--bg-tertiary)] px-3 py-2 text-sm text-[var(--text-primary)] transition-colors"
              placeholder="ex: 8 MAJCOMs / $27M portfolio / 1200 Airmen / 3 yr roadmap"
              value={metrics}
              onChange={e => setMetrics(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wide text-[var(--text-secondary)]">
              Notes (optional)
            </label>
            <textarea
              className="h-16 w-full resize-none rounded border border-[var(--border-color)] bg-[var(--bg-tertiary)] px-3 py-2 text-sm text-[var(--text-primary)] transition-colors"
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
            className="rounded px-3 py-2 text-sm text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
            onClick={onClose}
          >
            Cancel
          </button>
          {!initialImpact && (
            <button
              type="button"
              disabled={saving}
              className={`rounded px-3 py-2 text-sm font-semibold transition-colors ${
                !saving
                  ? "bg-blue-500 text-white hover:bg-blue-400"
                  : "bg-[var(--bg-tertiary)] text-[var(--text-secondary)] cursor-not-allowed"
              }`}
              onClick={handleAdd}
            >
              {saving ? "Adding…" : "Add"}
            </button>
          )}
          <button
            type="button"
            className="rounded px-3 py-2 text-sm text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] border border-[var(--border-color)] transition-colors"
            onClick={handleWorkspace}
          >
            Workspace
          </button>
          <button
            type="button"
            disabled={!canSave || saving}
            className={`rounded px-3 py-2 text-sm font-semibold transition-colors ${
              canSave && !saving
                ? "bg-emerald-500 text-white hover:bg-emerald-400"
                : "bg-[var(--bg-tertiary)] text-[var(--text-secondary)] cursor-not-allowed"
            }`}
            onClick={handleSave}
          >
            {saving ? (initialImpact ? "Updating…" : "Saving…") : (initialImpact ? "Update" : "Save")}
          </button>
        </div>
      </div>
    </div>
  );
};


