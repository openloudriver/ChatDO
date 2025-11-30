import React from 'react';

type ConfirmDialogProps = {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
};

const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  open,
  title,
  message,
  confirmLabel = 'OK',
  cancelLabel = 'Cancel',
  onConfirm,
  onCancel,
}) => {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onCancel}>
      <div 
        className="bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg w-full max-w-md p-6 flex flex-col shadow-lg transition-colors"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-[var(--text-primary)] mb-3">
          {title}
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-6">
          {message}
        </p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            className="px-4 py-2 rounded text-[var(--text-primary)] border border-[var(--border-color)] hover:bg-[var(--border-color)] transition-colors"
            onClick={onCancel}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            className="px-4 py-2 rounded text-white bg-blue-600 hover:bg-blue-700 transition-colors"
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConfirmDialog;

