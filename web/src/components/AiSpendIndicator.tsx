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
  const [menuPos, setMenuPos] = useState<{ x: number; y: number } | null>(null);

  useEffect(() => {
    async function fetchSpend() {
      try {
        const res = await fetch("http://localhost:8081/v1/ai/spend/monthly");
        const json = await res.json();
        if (json.ok) {
          setData(json);
        }
      } catch (e) {
        // fail silently; just don't update
      }
    }

    fetchSpend();
    const id = setInterval(fetchSpend, 30000); // refresh every 30s
    return () => clearInterval(id);
  }, []);

  function handleContextMenu(e: React.MouseEvent) {
    e.preventDefault();
    setMenuPos({ x: e.clientX, y: e.clientY });
    setMenuOpen(true);
  }

  function closeMenu() {
    setMenuOpen(false);
  }

  const total = data?.totalUsd ?? 0;

  return (
    <>
      <div
        onContextMenu={handleContextMenu}
        className="text-[#8e8ea0] hover:text-white cursor-default select-none text-sm px-2 py-1"
      >
        {`$${total.toFixed(2)}`}
      </div>
      {menuOpen && menuPos && data && (
        <div
          className="fixed bg-[#202123] border border-[#565869] rounded-lg p-2 z-[9999] min-w-[200px] shadow-lg"
          style={{
            top: menuPos.y,
            left: menuPos.x,
          }}
          onMouseLeave={closeMenu}
        >
          {data.providers.map((p) => (
            <div
              key={p.id}
              className="flex justify-between px-2 py-1 text-sm text-[#ececf1]"
            >
              <span>{p.label}</span>
              <span>${p.usd.toFixed(2)}</span>
            </div>
          ))}
          {data.providers.length > 0 && (
            <>
              <hr className="border-[#565869] my-2" />
              <div className="flex justify-between px-2 py-1 text-sm font-semibold text-[#ececf1]">
                <span>Total</span>
                <span>${data.totalUsd.toFixed(2)}</span>
              </div>
            </>
          )}
          {data.providers.length === 0 && (
            <div className="text-sm text-[#8e8ea0] px-2 py-1">
              No spend recorded yet
            </div>
          )}
        </div>
      )}
    </>
  );
};

