/** Admin session state: Steam sign-in plus the `admin` role gate (`GET /admin/me`). */
import { ACCOUNT_SUSPENDED_TYPE } from "@csmarket/api-client";
import { create } from "zustand";

import { apiBase, ApiError, session } from "@/lib/api";

/** `GET /api/v1/admin/me` (`MeOut`), the fields the admin shell reads. */
export interface AdminMe {
  id: string;
  display_name: string | null;
  roles: string[];
}

export type AuthStatus = "loading" | "anonymous" | "forbidden" | "suspended" | "admin";

interface AuthState {
  status: AuthStatus;
  me: AdminMe | null;
  bootstrap: () => Promise<void>;
  completeSteam: (params: Record<string, string>) => Promise<void>;
  signOut: () => void;
}

/** Where the sign-in button goes: the API 302s to Steam and back to our callback. */
export function loginHref(): string {
  return `${apiBase}/api/v1/auth/steam/start?app=admin&locale=ru`;
}

/** The page is Steam's return: the URL still carries the assertion. */
function isSteamReturn(): boolean {
  return new URLSearchParams(window.location.search).has("openid.mode");
}

async function probe(): Promise<Pick<AuthState, "status" | "me">> {
  // A refresh refused as `account-suspended`: no token, but not a plain sign-out.
  if (session.isSuspended()) return { status: "suspended", me: null };
  if (!session.getAccessToken()) return { status: "anonymous", me: null };
  try {
    const me = await session.apiGet<AdminMe>("/api/v1/admin/me");
    return { status: "admin", me };
  } catch (err) {
    if (err instanceof ApiError && err.status === 403) {
      const suspended = err.type === ACCOUNT_SUSPENDED_TYPE;
      return { status: suspended ? "suspended" : "forbidden", me: null };
    }
    return { status: "anonymous", me: null };
  }
}

export const useAuthStore = create<AuthState>((set) => ({
  status: "loading",
  me: null,
  bootstrap: async () => {
    // On the Steam return a refresh against a stale cookie would fail, fire a
    // logout and revoke the session `completeSteam` is creating: leave it alone.
    const steamReturn = isSteamReturn();
    if (!steamReturn && !session.getAccessToken() && session.hasSessionHint()) {
      await session.refreshAccessToken();
    }
    set(await probe());
  },
  completeSteam: async (params) => {
    const tokens = await session.apiPost<{ access_token: string }>(
      "/api/v1/auth/steam",
      { app: "admin", params },
      { anonymous: true },
    );
    session.setAccessToken(tokens.access_token);
    set(await probe());
  },
  signOut: () => {
    session.clearSession();
    set({ status: "anonymous", me: null });
  },
}));

// A refused refresh mid-session means the session is dead: back to the login page,
// or to «заблокирован» when the refusal was a ban.
session.onAuthLost(() => {
  useAuthStore.setState({ status: session.isSuspended() ? "suspended" : "anonymous", me: null });
});
