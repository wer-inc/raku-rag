// Browser TTS voice preferences for the AI電話 call simulator (通話シミュレータ voice mode).
// The available voices come from the browser/OS (`speechSynthesis.getVoices()`), so this only records
// the user's pick (by voiceURI) plus rate/pitch; an empty voiceURI means "browser default (ja-JP)".

export interface VoicePrefs {
  voiceURI: string | null;
  rate: number; // 0.5–2.0 (1.0 = normal)
  pitch: number; // 0–2 (1.0 = normal)
}

const KEY = "raku.phoneVoicePrefs";
export const DEFAULT_VOICE_PREFS: VoicePrefs = { voiceURI: null, rate: 1, pitch: 1 };

export function clampRate(value: unknown): number {
  const n = Number(value);
  if (!Number.isFinite(n)) return 1;
  return Math.min(2, Math.max(0.5, n));
}

export function clampPitch(value: unknown): number {
  const n = Number(value);
  if (!Number.isFinite(n)) return 1;
  return Math.min(2, Math.max(0, n));
}

export function loadVoicePrefs(): VoicePrefs {
  if (typeof window === "undefined") return { ...DEFAULT_VOICE_PREFS };
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return { ...DEFAULT_VOICE_PREFS };
    const parsed = JSON.parse(raw) as Partial<VoicePrefs>;
    return {
      voiceURI: typeof parsed.voiceURI === "string" && parsed.voiceURI ? parsed.voiceURI : null,
      rate: clampRate(parsed.rate),
      pitch: clampPitch(parsed.pitch),
    };
  } catch {
    return { ...DEFAULT_VOICE_PREFS };
  }
}

export function saveVoicePrefs(prefs: VoicePrefs): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      KEY,
      JSON.stringify({
        voiceURI: prefs.voiceURI || null,
        rate: clampRate(prefs.rate),
        pitch: clampPitch(prefs.pitch),
      }),
    );
  } catch {
    /* best-effort */
  }
}
