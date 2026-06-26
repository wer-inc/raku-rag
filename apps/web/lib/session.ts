// Browser session boundary. Production stores the Cognito token from Hosted UI or password login;
// local/demo mode mints the HMAC dev-token used by the deterministic stack.

import { normalizeWorkspaceRoles, rolesForUser, type WorkspaceRole } from "./nav-rbac";

export const DEMO_TENANT = process.env.NEXT_PUBLIC_DEMO_TENANT_ID ?? "demo";
export const DEMO_USER = process.env.NEXT_PUBLIC_DEMO_USER_ID ?? "alice";
export const DEMO_COLLECTION = process.env.NEXT_PUBLIC_DEMO_COLLECTION_ID ?? "manuals";

const STORAGE_KEY = "raku.devtoken";
const USER_KEY = "raku.devuser";
const TENANT_KEY = "raku.session.tenant";
const ROLES_KEY = "raku.session.roles";
const DISPLAY_NAME_KEY = "raku.session.display_name";
const COLLECTION_KEY = "raku.answerCollection";
const COGNITO_ID_TOKEN_KEY = "raku.cognito.id_token";
const COGNITO_ACCESS_TOKEN_KEY = "raku.cognito.access_token";
const COGNITO_STATE_KEY = "raku.cognito.pkce.state";
const COGNITO_VERIFIER_KEY = "raku.cognito.pkce.verifier";
const COGNITO_RETURN_TO_KEY = "raku.cognito.return_to";

export interface AuthConfig {
  auth_mode: string;
  cognito_domain: string;
  cognito_client_id: string;
  cognito_issuer: string;
}

export interface BrowserSessionState {
  authMode: string;
  isCognito: boolean;
  isAuthenticated: boolean;
  isConfigured: boolean;
  isSalesDemo: boolean;
  tenantId: string;
  userId: string;
  displayName: string;
  roles: WorkspaceRole[];
}

export type CognitoPasswordLoginResult =
  | { status: "authenticated" }
  | { status: "new_password_required"; session: string; username: string };

let authConfigPromise: Promise<AuthConfig> | null = null;

function normalizeDomain(raw: string): string {
  if (!raw.trim()) return "";
  return raw.startsWith("https://") || raw.startsWith("http://")
    ? raw.replace(/\/+$/, "")
    : `https://${raw.replace(/\/+$/, "")}`;
}

function staticAuthConfig(): AuthConfig {
  return {
    auth_mode: (process.env.NEXT_PUBLIC_RAKU_AUTH_MODE ?? "").trim().toLowerCase(),
    cognito_domain: normalizeDomain(process.env.NEXT_PUBLIC_COGNITO_DOMAIN ?? ""),
    cognito_client_id: process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID ?? "",
    cognito_issuer: process.env.NEXT_PUBLIC_COGNITO_ISSUER ?? "",
  };
}

