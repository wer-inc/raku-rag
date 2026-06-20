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
  if (process.env.NODE_ENV === "production") {
    return false;
  }
  const raw = process.env.RAKU_ENABLE_DEV_TOKEN_ISSUER;
  if (raw !== undefined) {
    return raw === "1" || raw.toLowerCase() === "true";
  }
  return true;
}

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
    groups: Array.isArray(body.groups) ? body.groups.filter((v): v is string => typeof v === "string") : [],
    roles: Array.isArray(body.roles) ? body.roles.filter((v): v is string => typeof v === "string") : [],
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
