# Research: Live Telephony Adapter

**Feature**: `024-phone-live-telephony` · **Date**: 2026-07-02

## Decision 1: Production telephony target は Amazon Connect(022 Open Question #1 の解決)

**Decision**: Amazon Connect(東京リージョン、既存 stg アカウント)を最初の実電話基盤とする。
ユーザー決定 2026-07-02。

**Rationale**:
- AWS 完結: 請求・IAM・監視・OIDC デプロイが現行スタックと一元(運用者1名の体制で新ベンダー管理を増やさない)。
- 人間転送が標準装備: キュー+CCP(ブラウザのオペレータ画面)が US2 の HandoffPackage 設計とそのまま噛み合う。
- ASR/TTS/バージイン内蔵(Lex V2 ja-JP / Polly neural)。
- 番号コスト: 050 DID $0.10/日+着信 $0.003/分(+サービス料 $0.018/分)でデモ運用は誤差レベル。

**Alternatives considered**:
- **Twilio**: 実装最小(Webhook のみ)・トライアルで即日試験可だが、新ベンダー契約/別請求が増え、
  人間転送は `<Dial>` 自作になる。JP 050 も結局書類審査があり番号リードタイム優位は小さい。
- **Chime SDK / 自前 SIP**: 柔軟だが運用負荷・JP 番号制約から却下。

## Decision 2: 会話ループは Contact Flow 主導 + 最小 Lex(NLU に判断させない)

**Decision**: Lex V2 は「ja-JP の音声→テキスト変換器」としてだけ使う(FallbackIntent のみ・スロットなし・
fulfillment なし)。ループ制御は Contact Flow(Get customer input → Invoke Lambda → 分岐 → Play)で行い、
`ask_clarification / answer_with_citations / handoff / fallback / end_call` の判断は 022 orchestrator の
返す `ai_action` に完全委譲する。

**Rationale**: 022 Decision 4(状態遷移はルールで閉じる)を電話でも維持する。Lex に intent/slot を
持たせると判断が二重化し、安全境界が曖昧になる。

**Alternatives**: Lex dialog + code hook 主導(NLU 二重管理になるため却下)。

## Decision 3: アダプタ Lambda は VPC 内から answer-service 内部 ALB を直接呼ぶ

**Decision**: Python 3.12 stdlib-only Lambda(依存ゼロ・ビルド不要)を private subnet に置き、
`http://<internal-alb>/internal/phone/*` を `X-Internal-Auth`(Secrets Manager)+ 合成 `x-raku-*`
ヘッダで呼ぶ。公開 API(Cognito/dev トークン)は経由しない。

**Rationale**: NestJS 公開面に電話用のマシン認証を新設するより、既存の service-to-service 境界
(API→answer-service と同じゲート)を再利用する方が攻撃面が増えない。stdlib-only は本リポの
Tier A 哲学と一致し、Lambda バンドラも不要。

## Decision 4: 電話チャネルの principal は専用サービスロール `phone_gateway`

**Decision**: DID マッピング(SSM `raku-rag/<stage>/phone/did-map`)が
`{tenant_id, user_id, groups, collection_id, scenario_id}` を与える。orchestrator は
`phone_gateway` ロールを simulate/turn に限り許可(通話閲覧・転送受理・シナリオ管理には不可)。
ナレッジ可視範囲は既存 ACL のまま(サービスユーザー/グループへの grant で管理)。

**Rationale**: `tenant_admin` をゲートウェイに渡すのは過剰権限。「電話が読める知識」=
「そのサービスユーザーに grant された知識」という既存 ACL の一物一権に載せる。

## Decision 5: 音声整形は `speech_text` として応答に併載(置換しない)

**Decision**: `render_for_voice()` が markdown/箇条書き/URL を落とし、~3文・~160字に短縮し、
打切り時は「続きをお聞きになりますか」を付ける。`ai_response_text`(UI/履歴用)は不変。
引用は音声で読み上げない(通話履歴・オペレータ画面で確認)。

## Decision 6: Connect リソースの IaC 境界

**Decision**: CDK は `phoneTelephony=connect` コンテキスト時のみ Lambda+SG+Secrets/SSM を合成。
Connect インスタンス・番号・Lex bot・Contact Flow は初回コンソール手作業とし、取込み用
アーティファクト(`infra/connect/contact-flow.json`, `lex-bot-definition.md`)と runbook を提供する。

**Rationale**: 番号取得が人間手続きである以上、インスタンスも手作業が自然。Flow は反復編集が
コンソールの方が速い。CFN 化(AWS::Connect::ContactFlow / AWS::Lex::Bot)は安定後の後続タスク。

## Open Questions

1. 0120/0800(フリーダイヤル)を商用時に追加するか(コストは 050 の約5倍/分)。
2. Contact Flow / Lex の CFN 管理化のタイミング。
3. 通話録音ポリシー(現状 OFF・transcript-first)を変えるテナント要件が出るか。
