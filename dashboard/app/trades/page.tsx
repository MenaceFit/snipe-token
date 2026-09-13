import { api } from "@/lib/api";

function pct(n: number | null | undefined) {
  if (n == null) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;
}

export default async function TopTradesPage() {
  let trades;
  try {
    trades = await api.topTrades(50);
  } catch {
    return <p style={{ color: "var(--muted)" }}>API unreachable.</p>;
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Top Trades (≥50% ROI)</h1>
      <div className="overflow-x-auto rounded-xl" style={{ border: "1px solid var(--border)" }}>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ background: "var(--surface)", borderBottom: "1px solid var(--border)" }}>
              {["Wallet", "Token", "ROI", "PnL", "Value", "Time"].map((h) => (
                <th key={h} className="px-4 py-3 text-left font-medium" style={{ color: "var(--muted)" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => (
              <tr key={t.id} style={{ borderBottom: "1px solid var(--border)" }} className="hover:bg-white/5">
                <td className="px-4 py-3">
                  <a href={`/wallets/${t.wallet_id}`} className="hover:underline text-xs" style={{ color: "var(--muted)" }}>
                    #{t.wallet_id}
                  </a>
                </td>
                <td className="px-4 py-3 text-xs" style={{ color: "var(--muted)" }}>#{t.token_id}</td>
                <td className="px-4 py-3 font-bold tabular-nums" style={{ color: "var(--green)" }}>
                  {pct(t.roi_percent)}
                </td>
                <td className="px-4 py-3 tabular-nums" style={{ color: "var(--green)" }}>
                  ${t.realized_pnl_usd?.toFixed(2) ?? "—"}
                </td>
                <td className="px-4 py-3 tabular-nums">${t.value_usd?.toFixed(2) ?? "—"}</td>
                <td className="px-4 py-3 text-xs" style={{ color: "var(--muted)" }}>
                  {t.timestamp ? new Date(t.timestamp).toLocaleString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
