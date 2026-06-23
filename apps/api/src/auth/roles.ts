import { ForbiddenException } from "@nestjs/common";
import type { Request } from "express";

const ADMIN_MUTATION_ROLES = new Set(["admin", "tenant_admin", "platform_admin", "owner"]);

export function assertAdminMutationAllowed(req: Request): void {
  const roles = req.principal?.roles ?? [];
  if (!roles.some((role) => ADMIN_MUTATION_ROLES.has(role))) {
    throw new ForbiddenException("admin role required");
  }
}

/**
 * Gate tenant-wide AGGREGATE read views (audit / dashboard / KPI / safety-telemetry). These have no
 * per-document ACL — they expose cross-user activity for the whole tenant — so an un-provisioned
 * member (zero roles) must NOT read them. Require at least one role; any provisioned member passes
 * (a viewer is enough), while a no-role principal is denied. Per-document reads keep their own ACL.
 */
export function assertReadViewAllowed(req: Request): void {
  const roles = req.principal?.roles ?? [];
  if (roles.length === 0) {
    throw new ForbiddenException("a tenant role is required to read tenant-wide views");
  }
}
