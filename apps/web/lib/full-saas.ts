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

// Temporarily keep the document approval workflow out of the main E2E path.
// Server-side safety gates and AI draft review rules still apply; this only changes product
// navigation/default ingest policy. Set NEXT_PUBLIC_RAKU_APPROVAL_WORKFLOW=on to restore the queue.
export const APPROVAL_WORKFLOW_ENABLED =
  (process.env.NEXT_PUBLIC_RAKU_APPROVAL_WORKFLOW ?? "off").trim().toLowerCase() === "on";

// Count shown on the AIドラフトレビュー nav badge (pending review drafts).
// Matches the workspace default; replace with a live count once
// `GET /v1/manufacturing/drafts` exists (see specs/full-saas/gaps.md).
export const REVIEW_BADGE_COUNT = APPROVAL_WORKFLOW_ENABLED ? 2 : 0;

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

// Grouped navigation — order, labels, icons, and grouping mirror the
// standalone sidebar. Each href targets an existing workspace route.
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
];

// All nav hrefs, used by the sidebar to resolve the single active item by
// longest-prefix match (so /sources/list wins over /sources, etc.).
export const ALL_NAV_HREFS: string[] = [
  HOME_NAV.href,
  ...NAV_GROUPS.flatMap((group) => group.items.map((item) => item.href)),
];

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
