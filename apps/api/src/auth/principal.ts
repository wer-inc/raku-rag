import { createHmac, timingSafeEqual } from "crypto";

// X-User-Token = base64url(JSON{tenant_id,user_id,groups,roles}).base64url(HMAC-SHA256(body)).
// This mirrors src/raku_rag/core/security/token.py so the NestJS facade and Python core share the
// same local MVP token boundary. Production can swap this behind Cognito/JWKS without changing callers.

export interface Principal {
  tenant_id: string;
  user_id: string;
  groups: string[];
  roles: string[];
}

const DEFAULT_DEV_SECRET = "dev-secret-change-me";

/**
 * Resolve the X-User-Token signing secret, FAIL-CLOSED.
 *
 * The in-repo literal `dev-secret-change-me` is public, so accepting it in a real environment lets
 * anyone forge a valid X-User-Token and impersonate any tenant/user (a full ACL/tenant bypass). We
 * therefore require an explicit, non-default `RAKU_TOKEN_SIGNING_SECRET` everywhere EXCEPT the test
 * harness (e2e specs set NODE_ENV=test and rely on the shared dev default).
 */
export function tokenSecret(): string {
  const secret = process.env.RAKU_TOKEN_SIGNING_SECRET;
  if (secret && secret !== DEFAULT_DEV_SECRET) {
    return secret;
  }
  if (process.env.NODE_ENV === "test") {
    return DEFAULT_DEV_SECRET;
  }
  throw new Error(
    "RAKU_TOKEN_SIGNING_SECRET must be set to a non-default value. The in-repo default " +
      "'dev-secret-change-me' is public; using it would let anyone forge an X-User-Token and " +
      "impersonate any tenant/user. Set the SAME secret on the API and the dev-token issuer.",
  );
}

function canonicalPayload(p: Principal) {
  return {
    groups: p.groups,
    roles: p.roles,
    tenant_id: p.tenant_id,
    user_id: p.user_id,
  };
}

function signBody(body: string, secret: string): string {
  return createHmac("sha256", secret).update(body).digest("base64url");
}

function sameSignature(a: string, b: string): boolean {
  const left = Buffer.from(a, "utf8");
  const right = Buffer.from(b, "utf8");
  return left.length === right.length && timingSafeEqual(left, right);
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

export function makeUserToken(p: Principal, secret = tokenSecret()): string {
  const body = Buffer.from(JSON.stringify(canonicalPayload(p)), "utf8").toString("base64url");
  return `${body}.${signBody(body, secret)}`;
}

export function parseUserToken(token: string, secret = tokenSecret()): Principal | null {
  try {
    const [body, sig, extra] = token.split(".");
    if (!body || !sig || extra !== undefined) {
      return null;
    }
    const expected = signBody(body, secret);
    if (!sameSignature(sig, expected)) {
      return null;
    }
    const json = Buffer.from(body, "base64url").toString("utf8");
    const obj = JSON.parse(json);
    if (!obj || typeof obj.tenant_id !== "string" || typeof obj.user_id !== "string") {
      return null;
    }
    return {
      tenant_id: obj.tenant_id,
      user_id: obj.user_id,
      groups: stringArray(obj.groups),
      roles: stringArray(obj.roles),
    };
  } catch {
    return null;
  }
}
