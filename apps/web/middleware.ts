import { NextResponse, type NextRequest } from "next/server";

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

export function middleware(req: NextRequest) {
  const expectedUser = envFirst("RAKU_BASIC_AUTH_USER", "BASIC_AUTH_USER");
  const expectedPassword = envFirst("RAKU_BASIC_AUTH_PASSWORD", "BASIC_AUTH_PASSWORD");
  if (!expectedUser || !expectedPassword) {
    return NextResponse.next();
  }

  const credentials = parseBasicAuth(req.headers.get("authorization"));
  if (
    credentials &&
    constantTimeEqual(credentials.user, expectedUser) &&
    constantTimeEqual(credentials.password, expectedPassword)
  ) {
    return NextResponse.next();
  }

  return unauthorized();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
  runtime: "nodejs",
};
