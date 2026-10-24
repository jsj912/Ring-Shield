/** FR-D30-34, D36. A failure here stays in this panel (NFR-D32). */
import { Component, useState, type ReactNode } from "react";
import { Share2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { ErrorState, Notice } from "@/components/shared";
import { RingGraph } from "@/components/RingGraph";
import { NODE_CAP } from "@/lib/ring-graph";
import { useSubgraph } from "./queries";

/** Keeps a drawing failure inside the graph panel; the narrative and evidence stay up. */
class GraphBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed
      ? <Notice tone="error">The graph could not be drawn for this ring; the narrative and evidence are unaffected.</Notice>
      : this.props.children;
  }
}

export function GraphPanel({ tenantId, ringId }: { tenantId: number; ringId: string }) {
  const subgraph = useSubgraph(tenantId, ringId);
  const [showConversions, setShowConversions] = useState(false);
  const [loadAll, setLoadAll] = useState(false);
  const capped = subgraph.data ? subgraph.data.n_accounts > NODE_CAP && !loadAll : false;

  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Share2 className="size-4 text-primary" /> Graph</CardTitle>
        <label className="flex items-center gap-2 text-xs">
          <Switch checked={showConversions} onCheckedChange={setShowConversions} aria-label="Show currency conversions" />
          Show currency conversions
        </label>
      </CardHeader>
      <CardContent className="space-y-2">
        {subgraph.isPending ? <Skeleton className="h-[460px] w-full" /> : subgraph.isError ? (
          <>
            <ErrorState compact error={subgraph.error} onRetry={() => subgraph.refetch()} />
            <p className="text-muted-foreground text-xs">The graph could not be loaded; the narrative and evidence are unaffected.</p>
          </>
        ) : (
          <>
            {capped ? (
              <Notice tone="info" className="flex items-center justify-between gap-2">
                <span data-testid="node-cap-banner">Showing {NODE_CAP} of {subgraph.data.n_accounts} accounts</span>
                <Button size="xs" variant="outline" onClick={() => setLoadAll(true)}>Load all accounts</Button>
              </Notice>
            ) : null}
            <GraphBoundary>
              <RingGraph subgraph={subgraph.data} showConversions={showConversions} loadAll={loadAll} ringId={ringId} />
            </GraphBoundary>
          </>
        )}
      </CardContent>
    </Card>
  );
}
