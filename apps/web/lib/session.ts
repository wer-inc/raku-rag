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
const COGNITO_REFRESH_TOKEN_KEY = "raku.cognito.refresh_token";
const COGNITO_STATE_KEY = "raku.cognito.pkce.state";
const COGNITO_VERIFIER_KEY = "raku.cognito.pkce.verifier";
const COGNITO_RETURN_TO_KEY = "raku.cognito.return_to";
const REMEMBER_LOGIN_KEY = "raku.session.remember_login";
const AUTH_STORAGE_KEYS = [
  STORAGE_KEY,
  USER_KEY,
  TENANT_KEY,
  ROLES_KEY,
  DISPLAY_NAME_KEY,
  COGNITO_ID_TOKEN_KEY,
  COGNITO_ACCESS_TOKEN_KEY,
  COGNITO_REFRESH_TOKEN_KEY,
  COGNITO_STATE_KEY,
  COGNITO_VERIFIER_KEY,
  COGNITO_RETURN_TO_KEY,
];

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

export type AppSessionErrorCode =
  | "reauth_required"
  | "session_mismatch"
  | "tenant_not_configured"
  | "session_missing";

const APP_SESSION_ERROR_MESSAGES: Record<AppSessionErrorCode, string> = {
  reauth_required: "ログイン情報を更新してください",
  session_mismatch: "ログイン設定が変更されました。ログインし直してください",
  tenant_not_configured: "アカウント設定が未完了です。管理者に確認してください",
  session_missing: "ログインしてください",
};

export class AppSessionError extends Error {
  code: AppSessionErrorCode;

  constructor(code: AppSessionErrorCode, message = APP_SESSION_ERROR_MESSAGES[code]) {
    super(message);
    this.name = "AppSessionError";
    this.code = code;
  }
}

export function isAppSessionError(error: unknown): error is AppSessionError {
  return (
    error instanceof AppSessionError ||
    (typeof error === "object" &&
      error !== null &&
      "name" in error &&
      (error as { name?: unknown }).name === "AppSessionError" &&
      "code" in error &&
      typeof (error as { code?: unknown }).code === "string")
  );
}

export type CognitoPasswordLoginResult =
  | { status: "authenticated" }
  | { status: "new_password_required"; session: string; username: string };

let authConfigPromise: Promise<AuthConfig> | null = null;
let refreshInflight: Promise<ValidatedCognitoToken | null> | null = null;

function storageGet(storage: Storage, key: string): string | null {
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(storage: Storage, key: string, value: string): void {
  try {
    storage.setItem(key, value);
  } catch {
    /* best-effort */
  }
}

function storageRemove(storage: Storage, key: string): void {
  try {
    storage.removeItem(key);
  } catch {
    /* best-effort */
  }
}

function storedSessionValue(key: string): string | null {
  if (typeof window === "undefined") return null;
  return storageGet(window.sessionStorage, key) ?? storageGet(window.localStorage, key);
}

function rememberLoginEnabled(): boolean {
  if (typeof window === "undefined") return false;
  return storageGet(window.localStorage, REMEMBER_LOGIN_KEY) === "true";
}

export function loadRememberLoginPreference(): boolean {
  return rememberLoginEnabled();
}

function setRememberLoginPreference(remember: boolean): void {
  if (typeof window === "undefined") return;
  if (remember) {
    storageSet(window.localStorage, REMEMBER_LOGIN_KEY, "true");
  } else {
    storageRemove(window.localStorage, REMEMBER_LOGIN_KEY);
  }
}

function writeSessionValue(key: string, value: string, remember = false): void {
  if (typeof window === "undefined") return;
  storageSet(window.sessionStorage, key, value);
  if (remember) {
    storageSet(window.localStorage, key, value);
  } else {
    storageRemove(window.localStorage, key);
  }
}

function removeSessionValue(key: string): void {
  if (typeof window === "undefined") return;
  storageRemove(window.sessionStorage, key);
  storageRemove(window.localStorage, key);
}

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

function cognitoTenantFromClaims(claims: Record<string, unknown> | null): string {
  return claimString(claims, "custom:tenant_id");
}

function tenantFromClaims(claims: Record<string, unknown> | null): string {
  return cognitoTenantFromClaims(claims) || claimString(claims, "tenant_id") || DEMO_TENANT;
}

function unexpiredJwt(token: string): boolean {
  const payload = decodeJwtPayload(token);
  const exp = payload?.exp;
  return typeof exp !== "number" || exp > Math.floor(Date.now() / 1000) + 30;
}

function unexpiredStoredJwt(key: string): string | null {
  const token = storedSessionValue(key);
  if (!token) return null;
  if (unexpiredJwt(token)) return token;
  removeSessionValue(key);
  return null;
}

function loadDisplayCognitoToken(): string | null {
  return unexpiredStoredJwt(COGNITO_ID_TOKEN_KEY) ?? unexpiredStoredJwt(COGNITO_ACCESS_TOKEN_KEY);
}

type CognitoStoredTokenKind = "id" | "access";

type ValidatedCognitoToken = {
  token: string;
  claims: Record<string, unknown>;
  kind: CognitoStoredTokenKind;
};

type CognitoTokenValidation =
  | { ok: true; value: ValidatedCognitoToken }
  | { ok: false; code: AppSessionErrorCode };

function normalizedIssuer(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function claimMatchesStringOrArray(value: unknown, expected: string): boolean {
  if (!expected) return true;
  if (typeof value === "string") return value === expected;
  return Array.isArray(value) && value.includes(expected);
}

function tokenClientMatches(claims: Record<string, unknown>, clientId: string): boolean {
  return claimMatchesStringOrArray(claims.aud, clientId) || claimString(claims, "client_id") === clientId;
}

function validateCognitoTokenForApp(
  token: string,
  config: AuthConfig,
  kind: CognitoStoredTokenKind,
): CognitoTokenValidation {
  const claims = decodeJwtPayload(token);
  if (!claims) return { ok: false, code: "reauth_required" };

  const tokenUse = claimString(claims, "token_use");
  if (tokenUse !== kind) return { ok: false, code: "reauth_required" };

  const now = Math.floor(Date.now() / 1000);
  if (typeof claims.exp !== "number" || claims.exp <= now + 30) {
    return { ok: false, code: "reauth_required" };
  }
  if (typeof claims.nbf === "number" && claims.nbf > now) {
    return { ok: false, code: "reauth_required" };
  }

  const expectedIssuer = normalizedIssuer(config.cognito_issuer);
  if (expectedIssuer && normalizedIssuer(claimString(claims, "iss")) !== expectedIssuer) {
    return { ok: false, code: "session_mismatch" };
  }
  if (config.cognito_client_id && !tokenClientMatches(claims, config.cognito_client_id)) {
    return { ok: false, code: "session_mismatch" };
  }
  if (!cognitoTenantFromClaims(claims)) {
    return { ok: false, code: "tenant_not_configured" };
  }
  if (!claimString(claims, "sub")) {
    return { ok: false, code: "reauth_required" };
  }

  return { ok: true, value: { token, claims, kind } };
}

function chooseSessionError(
  sawToken: boolean,
  failures: AppSessionErrorCode[],
): AppSessionErrorCode {
  if (!sawToken) return "session_missing";
  if (failures.includes("tenant_not_configured")) return "tenant_not_configured";
  if (failures.includes("session_mismatch")) return "session_mismatch";
  if (failures.includes("reauth_required")) return "reauth_required";
  return "session_missing";
}

function loadStoredAppCognitoToken(config: AuthConfig): CognitoTokenValidation {
  const candidates: Array<{ key: string; kind: CognitoStoredTokenKind }> = [
    { key: COGNITO_ID_TOKEN_KEY, kind: "id" },
    { key: COGNITO_ACCESS_TOKEN_KEY, kind: "access" },
  ];
  const failures: AppSessionErrorCode[] = [];
  let sawToken = false;
  for (const candidate of candidates) {
    const token = storedSessionValue(candidate.key);
    if (!token) continue;
    sawToken = true;
    const validated = validateCognitoTokenForApp(token, config, candidate.kind);
    if (validated.ok) return validated;
    failures.push(validated.code);
  }
  return { ok: false, code: chooseSessionError(sawToken, failures) };
}

function loadCognitoRefreshToken(): string | null {
  return storedSessionValue(COGNITO_REFRESH_TOKEN_KEY);
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

function storeCognitoTokens(
  idToken: string,
  accessToken = "",
  refreshToken = "",
  remember = rememberLoginEnabled(),
): void {
  if (typeof window === "undefined" || !idToken) return;
  setRememberLoginPreference(remember);
  writeSessionValue(COGNITO_ID_TOKEN_KEY, idToken, remember);
  if (accessToken) {
    writeSessionValue(COGNITO_ACCESS_TOKEN_KEY, accessToken, remember);
  } else {
    removeSessionValue(COGNITO_ACCESS_TOKEN_KEY);
  }
  if (refreshToken) {
    writeSessionValue(COGNITO_REFRESH_TOKEN_KEY, refreshToken, remember);
  }
  const claims = decodeJwtPayload(idToken);
  const user = userFromClaims(claims);
  if (user) {
    writeSessionValue(USER_KEY, user, remember);
  }
  const tenant = cognitoTenantFromClaims(claims);
  if (tenant) {
    writeSessionValue(TENANT_KEY, tenant, remember);
  } else {
    removeSessionValue(TENANT_KEY);
  }
  writeSessionValue(DISPLAY_NAME_KEY, displayNameFromClaims(claims), remember);
  writeSessionValue(ROLES_KEY, JSON.stringify(rolesFromClaims(claims)), remember);
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
    typeof payload.refresh_token === "string" ? payload.refresh_token : "",
    rememberLoginEnabled(),
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

function persistPasswordAuth(payload: Record<string, unknown>, remember = false, fallbackRefreshToken = ""): void {
  const idToken = typeof payload.id_token === "string" ? payload.id_token : "";
  const accessToken = typeof payload.access_token === "string" ? payload.access_token : "";
  const refreshToken =
    typeof payload.refresh_token === "string" && payload.refresh_token
      ? payload.refresh_token
      : fallbackRefreshToken;
  if (!idToken) {
    throw new Error("Cognito token is missing");
  }
  storeCognitoTokens(idToken, accessToken, refreshToken, remember);
}

async function refreshCognitoSession(config: AuthConfig): Promise<ValidatedCognitoToken | null> {
  const refreshToken = loadCognitoRefreshToken();
  if (!refreshToken) return null;
  if (!refreshInflight) {
    refreshInflight = postCognitoPassword({ action: "refresh", refresh_token: refreshToken })
      .then((payload) => {
        persistPasswordAuth(payload, rememberLoginEnabled(), refreshToken);
        const validated = loadStoredAppCognitoToken(config);
        if (validated.ok) return validated.value;
        throw new AppSessionError(validated.code);
      })
      .catch(() => {
        clearSessionToken();
        return null;
      })
      .finally(() => {
        refreshInflight = null;
      });
  }
  return refreshInflight;
}

async function ensureCognitoToken(): Promise<string | null> {
  const config = await loadAuthConfig();
  if (config.auth_mode !== "cognito" || !config.cognito_domain || !config.cognito_client_id) {
    return null;
  }
  const stored = loadStoredAppCognitoToken(config);
  if (stored.ok) return stored.value.token;
  const refreshed = await refreshCognitoSession(config);
  if (refreshed) return refreshed.token;
  clearSessionToken();
  throw new AppSessionError(stored.code);
}

export async function signInWithCognitoPassword(
  email: string,
  password: string,
  remember = false,
): Promise<CognitoPasswordLoginResult> {
  const payload = await postCognitoPassword({ action: "sign_in", email, password });
  if (payload.challenge === "NEW_PASSWORD_REQUIRED") {
    const session = typeof payload.session === "string" ? payload.session : "";
    const username = typeof payload.challenge_username === "string" ? payload.challenge_username : email;
    if (!session) throw new Error("Cognito challenge session is missing");
    return { session, status: "new_password_required", username };
  }
  persistPasswordAuth(payload, remember);
  return { status: "authenticated" };
}

export async function completeCognitoNewPassword(
  email: string,
  newPassword: string,
  session: string,
  challengeUsername = email,
  remember = false,
): Promise<CognitoPasswordLoginResult> {
  const payload = await postCognitoPassword({
    action: "complete_new_password",
    challenge_username: challengeUsername,
    email,
    new_password: newPassword,
    session,
  });
  persistPasswordAuth(payload, remember);
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
  const cognitoToken = await ensureCognitoToken();
  if (cognitoToken) return cognitoToken;
  const authConfig = await loadAuthConfig();
  if (authConfig.auth_mode === "cognito" && authConfig.cognito_domain && authConfig.cognito_client_id) {
    throw new AppSessionError("session_missing");
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
  const token = loadDisplayCognitoToken();
  if (token) {
    const user = userFromClaims(decodeJwtPayload(token));
    if (user) return user;
  }
  return storedSessionValue(USER_KEY);
}

export function saveSessionUserId(userId: string): void {
  if (typeof window === "undefined") return;
  writeSessionValue(USER_KEY, userId.trim());
  writeSessionValue(TENANT_KEY, DEMO_TENANT);
  writeSessionValue(ROLES_KEY, JSON.stringify(rolesForUser(userId.trim())));
  writeSessionValue(DISPLAY_NAME_KEY, userId.trim());
}

export function loadSessionTenantId(): string {
  if (typeof window === "undefined") return DEMO_TENANT;
  const token = loadDisplayCognitoToken();
  if (token) {
    return tenantFromClaims(decodeJwtPayload(token));
  }
  return storedSessionValue(TENANT_KEY) || DEMO_TENANT;
}

export function loadSessionRoles(): WorkspaceRole[] {
  if (typeof window === "undefined") return rolesForUser(DEMO_USER);
  const token = loadDisplayCognitoToken();
  if (token) {
    const roles = rolesFromClaims(decodeJwtPayload(token));
    return roles.length ? roles : ["field_user"];
  }
  const raw = storedSessionValue(ROLES_KEY);
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
  const token = loadDisplayCognitoToken();
  if (token) {
    return displayNameFromClaims(decodeJwtPayload(token));
  }
  return storedSessionValue(DISPLAY_NAME_KEY) || loadSessionUserId() || DEMO_USER;
}

export async function getBrowserSessionState(): Promise<BrowserSessionState> {
  const config = await loadAuthConfig();
  const isCognito = config.auth_mode === "cognito";
  const isConfigured = Boolean(config.cognito_domain && config.cognito_client_id);
  let token: string | null = null;
  try {
    token = await ensureCognitoToken();
  } catch (err) {
    if (!isAppSessionError(err)) throw err;
  }
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
    AUTH_STORAGE_KEYS.forEach(removeSessionValue);
    setRememberLoginPreference(false);
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
