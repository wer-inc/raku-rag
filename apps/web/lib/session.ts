// Browser session boundary. Production stores the Cognito Hosted UI token from the PKCE callback;
// local/demo mode mints the HMAC dev-token used by the deterministic stack.

export const DEMO_TENANT = process.env.NEXT_PUBLIC_DEMO_TENANT_ID ?? "demo";
export const DEMO_USER = process.env.NEXT_PUBLIC_DEMO_USER_ID ?? "alice";
export const DEMO_COLLECTION = process.env.NEXT_PUBLIC_DEMO_COLLECTION_ID ?? "manuals";

const STORAGE_KEY = "raku.devtoken";
const USER_KEY = "raku.devuser";
const COLLECTION_KEY = "raku.answerCollection";
const COGNITO_ID_TOKEN_KEY = "raku.cognito.id_token";
const COGNITO_ACCESS_TOKEN_KEY = "raku.cognito.access_token";
const COGNITO_STATE_KEY = "raku.cognito.pkce.state";
const COGNITO_VERIFIER_KEY = "raku.cognito.pkce.verifier";

interface AuthConfig {
  auth_mode: string;
  cognito_domain: string;
  cognito_client_id: string;
  cognito_issuer: string;
}

let authConfigPromise: Promise<AuthConfig> | null = null;

function normalizeDomain(raw: string): string {
  if (!raw.trim()) return "";
  return raw.startsWith("https://") || raw.startsWith("http://")
    ? raw.replace(/\/+$/, "")
    : `https://${raw.replace(/\/+$/, "")}`;
}

function staticAuthConfig(): AuthConfig {
  return {
    auth_mode: process.env.NEXT_PUBLIC_RAKU_AUTH_MODE ?? "",
    cognito_domain: normalizeDomain(process.env.NEXT_PUBLIC_COGNITO_DOMAIN ?? ""),
    cognito_client_id: process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID ?? "",
    cognito_issuer: process.env.NEXT_PUBLIC_COGNITO_ISSUER ?? "",
  };
}

async function loadAuthConfig(): Promise<AuthConfig> {
  const staticConfig = staticAuthConfig();
  if (staticConfig.cognito_domain && staticConfig.cognito_client_id) {
    return staticConfig;
  }
  if (typeof window === "undefined") return staticConfig;
  if (!authConfigPromise) {
    authConfigPromise = fetch("/api/auth-config", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : {}))
      .then((raw: unknown) => {
        const body = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
        return {
          auth_mode: typeof body.auth_mode === "string" ? body.auth_mode : "",
          cognito_domain: normalizeDomain(
            typeof body.cognito_domain === "string" ? body.cognito_domain : "",
          ),
          cognito_client_id:
            typeof body.cognito_client_id === "string" ? body.cognito_client_id : "",
          cognito_issuer: typeof body.cognito_issuer === "string" ? body.cognito_issuer : "",
        };
      })
      .catch(() => staticConfig);
  }
  return authConfigPromise;
}

export function isCognitoConfigured(): boolean {
  const config = staticAuthConfig();
  return config.auth_mode === "cognito" && Boolean(config.cognito_domain && config.cognito_client_id);
}

function callbackUrl(): string {
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/oauth/cognito/callback`;
}

function base64url(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return base64url(bytes);
}

async function sha256Base64Url(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return base64url(new Uint8Array(digest));
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const [, payload] = token.split(".");
    if (!payload) return null;
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
    return JSON.parse(atob(padded)) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function unexpiredJwt(token: string): boolean {
  const payload = decodeJwtPayload(token);
  const exp = payload?.exp;
  return typeof exp !== "number" || exp > Math.floor(Date.now() / 1000) + 30;
}

function loadCognitoToken(): string | null {
  if (typeof window === "undefined") return null;
  const idToken = window.sessionStorage.getItem(COGNITO_ID_TOKEN_KEY);
  if (idToken && unexpiredJwt(idToken)) return idToken;
  const accessToken = window.sessionStorage.getItem(COGNITO_ACCESS_TOKEN_KEY);
  if (accessToken && unexpiredJwt(accessToken)) return accessToken;
  return null;
}

export async function startCognitoLogin(): Promise<boolean> {
  const config = await loadAuthConfig();
  if (
    typeof window === "undefined" ||
    config.auth_mode !== "cognito" ||
    !config.cognito_domain ||
    !config.cognito_client_id
  ) {
    return false;
  }
  const verifier = randomString(32);
  const state = randomString(24);
  window.sessionStorage.setItem(COGNITO_VERIFIER_KEY, verifier);
  window.sessionStorage.setItem(COGNITO_STATE_KEY, state);
  const params = new URLSearchParams({
    client_id: config.cognito_client_id,
    code_challenge: await sha256Base64Url(verifier),
    code_challenge_method: "S256",
    redirect_uri: callbackUrl(),
    response_type: "code",
    scope: "openid email profile",
    state,
  });
  window.location.assign(`${config.cognito_domain}/oauth2/authorize?${params.toString()}`);
  return true;
}

export async function finishCognitoLogin(code: string, state: string): Promise<void> {
  const config = await loadAuthConfig();
  if (typeof window === "undefined" || !config.cognito_domain || !config.cognito_client_id) {
    throw new Error("Cognito is not configured");
  }
  const expectedState = window.sessionStorage.getItem(COGNITO_STATE_KEY);
  const verifier = window.sessionStorage.getItem(COGNITO_VERIFIER_KEY);
  window.sessionStorage.removeItem(COGNITO_STATE_KEY);
  window.sessionStorage.removeItem(COGNITO_VERIFIER_KEY);
  if (!expectedState || expectedState !== state || !verifier) {
    throw new Error("invalid Cognito login state");
  }
  const body = new URLSearchParams({
    client_id: config.cognito_client_id,
    code,
    code_verifier: verifier,
    grant_type: "authorization_code",
    redirect_uri: callbackUrl(),
  });
  const res = await fetch(`${config.cognito_domain}/oauth2/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body,
  });
  const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (!res.ok || typeof payload.id_token !== "string") {
    throw new Error(typeof payload.error === "string" ? payload.error : "Cognito token exchange failed");
  }
  window.sessionStorage.setItem(COGNITO_ID_TOKEN_KEY, payload.id_token);
  if (typeof payload.access_token === "string") {
    window.sessionStorage.setItem(COGNITO_ACCESS_TOKEN_KEY, payload.access_token);
  }
  const claims = decodeJwtPayload(payload.id_token);
  const user = typeof claims?.email === "string" ? claims.email : typeof claims?.sub === "string" ? claims.sub : "";
  if (user) {
    window.sessionStorage.setItem(USER_KEY, user);
  }
}

