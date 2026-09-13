import { api } from "@/lib/api";
import StatCard from "@/components/StatCard";

function fmt(n: number | null | undefined, prefix = "$") {
  if (n == null) return "—";
  const abs = Math.abs(n);
  const sign = n >= 0 ? "+" : "-";
  if (abs >= 1_000_000) return `${sign}${prefix}${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${sign}${prefix}${(abs / 1_000).toFixed(1)}K`;
  return `${sign}${prefix}${abs.toFixed(2)}`;
}

export default async function WalletDetailPage({ params }: { params: { id: string } }) {
  const id = parseInt(params.id, 10);

  let wallet;
  let positions;
  try {
    [wallet, positions] = await Promise.all([api.wallet(id), api.positions(id)]);
  } catch {
    return <p style={{ color: "var(--muted)" }}>Wallet not found or API unreachable.</p>;
  }

  const m = wallet.metrics;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">{wallet.label ?? "Wallet"}</h1>
        <p className="text-sm font-mono mt-1" style={{ color: "var(--muted)" }}>{wallet.address}</p>
        <div className="flex gap-2 mt-2">
          {wallet.chains.map((c) => (
            <span
              key={c}
              className="text-xs px-2 py-0.5 rounded"
              style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
            >
              {c}
            </span>
          ))}
          {wallet.flags.map((f) => (
            <span
              key={f}
              className="text-xs px-2 py-0.5 rounded"
              style={{ background: "rgba(248,81,73,0.2)", color: "var(--red)" }}
            >
              ⚠ {f}
            </span>
          ))}
        </div>
      </div>

      {m && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <StatCard label="Score" value={wallet.score?.toFixed(0) ?? "—"} positive />
          <StatCard label="Win Rate" value={`${m.win_rate?.toFixed(1) ?? 0}%`} positive={m.win_rate >= 50} />
          <StatCard label="Avg ROI" value={`${m.average_roi?.toFixed(1) ?? 0}%`} positive={m.average_roi > 0} />
          <StatCard label="Total PnL" value={fmt(m.total_pnl_usd)} positive={m.total_pnl_usd > 0} />
          <StatCard label="Total Trades" value={m.total_trades ?? 0} />
          <StatCard label="Profit Factor" value={m.profit_factor?.toFixed(2) ?? "—"} />
          <StatCard label="Max Drawdown" value={`${m.max_drawdown?.toFixed(1) ?? 0}%`} positive={false} />
          <StatCard label="Best Trade" value={`+${m.best_trade_roi?.toFixed(0) ?? 0}%`} positive />
        </div>
      )}

      <h2 className="text-lg font-semibold mb-4">Open Positions ({positions.length})</h2>
      {positions.length === 0 ? (
        <p style={{ color: "var(--muted)" }}>No open positions.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl" style={{ border: "1px solid var(--border)" }}>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: "var(--surface)", borderBottom: "1px solid var(--border)" }}>
                {["Token", "Status", "Avg Entry", "Current", "Invested", "Unrealized PnL", "ROI"].map((h) => (
                  <th key={h} className="px-4 py-3 text-left font-medium" style={{ color: "var(--muted)" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.id} style={{ borderBottom: "1px solid var(--border)" }} className="hover:bg-white/5">
                  <td className="px-4 py-3">#{p.token_id}</td>
                  <td className="px-4 py-3">
                    <span
                      className="text-xs px-2 py-0.5 rounded"
                      style={{ background: "rgba(63,185,80,0.15)", color: "var(--green)" }}
                    >
                      {p.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 tabular-nums">${p.average_entry_usd?.toFixed(6) ?? "—"}</td>
                  <td className="px-4 py-3 tabular-nums">${p.current_price_usd?.toFixed(6) ?? "—"}</td>
                  <td className="px-4 py-3 tabular-nums">${p.total_invested_usd?.toFixed(2) ?? "—"}</td>
                  <td
                    className="px-4 py-3 tabular-nums font-medium"
                    style={{ color: (p.unrealized_pnl_usd ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}
                  >
                    {fmt(p.unrealized_pnl_usd)}
                  </td>
                  <td
                    className="px-4 py-3 tabular-nums"
                    style={{ color: (p.roi_percent ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}
                  >
                    {p.roi_percent != null ? `${p.roi_percent > 0 ? "+" : ""}${p.roi_percent.toFixed(1)}%` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
