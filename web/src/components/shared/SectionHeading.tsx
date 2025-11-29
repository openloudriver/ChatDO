import React from "react";

const SectionHeading: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="mt-7 first:mt-0">
    <h3 className="text-sm font-semibold text-white/85 uppercase tracking-[0.3px] max-sm:text-[13px]">
      {children}
    </h3>
    <div className="w-full h-px bg-white/8 mt-2 mb-5"></div>
  </div>
);

export default SectionHeading;

