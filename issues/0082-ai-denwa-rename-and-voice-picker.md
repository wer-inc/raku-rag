# 0082 — 「電話AI」→「AI電話」表記変更 + 通話シミュレータに読み上げ音声セレクタ(系統 = web / phone / UX)

> Priority: **P3/Low** / Status: Fixed / Labels: `web`, `ux`, `phone`, `a11y`, `stg`

## 背景

- ナビ表記を「電話AI」から「AI電話」へ変更したい。
- 通話シミュレータ(音声モード)で喋る声は、コードが `lang="ja-JP"` を指定するだけで voice 未指定 →
  ブラウザ/OS 既定の日本語音声(多くは女性)。声・速度・高さを変えたい。

## どう解決したか

**① リネーム:** サイドバー nav ラベル(`full-saas.ts`)+ タブ `aria-label` を「AI電話」に。
nav ラベルはパンくず(`navLabelFor`)にも波及。

**② 読み上げ音声セレクタ(ユーザー選択案「ブラウザ試聴に声セレクタ追加」):**
- `lib/voice-prefs.ts`(新規):`{voiceURI, rate, pitch}` を localStorage 保存(`load/saveVoicePrefs`、
  rate 0.5–2.0 / pitch 0–2 を clamp)。
- 通話シミュレータの音声モードに設定パネルを追加:
  - **声** = `speechSynthesis.getVoices()` の日本語音声から選択(`voiceschanged` で非同期ロード。
    既定=「ブラウザ既定(日本語)」)。
  - **速度 / 高さ** = レンジスライダー。
  - **試聴** ボタン = 現在の設定でサンプル文を読み上げ。
  - `applyVoicePrefs(utterance)` を読み上げ(`speakTurn`)と試聴の両方に適用。
- 制約(既知):選べる声は**その端末にインストール済みの日本語音声のみ**(多くは女性1種。男性は端末次第)。
  端末非依存で男性含む声が欲しい場合は本番の Amazon Connect / Polly 経路(Mizuki/Takumi 等)が本命 → 別途。

## どこ

- `apps/web/lib/full-saas.ts`(nav ラベル)
- `apps/web/app/components/FullSaasScreen.tsx`(aria-label / voice picker / `applyVoicePrefs` / `previewVoice`)
- `apps/web/lib/voice-prefs.ts`(新規)、`apps/web/app/globals.css`(`.phone-voice-settings`)
- `tests/contract/test_web_phone_voice.py`(新規)

## QA

- [x] `tsc --noEmit` 0 / `next build` 成功。契約テスト GREEN(3 cases)。
- [ ] stg 反映後、音声モードON→声/速度/高さ変更→試聴で反映を実機確認(HTTPS 必須)。

## 参照

- `src/raku_rag/phone/voice.py`(本番は Polly 前提)、memory: phone-connect-024-groundwork
