// Dev session: mint the local HMAC dev-token once and reuse it across views (specs/014 FR-008).
// The token carries the signed tenant/user identity; browser code never sends identity in bodies.

export const DEMO_TENANT = process.env.NEXT_PUBLIC_DEMO_TENANT_ID ?? "demo";
export const DEMO_USER = process.env.NEXT_PUBLIC_DEMO_USER_ID ?? "alice";
export const DEMO_COLLECTION = process.env.NEXT_PUBLIC_DEMO_COLLECTION_ID ?? "manuals";

const STORAGE_KEY = "raku.devtoken";

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
  userId: string = DEMO_USER,
): Promise<string> {
  if (typeof window !== "undefined") {
    const cached = window.sessionStorage.getItem(STORAGE_KEY);
    if (cached) return cached;
  }
  if (!inflight) {
    inflight = mint(tenantId, userId)
      .then((token) => {
        if (typeof window !== "undefined") window.sessionStorage.setItem(STORAGE_KEY, token);
        return token;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/** Forget the cached token (e.g. on auth failure) so the next call re-mints. */
export function clearSessionToken(): void {
  if (typeof window !== "undefined") window.sessionStorage.removeItem(STORAGE_KEY);
}

/**
 * Mint a fresh (uncached) dev-token for an arbitrary identity — used by the
 * permission simulator to run a query AS another user and prove ACL isolation.
 * Roles are assigned authoritatively server-side by the issuer (never the body).
 */
export async function mintTokenFor(tenantId: string, userId: string): Promise<string> {
  return mint(tenantId, userId);
}
