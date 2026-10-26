/**
 * FR-D40-44: transactions, accounts and detector signals. Independent of the graph route: it
 * reads GET .../evidence and the explanation, and a failure in either stays in this panel.
 */
import { useState } from "react";
import { Download, ListTree } from "lucide-react";
import type { AccountWeight, EdgeWeight, RingDetail, RingEvidenceGraph, RingExplanation } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ErrorState, TableSkeleton, WeightBar } from "@/components/shared";
import { Plot } from "@/components/Plot";
import { downloadText, toCsv } from "@/lib/csv";
import { fmtAmount, fmtSeconds, fmtTime, fmtTimeUtc, fmtWeight } from "@/lib/formatters";
import { isRemoved, type Correction } from "./verdict-state";

export const DETECTOR_CAPTION = "Signals from the transaction-level detector on the ring's seed transactions";

/** Python: sorted(key=(value is not None, value or 0), reverse=True): present values first, high to low, stable. */
function byWeightDescending<T>(items: T[], weight: (item: T) => number | null | undefined): T[] {
  return [...items].sort((a, b) => {
    const wa = weight(a), wb = weight(b);
    const aHas = wa !== null && wa !== undefined, bHas = wb !== null && wb !== undefined;
    if (aHas !== bHas) return aHas ? -1 : 1;
    const va = wa ?? 0, vb = wb ?? 0;
    return va === vb ? 0 : va > vb ? -1 : 1;
  });
}

interface TransactionRow {
  edge_id: number;
  from: number;
  to: number;
  amount: string;
  time: string;
  timeUtc: string;
  payment_format: string;
  kind: string;
  w_total: number | null;
  w_score: number | null;
  w_loo: number | null;
  w_flow: number | null;
}

function transactionRows(evidence: RingEvidenceGraph | undefined, explanation: RingExplanation | null | undefined,
  ring: RingDetail, showConversions: boolean): TransactionRow[] {
  const weights = new Map<number, EdgeWeight>((explanation?.edge_weights ?? []).map((item) => [item.edge_id, item]));
  const seeds = new Set(ring.seed_edges);
  const rows: TransactionRow[] = [];
  for (const edge of evidence?.edges ?? []) {
    if (edge.is_conversion && !showConversions) continue;
    const weight = weights.get(edge.edge_id);
    rows.push({
      edge_id: edge.edge_id, from: edge.source_account, to: edge.target_account,
      amount: fmtAmount(edge.amount_sent, edge.currency_sent), time: fmtTime(edge.timestamp), timeUtc: fmtTimeUtc(edge.timestamp),
      payment_format: edge.payment_format || "—",
      kind: edge.is_conversion ? "conversion" : seeds.has(edge.edge_id) ? "seed" : "expanded",
      w_total: weight?.w_total ?? null, w_score: weight?.w_score ?? null, w_loo: weight?.w_loo ?? null, w_flow: weight?.w_flow ?? null,
    });
  }
  return byWeightDescending(rows, (row) => row.w_total);
}

function ExportButton({ onClick }: { onClick: () => void }) {
  return <Button size="xs" variant="outline" onClick={onClick}><Download /> CSV</Button>;
}

