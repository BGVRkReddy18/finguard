"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button, ErrorNote } from "@/components/ui";
import { useSession } from "@/lib/session";

const DEMO = [
  { username: "analyst", role: "Fraud analyst" },
  { username: "manager", role: "Risk manager" },
  { username: "admin", role: "Administrator" },
];

export default function LoginPage() {
  const { user, login } = useSession();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!user) return;
    // Return to the page that sent us here; only same-site paths (blocks open redirects like //evil.com)
    const next = new URLSearchParams(window.location.search).get("next") ?? "/";
    router.replace(next.startsWith("/") && !next.startsWith("//") ? next : "/");
  }, [user, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <div aria-hidden className="grid h-9 w-9 place-items-center rounded-lg bg-accent text-sm font-bold text-accent-ink">FG</div>
          <div>
            <h1 className="text-lg font-semibold text-ink">FinGuard</h1>
            <p className="text-xs text-ink-3">Real-time fraud detection · AI risk analyst</p>
          </div>
        </div>

        <form onSubmit={submit} className="space-y-3 rounded-xl border border-line bg-surface p-5">
          <label className="block">
            <span className="text-xs font-medium text-ink-2">Username</span>
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required
              className="mt-1 w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent" />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-ink-2">Password</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required
              className="mt-1 w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent" />
          </label>
          {error && <ErrorNote message={error} />}
          <Button type="submit" variant="primary" loading={busy} className="w-full">Sign in</Button>
        </form>

        <div className="mt-4 rounded-xl border border-dashed border-line p-4">
          <div className="text-xs font-medium text-ink-2">Demo accounts <span className="font-normal text-ink-3">(password: finguard123)</span></div>
          <div className="mt-2 flex flex-wrap gap-2">
            {DEMO.map((d) => (
              <button key={d.username} type="button"
                onClick={() => { setUsername(d.username); setPassword("finguard123"); }}
                className="rounded-lg border border-line bg-surface px-2.5 py-1 text-xs text-ink-2 hover:bg-surface-2">
                {d.username} <span className="text-ink-3">· {d.role}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
