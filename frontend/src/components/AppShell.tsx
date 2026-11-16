"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { useLive, useSession } from "@/lib/session";
import { cx } from "./ui";

const NAV = [
  { href: "/", label: "Overview", icon: "M3 12l9-8 9 8M5 10v10h14V10" },
  { href: "/cases", label: "Cases", icon: "M4 6h16M4 12h16M4 18h10" },
  { href: "/ask", label: "Ask AI", icon: "M12 3a9 9 0 019 9 9 9 0 01-13.5 7.8L3 21l1.2-4.5A9 9 0 0112 3z" },
  { href: "/model", label: "Model", icon: "M4 19V9m6 10V5m6 14v-7m4 7H2" },
  { href: "/audit", label: "Audit log", icon: "M9 12l2 2 4-4M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7l8-4z", managerOnly: true },
];

function Icon({ d }: { d: string }) {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}

function LiveIndicator() {
  const { status, tps } = useLive();
  const label = { live: `Live · ${tps.toFixed(1)} tx/s`, connecting: "Connecting…", offline: "Reconnecting…" }[status];
  return (
    <span className="inline-flex items-center gap-2 text-xs text-ink-2" role="status">
      <span aria-hidden className={cx("h-2 w-2 rounded-full", status === "live" ? "pulse-dot bg-good" : "bg-warning")} />
      {label}
    </span>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark" | null>(null);
  useEffect(() => {
    const stored = document.documentElement.dataset.theme as "light" | "dark" | undefined;
    setTheme(stored ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  }, []);
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("finguard.theme", next); } catch { /* ignore */ }
    setTheme(next);
  };
  return (
    <button onClick={toggle} className="rounded-lg px-2 py-1 text-xs text-ink-2 hover:bg-surface-2" aria-label="Toggle colour theme">
      {theme === "dark" ? "Light mode" : "Dark mode"}
    </button>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, isManager, logout } = useSession();
  const items = NAV.filter((n) => !n.managerOnly || isManager);
  const active = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  return (
    <div className="min-h-screen md:grid md:grid-cols-[220px_1fr]">
      <aside className="border-b border-line bg-surface md:sticky md:top-0 md:h-screen md:border-b-0 md:border-r">
        <div className="flex items-center gap-2 px-4 py-4">
          <div aria-hidden className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-xs font-bold text-accent-ink">FG</div>
          <div>
            <div className="text-sm font-semibold text-ink">FinGuard</div>
            <div className="text-[11px] text-ink-3">Fraud operations</div>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:pb-0">
          {items.map((n) => (
            <Link key={n.href} href={n.href}
              className={cx("flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2 text-sm",
                active(n.href) ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink")}>
              <Icon d={n.icon} />
              {n.label}
            </Link>
          ))}
        </nav>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-line bg-bg/90 px-4 py-3 backdrop-blur md:px-6">
          <LiveIndicator />
          <div className="flex items-center gap-2">
            <ThemeToggle />
            {user && (
              <div className="flex items-center gap-2 border-l border-line pl-3">
                <div className="text-right leading-tight">
                  <div className="text-sm font-medium text-ink">{user.username}</div>
                  <div className="text-[11px] text-ink-3">{user.role.toLowerCase()}</div>
                </div>
                <button onClick={logout} className="rounded-lg px-2 py-1 text-xs text-ink-2 hover:bg-surface-2">Sign out</button>
              </div>
            )}
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6 md:px-6">{children}</main>
      </div>
    </div>
  );
}
