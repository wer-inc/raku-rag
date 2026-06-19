import { apiHealth } from "../lib/api-client";

// Phase 0 skeleton page — proves the web app boots and can reach the API health route.
export default async function Home() {
  let status = "unknown";
  try {
    status = (await apiHealth()).status;
  } catch {
    status = "api unreachable (start the API: npm run dev:api)";
  }
  return (
    <main style={{ fontFamily: "system-ui", padding: 32 }}>
      <h1>raku-rag — local foundation</h1>
      <p>Phase 0 web skeleton (Next.js + Vercel AI SDK).</p>
      <p>API health: {status}</p>
    </main>
  );
}