async function loadAuthConfig(): Promise<AuthConfig> {
  const staticConfig = staticAuthConfig();
  if (
    staticConfig.auth_mode === "cognito" &&
    staticConfig.cognito_domain &&
    staticConfig.cognito_client_id
  ) {
    return staticConfig;
  }
  if (typeof window === "undefined") return staticConfig;
  if (!authConfigPromise) {
    authConfigPromise = fetch("/api/auth-config", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : {}))
      .then((raw: unknown) => {
        const body = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
        return {
          auth_mode:
            typeof body.auth_mode === "string" ? body.auth_mode.trim().toLowerCase() : "",
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

export function resetAuthConfigCache(): void {
  authConfigPromise = null;
}

export async function getAuthConfig(): Promise<AuthConfig> {
  return loadAuthConfig();
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

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function claimString(claims: Record<string, unknown> | null, key: string): string {
  const value = claims?.[key];
  return typeof value === "string" ? value.trim() : "";
}

function rolesFromClaims(claims: Record<string, unknown> | null): WorkspaceRole[] {
  return normalizeWorkspaceRoles([
    ...stringArray(claims?.["cognito:groups"]),
    ...stringArray(claims?.roles),
    ...stringArray(claims?.groups),
  ]);
}

function userFromClaims(claims: Record<string, unknown> | null): string {
  return claimString(claims, "email") || claimString(claims, "username") || claimString(claims, "sub");
}

function displayNameFromClaims(claims: Record<string, unknown> | null): string {
  return claimString(claims, "name") || userFromClaims(claims);
}

function tenantFromClaims(claims: Record<string, unknown> | null): string {
  return claimString(claims, "custom:tenant_id") || claimString(claims, "tenant_id") || DEMO_TENANT;
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

function safeReturnTo(value: string | null | undefined): string {
  const candidate = (value ?? "").trim();
  if (!candidate || !candidate.startsWith("/") || candidate.startsWith("//")) {
    return "/home";
  }
  if (candidate.startsWith("/login") || candidate.startsWith("/oauth/")) {
    return "/home";
  }
  return candidate;
}

function storeCognitoTokens(idToken: string, accessToken = ""): void {
  if (typeof window === "undefined" || !idToken) return;
  window.sessionStorage.setItem(COGNITO_ID_TOKEN_KEY, idToken);
  if (accessToken) {
    window.sessionStorage.setItem(COGNITO_ACCESS_TOKEN_KEY, accessToken);
  }
  const claims = decodeJwtPayload(idToken);
  const user = userFromClaims(claims);
  if (user) {
    window.sessionStorage.setItem(USER_KEY, user);
  }
  window.sessionStorage.setItem(TENANT_KEY, tenantFromClaims(claims));
  window.sessionStorage.setItem(DISPLAY_NAME_KEY, displayNameFromClaims(claims));
  window.sessionStorage.setItem(ROLES_KEY, JSON.stringify(rolesFromClaims(claims)));
}

export async function startCognitoLogin(returnTo = "/home"): Promise<boolean> {
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
  window.sessionStorage.setItem(COGNITO_RETURN_TO_KEY, safeReturnTo(returnTo));
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

export async function finishCognitoLogin(code: string, state: string): Promise<string> {
  const config = await loadAuthConfig();
  if (
    typeof window === "undefined" ||
    config.auth_mode !== "cognito" ||
    !config.cognito_domain ||
    !config.cognito_client_id
  ) {
    throw new Error("Cognito is not configured");
  }
  const expectedState = window.sessionStorage.getItem(COGNITO_STATE_KEY);
  const verifier = window.sessionStorage.getItem(COGNITO_VERIFIER_KEY);
  const returnTo = safeReturnTo(window.sessionStorage.getItem(COGNITO_RETURN_TO_KEY));
  window.sessionStorage.removeItem(COGNITO_STATE_KEY);
  window.sessionStorage.removeItem(COGNITO_VERIFIER_KEY);
  window.sessionStorage.removeItem(COGNITO_RETURN_TO_KEY);
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
  storeCognitoTokens(
    payload.id_token,
    typeof payload.access_token === "string" ? payload.access_token : "",
  );
  return returnTo;
}

async function postCognitoPassword(body: Record<string, string>): Promise<Record<string, unknown>> {
  const res = await fetch("/api/auth/cognito/password", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (!res.ok) {
    throw new Error(typeof payload.error === "string" ? payload.error : "ログインに失敗しました");
  }
  return payload;
}

function persistPasswordAuth(payload: Record<string, unknown>): void {
  const idToken = typeof payload.id_token === "string" ? payload.id_token : "";
  const accessToken = typeof payload.access_token === "string" ? payload.access_token : "";
  if (!idToken) {
    throw new Error("Cognito token is missing");
  }
  storeCognitoTokens(idToken, accessToken);
}

export async function signInWithCognitoPassword(
  email: string,
  password: string,
): Promise<CognitoPasswordLoginResult> {
  const payload = await postCognitoPassword({ action: "sign_in", email, password });
  if (payload.challenge === "NEW_PASSWORD_REQUIRED") {
    const session = typeof payload.session === "string" ? payload.session : "";
    const username = typeof payload.challenge_username === "string" ? payload.challenge_username : email;
    if (!session) throw new Error("Cognito challenge session is missing");
    return { session, status: "new_password_required", username };
  }
  persistPasswordAuth(payload);
  return { status: "authenticated" };
}

export async function completeCognitoNewPassword(
  email: string,
  newPassword: string,
  session: string,
  challengeUsername = email,
): Promise<CognitoPasswordLoginResult> {
  const payload = await postCognitoPassword({
    action: "complete_new_password",
    challenge_username: challengeUsername,
    email,
    new_password: newPassword,
    session,
  });
  persistPasswordAuth(payload);
  return { status: "authenticated" };
}

export async function startCognitoLogout(): Promise<boolean> {
  clearSessionToken();
  return false;
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
  const token = loadCognitoToken();
  if (token) {
    const user = userFromClaims(decodeJwtPayload(token));
    if (user) return user;
  }
  return window.sessionStorage.getItem(USER_KEY);
}

export function saveSessionUserId(userId: string): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(USER_KEY, userId.trim());
  window.sessionStorage.setItem(TENANT_KEY, DEMO_TENANT);
  window.sessionStorage.setItem(ROLES_KEY, JSON.stringify(rolesForUser(userId.trim())));
  window.sessionStorage.setItem(DISPLAY_NAME_KEY, userId.trim());
}

export function loadSessionTenantId(): string {
  if (typeof window === "undefined") return DEMO_TENANT;
  const token = loadCognitoToken();
  if (token) {
    return tenantFromClaims(decodeJwtPayload(token));
  }
  return window.sessionStorage.getItem(TENANT_KEY) || DEMO_TENANT;
}

export function loadSessionRoles(): WorkspaceRole[] {
  if (typeof window === "undefined") return rolesForUser(DEMO_USER);
  const token = loadCognitoToken();
  if (token) {
    const roles = rolesFromClaims(decodeJwtPayload(token));
    return roles.length ? roles : ["field_user"];
  }
  const raw = window.sessionStorage.getItem(ROLES_KEY);
  if (raw) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        const roles = normalizeWorkspaceRoles(parsed);
        if (roles.length) return roles;
      }
    } catch {
      /* fall through to demo mapping */
    }
  }
  return rolesForUser(loadSessionUserId() ?? DEMO_USER);
}

export function loadSessionDisplayName(): string {
  if (typeof window === "undefined") return DEMO_USER;
  const token = loadCognitoToken();
  if (token) {
    return displayNameFromClaims(decodeJwtPayload(token));
  }
  return window.sessionStorage.getItem(DISPLAY_NAME_KEY) || loadSessionUserId() || DEMO_USER;
}

export async function getBrowserSessionState(): Promise<BrowserSessionState> {
  const config = await loadAuthConfig();
  const isCognito = config.auth_mode === "cognito";
  const isConfigured = Boolean(config.cognito_domain && config.cognito_client_id);
  const token = loadCognitoToken();
  const userId = loadSessionUserId() ?? DEMO_USER;
  const roles = loadSessionRoles();
  return {
    authMode: config.auth_mode || "dev",
    displayName: loadSessionDisplayName(),
    isAuthenticated: isCognito ? Boolean(token) : true,
    isCognito,
    isConfigured,
    isSalesDemo: isSalesDemoUser(userId, roles),
    roles,
    tenantId: loadSessionTenantId(),
    userId,
  };
}

export function isSalesDemoUser(userId: string, roles: WorkspaceRole[]): boolean {
  const normalized = userId.trim().toLowerCase();
  return roles.includes("sales_demo") || normalized.startsWith("sales@") || normalized.includes("+sales@");
}

/** Forget the cached token (e.g. on auth failure) so the next call re-mints. */
export function clearSessionToken(): void {
  if (typeof window !== "undefined") {
    window.sessionStorage.removeItem(STORAGE_KEY);
    window.sessionStorage.removeItem(USER_KEY);
    window.sessionStorage.removeItem(TENANT_KEY);
    window.sessionStorage.removeItem(ROLES_KEY);
    window.sessionStorage.removeItem(DISPLAY_NAME_KEY);
    window.sessionStorage.removeItem(COGNITO_ID_TOKEN_KEY);
    window.sessionStorage.removeItem(COGNITO_ACCESS_TOKEN_KEY);
    window.sessionStorage.removeItem(COGNITO_STATE_KEY);
    window.sessionStorage.removeItem(COGNITO_VERIFIER_KEY);
    window.sessionStorage.removeItem(COGNITO_RETURN_TO_KEY);
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
