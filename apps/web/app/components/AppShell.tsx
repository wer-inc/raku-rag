"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import Sidebar from "./Sidebar";
import { loadSessionUserId } from "../../lib/session";
import { navAllowed, rolesForUser, type WorkspaceRole } from "../../lib/nav-rbac";

const AUTH_ROUTES = new Set(["/login", "/orgselect", "/onboarding"]);

// B3: role-based navigation must hide unauthorized screens from the UI, not just from the sidebar —
// a field_user typing /admin/users must not get the admin screen. The sidebar already filters its
// links by role (filterNavGroups); this guards direct-URL / deep-link access at the single chokepoint
// every workspace screen passes through. (The API independently enforces server-side, e.g.
// assertAdminMutationAllowed — this is the matching UI half, not the security boundary.)
function AccessDenied({ pathname }: { pathname: string }) {
  return (
    <section className="workspace" aria-label="Access denied">
      <header className="topbar">
        <div>
          <p className="eyebrow">権限</p>
          <h2>この画面を表示する権限がありません</h2>
        </div>
      </header>
      <p className="ops-empty">
        現在のロールでは <code>{pathname}</code> にアクセスできません。
        <Link href="/home"> ホームへ戻る</Link>。
      </p>
    </section>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  // Least privilege until the session role is known (avoids an admin-nav / admin-screen flash on load).
  const [roles, setRoles] = useState<WorkspaceRole[] | null>(null);

  useEffect(() => {
    const uid = loadSessionUserId() ?? "misaki";
    setRoles(rolesForUser(uid));
  }, []);

  if (AUTH_ROUTES.has(pathname)) {
    return <>{children}</>;
  }

  // roles === null -> not resolved yet; withhold the screen rather than optimistically render an
  // unauthorized one. Once resolved, show the screen or the access-denied panel.
  const decided = roles !== null;
  const allowed = decided && navAllowed(pathname, roles);

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-main">
        {!decided ? (
          <p className="ops-empty" aria-busy="true">
            読み込み中…
          </p>
        ) : allowed ? (
          children
        ) : (
          <AccessDenied pathname={pathname} />
        )}
      </div>
    </div>
  );
}
