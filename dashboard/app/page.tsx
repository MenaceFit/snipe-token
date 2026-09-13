import { api } from "@/lib/api";
import StatCard from "@/components/StatCard";

function fmt(n: number) {
  return n >= 1_000_000
    ? `$${(n / 1_000_000).toFixed(2)}M`
    : n >= 1_000
    ? `$${(n / 1_000).toFixed(1)}K`
    : `$${n.toFixed(2)}`;
}

export default async function OverviewPage() {
  let overview;
  try {
    overview = await api.overview();
  } catch {
    return (
      <div className="text-center py-20" style={{ color: "var(--muted)" }}>
        API unreachable. Make sure the backend is running.
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Overview</h1>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-10">
        <StatCard label="Tracked Wallets" value={overview.tracked_wallets} />
        <StatCard label="Total Trades" value={overview.total_trades.toLocaleString()} />
        <StatCard label="Open Positions" value={overview.open_positions} />
        <StatCard label="Win Rate" value={`${overview.win_rate.toFixed(1)}%`} positive={overview.win_rate >= 50} />
        <StatCard
          label="Total PnL"
          value={fmt(Math.abs(overview.total_pnl_usd))}
          sub={overview.total_pnl_usd >= 0 ? "profit" : "loss"}
          positive={overview.total_pnl_usd >= 0}
        />
      </div>

      <section>
        <h2 className="text-lg font-semibold mb-4">Top Ranked Wallets</h2>
        <RankingTable />
      </section>
    </div>
  );
}

async function RankingTable() {
  let wallets;
  try {
    wallets = await api.ranking(10);
  } catch {
    return <p style={{ color: "var(--muted)" }}>Could not load ranking.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-xl" style={{ border: "1px solid var(--border)" }}>
      <table className="w-full text-sm">
        <thead>
          <tr style={{ background: "var(--surface)", borderBottom: "1px solid var(--border)" }}>
            {["#", "Label / Address", "Score", "Chains", "Flags"].map((h) => (
              <th key={h} className="px-4 py-3 text-left font-medium" style={{ color: "var(--muted)" }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {wallets.map((w, i) => (
            <tr
              key={w.id}
              style={{ borderBottom: "1px solid var(--border)" }}
              className="hover:bg-white/5 transition-colors"
            >
              <td className="px-4 py-3" style={{ color: "var(--muted)" }}>{i + 1}</td>
              <td className="px-4 py-3">
                <a href={`/wallets/${w.id}`} className="hover:underline">
                  {w.label ?? `${w.address.slice(0, 8)}…${w.address.slice(-6)}`}
                </a>
              </td>
              <td className="px-4 py-3 font-bold tabular-nums" style={{ color: "var(--green)" }}>
                {w.score?.toFixed(0) ?? "—"}
              </td>
              <td className="px-4 py-3" style={{ color: "var(--muted)" }}>{w.chains.join(", ") || "—"}</td>
              <td className="px-4 py-3">
                {w.flags.length > 0 ? (
                  <span className="text-xs px-2 py-0.5 rounded" style={{ background: "var(--red)", color: "#fff" }}>
                    {w.flags.join(", ")}
                  </span>
                ) : (
                  <span style={{ color: "var(--muted)" }}>—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
