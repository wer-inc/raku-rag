"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const INDUSTRIES = ["製造", "建設", "エネルギー", "医療機器"] as const;
const USES = ["現場の手順照会", "トラブル対応", "教育・研修", "品質レビュー"] as const;

// U6/U7: honest single-step onboarding — the chips are real controls whose selections are stored
// locally for future defaults; no fake "ステップ 1 / 3" framing, and skipping is explicitly OK.
const STORAGE_KEY = "raku.onboarding.preferences";

export default function OnboardingPage() {
  const router = useRouter();
  const [industry, setIndustry] = useState<string | null>(null);
  const [uses, setUses] = useState<string[]>([]);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw) as { industry?: unknown; uses?: unknown };
      if (typeof saved.industry === "string" && (INDUSTRIES as readonly string[]).includes(saved.industry)) {
        setIndustry(saved.industry);
      }
      if (Array.isArray(saved.uses)) {
        setUses(saved.uses.filter((u): u is string => typeof u === "string" && (USES as readonly string[]).includes(u)));
      }
    } catch {
      // Corrupt/blocked storage — start unselected.
    }
  }, []);

  function toggleUse(item: string) {
    setUses((current) => (current.includes(item) ? current.filter((u) => u !== item) : [...current, item]));
  }

  function onStart() {
    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ industry, uses, saved_at: new Date().toISOString() }),
      );
    } catch {
      // Storage unavailable — continue anyway; the selection is optional.
    }
    router.push("/home");
  }

  return (
    <div className="auth-center-page">
      <div className="auth-center-card auth-onboarding-card">
        <div className="auth-step">セットアップ（任意）</div>
        <h1>利用目的を選ぶ</h1>
        <p className="auth-subtle">
          選択はこのブラウザに保存され、今後の初期設定の改善に使われます。選択せずに開始しても構いません。
        </p>

        <div className="auth-chip-group">
          <div>
            <h2>業種</h2>
            <div className="auth-chips" role="group" aria-label="業種">
              {INDUSTRIES.map((item) => (
                <button
                  key={item}
                  type="button"
                  className={industry === item ? "auth-chip active" : "auth-chip"}
                  aria-pressed={industry === item}
                  onClick={() => setIndustry((current) => (current === item ? null : item))}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>
          <div>
            <h2>主な利用目的（複数可）</h2>
            <div className="auth-chips" role="group" aria-label="主な利用目的">
              {USES.map((item) => (
                <button
                  key={item}
                  type="button"
                  className={uses.includes(item) ? "auth-chip active" : "auth-chip"}
                  aria-pressed={uses.includes(item)}
                  onClick={() => toggleUse(item)}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>
        </div>

        <button className="auth-primary auth-primary-wide" type="button" onClick={onStart}>
          {industry || uses.length > 0 ? "この設定で開始する" : "選択せずに開始する"}
        </button>
      </div>
    </div>
  );
}
