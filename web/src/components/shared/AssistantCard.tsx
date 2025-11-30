import React from "react";

type AssistantCardProps = {
  children: React.ReactNode;
  className?: string;
  footer?: React.ReactNode; // optional footer slot for model badge, etc.
};

/**
 * Shared card component for all assistant "rich content" cards.
 * Uses ChatGPT's design language as the source of truth:
 * - Pure charcoal black background (#0D0D0D)
 * - 14px border radius
 * - Subtle border (rgba(255,255,255,0.08))
 * - Padding: 28px top/bottom, 32px left/right
 * - Shadow for separation
 */
export function AssistantCard({ children, className = "", footer }: AssistantCardProps) {
  return (
    <div className={`mt-4 w-full ${className}`}>
      <div 
        className="assistant-card rounded-2xl bg-[var(--card-bg)] border border-[var(--card-border)] px-5 py-5 space-y-4 max-sm:px-5 transition-colors"
        style={{ 
          boxShadow: '0 2px 4px rgba(0, 0, 0, 0.08)'
        }}
      >
        {children}
        {footer ? (
          <div className="pt-[18px]">
            <div className="w-full h-px border-[var(--border-color)]/30 mb-[14px]"></div>
            <div className="text-xs text-[var(--text-secondary)] text-right">
              {footer}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

