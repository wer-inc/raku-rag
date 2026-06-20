export const CURRENT_API_VERSION = "1";

const VERSION_RE = /^\/v(?<version>[0-9]+)(?:\/|$)/;

export interface VersionHeaderPolicy {
  version: string;
  headers: Record<string, string>;
}

export function versionFromPath(path: string): string {
  return VERSION_RE.exec(path)?.groups?.version ?? CURRENT_API_VERSION;
}

export function versionHeaderPolicy(path: string, env: NodeJS.ProcessEnv = process.env): VersionHeaderPolicy {
  const version = versionFromPath(path);
  const headers: Record<string, string> = {
    "api-version": version,
  };

  const prefix = `RAKU_API_V${version}_`;
  const deprecated = env[`${prefix}DEPRECATED`] === "1" || env[`${prefix}DEPRECATED`] === "true";
  if (deprecated) {
    headers.Deprecation = env[`${prefix}DEPRECATION`] || "true";
    const sunset = env[`${prefix}SUNSET`];
    if (sunset) {
      headers.Sunset = sunset;
    }
    const deprecationUrl = env[`${prefix}DEPRECATION_URL`];
    if (deprecationUrl) {
      headers.Link = `<${deprecationUrl}>; rel="deprecation"`;
    }
  }

  return { version, headers };
}
