/**
 * API client for the three backends + JWT token management.
 *
 * Tokens: short-lived access JWT (30 min) + refresh JWT, kept in localStorage so a reload keeps you
 * signed in. Trade-off noted in the README: an httpOnly-cookie BFF would hide tokens from JS (XSS),
 * at the cost of proxying every call — and the WebSocket — through Next.js.
 */
// Absolute URLs (local dev: separate ports) or same-origin paths (behind a reverse proxy: "", "/ai",
// "/ml") — the latter makes one build work on any domain.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const AI_URL = process.env.NEXT_PUBLIC_AI_URL ?? "http://localhost:8002";
export const ML_URL = process.env.NEXT_PUBLIC_ML_URL ?? "http://localhost:8001";

/** WebSocket base for the AI service, from an absolute URL or a same-origin path. */
export function aiWebSocketBase(): string {
  if (/^https?:\/\//.test(AI_URL)) return AI_URL.replace(/^http/, "ws");
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}${AI_URL}`;
}

const BASES = { core: API_URL, ai: AI_URL, ml: ML_URL } as const;
type Base = keyof typeof BASES;

const STORAGE_KEY = "finguard.tokens";
interface Tokens {
  access: string;
  refresh: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// ---------------- token store (framework-free, so non-React code can use it) ----------------
let tokens: Tokens | null = null;
const listeners = new Set<() => void>();

function load(): Tokens | null {
  if (tokens || typeof window === "undefined") return tokens;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    tokens = raw ? (JSON.parse(raw) as Tokens) : null;
  } catch {
    tokens = null;
  }
  return tokens;
}

function save(next: Tokens | null) {
  tokens = next;
  try {
    if (next) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable (private mode) — tokens still work for this tab */
  }
  listeners.forEach((fn) => fn());
}

export const tokenStore = {
  has: () => load() !== null,
  subscribe(fn: () => void): () => void {
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  },
  clear: () => save(null),
};

function expiresAt(jwt: string): number {
  try {
    const payload = JSON.parse(atob(jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return (payload.exp ?? 0) * 1000;
  } catch {
    return 0;
  }
}

let refreshing: Promise<string | null> | null = null;

async function refreshAccess(): Promise<string | null> {
  const current = load();
  if (!current) return null;
  // De-duplicate: many parallel requests share one refresh call
  refreshing ??= (async () => {
    try {
      const res = await fetch(`${API_URL}/api/auth/token/refresh/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh: current.refresh }),
      });
      if (!res.ok) throw new Error("refresh failed");
      const data = (await res.json()) as { access: string; refresh?: string };
      save({ access: data.access, refresh: data.refresh ?? current.refresh });
      return data.access;
    } catch {
      save(null); // refresh token expired -> back to login
      return null;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

/** A valid access token, refreshed if it expires within 30 s. */
export async function getAccessToken(): Promise<string | null> {
  const current = load();
  if (!current) return null;
  if (expiresAt(current.access) - Date.now() > 30_000) return current.access;
  return refreshAccess();
}

export async function login(username: string, password: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/auth/token/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new ApiError(res.status, res.status === 401 ? "Wrong username or password" : "Login failed");
  save((await res.json()) as Tokens);
}

function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if (typeof b.detail === "string") return b.detail;
    const first = Object.values(b)[0];
    if (Array.isArray(first) && typeof first[0] === "string") return first[0];
  }
  return `Request failed (${status})`;
}

export async function api<T>(base: Base, path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  const send = async (token: string | null) =>
    fetch(`${BASES[base]}${path}`, {
      ...rest,
      headers: {
        ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...rest.headers,
      },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });

  let res = await send(await getAccessToken());
  if (res.status === 401 && load()) res = await send(await refreshAccess()); // token revoked/expired early
  if (res.status === 401) save(null);

  const body = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, errorMessage(body, res.status));
  return body as T;
}
