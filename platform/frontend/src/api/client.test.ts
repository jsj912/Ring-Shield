/** The one API client: header, 401 sign-out, error messages with request ids (FR-D100, NFR-D54). */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, request } from "./client";
import { getSession, peekNotice, setSession, SESSION_EXPIRED } from "./session";
import type { SessionResponse } from "./types";

const session: SessionResponse = {
  user_id: 1, tenant_id: 1001, tenant_name: "Fixture Bank A", role: "analyst", token: "tok-123", expires_at: "2099-01-01T00:00:00Z",
};

function reply(status: number, body: unknown, headers: Record<string, string> = {}) {
  return vi.fn().mockImplementation(async () =>
    new Response(body === undefined ? null : JSON.stringify(body), { status, headers }));
}

beforeEach(() => setSession(session));
afterEach(() => {
  vi.unstubAllGlobals();
  setSession(null);
});

describe("request", () => {
  it("sends the token in the Authorization header and repeated query keys in order", async () => {
    const fetchMock = reply(200, { ok: true });
    vi.stubGlobal("fetch", fetchMock);
    await request("GET", "/tenants/1001/rings", { params: [["status", "open"], ["status", "partial"], ["limit", "50"]] });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/tenants\/1001\/rings\?status=open&status=partial&limit=50$/);
    expect(init.headers.Authorization).toBe("Bearer tok-123");
  });

  it("signs out with 'Session expired' on a 401", async () => {
    vi.stubGlobal("fetch", reply(401, { message: "Authentication required", request_id: "r1" }));
    await expect(request("GET", "/tenants/1001/rings")).rejects.toMatchObject({ kind: "unauthorized" });
    expect(getSession()).toBeNull();
    expect(peekNotice()).toBe(SESSION_EXPIRED);
  });

  it("gives one generic message for a failed login and keeps no session", async () => {
    setSession(null);
    vi.stubGlobal("fetch", reply(401, { message: "Incorrect email or password" }));
    await expect(request("POST", "/auth/login", { body: {} })).rejects.toThrow("Incorrect email or password.");
    expect(peekNotice()).toBeNull();
  });

  it("shows the API message with the request id from the body, or the header", async () => {
    vi.stubGlobal("fetch", reply(503, { message: "Service temporarily unavailable", request_id: "body-req-7" }));
    const fromBody = await request("GET", "/x").catch((error: ApiError) => error);
    expect((fromBody as ApiError).display).toBe("Service temporarily unavailable (request id body-req-7)");

    vi.stubGlobal("fetch", reply(500, "not json", { "X-Request-ID": "header-req-9" }));
    const fromHeader = await request("GET", "/x").catch((error: ApiError) => error);
    expect((fromHeader as ApiError).display).toBe("Request failed (request id header-req-9)");
  });

  it("says the role cannot do this on a 403", async () => {
    vi.stubGlobal("fetch", reply(403, { message: "Not permitted", request_id: "f-1" }));
    const error = (await request("GET", "/admin/tenants").catch((e: ApiError) => e)) as ApiError;
    expect(error.kind).toBe("forbidden");
    expect(error.display).toBe("Not permitted: your role cannot do this. (request id f-1)");
    expect(getSession()).not.toBeNull();
  });

  it("turns a network failure into 'API is unavailable'", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await expect(request("GET", "/x")).rejects.toThrow("RingShield API is unavailable: offline");
  });

  it("resolves an expected 404 to null", async () => {
    vi.stubGlobal("fetch", reply(404, { message: "Not found" }));
    await expect(request("GET", "/x", { quietNotFound: true })).resolves.toBeNull();
    await expect(request("GET", "/x")).rejects.toMatchObject({ kind: "not_found" });
  });
});
