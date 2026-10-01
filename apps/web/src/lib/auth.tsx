"use client";

import { SessionApiError } from "@csmarket/api-client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { API_BASE, session } from "./api";

/** The signed-in user, as `GET /api/v1/me` returns it (`MeOut`). */
export interface Me {
  id: string;
  steam_id: string;
  display_name: string | null;
  avatar_url: string | null;
  email: string | null;
  email_verified: boolean;
  locale: "ru" | "uz" | "en";
  trade_link: string | null;
  trade_link_verdict: "ok" | "warn" | "bad" | null;
  trade_link_reason: "invalid" | "private" | "trade_ban" | "hold" | "unavailable" | null;
  trade_link_checked_at: string | null;
  roles: string[];
  created_at: string;
}

export type AuthStatus = "loading" | "anonymous" | "signed_in" | "suspended";

export interface AuthValue {
  user: Me | null;
  status: AuthStatus;
  signInHref: (locale: string) => string;
  completeSteamSignIn: (params: Record<string, string>) => Promise<void>;
  signOut: () => Promise<void>;
  refreshMe: () => Promise<void>;
}

interface AuthProviderProps {
  children: ReactNode;
}

const AuthContext = createContext<AuthValue | null>(null);
const ME = ["me"] as const;

const fetchMe = (): Promise<Me> => session.apiGet<Me>("/api/v1/me");

function signInHref(locale: string): string {
  return `${API_BASE}/api/v1/auth/steam/start?app=web&locale=${encodeURIComponent(locale)}`;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const qc = useQueryClient();
  // The token lives in memory, invisible to the server: stay "loading" until the
  // boot-time refresh settles so server and first client render agree.
  const [booted, setBooted] = useState(false);
  const [hasToken, setHasToken] = useState(false);
  // Set by the Steam callback before this provider's boot effect runs (child
  // effects run first): a boot refresh against a stale cookie would otherwise
  // fail, fire a logout and revoke the session the sign-in is creating.
  const signingIn = useRef(false);

  useEffect(() => {
    // An object, not a `let`: the flag is flipped by the cleanup, after the await.
    const effect = { cancelled: false };
    void (async () => {
      if (!signingIn.current && !session.getAccessToken() && session.hasSessionHint()) {
        await session.refreshAccessToken();
      }
      if (!effect.cancelled) {
        setHasToken(Boolean(session.getAccessToken()));
        setBooted(true);
      }
    })();
    const off = session.onAuthLost(() => {
      setHasToken(false);
      qc.removeQueries({ queryKey: ME });
    });
    return () => {
      effect.cancelled = true;
      off();
    };
  }, [qc]);

  const me = useQuery({
    queryKey: ME,
    queryFn: fetchMe,
    enabled: booted && hasToken,
    retry: false,
    staleTime: 60_000,
  });

  const suspended = me.error instanceof SessionApiError && me.error.status === 403;
  const status: AuthStatus =
    // Pending never carries an error in react-query v5.
    !booted || (hasToken && me.isPending)
      ? "loading"
      : suspended
        ? "suspended"
        : me.data
          ? "signed_in"
          : "anonymous";

  const completeSteamSignIn = useCallback(
    async (params: Record<string, string>) => {
      signingIn.current = true;
      try {
        const tokens = await session.apiPost<{ access_token: string }>(
          "/api/v1/auth/steam",
          { app: "web", params },
          { anonymous: true },
        );
        session.setAccessToken(tokens.access_token);
        // Seed the cache before enabling the query, so it doesn't fetch /me twice.
        qc.setQueryData(ME, await fetchMe());
        setHasToken(true);
      } finally {
        signingIn.current = false;
      }
    },
    [qc],
  );

  const signOut = useCallback((): Promise<void> => {
    session.clearSession();
    setHasToken(false);
    qc.removeQueries({ queryKey: ME });
    return Promise.resolve();
  }, [qc]);

  const refreshMe = useCallback(async () => {
    await qc.invalidateQueries({ queryKey: ME });
  }, [qc]);

  const value = useMemo<AuthValue>(
    () => ({
      user: me.data ?? null,
      status,
      signInHref,
      completeSteamSignIn,
      signOut,
      refreshMe,
    }),
    [me.data, status, completeSteamSignIn, signOut, refreshMe],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
