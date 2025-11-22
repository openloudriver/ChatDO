import React from "react";

const SectionHeading: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <h3 className="text-base font-semibold text-[#8e8ea0] mb-2 uppercase tracking-wide">
    {children}
  </h3>
);

export default SectionHeading;

