/**
 * The tenant every screen is scoped to (app.py::_active_tenant). Bank users: their session's
 * tenant, never one from the URL (NFR-D11). Admin: one of the loaded tenants, chosen in the top bar.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/endpoints";
import type { TenantResponse } from "@/api/types";
import { useSession } from "./session";
import { useWorkspace } from "./workspace";

export interface ActiveTenant {
  tenantId: number | null;
  tenantName: string | null;
  loaded: TenantResponse[];
  tenantsQuery: ReturnType<typeof useTenantsQuery> | null;
}

export function useTenantsQuery(enabled: boolean) {
  return useQuery({ queryKey: ["admin", "tenants"], queryFn: api.tenants, enabled });
}

export function useActiveTenant(): ActiveTenant {
  const session = useSession();
  const { selectedTenant } = useWorkspace();
  const isAdmin = session?.role === "admin";
  const tenantsQuery = useTenantsQuery(Boolean(isAdmin));
  if (!session) return { tenantId: null, tenantName: null, loaded: [], tenantsQuery: null };
  if (!isAdmin) {
    return { tenantId: session.tenant_id, tenantName: session.tenant_name, loaded: [], tenantsQuery: null };
  }
  const loaded = (tenantsQuery.data ?? []).filter((item) => item.is_loaded);
  const chosen = loaded.find((item) => item.tenant_id === selectedTenant) ?? loaded[0];
  return { tenantId: chosen?.tenant_id ?? null, tenantName: chosen?.name ?? null, loaded, tenantsQuery };
}
