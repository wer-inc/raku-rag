export interface ManifestApi {
  method: string;
  path: string;
  status: "existing" | "missing";
}

export interface ManifestScreen {
  id: string;
  category: string;
  route: string;
  title: string;
  absorbs: string[];
  data: string[];
  apis: ManifestApi[];
  states: string[];
  rbac: string[];
  deps: string[];
  status: string;
}

// Workspace identity shown in the sidebar org switcher + user footer.
// Mirrors the workspace defaults (東洋精機 第一工場 / 田中 美咲) and the
// /login + /orgselect selected identity so the shell reads consistently.
export const WORKSPACE_IDENTITY = {
  orgName: "東洋精機 第一工場",
  orgPlan: "raku-rag · Enterprise",
  userName: "田中 美咲",
  userRole: "品質保証部 · 承認者",
  userInitial: "田",
} as const;

// Document approval workflow is ON by default (U13): the governance UI (レビュー nav group,
// document approval queue, 承認待ち columns) is part of the product's main path. Server-side safety
// gates and AI draft review rules apply regardless; this only changes product navigation/default
// ingest policy. Set NEXT_PUBLIC_RAKU_APPROVAL_WORKFLOW=off to take the queue out of the E2E path.
export const APPROVAL_WORKFLOW_ENABLED =
  (process.env.NEXT_PUBLIC_RAKU_APPROVAL_WORKFLOW ?? "on").trim().toLowerCase() !== "off";

export type NavIconName =
  | "home" | "answers" | "chatbot" | "phone" | "history" | "sources" | "documents" | "search"
  | "ingestion" | "reviewqueue" | "approvalsettings" | "operations" | "safety"
  | "quality" | "audit" | "compliance" | "users" | "roles" | "integrations"
  | "apikeys" | "billing" | "support" | "provider" | "retrieval" | "logging" | "improvements";

export interface NavItem {
  href: string;
  label: string;
  icon: NavIconName;
  badge?: "review";
}

export interface NavGroup {
  label: string;
  items: NavItem[];
  /** U8: render this group collapsed until opened (or until it holds the active route),
   *  so the added 運用/管理 groups don't overwhelm the sidebar. */
  defaultCollapsed?: boolean;
}

// Single top-level item rendered above the grouped nav (standalone parity).
export const HOME_NAV: NavItem = { href: "/home", label: "ホーム", icon: "home" };

const REVIEW_NAV_GROUP: NavGroup = {
  label: "レビュー",
  items: [
    { href: "/reviews", label: "AIドラフトレビュー", icon: "reviewqueue", badge: "review" },
    { href: "/reviews/documents", label: "根拠文書レビュー", icon: "documents" },
    { href: "/reviews/settings", label: "同期・承認ポリシー", icon: "approvalsettings" },
  ],
};

// U8: 運用 — the operations screens that prove "運用できるRAG" (all routes render real,
// API-backed content in FullSaasScreen). RBAC mirrors screens.manifest.json: /operations/*
// = ops_owner+tenant_admin (improvements also reviewer), /audit = ops_owner+tenant_admin+auditor.
const OPERATIONS_NAV_GROUP: NavGroup = {
  label: "運用",
  defaultCollapsed: true,
  items: [
    { href: "/operations", label: "運用ダッシュボード", icon: "operations" },
    { href: "/operations/quality", label: "品質・KPI", icon: "quality" },
    { href: "/operations/improvements", label: "改善キュー", icon: "improvements" },
    { href: "/operations/safety", label: "安全テレメトリ", icon: "safety" },
    { href: "/operations/impact-report", label: "導入効果レポート", icon: "compliance" },
    { href: "/audit", label: "監査ログ", icon: "audit" },
  ],
};

// U8: 管理 — tenant_admin screens (screens.manifest.json admin-saas rbac=[tenant_admin]).
// navAllowed only ever grants these to tenant_admin/platform_admin, so members never see them.
const ADMIN_NAV_GROUP: NavGroup = {
  label: "管理",
  defaultCollapsed: true,
  items: [
    { href: "/admin/access", label: "ロール・権限", icon: "roles" },
    { href: "/admin/provider-policy", label: "プロバイダポリシー", icon: "provider" },
    { href: "/admin/users", label: "ユーザー", icon: "users" },
    { href: "/admin/integrations", label: "連携", icon: "integrations" },
    { href: "/admin/billing", label: "請求", icon: "billing" },
    { href: "/admin/retrieval", label: "検索設定", icon: "retrieval" },
    { href: "/admin/logging-privacy", label: "ログポリシー", icon: "logging" },
  ],
};

// Grouped navigation — order, labels, icons, and grouping mirror the
// standalone sidebar. Each href targets an existing workspace route.
// Group order (U8): 回答 / データ / レビュー / 運用 / 管理.
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "回答",
    items: [
      { href: "/chatbot", label: "チャットボット", icon: "chatbot" },
      { href: "/phone", label: "電話AI", icon: "phone" },
    ],
  },
  {
    label: "データ",
    items: [
      { href: "/sources/list", label: "外部接続", icon: "sources" },
      { href: "/files", label: "ファイル", icon: "documents" },
    ],
  },
  ...(APPROVAL_WORKFLOW_ENABLED ? [REVIEW_NAV_GROUP] : []),
  OPERATIONS_NAV_GROUP,
  ADMIN_NAV_GROUP,
];

// All nav hrefs, used by the sidebar to resolve the single active item by
// longest-prefix match (so /sources/list wins over /sources, etc.).
export const ALL_NAV_HREFS: string[] = [
  HOME_NAV.href,
  ...NAV_GROUPS.flatMap((group) => group.items.map((item) => item.href)),
];

// href -> sidebar display label, for breadcrumb trails (and anywhere a route needs its human name).
const NAV_LABEL_BY_HREF: Record<string, string> = Object.fromEntries(
  [HOME_NAV, ...NAV_GROUPS.flatMap((group) => group.items)].map((item) => [item.href, item.label]),
);

export function navLabelFor(href: string): string | null {
  return NAV_LABEL_BY_HREF[href] ?? null;
}

export function activeNavHref(pathname: string): string | null {
  if (ALL_NAV_HREFS.includes(pathname)) return pathname;
  if (pathname.startsWith("/sources/")) return "/sources/list";
  let best: string | null = null;
  for (const href of ALL_NAV_HREFS) {
    if (href === "/") continue;
    if (pathname === href || pathname.startsWith(`${href}/`)) {
      if (!best || href.length > best.length) best = href;
    }
  }
  return best;
}

export function normalizePath(slug: string[] | undefined): string {
  if (!slug || slug.length === 0) return "/";
  return `/${slug.map((part) => part.trim()).filter(Boolean).join("/")}`;
}

export function missingApis(screen: ManifestScreen): ManifestApi[] {
  return screen.apis.filter((api) => api.status === "missing");
}

export function existingApis(screen: ManifestScreen): ManifestApi[] {
  return screen.apis.filter((api) => api.status === "existing");
}
