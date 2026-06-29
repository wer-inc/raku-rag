import { createHmac, timingSafeEqual } from "crypto";

export interface ChatWidgetClaims {
  tenant_id: string;
  widget_id: string;
  allowed_domains: string[];
  collection_id?: string;
  exp?: number;
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

export function chatWidgetSecret(): string {
  const secret = process.env.RAKU_CHAT_WIDGET_SECRET;
  if (secret && secret.trim() !== "") {
    return secret;
  }
  throw new Error("RAKU_CHAT_WIDGET_SECRET is required for public ChatBot widget sessions");
}

export function makeChatWidgetToken(claims: ChatWidgetClaims, secret = chatWidgetSecret()): string {
  const body = Buffer.from(
    JSON.stringify({
      allowed_domains: claims.allowed_domains,
      collection_id: claims.collection_id,
      exp: claims.exp,
      tenant_id: claims.tenant_id,
      widget_id: claims.widget_id,
    }),
    "utf8",
  ).toString("base64url");
  return `${body}.${signBody(body, secret)}`;
}

export function parseChatWidgetToken(token: string, secret = chatWidgetSecret()): ChatWidgetClaims | null {
  try {
    const [body, sig, extra] = token.split(".");
    if (!body || !sig || extra !== undefined) {
      return null;
    }
    const expected = signBody(body, secret);
    if (!sameSignature(sig, expected)) {
      return null;
    }
    const parsed = JSON.parse(Buffer.from(body, "base64url").toString("utf8"));
    if (!parsed || typeof parsed.tenant_id !== "string" || typeof parsed.widget_id !== "string") {
      return null;
    }
    const claims: ChatWidgetClaims = {
      tenant_id: parsed.tenant_id,
      widget_id: parsed.widget_id,
      allowed_domains: stringArray(parsed.allowed_domains),
      collection_id: typeof parsed.collection_id === "string" ? parsed.collection_id : undefined,
      exp: typeof parsed.exp === "number" ? parsed.exp : undefined,
    };
    if (!claims.allowed_domains.length) {
      return null;
    }
    if (claims.exp !== undefined && claims.exp < Math.floor(Date.now() / 1000)) {
      return null;
    }
    return claims;
  } catch {
    return null;
  }
}
