"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  activeNavHref,
  HOME_NAV,
  type NavGroup,
  type NavIconName,
  type NavItem,
  WORKSPACE_IDENTITY,
} from "../../lib/full-saas";
import {
  filterNavGroups,
  homeNavVisible,
  primaryRole,
  roleLabel,
  userDisplayName,
  type WorkspaceRole,
} from "../../lib/nav-rbac";
import { manufacturingListDrafts } from "../../lib/api-client";
import { getBrowserSessionState, getSessionToken, startCognitoLogout } from "../../lib/session";

const ICON_PATHS: Record<NavIconName | "orgswitch" | "signout", string> = {
  home: '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>',
  answers: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="m9 10 2 2 4-4"/>',
  chatbot: '<path d="M7 8h10"/><path d="M7 12h7"/><path d="M12 20H7l-4 3v-4a4 4 0 0 1-1-3V7a4 4 0 0 1 4-4h12a4 4 0 0 1 4 4v7a4 4 0 0 1-4 4h-3l-3 2Z"/><path d="M17 12h.01"/>',
  phone: '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>',
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

// U8: a nav group. Groups marked defaultCollapsed (運用/管理) start closed so the sidebar stays
// scannable, and auto-open whenever the active route lives inside them (deep links included).
function NavGroupSection({
  group,
  active,
  reviewCount,
}: {
  group: NavGroup;
  active: string | null;
  reviewCount: number | null;
}) {
  const containsActive = group.items.some((item) => item.href === active);
  const [open, setOpen] = useState(!group.defaultCollapsed || containsActive);

  useEffect(() => {
    if (containsActive) setOpen(true);
  }, [containsActive]);

  if (!group.defaultCollapsed) {
    return (
      <div className="sidebar-group">
        <p className="sidebar-group-label">{group.label}</p>
        {group.items.map((item) => (
          <NavLink key={item.href} item={item} active={active === item.href} reviewCount={reviewCount} />
        ))}
      </div>
    );
  }

  const sectionId = `sidebar-group-${group.label}`;
  return (
    <div className="sidebar-group">
      <button
        type="button"
        className="sidebar-group-toggle"
        aria-expanded={open}
        aria-controls={sectionId}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="sidebar-group-label">{group.label}</span>
        <svg
          className={`sidebar-group-chevron${open ? " open" : ""}`}
          viewBox="0 0 24 24"
          width={12}
          height={12}
          aria-hidden="true"
        >
          <path d="m9 6 6 6-6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <div id={sectionId} hidden={!open}>
        {group.items.map((item) => (
          <NavLink key={item.href} item={item} active={active === item.href} reviewCount={reviewCount} />
        ))}
      </div>
    </div>
  );
}

function NavLink({
  item,
  active,
  reviewCount = null,
}: {
  item: NavItem;
  active: boolean;
  /** U18: live pending-review draft count (null = unknown/fetch failed → badge hidden). */
  reviewCount?: number | null;
}) {
  return (
    <Link
      href={item.href}
      className={`sidebar-nav-item ${active ? "active" : ""}`}
      aria-current={active ? "page" : undefined}
    >
      <NavIcon name={item.icon} />
      <span className="sidebar-nav-label">{item.label}</span>
      {item.badge === "review" && reviewCount !== null && reviewCount > 0 && (
        <span className="sidebar-nav-badge" aria-label={`未レビュー ${reviewCount} 件`}>
          {reviewCount}
        </span>
      )}
    </Link>
  );
}

export default function Sidebar() {
  const pathname = usePathname() ?? "/";
  const router = useRouter();
  const active = activeNavHref(pathname);
  const [userId, setUserId] = useState(DEMO_USER_FALLBACK);
  const [displayName, setDisplayName] = useState(userDisplayName(DEMO_USER_FALLBACK));
  // Least privilege until the browser session resolves the real role (avoids an admin-nav flash on load).
  const [roles, setRoles] = useState<WorkspaceRole[]>(["field_user"]);

  useEffect(() => {
    let active = true;
    getBrowserSessionState()
      .then((session) => {
        if (!active) return;
        setUserId(session.userId);
        setDisplayName(session.displayName || userDisplayName(session.userId));
        setRoles(session.roles.length ? session.roles : ["field_user"]);
      })
      .catch(() => {
        if (active) {
          setUserId(DEMO_USER_FALLBACK);
          setDisplayName(userDisplayName(DEMO_USER_FALLBACK));
          setRoles(["field_user"]);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const groups = filterNavGroups(roles);
  const showHome = homeNavVisible(roles);
  const displayRole = roleLabel(primaryRole(roles));

  // U18: real review badge — pending drafts (status draft/in_review) from the existing drafts API.
  // Fetched once on mount and again when the route enters/leaves /reviews (no polling); on error the
  // badge is hidden (null) rather than showing a stale or fake number.
  const [reviewCount, setReviewCount] = useState<number | null>(null);
  const hasReviewBadgeNav = groups.some((group) => group.items.some((item) => item.badge === "review"));
  const inReviews = pathname.startsWith("/reviews");
  useEffect(() => {
    if (!hasReviewBadgeNav) {
      setReviewCount(null);
      return;
    }
    let cancelled = false;
    void getSessionToken()
      .then((token) => manufacturingListDrafts(token))
      .then((drafts) => {
        if (cancelled) return;
        setReviewCount(drafts.filter((d) => d.status === "draft" || d.status === "in_review").length);
      })
      .catch(() => {
        if (!cancelled) setReviewCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, [hasReviewBadgeNav, inReviews]);

  function onSignOut() {
    void startCognitoLogout().then((started) => {
      if (!started) router.push("/login");
    });
  }

  return (
    <aside id="workspace-sidebar" className="sidebar" aria-label="Workspace" tabIndex={-1}>
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
        {showHome && <NavLink item={HOME_NAV} active={active === HOME_NAV.href} />}
        {groups.map((group) => (
          <NavGroupSection key={group.label} group={group} active={active} reviewCount={reviewCount} />
        ))}
      </nav>

      <div className="sidebar-foot">
        <span className="sidebar-foot-avatar" aria-hidden="true">
          {displayName.slice(0, 1)}
        </span>
        <span className="sidebar-foot-copy">
          <span className="sidebar-foot-name">{displayName}</span>
          <span className="sidebar-foot-role">{displayRole}</span>
        </span>
        <button
          type="button"
          className="sidebar-foot-signout"
          aria-label="サインアウト"
          title="サインアウト"
          onClick={onSignOut}
        >
          <NavIcon name="signout" size={17} />
        </button>
      </div>
    </aside>
  );
}

const DEMO_USER_FALLBACK = "misaki";
