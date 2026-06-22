import { ForbiddenException } from "@nestjs/common";
import type { Request } from "express";

const ADMIN_MUTATION_ROLES = new Set(["admin", "tenant_admin", "platform_admin", "owner"]);

export function assertAdminMutationAllowed(req: Request): void {
  const roles = req.principal?.roles ?? [];
  if (!roles.some((role) => ADMIN_MUTATION_ROLES.has(role))) {
    throw new ForbiddenException("admin role required");
  }
}
