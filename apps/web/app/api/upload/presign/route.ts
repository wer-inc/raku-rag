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

function jsonError(message: string, status: number): NextResponse {
  return NextResponse.json({ error: message }, { status });
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

function publicOrigin(req: Request): string {
  const url = new URL(req.url);
  const host = req.headers.get("x-forwarded-host") || req.headers.get("host") || url.host;
  const proto = req.headers.get("x-forwarded-proto") || url.protocol.replace(/:$/, "") || "http";
  return `${proto}://${host}`;
}

async function assertAppSession(req: Request): Promise<{ principal: VerifiedPrincipal } | Response> {
  const authorization = req.headers.get("authorization") || "";
  if (!authorization.toLowerCase().startsWith("bearer ")) {
    return jsonError("Cognito session is missing; sign in again", 401);
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
      return jsonError("Cognito session is invalid; sign in again", 401);
    }
    const principal = principalFromWhoami(await res.json().catch(() => null));
    if (!principal) {
      return jsonError("could not resolve tenant before upload", 401);
    }
    return { principal };
  } catch {
    return jsonError("could not verify session before upload", 502);
  }
}

export async function POST(req: Request) {
  if (!enabled()) {
    return jsonError("upload sink disabled", 403);
  }
  const bucket = uploadBucket();
  if (!bucket) {
    return jsonError("S3 upload bucket is not configured", 501);
  }

  const session = await assertAppSession(req);
  if (session instanceof Response) return session;

  const body = (await req.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body) {
    return jsonError("invalid JSON body", 400);
  }

  const filename = safeFilename(text(body.filename));
  const size = Number(body.size);
  if (!Number.isFinite(size) || size <= 0) {
    return jsonError("file size is required", 400);
  }
  if (size > MAX_BYTES) {
    return jsonError("file too large (max 25MB)", 413);
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
    return jsonError("could not register upload before presigning", 502);
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
