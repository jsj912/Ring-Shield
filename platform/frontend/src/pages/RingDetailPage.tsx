/**
 * Ring detail (app.py::_ring_detail): narrative | graph | evidence side by side on wide screens,
 * stacking below 1600 px, then the ring's verdicts. Each panel loads and fails on its own.
 */
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Globe2, Lock } from "lucide-react";
import { ApiError } from "@/api/client";
import { useSession } from "@/app/session";
import { useActiveTenant } from "@/app/tenant";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader, ReadOnlyBanner, StatusBadge } from "@/components/shared";
import { fmtWeight } from "@/lib/formatters";
import { EvidencePanel } from "./ring/EvidencePanel";
import { GraphPanel } from "./ring/GraphPanel";
import { NarrativePanel } from "./ring/NarrativePanel";
import { RegenerationStatus } from "./ring/RegenerationStatus";
import { RingVerdicts } from "./ring/RingVerdicts";
import { VerdictForm } from "./ring/VerdictForm";
import { useEvidence, useExplanation, useRing, useRingVerdicts } from "./ring/queries";

function BackToQueue() {
  // The queue keeps its filters and page in the workspace (FR-D14).
  return (
    <Button asChild variant="ghost" size="sm" className="-ml-2 w-fit">
      <Link to="/rings"><ArrowLeft /> Back to queue</Link>
    </Button>
  );
}

function RingDetail({ tenantId, ringId }: { tenantId: number; ringId: string }) {
  const session = useSession()!;
  const ring = useRing(tenantId, ringId);
  const explanation = useExplanation(tenantId, ringId);
  const evidence = useEvidence(tenantId, ringId);
  const history = useRingVerdicts(tenantId, ringId);

  if (ring.isPending) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-80" />
        <div className="grid gap-4 min-[1600px]:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_minmax(0,1.3fr)]">
          <Skeleton className="h-[520px]" /><Skeleton className="h-[520px]" /><Skeleton className="h-[520px]" />
        </div>
      </div>
    );
  }
  // A ring the tenant does not hold (another bank's, or none) answers 404 or 403: say "Not permitted"
  // either way, so the screen does not tell whether another bank has a ring with this id.
  if (ring.error instanceof ApiError && (ring.error.kind === "not_found" || ring.error.kind === "forbidden")) {
    return <EmptyState title="Not permitted" icon={<Lock />}>This ring is not in your bank's queue.</EmptyState>;
  }
  if (ring.isError) return <ErrorState error={ring.error} onRetry={() => ring.refetch()} />;
  const detail = ring.data;
  const explanationState = { isPending: explanation.isPending, error: explanation.error, retry: () => explanation.refetch() };

  return (
    <>
      <PageHeader
        title={<>
          <span className="font-mono">Ring {detail.ring_id}</span>
          <StatusBadge status={detail.status} />
        </>}
      >
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
          <Badge variant="outline">{detail.topology_type}</Badge>
          <Badge variant="outline">Confidence {fmtWeight(detail.confidence)}</Badge>
          <Badge variant="outline">{detail.n_members} members · {detail.n_edges} edges</Badge>
          {detail.cross_bank ? <Badge variant="violet"><Globe2 /> Cross-bank: {detail.counterparty_banks.join(", ")}</Badge> : null}
        </div>
      </PageHeader>
      {session.role === "admin" ? <ReadOnlyBanner /> : null}
      <RegenerationStatus tenantId={tenantId} ringId={ringId} explanation={explanation.data} />
      <div className="grid items-start gap-4 min-[1600px]:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_minmax(0,1.3fr)]">
        <NarrativePanel ring={detail} explanation={explanation.data} explanationState={explanationState} history={history.data} />
        <GraphPanel tenantId={tenantId} ringId={ringId} />
        <EvidencePanel
          ring={detail} ringId={ringId}
          evidence={evidence.data}
          evidenceState={{ isPending: evidence.isPending, error: evidence.error, retry: () => evidence.refetch() }}
          explanation={explanation.data}
          explanationState={explanationState}
        />
      </div>
      <RingVerdicts history={history.data}
        state={{ isPending: history.isPending, error: history.error, retry: () => history.refetch() }} />
      <VerdictForm tenantId={tenantId} ringId={ringId} ring={detail} />
    </>
  );
}

export function RingDetailPage() {
  const { ringId = "" } = useParams();
  const { tenantId } = useActiveTenant();
  return (
    <>
      <BackToQueue />
      {tenantId === null ? null : <RingDetail key={`${tenantId}/${ringId}`} tenantId={tenantId} ringId={ringId} />}
    </>
  );
}
