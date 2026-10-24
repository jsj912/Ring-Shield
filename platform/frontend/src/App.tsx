import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Construction } from "lucide-react";
import { ApiError } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { EmptyState, PageHeader } from "@/components/shared";
import { RequirePage, RequireSession } from "@/app/guards";
import { Layout } from "@/app/Layout";
import { PAGE_LABELS, type PageSlug } from "@/app/pages";
import { useClearOnSignOut, useExpiryTimer, useSession } from "@/app/session";
import { WorkspaceProvider } from "@/app/workspace";
import { LoginPage } from "@/pages/LoginPage";
import { QueuePage } from "@/pages/QueuePage";
import { RingDetailPage } from "@/pages/RingDetailPage";

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

function Pending({ slug }: { slug: PageSlug }) {
  return (
    <>
      <PageHeader title={PAGE_LABELS[slug]} />
      <EmptyState title="Coming in the next step" icon={<Construction />}>
        This screen is being ported from the Streamlit dashboard.
      </EmptyState>
    </>
  );
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
          <Route path="/rings/:ringId" element={<RequirePage slug="rings"><RingDetailPage /></RequirePage>} />
          <Route path="/verdicts" element={<RequirePage slug="verdicts"><Pending slug="verdicts" /></RequirePage>} />
          <Route path="/models" element={<RequirePage slug="models"><Pending slug="models" /></RequirePage>} />
          <Route path="/drift" element={<RequirePage slug="drift"><Pending slug="drift" /></RequirePage>} />
          <Route path="/admin" element={<RequirePage slug="admin"><Pending slug="admin" /></RequirePage>} />
          <Route path="*" element={<Navigate to="/rings" replace />} />
        </Route>
      </Routes>
    </WorkspaceProvider>
  );
}

export default function App({ client = makeQueryClient() }: { client?: QueryClient }) {
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
