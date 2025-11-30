import React, { useEffect, useState } from "react";
import { useAppLayout } from "../hooks/useAppLayout";
import { useTheme } from "../contexts/ThemeContext";
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
  const { theme, toggleTheme } = useTheme();
  const [isBrowserFullscreen, setIsBrowserFullscreen] = useState(false);

  // Browser fullscreen toggle functionality
  const toggleBrowserFullscreen = () => {
    if (typeof document === "undefined") return;

    const elem = document.documentElement;

    if (!document.fullscreenElement) {
      if (elem.requestFullscreen) {
        elem.requestFullscreen().catch(() => {
          // Handle error silently
        });
      }
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen().catch(() => {
          // Handle error silently
        });
      }
    }
  };

  useEffect(() => {
    if (typeof document === "undefined") return;

    const handleFullscreenChange = () => {
      setIsBrowserFullscreen(Boolean(document.fullscreenElement));
    };

    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
    };
  }, []);

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

  // Keyboard shortcut: F9 for fullscreen toggle
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Only trigger if not typing in an input, textarea, or contenteditable element
      const target = e.target as HTMLElement;
      const isInputElement = 
        target.tagName === 'INPUT' || 
        target.tagName === 'TEXTAREA' || 
        target.isContentEditable;
      
      if (e.key === 'F9' && !isInputElement) {
        e.preventDefault();
        toggleBrowserFullscreen();
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggleBrowserFullscreen]);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[var(--bg-primary)] text-[var(--text-primary)] transition-colors">
      {/* Sidebar column */}
      <div
        className={
          isSidebarOpen
            ? "w-64 shrink-0 border-r border-[var(--border-color)] bg-[var(--bg-secondary)] transition-all duration-150"
            : "w-0 shrink-0 overflow-hidden border-r border-[var(--border-color)] transition-all duration-150"
        }
      >
        {/* Only render content when open to avoid weird focus/tab issues */}
        {isSidebarOpen && <Sidebar />}
      </div>

      {/* Main content column */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Global header */}
        <header className="flex items-center gap-3 border-b border-[var(--border-color)] px-4 py-2 bg-[var(--bg-primary)] transition-colors">
          {/* Sidebar toggle button – always visible */}
          <button
            type="button"
            onClick={toggleSidebar}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--border-color)] hover:text-[var(--text-primary)] transition-colors"
            aria-label={isSidebarOpen ? "Hide sidebar" : "Show sidebar"}
          >
            {isSidebarOpen ? <PanelLeftIcon /> : <PanelLeftOpenIcon />}
          </button>

          {/* Optional: current view / breadcrumbs placeholder */}
          <div className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
            ChatDO
          </div>

          {/* Spacer flex to push anything else (e.g. model indicator) to the right */}
          <div className="ml-auto flex items-center gap-2">
            {/* Theme toggle button */}
            <button
              type="button"
              onClick={toggleTheme}
              className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--border-color)] hover:text-[var(--text-primary)] transition-colors"
              aria-label={theme === 'dark' ? "Switch to light mode" : "Switch to dark mode"}
              title={theme === 'dark' ? "Switch to light mode" : "Switch to dark mode"}
            >
              {theme === 'dark' ? (
                // Sun icon (light mode)
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                </svg>
              ) : (
                // Moon icon (dark mode)
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                </svg>
              )}
            </button>
            {/* Fullscreen toggle button */}
            <button
              type="button"
              onClick={toggleBrowserFullscreen}
              className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--border-color)] hover:text-[var(--text-primary)] transition-colors"
              aria-label={isBrowserFullscreen ? "Exit full screen" : "Enter full screen"}
              title={isBrowserFullscreen ? "Exit full screen (F9)" : "Enter full screen (F9)"}
            >
              {isBrowserFullscreen ? (
                // Minimize icon (exit fullscreen)
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 9V4.5M9 9H4.5M9 9L3.75 3.75M9 15v4.5M9 15H4.5M9 15l-5.25 5.25M15 9h4.5M15 9V4.5M15 9l5.25-5.25M15 15h4.5M15 15v4.5m0-4.5l5.25 5.25" />
                </svg>
              ) : (
                // Maximize icon (enter fullscreen)
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
                </svg>
              )}
            </button>
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
