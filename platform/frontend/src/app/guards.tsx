import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { Lock } from "lucide-react";
import { peekNotice } from "@/api/session";
import { EmptyState } from "@/components/shared";
import { mayOpen, type PageSlug } from "./pages";
import { useSession } from "./session";

/** Signed-out users go to /login (and come back to where they were going after signing in). */
export function RequireSession({ children }: { children: ReactNode }) {
  const session = useSession();
  const location = useLocation();
  // After an expired session the user comes back to where they were; a deliberate sign out does not
  // carry the page over to whoever signs in next.
  if (!session) return <Navigate to="/login" replace state={peekNotice() ? { from: location.pathname } : null} />;
  return <>{children}</>;
}

/** FR-D05: a page the role may not open is not in the navigation and says so if reached by URL. */
export function RequirePage({ slug, children }: { slug: PageSlug; children: ReactNode }) {
  const session = useSession();
  if (!session || !mayOpen(session.role, slug)) {
    return (
      <EmptyState title="Not permitted" icon={<Lock />}>
        Your role cannot open this screen.
      </EmptyState>
    );
  }
  return <>{children}</>;
}
