import type { Request } from "express";
import type { Principal } from "../auth/principal";

// P0-T06 stub — resolve the tenant for the current request from the attached principal.
// Phase 1 (P1-T15) wires this into a request-scoped DB session that sets app.current_tenant_id
// (Postgres RLS). Phase 0 only exposes the resolution helper.
export function tenantOf(req: Request): string {
  const principal = req.principal as Principal | undefined;
  if (!principal?.tenant_id) {
    throw new Error("no tenant in request context");
  }
  return principal.tenant_id;
}
