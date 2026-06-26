import { ALL_NAV_HREFS, HOME_NAV, NAV_GROUPS, type NavGroup, type NavItem } from "./full-saas";

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

const FIELD_USER_HREFS = new Set(["/home", "/", "/answers/history"]);

const REVIEWER_HREFS = new Set([
  ...FIELD_USER_HREFS,
  "/reviews",
  "/reviews/documents",
  "/reviews/settings",
]);

const OPS_OWNER_HREFS = new Set([
  ...REVIEWER_HREFS,
  "/sources/list",
  "/sources",
  "/documents",
  "/ingestion-runs",
  "/operations",
  "/operations/safety",
  "/operations/quality",
  "/operations/improvements",
  "/operations/impact-report",
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
