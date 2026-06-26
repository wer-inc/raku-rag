import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

function first(...values: Array<string | undefined>): string {
  return values.find((value) => value && value.trim()) ?? "";
}

export async function GET() {
  const authMode = first(process.env.RAKU_AUTH_MODE, process.env.NEXT_PUBLIC_RAKU_AUTH_MODE);
  if (authMode !== "cognito") {
    return NextResponse.json({
      auth_mode: authMode,
      cognito_domain: "",
      cognito_client_id: "",
      cognito_issuer: "",
    });
  }
  return NextResponse.json({
    auth_mode: authMode,
    cognito_domain: first(process.env.COGNITO_DOMAIN, process.env.NEXT_PUBLIC_COGNITO_DOMAIN),
    cognito_client_id: first(
      process.env.COGNITO_CLIENT_ID,
      process.env.COGNITO_USER_POOL_CLIENT_ID,
      process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID,
    ),
    cognito_issuer: first(process.env.COGNITO_ISSUER, process.env.NEXT_PUBLIC_COGNITO_ISSUER),
  });
}
