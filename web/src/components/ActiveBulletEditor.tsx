import React from 'react';
import type { ImpactEntry } from '../types/impact';

export type BulletMode = '1206_2LINE' | 'OPB_350' | 'OPB_450' | 'FREE';

export const BULLET_MODES: {
  id: BulletMode;
  label: string;
  description: string;
  maxChars?: number; // undefined means no hard limit
}[] = [
  {
    id: '1206_2LINE',
    label: 'Award (230)',
    description: 'Target ~230 chars',
    maxChars: 230,
  },
  {
    id: 'OPB_350',
    label: 'OPB 350',
    description: 'Executing/Leading/Managing/Improving',
    maxChars: 350,
  },
  {
    id: 'OPB_450',
    label: 'OPB 250',
    description: 'Duty Description',
    maxChars: 250,
  },
  {
    id: 'FREE',
    label: 'Freeform',
    description: 'No fixed limit',
  },
];

interface ActiveBulletEditorProps {
  selectedImpact: ImpactEntry | null;
  bulletMode: BulletMode;
  bulletText: string;
  onChangeText: (text: string) => void;
}

export function ActiveBulletEditor({
  selectedImpact,
  bulletMode,
  bulletText,
  onChangeText,
}: ActiveBulletEditorProps) {
  const modeMeta = BULLET_MODES.find((m) => m.id === bulletMode)!;
  const max = modeMeta.maxChars;
  const length = bulletText.length;
  const remaining = max != null ? max - length : undefined;
  const over = max != null && length > max;

  return (
    <div className="border-b border-slate-700 pb-3 mb-3 flex flex-col gap-2 flex-shrink-0 bg-[#343541] px-4 pt-3">
      {/* Top row: impact title */}
      <div className="flex flex-col flex-1 min-w-0">
        <span className="text-[10px] text-slate-400 uppercase tracking-wide mb-1">
          Active bullet
        </span>
        <span className="text-sm text-slate-200 truncate">
          {selectedImpact
            ? selectedImpact.title || "(untitled impact)"
            : 'No impact selected — select one on the left to ground the bullet.'}
        </span>
      </div>

      {/* Textarea */}
      <textarea
        className={`w-full rounded-md bg-slate-800 px-3 py-2 text-sm leading-snug resize-vertical min-h-[72px] border ${
          over ? 'border-red-500' : 'border-slate-700'
        } text-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500`}
        value={bulletText}
        onChange={(e) => {
          const val = e.target.value;
          // Enforce hard limit if maxChars is defined
          if (max != null && val.length > max) {
            onChangeText(val.slice(0, max));
          } else {
            onChangeText(val);
          }
        }}
        placeholder={
          modeMeta.maxChars
            ? `Draft your bullet here (max ${modeMeta.maxChars} chars)...`
            : 'Draft your bullet here...'
        }
      />

      {/* Counters row */}
      <div className="flex items-center justify-between text-[11px] text-slate-400">
        <span className={over ? 'text-red-400' : ''}>
          {length}
          {max != null ? ` / ${max} chars` : ' chars'}
          {remaining != null && (
            <> · {remaining >= 0 ? `${remaining} remaining` : `${-remaining} over`}</>
          )}
        </span>
      </div>
    </div>
  );
}

