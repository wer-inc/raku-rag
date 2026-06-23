import fs from "fs";
import path from "path";
import type { ManifestScreen } from "./full-saas";

type ManifestFile = { screens: ManifestScreen[] };

function escapePattern(route: string): RegExp {
  const escaped = route.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/:[^/]+/g, "[^/]+");
  return new RegExp(`^${escaped}$`);
}

export function loadStandaloneScreen(pathname: string): ManifestScreen | null {
  const filePath = path.resolve(process.cwd(), "..", "..", "specs/full-saas/screens.manifest.json");
  const raw = fs.readFileSync(filePath, "utf8");
  const manifest = JSON.parse(raw) as ManifestFile;
  return (
    manifest.screens.find((screen) => screen.route === pathname) ??
    manifest.screens.find((screen) => screen.route.includes(":") && escapePattern(screen.route).test(pathname)) ??
    null
  );
}
