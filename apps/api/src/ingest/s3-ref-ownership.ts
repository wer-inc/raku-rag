import { BadRequestException, ForbiddenException } from "@nestjs/common";

function tenantPrefixSegment(tenantId: string): string {
  return encodeURIComponent(tenantId).slice(0, 180);
}

function allowedBuckets(): Set<string> {
  const raw = [
    process.env.RAKU_ALLOWED_INGEST_BUCKETS,
    process.env.RAKU_UPLOAD_BUCKET,
    process.env.DOCUMENT_BUCKET,
    process.env.S3_BUCKET,
  ]
    .filter((value): value is string => typeof value === "string")
    .flatMap((value) => value.split(","))
    .map((value) => value.trim())
    .filter(Boolean);
  return new Set(raw);
}

function parseS3Ref(ref: string): { bucket: string; key: string } {
  const rest = ref.slice("s3://".length);
  const slash = rest.indexOf("/");
  if (slash <= 0 || slash === rest.length - 1) {
    throw new BadRequestException("invalid s3 document ref");
  }
  return { bucket: rest.slice(0, slash), key: rest.slice(slash + 1) };
}

export function assertDocumentRefOwnedByTenant(ref: unknown, tenantId: string): void {
  if (typeof ref !== "string" || !ref.startsWith("s3://")) {
    return;
  }

  const { bucket, key } = parseS3Ref(ref);
  const buckets = allowedBuckets();
  if (buckets.size === 0) {
    throw new BadRequestException("S3 ingest bucket is not configured");
  }
  if (!buckets.has(bucket)) {
    throw new ForbiddenException("S3 document ref bucket is not allowed");
  }

  const expectedPrefix = `tenants/${tenantPrefixSegment(tenantId)}/uploads/`;
  if (!key.startsWith(expectedPrefix)) {
    throw new ForbiddenException("S3 document ref is not owned by the authenticated tenant");
  }
}
