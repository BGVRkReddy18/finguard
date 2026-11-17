"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button, ErrorNote, Spinner, cx } from "@/components/ui";
import { useSession } from "@/lib/session";

const DEMO_PASSWORD = "finguard123";

// Which demo accounts the login page offers. Production lists only manager/analyst — the admin
// account has its own secret password and is never advertised.
const SHOWN = (process.env.NEXT_PUBLIC_DEMO_ACCOUNTS ?? "analyst,manager,admin").split(",");
const DEMO = [
  { username: "manager", role: "Risk manager", blurb: "Sees every feature, including the audit log", recommended: true },
  { username: "analyst", role: "Fraud analyst", blurb: "Works the case queue like a bank analyst", recommended: false },
  { username: "admin", role: "Administrator", blurb: "Local development only", recommended: false },
].filter((d) => SHOWN.includes(d.username));

export default function LoginPage() {
  const { user, login } = useSession();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null); // which button is signing in

  useEffect(() => {
    if (!user) return;
    // Return to the page that sent us here; only same-site paths (blocks open redirects like //evil.com)
    const next = new URLSearchParams(window.location.search).get("next") ?? "/";
    router.replace(next.startsWith("/") && !next.startsWith("//") ? next : "/");
  }, [user, router]);

  const signIn = async (name: string, pass: string, key: string) => {
    setBusy(key);
    setError(null);
    try {
      await login(name, pass);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
      setBusy(null);
    }
  };

  return (
    <main className="grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-2.5">
          <div aria-hidden className="grid h-9 w-9 place-items-center rounded-lg bg-accent text-sm font-bold text-accent-ink">FG</div>
          <div>
            <h1 className="text-lg font-semibold text-ink">FinGuard</h1>
            <p className="text-xs text-ink-3">Real-time fraud detection · AI risk analyst</p>
          </div>
        </div>

        {DEMO.length > 0 && (
          <section aria-labelledby="demo-title" className="rounded-xl border border-line bg-surface p-5">
            <h2 id="demo-title" className="text-base font-semibold text-ink">Explore the live demo</h2>
            <p className="mt-1 text-sm text-ink-2">
              No sign-up needed — pick a role and you&apos;re in. A live stream of card transactions starts as
              soon as you open the dashboard.
            </p>
            <div className="mt-4 space-y-2">
              {DEMO.map((d) => (
                <button key={d.username} type="button" disabled={busy !== null}
                  onClick={() => signIn(d.username, DEMO_PASSWORD, d.username)}
                  className={cx("flex w-full items-center justify-between gap-3 rounded-lg border px-4 py-3 text-left transition disabled:opacity-60",
                    d.recommended ? "border-accent bg-accent text-accent-ink hover:opacity-90" : "border-line bg-surface hover:bg-surface-2")}>
                  <span>
                    <span className="block text-sm font-semibold">
                      Enter as {d.role}{d.recommended && <span className="ml-2 rounded bg-white/20 px-1.5 py-0.5 text-[11px] font-medium">Recommended</span>}
                    </span>
                    <span className={cx("block text-xs", d.recommended ? "opacity-90" : "text-ink-3")}>{d.blurb}</span>
                  </span>
                  {busy === d.username ? <Spinner /> : <span aria-hidden className="text-lg">→</span>}
                </button>
              ))}
            </div>
            <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-lg bg-surface-2 px-3 py-2 text-xs">
              <dt className="text-ink-3">Usernames</dt>
              <dd className="font-mono text-ink">{DEMO.map((d) => d.username).join("  ·  ")}</dd>
              <dt className="text-ink-3">Password</dt>
              <dd className="font-mono text-ink">{DEMO_PASSWORD}</dd>
            </dl>
          </section>
        )}

        {error && <div className="mt-3"><ErrorNote message={error} /></div>}

        <details className="mt-4 rounded-xl border border-line bg-surface" open={DEMO.length === 0}>
          <summary className="cursor-pointer select-none px-5 py-3 text-sm text-ink-2">Sign in with a username and password</summary>
          <form onSubmit={(e) => { e.preventDefault(); signIn(username, password, "form"); }} className="space-y-3 px-5 pb-5">
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
            <Button type="submit" variant="primary" loading={busy === "form"} disabled={busy !== null} className="w-full">Sign in</Button>
          </form>
        </details>

        <p className="mt-4 text-center text-xs text-ink-3">
          Simulated data · <a className="underline hover:text-ink" href="https://github.com/BGVRkReddy18/finguard" target="_blank" rel="noreferrer">Source code on GitHub</a>
        </p>
      </div>
    </main>
  );
}
