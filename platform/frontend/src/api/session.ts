/**
 * The session lives in memory only (FR-D01, NFR-D10): a module variable plus subscribers, never
 * localStorage, sessionStorage, cookies or the URL. A reload signs the user out, by design.
 */
import type { SessionResponse } from "./types";

type Listener = () => void;

let current: SessionResponse | null = null;
let notice: string | null = null;
const listeners = new Set<Listener>();

export function getSession(): SessionResponse | null {
  return current;
}

export function setSession(session: SessionResponse | null, message: string | null = null): void {
  current = session;
  notice = message;
  listeners.forEach((listener) => listener());
}

/** A one-shot message for the login screen ("Session expired..."); reading it clears it. */
export function takeNotice(): string | null {
  const value = notice;
  notice = null;
  return value;
}

export function peekNotice(): string | null {
  return notice;
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export const SESSION_EXPIRED = "Session expired. Please sign in again.";
