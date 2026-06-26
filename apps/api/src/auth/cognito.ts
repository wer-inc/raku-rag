import { createPublicKey, verify as verifySignature } from "crypto";
import type { JsonWebKey as NodeJsonWebKey } from "crypto";
import type { Principal } from "./principal";

interface CognitoJwtConfig {
  issuer: string;
  clientId: string;
  jwksUri?: string;
  nowSeconds?: () => number;
}

interface JwtHeader {
  alg?: string;
  kid?: string;
}

type JwtClaims = Record<string, unknown>;

interface JwksCacheEntry {
  expiresAt: number;
  keys: JwksKey[];
}

type JwksKey = NodeJsonWebKey & { kid?: string };

const JWKS_CACHE_MS = 5 * 60 * 1000;
const jwksCache = new Map<string, JwksCacheEntry>();

function decodeJson<T>(part: string): T {
  return JSON.parse(Buffer.from(part, "base64url").toString("utf8")) as T;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function audienceMatches(claims: JwtClaims, clientId: string): boolean {
  const aud = claims.aud;
  if (typeof aud === "string" && aud === clientId) {
    return true;
  }
  if (Array.isArray(aud) && aud.includes(clientId)) {
    return true;
  }
  return typeof claims.client_id === "string" && claims.client_id === clientId;
}

function jwksUriForIssuer(issuer: string): string {
  return `${issuer.replace(/\/+$/, "")}/.well-known/jwks.json`;
}

async function fetchJwks(uri: string): Promise<JwksKey[]> {
  const cached = jwksCache.get(uri);
  if (cached && cached.expiresAt > Date.now()) {
    return cached.keys;
  }
  const res = await fetch(uri, { signal: AbortSignal.timeout(5000) });
  if (!res.ok) {
    throw new Error(`jwks_fetch_failed:${res.status}`);
  }
  const body = (await res.json()) as { keys?: JwksKey[] };
  const keys = Array.isArray(body.keys) ? body.keys : [];
  jwksCache.set(uri, { expiresAt: Date.now() + JWKS_CACHE_MS, keys });
  return keys;
}

export function clearCognitoJwksCache(): void {
  jwksCache.clear();
}

export async function parseCognitoJwt(
  token: string,
  config: CognitoJwtConfig,
): Promise<Principal | null> {
  try {
    const issuer = config.issuer.trim().replace(/\/+$/, "");
    const clientId = config.clientId.trim();
    if (!issuer || !clientId) {
      return null;
    }
    const [encodedHeader, encodedPayload, encodedSignature, extra] = token.split(".");
    if (!encodedHeader || !encodedPayload || !encodedSignature || extra !== undefined) {
      return null;
    }

    const header = decodeJson<JwtHeader>(encodedHeader);
    const claims = decodeJson<JwtClaims>(encodedPayload);
    if (header.alg !== "RS256" || typeof header.kid !== "string") {
      return null;
    }
    const keys = await fetchJwks(config.jwksUri || jwksUriForIssuer(issuer));
    const jwk = keys.find((key) => key.kid === header.kid);
    if (!jwk) {
      return null;
    }
    const publicKey = createPublicKey({ key: jwk, format: "jwk" });
    const signed = Buffer.from(`${encodedHeader}.${encodedPayload}`, "utf8");
    const signature = Buffer.from(encodedSignature, "base64url");
    if (!verifySignature("RSA-SHA256", signed, publicKey, signature)) {
      return null;
    }

    const now = config.nowSeconds ? config.nowSeconds() : Math.floor(Date.now() / 1000);
    if (claims.iss !== issuer) {
      return null;
    }
    if (!audienceMatches(claims, clientId)) {
      return null;
    }
    if (claims.token_use !== "id" && claims.token_use !== "access") {
      return null;
    }
    if (typeof claims.exp !== "number" || claims.exp <= now) {
      return null;
    }
    if (typeof claims.nbf === "number" && claims.nbf > now) {
      return null;
    }

    const tenantId = claims["custom:tenant_id"];
    const sub = claims.sub;
    if (typeof tenantId !== "string" || !tenantId.trim() || typeof sub !== "string" || !sub.trim()) {
      return null;
    }
    const userId = typeof claims.email === "string" && claims.email.trim() ? claims.email : sub;
    const groups = stringArray(claims["cognito:groups"]);
    return {
      tenant_id: tenantId,
      user_id: userId,
      groups,
      roles: groups,
    };
  } catch {
    return null;
  }
}
