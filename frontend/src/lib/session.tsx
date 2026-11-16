"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

import { AI_URL, api, getAccessToken, login as apiLogin, tokenStore } from "./api";
import type { LiveEvent, User } from "./types";

// ---------------------------------------------------------------- session (who is logged in)

interface Session {
  user: User | null;
  loading: boolean;
  isManager: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  // null = not known yet. Tokens live in localStorage, which only exists after hydration; deciding
  // "logged out" before then would bounce deep links (e.g. /cases/42 on refresh) to the login page.
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const update = () => setSignedIn(tokenStore.has());
    update();
    return tokenStore.subscribe(update);
  }, []);

  useEffect(() => {
    if (signedIn === null) return;
    if (!signedIn) {
      setUser(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    api<User>("core", "/api/auth/me/")
      .then(setUser)
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false));
  }, [signedIn]);

  const login = useCallback(async (username: string, password: string) => {
    await apiLogin(username, password);
  }, []);

  const value: Session = {
    user,
    loading,
    isManager: user?.role === "MANAGER" || user?.role === "ADMIN",
    login,
    logout: tokenStore.clear,
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside SessionProvider");
  return ctx;
}

// ---------------------------------------------------------------- live stream (WebSocket)

type LiveStatus = "connecting" | "live" | "offline";
type TxnEvent = Extract<LiveEvent, { type: "txn" }>;

interface Live {
  status: LiveStatus;
  recent: TxnEvent[]; // newest first
  tps: number; // transactions/second over the last 10 s
  subscribe: (fn: (e: LiveEvent) => void) => () => void;
}

const LiveContext = createContext<Live | null>(null);
const FEED_SIZE = 40;

export function LiveProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const [recent, setRecent] = useState<TxnEvent[]>([]);
  const [tps, setTps] = useState(0);
  const listeners = useRef(new Set<(e: LiveEvent) => void>());
  const arrivals = useRef<number[]>([]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const connect = async () => {
      setStatus("connecting");
      const token = await getAccessToken(); // fresh token on every (re)connect
      if (!token || closed) return;
      socket = new WebSocket(`${AI_URL.replace(/^http/, "ws")}/ws/live?token=${encodeURIComponent(token)}`);
      socket.onopen = () => {
        retry = 0;
        setStatus("live");
      };
      socket.onmessage = (msg) => {
        const event = JSON.parse(msg.data) as LiveEvent;
        if (event.type === "txn") {
          arrivals.current.push(Date.now());
          setRecent((prev) => [event, ...prev].slice(0, FEED_SIZE));
        }
        listeners.current.forEach((fn) => fn(event));
      };
      socket.onclose = () => {
        if (closed) return;
        setStatus("offline");
        const delay = Math.min(1000 * 2 ** retry++, 15_000); // exponential backoff, capped
        timer = setTimeout(connect, delay);
      };
    };
    connect();

    const rate = setInterval(() => {
      const cutoff = Date.now() - 10_000;
      arrivals.current = arrivals.current.filter((t) => t > cutoff);
      setTps(arrivals.current.length / 10);
    }, 1000);

    return () => {
      closed = true;
      clearTimeout(timer);
      clearInterval(rate);
      socket?.close();
    };
  }, []);

  const subscribe = useCallback((fn: (e: LiveEvent) => void) => {
    listeners.current.add(fn);
    return () => {
      listeners.current.delete(fn);
    };
  }, []);

  return <LiveContext.Provider value={{ status, recent, tps, subscribe }}>{children}</LiveContext.Provider>;
}

export function useLive() {
  const ctx = useContext(LiveContext);
  if (!ctx) throw new Error("useLive must be used inside LiveProvider");
  return ctx;
}

/** Run ``fn`` for matching live events (debounced), e.g. to refetch a list when a case opens. */
export function useLiveRefresh(types: LiveEvent["type"][], fn: () => void, debounceMs = 1500) {
  const { subscribe } = useLive();
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const key = types.join(",");
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const wanted = new Set(key.split(","));
    const unsubscribe = subscribe((e) => {
      if (!wanted.has(e.type)) return;
      clearTimeout(timer);
      timer = setTimeout(() => fnRef.current(), debounceMs);
    });
    return () => {
      clearTimeout(timer);
      unsubscribe();
    };
  }, [subscribe, key, debounceMs]);
}