export function EvidencePanel({ ring, ringId, correction, evidence, evidenceState, explanation, explanationState }: {
  ring: RingDetail; ringId: string; correction: Correction | null;
  evidence: RingEvidenceGraph | undefined;
  evidenceState: { isPending: boolean; error: unknown; retry: () => void };
  explanation: RingExplanation | null | undefined;
  explanationState: { isPending: boolean; error: unknown; retry: () => void };
}) {
  const [showConversions, setShowConversions] = useState(false);
  // After a partial verdict the tabs list the corrected ring only.
  const transactions = transactionRows(evidence, explanation, ring, showConversions)
    .filter((row) => !isRemoved(correction, row.edge_id, row.from, row.to));
  const banks = new Map((evidence?.nodes ?? []).map((node) => [node.account_id, node.bank_label]));
  const accounts = byWeightDescending<AccountWeight>((explanation?.account_weights ?? [])
    .filter((item) => !correction?.removedAccounts.has(item.account_id)), (item) => item.w_account);
  // The API sends feature_weights already ranked by |mean_shap| (explainability/feature_weights.py):
  // take its first ten as they come, reversed only so the chart draws the strongest at the top.
  const features = (explanation?.feature_weights ?? []).slice(0, 10).reverse();

  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><ListTree className="size-4 text-primary" /> Evidence</CardTitle>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="transactions">
          <TabsList className="w-full">
            <TabsTrigger value="transactions">Transactions</TabsTrigger>
            <TabsTrigger value="accounts">Accounts</TabsTrigger>
            <TabsTrigger value="signals">Detector signals</TabsTrigger>
          </TabsList>

          <TabsContent value="transactions" className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <label className="flex items-center gap-2 text-xs">
                <Switch checked={showConversions} onCheckedChange={setShowConversions} aria-label="Show currency conversions in evidence" />
                Show currency conversions
              </label>
              {transactions.length ? (
                <ExportButton onClick={() => downloadText(toCsv(transactions.map((row) => ({ ...row })),
                  ["edge_id", "from", "to", "amount", "time", "payment_format", "kind", "w_total", "w_score", "w_loo", "w_flow"],
                  new Set(["amount", "time", "payment_format", "kind"])), `${ringId}-transactions.csv`)} />
              ) : null}
            </div>
            {evidenceState.isPending ? <TableSkeleton rows={5} columns={5} /> : evidenceState.error ? (
              <ErrorState compact error={evidenceState.error} onRetry={evidenceState.retry} />
            ) : transactions.length === 0 ? (
              <p className="text-muted-foreground text-xs">No transactions are loaded for this ring.</p>
            ) : (
              <div className="max-h-[440px] overflow-auto rounded-md border">
                <Table className="text-xs">
                  <TableHeader className="sticky top-0 z-10 bg-card">
                    <TableRow>
                      <TableHead>From</TableHead><TableHead>To</TableHead><TableHead className="text-right">Amount</TableHead>
                      <TableHead>Time</TableHead><TableHead>Payment format</TableHead><TableHead>Kind</TableHead>
                      <TableHead>w_total</TableHead><TableHead>w_score</TableHead><TableHead>w_loo</TableHead><TableHead>w_flow</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {transactions.map((row) => (
                      <TableRow key={row.edge_id} data-testid="transaction-row">
                        <TableCell className="font-mono">{row.from}</TableCell>
                        <TableCell className="font-mono">{row.to}</TableCell>
                        <TableCell className="text-right tabular-nums">{row.amount}</TableCell>
                        <TableCell title={row.timeUtc}>{row.time}</TableCell>
                        <TableCell>{row.payment_format}</TableCell>
                        <TableCell>
                          <span className={row.kind === "seed" ? "font-medium" : "text-muted-foreground"}>{row.kind}</span>
                        </TableCell>
                        <TableCell><span className="inline-flex items-center gap-1.5 tabular-nums"><WeightBar value={row.w_total} />{fmtWeight(row.w_total)}</span></TableCell>
                        <TableCell className="tabular-nums">{fmtWeight(row.w_score)}</TableCell>
                        <TableCell className="tabular-nums">{fmtWeight(row.w_loo)}</TableCell>
                        <TableCell className="tabular-nums">{fmtWeight(row.w_flow)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </TabsContent>

          <TabsContent value="accounts" className="space-y-2">
            {explanationState.isPending ? <TableSkeleton rows={5} columns={5} /> : explanationState.error ? (
              <ErrorState compact error={explanationState.error} onRetry={explanationState.retry} />
            ) : accounts.length === 0 ? (
              <p className="text-muted-foreground text-xs">No account weights: the explanation has not been loaded.</p>
            ) : (
              <>
                <div className="flex justify-end">
                  <ExportButton onClick={() => downloadText(toCsv(accounts.map((item) => ({
                    account: item.account_id, bank: banks.get(item.account_id) ?? "", role: item.role ?? "",
                    inflow: item.inflow ?? "", outflow: item.outflow ?? "", hold_time_s: item.hold_time_s ?? "", w_account: item.w_account ?? "",
                  })), ["account", "bank", "role", "inflow", "outflow", "hold_time_s", "w_account"], new Set(["bank", "role"])),
                  `${ringId}-accounts.csv`)} />
                </div>
                <div className="max-h-[440px] overflow-auto rounded-md border">
                  <Table className="text-xs">
                    <TableHeader className="sticky top-0 z-10 bg-card">
                      <TableRow>
                        <TableHead>Account</TableHead><TableHead>Bank</TableHead><TableHead>Role</TableHead>
                        <TableHead className="text-right">Inflow</TableHead><TableHead className="text-right">Outflow</TableHead>
                        <TableHead className="text-right">Hold time</TableHead><TableHead>w_account</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {accounts.map((item) => (
                        <TableRow key={item.account_id} data-testid="account-row">
                          <TableCell className="font-mono">{item.account_id}</TableCell>
                          <TableCell>{banks.get(item.account_id) || "—"}</TableCell>
                          <TableCell>{item.role || "—"}</TableCell>
                          <TableCell className="text-right tabular-nums">{fmtAmount(item.inflow)}</TableCell>
                          <TableCell className="text-right tabular-nums">{fmtAmount(item.outflow)}</TableCell>
                          <TableCell className="text-right tabular-nums">{fmtSeconds(item.hold_time_s)}</TableCell>
                          <TableCell><span className="inline-flex items-center gap-1.5 tabular-nums"><WeightBar value={item.w_account} />{fmtWeight(item.w_account)}</span></TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </>
            )}
          </TabsContent>

          <TabsContent value="signals" className="space-y-2">
            {explanationState.error ? <ErrorState compact error={explanationState.error} onRetry={explanationState.retry} /> : null}
            {features.length ? (
              <>
                <div className="flex justify-end">
                  <ExportButton onClick={() => downloadText(toCsv([...features].reverse().map((item) => ({
                    feature_name: item.feature_name, display_name: item.display_name ?? "", mean_shap: item.mean_shap ?? "",
                  })), ["feature_name", "display_name", "mean_shap"], new Set(["feature_name", "display_name"])), `${ringId}-signals.csv`)} />
                </div>
                <Plot
                  testId="signals-chart"
                  height={360}
                  data={[{
                    type: "bar", orientation: "h",
                    x: features.map((item) => item.mean_shap),
                    y: features.map((item) => item.display_name || item.feature_name),
                    marker: { color: features.map((item) => ((item.mean_shap ?? 0) >= 0 ? "#c0392b" : "#2471a3")) },
                    hovertemplate: "%{y}: %{x:.2f}<extra></extra>",
                  }]}
                  layout={{ xaxis: { title: { text: "mean SHAP (red raises suspicion, blue lowers it)" } } }}
                />
              </>
            ) : null}
            <p className="text-muted-foreground text-xs">{DETECTOR_CAPTION}</p>
          </TabsContent>
        </Tabs>
        {explanation ? (
          <p className="text-muted-foreground mt-3 border-t pt-2 text-[11px]" data-testid="explanation-footer">
            Explainer {explanation.explainer_version} · {explanation.latency_ms} ms · revision {explanation.revision}
            {explanation.regenerated ? " · Regenerated" : ""}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
