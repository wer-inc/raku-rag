import {
  ALL_NAV_HREFS,
  APPROVAL_WORKFLOW_ENABLED,
  HOME_NAV,
  NAV_GROUPS,
  type NavGroup,
  type NavItem,
} from "./full-saas";

/** Dev/demo role slugs — mirror apps/web/app/api/dev-token/route.ts DEV_ROLES_BY_USER. */
export type WorkspaceRole =
  | "field_user"
  | "reviewer"
  | "ops_owner"
  | "tenant_admin"
  | "platform_admin"
  | "sales_demo";

const WORKSPACE_ROLES: WorkspaceRole[] = [
  "field_user",
  "reviewer",
  "ops_owner",
  "tenant_admin",
  "platform_admin",
  "sales_demo",
];

const FIELD_USER_HREFS = new Set(["/home", "/", "/chatbot", "/answers/history"]);

const REVIEWER_HREFS = new Set([
  ...FIELD_USER_HREFS,
  ...(APPROVAL_WORKFLOW_ENABLED ? ["/reviews", "/reviews/documents"] : []),
  // NOTE: /reviews/settings is tenant_admin-only (screens.manifest.json approval-workflow-settings
  // rbac=[tenant_admin]; see issue 0011 DoD#4 / 0014). It is intentionally NOT granted to reviewer.
  // screens.manifest.json knowledge-improvement-queue rbac=[reviewer, ops_owner, tenant_admin].
  "/operations/improvements",
]);

// Paths only tenant_admin/platform_admin may see, even when a less-privileged role holds the parent
// path (e.g. a reviewer holds /reviews). Without this, navAllowed's subpath rule would leak
// /reviews/settings to reviewers. Mirrors screens.manifest.json per-screen rbac.
const TENANT_ADMIN_ONLY_HREFS = new Set(
  APPROVAL_WORKFLOW_ENABLED ? ["/reviews/settings"] : [],
);

// ops_owner ("ナレッジ管理者") manages sources/documents/operations but is NOT a review-cluster role:
// screens.manifest.json review-queue/review-detail/document-approval-queue rbac=[reviewer, tenant_admin]
// exclude ops_owner, and the API (assertReviewViewAllowed / assertReviewApprovalAllowed) denies it too.
// So we spread FIELD_USER_HREFS (NOT REVIEWER_HREFS) to keep /reviews* out of the ops_owner nav and
// avoid a "nav shows it, API 403s it" dead screen. (issue 0011 DoD#4 / 0024)
const OPS_OWNER_HREFS = new Set([
  ...FIELD_USER_HREFS,
  // 022-ai-phone-rag: phone simulate/call-history are ops_owner+tenant_admin surfaces
  // (screens.manifest.json phone rbac=[ops_owner, tenant_admin]); NOT field_user.
  "/phone",
  "/files",
  "/sources/list",
  "/sources",
  "/documents",
  "/ingestion-runs",
  "/operations",
  "/operations/safety",
  "/operations/quality",
  "/operations/improvements",
  "/operations/impact-report",
  // screens.manifest.json audit-log rbac=[ops_owner, tenant_admin, auditor] (U8 nav item).
  "/audit",
  "/admin/retrieval/debug",
]);

const TENANT_ADMIN_HREFS = new Set(ALL_NAV_HREFS);

export function rolesForUser(userId: string): WorkspaceRole[] {
  const table: Record<string, WorkspaceRole[]> = {
    alice: ["tenant_admin", "reviewer"],
    bob: ["field_user"],
    carol: ["reviewer"],
    dave: ["ops_owner"],
    misaki: ["reviewer", "tenant_admin"],
    "sales-demo@example.com": ["sales_demo", "tenant_admin", "reviewer"],
  };
  return table[userId] ?? ["field_user"];
}

export function isWorkspaceRole(role: string): role is WorkspaceRole {
  return (WORKSPACE_ROLES as string[]).includes(role);
}

export function normalizeWorkspaceRoles(values: string[]): WorkspaceRole[] {
  const seen = new Set<WorkspaceRole>();
  for (const value of values) {
    if (isWorkspaceRole(value)) {
      seen.add(value);
    }
  }
  return Array.from(seen);
}

export function primaryRole(roles: WorkspaceRole[]): WorkspaceRole {
  if (roles.includes("tenant_admin") || roles.includes("platform_admin")) return "tenant_admin";
  if (roles.includes("ops_owner")) return "ops_owner";
  if (roles.includes("reviewer")) return "reviewer";
  return "field_user";
}

function allowedHrefs(role: WorkspaceRole): Set<string> {
  switch (role) {
    case "tenant_admin":
    case "platform_admin":
      return TENANT_ADMIN_HREFS;
    case "ops_owner":
      return OPS_OWNER_HREFS;
    case "reviewer":
      return REVIEWER_HREFS;
    default:
      return FIELD_USER_HREFS;
  }
}

export function navAllowed(href: string, roles: WorkspaceRole[]): boolean {
  const effective = roles.length ? roles : (["field_user"] as WorkspaceRole[]);
  if (effective.some((r) => r === "tenant_admin" || r === "platform_admin")) {
    return true;
  }
  // Non-admins never see a tenant_admin-only path OR its children, even when they hold a parent path
  // (a reviewer holds /reviews but must not get /reviews/settings or /reviews/settings/*). Mirrors
  // screens.manifest.json per-screen rbac. (tenant_admin/platform_admin already returned true above.)
  if ([...TENANT_ADMIN_ONLY_HREFS].some((x) => href === x || href.startsWith(`${x}/`))) {
    return false;
  }
  const union = new Set<string>();
  for (const role of effective) {
    for (const h of allowedHrefs(role)) union.add(h);
  }
  if (union.has(href)) return true;
  for (const h of union) {
    if (href !== "/" && href.startsWith(`${h}/`)) return true;
  }
  return false;
}

export function filterNavGroups(roles: WorkspaceRole[]): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => navAllowed(item.href, roles)),
  })).filter((g) => g.items.length > 0);
}

export function homeNavVisible(roles: WorkspaceRole[]): boolean {
  return navAllowed(HOME_NAV.href, roles);
}

export function roleLabel(role: WorkspaceRole): string {
  switch (role) {
    case "tenant_admin":
      return "管理者";
    case "ops_owner":
      return "ナレッジ管理者";
    case "reviewer":
      return "承認者";
    case "sales_demo":
      return "管理者";
    default:
      return "一般ユーザー";
  }
}

export function userDisplayName(userId: string): string {
  const names: Record<string, string> = {
    alice: "Alice Tanaka",
    bob: "Bob Sato",
    carol: "Carol Kato",
    dave: "Dave Ops",
    misaki: "田中 美咲",
    "sales-demo@example.com": "資料確認ユーザー",
  };
  return names[userId] ?? userId;
}

export function filterNavItem(item: NavItem, roles: WorkspaceRole[]): boolean {
  return navAllowed(item.href, roles);
}
