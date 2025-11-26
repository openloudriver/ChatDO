import React, { useState, useEffect } from 'react';
import { deleteMemorySource } from '../utils/api';

type ConfirmDeleteMemoryModalProps = {
  open: boolean;
  sourceId: string | null;
  displayName: string | null;
  onClose: () => void;
  onDeleted: () => void; // caller will refresh the list
};

const ConfirmDeleteMemoryModal: React.FC<ConfirmDeleteMemoryModalProps> = ({
  open,
  sourceId,
  displayName,
  onClose,
  onDeleted,
}) => {
  const [input, setInput] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open) {
      setInput('');
      setError(null);
      setLoading(false);
    }
  }, [open]);

  if (!open || !sourceId) return null;

  const nameToType = displayName || sourceId;
  const canDelete = input === nameToType && !loading;

  const handleDelete = async () => {
    if (!sourceId) return;
    if (!canDelete) return;

    setLoading(true);
    setError(null);

    try {
      await deleteMemorySource(sourceId);
      onDeleted();
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Failed to delete memory source.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-[#343541] border border-[#565869] rounded-lg w-full max-w-md p-6 flex flex-col">
        <h2 className="text-xl font-semibold text-white mb-2">
          Delete memory source
        </h2>
        <p className="text-sm text-[#8e8ea0] mb-3">
          This will remove{' '}
          <span className="font-mono font-semibold text-red-400">
            {nameToType}
          </span>{' '}
          from the Memory Dashboard and disconnect it from all projects.
        </p>
        <p className="text-sm text-[#8e8ea0] mb-4">
          Type the name&nbsp;
          <span className="font-mono text-white">{nameToType}</span>
          &nbsp;to confirm.
        </p>
        <input
          autoFocus
          className="w-full p-2 rounded bg-[#40414f] text-white border border-[#565869] focus:outline-none focus:ring-1 focus:ring-blue-500 mb-3"
          placeholder={nameToType}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && canDelete) {
              handleDelete();
            }
          }}
          disabled={loading}
        />
        {error && (
          <div className="mb-3 text-sm text-red-400">
            {error}
          </div>
        )}
        <div className="flex justify-end gap-2 mt-auto">
          <button
            type="button"
            className="px-4 py-2 rounded text-white border border-[#565869] hover:bg-[#565869] disabled:opacity-50"
            onClick={onClose}
            disabled={loading}
          >
            Cancel
          </button>
          <button
            type="button"
            className={`px-4 py-2 rounded text-white ${
              canDelete
                ? 'bg-red-600 hover:bg-red-700'
                : 'bg-red-900/60 text-red-300/60 cursor-not-allowed'
            } disabled:opacity-50 disabled:cursor-not-allowed`}
            onClick={handleDelete}
            disabled={!canDelete}
          >
            {loading ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConfirmDeleteMemoryModal;

