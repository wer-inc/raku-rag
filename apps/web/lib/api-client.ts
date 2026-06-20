import type { AnswerRequest, AnswerResponse } from "@raku-rag/shared";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:3000/v1";

async function jsonOrThrow<T>(res: Response): Promise<T> {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = typeof body?.message === "string" ? body.message : `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return body as T;
}

export async function apiHealth(): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/health`, { cache: "no-store" });
  return jsonOrThrow<{ status: string }>(res);
}

// Phase 0 skeleton: typed client surface. Real wiring (auth headers, streaming) lands in Phase 1.
export async function answer(req: AnswerRequest, userToken: string): Promise<AnswerResponse> {
  const res = await fetch(`${API_BASE}/answer`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: "Bearer local-dev-key",
      "x-user-token": userToken,
    },
    body: JSON.stringify(req),
  });
  return jsonOrThrow<AnswerResponse>(res);
}
