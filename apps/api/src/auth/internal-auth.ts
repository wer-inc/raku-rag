/**
 * Internal-boundary auth header for API -> answer-service calls.
 *
 * The Python answer-service enforces a shared-secret gate on every `/internal/*` route when
 * `RAKU_INTERNAL_AUTH_SECRET` is set (no-op when empty). The API must present the same secret in an
 * `X-Internal-Auth` header or the call 401s (surfacing as a 502 at the API facade). Spread this into
 * every outbound header object so the gate is satisfied uniformly. When the secret is unset (local
 * loopback / dev) this returns `{}` and the gate stays a no-op — no behaviour change.
 */
export function internalAuthHeaders(): Record<string, string> {
  const secret = process.env.RAKU_INTERNAL_AUTH_SECRET;
  return secret ? { "X-Internal-Auth": secret } : {};
}
