interface Props {
  label: string;
  value: string | number;
  sub?: string;
  positive?: boolean;
}

export default function StatCard({ label, value, sub, positive }: Props) {
  return (
    <div
      className="rounded-xl p-5 flex flex-col gap-1"
      style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
    >
      <span className="text-xs uppercase tracking-widest" style={{ color: "var(--muted)" }}>
        {label}
      </span>
      <span
        className="text-3xl font-bold tabular-nums"
        style={{ color: positive === false ? "var(--red)" : positive ? "var(--green)" : "var(--text)" }}
      >
        {value}
      </span>
      {sub && <span className="text-xs" style={{ color: "var(--muted)" }}>{sub}</span>}
    </div>
  );
}
