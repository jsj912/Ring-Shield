/**
 * Page slugs and the roles that may open them: app.py's PAGE_LABELS, PAGE_ROLES and pages_for().
 * Requirements Section 3: /rings, /verdicts, /models, /drift, /admin.
 */
import type { Role } from "@/api/types";

export type PageSlug = "rings" | "verdicts" | "models" | "drift" | "admin";

export const PAGE_LABELS: Record<PageSlug, string> = {
  rings: "Ring queue",
  verdicts: "Verdict history",
  models: "Models",
  drift: "Drift",
  admin: "Admin",
};

export const PAGE_ROLES: Record<PageSlug, ReadonlySet<Role>> = {
  rings: new Set(["analyst", "supervisor", "admin"]),
  verdicts: new Set(["analyst", "supervisor", "admin"]),
  models: new Set(["analyst", "supervisor", "admin"]),          // analyst: read-only
  drift: new Set(["supervisor", "admin"]),
  admin: new Set(["admin"]),
};

export function pagesFor(role: Role): PageSlug[] {
  return (Object.keys(PAGE_LABELS) as PageSlug[]).filter((slug) => PAGE_ROLES[slug].has(role));
}

export function mayOpen(role: Role, slug: PageSlug): boolean {
  return PAGE_ROLES[slug].has(role);
}

/** Roles that may record verdicts (verdicts.py; the form is disabled for everyone else). */
export function canRecordVerdicts(role: Role): boolean {
  return role === "analyst" || role === "supervisor";
}
