/**
 * The front end's one API client (NFR-D50), the equivalent of platform/dashboard/client.py plus
 * the error handling in app.py::_api. Base URL from VITE_API_URL, the token in the Authorization
 * header (NFR-D11), and the single place where 401 signs the user out and errors become messages
 * with the request id (FR-D100, NFR-D54). It never touches a database (NFR-D12).
 */
import { getSession, setSession, SESSION_EXPIRED } from "./session";
import type { ErrorBody, Params } from "./types";

export const API_BASE = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

export type ApiErrorKind = "network" | "unauthorized" | "forbidden" | "not_found" | "http";

/** What every screen's error state shows: the message as the user should read it, and the id. */
export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly requestId: string | null;

  constructor(kind: ApiErrorKind, message: string, status: number | null, requestId: string | null) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.requestId = requestId;
  }

  /** "message (request id X)", the Streamlit dashboard's wording. */
  get display(): string {
    return this.requestId ? `${this.message} (request id ${this.requestId})` : this.message;
  }
}

export interface RequestOptions {
  body?: unknown;
  params?: Params;
  /** A 404 is an expected answer (no explanation yet, no R10 result): resolve to null. */
  quietNotFound?: boolean;
  signal?: AbortSignal;
}

function url(path: string, params?: Params): string {
  const query = params && params.length ? `?${new URLSearchParams(params).toString()}` : "";
  return `${API_BASE}${path}${query}`;
}

async function readBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const session = getSession();
  const headers: Record<string, string> = {};
  if (session) headers.Authorization = `Bearer ${session.token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const isLogin = method.toUpperCase() === "POST" && path === "/auth/login";

  let response: Response;
  try {
    response = await fetch(url(path, options.params), {
      method,
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    const reason = error instanceof Error ? error.message : String(error);
    throw new ApiError("network", `RingShield API is unavailable: ${reason}`, null, null);
  }

  const payload = await readBody(response);
  const body = (payload && typeof payload === "object" ? payload : {}) as ErrorBody;
  const requestId = body.request_id ?? response.headers.get("X-Request-ID") ?? null;

  if (response.status === 401) {
    if (isLogin) {
      // one generic message whether the email or the password was wrong (FR-D02)
      throw new ApiError("unauthorized", "Incorrect email or password.", 401, null);
    }
    setSession(null, SESSION_EXPIRED);                           // FR-D03, NFR-D14: no silent refresh
    throw new ApiError("unauthorized", SESSION_EXPIRED, 401, requestId);
  }
  if (response.status === 403) {
    throw new ApiError("forbidden", "Not permitted: your role cannot do this.", 403, body.request_id ?? null);
  }
  if (!response.ok) {
    if (response.status === 404 && options.quietNotFound) return null as T;
    const kind: ApiErrorKind = response.status === 404 ? "not_found" : "http";
    throw new ApiError(kind, body.message ?? "Request failed", response.status, requestId);
  }
  if (response.status === 204) return {} as T;
  return payload as T;
}
