"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import Sidebar from "./Sidebar";
import SalesDemoDrawer from "./SalesDemoDrawer";
import { getBrowserSessionState } from "../../lib/session";
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
  const router = useRouter();
  // Least privilege until the session role is known (avoids an admin-nav / admin-screen flash on load).
  const [roles, setRoles] = useState<WorkspaceRole[] | null>(null);
  const [salesDemo, setSalesDemo] = useState<{ enabled: boolean; displayName: string }>({
    displayName: "",
    enabled: false,
  });
  // Mobile only: the sidebar is an off-canvas drawer; this toggles it. Desktop CSS ignores `nav-open`.
  const [navOpen, setNavOpen] = useState(false);
  const [salesDrawerOpen, setSalesDrawerOpen] = useState(false);
  const navToggleRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let active = true;
    if (AUTH_ROUTES.has(pathname)) {
      setRoles(null);
      setSalesDemo({ displayName: "", enabled: false });
      return () => {
        active = false;
      };
    }
    getBrowserSessionState()
      .then((session) => {
        if (!active) return;
        if (session.isCognito && !session.isAuthenticated) {
          router.replace(`/login?return_to=${encodeURIComponent(pathname)}`);
          return;
        }
        setRoles(session.roles.length ? session.roles : rolesForUser(session.userId));
        setSalesDemo({
          displayName: session.displayName || session.userId,
          enabled: session.isSalesDemo,
        });
      })
      .catch(() => {
        if (active) router.replace(`/login?return_to=${encodeURIComponent(pathname)}`);
      });
    return () => {
      active = false;
    };
  }, [pathname, router]);

  // Close the drawer whenever the route changes so a nav tap doesn't leave it open over the new screen.
  useEffect(() => {
    setNavOpen(false);
    setSalesDrawerOpen(false);
  }, [pathname]);

  // Mobile off-canvas drawer a11y: Escape closes it, focus moves into the nav on open and
  // returns to the toggle on close. navOpen is only ever true on mobile (the toggle is
  // display:none on desktop), so this stays inert for the always-visible desktop sidebar.
  useEffect(() => {
    if (!navOpen) return;
    const sidebar = document.getElementById("workspace-sidebar");
    (sidebar?.querySelector<HTMLElement>('a[href], button:not([disabled])') ?? sidebar)?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setNavOpen(false);
    }
    document.addEventListener("keydown", onKey);
    const trigger = navToggleRef.current;
    return () => {
      document.removeEventListener("keydown", onKey);
      trigger?.focus();
    };
  }, [navOpen]);

  if (AUTH_ROUTES.has(pathname)) {
    return <>{children}</>;
  }

  // roles === null -> not resolved yet; withhold the screen rather than optimistically render an
  // unauthorized one. Once resolved, show the screen or the access-denied panel.
  const decided = roles !== null;
  const allowed = decided && navAllowed(pathname, roles);

  return (
    <div className={`app-shell${navOpen ? " nav-open" : ""}`}>
      {/* Mobile-only header: gives the drawer a launch point when the sidebar is off-canvas. */}
      <header className="mobile-topbar">
        <button
          ref={navToggleRef}
          type="button"
          className="mobile-nav-toggle"
          aria-label={navOpen ? "メニューを閉じる" : "メニューを開く"}
          aria-expanded={navOpen}
          aria-controls="workspace-sidebar"
          onClick={() => setNavOpen(true)}
        >
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
            <path d="M4 6h16M4 12h16M4 18h16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </button>
        <span className="mobile-topbar-title">Raku RAG</span>
      </header>

      <Sidebar />
      {/* Scrim closes the drawer on outside tap; only interactive while open (CSS gates pointer events). */}
      <button
        type="button"
        className="nav-scrim"
        aria-label="メニューを閉じる"
        tabIndex={navOpen ? 0 : -1}
        onClick={() => setNavOpen(false)}
      />
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
      {salesDemo.enabled && (
        <SalesDemoDrawer
          displayName={salesDemo.displayName}
          open={salesDrawerOpen}
          onClose={() => setSalesDrawerOpen(false)}
          onToggle={() => setSalesDrawerOpen((open) => !open)}
        />
      )}
    </div>
  );
}
