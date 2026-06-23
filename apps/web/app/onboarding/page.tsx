"use client";

import { useRouter } from "next/navigation";

const INDUSTRIES = ["製造", "建設", "エネルギー", "医療機器"] as const;
const USES = ["現場の手順照会", "トラブル対応", "教育・研修", "品質レビュー"] as const;

export default function OnboardingPage() {
  const router = useRouter();
  return (
    <div className="auth-center-page">
      <div className="auth-center-card auth-onboarding-card">
        <div className="auth-step">セットアップ · ステップ 1 / 3</div>
        <h1>ワークスペースを初期設定</h1>
        <p className="auth-subtle">
          業種と利用目的を選ぶと、retrieval プロファイルと安全ルールの初期値が設定されます。
        </p>

        <div className="auth-chip-group">
          <div>
            <h2>業種</h2>
            <div className="auth-chips">
              {INDUSTRIES.map((item, index) => (
                <span key={item} className={index === 0 ? "auth-chip active" : "auth-chip"}>
                  {item}
                </span>
              ))}
            </div>
          </div>
          <div>
            <h2>主な利用目的</h2>
            <div className="auth-chips">
              {USES.map((item, index) => (
                <span key={item} className={index < 2 ? "auth-chip active" : "auth-chip"}>
                  {item}
                </span>
              ))}
            </div>
          </div>
        </div>

        <button className="auth-primary auth-primary-wide" type="button" onClick={() => router.push("/home")}>
          この設定で開始する
        </button>
      </div>
    </div>
  );
}
