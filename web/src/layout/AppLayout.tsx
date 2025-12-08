import React, { useEffect, useState } from "react";
import { useAppLayout } from "../hooks/useAppLayout";
import { useTheme } from "../contexts/ThemeContext";
import { useChatStore } from "../store/chat";
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
  const { theme, toggleTheme, accentColor, setAccentColor } = useTheme();
  const { isRagTrayOpen } = useChatStore();
  const [isBrowserFullscreen, setIsBrowserFullscreen] = useState(false);
  const [isAccentColorOpen, setIsAccentColorOpen] = useState(false);
  const accentColorButtonRef = React.useRef<HTMLButtonElement>(null);
  const dropdownRef = React.useRef<HTMLDivElement>(null);
  const [dropdownPosition, setDropdownPosition] = useState<{ top: number; right: number } | null>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        isAccentColorOpen &&
        accentColorButtonRef.current &&
        dropdownRef.current &&
        !accentColorButtonRef.current.contains(event.target as Node) &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setIsAccentColorOpen(false);
        setDropdownPosition(null);
      }
    };

    if (isAccentColorOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => {
        document.removeEventListener('mousedown', handleClickOutside);
      };
    }
  }, [isAccentColorOpen]);

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

  // Keyboard shortcut: F8 for hard reload (works even when typing)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // F8 = Hard Reload
      if (e.key === "F8") {
        e.preventDefault();
        console.log("[Hotkey] F8 hard reload triggered");
        // Hard reload equivalent: bypass cache and force full refresh
        // Use location.href with cache-busting parameter to force hard reload
        const url = new URL(window.location.href);
        url.searchParams.set('_reload', Date.now().toString());
        window.location.href = url.toString();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

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
            ? "w-64 shrink-0 border-r bg-[var(--bg-secondary)] transition-all duration-150"
            : "w-0 shrink-0 overflow-hidden border-r transition-all duration-150"
        }
        style={{ borderRightColor: 'var(--user-bubble-bg)', borderRightWidth: '1px', borderRightStyle: 'solid' }}
      >
        {/* Only render content when open to avoid weird focus/tab issues */}
        {isSidebarOpen && <Sidebar />}
      </div>

      {/* Main content column */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Global header */}
        <header 
          className="flex items-center gap-3 border-b px-4 py-2 transition-colors relative z-50"
          style={{ 
            backgroundColor: 'var(--bg-secondary)',
            borderBottomColor: 'var(--user-bubble-bg)',
            borderBottomWidth: '1px',
            borderBottomStyle: 'solid'
          }}
        >
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
          <div 
            className="ml-auto flex items-center gap-2 transition-transform duration-300"
            style={{ 
              transform: isRagTrayOpen ? 'translateX(-320px)' : 'translateX(0)'
            }}
          >
            {/* Accent color dropdown */}
            <div className="relative">
              <button
                ref={accentColorButtonRef}
                type="button"
                onClick={() => {
                  if (accentColorButtonRef.current) {
                    const rect = accentColorButtonRef.current.getBoundingClientRect();
                    setDropdownPosition({
                      top: rect.bottom + 8,
                      right: window.innerWidth - rect.right
                    });
                  }
                  setIsAccentColorOpen(!isAccentColorOpen);
                }}
                className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--border-color)] hover:text-[var(--text-primary)] transition-colors"
                aria-label="Accent color"
                title="Accent color"
              >
                <div 
                  className="h-3 w-3 rounded-full" 
                  style={{ backgroundColor: `var(--user-bubble-bg)` }}
                />
              </button>
              
              {isAccentColorOpen && dropdownPosition && (
                <>
                  {/* Backdrop to close dropdown */}
                  <div 
                    className="fixed inset-0 z-[9998]" 
                    onClick={() => {
                      setIsAccentColorOpen(false);
                      setDropdownPosition(null);
                    }}
                  />
                  {/* Dropdown menu - using fixed positioning to ensure it's always on top */}
                  <div 
                    ref={dropdownRef}
                    className="fixed z-[9999] w-48 rounded-lg border border-[var(--border-color)] bg-[var(--bg-primary)] shadow-lg transition-colors" 
                    style={{ 
                      top: `${dropdownPosition.top}px`, 
                      right: `${dropdownPosition.right}px` 
                    }}
                  >
                    <div className="p-2">
                      <div className="px-2 py-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
                        Accent color
                      </div>
                      {(['default', 'orange', 'yellow', 'green', 'blue', 'pink', 'purple'] as const).map((color) => {
                        const colors: Record<typeof color, { name: string; value: string }> = {
                          default: { name: 'Default', value: '#8C8C8C' }, // Graphite gray (ChatGPT's default)
                          orange: { name: 'Orange', value: '#F7821B' },
                          yellow: { name: 'Yellow', value: '#FFC600' },
                          green: { name: 'Green', value: '#62BA46' },
                          blue: { name: 'Blue', value: '#007AFF' },
                          pink: { name: 'Pink', value: '#F74F9E' },
                          purple: { name: 'Purple', value: '#A550A7' },
                        };
                        const isSelected = accentColor === color;
                        return (
                          <button
                            key={color}
                            type="button"
                            onClick={() => {
                              setAccentColor(color);
                              setIsAccentColorOpen(false);
                              setDropdownPosition(null);
                            }}
                            className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-sm text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
                          >
                            <div 
                              className="h-3 w-3 rounded-full flex-shrink-0" 
                              style={{ backgroundColor: colors[color].value }}
                            />
                            <span className="flex-1 text-left">{colors[color].name}</span>
                            {isSelected && (
                              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                              </svg>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </>
              )}
            </div>
            
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