/** Last selected answer/search collection in the browser (defaults to DEMO_COLLECTION). */
export function loadAnswerCollection(): string {
  if (typeof window === "undefined") return DEMO_COLLECTION;
  const cached = window.localStorage.getItem(COLLECTION_KEY);
  return cached?.trim() || DEMO_COLLECTION;
}

export function saveAnswerCollection(collectionId: string): void {
  if (typeof window === "undefined") return;
  const trimmed = collectionId.trim();
  if (!trimmed) return;
  try {
    window.localStorage.setItem(COLLECTION_KEY, trimmed);
  } catch {
    /* best-effort */
  }
}

let inflight: Promise<string> | null = null;

async function mint(tenantId: string, userId: string): Promise<string> {
  const res = await fetch("/api/dev-token", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ tenant_id: tenantId, user_id: userId, groups: [], roles: [] }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok || typeof body.token !== "string") {
    throw new Error(typeof body.error === "string" ? body.error : "failed to create session");
  }
  return body.token;
}

/** Return a cached dev-token for the demo identity, minting (once) if needed. */
export async function getSessionToken(
  tenantId: string = DEMO_TENANT,
  userId: string = loadSessionUserId() ?? DEMO_USER,
): Promise<string> {
  const cognitoToken = loadCognitoToken();
  if (cognitoToken) return cognitoToken;
  const authConfig = await loadAuthConfig();
  if (authConfig.auth_mode === "cognito" && authConfig.cognito_domain && authConfig.cognito_client_id) {
    throw new Error("Cognito session is missing; sign in again");
  }
  if (typeof window !== "undefined") {
    const cached = window.sessionStorage.getItem(STORAGE_KEY);
    const cachedUser = window.sessionStorage.getItem(USER_KEY);
    if (cached && cachedUser === userId) return cached;
  }
  if (!inflight) {
    inflight = mint(tenantId, userId)
      .then((token) => {
        if (typeof window !== "undefined") {
          window.sessionStorage.setItem(STORAGE_KEY, token);
          window.sessionStorage.setItem(USER_KEY, userId);
        }
        return token;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

export function loadSessionUserId(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(USER_KEY);
}

export function saveSessionUserId(userId: string): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(USER_KEY, userId.trim());
}

/** Forget the cached token (e.g. on auth failure) so the next call re-mints. */
export function clearSessionToken(): void {
  if (typeof window !== "undefined") {
    window.sessionStorage.removeItem(STORAGE_KEY);
    window.sessionStorage.removeItem(USER_KEY);
    window.sessionStorage.removeItem(COGNITO_ID_TOKEN_KEY);
    window.sessionStorage.removeItem(COGNITO_ACCESS_TOKEN_KEY);
    window.sessionStorage.removeItem(COGNITO_STATE_KEY);
    window.sessionStorage.removeItem(COGNITO_VERIFIER_KEY);
  }
}

/**
 * Mint a fresh (uncached) dev-token for an arbitrary identity — used by the
 * permission simulator to run a query AS another user and prove ACL isolation.
 * Roles are assigned authoritatively server-side by the issuer (never the body).
 */
export async function mintTokenFor(tenantId: string, userId: string): Promise<string> {
  return mint(tenantId, userId);
}
