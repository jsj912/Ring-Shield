/** The verdict form's rules (FR-D50-55), as test_dashboard_partial_verdict.py checks them in Streamlit. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setSession } from "@/api/session";
import type { RingDetail, Role } from "@/api/types";
import { NarrativePanel } from "./NarrativePanel";
import { VerdictForm } from "./VerdictForm";

const ring = {
  ring_id: "ring-1", tenant_id: 1001, topology_type: "CYCLE", topology_prob: 0.5, n_members: 2, n_edges: 1,
  total_amount: 10, total_currency: "US Dollar", start_time: "2022-09-10T00:00:00Z", end_time: "2022-09-10T01:00:00Z",
  window_text: "over 1 h", confidence: 0.9, cross_bank: false, counterparty_banks: [], status: "open",
  member_accounts: [11, 12], member_edges: [7], seed_edges: [7], expanded_edges: [], conservation_closure: 0.5,
  source_accounts: [], sink_accounts: [], mule_accounts: [], model_id: "m", aggregator_id: "a",
} satisfies RingDetail;

function renderForm(role: Role, ringOverride: Partial<RingDetail> = {}) {
  setSession({ user_id: 1, tenant_id: 1001, tenant_name: "Bank", role, token: "t", expires_at: "2099-01-01T00:00:00Z" });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <VerdictForm tenantId={1001} ringId={`ring-${role}-${Math.random()}`} ring={{ ...ring, ...ringOverride }} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();                                         // unmount before the session goes away
  vi.unstubAllGlobals();
  setSession(null);
});

describe("VerdictForm", () => {
  it("is disabled for an administrator, with the required text", () => {
    renderForm("admin");
    expect(screen.getByText("Administrators cannot record verdicts.")).toBeInTheDocument();
    for (const name of ["Confirm ring", "Reject ring", "Partially correct"]) expect(screen.getByRole("button", { name })).toBeDisabled();
  });

  it("blocks a partial verdict that keeps no account, removes nothing, or has no note", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderForm("analyst");
    await user.click(screen.getByRole("button", { name: /Partially correct/ }));
    const submit = screen.getByRole("button", { name: /Submit partial verdict/ });

    await user.click(submit);
    expect(screen.getByText("Remove at least one account or transaction; otherwise confirm the ring.")).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Keep account 11" }));
    await user.click(screen.getByRole("checkbox", { name: "Keep account 12" }));
    await user.click(submit);
    expect(screen.getByText("Keep at least one account for a partial correction.")).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Keep account 12" }));
    await user.click(submit);
    expect(screen.getByText("A note is required for a partial verdict.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends one request for a double click and keeps the note after a failure", async () => {
    let release: (value: Response) => void = () => {};
    const fetchMock = vi.fn().mockImplementation(() => new Promise<Response>((resolve) => { release = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderForm("analyst");
    await user.type(screen.getByLabelText(/Note \(optional/), "kept note");
    const confirm = screen.getByRole("button", { name: /Confirm ring/ });
    await user.dblClick(confirm);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    release(new Response(JSON.stringify({ message: "Server error", request_id: "p-1" }), { status: 500 }));
    expect(await screen.findByText("Server error (request id p-1)")).toBeInTheDocument();
    expect(screen.getByText("The verdict was not recorded. Your entries are kept: submit again to retry.")).toBeInTheDocument();
    expect(screen.getByLabelText(/Note \(optional/)).toHaveValue("kept note");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ verdict: "confirm", note: "kept note" });
  });

  it("says when the ring is no longer open", () => {
    renderForm("analyst", { status: "confirmed" });
    expect(screen.getByText("This ring is no longer open for verdicts.")).toBeInTheDocument();
  });
});

describe("NarrativePanel", () => {
  it("shows the narrative and notes as text, never as HTML (NFR-D13)", () => {
    render(
      <NarrativePanel
        ring={ring}
        explanation={{ narrative: "<script>alert(1)</script> exactly", explainer_version: "v", latency_ms: 1, revision: 1 } as never}
        explanationState={{ isPending: false, error: null, retry: () => {} }}
        history={{ items: [], next_before_id: null }}
      />,
    );
    expect(screen.getByTestId("narrative").textContent).toBe("<script>alert(1)</script> exactly");
    expect(document.querySelector("script")).toBeNull();
  });
});
