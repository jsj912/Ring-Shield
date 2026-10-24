/**
 * The application shell (requirements Section 3): a left sidebar with the role's pages and sign
 * out at the bottom, and a top bar with the tenant (a switcher for the admin), the user and role.
 */
import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { Activity, Building2, ClipboardCheck, Cpu, LogOut, Menu, Network, ShieldCheck, Shield, X } from "lucide-react";
import { API_BASE } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/shared";
import { cn } from "@/lib/utils";
import { PAGE_LABELS, pagesFor, type PageSlug } from "./pages";
import { useSession, useSignOut } from "./session";
import { useActiveTenant } from "./tenant";
import { ThemeToggle, useTheme } from "./theme";
import { useWorkspace } from "./workspace";

const ICONS: Record<PageSlug, ReactNode> = {
  rings: <Network />, verdicts: <ClipboardCheck />, models: <Cpu />, drift: <Activity />, admin: <ShieldCheck />,
};

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const session = useSession()!;
  const signOut = useSignOut();
  const navigate = useNavigate();
  return (
    <div className="bg-sidebar text-sidebar-foreground flex h-full w-60 flex-col">
      <div className="border-sidebar-border flex h-14 items-center gap-2 border-b px-4">
        <div className="bg-primary/20 text-primary rounded-md p-1.5">
          <Shield className="size-4" />
        </div>
        <div className="leading-tight">
          <p className="text-sm font-semibold text-white">RingShield</p>
          <p className="text-sidebar-muted text-[11px]">Investigator</p>
        </div>
      </div>
      <div className="border-sidebar-border border-b px-4 py-3">
        <p className="text-sidebar-muted text-[11px] uppercase tracking-wider">Signed in to</p>
        <p className="truncate text-sm font-medium text-white" data-testid="sidebar-tenant">{session.tenant_name}</p>
        <p className="text-sidebar-muted text-xs" data-testid="sidebar-role">Role: {session.role}</p>
      </div>
      <nav className="flex-1 space-y-0.5 p-2" aria-label="Workspace">
        {pagesFor(session.role).map((slug) => (
          <NavLink
            key={slug}
            to={`/${slug}`}
            onClick={onNavigate}
            className={({ isActive }) => cn(
              "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors [&_svg]:size-4",
              isActive ? "bg-sidebar-accent font-medium text-white" : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-white",
            )}
          >
            {ICONS[slug]}
            {PAGE_LABELS[slug]}
          </NavLink>
        ))}
      </nav>
      <div className="border-sidebar-border space-y-2 border-t p-2">
        <p className="text-sidebar-muted truncate px-3 text-[11px]" title={API_BASE}>API {API_BASE}</p>
        <button
          type="button"
          onClick={() => {
            signOut();
            navigate("/login", { replace: true });
          }}
          className="text-sidebar-foreground/80 hover:bg-sidebar-accent/60 flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm hover:text-white"
        >
          <LogOut className="size-4" /> Sign out
        </button>
      </div>
    </div>
  );
}

function TenantSwitcher() {
  const session = useSession()!;
  const { tenantId, tenantName, loaded, tenantsQuery } = useActiveTenant();
  const { setSelectedTenant } = useWorkspace();
  if (session.role !== "admin") {
    return (
      <div className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm">
        <Building2 className="text-muted-foreground size-4" />
        <span className="font-medium">{tenantName}</span>
      </div>
    );
  }
  if (tenantsQuery?.isPending) return <Skeleton className="h-9 w-56" />;
  if (tenantsQuery?.isError) return <ErrorState compact error={tenantsQuery.error} onRetry={() => tenantsQuery.refetch()} />;
  if (!loaded.length) return <span className="text-muted-foreground text-sm">No tenant is marked as loaded yet.</span>;
  return (
    <div className="flex items-center gap-2">
      <Building2 className="text-muted-foreground size-4" />
      <Select value={String(tenantId)} onValueChange={(value) => setSelectedTenant(Number(value))}>
        <SelectTrigger className="h-9 w-60" aria-label="Tenant">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {loaded.map((item) => (
            <SelectItem key={item.tenant_id} value={String(item.tenant_id)}>
              {item.name} ({item.bank_code})
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

export function Layout() {
  const session = useSession()!;
  const { theme, toggle } = useTheme();
  const [drawer, setDrawer] = useState(false);
  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="hidden shrink-0 lg:block">
        <Sidebar />
      </aside>
      {drawer ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setDrawer(false)} />
          <div className="relative h-full w-60">
            <Sidebar onNavigate={() => setDrawer(false)} />
          </div>
        </div>
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="bg-card/80 flex h-14 shrink-0 items-center gap-3 border-b px-4 backdrop-blur">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setDrawer((open) => !open)} aria-label="Menu">
            {drawer ? <X /> : <Menu />}
          </Button>
          <TenantSwitcher />
          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle theme={theme} onToggle={toggle} />
            <div className="hidden items-center gap-2 border-l pl-3 sm:flex">
              <div className="bg-primary/15 text-primary flex size-8 items-center justify-center rounded-full text-xs font-semibold">
                {session.role.slice(0, 2).toUpperCase()}
              </div>
              <div className="leading-tight">
                <p className="text-xs font-medium">User {session.user_id}</p>
                <Badge variant="outline" className="mt-0.5 px-1.5 py-0 text-[10px] capitalize">{session.role}</Badge>
              </div>
            </div>
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1920px] space-y-4 p-4 lg:p-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
