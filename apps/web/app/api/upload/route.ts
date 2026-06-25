import path from "path";
import { NextResponse } from "next/server";

// Upload sink: returns the uploaded bytes as an inline `data:` ref (RFC 2397). The answer-service's
// DataUriConnector decodes it in-request, so ingestion works even though web and the Python
// answer-service run as SEPARATE containers with no shared filesystem (a `file://` ref written here
// would 500 on the answer-service — it can't see this container's disk). The Add Source screen
// uploads here, then calls POST /v1/ingest with the returned ref. Disabled in production builds
// unless the demo flag is set.

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const MAX_BYTES = 10 * 1024 * 1024; // 10MB

const EXT_CONTENT_TYPE: Record<string, string> = {
  ".txt": "text/plain",
  ".md": "text/markdown",
  ".markdown": "text/markdown",
  ".html": "text/html",
  ".htm": "text/html",
  ".csv": "text/csv",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};

function enabled(): boolean {
  // Same demo gate as the dev-token issuer: honor an explicit RAKU_ENABLE_DEV_TOKEN_ISSUER=1 even in
  // production (the AWS demo sets it), else default dev-only (off in production).
  const raw = process.env.RAKU_ENABLE_DEV_TOKEN_ISSUER;
  if (raw !== undefined) return raw === "1" || raw.toLowerCase() === "true";
  return process.env.NODE_ENV !== "production";
}

export async function POST(req: Request) {
  if (!enabled()) {
    return NextResponse.json({ error: "local upload sink disabled" }, { status: 403 });
  }
  const form = await req.formData().catch(() => null);
  const file = form?.get("file");
  if (!(file instanceof File)) {
    return NextResponse.json({ error: "file is required" }, { status: 400 });
  }
  if (file.size === 0) {
    return NextResponse.json({ error: "file is empty" }, { status: 400 });
  }
  if (file.size > MAX_BYTES) {
    return NextResponse.json({ error: "file too large (max 10MB)" }, { status: 413 });
  }

  const safeName = (file.name || "upload.txt").replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 120);
  const ext = path.extname(safeName).toLowerCase();
  const contentType = EXT_CONTENT_TYPE[ext] ?? "text/plain";

  const buf = Buffer.from(await file.arrayBuffer());
  // Inline the bytes as a base64 data: ref — container-boundary-safe (see file header).
  const ref = `data:${contentType};base64,${buf.toString("base64")}`;

  return NextResponse.json({
    ref,
    filename: safeName,
    size: buf.length,
    content_type: contentType,
  });
}
