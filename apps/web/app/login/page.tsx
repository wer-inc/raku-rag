"use client";

import { useRouter } from "next/navigation";
import { isCognitoConfigured, startCognitoLogin } from "../../lib/session";

export default function LoginPage() {
  const router = useRouter();
  const signIn = () => {
    if (isCognitoConfigured()) {
      void startCognitoLogin();
      return;
    }
    void startCognitoLogin().then((started) => {
      if (!started) router.push("/orgselect");
    });
  };
  return (
    <div className="auth-page">
      <section className="auth-hero">
        <div className="auth-brand-row">
          <div className="auth-mark" aria-hidden="true">
            <span />
          </div>
          <span className="auth-brand">Raku RAG</span>
        </div>
        <div className="auth-hero-copy">
          <h1>
            現場の知識を、
            <br />
            承認済みのAI回答に。
          </h1>
          <p>
            製造手順・規格・トラブル事例を横断検索。安全分類と出典の有効期限つきで回答します。
          </p>
        </div>
        <div className="auth-hero-footer">© 2026 Raku RAG, Inc.</div>
      </section>

      <section className="auth-form-wrap">
        <div className="auth-card">
          <h2>サインイン</h2>
          <p className="auth-subtle">会社のメールアドレスでログインしてください。</p>
          <div className="auth-form-grid">
            <label>
              <span>メールアドレス</span>
              <input defaultValue="misaki@toyoseiki.co.jp" />
            </label>
            <label>
              <span>パスワード</span>
              <input type="password" defaultValue="passwordvalue" />
            </label>
            <button className="auth-primary" type="button" onClick={signIn}>
              ログイン
            </button>
          </div>
          <div className="auth-divider">
            <span>または</span>
          </div>
          <button className="auth-secondary" type="button" onClick={signIn}>
            <span className="auth-ms">M</span>
            Microsoft (SSO) で続ける
          </button>
          <p className="auth-note">SSO 必須のため新規登録は管理者が行います。</p>
        </div>
      </section>
    </div>
  );
}
