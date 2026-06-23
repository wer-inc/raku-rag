"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  activeNavHref,
  HOME_NAV,
  NAV_GROUPS,
  REVIEW_BADGE_COUNT,
  WORKSPACE_IDENTITY,
  type NavIconName,
  type NavItem,
} from "../../lib/full-saas";
import { clearSessionToken } from "../../lib/session";

// Inline icon set transcribed from the standalone sidebar. Static,
// developer-authored SVG path data — no user input flows in here.
const ICON_PATHS: Record<NavIconName | "orgswitch" | "signout", string> = {
  home: '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>',
  answers: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="m9 10 2 2 4-4"/>',
  history: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  sources: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
  documents: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6M9 17h6"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  ingestion: '<path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/>',
  reviewqueue: '<path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="m9 14 2 2 4-4"/>',
  approvalsettings: '<path d="m9 11 3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
  operations: '<path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>',
  safety: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
  quality: '<path d="M3 3v18h18"/><rect x="7" y="11" width="3" height="7"/><rect x="12" y="7" width="3" height="11"/><rect x="17" y="4" width="3" height="14"/>',
  audit: '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/>',
  compliance: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><path d="M12 15V3"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  roles: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
  integrations: '<path d="M12 22v-5"/><path d="M9 8V2"/><path d="M15 8V2"/><path d="M18 8v4a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"/>',
  apikeys: '<circle cx="7.5" cy="15.5" r="4.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/>',
  billing: '<rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/>',
  support: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/><path d="m4.9 4.9 4.2 4.2M14.9 14.9l4.2 4.2M14.9 9.1l4.2-4.2M4.9 19.1l4.2-4.2"/>',
  provider: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2"/>',
  retrieval: '<path d="M12 2 2 7l10 5 10-5-10-5Z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
  logging: '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
  improvements: '<circle cx="12" cy="12" r="10"/><path d="m16 12-4-4-4 4"/><path d="M12 16V8"/>',
  orgswitch: '<path d="m7 15 5 5 5-5"/><path d="m7 9 5-5 5 5"/>',
  signout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
};

function NavIcon({ name, size = 18 }: { name: keyof typeof ICON_PATHS; size?: number }) {
  return (
    <svg
      className="sidebar-icon"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: ICON_PATHS[name] }}
    />
  );
}

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  return (
    <Link
      href={item.href}
      className={`sidebar-nav-item ${active ? "active" : ""}`}
      aria-current={active ? "page" : undefined}
    >
      <NavIcon name={item.icon} />
      <span className="sidebar-nav-label">{item.label}</span>
      {item.badge === "review" && REVIEW_BADGE_COUNT > 0 && (
        <span className="sidebar-nav-badge">{REVIEW_BADGE_COUNT}</span>
      )}
    </Link>
  );
}

export default function Sidebar() {
  const pathname = usePathname() ?? "/";
  const router = useRouter();
  const active = activeNavHref(pathname);

  function onSignOut() {
    clearSessionToken();
    router.push("/login");
  }

  return (
    <aside className="sidebar" aria-label="Workspace">
      <div className="sidebar-org">
        <Link href="/orgselect" className="sidebar-org-btn">
          <span className="sidebar-org-mark" aria-hidden="true">
            <span />
          </span>
          <span className="sidebar-org-copy">
            <span className="sidebar-org-name">{WORKSPACE_IDENTITY.orgName}</span>
            <span className="sidebar-org-sub">{WORKSPACE_IDENTITY.orgPlan}</span>
          </span>
          <NavIcon name="orgswitch" size={14} />
        </Link>
      </div>

      <nav className="sidebar-nav" aria-label="Primary">
        <NavLink item={HOME_NAV} active={active === HOME_NAV.href} />
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="sidebar-group">
            <p className="sidebar-group-label">{group.label}</p>
            {group.items.map((item) => (
              <NavLink key={item.href} item={item} active={active === item.href} />
            ))}
          </div>
        ))}
      </nav>

      <div className="sidebar-foot">
        <span className="sidebar-foot-avatar" aria-hidden="true">
          {WORKSPACE_IDENTITY.userInitial}
        </span>
        <span className="sidebar-foot-copy">
          <span className="sidebar-foot-name">{WORKSPACE_IDENTITY.userName}</span>
          <span className="sidebar-foot-role">{WORKSPACE_IDENTITY.userRole}</span>
        </span>
        <button type="button" className="sidebar-foot-signout" title="サインアウト" onClick={onSignOut}>
          <NavIcon name="signout" size={17} />
        </button>
      </div>
    </aside>
  );
}
