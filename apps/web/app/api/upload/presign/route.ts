import path from "path";
import { randomUUID } from "crypto";
import { PutObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const MAX_BYTES = 25 * 1024 * 1024;
const SIGNED_URL_TTL_SECONDS = 5 * 60;

const EXT_CONTENT_TYPE: Record<string, string> = {
  ".txt": "text/plain",
  ".md": "text/markdown",
  ".markdown": "text/markdown",
  ".html": "text/html",
  ".htm": "text/html",
  ".csv": "text/csv",
  ".pdf": "application/pdf",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};

type PresignErrorCode =
  | "session_missing"
  | "reauth_required"
  | "session_mismatch"
  | "tenant_not_configured"
  | "permission_denied"
  | "upload_unavailable"
  | "invalid_request";

const ERROR_MESSAGES: Record<PresignErrorCode, string> = {
  session_missing: "ログインしてください",
  reauth_required: "ログイン情報を更新してください",
  session_mismatch: "ログイン設定が変更されました。ログインし直してください",
  tenant_not_configured: "アカウント設定が未完了です。管理者に確認してください",
  permission_denied: "この操作を行う権限がありません。管理者に確認してください",
  upload_unavailable: "アップロード設定を確認してください",
  invalid_request: "アップロード内容を確認してください",
};

function flagEnabled(value: string): boolean {
  return value === "1" || value.toLowerCase() === "true";
}

function enabled(): boolean {
  const presignedUpload = process.env.RAKU_ENABLE_UPLOAD_PRESIGN;
  if (presignedUpload !== undefined) return flagEnabled(presignedUpload);

  // Backward compatibility with earlier deployments that used the shared upload sink flag for both
  // S3 presign and the local inline fallback. New production deploys should set
  // RAKU_ENABLE_UPLOAD_PRESIGN so the two routes can be gated independently.
  const uploadSink = process.env.RAKU_ENABLE_UPLOAD_SINK;
  if (uploadSink !== undefined) return flagEnabled(uploadSink);

  const raw = process.env.RAKU_ENABLE_DEV_TOKEN_ISSUER;
  if (raw !== undefined) return flagEnabled(raw);
  return process.env.NODE_ENV !== "production";
}

function uploadBucket(): string {
  return process.env.RAKU_UPLOAD_BUCKET || process.env.DOCUMENT_BUCKET || "";
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function jsonError(
  message: string,
  status: number,
  errorCode: PresignErrorCode = "invalid_request",
): NextResponse {
  return NextResponse.json({ error_code: errorCode, error: message }, { status });
}

function safeFilename(rawName: string): string {
  return (rawName || "upload.bin").replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 120);
}

function safeObjectSegment(value: string): string {
  return encodeURIComponent(value).slice(0, 180);
}

type VerifiedPrincipal = {
  tenant_id: string;
  user_id: string;
};

function principalFromWhoami(value: unknown): VerifiedPrincipal | null {
  if (!value || typeof value !== "object") return null;
  const principal = (value as { principal?: unknown }).principal;
  if (!principal || typeof principal !== "object") return null;
  const tenantId = (principal as { tenant_id?: unknown }).tenant_id;
  const userId = (principal as { user_id?: unknown }).user_id;
  if (typeof tenantId !== "string" || !tenantId.trim()) return null;
  if (typeof userId !== "string" || !userId.trim()) return null;
  return { tenant_id: tenantId.trim(), user_id: userId.trim() };
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const [, payload] = token.split(".");
    if (!payload) return null;
    return JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function claimString(claims: Record<string, unknown> | null, key: string): string {
  const value = claims?.[key];
  return typeof value === "string" ? value.trim() : "";
}

function normalizedIssuer(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function first(...values: Array<string | undefined>): string {
  return values.find((value) => value && value.trim()) ?? "";
}

function claimMatchesStringOrArray(value: unknown, expected: string): boolean {
  if (!expected) return true;
  if (typeof value === "string") return value === expected;
  return Array.isArray(value) && value.includes(expected);
}

function tokenClientMatches(claims: Record<string, unknown>, clientId: string): boolean {
  return claimMatchesStringOrArray(claims.aud, clientId) || claimString(claims, "client_id") === clientId;
}

function classifyBearerToken(authorization: string): PresignErrorCode {
  const token = authorization.replace(/^bearer\s+/i, "").trim();
  const claims = decodeJwtPayload(token);
  if (!claims) return "reauth_required";

  const now = Math.floor(Date.now() / 1000);
  if (typeof claims.exp !== "number" || claims.exp <= now + 30) return "reauth_required";
  if (typeof claims.nbf === "number" && claims.nbf > now) return "reauth_required";
  const tokenUse = claimString(claims, "token_use");
  if (tokenUse !== "id" && tokenUse !== "access") return "reauth_required";

  const issuer = first(process.env.COGNITO_ISSUER, process.env.NEXT_PUBLIC_COGNITO_ISSUER);
  if (issuer && normalizedIssuer(claimString(claims, "iss")) !== normalizedIssuer(issuer)) {
    return "session_mismatch";
  }
  const clientId = first(
    process.env.COGNITO_CLIENT_ID,
    process.env.COGNITO_USER_POOL_CLIENT_ID,
    process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID,
  );
  if (clientId && !tokenClientMatches(claims, clientId)) return "session_mismatch";
  if (!claimString(claims, "custom:tenant_id")) return "tenant_not_configured";
  return "session_mismatch";
}

function publicOrigin(req: Request): string {
  const url = new URL(req.url);
  const host = req.headers.get("x-forwarded-host") || req.headers.get("host") || url.host;
  const proto = req.headers.get("x-forwarded-proto") || url.protocol.replace(/:$/, "") || "http";
  return `${proto}://${host}`;
}

async function assertAppSession(req: Request): Promise<{ principal: VerifiedPrincipal } | Response> {
  const authorization = req.headers.get("authorization") || "";
  if (!authorization.toLowerCase().startsWith("bearer ")) {
    return jsonError(ERROR_MESSAGES.session_missing, 401, "session_missing");
  }

  const origin = publicOrigin(req);
  const headers: Record<string, string> = { authorization };
  const userToken = req.headers.get("x-user-token");
  if (userToken) headers["x-user-token"] = userToken;

  try {
    const res = await fetch(`${origin}/v1/whoami`, {
      method: "GET",
      headers,
      cache: "no-store",
    });
    if (!res.ok) {
      const code =
        res.status === 403 ? "permission_denied" : classifyBearerToken(authorization);
      return jsonError(ERROR_MESSAGES[code], res.status === 403 ? 403 : 401, code);
    }
    const principal = principalFromWhoami(await res.json().catch(() => null));
    if (!principal) {
      return jsonError(ERROR_MESSAGES.tenant_not_configured, 401, "tenant_not_configured");
    }
    return { principal };
  } catch {
    return jsonError("セッション確認に失敗しました。少し待ってから再試行してください", 502, "upload_unavailable");
  }
}

export async function POST(req: Request) {
  if (!enabled()) {
    return jsonError("この環境ではファイルアップロードが無効です", 403, "upload_unavailable");
  }
  const bucket = uploadBucket();
  if (!bucket) {
    return jsonError("S3 アップロードバケットが設定されていません", 501, "upload_unavailable");
  }

  const session = await assertAppSession(req);
  if (session instanceof Response) return session;

  const body = (await req.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body) {
    return jsonError("アップロード内容を確認してください", 400, "invalid_request");
  }

  const filename = safeFilename(text(body.filename));
  const size = Number(body.size);
  if (!Number.isFinite(size) || size <= 0) {
    return jsonError("ファイルサイズを確認してください", 400, "invalid_request");
  }
  if (size > MAX_BYTES) {
    return jsonError("ファイルが大きすぎます（最大25MB）", 413, "invalid_request");
  }

  const ext = path.extname(filename).toLowerCase();
  const requestedContentType = text(body.content_type);
  const contentType = EXT_CONTENT_TYPE[ext] ?? (requestedContentType || "application/octet-stream");
  const uploadId = randomUUID();
  const tenantSegment = safeObjectSegment(session.principal.tenant_id);
  const userSegment = safeObjectSegment(session.principal.user_id);
  const day = new Date().toISOString().slice(0, 10);
  const key = `tenants/${tenantSegment}/uploads/${day}/${uploadId}${ext || ".bin"}`;
  const region = process.env.AWS_REGION || process.env.AWS_DEFAULT_REGION || "ap-northeast-1";
  const metadataHeaders = {
    "x-amz-meta-raku-tenant-id": tenantSegment,
    "x-amz-meta-raku-user-id": userSegment,
    "x-amz-meta-raku-upload-id": uploadId,
  };
  const uploadHeaders = { "content-type": contentType, ...metadataHeaders };

  // 0045: register the provenance record BEFORE the browser gets a PUT URL (fail-closed). Ingest
  // resolves upload_id -> (bucket, key) from this record and consumes it once.
  const registerRes = await fetch(`${publicOrigin(req)}/v1/uploads`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: req.headers.get("authorization") || "",
      ...(req.headers.get("x-user-token")
        ? { "x-user-token": req.headers.get("x-user-token") as string }
        : {}),
    },
    cache: "no-store",
    body: JSON.stringify({
      upload_id: uploadId,
      bucket,
      object_key: key,
      content_type: contentType,
      content_length: size,
      filename,
    }),
  }).catch(() => null);
  if (!registerRes || !registerRes.ok) {
    return jsonError("アップロード準備に失敗しました。少し待って再試行してください", 502, "upload_unavailable");
  }

  const client = new S3Client({ region });
  const command = new PutObjectCommand({
    Bucket: bucket,
    Key: key,
    ContentType: contentType,
    Metadata: {
      "raku-tenant-id": tenantSegment,
      "raku-user-id": userSegment,
      "raku-upload-id": uploadId,
    },
  });
  const uploadUrl = await getSignedUrl(client, command, {
    expiresIn: SIGNED_URL_TTL_SECONDS,
    signableHeaders: new Set(Object.keys(uploadHeaders)),
    unhoistableHeaders: new Set(Object.keys(metadataHeaders)),
  });

  return NextResponse.json({
    upload_url: uploadUrl,
    method: "PUT",
    headers: uploadHeaders,
    ref: `s3://${bucket}/${key}`,
    upload_id: uploadId,
    filename,
    size,
    content_type: contentType,
    storage: "s3",
    tenant_prefix: `tenants/${tenantSegment}/uploads/`,
    expires_in: SIGNED_URL_TTL_SECONDS,
  });
}
