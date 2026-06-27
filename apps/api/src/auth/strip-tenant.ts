/**
 * Defense-in-depth: recursively remove any `tenant_id` field from a request body before it is
 * forwarded to the answer-service. The authoritative tenant is always the signed principal
 * (forwarded as the `x-raku-tenant-id` header), never a client-supplied body field — stripping it
 * here makes a client-side tenant override impossible regardless of the downstream handler.
 *
 * Single source of truth shared by every proxy controller (settings / jobs / eval / …).
 */
export function stripTenantOverrides(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => stripTenantOverrides(item));
  }
  if (value && typeof value === "object") {
    const cleaned: Record<string, unknown> = {};
    for (const [key, child] of Object.entries(value)) {
      if (key !== "tenant_id") {
        cleaned[key] = stripTenantOverrides(child);
      }
    }
    return cleaned;
  }
  return value;
}
