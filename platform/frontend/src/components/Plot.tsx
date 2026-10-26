/** Charts load Plotly (about 1 MB) only when a chart is first shown. */
import { lazy, Suspense, type ComponentProps } from "react";
import { Skeleton } from "@/components/ui/skeleton";

const PlotImpl = lazy(() => import("./PlotImpl"));

export function Plot(props: ComponentProps<typeof PlotImpl>) {
  return (
    <Suspense fallback={<Skeleton className="w-full" style={{ height: props.height ?? 320 }} />}>
      <PlotImpl {...props} />
    </Suspense>
  );
}
