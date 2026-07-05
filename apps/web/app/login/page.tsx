"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  completeCognitoNewPassword,
  clearSessionToken,
  getBrowserSessionState,
  loadRememberLoginPreference,
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

function isReauthRequest(): boolean {
  if (typeof window === "undefined") return false;
  const params = new URLSearchParams(window.location.search);
  return params.get("reauth") === "1" || params.has("return_to");
}

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [rememberLogin, setRememberLogin] = useState(false);
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
    const reauth = isReauthRequest();
    setRememberLogin(loadRememberLoginPreference());
    if (reauth) clearSessionToken();
    getBrowserSessionState()
      .then((session) => {
        if (!active) return;
        if (!reauth && session.isCognito && session.isAuthenticated) {
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
    const rememberInput = event.currentTarget.elements.namedItem("remember_login");
    const remember =
      rememberInput instanceof HTMLInputElement ? rememberInput.checked : rememberLogin;
    setState((current) => ({ ...current, error: null, loading: true }));
    const login = challengeSession
      ? completeCognitoNewPassword(
          email,
          newPassword,
          challengeSession,
          challengeUsername,
          remember,
        )
      : signInWithCognitoPassword(email, password, remember);
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
          <ul className="auth-hero-points">
            <li className="auth-hero-point">
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="m4 12 5 5L20 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span>承認済みかつ有効な根拠だけを引用します。</span>
            </li>
            <li className="auth-hero-point">
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
              </svg>
              <span>安全分類で、高リスクな回答を保護します。</span>
            </li>
            <li className="auth-hero-point">
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" />
                <path d="M12 7v5l3 2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span>出典には有効期限。古い根拠は警告します。</span>
            </li>
          </ul>
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
          {state.error && (
            <p className="auth-alert" role="alert" id="login-error">
              {state.error}
            </p>
          )}
          {isCognito && !state.configured && !state.loading && (
            <p className="auth-alert" role="alert">
              ログイン設定が完了していません。管理者に確認してください。
            </p>
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
                  aria-invalid={state.error ? true : undefined}
                  aria-describedby={state.error ? "login-error" : undefined}
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
                    aria-invalid={state.error ? true : undefined}
                    aria-describedby={state.error ? "login-error" : undefined}
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
                    aria-invalid={state.error ? true : undefined}
                    aria-describedby={state.error ? "login-error" : undefined}
                  />
                </label>
              )}
              <label className="auth-remember">
                <input
                  checked={rememberLogin}
                  name="remember_login"
                  onChange={(event) => setRememberLogin(event.target.checked)}
                  type="checkbox"
                  aria-describedby="remember-login-note"
                />
                <span className="auth-remember-copy">
                  <span className="auth-remember-title">ログインを保持する</span>
                  <span className="auth-remember-note" id="remember-login-note">
                    共有端末ではオフにしてください。
                  </span>
                </span>
              </label>
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
