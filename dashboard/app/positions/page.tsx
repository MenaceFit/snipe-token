import { api } from "@/lib/api";

function fmt(n: number | null | undefined) {
  if (n == null) return "—";
  const sign = n >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(n).toFixed(2)}`;
}

export default async function PositionsPage() {
  let positions;
  try {
    positions = await api.positions();
  } catch {
    return <p style={{ color: "var(--muted)" }}>API unreachable.</p>;
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Open Positions ({positions.length})</h1>
      <div className="overflow-x-auto rounded-xl" style={{ border: "1px solid var(--border)" }}>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ background: "var(--surface)", borderBottom: "1px solid var(--border)" }}>
              {["Wallet", "Token", "Invested", "Current Value", "Unrealized PnL", "ROI", "% Sold"].map((h) => (
                <th key={h} className="px-4 py-3 text-left font-medium" style={{ color: "var(--muted)" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              const pnlColor = (p.unrealized_pnl_usd ?? 0) >= 0 ? "var(--green)" : "var(--red)";
              const roiColor = (p.roi_percent ?? 0) >= 0 ? "var(--green)" : "var(--red)";
              return (
                <tr key={p.id} style={{ borderBottom: "1px solid var(--border)" }} className="hover:bg-white/5">
                  <td className="px-4 py-3">
                    <a href={`/wallets/${p.wallet_id}`} className="hover:underline" style={{ color: "var(--muted)" }}>
                      #{p.wallet_id}
                    </a>
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: "var(--muted)" }}>#{p.token_id}</td>
                  <td className="px-4 py-3 tabular-nums">${p.total_invested_usd?.toFixed(2) ?? "—"}</td>
                  <td className="px-4 py-3 tabular-nums">${p.current_value_usd?.toFixed(2) ?? "—"}</td>
                  <td className="px-4 py-3 tabular-nums font-medium" style={{ color: pnlColor }}>
                    {fmt(p.unrealized_pnl_usd)}
                  </td>
                  <td className="px-4 py-3 tabular-nums" style={{ color: roiColor }}>
                    {p.roi_percent != null
                      ? `${p.roi_percent > 0 ? "+" : ""}${p.roi_percent.toFixed(1)}%`
                      : "—"}
                  </td>
                  <td className="px-4 py-3 tabular-nums" style={{ color: "var(--muted)" }}>
                    {p.percentage_sold != null ? `${p.percentage_sold.toFixed(0)}%` : "0%"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
