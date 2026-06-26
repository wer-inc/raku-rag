"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  completeCognitoNewPassword,
  getBrowserSessionState,
  signInWithCognitoPassword,
} from "../../lib/session";

interface LoginViewState {
  authMode: string;
  configured: boolean;
  error: string | null;
  loading: boolean;
}

function returnTo(): string {
  if (typeof window === "undefined") return "/home";
  const value = new URLSearchParams(window.location.search).get("return_to") ?? "/home";
  return value.startsWith("/") && !value.startsWith("//") ? value : "/home";
}

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [challengeSession, setChallengeSession] = useState("");
  const [challengeUsername, setChallengeUsername] = useState("");
  const [state, setState] = useState<LoginViewState>({
    authMode: "loading",
    configured: false,
    error: null,
    loading: true,
  });

  useEffect(() => {
    let active = true;
    getBrowserSessionState()
      .then((session) => {
        if (!active) return;
        if (session.isCognito && session.isAuthenticated) {
          router.replace(returnTo());
          return;
        }
        setState({
          authMode: session.authMode,
          configured: session.isConfigured,
          error: null,
          loading: false,
        });
      })
      .catch((err) => {
        if (!active) return;
        setState({
          authMode: "unknown",
          configured: false,
          error: err instanceof Error ? err.message : "認証設定を読み込めませんでした",
          loading: false,
        });
      });
    return () => {
      active = false;
    };
  }, [router]);

  const signIn = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setState((current) => ({ ...current, error: null, loading: true }));
    const login = challengeSession
      ? completeCognitoNewPassword(email, newPassword, challengeSession, challengeUsername)
      : signInWithCognitoPassword(email, password);
    void login
      .then((result) => {
        if (result.status === "new_password_required") {
          setChallengeSession(result.session);
          setChallengeUsername(result.username);
          setPassword("");
          setState((current) => ({ ...current, loading: false }));
          return;
        }
        router.replace(returnTo());
      })
      .catch((err) => {
        setState((current) => ({
          ...current,
          error: err instanceof Error ? err.message : "ログインに失敗しました",
          loading: false,
        }));
      });
  };

  const isCognito = state.authMode === "cognito";
  const primaryLabel = state.loading ? "確認中..." : challengeSession ? "新しいパスワードを設定" : "ログイン";

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
          <div className="auth-panel-head">
            <h2>ログイン</h2>
            <p className="auth-subtle">
              {isCognito
                ? "発行済みのアカウントでワークスペースに入ります。"
                : "組織とユーザーを選んでワークスペースに入ります。"}
            </p>
          </div>
          {state.error && <p className="auth-alert">{state.error}</p>}
          {isCognito && !state.configured && !state.loading && (
            <p className="auth-alert">ログイン設定が完了していません。管理者に確認してください。</p>
          )}
          {isCognito ? (
            <form className="auth-form-grid" onSubmit={signIn}>
              <label>
                <span>メールアドレス</span>
                <input
                  autoComplete="email"
                  inputMode="email"
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="name@example.com"
                  required
                  type="email"
                  value={email}
                />
              </label>
              {!challengeSession && (
                <label>
                  <span>パスワード</span>
                  <input
                    autoComplete="current-password"
                    onChange={(event) => setPassword(event.target.value)}
                    required
                    type="password"
                    value={password}
                  />
                </label>
              )}
              {challengeSession && (
                <label>
                  <span>新しいパスワード</span>
                  <input
                    autoComplete="new-password"
                    onChange={(event) => setNewPassword(event.target.value)}
                    required
                    type="password"
                    value={newPassword}
                  />
                </label>
              )}
              <div className="auth-login-actions">
                <button
                  className="auth-primary"
                  type="submit"
                  disabled={state.loading || !state.configured}
                >
                  {primaryLabel}
                </button>
              </div>
            </form>
          ) : (
            <div className="auth-login-actions">
              <button className="auth-primary" type="button" onClick={() => router.push("/orgselect")} disabled={state.loading}>
                {state.loading ? "確認中..." : "ワークスペースに入る"}
              </button>
            </div>
          )}
          {!isCognito && (
            <button className="auth-secondary" type="button" onClick={() => router.push("/orgselect")}>
              組織を選択
            </button>
          )}
          <p className="auth-note">ログイン情報が不明な場合は管理者にお問い合わせください。</p>
        </div>
      </section>
    </div>
  );
}
