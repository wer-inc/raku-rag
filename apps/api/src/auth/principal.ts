// P0-T06 — mock principal parsing. X-User-Token = base64url(JSON{tenant_id,user_id,groups,roles}).
// Phase 0 skeleton does NOT verify the HMAC signature; Phase 1 wires the real TokenVerifier
// (matching src/raku_rag/core/security/token.py) behind this boundary.

export interface Principal {
  tenant_id: string;
  user_id: string;
  groups: string[];
  roles: string[];
}

export function makeUserToken(p: Principal): string {
  const json = JSON.stringify(p);
  return Buffer.from(json, "utf8").toString("base64url");
}

export function parseUserToken(token: string): Principal | null {
  try {
    const body = token.includes(".") ? token.split(".")[0] : token;
    const json = Buffer.from(body, "base64url").toString("utf8");
    const obj = JSON.parse(json);
    if (!obj || typeof obj.tenant_id !== "string" || typeof obj.user_id !== "string") {
      return null;
    }
    return {
      tenant_id: obj.tenant_id,
      user_id: obj.user_id,
      groups: Array.isArray(obj.groups) ? obj.groups : [],
      roles: Array.isArray(obj.roles) ? obj.roles : [],
    };
  } catch {
    return null;
  }
}
