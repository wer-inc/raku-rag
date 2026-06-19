// ADR-015 lock: every policy/config entity carries these lifecycle fields FROM THE START so future
// versioning / runtime editing is non-breaking. Runtime editing itself is out of Phase 0/1 scope.
export interface PolicyLifecycle {
  profile_version: number;
  schema_version: number;
  /** ISO-8601; null = effective immediately */
  effective_from: string | null;
  /** ISO-8601; null = not deprecated */
  deprecated_at: string | null;
}
