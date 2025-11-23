import React, { useEffect, useState } from "react";

interface ProviderEntry {
  id: string;
  label: string;
  usd: number;
}

interface MonthlySpendResponse {
  ok: boolean;
  month: string;
  totalUsd: number;
  providers: ProviderEntry[];
}

export const AiSpendIndicator: React.FC = () => {
  const [data, setData] = useState<MonthlySpendResponse | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const amountRef = React.useRef<HTMLDivElement>(null);

  useEffect(() => {
    async function fetchSpend() {
      try {
        const res = await fetch("http://localhost:8081/v1/ai/spend/monthly");
        if (!res.ok) {
          // Silently fail - don't log to console
          return;
        }
        const json = await res.json();
        if (json.ok) {
          setData(json);
        }
        // Silently ignore errors
      } catch (e) {
        // Silently fail - don't log to console
        // Set empty data on error so menu can still show
        setData({
          ok: true,
          month: new Date().toISOString().slice(0, 7),
          totalUsd: 0,
          providers: []
        });
      }
    }

    fetchSpend();
    const id = setInterval(fetchSpend, 30000); // refresh every 30s
    return () => clearInterval(id);
  }, []);

  function handleMouseEnter() {
    setMenuOpen(true);
  }

  function handleMouseLeave() {
    setMenuOpen(false);
  }

  const total = data?.totalUsd ?? 0;

  // Sort providers: GPT-5 first, Whisper-1 second, then others alphabetically
  const sortedProviders = data?.providers ? [...data.providers].sort((a, b) => {
    // Define priority order
    const priority: Record<string, number> = {
      'openai-gpt5': 1,
      'openai-whisper-1': 2,
    };
    
    const aPriority = priority[a.id] ?? 999;
    const bPriority = priority[b.id] ?? 999;
    
    if (aPriority !== bPriority) {
      return aPriority - bPriority;
    }
    
    // If same priority, sort alphabetically by label
    return a.label.localeCompare(b.label);
  }) : [];

  return (
    <div 
      className="relative w-full"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <div
        ref={amountRef}
        onClick={(e) => e.stopPropagation()}
        className="text-[#8e8ea0] hover:text-white cursor-default select-none text-sm px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis"
      >
        {`$${total.toFixed(2)}`}
      </div>
      {menuOpen && amountRef.current && (
        <div
          className="spend-menu absolute bg-[#202123] border border-[#565869] rounded-lg p-2 z-[9999] min-w-[200px] max-w-[250px] shadow-lg"
          style={{
            bottom: '100%', // Position above
            right: 0, // Align to right edge
            marginBottom: '8px', // Small gap
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {data ? (
            <>
              {sortedProviders.map((p) => (
                <div
                  key={p.id}
                  className="flex justify-between px-2 py-1 text-sm text-[#ececf1]"
                >
                  <span>{p.label}</span>
                  <span>${p.usd.toFixed(2)}</span>
                </div>
              ))}
              {sortedProviders.length > 0 && (
                <>
                  <hr className="border-[#565869] my-2" />
                  <div className="flex justify-between px-2 py-1 text-sm font-semibold text-[#ececf1]">
                    <span>Total</span>
                    <span>${data.totalUsd.toFixed(2)}</span>
                  </div>
                </>
              )}
              {sortedProviders.length === 0 && (
                <div className="text-sm text-[#8e8ea0] px-2 py-1">
                  No spend recorded yet
                </div>
              )}
            </>
          ) : (
            <div className="text-sm text-[#8e8ea0] px-2 py-1">
              Loading...
            </div>
          )}
        </div>
      )}
    </div>
  );
};

