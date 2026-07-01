# 0058 — ChatBot品質目標を数値化しrelease判断に組み込む(系統 = chatbot / quality-gate)

> Priority: **P1/High** / Status: Open / Labels: `chatbot`, `quality`, `eval`, `release-readiness`

## 実装メモ(2026-07-01)

- Scorecard output に `quick_reply_count` と `quick_reply_pass_rate` を追加した。
- v2 readiness thresholds に `quick_reply_pass_rate: 1.0` を追加し、代表 quick reply が根拠不足や
  unsupported follow-up に落ちる劣化を release readiness で検知できるようにした。
- `scripts/aws/run-chatbot-golden-from-stack.sh` を追加し、stg deploy 後に ALB URL 解決、Cognito token 発行、
  scorecard 実行を 1 コマンド化した。
- 実行には `RAKU_CHATBOT_SMOKE_APPROVED=yes` または `RAKU_PROD_SMOKE_APPROVED=yes` を要求し、
  token/password はログに出さない。

## 背景(なぜ今)

現状は 17問 smoke が 17/17 PASS している一方、v2品質テストは 7/37 PASS に留まる。
「今の quality で十分か」を判断するには、用途別の明確な閾値が必要。

## どんな課題か

- 期待挙動: UI smoke、stg smoke、demo-quality、paid-pilot readiness の各段階で合格基準が明確。
- 実際の挙動: 17問 smoke の PASS と「売れる品質」が混同されやすい。
- release/deploy 前後で v2 の悪化を見逃しやすい。

## どこで起きたか

- 画面: `/chatbot`
- API: `/v1/chat/sessions`
- コード: `scripts/demo/chatbot_golden_scenarios.py`, `scripts/demo/chatbot_quality_v2_scenarios.json`,
  `docs/production-readiness/chatbot-golden-scenarios.md`
- 環境: local, AWS stg
- run id / ingestion id / correlation id: 2026-06-30 stg v2 scorecard `/tmp/chatbot-v2-stg.json`
- 再現条件: `bash scripts/demo/chatbot_golden_scorecard.sh --dataset scripts/demo/chatbot_quality_v2_scenarios.json`

## 影響

- 営業デモへの影響: デモ可能/販売可能/有償PoC可能の線引きが曖昧になる。
- 本番クライアントへの影響: 品質説明や改善優先順位を合意しにくい。
- セキュリティ、監査、データ品質、UX への影響: security refusal と answer quality が同じ「失敗」として
  混ざると、誤った改善判断につながる。

## どう解決すべきか

1. 品質段階を定義する:
   - UI smoke: ログイン/参照範囲/送信/引用表示
   - stg smoke: 17/17 PASS
   - demo-quality: v2 30/37 以上
   - paid-pilot: expanded 120+ scenario で合意閾値 PASS
2. v2 readiness thresholds をドキュメント化し、scorecard JSON に固定する。
3. failure kind 別に blocker を分ける:
   - security/refusal は 100% 必須
   - clarification は 100% 必須
   - quick reply は代表 smoke set で 100% 必須
   - expected citation は 98%以上
   - completeness は 80%以上から開始
4. deploy後の任意チェックとして stg v2 scorecard 実行手順を runbook 化する。
5. CI hard gate には入れず、release readiness gate として扱う。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [x] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- docs に用途別合格基準が明記されている。
- scorecard output に release readiness 判定が出る。
- 17問 smoke と v2 quality の役割が分離されている。
- security/refusal/clarification/completeness/retrieval を別々に判断できる。

## スコープ外

- Tier A hard gate への v2組み込み。
- 有料providerや本番reindexの無承認実行。
- 品質未達を安全ルール緩和で解消すること。

## 参照

- `docs/production-readiness/chatbot-golden-scenarios.md`
- `docs/production-readiness/chatbot-sellable-quality-plan.md`
- `scripts/demo/chatbot_golden_scenarios.py`
- `scripts/demo/chatbot_quality_v2_scenarios.json`
- `issues/0051-chatbot-sellable-answer-quality-roadmap.md`
