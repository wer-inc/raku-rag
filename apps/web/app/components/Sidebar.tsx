"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV: Array<{ href: string; label: string }> = [
  { href: "/", label: "Answers" },
  { href: "/sources", label: "Sources" },
  { href: "/reviews", label: "Reviews" },
  { href: "/operations", label: "Operations" },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function Sidebar() {
  const pathname = usePathname() ?? "/";
  return (
    <aside className="sidebar" aria-label="Workspace">
      <div>
        <p className="eyebrow">Raku RAG</p>
        <h1>Manufacturing Knowledge</h1>
      </div>
      <nav className="nav-list" aria-label="Primary">
        {NAV.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`nav-item ${active ? "active" : ""}`}
              aria-current={active ? "page" : undefined}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
