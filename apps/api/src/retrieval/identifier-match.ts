export const DEFAULT_IDENTIFIER_FIELDS = [
  "equipment_id",
  "alarm_code",
  "property_id",
  "room_number",
  "contract_id",
  "fund_id",
  "isin",
  "invoice_id",
];

export interface IdentifierMatch {
  field: string;
  value: string;
  normalized: string;
}

export function normalizeIdentifier(value: unknown): string {
  return String(value ?? "")
    .normalize("NFKC")
    .trim()
    .toUpperCase()
    .replace(/[‐‑‒–—−ー―\-_/#:\s.]/g, "");
}

export function extractIdentifierTokens(query: string): string[] {
  const rawTokens = query.match(/[A-Za-z0-9][A-Za-z0-9._:/#\-\s]{1,}[A-Za-z0-9]/g) ?? [];
  const normalized = rawTokens
    .map((token) => normalizeIdentifier(token))
    .filter((token) => token.length >= 2);
  return [...new Set(normalized)];
}

export function findIdentifierMatches(
  query: string,
  metadata: Record<string, unknown>,
  fields: string[] = DEFAULT_IDENTIFIER_FIELDS,
): IdentifierMatch[] {
  const queryTokens = extractIdentifierTokens(query);
  const matches: IdentifierMatch[] = [];
  for (const field of fields) {
    const raw = metadata[field];
    if (raw === undefined || raw === null || raw === "") {
      continue;
    }
    const normalized = normalizeIdentifier(raw);
    if (normalized.length < 2) {
      continue;
    }
    if (queryTokens.some((token) => token === normalized || token.includes(normalized))) {
      matches.push({ field, value: String(raw), normalized });
    }
  }
  return matches;
}
