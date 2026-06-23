import FullSaasScreen from "../components/FullSaasScreen";
import { loadStandaloneScreen } from "../../lib/standalone-screen";

export default async function FullSaasRoute({
  params,
}: {
  params: Promise<{ slug?: string[] }>;
}) {
  const resolved = await params;
  const pathname = `/${(resolved.slug ?? []).map((part) => part.trim()).filter(Boolean).join("/")}` || "/";
  const screen = loadStandaloneScreen(pathname);

  if (!screen) {
    return (
      <section className="workspace" aria-label="Not found">
        <header className="topbar">
          <div>
            <p className="eyebrow">Full SaaS workspace</p>
            <h2>Unknown route</h2>
          </div>
        </header>
        <p className="ops-empty">No screen is registered for {pathname}.</p>
      </section>
    );
  }

  return <FullSaasScreen pathname={pathname} screen={screen} />;
}
