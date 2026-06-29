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

// Count shown on the AIドラフトレビュー nav badge (pending review drafts).
// Matches the workspace default; replace with a live count once
// `GET /v1/manufacturing/drafts` exists (see specs/full-saas/gaps.md).
export const REVIEW_BADGE_COUNT = 2;

export type NavIconName =
  | "home" | "answers" | "chatbot" | "history" | "sources" | "documents" | "search"
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

// Grouped navigation — order, labels, icons, and grouping mirror the
// standalone sidebar. Each href targets an existing workspace route.
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "回答",
    items: [
      { href: "/", label: "質問する", icon: "answers" },
      { href: "/chatbot", label: "チャットボット", icon: "chatbot" },
      { href: "/answers/history", label: "回答履歴", icon: "history" },
    ],
  },
  {
    label: "ナレッジ",
    items: [
      { href: "/sources/list", label: "ソース", icon: "sources" },
      { href: "/documents", label: "ドキュメント", icon: "documents" },
      { href: "/sources", label: "事例検索", icon: "search" },
      { href: "/ingestion-runs", label: "取込ラン", icon: "ingestion" },
    ],
  },
  {
    label: "レビュー",
    items: [
      { href: "/reviews", label: "AIドラフトレビュー", icon: "reviewqueue", badge: "review" },
      { href: "/reviews/documents", label: "根拠文書レビュー", icon: "documents" },
      { href: "/reviews/settings", label: "同期・承認ポリシー", icon: "approvalsettings" },
    ],
  },
  {
    label: "運用・監査",
    items: [
      { href: "/operations", label: "運用ダッシュボード", icon: "operations" },
      { href: "/operations/safety", label: "安全テレメトリ", icon: "safety" },
      { href: "/operations/quality", label: "品質・KPI", icon: "quality" },
      { href: "/operations/impact-report", label: "導入効果レポート", icon: "operations" },
      { href: "/operations/improvements", label: "ナレッジ改善", icon: "improvements" },
      { href: "/audit", label: "監査ログ", icon: "audit" },
      { href: "/compliance/export", label: "コンプラ出力", icon: "compliance" },
    ],
  },
  {
    label: "管理",
    items: [
      { href: "/admin/users", label: "ユーザー", icon: "users" },
      { href: "/admin/access", label: "ロール・権限", icon: "roles" },
      { href: "/admin/integrations", label: "連携", icon: "integrations" },
      { href: "/admin/api", label: "API・Webhook", icon: "apikeys" },
      { href: "/admin/billing", label: "利用・課金", icon: "billing" },
      { href: "/admin/support", label: "サポート", icon: "support" },
    ],
  },
  {
    label: "設定",
    items: [
      { href: "/admin/provider-policy", label: "プロバイダ", icon: "provider" },
      { href: "/admin/retrieval", label: "Retrieval", icon: "retrieval" },
      { href: "/admin/retrieval/debug", label: "検索診断", icon: "search" },
      { href: "/admin/logging-privacy", label: "ログ・プライバシー", icon: "logging" },
    ],
  },
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
