import React, { useEffect } from "react";
import { useAppLayout } from "../hooks/useAppLayout";
import Sidebar from "../components/Sidebar";

type AppLayoutProps = {
  children: React.ReactNode;
};

// PanelLeft icon (sidebar open - shows collapse/hide icon - left chevron)
const PanelLeftIcon = () => (
  <svg
    className="h-4 w-4"
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={2}
      d="M15 19l-7-7 7-7"
    />
  </svg>
);

// PanelLeftOpen icon (sidebar closed - shows expand/show icon - right chevron)
const PanelLeftOpenIcon = () => (
  <svg
    className="h-4 w-4"
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={2}
      d="M9 5l7 7-7 7"
    />
  </svg>
);

export function AppLayout({ children }: AppLayoutProps) {
  const { isSidebarOpen, toggleSidebar } = useAppLayout();

  // Keyboard shortcut: Cmd/Ctrl + \
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const isModifier = e.metaKey || e.ctrlKey;
      if (isModifier && e.key === "\\") {
        e.preventDefault();
        toggleSidebar();
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggleSidebar]);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#343541] text-[#ececf1]">
      {/* Sidebar column */}
      <div
        className={
          isSidebarOpen
            ? "w-64 shrink-0 border-r border-[#565869] bg-[#202123] transition-all duration-150"
            : "w-0 shrink-0 overflow-hidden border-r border-[#565869] transition-all duration-150"
        }
      >
        {/* Only render content when open to avoid weird focus/tab issues */}
        {isSidebarOpen && <Sidebar />}
      </div>

      {/* Main content column */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Global header */}
        <header className="flex items-center gap-3 border-b border-[#565869] px-4 py-2 bg-[#343541]">
          {/* Sidebar toggle button – always visible */}
          <button
            type="button"
            onClick={toggleSidebar}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[#565869] bg-[#40414f] text-[#8e8ea0] hover:bg-[#565869] hover:text-white transition-colors"
            aria-label={isSidebarOpen ? "Hide sidebar" : "Show sidebar"}
          >
            {isSidebarOpen ? <PanelLeftIcon /> : <PanelLeftOpenIcon />}
          </button>

          {/* Optional: current view / breadcrumbs placeholder */}
          <div className="text-xs font-medium uppercase tracking-wide text-[#8e8ea0]">
            ChatDO
          </div>

          {/* Spacer flex to push anything else (e.g. model indicator) to the right */}
          <div className="ml-auto flex items-center gap-2">
            {/* Put any global status / model chip here if desired */}
          </div>
        </header>

        {/* Main view area */}
        <main className="flex-1 overflow-hidden">
          {children}
        </main>
      </div>
    </div>
  );
}
