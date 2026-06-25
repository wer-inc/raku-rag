"use client";

import { useEffect, useState } from "react";
import { apiPostJson } from "../../../../lib/api-client";
import { getSessionToken } from "../../../../lib/session";

/**
 * Google OAuth callback (021-gdrive). Google redirects here with ?code&state.
 *
 * Runs client-side so it can use the browser session token to call the authenticated API. Validates
 * state against the sessionStorage nonce set when the flow started, exchanges the code via the API
 * (which relays to the answer-service), then hands the connection_id back to the opener via
 * postMessage and closes the popup. Falls back to a redirect when opened directly (no opener).
 */
const STATE_KEY = "raku.gdrive.oauth.state";
const MESSAGE_SOURCE = "raku-gdrive-oauth";

interface CallbackResult {
  connection_id: string;
  refresh_token_stored: boolean;
}

export default function GoogleOAuthCallbackPage() {
  const [message, setMessage] = useState("Google 認証を処理しています…");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    const oauthError = params.get("error");
    const expected = window.sessionStorage.getItem(STATE_KEY);

    function finish(payload: { ok: boolean; connection_id?: string; error?: string }) {
      window.sessionStorage.removeItem(STATE_KEY);
      if (window.opener) {
        window.opener.postMessage({ source: MESSAGE_SOURCE, ...payload }, window.location.origin);
        setMessage(payload.ok ? "接続が完了しました。この画面は閉じて構いません。" : `接続に失敗しました: ${payload.error}`);
        window.setTimeout(() => window.close(), 800);
      } else {
        // Opened directly (no popup): stash the result and return to the app.
        if (payload.ok && payload.connection_id) {
          window.sessionStorage.setItem("raku.gdrive.connection_id", payload.connection_id);
        }
        setMessage(payload.ok ? "接続が完了しました。元の画面に戻ってください。" : `接続に失敗しました: ${payload.error}`);
      }
    }

    if (oauthError) {
      finish({ ok: false, error: oauthError });
      return;
    }
    if (!code || !state) {
      finish({ ok: false, error: "missing code/state" });
      return;
    }
    if (!expected || expected !== state) {
      // CSRF guard: the returned state must match the nonce we generated before redirecting.
      finish({ ok: false, error: "state mismatch (CSRF check failed)" });
      return;
    }

    const redirectUri = `${window.location.origin}/oauth/google/callback`;
    (async () => {
      try {
        const token = await getSessionToken();
        const result = await apiPostJson<CallbackResult>(
          "/oauth/google/callback",
          { code, state, redirect_uri: redirectUri },
          token,
        );
        finish({ ok: true, connection_id: result.connection_id });
      } catch (err) {
        finish({ ok: false, error: err instanceof Error ? err.message : "exchange failed" });
      }
    })();
  }, []);

  return (
    <main style={{ padding: "2rem", fontFamily: "system-ui, sans-serif" }}>
      <h1 style={{ fontSize: "1.1rem" }}>Google Drive 接続</h1>
      <p>{message}</p>
    </main>
  );
}
