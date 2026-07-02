# Tasks: Live Telephony Adapter (Amazon Connect)

**Input**: `specs/024-phone-live-telephony/spec.md` / `research.md`

## Phase 1: Voice rendering(基盤・課金ゼロ)

- [x] L001 `src/raku_rag/phone/voice.py` — `render_for_voice()`: markdown/箇条書き/表/URL 除去、
  文分割、≤3文/≤160字への短縮+続き案内、引用ID非読上げ。
- [x] L002 orchestrator: AI turn payload に `speech_text` を追加(`_turn_payload` / transcript)。
- [x] L003 [P] `tests/unit/test_phone_voice.py` — 整形規則(JP文分割・打切り・除去)+ turn payload 併載。

## Phase 2: Connect アダプタ(課金ゼロ・fixtureで検証)

- [x] L010 `infra/connect/lambda/connect_phone_adapter.py` — stdlib-only handler:
  `call_start`(simulate, utterances=[], channel="connect", provider_call_id=ContactId)/
  `turn`(InputTranscript→/turns)。応答を flow 属性(ai_action/speech_text/call_id/handoff_url)に平坦化。
- [x] L011 DID 解決: env `RAKU_PHONE_DID_MAP`(SSM 由来 JSON)→ {tenant_id,user_id,groups,collection_id,scenario_id}。
  未登録 DID は `action=reject` を返す(fail-closed)。
- [x] L012 認証/秘匿: `X-Internal-Auth` を env(Secrets 注入)から付与。発信者番号は **Lambda 内でマスク**して
  caller.phone_number に渡す(raw E.164 を外へ出さない)。
- [x] L013 orchestrator: `phone_gateway` ロールを SIMULATE(simulate/turn)のみに許可、
  read/handoff/scenario 系では不可のテストを追加。
- [x] L014 [P] `tests/unit/test_phone_connect_adapter.py`(+ 実HTTPスタック経由の `tests/integration/test_phone_connect_flow.py`) — Connect イベント fixture
  (`tests/fixtures/phone/connect_events.json`)で call_start/turn/handoff/end_call/未登録DID/API障害
  (=fallback 属性)を検証。boto3 非依存で import 可能なこと。
- [x] L015 [P] `tests/security/test_phone_gateway_role.py` — phone_gateway の権限最小性
  (simulate/turn 可・calls/handoffs/scenarios 読み書き不可)+ raw 番号がヘッダ/ボディに出ない。

## Phase 3: IaC + 取込みアーティファクト

- [x] L020 CDK `phoneTelephony=connect`(default off): Lambda(VPC private subnets)、
  answer-service ALB SG への ingress、`RAKU_INTERNAL_AUTH_SECRET` 注入、SSM `did-map` 参照、
  `lambda:InvokeFunction` を Connect service principal(インスタンスARN条件)に許可。
- [x] L021 `infra/connect/contact-flow.json` — greeting→(開示)→ Lex 入力→ Lambda→ ai_action 分岐
  (answer/clarify→loop, handoff→queue transfer+属性に handoff_url, end_call→切断, error→定型案内)。
- [x] L022 `infra/connect/README.md` — Lex V2 ja-JP 最小 bot 作成手順(FallbackIntent のみ)、
  flow import、番号紐付け、CCP 受電テスト手順(runbook §4 と対応)。
- [x] L023 seed: demo テナントに電話サービスユーザー grant(`phone-gateway` → demo/manuals)を追加
  (stg の migrate-seed 経由で反映)。

## Phase 4: ブラウザ音声デモ(課金ゼロ)

- [x] L030 `/phone` シミュレータに音声モード: Web Speech API(ja-JP)で発話→既存 API、
  `speech_text` を speechSynthesis で読み上げ、認識開始で合成停止(擬似バージイン)、非対応時トグル無効。
- [x] L031 web typecheck / 手動確認(Chrome)。

## Phase 5: Gates & ship

- [x] L040 `scripts/gate.sh a` / `all` / separation、`npm run test:api`、web typecheck。
- [ ] L041 commit → PR → develop → stg(フラグ OFF、挙動不変)→ 外形確認。
- [x] L042 022 research.md Open Question #1 を解決済みに更新、checklist 該当項目チェック。

## Phase 6: 番号合流後(human-gated・番号到着待ち)

- [ ] L050 Connect インスタンス ARN を context に設定し `phoneTelephony=connect` でデプロイ。
- [ ] L051 Lex/Flow 取込み・番号紐付け(README 手順)。
- [ ] L052 実受電 E2E: 携帯→050→FAQ 音声回答→「人につないで」→CCP 受電→ `/phone` に履歴/転送表示。
- [ ] L053 障害注入(API 停止)で無音にならないこと(SC-L3)。
