"use client";

import { useRouter } from "next/navigation";

const ORGS = [
  { name: "東洋精機 第一工場", detail: "Enterprise · 312 ユーザー", mono: "東", color: "#5b5bd6", go: "/home" },
  { name: "東洋精機 第二工場", detail: "Enterprise · 98 ユーザー", mono: "東", color: "#0f766e", go: "/home" },
  { name: "東洋精機 R&D センター", detail: "Business · 41 ユーザー", mono: "R", color: "#b45309", go: "/onboarding" },
] as const;

export default function OrgSelectPage() {
  const router = useRouter();
  return (
    <div className="auth-center-page">
      <div className="auth-center-card auth-org-card">
        <div className="auth-brand-row auth-brand-row-dark">
          <div className="auth-mark" aria-hidden="true">
            <span />
          </div>
          <span className="auth-brand">Raku RAG</span>
        </div>
        <h1>組織を選択</h1>
        <p className="auth-subtle">田中 美咲 さんがアクセスできる組織です。</p>
        <div className="auth-org-list">
          {ORGS.map((org) => (
            <button key={org.name} type="button" className="auth-org-item" onClick={() => router.push(org.go)}>
              <div className="auth-org-badge" style={{ background: org.color }}>
                {org.mono}
              </div>
              <div className="auth-org-copy">
                <strong>{org.name}</strong>
                <span>{org.detail}</span>
              </div>
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                <path d="m9 18 6-6-6-6" fill="none" stroke="#c4c4c8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          ))}
        </div>
        <button className="auth-text-link" type="button" onClick={() => router.push("/login")}>
          別のアカウントでログイン
        </button>
      </div>
    </div>
  );
}
