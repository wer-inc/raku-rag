"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { finishCognitoLogin } from "../../../../lib/session";

export default function CognitoCallbackPage() {
  const params = useSearchParams();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = params.get("code");
    const state = params.get("state");
    const oauthError = params.get("error");
    if (oauthError) {
      setError(oauthError);
      return;
    }
    if (!code || !state) {
      setError("missing Cognito callback parameters");
      return;
    }
    finishCognitoLogin(code, state)
      .then((next) => router.replace(next))
      .catch((err) => setError(err instanceof Error ? err.message : "Cognito login failed"));
  }, [params, router]);

  return (
    <section className="auth-page">
      <div className="auth-card">
        <h2>サインイン</h2>
        <p className="auth-subtle">{error ? `ログインに失敗しました: ${error}` : "認証を完了しています..."}</p>
      </div>
    </section>
  );
}
