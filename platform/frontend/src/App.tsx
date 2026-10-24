import { lazy, Suspense, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ApiError } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { RequirePage, RequireSession } from "@/app/guards";
import { Layout } from "@/app/Layout";
import { useClearOnSignOut, useExpiryTimer, useSession } from "@/app/session";
import { WorkspaceProvider } from "@/app/workspace";
import { LoginPage } from "@/pages/LoginPage";
import { QueuePage } from "@/pages/QueuePage";
import { AdminPage } from "@/pages/AdminPage";
import { DriftPage } from "@/pages/DriftPage";
import { ModelsPage } from "@/pages/ModelsPage";
import { VerdictsPage } from "@/pages/VerdictsPage";
import { Skeleton } from "@/components/ui/skeleton";

// The ring graph (Cytoscape) loads with the ring page, not with the login screen.
const RingDetailPage = lazy(() => import("@/pages/RingDetailPage").then((m) => ({ default: m.RingDetailPage })));

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Errors surface at once with a Retry button (FR-D100); a 401 has already signed out.
        retry: (count, error) => !(error instanceof ApiError) && count < 1,
        refetchOnWindowFocus: false,
        staleTime: 30_000,
      },
    },
  });
}

function Shell() {
  const session = useSession();
  useExpiryTimer(session);
  useClearOnSignOut(session);
  return (
    <WorkspaceProvider session={session}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireSession><Layout /></RequireSession>}>
          <Route path="/rings" element={<RequirePage slug="rings"><QueuePage /></RequirePage>} />
          <Route path="/rings/:ringId" element={<RequirePage slug="rings"><Suspense fallback={<Skeleton className="h-[520px] w-full" />}><RingDetailPage /></Suspense></RequirePage>} />
          <Route path="/verdicts" element={<RequirePage slug="verdicts"><VerdictsPage /></RequirePage>} />
          <Route path="/models" element={<RequirePage slug="models"><ModelsPage /></RequirePage>} />
          <Route path="/drift" element={<RequirePage slug="drift"><DriftPage /></RequirePage>} />
          <Route path="/admin" element={<RequirePage slug="admin"><AdminPage /></RequirePage>} />
          <Route path="*" element={<Navigate to="/rings" replace />} />
        </Route>
      </Routes>
    </WorkspaceProvider>
  );
}

export default function App({ client: given }: { client?: QueryClient }) {
  const [client] = useState(() => given ?? makeQueryClient());
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider delayDuration={200}>
        <BrowserRouter>
          <Shell />
        </BrowserRouter>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
