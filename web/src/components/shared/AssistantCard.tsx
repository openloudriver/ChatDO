import React from "react";

type AssistantCardProps = {
  children: React.ReactNode;
  className?: string;
  footer?: React.ReactNode; // optional footer slot for model badge, etc.
};

/**
 * Shared card component for all assistant "rich content" cards.
 * Uses the Summarizer card style as the source of truth:
 * - Black background (#1a1a1a)
 * - Rounded corners (rounded-xl)
 * - Border (border-[#565869])
 * - Consistent padding (p-6)
 * - Proper spacing (space-y-4)
 */
export function AssistantCard({ children, className = "", footer }: AssistantCardProps) {
  return (
    <div className={`mt-3 w-full ${className}`}>
      <div className="rounded-xl bg-[#1a1a1a] border border-[#565869] p-6 space-y-4">
        {children}
      </div>
      {footer ? (
        <div className="mt-2 flex justify-end text-xs text-[#8e8ea0]">
          {footer}
        </div>
      ) : null}
    </div>
  );
}

