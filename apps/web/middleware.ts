import { NextResponse, type NextRequest } from "next/server";

const BASIC_AUTH_COOKIE = "raku_basic_auth";
const BASIC_AUTH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 12;

function envFirst(...keys: string[]): string {
  for (const key of keys) {
    const value = process.env[key];
    if (value && value.trim()) return value.trim();
  }
  return "";
}

function constantTimeEqual(a: string, b: string): boolean {
  const max = Math.max(a.length, b.length);
  let diff = a.length ^ b.length;
  for (let i = 0; i < max; i += 1) {
    diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  }
  return diff === 0;
}

function base64UrlEncode(input: string | Uint8Array): string {
  const bytes = typeof input === "string" ? new TextEncoder().encode(input) : input;
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlDecode(input: string): string | null {
  try {
    const padded = input
      .replace(/-/g, "+")
      .replace(/_/g, "/")
      .padEnd(Math.ceil(input.length / 4) * 4, "=");
    const binary = atob(padded);
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  } catch {
    return null;
  }
}

async function hmacSha256(message: string, secret: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { hash: "SHA-256", name: "HMAC" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return base64UrlEncode(new Uint8Array(signature));
}

function sessionSecret(expectedUser: string, expectedPassword: string): string {
  return (
    envFirst("RAKU_BASIC_AUTH_COOKIE_SECRET", "BASIC_AUTH_COOKIE_SECRET") ||
    `${expectedUser}:${expectedPassword}`
  );
}

async function issueSessionCookie(expectedUser: string, expectedPassword: string): Promise<string> {
  const expiresAt = Math.floor(Date.now() / 1000) + BASIC_AUTH_COOKIE_MAX_AGE_SECONDS;
  const payload = base64UrlEncode(JSON.stringify({ exp: expiresAt, user: expectedUser }));
  const signature = await hmacSha256(payload, sessionSecret(expectedUser, expectedPassword));
  return `${payload}.${signature}`;
}

async function hasValidSessionCookie(
  cookieValue: string | undefined,
  expectedUser: string,
  expectedPassword: string,
): Promise<boolean> {
  if (!cookieValue) return false;
  const [payload, signature, extra] = cookieValue.split(".");
  if (!payload || !signature || extra !== undefined) return false;
  const expectedSignature = await hmacSha256(payload, sessionSecret(expectedUser, expectedPassword));
  if (!constantTimeEqual(signature, expectedSignature)) return false;

  const decoded = base64UrlDecode(payload);
  if (!decoded) return false;
  try {
    const body = JSON.parse(decoded) as { exp?: unknown; user?: unknown };
    return (
      body.user === expectedUser &&
      typeof body.exp === "number" &&
      Number.isFinite(body.exp) &&
      body.exp > Math.floor(Date.now() / 1000)
    );
  } catch {
    return false;
  }
}

function parseBasicAuth(header: string | null): { user: string; password: string } | null {
  if (!header?.toLowerCase().startsWith("basic ")) return null;
  try {
    const decoded = atob(header.slice(6).trim());
    const separator = decoded.indexOf(":");
    if (separator < 0) return null;
    return {
      password: decoded.slice(separator + 1),
      user: decoded.slice(0, separator),
    };
  } catch {
    return null;
  }
}

function unauthorized(): NextResponse {
  const realm = envFirst("RAKU_BASIC_AUTH_REALM", "BASIC_AUTH_REALM") || "Raku RAG";
  return new NextResponse("Authentication required", {
    headers: {
      "cache-control": "no-store",
      "www-authenticate": `Basic realm="${realm.replace(/"/g, "")}", charset="UTF-8"`,
    },
    status: 401,
  });
}

export async function middleware(req: NextRequest) {
  if (req.nextUrl.pathname === "/api/health") {
    return NextResponse.next();
  }

  const expectedUser = envFirst("RAKU_BASIC_AUTH_USER", "BASIC_AUTH_USER");
  const expectedPassword = envFirst("RAKU_BASIC_AUTH_PASSWORD", "BASIC_AUTH_PASSWORD");
  if (!expectedUser || !expectedPassword) {
    return NextResponse.next();
  }

  if (
    await hasValidSessionCookie(
      req.cookies.get(BASIC_AUTH_COOKIE)?.value,
      expectedUser,
      expectedPassword,
    )
  ) {
    return NextResponse.next();
  }

  const credentials = parseBasicAuth(req.headers.get("authorization"));
  if (
    credentials &&
    constantTimeEqual(credentials.user, expectedUser) &&
    constantTimeEqual(credentials.password, expectedPassword)
  ) {
    const response = NextResponse.next();
    response.cookies.set({
      httpOnly: true,
      maxAge: BASIC_AUTH_COOKIE_MAX_AGE_SECONDS,
      name: BASIC_AUTH_COOKIE,
      path: "/",
      sameSite: "lax",
      secure: req.nextUrl.protocol === "https:",
      value: await issueSessionCookie(expectedUser, expectedPassword),
    });
    return response;
  }

  return unauthorized();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
  runtime: "nodejs",
};
