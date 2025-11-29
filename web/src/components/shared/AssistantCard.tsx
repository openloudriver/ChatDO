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
    <div className={`mt-8 w-full ${className}`}>
      <div 
        className="assistant-card rounded-[14px] bg-[#0D0D0D] border border-white/8 shadow-lg px-8 py-7 space-y-4 max-sm:px-5"
        style={{ boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.4)' }}
      >
        {children}
        {footer ? (
          <div className="pt-[18px]">
            <div className="w-full h-px bg-white/6 mb-[14px]"></div>
            <div className="text-xs text-white/35 text-right">
              {footer}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

