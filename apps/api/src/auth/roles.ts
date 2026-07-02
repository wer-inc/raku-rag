import { ForbiddenException } from "@nestjs/common";
import type { Request } from "express";

const ADMIN_MUTATION_ROLES = new Set(["admin", "tenant_admin", "platform_admin", "owner"]);

export function assertAdminMutationAllowed(req: Request): void {
  const roles = req.principal?.roles ?? [];
  if (!roles.some((role) => ADMIN_MUTATION_ROLES.has(role))) {
    throw new ForbiddenException("admin role required");
  }
}

// Roles allowed to act on the HUMAN REVIEW / APPROVAL loop: assign a reviewer, approve/reject an AI
// draft, and approve/obsolete a source document. Per contract (mfg-interfaces.md:141 "approved は
// reviewer のみ") the dedicated `reviewer` role is the intended approver; admin-tier roles are kept as
// a superset (a tenant_admin can always act). `ops_owner` is intentionally EXCLUDED — the contract
// names only `reviewer`. To grant ops_owner approval rights once the spec decides so, add "ops_owner"
// to the set below (single-line change). This guard is the facade's authorization seam for these
// routes; the answer-service/core layers attribute the actor but do not re-check the role.
const REVIEW_APPROVAL_ROLES = new Set(["reviewer", ...ADMIN_MUTATION_ROLES]);

export function assertReviewApprovalAllowed(req: Request): void {
  const roles = req.principal?.roles ?? [];
  if (!roles.some((role) => REVIEW_APPROVAL_ROLES.has(role))) {
    throw new ForbiddenException("reviewer or admin role required");
  }
}

// Reading the review queue and individual AI drafts is limited to the SAME reviewer/admin set
// (screens.manifest.json review-queue/review-detail rbac=[reviewer, tenant_admin]). Drafts are
// pre-approval AI content (provenance, citations, decision), so an un-provisioned or field-only tenant
// member must NOT browse them — unlike the aggregate dashboards gated by assertReadViewAllowed. See
// issue 0024 (draft read endpoints were previously ungated).
export function assertReviewViewAllowed(req: Request): void {
  const roles = req.principal?.roles ?? [];
  if (!roles.some((role) => REVIEW_APPROVAL_ROLES.has(role))) {
    throw new ForbiddenException("reviewer or admin role required to read the review queue");
  }
}

// 022-ai-phone-rag — phone-channel role sets (contracts/phone-rag-openapi.md §Authorization
// Matrix). The answer-service phone layer re-checks the same sets; this facade gate is the
// defense-in-depth outer wall, mirroring the chat controller pattern.
export const PHONE_SIMULATE_ROLES = ["tenant_admin", "ops_owner", "qa_reviewer"] as const;
export const PHONE_CALL_READ_ROLES = ["ops_owner", "tenant_admin", "qa_reviewer"] as const;
export const PHONE_HANDOFF_READ_ROLES = ["operator", "ops_owner", "tenant_admin"] as const;
export const PHONE_SCENARIO_READ_ROLES = [
  "tenant_admin",
  "scenario_admin",
  "scenario_approver",
  "ops_owner",
] as const;
export const PHONE_SCENARIO_MANAGE_ROLES = ["tenant_admin", "scenario_admin"] as const;
export const PHONE_SCENARIO_APPROVE_ROLES = ["tenant_admin", "scenario_approver"] as const;

export function assertAnyRoleAllowed(
  req: Request,
  allowedRoles: readonly string[],
  message = "phone_role_required",
): void {
  const roles = new Set(req.principal?.roles ?? []);
  if (!allowedRoles.some((role) => roles.has(role))) {
    throw new ForbiddenException(message);
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
