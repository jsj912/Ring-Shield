import { useEffect, useSyncExternalStore } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getSession, setSession, SESSION_EXPIRED, subscribe } from "@/api/session";
import type { SessionResponse } from "@/api/types";

export function useSession(): SessionResponse | null {
  return useSyncExternalStore(subscribe, getSession, getSession);
}

/** Sign out clears the token and every cached response (FR-D04). */
export function useSignOut(): () => void {
  const queryClient = useQueryClient();
  return () => {
    setSession(null);
    queryClient.clear();
  };
}

/** NFR-D14: the session ends when the token expires, with no silent refresh. */
export function useExpiryTimer(session: SessionResponse | null): void {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!session) return;
    const expires = new Date(session.expires_at).getTime();
    if (Number.isNaN(expires)) return;
    const end = () => {
      setSession(null, SESSION_EXPIRED);
      queryClient.clear();
    };
    const wait = expires - Date.now();                           // clock time, not API data
    if (wait <= 0) {
      end();
      return;
    }
    // setTimeout caps at about 24.8 days; a longer token is re-checked when the timer fires.
    const timer = window.setTimeout(end, Math.min(wait, 2_000_000_000));
    return () => window.clearTimeout(timer);
  }, [session, queryClient]);
}

/** Clears cached data whenever the session ends, including a 401 from the client. */
export function useClearOnSignOut(session: SessionResponse | null): void {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!session) queryClient.clear();
  }, [session, queryClient]);
}
