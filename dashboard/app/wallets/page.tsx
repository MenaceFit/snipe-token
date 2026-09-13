import { api } from "@/lib/api";
import Link from "next/link";

export default async function WalletsPage() {
  let wallets;
  try {
    wallets = await api.wallets();
  } catch {
    return <p style={{ color: "var(--muted)" }}>API unreachable.</p>;
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Tracked Wallets</h1>
      <div className="overflow-x-auto rounded-xl" style={{ border: "1px solid var(--border)" }}>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ background: "var(--surface)", borderBottom: "1px solid var(--border)" }}>
              {["ID", "Label / Address", "Score", "Chains", "Status", "Flags"].map((h) => (
                <th key={h} className="px-4 py-3 text-left font-medium" style={{ color: "var(--muted)" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {wallets.map((w) => (
              <tr key={w.id} style={{ borderBottom: "1px solid var(--border)" }} className="hover:bg-white/5">
                <td className="px-4 py-3" style={{ color: "var(--muted)" }}>{w.id}</td>
                <td className="px-4 py-3">
                  <Link href={`/wallets/${w.id}`} className="hover:underline">
                    <span className="font-medium">{w.label ?? ""}</span>
                    <span className="ml-1 text-xs" style={{ color: "var(--muted)" }}>
                      {w.address.slice(0, 8)}…{w.address.slice(-6)}
                    </span>
                  </Link>
                </td>
                <td className="px-4 py-3 font-bold tabular-nums" style={{ color: "var(--green)" }}>
                  {w.score?.toFixed(0) ?? "—"}
                </td>
                <td className="px-4 py-3" style={{ color: "var(--muted)" }}>{w.chains.join(", ") || "—"}</td>
                <td className="px-4 py-3">
                  <span
                    className="text-xs px-2 py-0.5 rounded"
                    style={{
                      background: w.enabled ? "rgba(63,185,80,0.15)" : "rgba(248,81,73,0.15)",
                      color: w.enabled ? "var(--green)" : "var(--red)",
                    }}
                  >
                    {w.enabled ? "active" : "disabled"}
                  </span>
                </td>
                <td className="px-4 py-3">
                  {w.flags.map((f) => (
                    <span
                      key={f}
                      className="text-xs px-1.5 py-0.5 rounded mr-1"
                      style={{ background: "rgba(248,81,73,0.2)", color: "var(--red)" }}
                    >
                      {f}
                    </span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
