"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import Sidebar from "./Sidebar";

const AUTH_ROUTES = new Set(["/login", "/orgselect", "/onboarding"]);

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  if (AUTH_ROUTES.has(pathname)) {
    return <>{children}</>;
  }

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-main">{children}</div>
    </div>
  );
}
