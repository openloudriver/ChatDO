import React from "react";

const SectionHeading: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="mt-7 first:mt-0">
    <h3 className="text-sm font-semibold text-[var(--text-primary)] uppercase tracking-[0.3px] max-sm:text-[13px]">
      {children}
    </h3>
    <div className="w-full h-px border-[var(--border-color)] mt-2 mb-5" style={{ borderTopWidth: '1px' }}></div>
  </div>
);

export default SectionHeading;

