"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

const links = [
  { href: "/", label: "Overview" },
  { href: "/wallets", label: "Wallets" },
  { href: "/trades", label: "Top Trades" },
  { href: "/positions", label: "Positions" },
];

export default function Nav() {
  const path = usePathname();
  return (
    <nav
      style={{ background: "var(--surface)", borderBottom: "1px solid var(--border)" }}
      className="px-6 py-3 flex items-center gap-8"
    >
      <span className="font-bold text-lg tracking-tight" style={{ color: "var(--green)" }}>
        ⚡ Snipe Token
      </span>
      <div className="flex gap-6">
        {links.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className={clsx("text-sm transition-colors", {
              "font-semibold": path === l.href,
            })}
            style={{ color: path === l.href ? "var(--text)" : "var(--muted)" }}
          >
            {l.label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
