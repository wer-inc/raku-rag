import { createHmac } from "crypto";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

interface DevClaims {
  tenant_id: string;
  user_id: string;
  groups: string[];
  roles: string[];
}

function enabled(): boolean {
  const mode = (process.env.RAKU_AUTH_MODE ?? "").trim().toLowerCase();
  if (process.env.STAGE_NAME === "prod" || mode === "cognito") {
    return false;
  }
  if (mode === "dev") {
    return true;
  }
  const raw = process.env.RAKU_ENABLE_DEV_TOKEN_ISSUER;
  if (raw !== undefined) {
    return process.env.NODE_ENV !== "production" && (raw === "1" || raw.toLowerCase() === "true");
  }
  return process.env.NODE_ENV !== "production";
}

// Dev-only AUTHORITATIVE role assignment: roles/groups come from this server-side table keyed by
// user_id, NEVER echoed from the request body. The browser therefore cannot self-assert privileged
// roles or escalate — the only privilege it can obtain is what the issuer decides for a known
// identity. (Production swaps this issuer for Cognito/JWKS, where roles come from the IdP.)
// `carol` is a PURE reviewer (no tenant_admin): with the facade's reviewer-level approval guard
// (assertReviewApprovalAllowed) she runs the full review loop — assign/approve/reject and document
// approval — without any admin role. `alice`/`misaki` keep tenant_admin only because they also use
// admin-only operations (document metadata PUT, data-use policy PUT), NOT because approval needs it.
// `dave` (ops_owner) cannot approve by default — the contract (mfg-interfaces.md:141) names only
// `reviewer`. Un-provisioned identities get no roles (reads of per-doc content work; tenant-wide
// views and all mutations are server-rejected).
const DEV_ROLES_BY_USER: Record<string, string[]> = {
  alice: ["tenant_admin", "reviewer"],
  bob: ["field_user"],
  carol: ["reviewer"],
  dave: ["ops_owner"],
  misaki: ["tenant_admin", "reviewer"],
  "sales-demo@example.com": ["tenant_admin", "reviewer", "sales_demo"],
};

function normalize(body: Record<string, unknown>): DevClaims | null {
  if (typeof body.tenant_id !== "string" || typeof body.user_id !== "string") {
    return null;
  }
  const tenant = body.tenant_id.trim();
  const user = body.user_id.trim();
  if (!tenant || !user || tenant.length > 128 || user.length > 128) {
    return null;
  }
  return {
    groups: [],
    roles: DEV_ROLES_BY_USER[user] ?? [],
    tenant_id: tenant,
    user_id: user,
  };
}

function sign(claims: DevClaims): string {
  const secret = process.env.RAKU_TOKEN_SIGNING_SECRET ?? "dev-secret-change-me";
  const body = Buffer.from(JSON.stringify(claims), "utf8").toString("base64url");
  const sig = createHmac("sha256", secret).update(body).digest("base64url");
  return `${body}.${sig}`;
}

export async function POST(req: Request) {
  if (!enabled()) {
    return NextResponse.json({ error: "local dev token issuer disabled" }, { status: 403 });
  }
  const body = (await req.json().catch(() => null)) as Record<string, unknown> | null;
  const claims = body ? normalize(body) : null;
  if (!claims) {
    return NextResponse.json({ error: "invalid dev token claims" }, { status: 400 });
  }
  return NextResponse.json({ token: sign(claims) });
}
